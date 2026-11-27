"""The interface's --headless: one run that nobody has to watch. The program's
side on the screen in memory, and ui.sh with a stand-in for tmux."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import instructions
from robot.datastore import DataDir
from robot.tui import app as tui_app
from tests.fakes import FakeClient, reply, text_block
from tests.test_launchers import REPO, LauncherCase
from tests.test_tui_app import MainCase, said


class TheRunNobodyWatches(MainCase):
    def headless(self, script, **options):
        client = FakeClient(script)
        self.start_runner(client)
        self.make_app(headless=True, **options)
        return client

    def test_the_option_is_off_unless_given(self):
        parser = tui_app.build_parser()
        self.assertTrue(parser.parse_args(["--headless"]).headless)
        self.assertFalse(parser.parse_args([]).headless)

    def test_the_run_starts_by_itself_and_the_interface_goes_when_it_has_ended(self):
        client = self.headless([reply(text_block("Done."))], instruction="Task")
        # Nothing is typed, and the loop ends without Quit.
        self.drive(self.ended(), "tab", "tab", "tab", "tab", "tab", "tab")
        self.assertEqual(said(client.requests[0]["messages"][0]), "Say that it is done.")
        self.assertTrue(self.app.quitting)
        self.assertEqual(self.app.outcome, "completed")

    def test_it_says_what_it_is_while_the_run_goes(self):
        self.headless([reply(text_block("Done."))], instruction="Chat")
        self.drive(self.asked(), self.shows("Headless: closes when the run ends"))

    def test_nothing_is_remembered_for_the_next_start(self):
        self.headless([reply(text_block("Done."))], instruction="Chat", session="h1")
        # A box is ticked while the run waits: that is this run's, and no file is written.
        self.drive(self.asked(), "alt+t", self.shows("[x] Thinking"))
        self.assertFalse((self.datadir.root / "tui_state_h1.json").exists())

    def test_an_interface_that_is_not_headless_stays_when_its_run_has_ended(self):
        client = FakeClient([reply(text_block("Done."))])
        self.start_runner(client)
        self.make_app(instruction="Task", autostart=True)
        self.drive(self.ended(), self.shows("--- run ended: completed"))
        self.assertFalse(self.app.quitting)

    def test_an_instruction_that_has_gone_ends_it_without_a_message_to_read(self):
        self.headless([], instruction="Task")
        library = instructions.load_instructions(self.datadir)
        del library["Task"]
        instructions.save_instructions(self.datadir, library)
        self.drive("tab", "tab", "tab")
        self.assertTrue(self.app.quitting)
        self.assertEqual(self.app.outcome, "error")


class CanItStart(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(Path(self._tmp.name) / "data")
        self.datadir.ensure()
        library = instructions.ensure_default(self.datadir)
        library.update(Task={"text": "Do it."}, Empty={"text": "  "},
                       Talk={"text": "Hello.", "conversational": True})
        instructions.save_instructions(self.datadir, library)

    def check(self, load=None, session=""):
        return tui_app.headless_check(self.datadir, session, load)

    def test_an_instruction_with_a_task_can(self):
        self.assertEqual(self.check("Task"), ("", ""))

    def test_one_that_is_not_there_cannot(self):
        problem, _note = self.check("Nope")
        self.assertIn("No saved instruction named 'Nope'. Available: ", problem)
        self.assertIn("Task", problem)

    def test_one_without_a_task_cannot(self):
        problem, _note = self.check("Empty")
        self.assertIn("has no text, and a headless run cannot ask for the task", problem)

    def test_with_no_name_and_nothing_remembered_one_must_be_given(self):
        problem, _note = self.check()
        self.assertIn('name one with -l "Name"', problem)

    def test_with_no_name_the_remembered_one_of_that_session_is_meant(self):
        tui_app.save_store(self.datadir.root / "tui_state_2.json", {"instruction": "Task"})
        self.assertEqual(self.check(session="2"), ("", ""))
        self.assertIn("name one with", self.check(session="3")[0])

    def test_a_conversation_is_started_but_said_to_wait(self):
        problem, note = self.check("Talk")
        self.assertEqual(problem, "")
        self.assertIn("'Talk' has Convo on", note)

    def test_the_program_says_so_before_it_needs_a_terminal(self):
        def run(*words):
            said_here = io.StringIO()
            with mock.patch.dict(os.environ, {"ROBOT_DATA_DIR": str(self.datadir.root)}), \
                    contextlib.redirect_stderr(said_here):
                return tui_app.main(list(words)), said_here.getvalue()

        self.assertEqual(run("--headless", "--can-start", "-l", "Task"), (0, ""))
        code, words = run("--headless", "--can-start", "-l", "Nope")
        self.assertEqual(code, 2)
        self.assertIn("No saved instruction named 'Nope'", words)
        code, words = run("--headless", "--can-start", "-l", "Talk")
        self.assertEqual(code, 0)
        self.assertIn("Note: 'Talk' has Convo on", words)
        # Without --can-start the same is said, and nothing is started.
        code, words = run("--headless", "-l", "Empty")
        self.assertEqual(code, 2)
        self.assertIn("has no text", words)


@unittest.skipUnless((REPO / ".venv" / "bin" / "python").exists(),
                     "needs the checkout's own Python, as on the Pi")
class TheLauncher(LauncherCase):
    """ui.sh --headless. It asks the real program whether the run can start."""

    def setUp(self):
        super().setUp()
        self.data = Path(self._tmp.name) / "data"
        datadir = DataDir(self.data)
        datadir.ensure()
        library = instructions.ensure_default(datadir)
        library.update({"Task": {"text": "Do it."}, "Night watch": {"text": "Watch."}})
        instructions.save_instructions(datadir, library)

    def headless(self, *words, **options):
        return self.launch("ui.sh", *words, ROBOT_DATA_DIR=str(self.data), **options)

    def test_it_starts_in_an_interface_of_its_own_that_is_not_put_on_the_screen(self):
        code, words, calls = self.headless("-l", "Night watch", "--headless")
        self.assertEqual(code, 0, words)
        self.assertEqual(calls[0], ["-L", "robot-ui", "has-session", "-t", "=robot-ui-h1"])
        socket, session, program, after = self.started(calls)
        self.assertEqual((socket, session), ("robot-ui", "robot-ui-h1"))
        self.assertEqual(program, ["robot.tui", "--session", "h1", "--headless",
                                   "-l", "Night watch"])
        self.assertIn("-d", calls[-1])                        # nobody is joined to it
        self.assertNotIn("attach-session", [word for call in calls for word in call])
        self.assertEqual(after, [";", "set-option", "-sg", "escape-time", "20"])
        self.assertIn("Started as the interface 'h1'", words)
        self.assertIn("ui.sh --session h1", words)

    def test_a_name_can_be_given(self):
        _code, words, calls = self.headless("--headless", "--session", "night", "-l", "Task")
        _socket, session, program, _after = self.started(calls)
        self.assertEqual(session, "robot-ui-night")
        self.assertEqual(program, ["robot.tui", "--session", "night", "--headless", "-l", "Task"])
        self.assertIn("Started as the interface 'night'", words)

    def test_it_never_joins_an_interface_that_is_running(self):
        code, words, calls = self.headless("--headless", "--session", "2", "-l", "Task",
                                           running=True)
        self.assertEqual(code, 1)
        self.assertIn("already running, and a headless run needs one of its own", words)
        self.assertEqual([call for call in calls if "new-session" in call
                          or "attach-session" in call], [])

    def test_what_cannot_start_is_said_at_once_and_nothing_is_started(self):
        code, words, calls = self.headless("--headless", "-l", "Nope")
        self.assertEqual(code, 2)
        self.assertIn("No saved instruction named 'Nope'", words)
        self.assertEqual([call for call in calls if "new-session" in call], [])
        code, words, _calls = self.headless("--headless")
        self.assertEqual(code, 2)
        self.assertIn('name one with -l "Name"', words)

    def test_a_check_can_name_a_tmux_of_its_own(self):
        _code, _words, calls = self.headless("--headless", "-l", "Task", ROBOT_SOCKET="zz-check")
        self.assertEqual(self.started(calls)[:2], ("zz-check", "robot-ui-h1"))

    def test_without_the_option_nothing_has_changed(self):
        _code, words, calls = self.launch("ui.sh", "-l", "Task")
        self.assertEqual(self.started(calls)[2], ["robot.tui", "-l", "Task"])
        self.assertNotIn("-d", calls[-1])
        self.assertNotIn("Started as", words)


if __name__ == "__main__":
    unittest.main()
