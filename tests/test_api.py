"""The request builder and the retry ladder, with a scripted fake client."""

import unittest

from robot import api
from robot.api import Learned, build_request, cache_messages, cache_system, call_model
from tests.fakes import (FakeClient, InterruptDuring, NoWaitInterrupts, Obj, bad_request,
                         connection_error, piped_console, rate_limited, reply, status_error,
                         text_block, thinking_block, tool_use, usage)

TOOLS = [{"name": "user_prompt", "description": "ask", "input_schema": {"type": "object"}}]


def build(model="claude-opus-5-5", **overrides):
    args = dict(model=model, system_prompt="You are a robot.",
                messages=[{"role": "user", "content": "hi"}], client_tools=TOOLS)
    args.update(overrides)
    return build_request(**args)


class CacheMarkers(unittest.TestCase):
    def test_the_system_prompt_is_one_cached_block(self):
        self.assertEqual(cache_system("be brief"),
                         [{"type": "text", "text": "be brief",
                           "cache_control": {"type": "ephemeral"}}])

    def test_an_empty_system_prompt_stays_a_plain_string(self):
        self.assertEqual(cache_system(""), "")

    def test_the_two_newest_user_turns_are_marked(self):
        messages = [{"role": "user", "content": "one"},
                    {"role": "assistant", "content": [text_block("a")]},
                    {"role": "user", "content": "two"},
                    {"role": "assistant", "content": [text_block("b")]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                                  "content": "r"}]}]
        wire = cache_messages(messages)
        self.assertEqual(wire[0], messages[0])  # the oldest is left alone
        self.assertIn("cache_control", wire[2]["content"][0])
        self.assertIn("cache_control", wire[4]["content"][-1])
        self.assertEqual(wire[4]["content"][-1]["tool_use_id"], "t")

    def test_the_history_itself_is_never_changed(self):
        results = [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]
        messages = [{"role": "user", "content": "one"}, {"role": "user", "content": results}]
        cache_messages(messages)
        self.assertEqual(messages[0]["content"], "one")
        self.assertNotIn("cache_control", results[0])

    def test_empty_and_assistant_turns_are_skipped(self):
        messages = [{"role": "user", "content": "one"}, {"role": "user", "content": ""},
                    {"role": "assistant", "content": [text_block("a")]}]
        wire = cache_messages(messages)
        self.assertIn("cache_control", wire[0]["content"][0])
        self.assertEqual(wire[1]["content"], "")
        self.assertIs(wire[2], messages[2])


