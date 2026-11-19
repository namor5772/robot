"""The main window, and runs carried out through it against a scripted model."""

import contextlib
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from robot.datastore import load_store
from robot.tui import app as tui_app
from robot.tui.app import STATE_FILE, OutputBuffer, UiConsole, UiInterrupts, top_line
from robot.tui.screen import Mouse, Paste
from tests.fakes import FakeClient, InterruptDuring, bad_request, reply, text_block, tool_use
from tests.tui_fakes import AppCase, Check, FakeScreen, Until, typed

TASK = {"text": "Say that it is done.", "model": "claude-haiku-5-5", "thinking_mode": "low"}
CHAT = {"text": "", "model": "claude-haiku-5-5", "thinking_mode": "low", "conversational": True}
TALK = dict(CHAT, text="Greet the person.")


def said(message) -> str:
    """The text of a user message as it was sent, with or without cache marks."""
    content = message["content"]
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block.get("type") == "text")


class MainCase(AppCase):
    def setUp(self):
        super().setUp()
        self.library(Task=dict(TASK), Chat=dict(CHAT), Talk=dict(TALK))
        # The runner checks for a key before it starts a run. No test here
        # reaches the network: the client is a scripted stand-in.
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "not-a-real-key"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def shows(self, *texts):
        def check(screen):
            for text in texts:
                self.assertIsNotNone(screen.find(text), f"{text!r} is not on screen:\n"
                                     + screen.text())
        return Check(check)

    def lacks(self, *texts):
        def check(screen):
            for text in texts:
                self.assertIsNone(screen.find(text), f"{text!r} is on screen:\n" + screen.text())
        return Check(check)

    def asked(self):
        return Until(lambda: self.app.asking, "the robot to wait for a message")

    def ended(self):
        return Until(lambda: not self.app.running, "the run to end")

    def run_with(self, instruction, script, *keys):
        """Run an instruction against scripted replies. Returns the fake client."""
        client = FakeClient(script)
        self.start_runner(client)
        self.make_app(instruction=instruction)
        self.drive(*keys)
        return client


class TheWindow(MainCase):
    def test_what_the_main_window_shows(self):
        self.drive(self.shows(
            "Robot  |  Default  |  claude-opus-5-5 (Low)  |  conversation  |  meta",
            "[ START ]", "[ STOP ]", "[ Instruction ]", "[ Skills ]", "[ Help ]", "[ Quit ]",
            "Output", "Your message (the robot is not waiting for one)",
            "[x] Activity", "[ ] Thinking", "[ ] Tool calls", "[ ] Debug", "[ ] Save thinking",
            "Ready", "F1 Help"))

    def test_stop_is_off_and_start_does_not_have_the_focus_at_first(self):
        self.drive(Check(lambda screen: (
            self.assertEqual(screen.style_at("[ START ]"), "button"),
            self.assertEqual(screen.style_at("[ Instruction ]"), "button_focus"),
            self.assertEqual(screen.style_at("[ STOP ]"), "button_off"))))

    def test_an_instruction_can_be_named_when_the_program_starts(self):
        self.make_app(instruction="Task")
        self.drive(self.shows("Robot  |  Task  |  claude-haiku-5-5 (Low)  |  single task"))

    def test_a_name_that_does_not_exist_falls_back_to_default(self):
        self.make_app(instruction="No such thing")
        self.drive(self.shows("Robot  |  Default"))

    def test_a_long_name_gives_way_to_the_settings_in_the_top_row(self):
        name = "A very long name for an instruction indeed"
        self.library(**{name: dict(TASK, meta=True)})
        self.make_app(instruction=name)
        self.drive(
            Check(lambda screen: self.assertEqual(
                screen.line(0), " Robot  |  A very long n...  |  claude-haiku-5-5 (Low)  |  "
                                "single task  |  meta")),
            "f4", self.shows("Name: " + name))       # the editor has the name in full

    def test_the_top_row_keeps_the_settings_in_the_smallest_window(self):
        name = "A very long name for an instruction indeed"
        self.library(**{name: {"text": "x", "model": "claude-haiku-5-5-20261007",
                               "thinking_mode": "adaptive", "meta": True}})
        self.screen = FakeScreen(tui_app.MIN_ROWS, tui_app.MIN_COLS)
        self.make_app(instruction=name)
        self.drive(Check(lambda screen: self.assertEqual(
            screen.line(0),
            " A very... | claude-haiku-5-5-20261007 (Adaptive) | single task | meta")))

    def test_a_first_start_makes_the_default_instruction(self):
        self.datadir.instructions_file.unlink()
        self.drive(self.shows("Robot  |  Default  |  claude-opus-5-5 (Low)"))
        self.assertIn("Default", load_store(self.datadir.instructions_file))

    def test_help(self):
        self.drive("f1", self.shows("Help", "GETTING AROUND", "Tab, Shift+Tab"),
                   "pgdn", "pgdn", "pgdn", self.shows("INSIDE TMUX"), "esc",
                   self.lacks("GETTING AROUND"), self.shows("[ START ]"))

    def test_a_window_that_is_too_small_says_so(self):
        self.screen = FakeScreen(10, 40)

        def grow(screen):
            self.assertIsNotNone(screen.find("This window is too small: 40 x 10."))
            self.assertIsNone(screen.find("START"))
            screen.rows, screen.cols = 30, 100

        # Keys are ignored while the windows cannot be shown.
        self.drive(Check(grow), "f1", "resize", self.shows("[ START ]"),
                   self.lacks("too small", "GETTING AROUND"),
                   Check(lambda screen: self.assertEqual(self.app.main.output.w, 100)))

    def test_the_windows_fit_the_smallest_size_allowed(self):
        self.screen = FakeScreen(tui_app.MIN_ROWS, tui_app.MIN_COLS)
        # FakeScreen fails on anything drawn outside it, so opening is the test.
        self.drive(self.shows("[ START ]", "[ Quit ]", "Save thinking"),
                   "f4", self.shows("[ Save ]", "[ Close ]", "Convo"), "alt+l", "esc",
                   "alt+k", "esc", "alt+g", "esc", "alt+t", "esc", "alt+o", "esc", "esc",
                   "f5", self.shows("[ Cycle mode ]"), "alt+e", "esc", "esc",
                   "f1", "esc")

    def test_a_click_presses_a_button(self):
        def click_help(screen):
            y, x = screen.find("[ Help ]")
            screen.feed(Mouse("click", y, x + 3), self.shows("GETTING AROUND"), "esc")
        self.drive(Check(click_help))

    def test_quit_ends_the_program(self):
        self.drive("f10", "f1")            # the F1 is never read
        self.assertTrue(self.app.quitting)
        self.assertEqual(len(self.screen.script), 1)

    def test_escape_does_not_leave_the_main_window(self):
        self.drive("esc", "esc", self.shows("[ START ]"))
        self.assertFalse(self.app.quitting)


