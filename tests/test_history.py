"""Tests for robot/history.py: sizing and trimming the history, reading the
API's overflow and output-cap errors, stripping blocks the API will not take
back, the final report text, and repairing tool calls left without results."""

import ast
import copy
import random
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot import history
from robot.history import (estimate_content_tokens, final_assistant_text, parse_output_cap,
                           parse_overflow_counts, repair_tool_pairs,
                           strip_pre_fallback_blocks, strip_thinking_blocks,
                           trim_history_for_context)

DEFAULT_NOTE = "[Not run: the run was interrupted]"


def _round(user_text, big=200):
    """One round: a real user turn, a tool call, its result (a user message
    that does not open a round), and the reply."""
    return [
        {"role": "user", "content": user_text * big},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                           "name": "run_shell_command", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result",
                                      "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": "reply " + user_text},
    ]


def _use(call_id, as_object=False, name="run_shell_command"):
    block = {"type": "tool_use", "id": call_id, "name": name, "input": {}}
    return SimpleNamespace(**block) if as_object else block


def _result(call_id, content="ok", as_object=False):
    block = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    return SimpleNamespace(**block) if as_object else block


def _not_run(call_id, note=DEFAULT_NOTE):
    return {"type": "tool_result", "tool_use_id": call_id, "content": note, "is_error": True}


def _unanswered(messages):
    """What the API would reject: tool calls the next message does not answer,
    and results that do not come before everything else in their message."""
    problems = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, list):
            continue
        ids = [history._get(b, "id") for b in content if history._get(b, "type") == "tool_use"]
        if not ids:
            continue
        following = messages[index + 1] if index + 1 < len(messages) else {}
        answered, leading = set(), True
        blocks = following.get("content") if following.get("role") == "user" else None
        for block in blocks if isinstance(blocks, list) else []:
            if history._get(block, "type") == "tool_result":
                if not leading:
                    problems.append("result after other content")
                answered.add(history._get(block, "tool_use_id"))
            else:
                leading = False
        problems.extend(call_id for call_id in ids if call_id not in answered)
    return problems