class RequestShape(unittest.TestCase):
    def test_an_always_on_model_at_a_level(self):
        kwargs, betas, info = build(thinking_mode="high")
        self.assertEqual(kwargs["thinking"], {
            "type": "adaptive", "display": "summarized",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"}})
        self.assertEqual(kwargs["output_config"], {"effort": "high"})
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["max_tokens"], 128000)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("speed", kwargs)
        self.assertEqual(sorted(betas), ["server-side-fallback-2026-07-01",
                                         "thinking-binding-controls-2026-08-01"])
        self.assertEqual(info, {"fast": False, "fallbacks": True, "block_binding": True})

    def test_adaptive_sends_no_effort(self):
        kwargs, _, _ = build(thinking_mode="adaptive")
        self.assertNotIn("output_config", kwargs)

    def test_off_on_an_always_on_model_is_sent_as_plain_adaptive(self):
        kwargs, _, _ = build(thinking_mode="off")
        self.assertEqual(kwargs["thinking"]["type"], "adaptive")
        self.assertNotIn("output_config", kwargs)

    def test_off_on_a_model_that_thinks_by_default_is_an_explicit_disable(self):
        kwargs, betas, info = build(model="claude-opus-5", thinking_mode="off")
        self.assertEqual(kwargs["thinking"], {"type": "disabled"})
        self.assertNotIn("thinking-binding-controls-2026-08-01", betas)
        self.assertFalse(info["block_binding"])

    def test_sonnet_55_has_its_own_spelling_of_off(self):
        kwargs, betas, _ = build(model="claude-sonnet-5-5", thinking_mode="off")
        self.assertEqual(kwargs["thinking"], {"type": "between_tools"})
        self.assertNotIn("thinking-binding-controls-2026-08-01", betas)
        self.assertEqual(kwargs["fallbacks"], "default")

    def test_a_manual_budget_model(self):
        kwargs, betas, _ = build(model="claude-haiku-4-5-20251001", thinking_mode="high",
                                 thinking_budget=4096)
        self.assertEqual(kwargs["thinking"], {"type": "enabled", "budget_tokens": 4096})
        self.assertNotIn("fallbacks", kwargs)
        self.assertEqual(betas, [])
        self.assertEqual(kwargs["tools"][-1]["type"], "web_search_20250305")

    def test_fast_mode_only_where_the_model_has_it(self):
        kwargs, betas, info = build(fast_mode=True)
        self.assertEqual(kwargs["speed"], "fast")
        self.assertIn("fast-mode-2026-02-01", betas)
        self.assertTrue(info["fast"])
        kwargs, betas, info = build(model="claude-sonnet-5-5", fast_mode=True)
        self.assertNotIn("speed", kwargs)
        self.assertFalse(info["fast"])

    def test_learned_off_features_are_not_sent(self):
        learned = Learned(unsupported={"speed", "fallbacks", "block_binding",
                                       "server_tools_20260209"},
                          output_caps={"claude-opus-5-5": 64000})
        kwargs, betas, info = build(fast_mode=True, learned=learned)
        self.assertNotIn("speed", kwargs)
        self.assertNotIn("fallbacks", kwargs)
        self.assertNotIn("block_binding", kwargs["thinking"])
        self.assertEqual(kwargs["max_tokens"], 64000)
        self.assertEqual(kwargs["tools"][-1]["type"], "web_search_20250305")
        self.assertEqual(betas, [])
        self.assertEqual(info, {"fast": False, "fallbacks": False, "block_binding": False})

    def test_web_search_can_be_left_out(self):
        kwargs, _, _ = build(web_search=False)
        self.assertEqual([tool["name"] for tool in kwargs["tools"]], ["user_prompt"])
        kwargs, _, _ = build()
        self.assertEqual(kwargs["tools"][-1],
                         {"type": "web_search_20260209", "name": "web_search", "max_uses": 5})

    def test_the_request_can_be_described_as_json(self):
        kwargs, betas, _ = build(messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [thinking_block("hmm"), text_block("hello")]}])
        shown = api.describe_request(kwargs, betas)
        self.assertIn('"model": "claude-opus-5-5"', shown)
        self.assertIn('"hello"', shown)
        self.assertIn("thinking-binding-controls-2026-08-01", shown)