class TopLine(unittest.TestCase):
    """The top row: when it is too long, the name gives way, not the settings."""

    SHORT = ["claude-opus-5-5 (Low)", "conversation", "meta"]
    LONG = ["claude-haiku-5-5-20261007 (Adaptive)", "single task", "meta"]   # the longest there is
    NAME = "Morning report for the garden"

    def test_a_row_that_fits_is_shown_whole(self):
        self.assertEqual(top_line(["Default"] + self.SHORT, 78),
                         "Robot  |  Default  |  claude-opus-5-5 (Low)  |  conversation  |  meta")
        self.assertEqual(top_line(["Old one", "not saved yet"], 78),
                         "Robot  |  Old one  |  not saved yet")

    def test_a_long_name_is_cut_and_marked_with_dots(self):
        row = top_line([self.NAME] + self.SHORT, 78)
        self.assertEqual(
            row, "Robot  |  Morning repor...  |  claude-opus-5-5 (Low)  |  conversation  |  meta")
        self.assertEqual(len(row), 78)                   # every cell of the row is used

    def test_before_the_name_gets_short_the_word_robot_goes(self):
        # In a window of 72 columns the name would be down to "Morni..."
        # beside the word Robot. Robot says nothing new, so the name gets its
        # room. The dots follow the last letter, not the space after a word.
        self.assertEqual(
            top_line([self.NAME] + self.SHORT, 70),
            "Morning report...  |  claude-opus-5-5 (Low)  |  conversation  |  meta")

    def test_a_name_that_fits_once_robot_is_gone_is_shown_whole(self):
        self.assertEqual(
            top_line(["Twelve chars"] + self.LONG, 78),
            "Twelve chars  |  claude-haiku-5-5-20261007 (Adaptive)  |  single task  |  meta")

    def test_without_robot_the_name_may_get_shorter_still(self):
        self.assertEqual(
            top_line(["Morning report"] + self.LONG, 78),
            "Morning r...  |  claude-haiku-5-5-20261007 (Adaptive)  |  single task  |  meta")

    def test_and_then_the_dividers_close_up(self):
        self.assertEqual(
            top_line(["Morning report"] + self.LONG, 70),
            "Morning... | claude-haiku-5-5-20261007 (Adaptive) | single task | meta")

    def test_the_settings_fit_the_smallest_window_whatever_the_name(self):
        width = tui_app.MIN_COLS - 2
        for name in ("x", "Default", "A name that goes on and on and on"):
            with self.subTest(name=name):
                row = top_line([name] + self.LONG, width)
                self.assertLessEqual(len(row), width)
                self.assertTrue(row.endswith("meta"), row)
                for part in self.LONG:
                    self.assertIn(part, row)

    def test_a_name_is_only_cut_when_it_is_the_longer_for_it(self):
        # "Default" would not gain from being "Defau...": it is kept whole,
        # and the row finds its room elsewhere.
        row = top_line(["Default"] + self.LONG, 70)
        self.assertEqual(row,
                         "Default | claude-haiku-5-5-20261007 (Adaptive) | single task | meta")

    def test_only_when_nothing_else_gives_is_the_end_cut_off(self):
        whole = "Default | claude-haiku-5-5-20261007 (Adaptive) | single task | meta"
        self.assertEqual(top_line(["Default"] + self.LONG, 40), whole[:40])
        self.assertEqual(top_line([self.NAME] + self.LONG, 40),
                         "Morni... | claude-haiku-5-5-20261007 (Ad")
        self.assertEqual(top_line([self.NAME] + self.LONG, 0), "")

    def test_a_session_name_follows_the_word_robot(self):
        self.assertEqual(
            top_line(["Default"] + self.SHORT, 78, "2"),
            "Robot 2  |  Default  |  claude-opus-5-5 (Low)  |  conversation  |  meta")

    def test_the_session_name_stays_when_the_word_robot_goes(self):
        # It is what tells two copies of the interface apart.
        self.assertEqual(
            top_line([self.NAME] + self.SHORT, 70, "2"),
            "2  |  Morning r...  |  claude-opus-5-5 (Low)  |  conversation  |  meta")

    def test_with_a_session_name_the_settings_still_fit_the_smallest_window(self):
        # The name of the instruction gives way down to its first letters.
        self.assertEqual(
            top_line(["Morning report"] + self.LONG, tui_app.MIN_COLS - 2, "2"),
            "2 | Mor... | claude-haiku-5-5-20261007 (Adaptive) | single task | meta")

    def test_a_name_is_measured_in_cells_not_characters(self):
        wide = chr(0x4e2d) * 20                           # twenty characters, forty cells
        row = top_line([wide] + self.SHORT, 78)
        self.assertLessEqual(tui_app.text_width(row), 78)
        self.assertIn(chr(0x4e2d) * 6 + "...  |  claude-opus-5-5 (Low)", row)
        self.assertTrue(row.endswith("  |  meta"))


