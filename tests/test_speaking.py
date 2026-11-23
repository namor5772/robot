"""Speaking: the speak tool, from the text to the file that is played. Nothing
is sent and nothing sounds: the service and the player are stand-ins."""

import array
import io
import json
import struct
import subprocess
import tempfile
import unittest
import urllib.error
import wave
from datetime import datetime
from pathlib import Path
from unittest import mock

from robot import hearing, speaking
from robot.tools import ALL_TOOLS
from robot.tui import editor
from tests.fakes import reply, text_block, tool_use
from tests.test_agent import LoopCase
from tests.test_hearing import FakeAnswer

LISTING = """**** List of PLAYBACK Hardware Devices ****
card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
  Subdevices: 8/8
card 2: B100 [Brio 100], device 0: USB Audio [USB Audio]
"""


SENTENCE = 'Say "hi" ' + chr(0x2014) + ' caf' + chr(0xe9) + '.'  # not plain ASCII


def samples(seconds, level=1000, rate=speaking.TTS_RATE):
    return array.array("h", [level] * int(seconds * rate)).tobytes()


def wav(seconds, rate=speaking.TTS_RATE):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples(seconds, rate=rate))
    return buffer.getvalue()


def as_the_service_sends_it(good):
    """The same file with the lengths in its header that xAI really states
    (seen on 2026-11-23): far more than the file holds."""
    data_at = good.index(b"data")
    return (good[:4] + struct.pack("<I", 0x80000023) + good[8:data_at + 4]
            + struct.pack("<I", 0x7FFFFFFE) + good[data_at + 8:])


def http_error(code, text):
    return urllib.error.HTTPError(speaking.TTS_URL, code, "no", {}, io.BytesIO(text.encode()))


class FakePlayer:
    def __init__(self, err=b"", code=0, raises=None):
        self.err, self.returncode, self.raises, self.killed = err, code, raises, False

    def communicate(self, timeout=None):
        self.timeout = timeout
        if self.raises is not None and not self.killed:
            raise self.raises
        return b"", self.err

    def kill(self):
        self.killed = True

    def wait(self):
        return self.returncode