class Ladder(unittest.TestCase):
    def setUp(self):
        self.console, self.out = piped_console("")
        self.interrupts = self.console.interrupts
        self.learned = Learned()
        self.messages = [{"role": "user", "content": "hi"}]

    def call(self, script, **overrides):
        self.client = FakeClient(script)
        args = dict(model="claude-opus-5-5", system_prompt="You are a robot.",
                    messages=self.messages, client_tools=TOOLS, thinking_mode="low",
                    learned=self.learned)
        args.update(overrides)
        return call_model(self.client, self.console, self.interrupts, **args)

    def shown(self):
        return self.out.getvalue()

    def test_a_successful_call_returns_text_blocks_and_usage(self):
        result = self.call([reply(thinking_block(), text_block("Hello."),
                                  usage_=usage(120, 30, 400, 50, searches=2))])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.text, "Hello.")
        self.assertEqual(len(result.content), 2)
        self.assertFalse(result.interrupted)
        self.assertEqual(result.usage, {
            "input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": 400,
            "cache_read_input_tokens": 50, "model": "claude-opus-5-5", "speed": None,
            "web_search_requests": 2})

    def test_thinking_is_shown_only_when_asked_for(self):
        self.call([reply(thinking_block("deep thought"), text_block("Hi."))])
        self.assertNotIn("deep thought", self.shown())
        self.console, self.out = piped_console("", show_thinking=True)
        self.interrupts = self.console.interrupts
        self.call([reply(thinking_block("deep thought"), text_block("Hi."))])
        self.assertIn("[thinking] deep thought", self.shown())

    def test_a_web_search_shows_its_query(self):
        self.call([reply(Obj(type="server_tool_use", name="web_search",
                             input={"query": "sydney weather"}, id="s1"),
                         text_block("Rain."))])
        self.assertIn("[tool: web_search: sydney weather]", self.shown())

    def test_rate_limits_back_off_and_retry(self):
        result = self.call([rate_limited(), rate_limited(), reply(text_block("ok"))])
        self.assertEqual(result.text, "ok")
        self.assertEqual(self.interrupts.waits, [5, 10])
        self.assertIn("Rate limited - retrying in 5s (attempt 1/10)", self.shown())

    def test_the_last_attempt_raises(self):
        with self.assertRaises(Exception) as caught:
            self.call([rate_limited()] * 3, max_retries=3)
        self.assertEqual(type(caught.exception).__name__, "RateLimitError")
        self.assertEqual(self.interrupts.waits, [5, 10])

    def test_overload_and_connection_errors_wait_and_retry(self):
        result = self.call([status_error(529, "Overloaded"), connection_error(),
                            reply(text_block("ok"))])
        self.assertEqual(result.text, "ok")
        self.assertEqual(self.interrupts.waits, [10, 10])
        self.assertIn("API overloaded - retrying in 10s", self.shown())
        self.assertIn("Connection error. - retrying in 10s", self.shown())

    def test_other_server_errors_are_not_retried(self):
        with self.assertRaises(Exception):
            self.call([status_error(500, "boom"), reply(text_block("never"))])
        self.assertEqual(self.client.remaining, 1)

    def test_an_unrecognised_bad_request_is_raised(self):
        with self.assertRaises(Exception) as caught:
            self.call([bad_request("tools.0.name: invalid")])
        self.assertEqual(type(caught.exception).__name__, "BadRequestError")

    def test_a_fast_mode_limit_of_zero_turns_fast_mode_off_for_good(self):
        refusal = rate_limited("This request would exceed the rate limit of 0 fast mode "
                               "input tokens per minute")
        result = self.call([refusal, reply(text_block("ok"))], fast_mode=True)
        self.assertEqual(result.text, "ok")
        self.assertIn("speed", self.learned.unsupported)
        self.assertEqual(self.client.requests[0]["speed"], "fast")
        self.assertNotIn("speed", self.client.requests[1])
        self.assertEqual(self.interrupts.waits, [])

    def test_a_busy_fast_mode_drops_only_this_call_to_standard_speed(self):
        result = self.call([rate_limited("fast mode rate limit reached"),
                            reply(text_block("ok"))], fast_mode=True)
        self.assertEqual(result.text, "ok")
        self.assertNotIn("speed", self.learned.unsupported)
        self.assertNotIn("speed", self.client.requests[1])
        self.assertIsNone(result.usage["speed"])

    def test_a_refused_speed_parameter_is_learned_off(self):
        self.call([bad_request("speed: fast is not supported for this model"),
                   reply(text_block("ok"))], fast_mode=True)
        self.assertIn("speed", self.learned.unsupported)
        self.assertNotIn("speed", self.client.requests[1])

    def test_refused_fallbacks_are_learned_off(self):
        self.call([bad_request("fallbacks: Extra inputs are not permitted"),
                   reply(text_block("ok"))])
        self.assertIn("fallbacks", self.learned.unsupported)
        self.assertNotIn("fallbacks", self.client.requests[1])
        self.assertNotIn("server-side-fallback-2026-07-01", self.client.requests[1]["betas"])

    def test_refused_binding_controls_are_learned_off(self):
        self.call([bad_request("thinking.block_binding: Extra inputs are not permitted"),
                   reply(text_block("ok"))])
        self.assertIn("block_binding", self.learned.unsupported)
        self.assertNotIn("block_binding", self.client.requests[1]["thinking"])

    def test_a_refused_search_tool_falls_back_to_the_older_one(self):
        self.call([bad_request("claude-x does not support programmatic tool calling"),
                   reply(text_block("ok"))])
        self.assertIn("server_tools_20260209", self.learned.unsupported)
        self.assertEqual(self.client.requests[1]["tools"][-1]["type"], "web_search_20250305")

    def test_a_lower_output_ceiling_is_learned_from_the_error(self):
        self.call([bad_request("max_tokens: 128000 > 64000, which is the maximum allowed "
                               "number of output tokens for claude-opus-5-5"),
                   reply(text_block("ok"))])
        self.assertEqual(self.learned.output_caps, {"claude-opus-5-5": 64000})
        self.assertEqual(self.client.requests[1]["max_tokens"], 64000)

    def test_stale_thinking_blocks_are_stripped_once(self):
        self.messages[:] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [thinking_block("old"), text_block("hello")]},
            {"role": "user", "content": "and?"}]
        error = ("messages.1.content.0: Invalid `signature` in `thinking` block. The block "
                 "is bound to a different conversation. Remove the block, or set "
                 "`thinking.block_binding.prefix_mismatch_behavior` to \"drop_block\".")
        result = self.call([bad_request(error), reply(text_block("ok"))])
        self.assertEqual(result.text, "ok")
        self.assertEqual(len(self.messages[1]["content"]), 1)
        # That error names block_binding as its remedy; it must not turn it off.
        self.assertNotIn("block_binding", self.learned.unsupported)
        with self.assertRaises(Exception):
            self.call([bad_request(error), bad_request(error)])

    def test_a_context_overflow_trims_the_oldest_history_and_retries(self):
        rounds = []
        for number in range(6):
            rounds += [{"role": "user", "content": f"question {number} " + "x" * 400},
                       {"role": "assistant", "content": f"answer {number} " + "y" * 400}]
        self.messages[:] = rounds + [{"role": "user", "content": "latest"}]
        before = len(self.messages)
        result = self.call([bad_request("prompt is too long: 1200000 tokens > 1000000 maximum"),
                            reply(text_block("ok"))])
        self.assertEqual(result.text, "ok")
        self.assertLess(len(self.messages), before)
        self.assertEqual(self.messages[-1]["content"], "latest")
        self.assertEqual(len(self.client.requests[1]["messages"]), len(self.messages))
        self.assertIn("warning: Context exceeded the model's limit", self.shown())

    def test_an_overflow_with_nothing_left_to_trim_ends_the_call(self):
        with self.assertRaises(RuntimeError) as caught:
            self.call([bad_request("prompt is too long: 1200000 tokens > 1000000 maximum")])
        self.assertIn("nothing left to trim", str(caught.exception))

    def test_a_request_too_large_in_bytes_also_trims(self):
        rounds = []
        for number in range(6):
            rounds += [{"role": "user", "content": f"q{number}"},
                       {"role": "assistant", "content": f"a{number}"}]
        self.messages[:] = rounds + [{"role": "user", "content": "latest"}]
        before = len(self.messages)
        self.call([status_error(413, "request_too_large"), reply(text_block("ok"))])
        self.assertLess(len(self.messages), before)

    def test_ctrl_c_mid_reply_returns_what_had_streamed(self):
        result = self.call([InterruptDuring(reply(text_block("The answer")), self.interrupts)])
        self.assertTrue(result.interrupted)
        self.assertEqual(result.text, "The answer")
        self.assertEqual(result.content, [{"type": "text", "text": "The answer"}])
        self.assertEqual(result.usage["input_tokens"], 100)

    def test_ctrl_c_during_a_backoff_wait_ends_the_call(self):
        def interrupting_wait(seconds):
            self.interrupts.waits.append(seconds)
            return True
        self.interrupts.wait = interrupting_wait
        result = self.call([rate_limited(), reply(text_block("never"))])
        self.assertTrue(result.interrupted)
        self.assertEqual(self.client.remaining, 1)

    def test_a_call_served_by_a_fallback_model_is_reported_and_priced_by_it(self):
        served = reply(text_block("Here you go."), model="claude-opus-4-8",
                       usage_=usage(iterations=[Obj(type="fallback_message")]))
        result = self.call([served])
        self.assertEqual(result.usage["model"], "claude-opus-4-8")
        self.assertIn("served by claude-opus-4-8", self.shown())

    def test_a_refusal_is_explained(self):
        declined = reply(stop_reason="refusal",
                         stop_details=Obj(category="bio", explanation="declined",
                                          recommended_model="claude-opus-5"))
        result = self.call([declined])
        self.assertEqual(result.stop_reason, "refusal")
        shown = self.shown()
        self.assertIn("stop_reason=refusal, category=bio", shown)
        self.assertIn("retrying directly on claude-opus-5", shown)

    def test_dropped_thinking_blocks_are_counted_with_their_reasons(self):
        dropped = [Obj(type="thinking_dropped", reason="prefix_binding_mismatch"),
                   {"type": "thinking_dropped", "reason": "model_binding_mismatch"}]
        result = self.call([reply(text_block("ok"), input_transformations=dropped)])
        self.assertEqual(result.dropped_thinking,
                         (2, ("model_binding_mismatch", "prefix_binding_mismatch")))
        self.assertIsNone(self.call([reply(text_block("ok"))]).dropped_thinking)

    def test_a_tool_call_reply_keeps_its_blocks(self):
        result = self.call([reply(text_block("Checking."), tool_use("echo", {"a": 1}, "t1"))])
        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual([block.type for block in result.content], ["text", "tool_use"])


class Backoff(unittest.TestCase):
    def test_the_schedules(self):
        self.assertEqual([api.rate_limit_backoff(n) for n in range(5)], [5, 10, 20, 40, 60])
        self.assertEqual([api.server_error_backoff(n) for n in range(5)], [10, 20, 40, 80, 90])
        self.assertEqual([api.connection_error_backoff(n) for n in range(5)],
                         [5, 10, 20, 40, 60])


if __name__ == "__main__":
    unittest.main()