class DisplaySwitches(MainCase):
    def test_the_boxes_set_what_a_run_shows(self):
        self.drive("alt+t", "alt+c", "alt+d", "alt+a",
                   self.shows("[ ] Activity", "[x] Thinking", "[x] Tool calls", "[x] Debug"))
        console = self.console
        self.assertEqual((console.activity_on, console.show_thinking, console.tool_calls_on,
                          console.debug_on), (False, True, True, True))

    def test_the_boxes_are_remembered(self):
        self.drive("alt+t", "alt+v")
        state = load_store(self.datadir.root / STATE_FILE)
        self.assertEqual((state["thinking"], state["save_thinking"], state["activity"]),
                         (True, True, True))
        self.app = None
        self.console = UiConsole(self.bridge, self.interrupts)
        self.drive(self.shows("[x] Thinking", "[x] Save thinking", "[x] Activity"))
        self.assertTrue(self.console.show_thinking)

    def test_a_state_file_with_junk_in_it_is_survivable(self):
        (self.datadir.root / STATE_FILE).write_text("not json at all", encoding="utf-8")
        self.drive(self.shows("[x] Activity", "Robot  |  Default"))


class Sessions(MainCase):
    """Several copies of the interface open at once, each with a name (--session)."""

    def fresh_copy(self, **options):
        self.app = None
        self.console = UiConsole(self.bridge, self.interrupts)
        return self.make_app(**options)

    def test_a_named_copy_says_so_in_the_top_row(self):
        self.make_app(session="2")
        self.drive(self.shows("Robot 2  |  Default  |  claude-opus-5-5 (Low)"))

    def test_the_first_copy_has_no_name_to_show(self):
        self.drive(Check(lambda screen: self.assertTrue(
            screen.line(0).startswith(" Robot  |  Default"))))

    def test_each_copy_keeps_its_settings_in_a_file_of_its_own(self):
        self.assertEqual(tui_app.state_file_name(), STATE_FILE)
        self.assertEqual(tui_app.state_file_name("2"), "tui_state_2.json")
        self.assertEqual(tui_app.state_file_name("garden"), "tui_state_garden.json")

    def test_each_copy_remembers_its_own_instruction_and_boxes(self):
        self.drive("alt+t")                                  # the first copy: Thinking on
        self.fresh_copy(session="2")
        self.drive("f4", "end", "alt+u", "alt+d")            # the second: uses Task, Debug on
        first = load_store(self.datadir.root / STATE_FILE)
        second = load_store(self.datadir.root / "tui_state_2.json")
        self.assertEqual((first["instruction"], first["thinking"], first["debug"]),
                         ("Default", True, False))
        self.assertEqual((second["instruction"], second["thinking"], second["debug"]),
                         ("Task", False, True))
        # Started again, each shows what it had, not what the other had.
        self.fresh_copy(session="2")
        self.drive(self.shows("Robot 2  |  Task", "[ ] Thinking", "[x] Debug"))
        self.fresh_copy()
        self.drive(self.shows("Robot  |  Default", "[x] Thinking", "[ ] Debug"))

    def test_a_new_copy_starts_on_default_whatever_the_others_use(self):
        self.make_app(instruction="Task")
        self.drive("alt+a")                                  # saves the first copy's settings
        self.fresh_copy(session="3")
        self.drive(self.shows("Robot 3  |  Default", "[x] Activity"))

    def test_the_copies_share_the_library(self):
        self.make_app(session="2")
        self.drive("f4", self.shows("Chat", "Default  (in use)", "Talk", "Task"))


