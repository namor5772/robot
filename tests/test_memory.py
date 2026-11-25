"""The robot's memory: its files, what a run is told, and the remembering call.

No network: the model is the scripted fake client.
"""

import datetime
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from robot import costs, memory, prompts
from robot.agent import Agent
from robot.datastore import DataDir, load_store
from robot.instructions import (
    RunSettings, describe, load_instructions, save_instructions, settings_from_entry)
from robot.meta import manage_instructions
from robot.tools import available_tools
from tests.fakes import FakeClient, NoWaitInterrupts, piped_console, reply, text_block, usage

NOON = datetime.datetime(2026, 11, 25, 12, 0)
LATER = datetime.datetime(2026, 11, 26, 9, 12)

REMEMBERED = ("<memory>\nThe people I know\nRoman likes tea.\n</memory>\n"
              "<diary>\nRoman told me he likes tea.\n</diary>")
TALK = "=== x ===\nyou> Hi Otto\nrobot> Hello.\n  call 1: $0.0010 this call\nyou> (heard) I like tea\n"


class StoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.datadir = DataDir(tmp.name)
        self.datadir.ensure()
        self.store = memory.Store(self.datadir)

    def transcript(self, text=TALK, name="Talk_1.txt"):
        path = self.datadir.chats_dir / name
        path.write_text(text, encoding="utf-8")
        return path


