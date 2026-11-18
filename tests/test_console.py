"""What the console prints and reads, and when Ctrl-C is allowed to interrupt."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import relay
from robot.chats import Transcript
from robot.console import Console, Interrupts, convo_end_word, only_terminal_replies
from tests.fakes import NoWaitInterrupts, piped_console


class EndWords(unittest.TestCase):
    def test_a_bare_end_word_is_recognised(self):
        for text, word in (("quit", "quit"), ("  Stop.  ", "stop"), ("EXIT!", "exit"),
                           ("bye", "bye"), ("Quit...", "quit")):
            self.assertEqual(convo_end_word(text), word, text)

    def test_anything_else_is_an_ordinary_reply(self):
        for text in ("", None, "stop the motor", "quit now", "exit code?", "goodbye"):
            self.assertIsNone(convo_end_word(text), text)


class Output(unittest.TestCase):
    def test_each_stretch_of_reply_text_gets_one_label(self):
        console, out = piped_console("")
        console.text("Hello")
        console.text(", world.")
        console.tool_line("echo", '{"a": 1}')
        console.text("Done.")
        console.end_line()
        self.assertEqual(out.getvalue(),
                         'robot> Hello, world.\n[tool: echo: {"a": 1}]\nrobot> Done.\n')

    def test_activity_lines_are_indented_and_can_be_hidden(self):
        console, out = piped_console("")
        console.activity("Rate limited - retrying")
        console.cost(2, "$0.0100 this call")
        self.assertEqual(out.getvalue(), "  Rate limited - retrying\n  call 2: $0.0100 this call\n")
        console, out = piped_console("", activity=False)
        console.activity("hidden")
        console.tool_line("echo")
        console.cost(1, "hidden")
        console.warn("always shown")
        self.assertEqual(out.getvalue(), "warning: always shown\n")

    def test_thinking_and_debug_output_are_off_unless_asked_for(self):
        console, out = piped_console("")
        console.thinking_start()
        console.thinking_delta("hmm")
        console.thinking_end()
        console.call_header(1)
        console.tool_call_json("{}")
        console.debug_payload("{}")
        self.assertEqual(out.getvalue(), "")
        console, out = piped_console("", show_thinking=True, tool_calls=True, debug=True)
        console.thinking_start()
        console.thinking_delta("hmm")
        console.text("Hi.")
        console.call_header(3)
        self.assertEqual(out.getvalue(), "[thinking] hmm\nrobot> Hi.\n--- call #3 ---\n")

    def test_everything_shown_also_goes_to_the_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chat.txt"
            console, _ = piped_console("yes\n")
            transcript = Transcript(path)
            console.set_transcript(transcript)
            console.text("Shall I?")
            reply = console.ask()
            console.set_transcript(None)
            transcript.close()
            self.assertEqual(reply, "yes")
            self.assertEqual(path.read_text(encoding="utf-8"), "robot> Shall I?\n\nyou> yes\n")

    def test_a_dead_terminal_does_not_raise(self):
        class Dead(io.StringIO):
            def write(self, text):
                raise OSError("input/output error")
        console = Console(stdin=io.StringIO(""), stdout=Dead(), interrupts=NoWaitInterrupts())
        console.text("still fine")
        console.warn("still fine")


class Input(unittest.TestCase):
    def test_piped_lines_are_replies_and_are_echoed(self):
        console, out = piped_console("first\n  second  \n")
        self.assertEqual(console.ask(), "first")
        self.assertEqual(console.ask(question="Which one?"), "second")
        self.assertIn("you> first\n", out.getvalue())
        self.assertIn("robot asks> Which one?\n", out.getvalue())

    def test_an_empty_piped_line_is_an_empty_reply_and_the_end_is_none(self):
        console, _ = piped_console("\n")
        self.assertEqual(console.ask(), "")
        self.assertIsNone(console.ask())

    def test_a_headless_run_without_a_relay_gets_no_answer(self):
        console, _ = piped_console("typed but never read\n", headless=True)
        self.assertIsNone(console.ask(question="Anyone?"))

    def test_nobody_is_asked_after_a_stop_request(self):
        console, _ = piped_console("hello\n")
        console.interrupts.stop.set()
        self.assertIsNone(console.ask())

    def test_time_spent_waiting_is_recorded(self):
        console, _ = piped_console("x\n")
        console.ask()
        self.assertGreaterEqual(console.input_wait_secs, 0.0)

    def test_a_headless_run_is_answered_through_its_relay_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            console, out = piped_console("", headless=True, relay_dir=folder)
            original_wait = console.interrupts.wait

            def answer_then_wait(seconds):
                request = relay.read_request(folder)
                if request is not None:
                    relay.write_reply(folder, request["seq"], "relayed answer")
                return original_wait(seconds)
            console.interrupts.wait = answer_then_wait
            reply = console.ask(question="Delete it?", preface="I found one file.")
            self.assertEqual(reply, "relayed answer")
            self.assertIn("you> relayed answer", out.getvalue())
            self.assertIsNone(relay.read_request(folder))

    def test_a_relay_request_carries_the_preface_and_the_question(self):
        with tempfile.TemporaryDirectory() as folder:
            console, _ = piped_console("", headless=True, relay_dir=folder)
            seen = {}

            def capture_then_stop(seconds):
                seen["request"] = relay.read_request(folder)
                return True  # as if the run were stopped while waiting
            console.interrupts.wait = capture_then_stop
            self.assertIsNone(console.ask(question="Delete it?", preface="I found one file."))
            self.assertEqual(seen["request"]["seq"], 1)
            self.assertEqual(seen["request"]["text"], "I found one file.\n\nDelete it?")

    def test_a_relay_wait_ends_when_the_folder_disappears(self):
        folder = tempfile.mkdtemp()
        console, _ = piped_console("", headless=True, relay_dir=folder)

        def remove_folder(seconds):
            for child in Path(folder).iterdir():
                child.unlink()
            Path(folder).rmdir()
            return False
        console.interrupts.wait = remove_folder
        self.assertIsNone(console.ask(question="Anyone?"))


class TerminalReplies(unittest.TestCase):
    """Answers from the terminal that reached the prompt as if typed.

    The lines here are what readline 8.2 on the Pi left of real replies.
    """

    def test_what_is_left_of_a_terminal_reply_is_recognised(self):
        for line in ("11;rgb:0c0c/0c0c/0c0c",  # background colour
                     "10;rgb:cccc/cccc/cccc11;rgb:0c0c/0c0c/0c0c",  # both colours
                     "11;rgb:0c/0c/0c",
                     "61;4;6;7;14;21;22;23;24;28;32;42c",  # terminal type
                     "0;10;1c",
                     "61;4;6c0;10;1c10;rgb:cccc/cccc/cccc11;rgb:0C0C/0C0C/0C0C",  # all four
                     "  11;rgb:0c0c/0c0c/0c0c  "):
            self.assertTrue(only_terminal_replies(line), line)

    def test_typed_text_is_never_taken_for_one(self):
        for line in ("", None, "hello", "25c", "c", "10", "1;2", "rgb:0c0c/0c0c/0c0c",
                     "set the lamp to rgb:ff/00/00",
                     "why did 11;rgb:0c0c/0c0c/0c0c appear at the prompt?",
                     "11;rgb:0c0c/0c0c/0c0c what is this?",
                     "what is 1+111;rgb:0c0c/0c0c/0c0c",
                     "0;10;1c is what I saw",
                     "11;rgb:0c0c/0c0c"):
            self.assertFalse(only_terminal_replies(line), line)

    def test_a_long_line_of_numbers_is_decided_quickly(self):
        self.assertFalse(only_terminal_replies("1;" * 5000))
        self.assertFalse(only_terminal_replies("11;rgb:0c0c/0c0c/0c0c" * 500 + "x"))
        self.assertTrue(only_terminal_replies("0;10;1c" * 500))


class TerminalInput(unittest.TestCase):
    """The prompt at a real terminal, with the keyboard played by a patch."""

    def typed(self, line):
        console, out = piped_console("")
        console.tty = True
        with mock.patch("builtins.input", return_value=line) as asked:
            reply = console.ask()
        asked.assert_called_once_with("you> ")
        return reply, out.getvalue()

    def test_a_typed_line_is_the_reply(self):
        reply, shown = self.typed("  how hot are you?  ")
        self.assertEqual(reply, "how hot are you?")
        self.assertNotIn("ignored", shown)

    def test_a_line_from_the_terminal_itself_counts_as_a_bare_enter(self):
        reply, shown = self.typed("11;rgb:0c0c/0c0c/0c0c")
        self.assertEqual(reply, "")
        self.assertIn("(ignored: that line came from your terminal, not from the keyboard)\n",
                      shown)

    def test_a_sentence_that_quotes_such_a_line_is_sent_whole(self):
        line = "why did 11;rgb:0c0c/0c0c/0c0c appear at the prompt?"
        reply, shown = self.typed(line)
        self.assertEqual(reply, line)
        self.assertNotIn("ignored", shown)

    def test_the_ignored_line_is_still_in_the_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chat.txt"
            console, _ = piped_console("")
            console.tty = True
            transcript = Transcript(path)
            console.set_transcript(transcript)
            with mock.patch("builtins.input", return_value="0;10;1c"):
                console.ask()
            console.set_transcript(None)
            transcript.close()
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "\nyou> 0;10;1c\n"
                "(ignored: that line came from your terminal, not from the keyboard)\n")


class StartupInput(unittest.TestCase):
    """What reached the keyboard buffer before the first prompt is dropped."""

    def test_only_the_first_prompt_drops_pending_input(self):
        console, _ = piped_console("")
        console.tty = True
        console._in = mock.Mock()
        console._in.fileno.return_value = 7
        termios = mock.Mock(TCIFLUSH=0)
        with mock.patch.dict("sys.modules", {"termios": termios}), \
                mock.patch("builtins.input", return_value="hello"):
            self.assertEqual(console.ask(), "hello")
            self.assertEqual(console.ask(), "hello")
        termios.tcflush.assert_called_once_with(7, 0)

    def test_a_stream_that_is_no_terminal_is_left_alone(self):
        console, _ = piped_console("")
        console.tty = True
        with mock.patch("builtins.input", return_value="hello"):
            self.assertEqual(console.ask(), "hello")


class InterruptRegions(unittest.TestCase):
    def test_the_handler_only_raises_inside_a_declared_region(self):
        interrupts = Interrupts()
        interrupts._on_interrupt(None, None)  # outside a region: just a flag
        self.assertTrue(interrupts.interrupt.is_set())
        interrupts.clear()
        with self.assertRaises(KeyboardInterrupt):
            with interrupts.raisable():
                interrupts._on_interrupt(None, None)
        self.assertEqual(interrupts._depth, 0)

    def test_entering_a_region_with_a_pending_interrupt_raises_at_once(self):
        interrupts = Interrupts()
        interrupts.interrupt.set()
        with self.assertRaises(KeyboardInterrupt):
            with interrupts.raisable():
                self.fail("the region must not be entered")

    def test_a_stop_request_survives_clear(self):
        interrupts = Interrupts()
        interrupts._on_stop(None, None)
        interrupts.clear()
        self.assertTrue(interrupts.stop.is_set())
        self.assertTrue(interrupts.pending())

    def test_wait_returns_at_once_when_already_interrupted(self):
        interrupts = Interrupts()
        interrupts.interrupt.set()
        self.assertTrue(interrupts.wait(30))
        interrupts = Interrupts()
        self.assertFalse(interrupts.wait(0.01))


if __name__ == "__main__":
    unittest.main()