class SingleTask(MainCase):
    def test_start_runs_the_instruction_and_shows_the_reply(self):
        client = self.run_with(
            "Task", [reply(text_block("It is done."))],
            "f2", self.ended(),
            self.shows("Robot agent: instruction 'Task'. Single task on claude-haiku-5-5",
                       "robot> It is done.", "call 1:", "--- run ended: completed",
                       "Run ended: completed", "Ready"))
        self.assertEqual([said(message) for message in client.requests[0]["messages"]],
                         ["Say that it is done."])
        self.assertEqual(client.requests[0]["model"], "claude-haiku-5-5")

    def test_the_buttons_follow_the_run(self):
        hold = InterruptDuring(reply(text_block("Half")), self.interrupts)
        waiting = []

        def held(_request):
            waiting.append(True)
            self.interrupts.interrupt.wait(20)     # until STOP is pressed
            return hold

        self.run_with(
            "Task", [held], "f2", Until(lambda: waiting, "the model to be called"),
            Check(lambda screen: (
                self.assertEqual(screen.style_at("[ START ]"), "button_off"),
                self.assertEqual(screen.style_at("[ STOP ]"), "button"),
                self.assertIsNotNone(screen.find("Working 0:0")))),
            "f2",                                  # START does nothing during a run
            "f3", self.ended(),
            self.shows("Agent stopped by user.", "--- run ended: stopped"),
            Check(lambda screen: (
                self.assertEqual(screen.style_at("[ STOP ]"), "button_off"),
                self.assertNotEqual(screen.style_at("[ START ]"), "button_off"))))

    def test_the_run_is_recorded_like_any_other(self):
        self.run_with("Task", [reply(text_block("It is done."))], "f2", self.ended())
        chats = sorted(path.name for path in self.datadir.chats_dir.iterdir())
        self.assertEqual(len(chats), 2, chats)
        self.assertTrue(all(name.startswith("Task_") for name in chats))
        transcript = next(self.datadir.chats_dir.glob("*.txt")).read_text(encoding="utf-8")
        self.assertIn("you> Say that it is done.", transcript)
        self.assertIn("robot> It is done.", transcript)
        self.assertIn(";Task;", self.datadir.costlog_file.read_text(encoding="utf-8"))
        self.assertEqual(list(self.datadir.runs_dir.iterdir()), [])

    def test_one_run_after_another(self):
        client = self.run_with(
            "Task", [reply(text_block("First answer.")), reply(text_block("Second answer."))],
            "f2", self.ended(), "f2", self.ended(), self.shows("robot> Second answer."))
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(len(list(self.datadir.chats_dir.glob("*.json"))), 2)

    def test_start_clears_the_output_of_the_run_before(self):
        self.run_with(
            "Task", [reply(text_block("First answer.")), reply(text_block("Second answer."))],
            "f2", self.ended(), self.shows("robot> First answer."),
            "f2", self.ended(), self.shows("robot> Second answer."),
            self.lacks("robot> First answer."))
        shown = " | ".join(line.text for line in self.app.main.output.buffer.lines)
        self.assertNotIn("First answer.", shown)        # gone, not just scrolled away
        self.assertEqual(shown.count("--- run ended: completed"), 1)
        self.assertFalse(shown.startswith(" | "), shown)  # no empty line left at the top

    def test_start_while_looking_back_shows_the_new_run(self):
        self.run_with(
            "Task", [reply(text_block("First answer.")), reply(text_block("Second answer."))],
            "f2", self.ended(), Check(lambda screen: self.look_back()),
            "f2", self.ended(), self.shows("robot> Second answer."))
        self.assertTrue(self.app.main.output.buffer.follow)

    def look_back(self):
        buffer = self.app.main.output.buffer
        buffer.follow = False
        buffer.anchor = (buffer.first, 0)

    def test_a_refused_start_leaves_the_output_alone(self):
        def forget(screen):
            self.app.instruction = "Nobody"
        self.run_with(
            "Task", [reply(text_block("First answer."))],
            "f2", self.ended(), Check(forget), "f2",
            self.shows("There is no saved instruction"), "enter",
            self.shows("robot> First answer."))

    def test_a_cleared_buffer_starts_afresh(self):
        buffer = OutputBuffer()
        buffer.add("one\ntwo\nunfinished")
        buffer.scroll(40, 2, -1)
        buffer.clear()
        self.assertEqual(buffer.view(40, 5), [])
        buffer.add("new\n")
        self.assertEqual([line.text for line in buffer.lines], ["new"])
        self.assertTrue(buffer.follow)

    def test_a_question_from_the_model_is_answered_in_the_reply_box(self):
        client = self.run_with(
            "Task", [reply(tool_use("user_prompt", {"message": "Which colour?"})),
                     reply(text_block("Blue it is."))],
            "f2", self.asked(),
            self.shows("robot asks> Which colour?", "Waiting for your message",
                       "Your message (Enter sends, Ctrl+J starts a new line)"),
            typed("blue"), "enter", self.ended(),
            self.shows("you> blue", "robot> Blue it is.",
                       "Your message (the robot is not waiting for one)"))
        answer = client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual((answer["type"], answer["content"]), ("tool_result", "blue"))

    def test_stop_at_a_question_ends_the_run(self):
        client = self.run_with(
            "Task", [reply(tool_use("user_prompt", {"message": "Which colour?"})),
                     reply(text_block("Never said."))],
            "f2", self.asked(), "f3", self.ended(), self.shows("--- run ended: stopped"),
            self.lacks("Never said."))
        self.assertEqual(len(client.requests), 1)

    def test_an_error_from_the_api_ends_the_run_and_is_shown(self):
        self.run_with("Task", [bad_request("the request was malformed")],
                      "f2", self.ended(),
                      self.shows("error:", "the request was malformed",
                                 "--- run ended: error", "Ready"))

    def test_an_instruction_deleted_meanwhile_is_reported(self):
        def delete_it(screen):
            self.datadir.instructions_file.write_text("{}", encoding="utf-8")
        client = self.run_with("Task", [], Check(delete_it), "f2",
                               self.shows("There is no saved instruction named 'Task'."),
                               "enter")
        self.assertFalse(self.app.running)
        self.assertEqual(client.requests, [])

    def test_without_an_api_key_nothing_is_sent(self):
        with mock.patch.dict(os.environ):
            del os.environ["ANTHROPIC_API_KEY"]
            client = self.run_with("Task", [], "f2", self.ended(),
                                   self.shows("error: No ANTHROPIC_API_KEY found.",
                                              "--- run ended: error"))
        self.assertEqual(client.requests, [])