class WithKey(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {hearing.KEY_ENV: "test-key"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (speaking.VOICE_ENV, speaking.DEVICE_ENV):
            speaking.os.environ.pop(name, None)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        home = mock.patch.object(speaking.Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)


class TheText(unittest.TestCase):
    def test_it_is_taken_without_the_space_around_it(self):
        self.assertEqual(speaking.text_wanted("  Hello there.\n"), "Hello there.")

    def test_nothing_to_say_is_refused(self):
        for bad in (None, "", "   ", 5, ["Hello"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    speaking.text_wanted(bad)

    def test_too_much_is_refused_with_its_length(self):
        speaking.text_wanted("a" * speaking.MAX_CHARS)
        with self.assertRaisesRegex(ValueError, "2,001 characters, more than the 2,000"):
            speaking.text_wanted("a" * (speaking.MAX_CHARS + 1))


class TheSpeakers(WithKey):
    def listing(self, text):
        done = subprocess.CompletedProcess(["aplay", "-l"], 0, stdout=text, stderr="")
        return mock.patch.object(speaking.subprocess, "run", return_value=done)

    def test_the_first_output_is_taken_and_named_by_its_card(self):
        with self.listing(LISTING):
            self.assertEqual(speaking.find_speakers(),
                             ("plughw:CARD=Headphones,DEV=0", "bcm2835 Headphones"))

    def test_none_is_said_plainly(self):
        with self.listing("**** List of PLAYBACK Hardware Devices ****\n"):
            with self.assertRaisesRegex(RuntimeError, "no sound output was found"):
                speaking.find_speakers()

    def test_the_environment_can_name_another(self):
        with mock.patch.dict("os.environ", {speaking.DEVICE_ENV: "hw:3,0"}):
            with mock.patch.object(speaking.subprocess, "run") as run:
                self.assertEqual(speaking.find_speakers(), ("hw:3,0", "hw:3,0"))
        run.assert_not_called()


class Synthesizing(WithKey):
    def send(self, answer=b"sound", error=None, text="Hello."):
        urlopen = mock.patch.object(speaking.urllib.request, "urlopen", side_effect=error,
                                    return_value=FakeAnswer(answer))
        with urlopen as opened:
            try:
                return speaking.synthesize(text)
            finally:
                self.opened = opened

    def test_the_sound_comes_back_as_it_was_sent(self):
        self.assertEqual(self.send(b"RIFF..."), b"RIFF...")

    def test_the_request_asks_for_a_wav_file_in_the_usual_voice(self):
        self.send(text=SENTENCE)
        request = self.opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.x.ai/v1/tts")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "text": SENTENCE, "voice_id": "eve", "language": "auto",
            "output_format": {"codec": "wav", "sample_rate": 24000}})

    def test_the_environment_can_name_another_voice(self):
        with mock.patch.dict("os.environ", {speaking.VOICE_ENV: " rex "}):
            self.send()
        self.assertEqual(json.loads(self.opened.call_args.args[0].data)["voice_id"], "rex")

    def test_without_a_key_nothing_is_sent(self):
        with mock.patch.dict("os.environ", {hearing.KEY_ENV: ""}):
            with self.assertRaisesRegex(RuntimeError, "XAI_API_KEY is not set"):
                self.send()
        self.opened.assert_not_called()

    def test_a_refused_key_is_named(self):
        for error in (http_error(401, "no"), http_error(400, "Incorrect API key provided.")):
            with self.assertRaisesRegex(RuntimeError, "rejected the API key"):
                self.send(error=error)

    def test_an_unknown_voice_is_named(self):
        with mock.patch.dict("os.environ", {speaking.VOICE_ENV: "nobody"}):
            with self.assertRaisesRegex(RuntimeError, "no voice called 'nobody'.*ROBOT_VOICE"):
                self.send(error=http_error(404, "voice not found"))

    def test_another_refusal_shows_what_the_service_said(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 503: try later"):
            self.send(error=http_error(503, "try\n later"))

    def test_no_network_is_said_plainly(self):
        with self.assertRaisesRegex(RuntimeError, "could not be reached.*no route"):
            self.send(error=urllib.error.URLError("no route"))


class TheFile(WithKey):
    def test_a_good_file_stays_as_it_is(self):
        cleaned, seconds = speaking.clean_wav(wav(2))
        self.assertEqual(cleaned, wav(2))
        self.assertEqual(seconds, 2.0)

    def test_a_header_that_states_too_great_a_length_is_put_right(self):
        cleaned, seconds = speaking.clean_wav(as_the_service_sends_it(wav(3)))
        self.assertEqual(cleaned, wav(3))
        self.assertEqual(seconds, 3.0)

    def test_half_a_sample_at_the_end_is_dropped(self):
        cleaned, _ = speaking.clean_wav(as_the_service_sends_it(wav(1)) + b"\x07")
        self.assertEqual(cleaned, wav(1))

    def test_what_is_not_a_wav_file_is_an_error(self):
        for bad in (b"", b"ID3\x04 an mp3 file", b'{"error": "busy"}'):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(RuntimeError, "not a WAV file"):
                    speaking.clean_wav(bad)

    def test_a_file_without_sound_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "no sound in it"):
            speaking.clean_wav(wav(0))

    def test_it_is_saved_beside_the_recordings_under_its_time(self):
        path = speaking.save(b"one", datetime(2026, 11, 23, 21, 4, 5))
        self.assertEqual(path, self.home / "robot-sound" / "speech_2026-11-23_210405.wav")
        self.assertEqual(path.read_bytes(), b"one")

    def test_two_in_one_second_are_both_kept(self):
        when = datetime(2026, 11, 23, 21, 4, 5)
        first, second, third = (speaking.save(text, when) for text in (b"1", b"2", b"3"))
        self.assertEqual([path.name for path in (first, second, third)],
                         ["speech_2026-11-23_210405.wav", "speech_2026-11-23_210405_2.wav",
                          "speech_2026-11-23_210405_3.wav"])
        self.assertEqual(first.read_bytes(), b"1")


class Playing(unittest.TestCase):
    def play(self, player, seconds=4.0):
        with mock.patch.object(speaking.subprocess, "Popen", return_value=player) as popen:
            try:
                speaking.play(Path("/x/speech.wav"), seconds, "plughw:CARD=Headphones,DEV=0")
            finally:
                self.command = popen.call_args.args[0]

    def test_the_player_gets_the_device_and_the_file_and_time_enough(self):
        player = FakePlayer()
        self.play(player)
        self.assertEqual(self.command, ["aplay", "-q", "-D", "plughw:CARD=Headphones,DEV=0",
                                        str(Path("/x/speech.wav"))])
        self.assertEqual(player.timeout, 19.0)

    def test_a_player_that_fails_gives_its_own_reason(self):
        with self.assertRaisesRegex(RuntimeError, "could not be played: aplay: audio open error"):
            self.play(FakePlayer(err=b"aplay: audio open error\n", code=1))

    def test_an_interrupt_stops_the_sound_and_is_passed_on(self):
        player = FakePlayer(raises=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.play(player)
        self.assertTrue(player.killed)

    def test_a_player_that_never_ends_is_stopped(self):
        player = FakePlayer(raises=subprocess.TimeoutExpired("aplay", 19))
        with self.assertRaisesRegex(RuntimeError, "did not end in time"):
            self.play(player)
        self.assertTrue(player.killed)


class Speaking(WithKey):
    def speak(self, tool_input, answer=None, play_error=None):
        answer = as_the_service_sends_it(wav(3)) if answer is None else answer
        with mock.patch.object(speaking, "synthesize", return_value=answer) as synthesize, \
                mock.patch.object(speaking, "find_speakers",
                                  return_value=("dev", "bcm2835 Headphones")), \
                mock.patch.object(speaking, "play", side_effect=play_error) as play:
            try:
                return speaking.speak(tool_input)
            finally:
                self.synthesize, self.play = synthesize, play

    def saved(self):
        return sorted((self.home / "robot-sound").glob("speech_*.wav"))

    def test_the_text_is_made_into_a_file_and_played(self):
        result = self.speak({"text": " Good evening. "})
        self.synthesize.assert_called_once_with("Good evening.")
        (path,) = self.saved()
        self.assertEqual(path.read_bytes(), wav(3))
        self.play.assert_called_once_with(path, 3.0, "dev")
        self.assertEqual(result, (
            f"Spoken through bcm2835 Headphones: 13 characters as 3.0 s of speech in the "
            f"voice 'eve', about $0.0002, saved as {path}. The sound was sent to the speakers; whether it "
            f"was heard is not known."))

    def test_the_file_can_be_made_without_being_played(self):
        result = self.speak({"text": "Later.", "play": False})
        self.play.assert_not_called()
        (path,) = self.saved()
        self.assertTrue(result.startswith("Speech made, not played: 6 characters as 3.0 s"))
        self.assertIn(str(path), result)

    def test_a_failure_to_play_still_says_where_the_file_is(self):
        with self.assertRaises(RuntimeError) as raised:
            self.speak({"text": "Hello."}, play_error=RuntimeError("the file could not be "
                                                                   "played: busy"))
        (path,) = self.saved()
        self.assertEqual(str(raised.exception), f"the file could not be played: busy. The "
                                                f"speech was made and is saved as {path}")

    def test_bad_input_is_refused_before_anything_is_sent(self):
        for bad in ({}, {"text": ""}, {"text": "Hi.", "play": "no"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.speak(bad)
                self.synthesize.assert_not_called()

    def test_an_answer_that_is_no_sound_saves_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "not a WAV file"):
            self.speak({"text": "Hello."}, answer=b"<html>")
        self.assertEqual(self.saved(), [])
        self.play.assert_not_called()


class WhenItIsOffered(unittest.TestCase):
    def available(self, key="k", system="posix", player="/usr/bin/aplay"):
        with mock.patch.dict("os.environ", {hearing.KEY_ENV: key}), \
                mock.patch.object(speaking.os, "name", system), \
                mock.patch.object(speaking.shutil, "which", return_value=player):
            return speaking.available()

    def test_with_a_player_and_a_key(self):
        self.assertTrue(self.available())

    def test_not_without_either(self):
        self.assertFalse(self.available(key=" "))
        self.assertFalse(self.available(player=None))
        self.assertFalse(self.available(system="nt"))


class TheTool(LoopCase):
    def setUp(self):
        super().setUp()
        self.tool = next(tool for tool in ALL_TOOLS if tool.definition["name"] == "speak")

    def test_it_runs_on_the_main_thread_where_it_can_be_stopped(self):
        self.assertFalse(self.tool.parallel_safe)
        self.assertIs(self.tool.run, speaking.speak)
        self.assertIs(self.tool.is_available, speaking.available)

    def test_its_description_states_the_limit_the_code_has(self):
        described = self.tool.definition["input_schema"]["properties"]["text"]["description"]
        self.assertIn(f"{speaking.MAX_CHARS:,} characters", described)

    def test_an_instruction_can_block_it_in_the_editor(self):
        self.assertIn("speak", editor.TOOL_NAMES)
        self.assertNotIn("speak", editor.META_TOOL_NAMES)

    def test_what_was_done_reaches_the_model_as_the_tools_result(self):
        script = [reply(tool_use("speak", {"text": "Hello."})), reply(text_block("Said."))]
        made = self.make(script, tools={"speak": self.tool})
        with mock.patch.object(speaking, "speak", return_value="Spoken through X."):
            # The tool holds the real function, so the stand-in goes in by hand.
            self.tool.run, real = speaking.speak, self.tool.run
            self.addCleanup(setattr, self.tool, "run", real)
            made.run()
        result = made.messages[2]["content"][0]
        self.assertEqual(result["content"], "Spoken through X.")
        self.assertFalse(result.get("is_error"))


if __name__ == "__main__":
    unittest.main()
