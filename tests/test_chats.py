"""Tests for robot.chats: chat names, saved messages and the live transcript.

Everything is written inside a temporary folder that is removed afterwards.
"""

import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from robot.chats import (
    Transcript,
    chat_payload,
    new_chat_name,
    sanitize_filename,
    save_chat_json,
    serialize_messages,
    unique_chat_stem,
)

NOW = datetime(2026, 10, 7, 9, 15, 0)


class Obj:
    """Stands in for an SDK content block: its fields are attributes, not keys."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class Dumping:
    """An SDK-style block that also lists its fields through model_dump().

    Every field can be read as an attribute, but none of them shows up in
    vars(). The real SDK keeps fields it has no definition for in the same
    way, so model_dump() is the only complete list.
    """

    def __init__(self, type, **fields):
        self._fields = {"type": type, **fields}

    def __getattr__(self, name):
        try:
            return self.__dict__["_fields"][name]
        except KeyError:
            raise AttributeError(name) from None

    def model_dump(self):
        return copy.deepcopy(self._fields)


class ClassTyped:
    """A block whose type is declared on the class rather than set per object."""

    type = "text"

    def __init__(self, text):
        self.text = text


class Bare:
    """Has a type and nothing else to show: no attributes dict at all."""

    __slots__ = ()
    type = "mystery"


def saved_blocks(blocks, save_thinking=False):
    """Serialise one assistant message holding `blocks` and return its saved blocks.

    None means the whole message was left out of the saved chat.
    """
    saved = serialize_messages([{"role": "assistant", "content": blocks}], save_thinking)
    return saved[0]["content"] if saved else None


class BlockKindCase(unittest.TestCase):
    """Checks one block both ways: with the model's thinking saved and without."""

    def assert_saved_as(self, block, expected):
        self.assertEqual(saved_blocks([block], save_thinking=True), [expected])
        if expected["type"] in ("thinking", "redacted_thinking"):
            # Only ever saved on request. Being the only block, its message goes too.
            self.assertIsNone(saved_blocks([block], save_thinking=False))
            self.assertIsNone(saved_blocks([block]))
        else:
            self.assertEqual(saved_blocks([block], save_thinking=False), [expected])
            self.assertEqual(saved_blocks([block]), [expected])

    def assert_all_saved_as(self, blocks, expected):
        """For blocks that are no one's thinking: the setting makes no difference."""
        for save_thinking in (False, True):
            with self.subTest(save_thinking=save_thinking):
                self.assertEqual(saved_blocks(blocks, save_thinking), expected)