class Conversation(MainCase):
    def test_an_instruction_without_text_asks_for_the_task(self):
        client = self.run_with(
            "Chat", [reply(text_block("Hello there.")), reply(text_block("Still here."))],
            "f2", self.asked(),
            self.shows("This instruction has no saved task. Type it as your message."),
            typed("hi robot"), "enter", self.asked(),
            self.shows("you> hi robot", "robot> Hello there."),
            typed("and again"), "enter", self.asked(), self.shows("robot> Still here."),
            typed("exit"), "enter", self.ended(),
            self.shows("Conversation ended.", "--- run ended: completed"))
        self.assertEqual([said(message) for message in client.requests[0]["messages"]],
                         ["hi robot"])
        self.assertEqual(said(client.requests[1]["messages"][-1]), "and again")

    def test_the_reply_box_takes_the_focus_when_the_robot_waits(self):
        def focus_is_on_the_reply(screen):
            self.assertIs(self.app.main.focused(), self.app.main.reply)
            self.assertIsNotNone(screen.cursor)

        self.run_with("Talk", [reply(text_block("Hello."))], "f2", self.asked(),
                      Check(focus_is_on_the_reply))

    def test_typing_goes_to_the_reply_box_wherever_the_focus_is(self):
        client = self.run_with(
            "Talk", [reply(text_block("Hello.")), reply(text_block("Noted."))],
            "f2", self.asked(), "alt+o", "pgup", typed("from afar"), "enter", self.asked())
        self.assertEqual(said(client.requests[1]["messages"][-1]), "from afar")

    def test_pasted_text_goes_to_the_reply_box_too(self):
        client = self.run_with(
            "Talk", [reply(text_block("Hello.")), reply(text_block("Noted."))],
            "f2", self.asked(), "alt+a", "alt+a", Paste("two\nlines"), "enter", self.asked())
        self.assertEqual(said(client.requests[1]["messages"][-1]), "two\nlines")

    def test_a_message_of_several_lines(self):
        client = self.run_with(
            "Talk", [reply(text_block("Hello.")), reply(text_block("Noted."))],
            "f2", self.asked(), typed("one"), "ctrl+j", typed("two"), "enter", self.asked(),
            self.shows("you> one", "two"))
        self.assertEqual(said(client.requests[1]["messages"][-1]), "one\ntwo")

    def test_an_empty_message_is_not_sent(self):
        client = self.run_with(
            "Talk", [reply(text_block("Hello."))], "f2", self.asked(), "enter", typed("  "),
            "enter", self.shows("Type a message first.", "Waiting for your message"))
        self.assertTrue(self.app.asking)
        self.assertEqual(len(client.requests), 1)

    def test_nothing_can_be_typed_while_the_robot_is_not_waiting(self):
        self.run_with("Talk", [], "alt+o", typed("hello?"), "enter", self.lacks("hello?"))
        self.assertEqual(self.app.main.reply.text(), "")
        self.assertFalse(self.app.running)

    def test_a_stray_enter_never_starts_a_run(self):
        # Enter presses the button with the focus, so the focus is never left
        # on START: not when the program opens, and not when a run ends.
        def focus_is_not_on_start(screen):
            self.assertIsNot(self.app.main.focused(), self.app.main.start)

        client = self.run_with(
            "Task", [reply(text_block("Done."))], Check(focus_is_not_on_start),
            "alt+s", self.ended(), Check(focus_is_not_on_start), "enter", "enter")
        self.assertFalse(self.app.running)
        self.assertEqual(len(client.requests), 1)

    def test_stop_while_the_robot_waits_ends_the_conversation(self):
        self.run_with("Talk", [reply(text_block("Hello."))], "f2", self.asked(), "ctrl+c",
                      self.ended(), self.shows("Conversation ended.",
                                               "--- run ended: completed"))

    def test_stop_at_the_first_message_means_nothing_is_run(self):
        client = self.run_with("Chat", [], "f2", self.asked(), "f3", self.ended(),
                               self.shows("(nothing was run)", "--- run ended: stopped"))
        self.assertEqual(client.requests, [])
        self.assertEqual(list(self.datadir.chats_dir.iterdir()), [])

    def test_stop_during_a_reply_returns_to_the_reply_box(self):
        waiting = []

        def cut_short(_request):
            waiting.append(True)
            self.interrupts.interrupt.wait(20)     # until STOP is pressed
            return InterruptDuring(reply(text_block("A long answer that is cut")),
                                   self.interrupts)

        client = self.run_with(
            "Talk", [cut_short, reply(text_block("Shorter."))],
            "f2", Until(lambda: waiting, "the model to be called"), "f3", self.asked(),
            self.shows("robot> A long answer that is cut", "(stopped)"),
            self.lacks("Stopping..."),               # that note went when the stop was done
            typed("briefly please"), "enter", self.asked(), self.shows("robot> Shorter."))
        self.assertTrue(self.app.running)
        self.assertEqual(said(client.requests[1]["messages"][-1]), "briefly please")

    def test_the_clock_starts_again_with_each_message_sent(self):
        # "Working 0:07" is how long the robot has been at it, not how long
        # ago START was pressed with the person's thinking time in between.
        app = self.make_app()
        app.asking = True
        app.started = 0.0
        with mock.patch.object(tui_app.time, "monotonic", return_value=1234.5):
            self.assertTrue(app.send_reply("hello"))
        self.assertEqual(app.started, 1234.5)
        self.assertEqual(self.bridge.replies.get_nowait(), "hello")
        self.assertFalse(app.send_reply("again"))        # nobody is asking any more

    def test_an_error_from_the_api_returns_to_the_reply_box(self):
        self.run_with(
            "Talk", [bad_request("no good"), reply(text_block("Better now."))],
            "f2", self.asked(), self.shows("error:", "no good"),
            typed("try again"), "enter", self.asked(), self.shows("robot> Better now."))
        self.assertTrue(self.app.running)

    def test_an_end_word_ends_the_conversation(self):
        client = self.run_with("Talk", [reply(text_block("Hello."))], "f2", self.asked(),
                               typed("Bye."), "enter", self.ended(),
                               self.shows("you> Bye.", "Conversation ended."))
        self.assertEqual(len(client.requests), 1)