class FilesTest(StoreCase):
    def test_nothing_is_there_at_first(self):
        self.assertEqual(self.store.memory(), "")
        self.assertEqual(self.store.diary(), [])
        self.assertEqual(self.store.last_awake(), "")
        self.assertFalse(self.store.folder.exists())

    def test_what_is_written_is_read_back(self):
        self.store.write("I know Roman.", "We met.", NOON, NOON + datetime.timedelta(minutes=8))
        self.assertEqual(self.store.memory(), "I know Roman.")
        self.assertEqual(self.store.diary(), ["## 2026-11-25 12:00 to 2026-11-25 12:08\nWe met."])

    def test_the_diary_grows_and_the_memory_is_replaced(self):
        self.store.write("one", "first talk", NOON, NOON)
        self.store.write("two", "second talk", LATER, LATER)
        self.assertEqual(self.store.memory(), "two")
        self.assertEqual([entry.splitlines()[1] for entry in self.store.diary()],
                         ["first talk", "second talk"])

    def test_the_memory_as_it_was_is_kept_beside_it(self):
        self.store.write("one", "", NOON, NOON)
        self.assertFalse(self.store.versions_dir.exists())
        self.store.write("two", "", NOON, NOON)
        kept = list(self.store.versions_dir.glob("memory_*.md"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_text(encoding="utf-8").strip(), "one")

    def test_an_empty_diary_entry_adds_nothing(self):
        self.store.write("one", "  ", NOON, NOON)
        self.assertEqual(self.store.diary(), [])

    def test_a_memory_far_too_long_is_cut(self):
        self.store.write("x" * (memory.MAX_MEMORY_CHARS + 500), "", NOON, NOON)
        self.assertEqual(len(self.store.memory()), memory.MAX_MEMORY_CHARS)

    def test_the_model_is_the_default_the_setting_or_the_environment(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop(memory.MODEL_ENV, None)
            self.assertEqual(self.store.model(), memory.DEFAULT_MODEL)
            self.store.folder.mkdir()
            self.store.settings_file.write_text('{"model": "claude-haiku-5-5"}')
            self.assertEqual(self.store.model(), "claude-haiku-5-5")
            env[memory.MODEL_ENV] = "claude-opus-5-5"
            self.assertEqual(self.store.model(), "claude-opus-5-5")


class NotedRunsTest(StoreCase):
    def test_a_run_is_noted_and_settled(self):
        entry = self.store.begin("a.txt", 11, "boot", now=NOON)
        self.assertEqual(load_store(self.store.state_file)["pending"], [entry])
        self.store.settle(entry, LATER)
        state = load_store(self.store.state_file)
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["last_awake"], "2026-11-26T09:12:00")

    def test_settling_never_moves_the_last_time_awake_back(self):
        self.store.settle(self.store.begin("a.txt", 1), LATER)
        self.store.settle(self.store.begin("b.txt", 2), NOON)
        self.assertEqual(self.store.last_awake(), "2026-11-26T09:12:00")

    def test_a_run_whose_process_is_gone_is_unfinished(self):
        gone = self.store.begin("gone.txt", 11, "boot")
        self.store.begin("alive.txt", 12, "boot")
        self.store.begin("mine.txt", 13, "boot")
        found = self.store.unfinished(lambda pid: pid == 12, "boot", my_pid=13)
        self.assertEqual(found, [gone])

    def test_a_run_from_before_a_restart_is_unfinished_whatever_its_number(self):
        old = self.store.begin("old.txt", 13, "earlier boot")
        self.assertEqual(self.store.unfinished(lambda pid: True, "boot", my_pid=13), [old])

    def test_settling_one_run_leaves_the_others(self):
        first = self.store.begin("a.txt", 1)
        second = self.store.begin("b.txt", 2)
        self.store.settle(first)
        self.assertEqual(load_store(self.store.state_file)["pending"], [second])


class PromptBlockTest(StoreCase):
    def test_the_first_time_it_says_there_is_nothing_yet(self):
        block = self.store.prompt_block(LATER)
        self.assertIn("You have no memories yet", block)
        self.assertIn("It is now Thursday 26 November 2026, 09:12.", block)
        self.assertNotIn("last awake", block)
        self.assertIn(str(self.datadir.chats_dir), block)

    def test_it_holds_the_memory_the_diary_and_the_time_that_passed(self):
        self.store.write("Roman likes tea.", "We talked about tea.", NOON, NOON)
        self.store.settle(self.store.begin("a.txt", 1), NOON)
        block = self.store.prompt_block(LATER)
        self.assertIn("You were last awake until Wednesday 25 November 2026, 12:00. "
                      "It is now Thursday 26 November 2026, 09:12.", block)
        self.assertIn("--- What you remember ---\nRoman likes tea.", block)
        self.assertIn("We talked about tea.", block)
        self.assertNotIn("no memories yet", block)

    def test_only_the_newest_diary_entries_are_told(self):
        for number in range(memory.DIARY_SHOWN + 2):
            self.store.write("m", f"talk number {number}.", NOON, NOON)
        block = self.store.prompt_block(LATER)
        self.assertNotIn("talk number 1.", block)
        self.assertIn("talk number 2.", block)
        self.assertIn(f"talk number {memory.DIARY_SHOWN + 1}.", block)


class TextsTest(StoreCase):
    def test_the_reply_is_taken_apart(self):
        self.assertEqual(memory.parse_reply("noise " + REMEMBERED),
                         ("The people I know\nRoman likes tea.", "Roman told me he likes tea."))

    def test_a_reply_without_a_memory_fails(self):
        for text in ("", "I cannot do that.", "<memory>  </memory><diary>x</diary>"):
            with self.assertRaises(memory.MemoryFailed):
                memory.parse_reply(text)

    def test_a_reply_without_a_diary_entry_is_taken(self):
        self.assertEqual(memory.parse_reply("<memory>m</memory>"), ("m", ""))

    def test_the_transcript_is_read_without_its_cost_lines(self):
        text = memory.read_transcript(self.transcript())
        self.assertNotIn("call 1:", text)
        self.assertIn("you> (heard) I like tea", text)

    def test_a_transcript_too_long_keeps_its_end(self):
        path = self.transcript("you> start\n" + "x" * memory.MAX_TRANSCRIPT_CHARS + "\nyou> end")
        text = memory.read_transcript(path)
        self.assertTrue(text.startswith("[... the beginning is left out ...]"))
        self.assertTrue(text.endswith("you> end"))

    def test_a_missing_transcript_is_empty(self):
        self.assertEqual(memory.read_transcript(self.datadir.chats_dir / "none.txt"), "")

    def test_a_run_nobody_replied_to_is_not_worth_remembering(self):
        self.assertFalse(memory.worth_remembering("you> Hi Otto\nrobot> Hello."))
        self.assertTrue(memory.worth_remembering(TALK))

    def test_a_goodbye_alone_is_not_a_reply(self):
        for last in ("you> (heard) Bye.", "you> stop", "you> ", "you>"):
            self.assertFalse(memory.worth_remembering("you> Hi Otto\nrobot> Hello.\n" + last))
        self.assertTrue(memory.worth_remembering("you> Hi Otto\nyou> (heard) Bye for now"))

    def test_the_request_carries_the_character_the_memory_and_the_transcript(self):
        self.store.write("Roman likes tea.", "We talked.", NOON, NOON)
        system, user = memory.request_texts(self.store, "you> hello", NOON, LATER)
        self.assertIn(prompts.character(), system)
        self.assertIn(f"under {memory.MAX_WORDS} words", system)
        self.assertIn("<old_memory>\nRoman likes tea.\n</old_memory>", user)
        self.assertIn("We talked.", user)
        self.assertIn("<transcript>\nyou> hello\n</transcript>", user)
        self.assertIn("Wednesday 25 November 2026, 12:00", user)

    def test_the_character_is_the_prompts_first_paragraph(self):
        self.assertTrue(prompts.base_system_prompt(True).startswith(prompts.character() + "\n\n"))
        self.assertIn("Your name is", prompts.character())


class RememberTest(StoreCase):
    def remember(self, script, entry, **more):
        self.console, self.out = piped_console("")
        self.client = FakeClient(script)
        return memory.remember(self.store, entry, self.client, self.console,
                               self.console.interrupts, **more)

    def test_a_conversation_is_put_into_memory(self):
        entry = self.store.begin(self.transcript(), 1, now=NOON)
        made, model = self.remember(
            [reply(text_block(REMEMBERED), model="claude-sonnet-5-5")], entry, ended=LATER)
        self.assertEqual(model, memory.DEFAULT_MODEL)
        self.assertEqual(made["input_tokens"], 100)
        self.assertIn("Roman likes tea.", self.store.memory())
        self.assertEqual(self.store.diary(),
                         ["## 2026-11-25 12:00 to 2026-11-26 09:12\nRoman told me he likes tea."])
        self.assertEqual(self.store.unfinished(lambda pid: False), [])
        self.assertEqual(self.store.last_awake(), "2026-11-26T09:12:00")

    def test_the_call_offers_no_tools_and_shows_nothing(self):
        entry = self.store.begin(self.transcript(), 1, now=NOON)
        self.remember([reply(text_block(REMEMBERED))], entry, ended=LATER)
        sent = self.client.requests[0]
        self.assertEqual(sent["model"], memory.DEFAULT_MODEL)
        self.assertNotIn("tools", sent)
        self.assertEqual(len(sent["messages"]), 1)
        self.assertNotIn("Roman likes tea", self.out.getvalue())

    def test_a_run_nobody_replied_to_costs_no_call_and_is_settled(self):
        entry = self.store.begin(self.transcript("you> Hi Otto\nrobot> Hello.\n"), 1, now=NOON)
        self.assertEqual(self.remember([], entry, ended=LATER), (None, None))
        self.assertEqual(self.store.memory(), "")
        self.assertEqual(self.store.unfinished(lambda pid: False), [])
        self.assertEqual(self.store.last_awake(), "2026-11-26T09:12:00")

    def test_a_reply_that_cannot_be_used_leaves_the_run_noted(self):
        self.store.write("old", "", NOON, NOON)
        entry = self.store.begin(self.transcript(), 1, now=NOON)
        with self.assertRaises(memory.MemoryFailed):
            self.remember([reply(text_block("Sorry."))], entry, ended=LATER)
        self.assertEqual(self.store.memory(), "old")
        self.assertEqual(self.store.unfinished(lambda pid: False), [entry])

    def test_a_reply_that_was_cut_off_is_not_used(self):
        entry = self.store.begin(self.transcript(), 1, now=NOON)
        with self.assertRaises(memory.MemoryFailed):
            self.remember([reply(text_block(REMEMBERED), stop_reason="max_tokens")], entry)
        self.assertEqual(self.store.memory(), "")

    def test_without_an_end_time_the_transcripts_own_time_is_used(self):
        entry = self.store.begin(self.transcript(), 1, now=NOON)
        self.remember([reply(text_block(REMEMBERED))], entry)
        self.assertGreater(self.store.last_awake(), "2026-11-25T12:00:00")

    def test_a_trial_changes_nothing(self):
        entry = {"transcript": str(self.transcript()), "started": ""}
        _usage, model, texts = self.remember(
            [reply(text_block(REMEMBERED))], entry, model="claude-haiku-5-5", keep=False)
        self.assertEqual(model, "claude-haiku-5-5")
        self.assertEqual(texts[1], "Roman told me he likes tea.")
        self.assertFalse(self.store.folder.exists())

    def test_show_prints_what_a_run_would_be_told(self):
        shown = io.StringIO()
        with mock.patch.dict("os.environ", {"ROBOT_DATA_DIR": str(self.datadir.root)}), \
                redirect_stdout(shown):
            self.assertEqual(memory.main(["show"]), 0)
        self.assertIn("You have no memories yet", shown.getvalue())


class NamedTest(StoreCase):
    def named(self, name):
        return memory.Store(self.datadir, name)

    def test_names_that_will_do_and_names_that_will_not(self):
        for name in ("", "night watch", "Otto-2", "a", "x" * memory.MAX_NAME, "7_up"):
            self.assertEqual(memory.name_problem(name), "", name)
        for name in (" lead", "trail ", "a/b", "..", "a.b", "-dash", "x" * (memory.MAX_NAME + 1),
                     "versions", "Off", "shared", "new", 7, None):
            self.assertNotEqual(memory.name_problem(name), "", name)
        with self.assertRaises(ValueError):
            self.named("a/b")

    def test_a_named_memory_is_a_folder_inside_the_shared_ones(self):
        store = self.named("night watch")
        self.assertEqual(store.folder, self.store.folder / "night watch")
        self.assertEqual(store.settings_file, self.store.settings_file)
        store.write("The door was shut.", "A quiet night.", NOON, NOON)
        self.assertEqual(store.memory(), "The door was shut.")
        self.assertEqual(self.store.memory(), "")
        self.assertFalse(self.store.exists())
        self.assertTrue(store.exists())

    def test_the_named_memories_are_listed_and_nothing_else_is(self):
        self.assertEqual(memory.names(self.datadir), [])
        self.store.write("one", "", NOON, NOON)
        self.store.write("two", "", NOON, NOON)    # makes the shared one's versions folder
        self.named("zebra").write("z", "", NOON, NOON)
        self.named("Alpha").write("a", "", NOON, NOON)
        self.assertEqual(memory.names(self.datadir), ["Alpha", "zebra"])

    def test_who_uses_a_memory(self):
        save_instructions(self.datadir, {
            "Talk": {"text": "x", "memory": True},
            "Guard": {"text": "x", "memory": True, "memory_name": "night watch"},
            "Second": {"text": "x", "memory": True, "memory_name": "night watch"},
            "Off": {"text": "x", "memory": False, "memory_name": "night watch"}})
        self.assertEqual(memory.users(self.datadir, ""), ["Talk"])
        self.assertEqual(memory.users(self.datadir, "night watch"), ["Guard", "Second"])
        self.assertEqual(memory.users(self.datadir, "other"), [])

    def test_a_copy_has_the_text_the_diary_and_the_time_but_no_past(self):
        self.store.write("one", "first", NOON, NOON)
        self.store.write("two", "second", NOON, NOON)
        self.store.settle(self.store.begin("a.txt", 1), LATER)
        copy = self.named("trial")
        self.store.copy_to(copy)
        self.assertEqual(copy.memory(), "two")
        self.assertEqual(len(copy.diary()), 2)
        self.assertEqual(copy.last_awake(), self.store.last_awake())
        self.assertEqual(copy.versions(), [])
        copy.write("three", "", NOON, NOON)
        self.assertEqual(self.store.memory(), "two")

    def test_rolling_back_keeps_the_state_it_leaves(self):
        self.store.write("one", "", NOON, NOON)
        self.store.write("two", "", NOON, NOON)
        self.store.roll_back(self.store.versions()[0])
        self.assertEqual(self.store.memory(), "one")
        kept = [path.read_text(encoding="utf-8").strip() for path in self.store.versions()]
        self.assertEqual(sorted(kept), ["one", "two"])

    def test_two_changes_in_one_second_keep_two_states(self):
        for text in ("one", "two", "three"):
            self.store.set_memory(text)
        self.assertEqual(len(self.store.versions()), 2)

    def test_deleting_a_named_memory_removes_its_folder_only(self):
        self.store.write("shared", "", NOON, NOON)
        named = self.named("trial")
        named.write("mine", "entry", NOON, NOON)
        named.delete()
        self.assertFalse(named.folder.exists())
        self.assertEqual(self.store.memory(), "shared")

    def test_deleting_the_shared_memory_keeps_the_named_ones_and_the_setting(self):
        self.store.write("one", "entry", NOON, NOON)
        self.store.write("two", "", NOON, NOON)
        self.store.settle(self.store.begin("a.txt", 1), NOON)
        self.store.settings_file.write_text('{"model": "claude-haiku-5-5"}')
        self.named("trial").write("mine", "", NOON, NOON)
        self.store.delete()
        self.assertFalse(self.store.exists())
        self.assertEqual(self.store.versions(), [])
        self.assertEqual(self.store.diary(), [])
        self.assertEqual(self.named("trial").memory(), "mine")
        self.assertEqual(self.store.model(), "claude-haiku-5-5")

    def test_the_setting_carries_the_name(self):
        settings, warnings = settings_from_entry(
            "A", {"text": "x", "memory": True, "memory_name": "night watch"})
        self.assertEqual((settings.memory, settings.memory_name, warnings),
                         (True, "night watch", []))
        self.assertIn("memory: night watch", describe("A", {
            "text": "x", "memory": True, "memory_name": "night watch"}))

    def test_a_name_without_the_switch_means_nothing(self):
        settings, _ = settings_from_entry("A", {"text": "x", "memory_name": "night watch"})
        self.assertEqual((settings.memory, settings.memory_name), (False, ""))

    def test_a_name_that_will_not_do_gives_a_run_without_memory_not_the_shared_one(self):
        settings, warnings = settings_from_entry(
            "A", {"text": "x", "memory": True, "memory_name": "../elsewhere"})
        self.assertEqual((settings.memory, settings.memory_name), (False, ""))
        self.assertIn("This run has no memory.", warnings[0])

    def test_the_tool_that_manages_instructions_takes_and_checks_the_name(self):
        running = RunSettings(name="Patrol", model="claude-haiku-5-5")
        call = lambda **params: manage_instructions(self.datadir, running, params)  # noqa: E731
        call(action="create", name="Guard", text="Watch", memory=True, memory_name="night watch")
        self.assertEqual(load_instructions(self.datadir)["Guard"]["memory_name"], "night watch")
        self.assertIn('"memory_name": "night watch"', call(action="read", name="Guard"))
        self.assertIn("Error", call(action="update", name="Guard", memory_name="a/b"))
        self.assertIn("Error", call(action="update", name="Guard", memory_name=7))
        self.assertEqual(load_instructions(self.datadir)["Guard"]["memory_name"], "night watch")
        call(action="update", name="Guard", memory_name="")
        self.assertEqual(load_instructions(self.datadir)["Guard"]["memory_name"], "")

    def test_the_command_line_lists_them(self):
        save_instructions(self.datadir, {"Talk": {"text": "x", "memory": True}})
        self.store.write("one two", "entry", NOON, NOON)
        self.named("trial").write("three", "", NOON, NOON)
        shown = io.StringIO()
        with mock.patch.dict("os.environ", {"ROBOT_DATA_DIR": str(self.datadir.root)}), \
                redirect_stdout(shown):
            self.assertEqual(memory.main(["list"]), 0)
            self.assertEqual(memory.main(["show", "--name", "trial"]), 0)
            self.assertEqual(memory.main(["show", "--name", "a/b"]), 2)
        text = shown.getvalue()
        self.assertIn("- shared: 2 words, 1 conversation in the diary; used by Talk", text)
        self.assertIn("- trial: 1 word, 0 conversations in the diary; used by no instruction",
                      text)
        self.assertIn("--- What you remember ---\nthree", text)


class QuietAgent(Agent):
    """An Agent without the machine's own tools, which differ from place to place."""

    def tool_registry(self):
        machine = set(available_tools())
        return {name: tool for name, tool in super().tool_registry().items()
                if name not in machine}


class AgentTest(StoreCase):
    def make(self, script, lines="", interrupts=None, **settings):
        self.console, self.out = piped_console(lines, interrupts=interrupts)
        self.client = FakeClient(script)
        settings.setdefault("text", "Hi Otto")
        settings.setdefault("conversational", True)
        settings.setdefault("memory", True)
        return QuietAgent(settings=RunSettings(**settings), console=self.console,
                          datadir=self.datadir, get_client=lambda: self.client)

    def system_text(self, request):
        return "\n".join(block["text"] for block in request["system"])

    def test_the_setting_comes_from_the_entry_and_is_off_unless_asked_for(self):
        self.assertFalse(settings_from_entry("A", {"text": "x"})[0].memory)
        self.assertTrue(settings_from_entry("A", {"text": "x", "memory": True})[0].memory)

    def test_the_tool_that_manages_instructions_sets_and_shows_it(self):
        running = RunSettings(name="Patrol", model="claude-haiku-5-5")
        manage_instructions(self.datadir, running,
                            {"action": "create", "name": "Talk", "text": "Hi", "memory": True})
        library = load_instructions(self.datadir)
        self.assertIs(library["Talk"]["memory"], True)
        shown = manage_instructions(self.datadir, running, {"action": "read", "name": "Talk"})
        self.assertIn('"memory": true', shown)
        manage_instructions(self.datadir, running,
                            {"action": "update", "name": "Talk", "memory": False})
        self.assertIs(load_instructions(self.datadir)["Talk"]["memory"], False)
        self.assertIn("memory", describe("Talk", library["Talk"]))

    def test_the_interfaces_top_row_names_it(self):
        from robot.tui.app import describe_instruction

        manage_instructions(self.datadir, RunSettings(model="claude-haiku-5-5"),
                            {"action": "create", "name": "Talk", "text": "Hi", "memory": True})
        self.assertEqual(describe_instruction(self.datadir, "Talk")[-1], "memory")

    def test_a_run_with_a_named_memory_reads_and_writes_that_one_only(self):
        self.store.write("Roman likes tea.", "", NOON, NOON)
        named = memory.Store(self.datadir, "night watch")
        named.write("The door was shut.", "", NOON, NOON)
        agent = self.make([reply(text_block("Hello.")), reply(text_block("Noted.")),
                           reply(text_block(REMEMBERED))],
                          lines="The window is open\n", memory_name="night watch")
        agent.run()
        told = self.system_text(self.client.requests[0])
        self.assertIn("The door was shut.", told)
        self.assertNotIn("Roman likes tea.", told)
        self.assertIn("<old_memory>\nThe door was shut.",
                      self.client.requests[-1]["messages"][0]["content"][0]["text"])
        self.assertIn("The people I know", named.memory())
        self.assertEqual(self.store.memory(), "Roman likes tea.")
        self.assertEqual(self.store.diary(), [])
        self.assertEqual(len(named.diary()), 1)

    def test_a_run_without_memory_is_as_before(self):
        agent = self.make([reply(text_block("Hello."))], memory=False, conversational=False)
        self.assertEqual(agent.run(), "completed")
        self.assertEqual(len(self.client.requests), 1)
        self.assertNotIn("Your memory.", self.system_text(self.client.requests[0]))
        self.assertFalse(self.store.folder.exists())

    def test_the_run_is_told_its_memory_in_the_block_that_is_not_cached(self):
        self.store.write("Roman likes tea.", "We talked about tea.", NOON, NOON)
        agent = self.make([reply(text_block("Hello."))])
        agent.run()
        blocks = self.client.requests[0]["system"]
        self.assertNotIn("Roman likes tea.", blocks[0]["text"])
        self.assertIn("cache_control", blocks[0])
        self.assertIn("Roman likes tea.", blocks[1]["text"])
        self.assertNotIn("cache_control", blocks[1])
        self.assertTrue(blocks[1]["text"].rstrip().endswith(agent.run_facts.split("\n\n")[-1]))
        self.assertIn("About this run", blocks[1]["text"])

    def test_the_conversation_is_remembered_when_the_run_ends(self):
        agent = self.make([reply(text_block("Hello.")), reply(text_block("Noted.")),
                           reply(text_block(REMEMBERED), model="claude-sonnet-5-5")],
                          lines="I like tea\n")
        self.assertEqual(agent.run(), "completed")
        self.assertEqual(self.client.remaining, 0)
        self.assertIn("Roman likes tea.", self.store.memory())
        self.assertEqual(len(self.store.diary()), 1)
        self.assertEqual(load_store(self.store.state_file)["pending"], [])
        shown = self.out.getvalue()
        self.assertIn("Remembering this conversation...", shown)
        self.assertIn("Remembered, by claude-sonnet-5-5", shown)
        # The call that remembers is sent what was said, and no tools.
        sent = self.client.requests[-1]
        self.assertEqual(sent["model"], memory.DEFAULT_MODEL)
        self.assertNotIn("tools", sent)
        self.assertIn("you> I like tea", sent["messages"][0]["content"][0]["text"])

    def test_its_cost_is_on_the_runs_own_line_of_the_cost_log(self):
        agent = self.make([reply(text_block("Hello."), model="claude-haiku-5-5"),
                           reply(text_block("Noted."), model="claude-haiku-5-5"),
                           reply(text_block(REMEMBERED), model="claude-sonnet-5-5",
                                 usage_=usage(input_tokens=1000, output_tokens=500))],
                          lines="I like tea\n", model="claude-haiku-5-5")
        agent.run()
        self.assertIn("claude-sonnet-5-5", agent.run_cost.per_model)
        self.assertIn("claude-haiku-5-5", agent.run_cost.per_model)
        lines = self.datadir.costlog_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("claude-sonnet-5-5", lines[0])

    def test_a_run_nobody_replied_to_is_not_sent_anywhere(self):
        agent = self.make([reply(text_block("Hello."))])
        agent.run()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.store.memory(), "")
        self.assertNotEqual(self.store.last_awake(), "")

    def test_a_failure_to_remember_warns_and_leaves_the_run_noted(self):
        agent = self.make([reply(text_block("Hello.")), reply(text_block("Noted.")),
                           reply(text_block("Sorry."))], lines="I like tea\n")
        self.assertEqual(agent.run(), "completed")
        self.assertIn("was not put into memory", self.out.getvalue())
        self.assertEqual(len(load_store(self.store.state_file)["pending"]), 1)
        self.assertTrue(self.datadir.costlog_file.exists())

    def test_a_program_that_is_being_closed_leaves_it_for_the_next_start(self):
        interrupts = NoWaitInterrupts()

        def closing(_request):
            interrupts.stop.set()
            return reply(text_block("Hello."))

        agent = self.make([closing], interrupts=interrupts, lines="I like tea\n")
        agent.run()
        self.assertEqual(len(self.client.requests), 1)
        self.assertIn("will be remembered at the next start", self.out.getvalue())
        self.assertEqual(len(load_store(self.store.state_file)["pending"]), 1)

    def test_the_next_start_makes_up_for_a_run_that_never_remembered(self):
        earlier = self.store.begin(self.transcript(), 999999, "an earlier start", now=NOON)
        self.assertTrue(earlier)
        agent = self.make([reply(text_block(REMEMBERED)), reply(text_block("Hello."))])
        with mock.patch.object(costs, "process_is_robot", lambda pid: False):
            agent.run()
        self.assertIn("Remembering an earlier conversation first...", self.out.getvalue())
        # The first call remembered; the run itself was then told the result.
        self.assertNotIn("tools", self.client.requests[0])
        self.assertIn("Roman likes tea.", self.system_text(self.client.requests[1]))
        self.assertEqual(load_store(self.store.state_file)["pending"], [])

    def test_a_dry_run_shows_the_memory_and_remembers_nothing(self):
        self.store.write("Roman likes tea.", "", NOON, NOON)
        self.store.begin(self.transcript(), 999999, "an earlier start", now=NOON)
        self.console, self.out = piped_console("")
        agent = QuietAgent(settings=RunSettings(text="Hi", memory=True), console=self.console,
                           datadir=self.datadir, get_client=lambda: self.fail("no client"),
                           dry_run=True)
        agent.run()
        self.assertIn("Roman likes tea.", self.out.getvalue())
        self.assertEqual(len(load_store(self.store.state_file)["pending"]), 1)

    def test_the_transcript_of_the_run_is_what_was_noted(self):
        agent = self.make([reply(text_block("Hello."))])
        noted = []
        real = memory.Store.begin

        def begin(store, transcript, *rest, **more):
            noted.append(Path(transcript))
            return real(store, transcript, *rest, **more)

        with mock.patch.object(memory.Store, "begin", begin):
            agent.run()
        self.assertEqual(noted, [self.datadir.chats_dir / f"{agent.chat_stem}.txt"])


if __name__ == "__main__":
    unittest.main()
