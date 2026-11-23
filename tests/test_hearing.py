"""Hearing: the microphone_listen tool, from the recorder's command to the
words that come back. Nothing is recorded and nothing is sent: the recorder
and the speech-to-text service are stand-ins."""

import array
import email
import io
import json
import subprocess
import unittest
import urllib.error
import wave
from unittest import mock

from robot import hearing
from robot.tools import ALL_TOOLS
from robot.tui import editor
from tests.fakes import reply, text_block, tool_use
from tests.test_agent import LoopCase

LISTING = """**** List of CAPTURE Hardware Devices ****
card 2: B100 [Brio 100], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""


def sound(seconds, level):
    """`seconds` of 16-bit sound whose every sample is `level`."""
    return array.array("h", [level] * int(seconds * hearing.RATE)).tobytes()


class FakeRecorder:
    """Stands in for the arecord process."""

    def __init__(self, out=b"", err=b"", code=0, raises=None):
        self.out, self.err, self.returncode, self.raises = out, err, code, raises
        self.killed = False

    def communicate(self, timeout=None):
        if self.raises is not None and not self.killed:
            raise self.raises
        return self.out, self.err

    def kill(self):
        self.killed = True

    def wait(self):
        return self.returncode


class FakeAnswer:
    """Stands in for the service's HTTP answer."""

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def http_error(code, text):
    return urllib.error.HTTPError(hearing.STT_URL, code, "no", {}, io.BytesIO(text.encode()))


class WithKey(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {hearing.KEY_ENV: "test-key"})
        patcher.start()
        self.addCleanup(patcher.stop)  # puts the environment back as it was
        hearing.os.environ.pop(hearing.DEVICE_ENV, None)