class Quitting(MainCase):
    def test_quit_during_a_run_asks_and_no_carries_on(self):
        self.run_with("Talk", [reply(text_block("Hello."))], "f2", self.asked(), "f10",
                      self.shows("A run is in progress. Stop it and quit?"), "n",
                      self.shows("Waiting for your message"))
        self.assertTrue(self.app.running)
        self.assertFalse(self.app.quitting)

    def test_quit_during_a_run_stops_it_first(self):
        self.run_with("Talk", [reply(text_block("Hello."))], "f2", self.asked(), "f10", "y")
        self.assertTrue(self.app.quitting)
        self.assertFalse(self.app.running)       # the run wound down before the window went
        self.assertTrue(self.interrupts.stop.is_set())
        self.assertIn(";Talk;", self.datadir.costlog_file.read_text(encoding="utf-8"))
        self.assertEqual(load_store(self.datadir.root / STATE_FILE)["instruction"], "Talk")

    def test_a_signal_to_end_the_process_closes_the_window(self):
        self.drive(Check(lambda screen: self.interrupts.stop.set()), "f1", "f1")
        self.assertTrue(self.app.quitting)

    def test_the_editors_can_be_used_while_a_run_waits(self):
        self.run_with(
            "Talk", [reply(text_block("Hello."))], "f2", self.asked(),
            "f4", self.shows("Instruction Editor: Talk", "Waiting for your message"), "esc",
            "f5", self.shows("Skills Manager"), "esc",
            self.shows("robot> Hello.", "Waiting for your message"))
        self.assertTrue(self.app.asking)


class LookingBack(MainCase):
    def fill(self, count=60):
        buffer = self.make_app().main.output.buffer
        for number in range(count):
            buffer.add(f"line {number}\n")

    def test_the_newest_lines_show(self):
        self.fill()
        self.drive(self.shows("line 59"), self.lacks("line 40", "looking back"))

    def test_page_up_looks_back_and_end_returns(self):
        self.fill()
        self.drive("alt+o", "pgup", self.shows("looking back: End returns to the newest"),
                   self.lacks("line 59"), "pgup", "pgup", "pgup", "pgup", "pgup",
                   self.shows("line 0"), "end", self.shows("line 59"),
                   self.lacks("looking back"), "home", self.shows("line 0"))

    def test_the_view_stays_put_while_new_lines_arrive(self):
        self.fill()

        def more_arrives(screen):
            top = screen.line(3)
            for number in range(60, 70):
                self.app.main.output.buffer.add(f"line {number}\n")
            self.app.dirty = True
            screen.feed(Check(lambda later: self.assertEqual(later.line(3), top)))

        self.drive("alt+o", "pgup", Check(more_arrives))

    def test_scrolling_down_to_the_end_follows_again(self):
        self.fill()
        self.drive("alt+o", "up", "up", self.shows("looking back"), "down", "down",
                   self.lacks("looking back"),
                   Check(lambda screen: self.assertTrue(self.app.main.output.buffer.follow)))

    def test_the_wheel_scrolls(self):
        self.fill()
        self.drive(Mouse("wheel_up", 5, 10), self.shows("looking back"), self.lacks("line 59"),
                   Mouse("wheel_down", 5, 10), self.shows("line 59"))


