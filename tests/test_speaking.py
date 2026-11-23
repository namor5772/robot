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
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.data = self.home / "robot-data"  # where the settings file goes
        patcher = mock.patch.dict("os.environ", {hearing.KEY_ENV: "test-key",
                                                 "ROBOT_DATA_DIR": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (speaking.VOICE_ENV, speaking.DEVICE_ENV):
            speaking.os.environ.pop(name, None)
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
            with self.assertRaisesRegex(RuntimeError, "no voice called 'nobody'.*voice_settings"):
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
        self.synthesize.assert_called_once_with("Good evening.", "eve", 1.0)
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


VOICES = {"voices": [
    {"voice_id": "rex", "name": "Rex", "language": "multilingual", "gender": "male"},
    {"voice_id": "Eve", "name": "Eve", "language": "multilingual", "gender": "female"},
    {"voice_id": "luna"},
]}


class TheSettings(WithKey):
    def write(self, content):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "voice_settings.json").write_text(content, encoding="utf-8")

    def test_without_a_file_it_is_the_usual_voice_at_the_usual_speed(self):
        self.assertEqual((speaking.voice(), speaking.speed()), ("eve", 1.0))
        self.assertFalse(self.data.exists())  # asking creates nothing

    def test_the_file_decides(self):
        self.write('{"voice": "Rex", "speed": 1.25}')
        self.assertEqual((speaking.voice(), speaking.speed()), ("rex", 1.25))

    def test_the_environment_names_the_voice_only_where_the_file_names_none(self):
        with mock.patch.dict("os.environ", {speaking.VOICE_ENV: "Luna"}):
            self.assertEqual(speaking.voice(), "luna")
            self.write('{"speed": 0.8}')
            self.assertEqual((speaking.voice(), speaking.speed()), ("luna", 0.8))
            self.write('{"voice": "rex"}')
            self.assertEqual(speaking.voice(), "rex")

    def test_what_makes_no_sense_in_the_file_is_passed_over(self):
        for content in ("", "not json", "[1, 2]", '{"voice": 7, "speed": "fast"}',
                        '{"voice": "  ", "speed": 9}', '{"speed": true}'):
            with self.subTest(content=content):
                self.write(content)
                self.assertEqual((speaking.voice(), speaking.speed()), ("eve", 1.0))
        self.write('{"voice": "rex", "speed": 9}')
        self.assertEqual((speaking.voice(), speaking.speed()), ("rex", 1.0))

    def test_the_saved_voice_and_speed_go_into_the_request(self):
        self.write('{"voice": "rex", "speed": 1.3}')
        with mock.patch.object(speaking.urllib.request, "urlopen",
                               return_value=FakeAnswer(b"sound")) as opened:
            speaking.synthesize("Hello.")
            speaking.synthesize("Hello.", "luna", 1.0)
        first, second = (json.loads(call.args[0].data) for call in opened.call_args_list)
        self.assertEqual((first["voice_id"], first["speed"]), ("rex", 1.3))
        self.assertEqual(second["voice_id"], "luna")
        self.assertNotIn("speed", second)  # the usual speed is not stated


class TheVoices(WithKey):
    def listed(self, answer=None, error=None):
        answer = json.dumps(VOICES).encode() if answer is None else answer
        return mock.patch.object(speaking.urllib.request, "urlopen", side_effect=error,
                                 return_value=FakeAnswer(answer))

    def settings(self, tool_input, **listing):
        with self.listed(**listing) as opened:
            try:
                return speaking.voice_settings(tool_input)
            finally:
                self.opened = opened

    def saved(self):
        return json.loads((self.data / "voice_settings.json").read_text(encoding="utf-8"))

    def test_the_list_is_asked_of_the_service_with_the_key(self):
        with self.listed() as opened:
            voices = speaking.list_voices()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.x.ai/v1/tts/voices")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual([entry["voice_id"] for entry in voices], ["Eve", "luna", "rex"])

    def test_a_list_that_cannot_be_read_is_an_error(self):
        for answer in (b"<html>", b"{}", b'{"voices": []}', b'{"voices": [1, {"name": "x"}]}'):
            with self.subTest(answer=answer):
                with self.listed(answer=answer):
                    with self.assertRaisesRegex(RuntimeError, "could not be read"):
                        speaking.list_voices()

    def test_listing_says_what_is_in_use_and_what_there_is(self):
        self.assertEqual(self.settings({"action": "list"}), (
            "The voice in use is 'eve', at speed 1 (1 is the usual speed).\n"
            "The 3 voices there are:\n"
            "eve (female, multilingual)\nluna\nrex (male, multilingual)\n"
            "The speed can be set from 0.7 to 1.5."))
        self.assertFalse(self.data.exists())  # listing saves nothing

    def test_a_voice_is_saved_and_holds_from_then_on(self):
        result = self.settings({"action": "set", "voice": " REX "})
        self.assertEqual(self.saved(), {"voice": "rex"})
        self.assertEqual(speaking.voice(), "rex")
        self.assertIn("The voice in use is 'rex', at speed 1 ", result)

    def test_a_speed_is_saved_beside_the_voice_and_needs_no_list(self):
        self.settings({"action": "set", "voice": "luna"})
        result = self.settings({"action": "set", "speed": 1.234})
        self.opened.assert_not_called()
        self.assertEqual(self.saved(), {"voice": "luna", "speed": 1.23})
        self.assertIn("'luna', at speed 1.23 ", result)

    def test_both_can_be_set_at_once(self):
        self.settings({"action": "set", "voice": "rex", "speed": 0.7})
        self.assertEqual(self.saved(), {"voice": "rex", "speed": 0.7})

    def test_a_voice_the_service_does_not_have_is_refused_with_the_ones_it_has(self):
        self.settings({"action": "set", "voice": "rex"})
        with self.assertRaisesRegex(ValueError, "no voice called 'bob'.*eve, luna, rex"):
            self.settings({"action": "set", "voice": "bob", "speed": 1.2})
        self.assertEqual(self.saved(), {"voice": "rex"})  # nothing of it was saved

    def test_a_voice_is_not_saved_when_the_list_cannot_be_had(self):
        with self.assertRaisesRegex(RuntimeError, "could not be reached"):
            self.settings({"action": "set", "voice": "rex"},
                          error=urllib.error.URLError("no route"))
        self.assertFalse((self.data / "voice_settings.json").exists())

    def test_bad_input_is_refused(self):
        for bad in ({}, {"action": "delete"}, {"action": "set"},
                    {"action": "set", "speed": 0.5}, {"action": "set", "speed": 1.6},
                    {"action": "set", "speed": "fast"}, {"action": "set", "voice": ""},
                    {"action": "set", "voice": 3}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.settings(bad)
        self.assertFalse((self.data / "voice_settings.json").exists())


class OneCallInAnotherVoice(Speaking):
    def test_a_voice_and_a_speed_for_one_call_change_nothing_that_is_saved(self):
        speaking.atomic_write_text(self.data / "voice_settings.json", '{"voice": "rex"}')
        result = self.speak({"text": "Hello.", "voice": "Luna", "speed": 1.5})
        self.synthesize.assert_called_once_with("Hello.", "luna", 1.5)
        self.assertIn("in the voice 'luna' at speed 1.5, about", result)
        self.assertEqual(speaking.voice(), "rex")

    def test_without_them_it_is_the_saved_voice_and_speed(self):
        speaking.atomic_write_text(self.data / "voice_settings.json",
                                   '{"voice": "rex", "speed": 0.8}')
        result = self.speak({"text": "Hello."})
        self.synthesize.assert_called_once_with("Hello.", "rex", 0.8)
        self.assertIn("in the voice 'rex' at speed 0.8, about", result)

    def test_a_speed_out_of_range_is_refused_before_anything_is_sent(self):
        for bad in ({"text": "Hi.", "speed": 3}, {"text": "Hi.", "voice": ""}):
            with self.assertRaises(ValueError):
                self.speak(bad)
            self.synthesize.assert_not_called()


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
        for name in ("speak", "voice_settings"):
            self.assertIn(name, editor.TOOL_NAMES)
            self.assertNotIn(name, editor.META_TOOL_NAMES)

    def test_the_settings_tool_is_offered_with_it_and_states_the_codes_limits(self):
        settings = next(tool for tool in ALL_TOOLS
                        if tool.definition["name"] == "voice_settings")
        self.assertIs(settings.run, speaking.voice_settings)
        self.assertIs(settings.is_available, speaking.available)
        self.assertFalse(settings.parallel_safe)
        for tool in (settings, self.tool):
            described = tool.definition["input_schema"]["properties"]["speed"]["description"]
            self.assertIn(f"from {speaking.MIN_SPEED} (slow) to {speaking.MAX_SPEED} (fast)",
                          described)

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