class HowLong(unittest.TestCase):
    def test_five_seconds_when_nothing_is_said(self):
        self.assertEqual(hearing.seconds_wanted(None), 5)

    def test_part_of_a_second_is_rounded_up(self):
        self.assertEqual(hearing.seconds_wanted(2.2), 3)
        self.assertEqual(hearing.seconds_wanted(8), 8)
        self.assertEqual(hearing.seconds_wanted(hearing.MAX_SECONDS), hearing.MAX_SECONDS)

    def test_what_is_not_a_length_is_refused(self):
        for bad in (0, -3, "5", True, [5], hearing.MAX_SECONDS + 1, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    hearing.seconds_wanted(bad)


class TheMicrophone(WithKey):
    def listing(self, text):
        done = subprocess.CompletedProcess(["arecord", "-l"], 0, stdout=text, stderr="")
        return mock.patch.object(hearing.subprocess, "run", return_value=done)

    def test_it_is_named_by_its_card_not_by_its_number(self):
        with self.listing(LISTING):
            self.assertEqual(hearing.find_microphone(),
                             ("plughw:CARD=B100,DEV=0", "Brio 100"))

    def test_the_first_of_several_is_taken(self):
        more = LISTING + "card 3: Other [Second one], device 0: USB Audio [USB Audio]\n"
        with self.listing(more):
            self.assertEqual(hearing.find_microphone()[0], "plughw:CARD=B100,DEV=0")

    def test_none_is_said_plainly(self):
        with self.listing("**** List of CAPTURE Hardware Devices ****\n"):
            with self.assertRaisesRegex(RuntimeError, "no microphone was found"):
                hearing.find_microphone()

    def test_the_environment_can_name_another(self):
        with mock.patch.dict("os.environ", {hearing.DEVICE_ENV: "hw:5,0"}):
            with mock.patch.object(hearing.subprocess, "run") as run:
                self.assertEqual(hearing.find_microphone(), ("hw:5,0", "hw:5,0"))
        run.assert_not_called()


class Recording(unittest.TestCase):
    def record(self, recorder, seconds=3):
        with mock.patch.object(hearing.subprocess, "Popen", return_value=recorder) as popen:
            try:
                return hearing.record(seconds, "plughw:CARD=B100,DEV=0")
            finally:
                self.command = popen.call_args.args[0]
                self.options = popen.call_args.kwargs

    def test_the_command_asks_for_speech_format_and_one_second_more(self):
        self.record(FakeRecorder(out=sound(4, 100)))
        self.assertEqual(self.command, [
            "arecord", "-q", "-D", "plughw:CARD=B100,DEV=0", "-t", "raw", "-f", "S16_LE",
            "-c", "1", "-r", "16000", "-d", "4"])
        self.assertIs(self.options["stdin"], subprocess.DEVNULL)

    def test_the_first_second_is_thrown_away(self):
        got = self.record(FakeRecorder(out=sound(1, 9999) + sound(3, 100)))
        self.assertEqual(got, sound(3, 100))

    def test_half_a_sample_at_the_end_is_dropped(self):
        got = self.record(FakeRecorder(out=sound(2, 100) + b"\x01"), seconds=1)
        self.assertEqual(got, sound(1, 100))

    def test_a_recorder_that_fails_gives_its_own_reason(self):
        busy = FakeRecorder(err=b"arecord: main:831: audio open error:\n Device or resource busy\n",
                            code=1)
        with self.assertRaisesRegex(RuntimeError, "audio open error: Device or resource busy"):
            self.record(busy)

    def test_an_interrupt_stops_the_recorder_and_is_passed_on(self):
        recorder = FakeRecorder(raises=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.record(recorder)
        self.assertTrue(recorder.killed)

    def test_a_recorder_that_never_ends_is_stopped(self):
        recorder = FakeRecorder(raises=subprocess.TimeoutExpired("arecord", 19))
        with self.assertRaisesRegex(RuntimeError, "did not end in time"):
            self.record(recorder)
        self.assertTrue(recorder.killed)


class TheSound(unittest.TestCase):
    def test_the_loudest_sample_counts_whichever_way_it_points(self):
        self.assertEqual(hearing.peak(b""), 0)
        self.assertEqual(hearing.peak(array.array("h", [3, -700, 40]).tobytes()), 700)
        self.assertEqual(hearing.peak(array.array("h", [-32768]).tobytes()), 32768)

    def test_what_is_uploaded_is_a_wav_file_of_the_same_samples(self):
        samples = sound(2, 1234)
        with wave.open(io.BytesIO(hearing.wav_file(samples)), "rb") as back:
            self.assertEqual((back.getnchannels(), back.getsampwidth(), back.getframerate()),
                             (1, 2, 16000))
            self.assertEqual(back.readframes(back.getnframes()), samples)


class Transcribing(WithKey):
    def send(self, answer=None, error=None, wav=b"RIFFxxxxWAVEsound"):
        urlopen = mock.patch.object(hearing.urllib.request, "urlopen", side_effect=error,
                                    return_value=FakeAnswer(answer or b"{}"))
        with urlopen as opened:
            try:
                return hearing.transcribe(wav)
            finally:
                self.opened = opened

    def test_the_words_come_back(self):
        self.assertEqual(self.send(json.dumps({"text": " Hello robot. "}).encode()),
                         "Hello robot.")

    def test_no_words_is_an_answer_too(self):
        self.assertEqual(self.send(b'{"text": ""}'), "")
        self.assertEqual(self.send(b'{"duration": 3.0}'), "")

    def test_the_request_goes_to_the_service_with_the_key(self):
        self.send(b'{"text": "x"}')
        request = self.opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.x.ai/v1/stt")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(self.opened.call_args.kwargs["timeout"], hearing.STT_TIMEOUT)

    def test_the_body_is_a_form_with_the_model_first_and_the_file_last(self):
        wav = hearing.wav_file(sound(1, 500)) + b"\r\n--not-a-boundary\r\n"
        self.send(b'{"text": "x"}', wav=wav)
        request = self.opened.call_args.args[0]
        head = b"Content-Type: " + request.get_header("Content-type").encode() + b"\r\n\r\n"
        parts = email.message_from_bytes(head + request.data).get_payload()
        self.assertEqual([part.get_param("name", header="content-disposition")
                          for part in parts], ["model", "file"])
        self.assertEqual(parts[0].get_payload(), "grok-voice-transcribe-2.0")
        self.assertEqual(parts[1].get_content_type(), "audio/wav")
        self.assertEqual(parts[1].get_payload(decode=True), wav)

    def test_without_a_key_nothing_is_sent(self):
        with mock.patch.dict("os.environ", {hearing.KEY_ENV: " "}):
            with self.assertRaisesRegex(RuntimeError, "XAI_API_KEY is not set"):
                self.send()
        self.opened.assert_not_called()

    def test_a_refused_key_is_named(self):
        for code in (401, 403):
            with self.assertRaisesRegex(RuntimeError, "rejected the API key"):
                self.send(error=http_error(code, "no"))
        # What xAI really answers to a wrong key (seen on 2026-11-23).
        with self.assertRaisesRegex(RuntimeError, "rejected the API key"):
            self.send(error=http_error(400, '{"code":"Client specified an invalid argument",'
                                            '"error":"Incorrect API key provided."}'))

    def test_another_refusal_shows_what_the_service_said(self):
        with self.assertRaisesRegex(RuntimeError, r"HTTP 400: \{\"error\": \"bad audio\"\}"):
            self.send(error=http_error(400, '{"error":\n  "bad audio"}'))

    def test_no_network_is_said_plainly(self):
        with self.assertRaisesRegex(RuntimeError, "could not be reached.*no route"):
            self.send(error=urllib.error.URLError("no route"))
        with self.assertRaisesRegex(RuntimeError, "could not be reached"):
            self.send(error=TimeoutError("timed out"))

    def test_the_key_is_in_no_message(self):
        for error in (http_error(401, "test-key?"), http_error(500, "boom"),
                      urllib.error.URLError("down")):
            with self.assertRaises(RuntimeError) as raised:
                self.send(error=error)
            self.assertNotIn("test-key", str(raised.exception))

    def test_an_answer_that_is_not_json_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "could not be read"):
            self.send(b"<html>busy</html>")


class Listening(WithKey):
    def listen(self, recorded, said="", tool_input=None):
        self.transcribe = mock.Mock(return_value=said)
        with mock.patch.object(hearing, "find_microphone",
                               return_value=("plughw:CARD=B100,DEV=0", "Brio 100")), \
                mock.patch.object(hearing, "record", return_value=recorded) as record, \
                mock.patch.object(hearing, "transcribe", self.transcribe):
            try:
                return hearing.listen(tool_input or {})
            finally:
                self.record = record

    def test_speech_comes_back_as_text_with_what_it_took(self):
        result = self.listen(sound(5, 3000), "What is the time?")
        self.assertRegex(result, r'^Microphone transcript \(5\.0 s through Brio 100, '
                                 r'transcribed by grok-voice-transcribe-2\.0 in \d+\.\d s, '
                                 r'about \$0\.0001\): "What is the time\?"$')
        self.record.assert_called_once_with(5, "plughw:CARD=B100,DEV=0")

    def test_the_length_asked_for_is_the_length_recorded(self):
        self.listen(sound(12, 3000), "x", {"seconds": 11.5})
        self.record.assert_called_once_with(12, "plughw:CARD=B100,DEV=0")

    def test_what_is_sent_is_the_recording_as_a_wav_file(self):
        self.listen(sound(2, 3000), "x")
        self.assertEqual(self.transcribe.call_args.args[0], hearing.wav_file(sound(2, 3000)))

    def test_a_dead_microphone_is_reported_and_sent_nowhere(self):
        result = self.listen(sound(5, hearing.SILENCE_PEAK - 1))
        self.assertIn("heard only silence for 5.0 s through Brio 100", result)
        self.assertIn("Nothing was sent", result)
        self.transcribe.assert_not_called()

    def test_a_room_without_speech_is_sent_and_said_to_hold_none(self):
        result = self.listen(sound(5, hearing.SILENCE_PEAK), "")
        self.assertRegex(result, r"^Microphone transcript: no speech was recognised \(5\.0 s ")
        self.transcribe.assert_called_once()

    def test_no_sound_at_all_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "nothing was recorded through Brio 100"):
            self.listen(b"")

    def test_a_bad_length_is_refused_before_anything_is_recorded(self):
        with self.assertRaises(ValueError):
            self.listen(sound(1, 3000), "x", {"seconds": -1})
        self.record.assert_not_called()