class Buffers(unittest.TestCase):
    def rows(self, buffer, width=20, height=5):
        return ["".join(text for text, _style in row) for row in buffer.view(width, height)]

    def test_pieces_of_a_line_are_joined_until_its_line_break(self):
        buffer = OutputBuffer()
        buffer.add("robot> Hel")
        buffer.add("lo")
        buffer.add(" there\nnext")
        buffer.add("\n")
        self.assertEqual(self.rows(buffer), ["robot> Hello there", "next"])

    def test_blank_lines_are_kept(self):
        buffer = OutputBuffer()
        buffer.add("one\n")
        buffer.add("\n")
        buffer.add("two\n\nthree\n")
        self.assertEqual(self.rows(buffer), ["one", "", "two", "", "three"])

    def test_long_lines_wrap_and_the_view_shows_the_newest_rows(self):
        buffer = OutputBuffer()
        buffer.add("first\n")
        buffer.add("one two three four five six seven eight nine ten\n")
        self.assertEqual(self.rows(buffer, width=12, height=3),
                         ["five six", "seven eight", "nine ten"])

    def test_the_label_at_the_start_of_a_line_is_coloured(self):
        buffer = OutputBuffer()
        for text, dim in (("robot> hi there friend\n", False), ("you> hello\n", False),
                          ("  call 1: $0.01\n", True), ("warning: careful now\n", False),
                          ("error: broken\n", False), ("robot asks> which?\n", False)):
            buffer.add(text, dim)
        view = buffer.view(16, 20)
        self.assertEqual(view, [
            [("robot> ", "robot"), ("hi there", "normal")],
            [("friend", "normal")],                      # the label is on the first row only
            [("you> ", "you"), ("hello", "normal")],
            [("  call 1: $0.01", "dim")],
            [("warning: careful", "warn")],
            [("now", "warn")],                           # a warning is coloured all through
            [("error: broken", "error")],
            [("robot asks>", "robot")],                  # a row that is the label alone
            [("which?", "normal")],
        ])

    def test_scrolling_back_and_forth(self):
        buffer = OutputBuffer()
        for number in range(10):
            buffer.add(f"line {number}\n")
        self.assertEqual(self.rows(buffer, height=3), ["line 7", "line 8", "line 9"])
        buffer.scroll(20, 3, -2)
        self.assertFalse(buffer.follow)
        self.assertEqual(self.rows(buffer, height=3), ["line 5", "line 6", "line 7"])
        buffer.scroll(20, 3, -100)
        self.assertEqual(self.rows(buffer, height=3), ["line 0", "line 1", "line 2"])
        self.assertFalse(buffer.more_above(20, 3))
        buffer.scroll(20, 3, 3)
        self.assertEqual(self.rows(buffer, height=3), ["line 3", "line 4", "line 5"])
        buffer.scroll(20, 3, 100)
        self.assertTrue(buffer.follow)
        self.assertEqual(self.rows(buffer, height=3), ["line 7", "line 8", "line 9"])

    def test_scrolling_goes_through_wrapped_rows(self):
        buffer = OutputBuffer()
        buffer.add("aaa bbb ccc ddd\n")       # at width 7: "aaa bbb", "ccc ddd"
        buffer.add("eee\nfff\n")
        buffer.scroll(7, 2, -1)
        self.assertEqual(self.rows(buffer, 7, 2), ["ccc ddd", "eee"])
        buffer.scroll(7, 2, -1)
        self.assertEqual(self.rows(buffer, 7, 2), ["aaa bbb", "ccc ddd"])

    def test_scrolling_forward_while_following_changes_nothing(self):
        buffer = OutputBuffer()
        buffer.add("one\ntwo\n")
        buffer.scroll(20, 5, 3)
        self.assertTrue(buffer.follow)

    def test_a_view_that_was_scrolled_back_survives_another_width(self):
        buffer = OutputBuffer()
        for number in range(6):
            buffer.add(f"this is line number {number} of the text\n")
        buffer.scroll(15, 3, -4)
        buffer.view(15, 3)
        self.assertEqual(len(buffer.view(60, 3)), 3)
        self.assertEqual(len(buffer.view(5, 3)), 3)

    def test_old_lines_are_dropped(self):
        buffer = OutputBuffer()
        buffer.LIMIT, buffer._SLACK = 10, 5
        for number in range(40):
            buffer.add(f"line {number}\n")
        self.assertLessEqual(len(buffer.lines), 15)
        self.assertEqual(self.rows(buffer, height=2), ["line 38", "line 39"])
        buffer.to_start(20, 2)
        self.assertEqual(self.rows(buffer, height=1), [f"line {buffer.first}"])

    def test_a_view_of_lines_that_were_dropped_moves_to_the_oldest_left(self):
        buffer = OutputBuffer()
        buffer.LIMIT, buffer._SLACK = 10, 5
        for number in range(12):
            buffer.add(f"line {number}\n")
        buffer.to_start(20, 2)
        for number in range(12, 60):
            buffer.add(f"line {number}\n")
        self.assertEqual(self.rows(buffer, height=1), [f"line {buffer.first}"])

    def test_an_empty_buffer(self):
        buffer = OutputBuffer()
        self.assertEqual(buffer.view(20, 5), [])
        buffer.scroll(20, 5, -3)
        buffer.to_start(20, 5)
        self.assertFalse(buffer.more_above(20, 5))