class TempDirCase(unittest.TestCase):
    """Gives each test a folder of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def names(self, folder=None):
        return sorted(p.name for p in (folder or self.dir).iterdir())


# ---- names ----


class SanitizeFilenameTests(unittest.TestCase):

    def test_cases(self):
        cases = [
            ("hello", "hello"),
            ("a/b\\c:d*e?", "a_b_c_d_e_"),
            ("  ...trim...  ", "trim"),
            ("", "_"),
            ("...", "_"),
            ('CON<>:"|', "CON_____"),
            ("  my: chat  ", "my_ chat"),
            ('a<b>:"c/d\\e|f?g*h. ', "a_b___c_d_e_f_g_h"),
            ("Tidy Logs_2026-10-07_091500", "Tidy Logs_2026-10-07_091500"),
            ("v1.2 notes", "v1.2 notes"),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(sanitize_filename(name), expected)

    def test_control_characters_are_replaced(self):
        self.assertEqual(sanitize_filename("a\x00b\nc\td\x1fe"), "a_b_c_d_e")

    def test_a_clean_name_is_left_alone_when_cleaned_again(self):
        for name in ("a/b", "  x. ", "", 'q"?', "..hidden"):
            with self.subTest(name=name):
                once = sanitize_filename(name)
                self.assertEqual(sanitize_filename(once), once)

    def test_the_result_has_no_folder_parts(self):
        for name in ("../../etc/passwd", "..\\..\\x", "/abs/path", "C:\\x\\y"):
            with self.subTest(name=name):
                stem = sanitize_filename(name)
                self.assertNotIn("/", stem)
                self.assertNotIn("\\", stem)
                self.assertEqual(Path(stem).name, stem)


class NewChatNameTests(unittest.TestCase):

    def test_the_name_is_the_instruction_then_the_time(self):
        self.assertEqual(new_chat_name("Tidy Logs", NOW), "Tidy Logs_2026-10-07_091500")

    def test_a_run_without_an_instruction_is_named_agent(self):
        self.assertEqual(new_chat_name("", NOW), "Agent_2026-10-07_091500")
        self.assertEqual(new_chat_name(now=NOW), "Agent_2026-10-07_091500")
        self.assertEqual(new_chat_name(None, NOW), "Agent_2026-10-07_091500")
        self.assertEqual(new_chat_name("  \n ", NOW), "Agent_2026-10-07_091500")

    def test_whitespace_in_the_instruction_name_is_collapsed(self):
        self.assertEqual(new_chat_name("  Two   words\n", NOW), "Two words_2026-10-07_091500")

    def test_without_a_time_the_clock_is_used(self):
        self.assertRegex(new_chat_name("Tidy Logs"), r"^Tidy Logs_\d{4}-\d{2}-\d{2}_\d{6}$")
        before = datetime.now().replace(microsecond=0)
        stamp = new_chat_name("x")[len("x_"):]
        after = datetime.now()
        self.assertLessEqual(before, datetime.strptime(stamp, "%Y-%m-%d_%H%M%S"))
        self.assertLessEqual(datetime.strptime(stamp, "%Y-%m-%d_%H%M%S"), after)

    def test_the_name_is_safe_to_use_as_a_file_name(self):
        # The run's files are called after it, and an instruction can be
        # called anything.
        cases = [
            ("Fix a/b: now?", "Fix a_b_ now__2026-10-07_091500"),
            ("/etc cleanup", "_etc cleanup_2026-10-07_091500"),
            ("../../up", "_.._up_2026-10-07_091500"),
            ("..\\up", "_up_2026-10-07_091500"),
            (".hidden", "hidden_2026-10-07_091500"),
            ("C:\\x", "C__x_2026-10-07_091500"),
        ]
        for instruction, expected in cases:
            with self.subTest(instruction=instruction):
                name = new_chat_name(instruction, NOW)
                self.assertEqual(name, expected)
                self.assertEqual(sanitize_filename(name), name)
                self.assertEqual(Path(name).name, name)


class UniqueChatStemTests(TempDirCase):

    STEM = "Tidy Logs_2026-10-07_091500"

    def test_a_free_stem_is_kept(self):
        self.assertEqual(unique_chat_stem(self.dir, self.STEM, 4242), self.STEM)
        self.assertEqual(unique_chat_stem(str(self.dir), self.STEM, 4242), self.STEM)

    def test_a_folder_that_does_not_exist_yet_has_every_stem_free(self):
        self.assertEqual(unique_chat_stem(self.dir / "not_yet", self.STEM, 4242), self.STEM)

    def test_an_existing_json_adds_the_process_id(self):
        (self.dir / f"{self.STEM}.json").write_text("{}", encoding="utf-8")
        self.assertEqual(unique_chat_stem(self.dir, self.STEM, 4242), f"{self.STEM}_4242")

    def test_an_existing_txt_adds_the_process_id(self):
        (self.dir / f"{self.STEM}.txt").write_text("", encoding="utf-8")
        self.assertEqual(unique_chat_stem(self.dir, self.STEM, 77), f"{self.STEM}_77")

    def test_other_chats_do_not_count(self):
        (self.dir / "Tidy Logs_2026-10-07_091501.json").write_text("{}", encoding="utf-8")
        (self.dir / f"{self.STEM}.log").write_text("", encoding="utf-8")
        self.assertEqual(unique_chat_stem(self.dir, self.STEM, 4242), self.STEM)

    def test_a_dot_in_the_stem_is_part_of_the_name(self):
        (self.dir / "v1.json").write_text("{}", encoding="utf-8")
        self.assertEqual(unique_chat_stem(self.dir, "v1.2 notes", 5), "v1.2 notes")
        (self.dir / "v1.2 notes.txt").write_text("", encoding="utf-8")
        self.assertEqual(unique_chat_stem(self.dir, "v1.2 notes", 5), "v1.2 notes_5")


class RunFilesTests(TempDirCase):
    """The steps a run takes to start and save its two files, taken together."""

    def start(self, chats, instruction, pid):
        stem = unique_chat_stem(chats, new_chat_name(instruction, NOW), pid)
        transcript = Transcript(chats / f"{stem}.txt")
        self.addCleanup(transcript.close)
        transcript.write("you> go\n")
        save_chat_json(chats / f"{stem}.json", chat_payload(
            name=stem, messages=[{"role": "user", "content": "go"}], tools=[],
            system_prompt="s", instruction=instruction, model="claude-opus-5-5",
            thinking_mode="low"))
        return stem

    def test_the_second_run_with_one_name_gets_files_of_its_own(self):
        chats = self.dir / "saved_chats"
        first = self.start(chats, "Tidy Logs", 100)
        second = self.start(chats, "Tidy Logs", 200)
        self.assertEqual(first, "Tidy Logs_2026-10-07_091500")
        self.assertEqual(second, "Tidy Logs_2026-10-07_091500_200")
        self.assertEqual(self.names(chats), sorted(
            f"{stem}{ext}" for stem in (first, second) for ext in (".json", ".txt")))

    def test_the_files_stay_in_the_chats_folder_whatever_the_instruction_is_called(self):
        instructions = ["Tidy Logs", "a/b", "/abs/name", "../../up", "..\\..\\up", "C:\\x",
                        ".hidden", "what?*", "tab\there"]
        for number, instruction in enumerate(instructions):
            with self.subTest(instruction=instruction):
                base = self.dir / f"case{number}" / "robot-data"
                chats = base / "saved_chats"
                stem = self.start(chats, instruction, 100)
                self.assertEqual(self.names(chats), [f"{stem}.json", f"{stem}.txt"])
                self.assertEqual(self.names(base), ["saved_chats"])
                self.assertEqual(self.names(base.parent), ["robot-data"])
                saved = json.loads((chats / f"{stem}.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["name"], stem)
                self.assertEqual(saved["agent_instruction_name"], instruction)


# ---- messages ----


class SerializeDictBlockTests(BlockKindCase):

    def test_text_content_passes_through(self):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        self.assertEqual(serialize_messages(messages), messages)

    def test_each_kind_of_block(self):
        cases = [
            ({"type": "text", "text": "hi"},
             {"type": "text", "text": "hi"}),
            ({"type": "tool_use", "id": "t1", "name": "foo", "input": {"a": 1}},
             {"type": "tool_use", "id": "t1", "name": "foo", "input": {"a": 1}}),
            ({"type": "tool_result", "tool_use_id": "u1", "content": "ok"},
             {"type": "tool_result", "tool_use_id": "u1", "content": "ok"}),
            ({"type": "tool_result", "tool_use_id": "u2",
              "content": [{"type": "image", "source": {}}, {"type": "text", "text": "t"}]},
             {"type": "tool_result", "tool_use_id": "u2",
              "content": [{"type": "text", "text": "[Screenshot]"},
                          {"type": "text", "text": "t"}]}),
            ({"type": "image", "source": {"type": "base64", "data": "AAAA"}},
             {"type": "text", "text": "[Image was attached]"}),
            ({"type": "thinking", "thinking": "deep", "signature": "s"},
             {"type": "thinking", "thinking": "deep", "signature": "s"}),
            ({"type": "redacted_thinking", "data": "xx"},
             {"type": "redacted_thinking", "data": "xx"}),
            ({"type": "weird", "foo": 1},
             {"type": "weird", "foo": 1}),
            ("a bare string",
             {"type": "text", "text": "a bare string"}),
        ]
        for block, expected in cases:
            with self.subTest(block=block):
                self.assert_saved_as(block, expected)

    def test_fields_a_saved_chat_does_not_need_are_dropped(self):
        blocks = [
            {"type": "text", "text": "hi", "citations": [{"url": "u"}],
             "cache_control": {"type": "ephemeral"}},
            {"type": "tool_use", "id": "t1", "name": "foo", "input": {}, "caller": None},
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok",
             "cache_control": {"type": "ephemeral"}},
        ]
        self.assert_all_saved_as(blocks, [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "foo", "input": {}},
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ])

    def test_missing_fields_do_not_crash(self):
        blocks = [{"type": "text"}, {"type": "thinking"}, {"type": "redacted_thinking"},
                  {"type": "tool_use"}, {"type": "tool_result"}]
        self.assertEqual(saved_blocks(blocks, save_thinking=True), [
            {"type": "text", "text": ""},
            {"type": "thinking", "thinking": "", "signature": ""},
            {"type": "redacted_thinking", "data": ""},
            {"type": "tool_use", "id": None, "name": None, "input": None},
            {"type": "tool_result", "tool_use_id": None},
        ])

    def test_a_failed_tool_call_stays_marked(self):
        blocks = [
            {"type": "tool_result", "tool_use_id": "t1", "content": "boom", "is_error": True},
            {"type": "tool_result", "tool_use_id": "t2", "content": "fine", "is_error": False},
            {"type": "tool_result", "tool_use_id": "t3", "content": "fine"},
        ]
        self.assert_all_saved_as(blocks, blocks)

    def test_a_tool_result_list_keeps_its_parts(self):
        block = {"type": "tool_result", "tool_use_id": "t1", "content": [
            "loose text",
            {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
            {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
            {"type": "search_result", "source": "s", "title": "T"},
            Obj(type="text", text="from an object"),
            Obj(type="image", source={}),
        ]}
        self.assert_all_saved_as([block], [{
            "type": "tool_result", "tool_use_id": "t1", "content": [
                "loose text",
                {"type": "text", "text": "a"},
                {"type": "text", "text": "[Screenshot]"},
                {"type": "search_result", "source": "s", "title": "T"},
                {"type": "text", "text": "from an object"},
                {"type": "text", "text": "[Screenshot]"},
            ]}])

    def test_server_tool_blocks_are_kept_whole(self):
        blocks = [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "weather"}, "caller": None},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "caller": None,
             "content": [{"type": "web_search_result", "url": "https://example.com",
                          "title": "T", "encrypted_content": "ENC", "page_age": None}]},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2",
             "content": {"type": "web_search_tool_result_error",
                         "error_code": "max_uses_exceeded"}},
            {"type": "code_execution_tool_result", "tool_use_id": "srvtoolu_3",
             "content": {"type": "code_execution_result", "stdout": "1\n", "stderr": "",
                         "return_code": 0, "content": []}},
        ]
        self.assert_all_saved_as(blocks, blocks)

    def test_content_that_is_neither_text_nor_a_list_is_saved_as_text(self):
        saved = serialize_messages([{"role": "user", "content": None},
                                    {"role": "user", "content": 42}])
        self.assertEqual(saved, [{"role": "user", "content": "None"},
                                 {"role": "user", "content": "42"}])

    def test_a_tuple_of_blocks_is_read_like_a_list(self):
        result = {"type": "tool_result", "tool_use_id": "t1", "content": (
            {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
            {"type": "image", "source": {}},
            "b",
        )}
        saved = serialize_messages([{"role": "user", "content": (result,)}])
        self.assertEqual(saved, [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "a"},
                {"type": "text", "text": "[Screenshot]"},
                "b",
            ]}]}])

    def test_only_role_and_content_are_saved(self):
        saved = serialize_messages([{"role": "user", "content": "hi", "extra": 1}])
        self.assertEqual(saved, [{"role": "user", "content": "hi"}])

    def test_a_message_with_no_blocks_is_left_out(self):
        saved = serialize_messages([{"role": "user", "content": "hi"},
                                    {"role": "assistant", "content": []},
                                    {"role": "user", "content": "again"}])
        self.assertEqual(saved, [{"role": "user", "content": "hi"},
                                 {"role": "user", "content": "again"}])


class SerializeThinkingTests(unittest.TestCase):

    def turn(self, make):
        return [
            make(type="thinking", thinking="deep", signature="sig"),
            make(type="redacted_thinking", data="xx"),
            make(type="text", text="answer"),
        ]

    def test_thinking_is_dropped_unless_asked_for(self):
        for make in (dict, Obj, Dumping):
            with self.subTest(blocks=make.__name__):
                self.assertEqual(saved_blocks(self.turn(make)),
                                 [{"type": "text", "text": "answer"}])
                self.assertEqual(saved_blocks(self.turn(make), save_thinking=False),
                                 [{"type": "text", "text": "answer"}])

    def test_thinking_is_kept_when_asked_for(self):
        for make in (dict, Obj, Dumping):
            with self.subTest(blocks=make.__name__):
                self.assertEqual(saved_blocks(self.turn(make), save_thinking=True), [
                    {"type": "thinking", "thinking": "deep", "signature": "sig"},
                    {"type": "redacted_thinking", "data": "xx"},
                    {"type": "text", "text": "answer"},
                ])

    def test_a_turn_of_nothing_but_thinking_leaves_no_message(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "t",
                                               "signature": "s"}]},
            {"role": "user", "content": "more"},
        ]
        self.assertEqual(serialize_messages(messages), [messages[0], messages[2]])
        self.assertEqual(serialize_messages(messages, save_thinking=True), messages)


class SerializeObjectBlockTests(BlockKindCase):

    def test_each_kind_of_block(self):
        cases = [
            (Obj(type="text", text="hi", citations=None),
             {"type": "text", "text": "hi"}),
            (Obj(type="tool_use", id="t1", name="foo", input={"a": [1, 2]}, caller=None),
             {"type": "tool_use", "id": "t1", "name": "foo", "input": {"a": [1, 2]}}),
            (Obj(type="tool_result", tool_use_id="u1", content="ok"),
             {"type": "tool_result", "tool_use_id": "u1", "content": "ok"}),
            (Obj(type="tool_result", tool_use_id="u2", is_error=True,
                 content=[Obj(type="text", text="t"), Obj(type="image", source={})]),
             {"type": "tool_result", "tool_use_id": "u2", "is_error": True,
              "content": [{"type": "text", "text": "t"},
                          {"type": "text", "text": "[Screenshot]"}]}),
            (Obj(type="tool_result", tool_use_id="u3"),
             {"type": "tool_result", "tool_use_id": "u3"}),
            (Obj(type="image", source={"type": "base64", "data": "AAAA"}),
             {"type": "text", "text": "[Image was attached]"}),
            (Obj(type="thinking", thinking="deep", signature="s"),
             {"type": "thinking", "thinking": "deep", "signature": "s"}),
            (Obj(type="redacted_thinking", data="xx"),
             {"type": "redacted_thinking", "data": "xx"}),
            (ClassTyped("typed on the class"),
             {"type": "text", "text": "typed on the class"}),
        ]
        for block, expected in cases:
            with self.subTest(expected=expected):
                self.assert_saved_as(block, expected)

    def test_server_tool_objects_become_plain_dicts(self):
        blocks = [
            Obj(type="server_tool_use", id="srvtoolu_1", name="web_search",
                input={"query": "weather"}, caller=None),
            Obj(type="web_search_tool_result", tool_use_id="srvtoolu_1", caller=None,
                content=[Obj(type="web_search_result", url="https://example.com", title="T",
                             encrypted_content="ENC", page_age=None)]),
            Obj(type="web_search_tool_result", tool_use_id="srvtoolu_2",
                content=Obj(type="web_search_tool_result_error",
                            error_code="max_uses_exceeded")),
        ]
        self.assert_all_saved_as(blocks, [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "weather"}, "caller": None},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "caller": None,
             "content": [{"type": "web_search_result", "url": "https://example.com",
                          "title": "T", "encrypted_content": "ENC", "page_age": None}]},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2",
             "content": {"type": "web_search_tool_result_error",
                         "error_code": "max_uses_exceeded"}},
        ])

    def test_model_dump_is_used_when_an_object_has_it(self):
        # The dump holds fields that are not attributes, so only it is complete.
        blocks = [
            Dumping("server_tool_use", id="srvtoolu_1", name="web_search",
                    input={"query": "weather"}, caller=None),
            Dumping("web_search_tool_result", tool_use_id="srvtoolu_1",
                    content=[{"type": "web_search_result", "url": "https://example.com",
                              "title": "T", "encrypted_content": "ENC"}]),
            Dumping("fallback", from_={"model": "a"}, to={"model": "b"},
                    trigger={"type": "refusal"}),
            Dumping("brand_new_kind", foo=1, nested={"a": [1, 2]}),
        ]
        self.assert_all_saved_as(blocks, [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "weather"}, "caller": None},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
             "content": [{"type": "web_search_result", "url": "https://example.com",
                          "title": "T", "encrypted_content": "ENC"}]},
            {"type": "fallback", "from_": {"model": "a"}, "to": {"model": "b"},
             "trigger": {"type": "refusal"}},
            {"type": "brand_new_kind", "foo": 1, "nested": {"a": [1, 2]}},
        ])

    def test_an_unknown_kind_keeps_its_type_and_public_fields(self):
        block = Obj(type="brand_new_kind", foo=1, nested=Obj(deep=[Obj(x=1)]), _private="no")
        self.assert_all_saved_as([block], [
            {"type": "brand_new_kind", "foo": 1, "nested": {"deep": [{"x": 1}]}}])

    def test_an_object_with_only_a_type_keeps_the_type(self):
        self.assertEqual(saved_blocks([Bare()]), [{"type": "mystery"}])

    def test_things_that_are_not_blocks_are_saved_as_text(self):
        self.assertEqual(saved_blocks(["text", 7, None]), [
            {"type": "text", "text": "text"},
            {"type": "text", "text": "7"},
            {"type": "text", "text": "None"},
        ])

    def test_an_object_without_a_type_keeps_its_fields(self):
        self.assertEqual(saved_blocks([Obj(foo=1)]), [{"foo": 1}])

    def test_a_model_dump_that_fails_falls_back_to_the_attributes(self):
        class Broken(Obj):
            def model_dump(self):
                raise RuntimeError("cannot dump")

        class NotADict(Obj):
            def model_dump(self):
                return "nonsense"

        class Empty(Obj):
            def model_dump(self):
                return {}

        for make in (Broken, NotADict, Empty):
            with self.subTest(kind=make.__name__):
                block = make(type="server_tool_use", id="s1", name="web_search", input={})
                self.assertEqual(saved_blocks([block]), [
                    {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}}])

    def test_a_message_given_as_an_object_is_read_too(self):
        message = Obj(role="assistant", content=[Obj(type="text", text="hi")])
        self.assertEqual(serialize_messages([message]),
                         [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}])


class SerializeSafetyTests(unittest.TestCase):

    def conversation(self):
        return [
            {"role": "user", "content": "what is the weather?"},
            {"role": "assistant", "content": [
                Obj(type="thinking", thinking="let me look", signature="sig"),
                Obj(type="server_tool_use", id="srvtoolu_1", name="web_search",
                    input={"query": "weather"}),
                Dumping("web_search_tool_result", tool_use_id="srvtoolu_1",
                        content=[{"type": "web_search_result", "url": "https://example.com",
                                  "title": "T", "encrypted_content": "ENC"}]),
                Obj(type="text", text="Checking the sensor too."),
                Obj(type="tool_use", id="toolu_1", name="get_cpu_temperature", input={}),
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "41.2 degrees"}]},
            {"role": "assistant", "content": [Obj(type="text", text="Mild, and I am at 41 C.")]},
        ]

    def test_the_result_can_be_written_as_json(self):
        for save_thinking in (False, True):
            with self.subTest(save_thinking=save_thinking):
                saved = serialize_messages(self.conversation(), save_thinking)
                self.assertEqual(json.loads(json.dumps(saved)), saved)
                self.assertEqual([m["role"] for m in saved],
                                 ["user", "assistant", "user", "assistant"])

    def test_odd_values_inside_a_block_are_made_writable(self):
        block = {"type": "weird", "when": NOW, "raw": b"bytes", "pair": (1, 2),
                 "obj": Obj(a=1), 5: "number key", "many": {3, }}
        (saved,) = saved_blocks([block])
        json.dumps(saved)
        self.assertEqual(saved["pair"], [1, 2])
        self.assertEqual(saved["obj"], {"a": 1})
        self.assertEqual(saved["5"], "number key")
        self.assertEqual(saved["when"], str(NOW))
        self.assertEqual(saved["many"], "{3}")

    def test_the_messages_passed_in_are_not_changed(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "t", "signature": "s"},
                {"type": "text", "text": "hi", "citations": [{"url": "u"}]},
                {"type": "tool_use", "id": "t1", "name": "foo", "input": {"a": {"b": 1}}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "image", "source": {"data": "AAAA"}}]}]},
        ]
        before = copy.deepcopy(messages)
        serialize_messages(messages)
        serialize_messages(messages, save_thinking=True)
        self.assertEqual(messages, before)

    def test_the_result_shares_nothing_with_the_messages(self):
        tool_input = {"a": {"b": [1]}}
        unknown = {"type": "weird", "data": {"k": [1]}}
        messages = [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "foo", "input": tool_input}, unknown]}]
        saved = serialize_messages(messages)
        saved[0]["content"][0]["input"]["a"]["b"].append(2)
        saved[0]["content"][1]["data"]["k"].append(2)
        self.assertEqual(tool_input, {"a": {"b": [1]}})
        self.assertEqual(unknown, {"type": "weird", "data": {"k": [1]}})

    def test_a_block_that_contains_itself_does_not_loop_for_ever(self):
        looped = Obj(type="brand_new_kind", name="loop")
        looped.me = looped
        looped.items = [looped, {"again": looped}]
        circular = {"type": "weird"}
        circular["self"] = circular
        saved = saved_blocks([looped, circular])
        json.dumps(saved)
        self.assertEqual(saved[0]["type"], "brand_new_kind")
        self.assertEqual(saved[0]["name"], "loop")
        self.assertEqual(saved[1]["type"], "weird")

    def test_a_mock_as_a_block_does_not_crash(self):
        saved = saved_blocks([mock.Mock(), mock.MagicMock()], save_thinking=True)
        self.assertEqual(len(saved), 2)
        json.dumps(saved)

    def test_a_mock_set_up_as_a_block_is_read_by_its_attributes(self):
        blocks = [mock.Mock(type="text", text="hi"),
                  mock.Mock(type="tool_use", id="t1", input={"a": 1})]
        blocks[1].name = "foo"  # Mock keeps `name` for itself when it is passed in
        self.assertEqual(saved_blocks(blocks), [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "foo", "input": {"a": 1}},
        ])


# ---- the .json ----


class ChatPayloadTests(unittest.TestCase):

    TOOLS = [{"name": "get_cpu_temperature", "description": "d",
              "input_schema": {"type": "object", "properties": {}}},
             {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]

    def payload(self, **changes):
        fields = dict(
            name="Tidy Logs_2026-10-07_091500",
            messages=[
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": [
                    Obj(type="thinking", thinking="t", signature="s"),
                    Obj(type="text", text="done")]},
            ],
            tools=self.TOOLS,
            system_prompt="You are the brain of a small robot.",
            instruction="Tidy Logs",
            model="claude-opus-5-5",
            thinking_mode="low",
        )
        fields.update(changes)
        return chat_payload(**fields)

    def test_the_shape(self):
        self.assertEqual(self.payload(), {
            "messages": [
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            ],
            "tools": self.TOOLS,
            "system_prompt": "You are the brain of a small robot.",
            "agent_instruction_name": "Tidy Logs",
            "provider": "Anthropic",
            "model": "claude-opus-5-5",
            "thinking_mode": "low",
            "name": "Tidy Logs_2026-10-07_091500",
        })

    def test_the_keys_come_in_the_order_the_file_shows_them(self):
        self.assertEqual(list(self.payload()), [
            "messages", "tools", "system_prompt", "agent_instruction_name",
            "provider", "model", "thinking_mode", "name"])

    def test_there_is_no_temperature(self):
        self.assertNotIn("temperature", self.payload())

    def test_thinking_is_saved_only_when_asked_for(self):
        def kinds(payload):
            return [block["type"] for block in payload["messages"][1]["content"]]

        self.assertEqual(kinds(self.payload()), ["text"])
        self.assertEqual(kinds(self.payload(save_thinking=False)), ["text"])
        self.assertEqual(kinds(self.payload(save_thinking=True)), ["thinking", "text"])

    def test_an_ad_hoc_run_has_an_empty_instruction_name(self):
        self.assertEqual(self.payload(instruction="")["agent_instruction_name"], "")

    def test_the_tools_are_copied(self):
        payload = self.payload()
        payload["tools"][0]["input_schema"]["properties"]["x"] = {}
        self.assertEqual(self.TOOLS[0]["input_schema"]["properties"], {})

    def test_the_fields_must_be_given_by_name(self):
        with self.assertRaises(TypeError):
            chat_payload("name", [], [], "", "", "model", "low")

    def test_it_can_be_written_as_json(self):
        payload = self.payload(save_thinking=True)
        self.assertEqual(json.loads(json.dumps(payload)), payload)


class SaveChatJsonTests(TempDirCase):

    PAYLOAD = {
        "messages": [{"role": "user", "content": "caf\u00e9 \u2603"},
                     {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}],
        "tools": [],
        "name": "x",
    }

    def test_the_file_is_indented_json_readable_as_text(self):
        path = self.dir / "chat.json"
        save_chat_json(path, self.PAYLOAD)
        raw = path.read_bytes()
        self.assertEqual(raw.decode("utf-8"),
                         json.dumps(self.PAYLOAD, indent=2, ensure_ascii=False))
        self.assertIn("caf\u00e9 \u2603".encode("utf-8"), raw)  # not \u escapes
        self.assertNotIn(b"\r", raw)
        self.assertEqual(json.loads(raw.decode("utf-8")), self.PAYLOAD)

    def test_saving_again_replaces_the_file_and_leaves_no_temp_file(self):
        path = self.dir / "chat.json"
        save_chat_json(path, self.PAYLOAD)
        save_chat_json(str(path), {"messages": [], "name": "x"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"messages": [], "name": "x"})
        self.assertEqual(self.names(), ["chat.json"])

    def test_the_chats_folder_is_created(self):
        path = self.dir / "saved_chats" / "chat.json"
        save_chat_json(path, self.PAYLOAD)
        self.assertTrue(path.is_file())

    def test_a_payload_that_cannot_be_written_keeps_the_earlier_file(self):
        path = self.dir / "chat.json"
        save_chat_json(path, self.PAYLOAD)
        with self.assertRaises(TypeError):
            save_chat_json(path, {"messages": [object()]})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.PAYLOAD)
        self.assertEqual(self.names(), ["chat.json"])

    def test_a_write_that_fails_part_way_keeps_the_earlier_file(self):
        path = self.dir / "chat.json"
        save_chat_json(path, self.PAYLOAD)
        # Half of a surrogate pair cannot be encoded, so this fails while the
        # file is being written, not before.
        with self.assertRaises(UnicodeEncodeError):
            save_chat_json(path, {"messages": [{"role": "user", "content": "bad \ud83d"}]})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.PAYLOAD)
        self.assertEqual(self.names(), ["chat.json"])

    def test_a_whole_chat_round_trips(self):
        payload = chat_payload(
            name="Agent_2026-10-07_091500",
            messages=[{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": [Obj(type="text", text="hello")]}],
            tools=[], system_prompt="s", instruction="", model="claude-opus-5-5",
            thinking_mode="off")
        path = self.dir / "Agent_2026-10-07_091500.json"
        save_chat_json(path, payload)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)


# ---- the .txt ----


class FailingFile:
    """A file whose every operation fails with the given error."""

    def __init__(self, error):
        self.error = error

    def write(self, text):
        raise self.error

    def flush(self):
        raise self.error

    def close(self):
        raise self.error


class TranscriptTests(TempDirCase):

    def open(self, path):
        transcript = Transcript(path)
        self.addCleanup(transcript.close)  # before the folder is removed
        return transcript

    def test_writes_are_appended_in_order(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write("you> hello\n")
        transcript.write("robot> ")
        transcript.write("hi")
        transcript.write("\n")
        transcript.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "you> hello\nrobot> hi\n")

    def test_each_write_reaches_the_file_at_once(self):
        # Read back while still open: a killed run must already have its text.
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write("first ")
        self.assertEqual(path.read_text(encoding="utf-8"), "first ")
        transcript.write("second")
        self.assertEqual(path.read_text(encoding="utf-8"), "first second")

    def test_an_existing_transcript_is_added_to_not_replaced(self):
        path = self.dir / "run.txt"
        first = self.open(path)
        first.write("one\n")
        first.close()
        second = self.open(path)
        second.write("two\n")
        second.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "one\ntwo\n")

    def test_parent_folders_are_created(self):
        path = self.dir / "robot-data" / "saved_chats" / "run.txt"
        transcript = self.open(path)
        transcript.write("x")
        transcript.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "x")

    def test_the_file_exists_as_soon_as_the_transcript_is_opened(self):
        path = self.dir / "run.txt"
        self.open(path)
        self.assertTrue(path.is_file())

    def test_the_path_is_kept_and_may_be_text(self):
        transcript = self.open(str(self.dir / "run.txt"))
        self.assertEqual(transcript.path, self.dir / "run.txt")

    def test_the_file_is_utf8_with_lf_newlines(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        text = "caf\u00e9 \u2603\nsecond line\n"
        transcript.write(text)
        transcript.close()
        # Exactly these bytes: no \r\n on Windows.
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_a_character_that_cannot_be_encoded_costs_nothing_else(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write("before \ud83d after\n")
        transcript.write("next\n")
        transcript.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "before \\ud83d after\nnext\n")

    def test_empty_and_missing_text_write_nothing(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write("")
        transcript.write(None)
        transcript.close()
        self.assertEqual(path.read_bytes(), b"")

    def test_text_that_is_not_a_string_is_written_as_text(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write(42)
        transcript.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "42")

    def test_nothing_raises_after_close(self):
        path = self.dir / "run.txt"
        transcript = self.open(path)
        transcript.write("kept\n")
        transcript.close()
        transcript.write("lost\n")
        transcript.close()
        transcript.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "kept\n")

    def test_nothing_raises_when_the_folder_is_deleted_under_it(self):
        folder = self.dir / "saved_chats"
        transcript = self.open(folder / "run.txt")
        transcript.write("one\n")
        # Linux removes the folder even though the file is open. Windows
        # refuses to, so there this only shows that writing carries on.
        shutil.rmtree(folder, ignore_errors=True)
        transcript.write("two\n")
        transcript.close()
        transcript.write("three\n")

    def test_nothing_raises_once_the_folder_is_gone_and_the_file_closed(self):
        folder = self.dir / "saved_chats"
        transcript = self.open(folder / "run.txt")
        transcript.write("one\n")
        transcript.close()
        shutil.rmtree(folder)
        self.assertFalse(folder.exists())
        transcript.write("two\n")
        transcript.close()
        self.assertFalse(folder.exists())  # and nothing is recreated

    def test_a_failing_file_never_raises(self):
        errors = [OSError(28, "No space left on device"),
                  ValueError("I/O operation on closed file")]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                transcript = self.open(self.dir / f"{type(error).__name__}.txt")
                real_file = transcript._file
                self.addCleanup(real_file.close)
                transcript._file = FailingFile(error)
                transcript.write("text")
                transcript.close()

    def test_an_interrupt_is_not_swallowed(self):
        # Ctrl-C has to get through, or a reply could not be cancelled.
        transcript = self.open(self.dir / "run.txt")
        real_file = transcript._file
        transcript._file = FailingFile(KeyboardInterrupt())
        try:
            with self.assertRaises(KeyboardInterrupt):
                transcript.write("text")
        finally:
            transcript._file = real_file  # so the clean-up closes the real file

    def test_opening_fails_loudly_when_the_file_cannot_be_made(self):
        blocker = self.dir / "a_file"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(OSError):
            Transcript(blocker / "run.txt")


if __name__ == "__main__":
    unittest.main()