class WhenItIsOffered(unittest.TestCase):
    def available(self, key="k", system="posix", recorder="/usr/bin/arecord"):
        with mock.patch.dict("os.environ", {hearing.KEY_ENV: key}), \
                mock.patch.object(hearing.os, "name", system), \
                mock.patch.object(hearing.shutil, "which", return_value=recorder):
            return hearing.available()

    def test_with_a_recorder_and_a_key(self):
        self.assertTrue(self.available())

    def test_not_without_a_key(self):
        self.assertFalse(self.available(key=""))
        self.assertFalse(self.available(key="  "))

    def test_not_without_a_recorder(self):
        self.assertFalse(self.available(recorder=None))
        self.assertFalse(self.available(system="nt"))


class TheTool(LoopCase):
    def setUp(self):
        super().setUp()
        self.tool = next(tool for tool in ALL_TOOLS
                         if tool.definition["name"] == "microphone_listen")

    def test_it_runs_on_the_main_thread_where_it_can_be_stopped(self):
        self.assertFalse(self.tool.parallel_safe)
        self.assertIs(self.tool.run, hearing.listen)
        self.assertIs(self.tool.is_available, hearing.available)

    def test_its_description_states_the_limits_the_code_has(self):
        described = self.tool.definition["input_schema"]["properties"]["seconds"]["description"]
        self.assertIn(f"default {hearing.DEFAULT_SECONDS}", described)
        self.assertIn(f"maximum {hearing.MAX_SECONDS}", described)

    def test_an_instruction_can_block_it_in_the_editor(self):
        self.assertIn("microphone_listen", editor.TOOL_NAMES)
        self.assertNotIn("microphone_listen", editor.META_TOOL_NAMES)

    def test_what_was_heard_reaches_the_model_as_the_tools_result(self):
        script = [reply(tool_use("microphone_listen", {"seconds": 4})),
                  reply(text_block("You asked for the time."))]
        made = self.make(script, tools={"microphone_listen": self.tool})
        with mock.patch.object(hearing, "find_microphone", return_value=("dev", "Brio 100")), \
                mock.patch.object(hearing, "record", return_value=sound(4, 3000)), \
                mock.patch.object(hearing, "transcribe", return_value="What is the time?"):
            made.run()
        result = made.messages[2]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertIn('"What is the time?"', result["content"])
        self.assertFalse(result.get("is_error"))

    def test_a_failure_goes_to_the_model_and_the_run_goes_on(self):
        script = [reply(tool_use("microphone_listen", {})), reply(text_block("I could not."))]
        made = self.make(script, tools={"microphone_listen": self.tool})
        with mock.patch.object(hearing, "find_microphone",
                               side_effect=RuntimeError("no microphone was found")):
            made.run()
        result = made.messages[2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("no microphone was found", result["content"])


if __name__ == "__main__":
    unittest.main()