class EstimateTokens(unittest.TestCase):
    def test_string_is_a_quarter_of_its_length(self):
        self.assertEqual(estimate_content_tokens("x" * 400), 100)

    def test_image_counts_a_flat_1600(self):
        content = [{"type": "image", "source": {"data": "A" * 500_000}}]
        self.assertEqual(estimate_content_tokens(content), 1600)

    def test_image_object_counts_the_same(self):
        content = [SimpleNamespace(type="image", source={"data": "A" * 500_000})]
        self.assertEqual(estimate_content_tokens(content), 1600)

    def test_mixed_blocks_sum(self):
        content = [{"type": "text", "text": "y" * 400},
                   {"type": "image", "source": {"data": "A" * 999}}]
        estimate = estimate_content_tokens(content)
        self.assertGreaterEqual(estimate, 1600 + 100)
        self.assertLess(estimate, 1600 + 200)  # only the text block's JSON overhead

    def test_object_blocks_are_sized_by_their_repr(self):
        block = SimpleNamespace(type="text", text="y" * 400)
        self.assertEqual(estimate_content_tokens([block]), len(str(block)) // 4)
        self.assertGreaterEqual(estimate_content_tokens([block]), 100)

    def test_content_that_is_neither_text_nor_a_list(self):
        self.assertEqual(estimate_content_tokens(None), len("None") // 4)
        self.assertEqual(estimate_content_tokens(12345678), 2)

    def test_a_block_json_cannot_write_is_sized_by_its_repr(self):
        odd_key = {"type": "text", ("a", "b"): "x" * 400}   # JSON keys cannot be tuples
        self.assertEqual(estimate_content_tokens([odd_key]), len(str(odd_key)) // 4)
        loop = {"type": "text"}
        loop["self"] = loop                                   # a circular reference
        self.assertEqual(estimate_content_tokens([loop]), len(str(loop)) // 4)

    def test_empty_content(self):
        self.assertEqual(estimate_content_tokens(""), 0)
        self.assertEqual(estimate_content_tokens([]), 0)


class ParseOverflowCounts(unittest.TestCase):
    def test_parses_the_overflow_message(self):
        self.assertEqual(
            parse_overflow_counts("prompt is too long: 1597842 tokens > 1000000 maximum"),
            (1597842, 1000000))

    def test_parses_comma_grouped_counts(self):
        self.assertEqual(
            parse_overflow_counts("prompt is too long: 1,597,842 tokens > 1,000,000 maximum"),
            (1597842, 1000000))

    def test_no_match_returns_nones(self):
        self.assertEqual(parse_overflow_counts("something else"), (None, None))
        self.assertEqual(parse_overflow_counts(""), (None, None))
        self.assertEqual(parse_overflow_counts(None), (None, None))

    def test_the_output_cap_message_is_not_an_overflow(self):
        message = ("max_tokens: 128000 > 64000, which is the maximum allowed number of "
                   "output tokens for claude-zeta-9")
        self.assertEqual(parse_overflow_counts(message), (None, None))


class ParseOutputCap(unittest.TestCase):
    OVER_CAP = ("max_tokens: 128000 > 64000, which is the maximum allowed number of "
                "output tokens for claude-zeta-9")

    def test_reads_the_ceiling_the_api_names(self):
        self.assertEqual(parse_output_cap(self.OVER_CAP), 64000)

    def test_reads_comma_grouped_counts(self):
        self.assertEqual(parse_output_cap(
            "max_tokens: 200,000 > 128,000, which is the maximum allowed number of "
            "output tokens for claude-fable-5-1"), 128000)

    def test_nothing_else_is_a_ceiling(self):
        for other in ("prompt is too long: 1,200 tokens > 1,000 maximum", "", None,
                      "max_tokens: 0 > 0, which is", "something else"):
            with self.subTest(message=other):
                self.assertIsNone(parse_output_cap(other))

    def test_a_lower_cased_message_still_parses(self):
        # The caller matches on the lower-cased error text.
        self.assertEqual(parse_output_cap(self.OVER_CAP.lower()), 64000)
        self.assertEqual(
            parse_overflow_counts("Prompt is too long: 12 tokens > 7 maximum".lower()), (12, 7))


class TrimHistory(unittest.TestCase):
    def test_two_rounds_or_fewer_cannot_be_trimmed(self):
        messages = _round("a") + _round("b")
        before = list(messages)
        self.assertEqual(trim_history_for_context(messages, 999_999, 100), 0)
        self.assertEqual(messages, before)

    def test_first_kept_message_is_a_real_user_turn(self):
        messages = _round("a") + _round("b") + _round("c") + _round("d")
        removed = trim_history_for_context(messages)   # sizes unknown: the oldest half goes
        self.assertGreater(removed, 0)
        self.assertEqual(messages[0]["role"], "user")
        self.assertIsInstance(messages[0]["content"], str)   # not a message of tool results

    def test_never_leaves_a_result_without_its_call(self):
        messages = _round("a") + _round("b") + _round("c") + _round("d")
        trim_history_for_context(messages, 100_000, 50_000)
        seen_calls = set()
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    seen_calls.add(block["id"])
                elif block.get("type") == "tool_result":
                    self.assertIn(block["tool_use_id"], seen_calls)

    def test_always_keeps_the_last_two_rounds(self):
        messages = _round("a") + _round("b") + _round("c") + _round("d")
        tail = list(messages[-8:])
        trim_history_for_context(messages, 10_000_000, 1_000)   # asks for far more than exists
        self.assertGreaterEqual(len(messages), 8)
        self.assertEqual(messages[-8:], tail)

    def test_small_overflow_drops_only_the_oldest_round(self):
        messages = _round("a") + _round("b") + _round("c") + _round("d")
        removed = trim_history_for_context(messages, 101, 100)
        self.assertEqual(removed, 4)
        self.assertEqual(len(messages), 12)

    def test_returns_the_number_of_messages_removed(self):
        messages = _round("a") + _round("b") + _round("c") + _round("d")
        before = len(messages)
        removed = trim_history_for_context(messages)
        self.assertEqual(removed, before - len(messages))

    def test_unknown_sizes_drop_the_oldest_half(self):
        messages = sum((_round(letter) for letter in "abcdef"), [])
        self.assertEqual(trim_history_for_context(messages), 12)   # three of six rounds
        self.assertEqual(messages[0]["content"], "d" * 200)

    def test_known_sizes_drop_as_many_rounds_as_needed(self):
        one_round = sum(estimate_content_tokens(m["content"]) for m in _round("a", big=4000))
        messages = sum((_round(letter, big=4000) for letter in "abcdef"), [])
        maximum = 4000
        # Aim: three quarters of the maximum. Two and a half rounds over it
        # means three whole rounds have to go.
        reported = int(maximum * 0.75) + int(2.5 * one_round)
        self.assertEqual(trim_history_for_context(messages, reported, maximum), 12)
        self.assertEqual(messages[0]["content"], "d" * 4000)

    def test_counts_that_do_not_show_an_overflow_fall_back_to_halving(self):
        for reported, maximum in ((50, 100), (100, 100), (500, None), (None, 100), (0, 0)):
            with self.subTest(reported=reported, maximum=maximum):
                messages = sum((_round(letter) for letter in "abcdef"), [])
                self.assertEqual(trim_history_for_context(messages, reported, maximum), 12)

    def test_results_held_as_objects_do_not_open_a_round(self):
        messages = []
        for letter in "abcd":
            messages += [
                {"role": "user", "content": letter * 200},
                {"role": "assistant", "content": [_use("t1", as_object=True)]},
                {"role": "user", "content": [_result("t1", as_object=True)]},
                {"role": "assistant", "content": "reply"},
            ]
        self.assertEqual(trim_history_for_context(messages), 8)
        self.assertEqual(messages[0]["content"], "c" * 200)

    def test_a_user_message_of_text_blocks_opens_a_round(self):
        messages = []
        for letter in "abcd":
            messages += [{"role": "user", "content": [{"type": "text", "text": letter}]},
                         {"role": "assistant", "content": "reply"}]
        self.assertEqual(trim_history_for_context(messages), 4)
        self.assertEqual(messages[0]["content"], [{"type": "text", "text": "c"}])

    def test_an_empty_content_list_opens_a_round(self):
        messages = []
        for _ in range(4):
            messages += [{"role": "user", "content": []}, {"role": "assistant", "content": "r"}]
        self.assertEqual(trim_history_for_context(messages), 4)

    def test_results_followed_by_text_do_not_open_a_round(self):
        # The shape repair_tool_pairs leaves: results first, then what was typed.
        messages = []
        for letter in "abcd":
            messages += [
                {"role": "user", "content": letter * 200},
                {"role": "assistant", "content": [_use("t1")]},
                {"role": "user", "content": [_not_run("t1"), {"type": "text", "text": "next"}]},
                {"role": "assistant", "content": "reply"},
            ]
        self.assertEqual(trim_history_for_context(messages), 8)
        self.assertEqual(messages[0]["content"], "c" * 200)

    def test_a_result_anywhere_in_a_message_keeps_it_from_opening_a_round(self):
        messages = []
        for letter in "abcd":
            messages += [
                {"role": "user", "content": letter * 200},
                {"role": "assistant", "content": [_use("t1")]},
                {"role": "user", "content": [{"type": "text", "text": "note"}, _result("t1")]},
                {"role": "assistant", "content": "reply"},
            ]
        # A small overflow drops one round. If the message with the result
        # counted as a round's start, the cut would land on it (after two
        # messages) and leave that result without its call.
        self.assertEqual(trim_history_for_context(messages, 101, 100), 4)
        self.assertEqual(messages[0]["content"], "b" * 200)

    def test_a_history_that_starts_mid_round(self):
        messages = [{"role": "assistant", "content": "left over"}]
        messages += _round("a") + _round("b") + _round("c") + _round("d")
        self.assertEqual(trim_history_for_context(messages), 9)
        self.assertEqual(messages[0]["content"], "c" * 200)

    def test_an_empty_history(self):
        messages = []
        self.assertEqual(trim_history_for_context(messages, 10, 5), 0)
        self.assertEqual(messages, [])


def _thinking(signature="sig"):
    return {"type": "thinking", "thinking": "...", "signature": signature}


class StripThinking(unittest.TestCase):
    def test_strips_dict_and_object_blocks_in_place(self):
        object_thinking = SimpleNamespace(type="thinking", thinking="x", signature="y")
        object_text = SimpleNamespace(type="text", text="hi")
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": [_thinking(), {"type": "text", "text": "a"}]},
            {"role": "user", "content": [_result("t", "r")]},
            {"role": "assistant", "content": [object_thinking,
                                              {"type": "redacted_thinking", "data": "z"},
                                              object_text]},
            {"role": "assistant", "content": "plain string turn"},
        ]
        self.assertEqual(strip_thinking_blocks(messages), 3)
        self.assertEqual(messages[1]["content"], [{"type": "text", "text": "a"}])
        self.assertEqual(messages[3]["content"], [object_text])
        self.assertEqual(messages[2]["content"][0]["type"], "tool_result")   # user turn untouched
        self.assertEqual(messages[4]["content"], "plain string turn")

    def test_nothing_to_strip(self):
        messages = [{"role": "assistant", "content": [{"type": "text", "text": "a"}]}]
        self.assertEqual(strip_thinking_blocks(messages), 0)

    def test_never_empties_a_turn(self):
        # An assistant turn with no content would itself be rejected.
        messages = [{"role": "assistant", "content": [_thinking()]}]
        self.assertEqual(strip_thinking_blocks(messages), 0)
        self.assertEqual(len(messages[0]["content"]), 1)

    def test_keeps_tool_calls_beside_the_thinking(self):
        call = _use("t1", as_object=True)
        messages = [{"role": "assistant", "content": [_thinking(), call]},
                    {"role": "user", "content": [_result("t1")]}]
        self.assertEqual(strip_thinking_blocks(messages), 1)
        self.assertEqual(messages[0]["content"], [call])

    def test_only_assistant_turns_are_touched(self):
        user_blocks = [_thinking(), {"type": "text", "text": "quoted"}]
        messages = [{"role": "user", "content": user_blocks}, "not a message"]
        self.assertEqual(strip_thinking_blocks(messages), 0)
        self.assertEqual(len(user_blocks), 2)


def _fallback(declined="claude-fable-5-1", serving="claude-opus-5"):
    return {"type": "fallback", "from": {"model": declined}, "to": {"model": serving}}


class StripPreFallback(unittest.TestCase):
    def test_no_fallback_returns_the_same_list(self):
        blocks = [{"type": "text", "text": "a"}, _use("t1")]
        self.assertIs(strip_pre_fallback_blocks(blocks), blocks)

    def test_decline_before_any_output_drops_only_the_marker(self):
        tail = [{"type": "thinking", "thinking": "", "signature": "s"}, _use("t1")]
        self.assertEqual(strip_pre_fallback_blocks([_fallback()] + tail), tail)

    def test_decline_part_way_keeps_text_and_paired_server_tools_only(self):
        before = [
            {"type": "thinking", "thinking": "plan", "signature": "s1"},
            {"type": "text", "text": "Partial answer"},
            {"type": "server_tool_use", "id": "srv1", "name": "web_search", "input": {}},
            {"type": "web_search_tool_result", "tool_use_id": "srv1", "content": []},
            {"type": "server_tool_use", "id": "srv2", "name": "web_search", "input": {}},
            _use("t1"),
        ]
        after = [{"type": "thinking", "thinking": "", "signature": "s2"}, _use("t2")]
        kept = strip_pre_fallback_blocks(before + [_fallback()] + after)
        # The text and the paired search survive. The thinking, the search
        # without a result and the declined model's tool call do not.
        self.assertEqual(kept, [before[1], before[2], before[3]] + after)

    def test_the_last_marker_is_the_boundary(self):
        blocks = [{"type": "text", "text": "one"}, _fallback(), _use("a"),
                  _fallback("claude-opus-5", "claude-opus-4-8"),
                  {"type": "text", "text": "final"}]
        self.assertEqual(strip_pre_fallback_blocks(blocks),
                         [{"type": "text", "text": "one"}, {"type": "text", "text": "final"}])

    def test_object_blocks(self):
        marker = SimpleNamespace(type="fallback")
        declined_call = SimpleNamespace(type="tool_use", id="t1", name="x", input={})
        served_text = SimpleNamespace(type="text", text="served")
        self.assertEqual(strip_pre_fallback_blocks([declined_call, marker, served_text]),
                         [served_text])

    def test_a_result_whose_search_was_dropped_goes_too(self):
        blocks = [{"type": "web_search_tool_result", "tool_use_id": "gone", "content": []},
                  _fallback(), {"type": "text", "text": "served"}]
        self.assertEqual(strip_pre_fallback_blocks(blocks), [{"type": "text", "text": "served"}])

    def test_the_input_list_is_not_changed(self):
        blocks = [_use("t1"), _fallback(), {"type": "text", "text": "served"}]
        before = list(blocks)
        strip_pre_fallback_blocks(blocks)
        self.assertEqual(blocks, before)


class FinalAssistantText(unittest.TestCase):
    def test_plain_string_content(self):
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "the report"}]
        self.assertEqual(final_assistant_text(messages), "the report")

    def test_skips_trailing_user_messages(self):
        messages = [{"role": "assistant", "content": "answer"},
                    {"role": "user", "content": [_result("t")]}]
        self.assertEqual(final_assistant_text(messages), "answer")

    def test_the_last_assistant_message_is_the_report(self):
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "user", "content": "and then?"},
                    {"role": "assistant", "content": [{"type": "text", "text": "second answer"}]}]
        self.assertEqual(final_assistant_text(messages), "second answer")

    def test_joins_text_blocks_and_ignores_tool_calls(self):
        messages = [{"role": "assistant", "content": [
            {"type": "text", "text": "part one"},
            _use("t"),
            {"type": "text", "text": "part two"},
        ]}]
        self.assertEqual(final_assistant_text(messages), "part one\npart two")

    def test_object_blocks(self):
        block = SimpleNamespace(type="text", text="sdk text")
        self.assertEqual(final_assistant_text([{"role": "assistant", "content": [block]}]),
                         "sdk text")

    def test_dict_and_object_blocks_together(self):
        messages = [{"role": "assistant", "content": [
            SimpleNamespace(type="thinking", thinking="hm", signature="s"),
            SimpleNamespace(type="text", text="first"),
            {"type": "text", "text": "second"},
            SimpleNamespace(type="text", text=""),
        ]}]
        self.assertEqual(final_assistant_text(messages), "first\nsecond")

    def test_skips_an_empty_assistant_turn_and_falls_back(self):
        messages = [{"role": "assistant", "content": "earlier real answer"},
                    {"role": "assistant", "content": "   "}]
        self.assertEqual(final_assistant_text(messages), "earlier real answer")

    def test_skips_a_turn_of_tool_calls_only(self):
        messages = [{"role": "assistant", "content": "the last thing said"},
                    {"role": "assistant", "content": [_use("t", as_object=True)]},
                    {"role": "user", "content": [_result("t")]}]
        self.assertEqual(final_assistant_text(messages), "the last thing said")

    def test_no_assistant_message_gives_empty_text(self):
        self.assertEqual(final_assistant_text([{"role": "user", "content": "only"}]), "")
        self.assertEqual(final_assistant_text([]), "")