class TheConsole(AppCase):
    def events(self):
        found = []
        while not self.bridge.events.empty():
            found.append(self.bridge.events.get_nowait())
        return found

    def test_what_is_shown_goes_to_the_screen_thread(self):
        self.console.text("Hello")
        self.console.activity("doing things")
        self.assertEqual(self.events(), [
            ("out", "robot> ", False), ("out", "Hello", False), ("out", "\n", False),
            ("out", "  doing things\n", True)])

    def test_the_transcript_still_gets_everything(self):
        class Transcript:
            def __init__(self):
                self.text = ""

            def write(self, text):
                self.text += text

        transcript = Transcript()
        self.console.set_transcript(transcript)
        self.console.text("Hello")
        self.console.warn("careful")
        self.assertEqual(transcript.text, "robot> Hello\nwarning: careful\n")

    def test_a_reply_comes_back_from_the_screen(self):
        threading.Timer(0.2, self.bridge.replies.put, args=("  typed answer ",)).start()
        self.assertEqual(self.console.ask(question="Well?"), "typed answer")
        kinds = [event[0] for event in self.events()]
        self.assertEqual(kinds.count("ask"), 1)
        self.assertEqual(kinds[-2:], ["ask_done", "out"])      # then the echo of the answer

    def test_an_answer_left_from_before_is_not_used(self):
        self.bridge.replies.put("stale")
        threading.Timer(0.3, self.bridge.replies.put, args=("fresh",)).start()
        self.assertEqual(self.console.ask(), "fresh")

    def test_stop_while_waiting_means_nobody_answered(self):
        threading.Timer(0.2, self.interrupts.press).start()
        self.assertIsNone(self.console.ask())
        self.assertFalse(self.interrupts.pending())     # dealt with: the next call may run

    def test_a_process_told_to_end_is_not_asked(self):
        self.interrupts.stop.set()
        self.assertIsNone(self.console.ask())
        self.assertEqual([event[0] for event in self.events()], [])

    def test_a_person_counts_as_being_there(self):
        self.assertTrue(self.console.tty)


class Interrupting(unittest.TestCase):
    def test_a_press_of_stop(self):
        interrupts = UiInterrupts()
        interrupts.press()
        self.assertTrue(interrupts.interrupt.is_set())
        self.assertFalse(interrupts.stop.is_set())
        interrupts.clear()
        self.assertFalse(interrupts.pending())

    def test_a_press_that_ends_the_run_stays(self):
        interrupts = UiInterrupts()
        interrupts.press(end_run=True)
        interrupts.clear()
        self.assertTrue(interrupts.stop.is_set())
        self.assertTrue(interrupts.pending())

    def test_three_presses_do_not_end_the_process(self):
        # The chat leaves at once on a third Ctrl-C. Here that would leave
        # the terminal in the state the windows put it in.
        interrupts = UiInterrupts()
        with mock.patch("os._exit") as leave:
            for _ in range(5):
                interrupts._on_interrupt(2, None)
        leave.assert_not_called()
        self.assertTrue(interrupts.interrupt.is_set())

    def test_inside_a_region_that_may_be_abandoned_the_handler_raises(self):
        interrupts = UiInterrupts()
        with self.assertRaises(KeyboardInterrupt):
            with interrupts.raisable():
                interrupts._on_interrupt(2, None)


class StartingUp(unittest.TestCase):
    def test_without_a_terminal_it_says_how_to_get_one(self):
        errors = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
                contextlib.redirect_stderr(errors):
            code = tui_app.main([])
        self.assertEqual(code, 2)
        self.assertIn("needs a terminal", errors.getvalue())
        self.assertIn("ssh -t", errors.getvalue())

    def test_stray_output_goes_to_a_file_while_the_windows_are_up(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "errors.log"
            before = sys.stdout, sys.stderr
            with tui_app._streams_to_log(path):
                print("to stdout")
                print("to stderr", file=sys.stderr)
                os.write(2, b"from underneath\n")
            self.assertEqual((sys.stdout, sys.stderr), before)
            text = path.read_text(encoding="utf-8")
            for expected in ("to stdout", "to stderr", "from underneath"):
                self.assertIn(expected, text)

    def test_the_file_of_stray_output_does_not_grow_for_ever(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "errors.log"
            path.write_text("x" * (tui_app._ERROR_LOG_LIMIT + 1), encoding="utf-8")
            with tui_app._streams_to_log(path):
                print("fresh")
            self.assertEqual(path.read_text(encoding="utf-8").strip(), "fresh")

    def test_the_command_line(self):
        self.assertEqual(tui_app.build_parser().parse_args(["-l", "Name"]).load, "Name")
        self.assertIsNone(tui_app.build_parser().parse_args([]).load)

    def test_a_session_name_on_the_command_line(self):
        parse = tui_app.build_parser().parse_args
        self.assertFalse(parse([]).session)                  # no name: the first copy
        self.assertFalse(parse(["-l", "Name"]).session)
        self.assertEqual(parse(["--session", "2"]).session, "2")
        self.assertEqual(parse(["--session=garden-1", "-l", "Name"]).session, "garden-1")
        self.assertEqual(parse(["--session", "x" * 12]).session, "x" * 12)
        # Session 1 is the first copy, the one that is started without a name.
        self.assertEqual(parse(["--session", "1"]).session, "")

    def test_a_session_name_must_be_fit_for_a_file_name(self):
        # It becomes part of the name of the copy's settings file, and of a
        # tmux session.
        for bad in ("two words", "a/b", "..", "x" * 13, "", "semi;colon"):
            with self.subTest(name=bad):
                errors = io.StringIO()
                with self.assertRaises(SystemExit) as stopped, \
                        contextlib.redirect_stderr(errors):
                    tui_app.build_parser().parse_args(["--session", bad])
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("a session name is 1 to 12 letters, digits", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
