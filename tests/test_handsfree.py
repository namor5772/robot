"""Hands-free: cutting what was said out of the microphone's sound, the thread
that listens, and a spoken message as a reply in the chat and the interface.
No microphone and no network: the recorder and the service are stand-ins."""

import array
import io
import json
import os
import queue
import threading
import time
import unittest
from unittest import mock

from robot import agent as agent_module
from robot import handsfree, hearing, speaking
from robot import main as command_line
from robot.console import Console
from robot.handsfree import (
    CHUNK_BYTES, END_QUIET_CHUNKS, LEAD_IN_CHUNKS, MAX_CHUNKS, PRE_ROLL_CHUNKS, TAIL_CHUNKS,
    Ear, Segmenter)
from tests.fakes import NoWaitInterrupts, TerminalConsole, reply, text_block
from tests.test_agent import LoopCase
from tests.test_tui_app import MainCase, said
from tests.tui_fakes import Check, Until

ROOM = 300  # a quiet room at the Pi's microphone, as measured
VOICE = 2000


def chunk(loudness, offset=0):
    """A tenth of a second whose level is `loudness`: a square wave around `offset`."""
    half = CHUNK_BYTES // 4
    return array.array("h", [offset + loudness, offset - loudness] * half).tobytes()


def stream(*parts):
    """Chunks from (count, level) pairs, after the lead-in that is not looked at."""
    chunks = [chunk(ROOM)] * LEAD_IN_CHUNKS
    for count, loudness in parts:
        chunks += [chunk(loudness)] * count
    return chunks