class RepairToolPairs(unittest.TestCase):
    def test_a_complete_history_is_left_alone(self):
        messages = _round("a") + _round("b")
        before = copy.deepcopy(messages)
        self.assertEqual(repair_tool_pairs(messages), 0)
        self.assertEqual(messages, before)

    def test_an_empty_history(self):
        messages = []
        self.assertEqual(repair_tool_pairs(messages), 0)
        self.assertEqual(messages, [])

    def test_a_call_at_the_end_gets_a_new_user_message(self):
        messages = [{"role": "user", "content": "go"},
                    {"role": "assistant", "content": [{"type": "text", "text": "running"},
                                                      _use("t1")]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[2], {"role": "user", "content": [_not_run("t1")]})

    def test_the_result_is_an_error_result_with_the_default_note(self):
        messages = [{"role": "assistant", "content": [_use("t1")]}]
        repair_tool_pairs(messages)
        self.assertEqual(messages[1]["content"], [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "[Not run: the run was interrupted]", "is_error": True}])

    def test_a_custom_note(self):
        messages = [{"role": "assistant", "content": [_use("t1")]}]
        self.assertEqual(repair_tool_pairs(messages, note="[Not run: stopped]"), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1", "[Not run: stopped]")])

    def test_calls_held_as_objects(self):
        messages = [{"role": "user", "content": "go"},
                    {"role": "assistant", "content": [
                        SimpleNamespace(type="thinking", thinking="", signature="s"),
                        SimpleNamespace(type="text", text="running"),
                        _use("t1", as_object=True), _use("t2", as_object=True)]}]
        self.assertEqual(repair_tool_pairs(messages), 2)
        self.assertEqual(messages[2], {"role": "user",
                                       "content": [_not_run("t1"), _not_run("t2")]})

    def test_results_follow_the_order_of_the_calls(self):
        messages = [{"role": "assistant", "content": [_use("b"), _use("a"), _use("c")]}]
        repair_tool_pairs(messages)
        self.assertEqual([block["tool_use_id"] for block in messages[1]["content"]],
                         ["b", "a", "c"])

    def test_text_typed_next_becomes_a_text_block_after_the_results(self):
        messages = [{"role": "assistant", "content": [_use("t1"), _use("t2")]},
                    {"role": "user", "content": "never mind, what time is it?"}]
        self.assertEqual(repair_tool_pairs(messages), 2)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1], {"role": "user", "content": [
            _not_run("t1"), _not_run("t2"),
            {"type": "text", "text": "never mind, what time is it?"}]})

    def test_blank_text_is_dropped_rather_than_sent_as_an_empty_block(self):
        for blank in ("", "   \n"):
            with self.subTest(blank=blank):
                messages = [{"role": "assistant", "content": [_use("t1")]},
                            {"role": "user", "content": blank}]
                self.assertEqual(repair_tool_pairs(messages), 1)
                self.assertEqual(messages[1]["content"], [_not_run("t1")])

    def test_missing_results_go_in_front_of_the_ones_already_there(self):
        done = _result("t2", "finished")
        content = [done]
        messages = [{"role": "assistant", "content": [_use("t1"), _use("t2"), _use("t3")]},
                    {"role": "user", "content": content}]
        self.assertEqual(repair_tool_pairs(messages), 2)
        self.assertEqual(messages[1]["content"], [_not_run("t1"), _not_run("t3"), done])
        self.assertIs(messages[1]["content"], content)      # the same list, changed in place
        self.assertIs(messages[1]["content"][2], done)      # the real result is untouched

    def test_results_held_as_objects_count_as_answers(self):
        done = _result("t1", "finished", as_object=True)
        messages = [{"role": "assistant", "content": [_use("t1", as_object=True), _use("t2")]},
                    {"role": "user", "content": [done]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t2"), done])

    def test_results_go_before_text_blocks(self):
        text = {"type": "text", "text": "carry on"}
        messages = [{"role": "assistant", "content": [_use("t1")]},
                    {"role": "user", "content": [text]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1"), text])

    def test_results_for_other_calls_do_not_count(self):
        stray = _result("zz", "from somewhere else")
        messages = [{"role": "assistant", "content": [_use("t1")]},
                    {"role": "user", "content": [stray]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1"), stray])

    def test_a_following_assistant_message_gets_a_user_message_put_before_it(self):
        messages = [{"role": "user", "content": "go"},
                    {"role": "assistant", "content": [_use("t1")]},
                    {"role": "assistant", "content": "something else"}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual(messages[2]["content"], [_not_run("t1")])
        self.assertEqual(messages[3]["content"], "something else")

    def test_every_broken_turn_is_repaired(self):
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": [_use("a")]},                 # nothing follows it
            {"role": "assistant", "content": [_use("b"), _use("c")]},
            {"role": "user", "content": [_result("c")]},                   # b is missing
            {"role": "assistant", "content": [_use("d")]},
            {"role": "user", "content": [_result("d")]},                   # complete
            {"role": "assistant", "content": [_use("e", as_object=True)]},
            {"role": "user", "content": "typed after an interruption"},
        ]
        self.assertEqual(repair_tool_pairs(messages), 3)
        self.assertEqual(_unanswered(messages), [])
        self.assertEqual([m["role"] for m in messages],
                         ["user", "assistant", "user", "assistant", "user", "assistant",
                          "user", "assistant", "user"])
        self.assertEqual(messages[2]["content"], [_not_run("a")])
        self.assertEqual(messages[4]["content"], [_not_run("b"), _result("c")])
        self.assertEqual(messages[6]["content"], [_result("d")])
        self.assertEqual(messages[8]["content"], [
            _not_run("e"), {"type": "text", "text": "typed after an interruption"}])

    def test_server_tool_calls_need_no_result(self):
        for as_object in (False, True):
            with self.subTest(as_object=as_object):
                search = {"type": "server_tool_use", "id": "srv1", "name": "web_search",
                          "input": {"query": "weather"}}
                if as_object:
                    search = SimpleNamespace(**search)
                messages = [{"role": "user", "content": "go"},
                            {"role": "assistant", "content": [search]}]
                before = list(messages)
                self.assertEqual(repair_tool_pairs(messages), 0)
                self.assertEqual(messages, before)

    def test_only_the_client_call_of_a_mixed_turn_gets_a_result(self):
        messages = [{"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srv1", "name": "web_search", "input": {}},
            {"type": "web_search_tool_result", "tool_use_id": "srv1", "content": []},
            _use("t1"),
        ]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1")])

    def test_a_string_assistant_turn_has_no_calls(self):
        messages = [{"role": "assistant", "content": "tool_use t1 (just text)"},
                    {"role": "user", "content": "ok"}]
        before = copy.deepcopy(messages)
        self.assertEqual(repair_tool_pairs(messages), 0)
        self.assertEqual(messages, before)

    def test_a_repeated_id_gets_one_result(self):
        messages = [{"role": "assistant", "content": [_use("t1"), _use("t1")]}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1")])

    def test_a_call_without_an_id_is_skipped(self):
        messages = [{"role": "assistant", "content": [
            {"type": "tool_use", "name": "x", "input": {}},
            SimpleNamespace(type="tool_use", id=None, name="x", input={})]}]
        self.assertEqual(repair_tool_pairs(messages), 0)
        self.assertEqual(len(messages), 1)

    def test_user_content_that_is_missing_or_a_tuple(self):
        messages = [{"role": "assistant", "content": [_use("t1")]},
                    {"role": "user", "content": None}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1")])

        text = {"type": "text", "text": "hello"}
        messages = [{"role": "assistant", "content": [_use("t1")]},
                    {"role": "user", "content": (text,)}]
        self.assertEqual(repair_tool_pairs(messages), 1)
        self.assertEqual(messages[1]["content"], [_not_run("t1"), text])

    def test_other_fields_of_the_user_message_are_kept(self):
        messages = [{"role": "assistant", "content": [_use("t1")]},
                    {"role": "user", "content": "hello", "extra": 1}]
        repair_tool_pairs(messages)
        self.assertEqual(messages[1]["extra"], 1)
        self.assertEqual(messages[1]["role"], "user")

    def test_the_assistant_turn_itself_is_never_changed(self):
        call = _use("t1", as_object=True)
        content = [SimpleNamespace(type="text", text="running"), call]
        messages = [{"role": "assistant", "content": content}]
        repair_tool_pairs(messages)
        self.assertIs(messages[0]["content"], content)
        self.assertEqual(len(content), 2)
        self.assertIs(content[1], call)

    def test_repairing_twice_adds_nothing_more(self):
        messages = [{"role": "assistant", "content": [_use("t1"), _use("t2")]},
                    {"role": "user", "content": "next"},
                    {"role": "assistant", "content": [_use("t3")]}]
        self.assertEqual(repair_tool_pairs(messages), 3)
        after_first = copy.deepcopy(messages)
        self.assertEqual(repair_tool_pairs(messages), 0)
        self.assertEqual(messages, after_first)

    def test_each_result_is_its_own_dict(self):
        messages = [{"role": "assistant", "content": [_use("t1"), _use("t2")]}]
        repair_tool_pairs(messages)
        first, second = messages[1]["content"]
        self.assertIsNot(first, second)
        first["content"] = "changed"
        self.assertEqual(second["content"], DEFAULT_NOTE)

    def test_a_repaired_message_does_not_become_a_cut_point(self):
        # After a repair the user message starts with results, so trimming
        # must not treat it as the start of a round.
        messages = []
        for letter in "abcd":
            messages += [{"role": "user", "content": letter * 200},
                         {"role": "assistant", "content": [_use("t1")]},
                         {"role": "user", "content": "typed after an interruption"},
                         {"role": "assistant", "content": "reply"}]
        self.assertEqual(repair_tool_pairs(messages), 4)
        self.assertEqual(trim_history_for_context(messages), 8)
        self.assertEqual(messages[0]["content"], "c" * 200)
        self.assertEqual(_unanswered(messages), [])

    def test_random_interrupted_histories_always_come_out_valid(self):
        rng = random.Random(7)
        for case in range(400):
            messages, next_id = [], 0
            for _ in range(rng.randint(1, 6)):
                messages.append({"role": "user", "content": "ask"})
                for _ in range(rng.randint(0, 3)):
                    ids = [f"t{next_id + n}" for n in range(rng.randint(1, 3))]
                    next_id += len(ids)
                    calls = [_use(call_id, as_object=rng.random() < 0.5) for call_id in ids]
                    lead = [SimpleNamespace(type="text", text="x")] if rng.random() < 0.5 else []
                    messages.append({"role": "assistant", "content": lead + calls})
                    kept = [call_id for call_id in ids if rng.random() < 0.6]
                    shape = rng.random()
                    if shape < 0.5:
                        results = [_result(call_id, as_object=rng.random() < 0.3)
                                   for call_id in kept]
                        if results or rng.random() < 0.5:
                            messages.append({"role": "user", "content": results})
                    elif shape < 0.75:
                        messages.append({"role": "user", "content": rng.choice(["next", "", " "])})
                    # otherwise nothing follows the call at all
                if rng.random() < 0.7:
                    messages.append({"role": "assistant", "content": "done"})
            before = copy.deepcopy(messages)
            broken = len(_unanswered(before))
            added = repair_tool_pairs(messages)
            with self.subTest(case=case):
                self.assertEqual(_unanswered(messages), [])
                self.assertEqual(added, broken)
                results_before = sum(1 for m in before if isinstance(m["content"], list)
                                     for b in m["content"]
                                     if history._get(b, "type") == "tool_result")
                results_after = sum(1 for m in messages if isinstance(m["content"], list)
                                    for b in m["content"]
                                    if history._get(b, "type") == "tool_result")
                self.assertEqual(results_after - results_before, added)
                self.assertEqual(repair_tool_pairs(messages), 0)


class ModuleRules(unittest.TestCase):
    SOURCE = Path(history.__file__).read_text(encoding="utf-8")

    def test_only_the_standard_library_is_imported(self):
        imported = set()
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"json", "re"})

    def test_the_source_is_plain_ascii(self):
        self.assertTrue(self.SOURCE.isascii())

    def test_public_names(self):
        for name in ("estimate_content_tokens", "strip_thinking_blocks",
                     "strip_pre_fallback_blocks", "parse_overflow_counts", "parse_output_cap",
                     "trim_history_for_context", "final_assistant_text", "repair_tool_pairs"):
            self.assertTrue(callable(getattr(history, name)), name)


if __name__ == "__main__":
    unittest.main()