def cut(chunks, segmenter=None):
    """Feed the chunks; returns (the utterances, in chunks each, and the segmenter)."""
    segmenter = segmenter or Segmenter()
    found = []
    for piece in chunks:
        sound = segmenter.feed(piece)
        if sound is not None:
            found.append(len(sound) // CHUNK_BYTES)
    return found, segmenter


class TheLevel(unittest.TestCase):
    def test_it_is_how_far_the_sound_swings(self):
        self.assertAlmostEqual(handsfree.level(chunk(1234)), 1234.0)
        self.assertEqual(handsfree.level(b""), 0.0)

    def test_a_steady_offset_counts_as_nothing(self):
        self.assertAlmostEqual(handsfree.level(chunk(0, offset=900)), 0.0)
        self.assertAlmostEqual(handsfree.level(chunk(500, offset=900)), 500.0)


class CuttingOutWhatWasSaid(unittest.TestCase):
    def test_speech_and_the_pause_after_it_give_one_utterance(self):
        found, _ = cut(stream((20, ROOM), (12, VOICE), (END_QUIET_CHUNKS, ROOM)))
        # What came just before it, the speech, and a little of the pause.
        self.assertEqual(found, [PRE_ROLL_CHUNKS + 12 + TAIL_CHUNKS])

    def test_it_is_handed_over_only_when_the_pause_is_long_enough(self):
        found, segmenter = cut(stream((20, ROOM), (12, VOICE), (END_QUIET_CHUNKS - 1, ROOM)))
        self.assertEqual(found, [])
        self.assertTrue(segmenter.hearing)

    def test_a_breath_between_words_does_not_end_it(self):
        found, _ = cut(stream((20, ROOM), (8, VOICE), (6, ROOM), (8, VOICE),
                              (END_QUIET_CHUNKS, ROOM)))
        self.assertEqual(found, [PRE_ROLL_CHUNKS + 22 + TAIL_CHUNKS])

    def test_two_things_said_are_two_utterances(self):
        found, _ = cut(stream((20, ROOM), (10, VOICE), (END_QUIET_CHUNKS + 10, ROOM),
                              (6, VOICE), (END_QUIET_CHUNKS, ROOM)))
        self.assertEqual(found, [PRE_ROLL_CHUNKS + 10 + TAIL_CHUNKS,
                                 PRE_ROLL_CHUNKS + 6 + TAIL_CHUNKS])

    def test_a_click_is_not_speech(self):
        for clicks in (1, 2):
            found, segmenter = cut(stream((20, ROOM), (clicks, 9000), (40, ROOM)))
            self.assertEqual(found, [], clicks)
            self.assertFalse(segmenter.hearing)

    def test_the_thump_of_a_microphone_waking_is_not_looked_at(self):
        chunks = [chunk(7000), chunk(2500)] + [chunk(1200)] * (LEAD_IN_CHUNKS - 2)
        found, segmenter = cut(chunks + [chunk(ROOM)] * 40)
        self.assertEqual(found, [])
        self.assertFalse(segmenter.hearing)
        self.assertAlmostEqual(segmenter.floor, ROOM, delta=1)

    def test_a_noisy_room_needs_a_louder_voice(self):
        noisy = 1500
        quiet_voice, _ = cut(stream((30, noisy), (12, 2400), (END_QUIET_CHUNKS, noisy)))
        loud_voice, _ = cut(stream((30, noisy), (12, 6000), (END_QUIET_CHUNKS, noisy)))
        self.assertEqual(quiet_voice, [])
        self.assertEqual(loud_voice, [PRE_ROLL_CHUNKS + 12 + TAIL_CHUNKS])

    def test_a_room_that_goes_quiet_is_followed_down_fast(self):
        # Somebody was talking when the listening began, and then stopped.
        found, segmenter = cut(stream((1, 3000), (15, ROOM)))
        self.assertEqual(found, [])
        self.assertLess(segmenter.floor, ROOM * 1.05)
        found, _ = cut([chunk(1100)] * 8 + [chunk(ROOM)] * END_QUIET_CHUNKS, segmenter)
        self.assertEqual(len(found), 1)

    def test_a_room_that_gets_a_little_louder_is_followed_up_slowly(self):
        _, segmenter = cut(stream((10, ROOM), (200, ROOM + 150)))
        self.assertGreater(segmenter.floor, ROOM + 100)
        self.assertFalse(segmenter.hearing)

    def test_speech_without_end_is_cut_at_a_minute(self):
        found, segmenter = cut(stream((10, ROOM), (MAX_CHUNKS + 50, VOICE)))
        self.assertEqual(found, [MAX_CHUNKS])
        self.assertTrue(segmenter.hearing)  # and what follows is the next one

    def test_what_held_no_words_becomes_the_rooms_level(self):
        hum = [chunk(1000)] * 30 + [chunk(ROOM)] * END_QUIET_CHUNKS
        found, segmenter = cut(stream((20, ROOM)) + hum)
        self.assertEqual(len(found), 1)
        segmenter.not_speech()
        again, _ = cut(hum, segmenter)
        self.assertEqual(again, [])  # the same hum does not start another
        louder, _ = cut([chunk(4000)] * 10 + [chunk(ROOM)] * END_QUIET_CHUNKS, segmenter)
        self.assertEqual(len(louder), 1)


class FakeRecorder:
    """Stands in for the arecord process: its sound comes through a real pipe,
    so that reading waits, as it does at a microphone."""

    def __init__(self, chunks=(), then_end=False, complaint=b""):
        read_end, self._write_end = os.pipe()
        self.stdout = os.fdopen(read_end, "rb")
        self.stderr = io.BytesIO(complaint)
        self.killed = False
        # A pipe holds little, so the sound is written by a thread of its own,
        # which waits for the reader as a recorder waits for nobody.
        self._todo = queue.Queue()
        threading.Thread(target=self._write, daemon=True).start()
        self.give(chunks)
        if then_end:
            self._todo.put(None)

    def give(self, chunks):
        for piece in chunks:
            self._todo.put(piece)

    def _write(self):
        while True:
            piece = self._todo.get()
            try:
                if piece is None:
                    os.close(self._write_end)
                    return
                os.write(self._write_end, piece)
            except OSError:
                return  # the reader has gone

    def kill(self):
        self.killed = True
        # Ends the reader's wait, as killing a recorder does: its pipe closes.
        self._todo.put(None)

    def wait(self, timeout=None):
        return 0


SAID = stream((15, ROOM), (10, VOICE), (END_QUIET_CHUNKS, ROOM))


def until(condition, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class TheEar(unittest.TestCase):
    def ear(self, recorder, transcribe, available=True):
        ear = Ear(transcribe=transcribe)
        patches = [
            mock.patch.object(hearing, "available", return_value=available),
            mock.patch.object(hearing, "find_microphone", return_value=("mic", "Brio 100")),
            mock.patch.object(handsfree.subprocess, "Popen", return_value=recorder)]
        for patch in patches:
            self.popen = patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(ear.stop)
        return ear

    def test_what_was_said_can_be_taken_as_words(self):
        sent = []
        ear = self.ear(FakeRecorder(SAID), lambda wav: sent.append(wav) or "Hello robot.")
        self.assertTrue(ear.start())
        self.assertTrue(until(lambda: sent))
        self.assertTrue(until(lambda: ear.state == handsfree.LISTENING))
        self.assertEqual(ear.take(), "Hello robot.")
        self.assertIsNone(ear.take())
        self.assertEqual(sent[0][:4], b"RIFF")  # a WAV file of the utterance alone
        self.assertEqual(len(sent[0]) - 44,
                         (PRE_ROLL_CHUNKS + 10 + TAIL_CHUNKS) * CHUNK_BYTES)

    def test_the_recorder_runs_without_an_end_at_speech_format(self):
        ear = self.ear(FakeRecorder(), lambda wav: "")
        ear.start()
        self.assertEqual(self.popen.call_args.args[0], [
            "arecord", "-q", "-D", "mic", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", "16000"])

    def test_sound_without_words_is_no_message_and_listening_goes_on(self):
        answers = iter(["", "Second try."])
        recorder = FakeRecorder(SAID)
        ear = self.ear(recorder, lambda wav: next(answers))
        ear.start()
        recorder.give([chunk(9000)] * 10 + [chunk(ROOM)] * END_QUIET_CHUNKS)
        self.assertTrue(until(lambda: ear.take() == "Second try."))

    def test_a_failure_to_transcribe_is_kept_as_trouble_and_listening_goes_on(self):
        calls = []

        def transcribe(wav):
            calls.append(wav)
            if len(calls) == 1:
                raise RuntimeError("xAI could not be reached")
            return "Now it works."

        recorder = FakeRecorder(SAID)
        ear = self.ear(recorder, transcribe)
        ear.start()
        self.assertTrue(until(lambda: ear.trouble))
        self.assertEqual(ear.trouble, "xAI could not be reached")
        self.assertEqual(ear.problem, "")
        recorder.give([chunk(9000)] * 10 + [chunk(ROOM)] * END_QUIET_CHUNKS)
        self.assertTrue(until(lambda: ear.take() == "Now it works."))

    def test_a_recorder_that_ends_by_itself_is_a_problem_with_its_reason(self):
        recorder = FakeRecorder(then_end=True, complaint=b"arecord: audio open error:\n busy\n")
        ear = self.ear(recorder, lambda wav: "")
        ear.start()
        self.assertTrue(until(lambda: ear.problem))
        self.assertEqual(ear.problem, "the microphone stopped: arecord: audio open error: busy")

    def test_stopping_ends_the_recorder_and_is_no_problem(self):
        recorder = FakeRecorder(SAID[:20])
        ear = self.ear(recorder, lambda wav: "")
        ear.start()
        ear.stop()
        self.assertTrue(recorder.killed)
        self.assertEqual(ear.problem, "")
        self.assertFalse(ear._thread.is_alive())

    def test_words_worked_out_after_the_stop_are_dropped(self):
        release = threading.Event()

        def slow(wav):
            release.wait(5)
            return "Too late."

        ear = self.ear(FakeRecorder(SAID), slow)
        ear.start()
        self.assertTrue(until(lambda: ear.state == handsfree.WORKING))
        ear._stopping.set()
        release.set()
        ear.stop()
        self.assertIsNone(ear.take())

    def test_where_hearing_cannot_work_it_does_not_start(self):
        ear = self.ear(FakeRecorder(), lambda wav: "", available=False)
        self.assertFalse(ear.start())
        self.assertIn("XAI_API_KEY", ear.problem)
        self.popen.assert_not_called()

    def test_no_microphone_is_a_problem_not_a_crash(self):
        ear = self.ear(FakeRecorder(), lambda wav: "")
        with mock.patch.object(hearing, "find_microphone",
                               side_effect=RuntimeError("no microphone was found")):
            self.assertFalse(ear.start())
        self.assertEqual(ear.problem, "no microphone was found")


class FakeEar:
    """Stands in for the ear in the console's tests. `script` is shared by all
    the ears a test opens: each entry is what one ear will hear, or None."""

    script = []
    starts = True
    opened = []

    def __init__(self):
        self.state, self.problem, self.trouble = handsfree.LISTENING, "", ""
        self.stopped = False
        self.words = FakeEar.script.pop(0) if FakeEar.script else None
        FakeEar.opened.append(self)

    def start(self):
        if not FakeEar.starts:
            self.problem = "no microphone was found"
        return FakeEar.starts

    def take(self):
        words, self.words = self.words, None
        return words

    def stop(self):
        self.stopped = True


def fake_ears(case, *script, starts=True):
    FakeEar.script, FakeEar.starts, FakeEar.opened = list(script), starts, []
    patch = mock.patch.object(handsfree, "Ear", FakeEar)
    patch.start()
    case.addCleanup(patch.stop)


@unittest.skipUnless(os.name == "posix", "waiting on the keyboard and the ear needs select()")
class AtTheChatsPrompt(unittest.TestCase):
    def console(self, typed=None):
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, write_end)
        keyboard = os.fdopen(read_end, "r")
        self.addCleanup(keyboard.close)
        if typed is not None:
            os.write(write_end, typed.encode())
        self.out = io.StringIO()
        console = Console(stdin=keyboard, stdout=self.out, interrupts=NoWaitInterrupts())
        console.tty = True
        console.hands_free = True
        return console

    def test_a_spoken_message_is_the_reply_and_is_shown_as_heard(self):
        fake_ears(self, "What time is it?")
        console = self.console()
        self.assertEqual(console.ask(), "What time is it?")
        self.assertIn("(listening: speak, or type)", self.out.getvalue())
        self.assertTrue(self.out.getvalue().endswith("you> (heard) What time is it?\n"))
        self.assertTrue(FakeEar.opened[0].stopped)

    def test_the_console_remembers_whether_the_last_reply_was_spoken(self):
        fake_ears(self, None)
        console = self.console(typed="typed\n")
        self.assertEqual(console.ask(), "typed")
        self.assertFalse(console.last_reply_heard)
        fake_ears(self, "Spoken.")
        self.assertEqual(console.ask(), "Spoken.")
        self.assertTrue(console.last_reply_heard)

    def test_a_typed_line_is_the_reply_all_the_same(self):
        fake_ears(self, None)
        console = self.console(typed="  typed instead \n")
        self.assertEqual(console.ask(), "typed instead")
        self.assertTrue(FakeEar.opened[0].stopped)

    def test_an_empty_line_is_still_the_empty_reply(self):
        fake_ears(self, None)
        self.assertEqual(self.console(typed="\n").ask(), "")

    def test_the_spoken_message_goes_into_the_saved_transcript(self):
        fake_ears(self, "Hello.")
        console = self.console()
        saved = io.StringIO()
        console.set_transcript(saved)
        console.ask()
        self.assertIn("you> (heard) Hello.\n", saved.getvalue())

    def test_an_ear_that_cannot_start_is_said_once_and_typing_is_used(self):
        fake_ears(self, starts=False)
        console = self.console()
        with mock.patch("builtins.input", side_effect=["first", "second"]):
            self.assertEqual(console.ask(), "first")
            self.assertEqual(console.ask(), "second")
        self.assertEqual(self.out.getvalue().count("Hands-free is not listening"), 1)
        self.assertIn("no microphone was found. Type instead.", self.out.getvalue())

    def test_without_hands_free_no_ear_is_opened(self):
        fake_ears(self, "never heard")
        console = self.console()
        console.hands_free = False
        with mock.patch("builtins.input", return_value="typed"):
            self.assertEqual(console.ask(), "typed")
        self.assertEqual(FakeEar.opened, [])


class HeardConsole(TerminalConsole):
    """A terminal console whose replies in `spoken` count as heard."""

    spoken = ()

    def ask(self, **how):
        reply = super().ask(**how)
        self.last_reply_heard = reply in self.spoken
        return reply


class TheGoodbye(LoopCase):
    WORDS = "I am ending this conversation now. Good to have known you."

    def end_with(self, replies, spoken, can_speak=True, say=None):
        console = HeardConsole(replies)
        console.spoken = spoken
        made = self.make([reply(text_block("Hi."))], console=console, conversational=True)
        with mock.patch.object(speaking, "available", return_value=can_speak), \
                mock.patch.object(speaking, "say", side_effect=say) as said:
            self.assertEqual(made.run(), "completed")
        self.said = said
        return console.out.getvalue()

    def test_a_spoken_end_word_is_answered_out_loud_before_the_end(self):
        for word in ("Bye.", "Stop.", "quit", "Exit!"):
            with self.subTest(word=word):
                shown = self.end_with([word], spoken=(word,))
                self.said.assert_called_once_with(self.WORDS)
                self.assertEqual(agent_module.FAREWELL, self.WORDS)
                self.assertLess(shown.index("robot> " + self.WORDS),
                                shown.index("Conversation ended."))
                self.assertEqual(len(self.client.requests), 1)  # no call is made for it

    def test_a_typed_end_word_ends_it_without_a_word(self):
        shown = self.end_with(["bye"], spoken=())
        self.said.assert_not_called()
        self.assertNotIn(self.WORDS, shown)
        self.assertIn("Conversation ended.", shown)

    def test_an_empty_reply_and_nobody_there_end_it_without_a_word(self):
        for replies in ([""], [None]):
            self.end_with(replies, spoken=())
            self.said.assert_not_called()

    def test_an_ordinary_spoken_message_is_not_a_goodbye(self):
        console = HeardConsole(["Stop the motor.", None])
        console.spoken = ("Stop the motor.",)
        made = self.make([reply(text_block("Hi.")), reply(text_block("Done."))],
                         console=console, conversational=True)
        with mock.patch.object(speaking, "available", return_value=True), \
                mock.patch.object(speaking, "say") as said:
            made.run()
        said.assert_not_called()
        self.assertEqual(len(self.client.requests), 2)

    def test_without_a_voice_the_goodbye_is_shown_and_not_spoken(self):
        shown = self.end_with(["Bye."], spoken=("Bye.",), can_speak=False)
        self.said.assert_not_called()
        self.assertIn("robot> " + self.WORDS, shown)

    def test_a_goodbye_that_cannot_be_spoken_still_ends_the_conversation(self):
        shown = self.end_with(["Bye."], spoken=("Bye.",),
                              say=RuntimeError("xAI could not be reached"))
        self.assertIn("warning: The goodbye could not be spoken: xAI could not be reached",
                      shown)
        self.assertIn("Conversation ended.", shown)

    def test_stop_cuts_the_goodbye_short_and_the_conversation_still_ends(self):
        shown = self.end_with(["Bye."], spoken=("Bye.",), say=KeyboardInterrupt())
        self.assertIn("Conversation ended.", shown)


class SayingWithoutKeeping(unittest.TestCase):
    def test_the_file_is_played_from_the_data_folders_tmp_and_removed(self):
        import tempfile
        from pathlib import Path
        from tests.test_speaking import wav
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        played = []

        def play(path, seconds, device):
            played.append((path, path.read_bytes(), seconds, device))

        with mock.patch.dict("os.environ", {"ROBOT_DATA_DIR": folder.name}), \
                mock.patch.object(speaking, "synthesize", return_value=wav(2)) as synthesize, \
                mock.patch.object(speaking, "find_speakers", return_value=("dev", "X")), \
                mock.patch.object(speaking, "play", side_effect=play):
            speaking.say("Goodbye.")
        synthesize.assert_called_once_with("Goodbye.")
        (path, content, seconds, device), = played
        self.assertEqual(path.parent, Path(folder.name).resolve() / "tmp")
        self.assertEqual((content, seconds, device), (wav(2), 2.0, "dev"))
        self.assertFalse(path.exists())
        self.assertEqual(list(Path(folder.name).rglob("*.wav")), [])

    def test_it_is_removed_when_playing_fails_too(self):
        import tempfile
        from pathlib import Path
        from tests.test_speaking import wav
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with mock.patch.dict("os.environ", {"ROBOT_DATA_DIR": folder.name}), \
                mock.patch.object(speaking, "synthesize", return_value=wav(1)), \
                mock.patch.object(speaking, "find_speakers", return_value=("dev", "X")), \
                mock.patch.object(speaking, "play", side_effect=RuntimeError("busy")):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                speaking.say("Goodbye.")
        self.assertEqual(list(Path(folder.name).rglob("*.wav")), [])


class TheChatsCommandLine(unittest.TestCase):
    def test_hands_free_is_an_option_and_off_without_it(self):
        parser = command_line.build_parser()
        self.assertTrue(parser.parse_args(["--hands-free"]).hands_free)
        self.assertFalse(parser.parse_args([]).hands_free)


class InTheInterface(MainCase):
    TALK = [reply(text_block("Hello.")), reply(text_block("It is noon."))]

    def state(self):
        return json.loads(self.app.state_path.read_text(encoding="utf-8"))

    def test_the_box_is_there_unticked_and_is_remembered(self):
        self.drive(self.shows("[ ] Hands-free"), "alt+h", self.shows("[x] Hands-free"))
        self.assertIs(self.state()["hands_free"], True)
        self.assertTrue(self.console.hands_free)

    def test_a_spoken_message_is_sent_as_the_reply(self):
        fake_ears(self, "What time is it?")
        client = self.run_with(
            "Talk", self.TALK, "alt+h", "f2",
            Until(lambda: self.screen.find("It is noon.") is not None,
                  "the answer to the spoken message"),
            self.asked(), self.shows("you> (heard) What time is it?", "It is noon."))
        self.assertEqual(said(client.requests[1]["messages"][-1]), "What time is it?")
        self.assertTrue(FakeEar.opened[0].stopped)

    def bye(self, typed_it):
        fake_ears(self, *([] if typed_it else ["Bye."]))
        keys = list("bye") + ["enter"] if typed_it else []
        with mock.patch.object(speaking, "available", return_value=True), \
                mock.patch.object(speaking, "say") as say:
            self.run_with("Talk", self.TALK, "alt+h", "f2", self.asked(), *keys,
                          self.ended(), self.shows("Conversation ended."))
        return say, self.screen.find("robot> I am ending this conversation now.")

    def test_a_spoken_bye_gets_the_goodbye(self):
        say, shown = self.bye(typed_it=False)
        say.assert_called_once_with(agent_module.FAREWELL)
        self.assertIsNotNone(shown)

    def test_a_typed_bye_does_not(self):
        say, shown = self.bye(typed_it=True)
        say.assert_not_called()
        self.assertIsNone(shown)

    def test_the_bottom_line_says_that_it_listens(self):
        fake_ears(self)
        self.run_with("Talk", self.TALK, "alt+h", "f2", self.asked(),
                      Until(lambda: self.app.ear, "the ear to be shown"),
                      self.shows("Listening: speak, or type your message"),
                      self.lacks("Waiting for your message"))

    def test_without_the_box_it_only_waits(self):
        fake_ears(self, "never heard")
        self.run_with("Talk", self.TALK, "f2", self.asked(),
                      self.shows("Waiting for your message"))
        self.assertEqual(FakeEar.opened, [])

    def test_typing_still_answers_while_it_listens(self):
        fake_ears(self)
        client = self.run_with("Talk", self.TALK, "alt+h", "f2", self.asked(),
                               *"typed", "enter", self.asked(), self.shows("you> typed"),
                               self.lacks("(heard)"))
        self.assertEqual(said(client.requests[1]["messages"][-1]), "typed")
        self.assertTrue(FakeEar.opened[0].stopped)

    def test_the_box_can_be_ticked_and_cleared_while_the_robot_waits(self):
        fake_ears(self)
        self.run_with(
            "Talk", self.TALK, "f2", self.asked(), self.shows("Waiting for your message"),
            "alt+h", Until(lambda: self.app.ear, "the ear to open"),
            self.shows("Listening: speak, or type"),
            "alt+h", Until(lambda: not self.app.ear, "the ear to close"),
            self.shows("Waiting for your message"))
        self.assertTrue(FakeEar.opened[0].stopped)

    def test_an_ear_that_cannot_start_is_said_and_typing_is_used(self):
        fake_ears(self, starts=False)
        client = self.run_with(
            "Talk", self.TALK, "alt+h", "f2", self.asked(),
            Until(lambda: self.screen.find("Hands-free is not listening") is not None,
                  "the warning"),
            self.shows("Waiting for your message"), *"ok", "enter", self.asked())
        self.assertEqual(said(client.requests[1]["messages"][-1]), "ok")
        self.assertEqual(len(FakeEar.opened), 2)  # one try for each wait, not ten a second

    def test_what_the_ear_is_doing_is_shown(self):
        fake_ears(self)

        def now(state):
            def change(screen):
                FakeEar.opened[0].state = state
            return Check(change)

        self.run_with(
            "Talk", self.TALK, "alt+h", "f2", self.asked(),
            Until(lambda: self.app.ear, "the ear to be shown"),
            now(handsfree.HEARING), Until(lambda: self.app.ear == handsfree.HEARING, "hearing"),
            self.shows("Hearing you..."),
            now(handsfree.WORKING), Until(lambda: self.app.ear == handsfree.WORKING, "working"),
            self.shows("Working out what you said..."))


class InANarrowWindow(MainCase):
    rows, cols = 18, 72  # the smallest the interface takes

    def test_all_six_boxes_and_the_bottom_line_are_on_screen(self):
        def six_boxes_on_two_rows(screen):
            rows = {screen.find(label)[0] for label in (
                "[x] Activity", "[ ] Thinking", "[ ] Tool calls", "[ ] Debug",
                "[ ] Save thinking", "[ ] Hands-free")}
            self.assertEqual(rows, {self.rows - 3, self.rows - 2})
            self.assertEqual(screen.find("Ready")[0], self.rows - 1)

        self.drive(Check(six_boxes_on_two_rows), self.shows("Your message", "Output"))


if __name__ == "__main__":
    unittest.main()
