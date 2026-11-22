"""scripts/pi_sound.py: a sound recording from the Pi, played on a PC.

No Pi, no network and no sound: ssh and scp are replaced by a stand-in that
writes down how it was called and puts a made-up recording where scp would
have put it, and the playing by one that only notes what it was given.
"""

import contextlib
import importlib.util
import io
import struct
import tempfile
import unittest
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("pi_sound", REPO / "scripts" / "pi_sound.py")
pi_sound = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pi_sound)


def wav_bytes(samples, rate=16000, width=2, channels=1):
    """A WAV file of these samples: 16-bit numbers, or bytes when width is 1."""
    target = io.BytesIO()
    with wave.open(target, "wb") as recording:
        recording.setnchannels(channels)
        recording.setsampwidth(width)
        recording.setframerate(rate)
        if width == 2:
            recording.writeframes(struct.pack("<%dh" % len(samples), *samples))
        else:
            recording.writeframes(bytes(samples))
    return target.getvalue()


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def file(self, data, name="sound.wav"):
        path = self.tmp / name
        path.write_bytes(data)
        return path


class ReadCase(TempCase):
    def read(self, *arguments, **options):
        return pi_sound.read_recording(self.file(wav_bytes(*arguments, **options)))

    def test_length_and_kind_are_read_from_the_file(self):
        recording = self.read([0] * 24000)
        self.assertEqual(recording.seconds, 1.5)
        self.assertEqual((recording.channels, recording.rate, recording.bits), (1, 16000, 16))
        self.assertFalse(recording.cut_off)

    def test_stereo_at_another_rate(self):
        recording = self.read([0] * 48000, rate=48000, channels=2)
        self.assertEqual(recording.seconds, 0.5)
        self.assertEqual((recording.channels, recording.rate), (2, 48000))

    def test_the_level_is_measured(self):
        recording = self.read([0, 16384, -8192, 0])
        self.assertEqual(recording.loudest, 0.5)
        self.assertEqual(recording.average, 0.1875)
        self.assertFalse(recording.clipped)

    def test_the_loudest_sample_may_be_a_negative_one(self):
        self.assertEqual(self.read([100, -16384]).loudest, 0.5)

    def test_full_scale_either_way_counts_as_over_the_top(self):
        self.assertTrue(self.read([0, 32767]).clipped)
        self.assertTrue(self.read([0, -32768]).clipped)
        self.assertFalse(self.read([32766, -32767]).clipped)

    def test_a_silent_recording_has_a_level_of_nothing(self):
        recording = self.read([0] * 100)
        self.assertEqual((recording.loudest, recording.average), (0, 0))

    def test_a_file_with_no_sound_in_it(self):
        recording = self.read([])
        self.assertEqual(recording.seconds, 0)
        self.assertIsNone(recording.loudest)

    def test_the_level_is_measured_for_16_bit_only(self):
        recording = self.read([128] * 8000, rate=8000, width=1)
        self.assertEqual((recording.seconds, recording.bits), (1.0, 8))
        self.assertIsNone(recording.loudest)

    def test_a_file_that_was_cut_off_says_so(self):
        whole = wav_bytes([1000] * 1000)
        recording = pi_sound.read_recording(self.file(whole[:-500]))
        self.assertTrue(recording.cut_off)
        self.assertEqual(recording.seconds, 750 / 16000)
        self.assertEqual(recording.loudest, 1000 / 32768)

    def test_what_is_not_a_wav_file_is_refused(self):
        for data in (b"", b"RIFF", b"\xff\xd8" + bytes(60), b"RIFF" + bytes(60)):
            with self.assertRaises(ValueError) as caught:
                pi_sound.read_recording(self.file(data))
            self.assertIn("sound.wav", str(caught.exception))


class DescribeCase(TempCase):
    def lines(self, *arguments, **options):
        path = self.file(wav_bytes(*arguments, **options))
        return pi_sound.describe(pi_sound.read_recording(path))

    def test_a_recording_with_sound_in_it(self):
        self.assertEqual(self.lines([0, 16384, -8192, 0] * 4000), [
            "1.0 s, mono, 16000 Hz, 16 bit",
            "loudest 50% of full scale, average 18.8%",
        ])

    def test_a_quiet_recording_still_shows_a_level(self):
        self.assertIn("average 0.3%", self.lines([100] * 16000)[1])

    def test_a_silent_one(self):
        self.assertIn("silent", self.lines([0] * 16000)[1])

    def test_one_that_went_over_the_top(self):
        lines = self.lines([0, 32767] * 8000)
        self.assertIn("loudest 100%", lines[1])
        self.assertIn("distorted", lines[2])

    def test_one_with_nothing_in_it(self):
        self.assertEqual(self.lines([]), ["0.0 s, mono, 16000 Hz, 16 bit",
                                          "there is no sound in it"])

    def test_stereo_and_a_level_that_was_not_measured(self):
        lines = self.lines([128] * 8000, rate=8000, width=1, channels=2)
        self.assertEqual(lines[0], "0.5 s, stereo, 8000 Hz, 8 bit")
        self.assertIn("not measured", lines[1])

    def test_one_that_was_cut_off(self):
        path = self.file(wav_bytes([1000] * 1000)[:-500])
        lines = pi_sound.describe(pi_sound.read_recording(path))
        self.assertIn("cut off", lines[1])
        self.assertIn("loudest 3%", lines[2])


class PlayCase(unittest.TestCase):
    """The playing itself, with a stand-in for Windows' sound module."""

    class Winsound:
        SND_FILENAME = 0x20000
        SND_NODEFAULT = 0x2

        def __init__(self):
            self.played = []

        def PlaySound(self, sound, flags):
            self.played.append((sound, flags))

    def with_winsound(self, module):
        self.addCleanup(setattr, pi_sound, "winsound", pi_sound.winsound)
        pi_sound.winsound = module

    def test_windows_is_asked_to_play_the_file_and_wait(self):
        module = self.Winsound()
        self.with_winsound(module)
        self.assertTrue(pi_sound.play(Path("some") / "sound.wav"))
        ((sound, flags),) = module.played
        self.assertEqual(sound, str(Path("some") / "sound.wav"))
        self.assertTrue(flags & module.SND_FILENAME)
        self.assertTrue(flags & module.SND_NODEFAULT)
        self.assertFalse(flags & 0x1, "SND_ASYNC would return before the end")

    def test_where_there_is_no_way_to_play_it_says_so(self):
        self.with_winsound(None)
        self.assertFalse(pi_sound.play(Path("sound.wav")))


class FetchCase(TempCase):
    """The whole job, with stand-ins for ssh, scp and the speakers."""

    def setUp(self):
        super().setUp()
        self.folder = self.tmp / "RobotSound"
        self.calls = []
        self.said = []
        self.played = []
        self.on_pi = {
            "sound_b.wav": wav_bytes([0, 16384, -8192, 0] * 4000),
            "sound_a.wav": wav_bytes([0] * 8000),
            "sound_empty.wav": wav_bytes([]),
            "sound_bad.wav": b"not a recording at all",
        }
        self.newest = "/home/someone/robot-sound/sound_b.wav"

    def run_program(self, arguments):
        self.calls.append(arguments)
        if arguments[0] == "ssh":
            return 0, self.newest
        source, target = arguments[-2], Path(arguments[-1])
        name = source.rsplit("/", 1)[-1]
        if name not in self.on_pi:
            return 1, "scp: %s: No such file or directory" % name
        (target / name).write_bytes(self.on_pi[name])
        return 0, ""

    def fetch(self, can_play=True, **options):
        options.setdefault("folder", self.folder)
        return pi_sound.fetch_and_play(
            run=self.run_program,
            play=lambda path: self.played.append(path) or can_play,
            say=self.said.append, environ={}, **options)

    def test_the_newest_recording_is_copied_described_and_played(self):
        result = self.fetch()
        self.assertEqual(result, self.folder / "sound_b.wav")
        self.assertEqual(result.read_bytes(), self.on_pi["sound_b.wav"])
        self.assertEqual(self.played, [result])
        self.assertEqual(self.said, [
            "newest on the Pi: sound_b.wav",
            "copied to: %s" % result,
            "1.0 s, mono, 16000 Hz, 16 bit",
            "loudest 50% of full scale, average 18.8%",
            "playing it ...",
            "played to the end",
        ])

    def test_the_pi_is_only_asked_and_copied_from(self):
        self.fetch()
        ssh, scp = self.calls
        self.assertEqual(ssh[0], "ssh")
        self.assertEqual(ssh[-2], "pi")
        self.assertIn("ls -t robot-sound/*.wav", ssh[-1])
        self.assertNotIn("rm", ssh[-1].split())
        self.assertEqual(scp[0], "scp")
        self.assertEqual(scp[-2], "pi:" + self.newest)
        for call in self.calls:
            self.assertIn("BatchMode=yes", call)

    def test_another_ssh_name_for_the_pi(self):
        self.fetch(host="pi-local")
        ssh, scp = self.calls
        self.assertEqual(ssh[-2], "pi-local")
        self.assertEqual(scp[-2], "pi-local:" + self.newest)

    def test_a_named_recording_is_copied_without_asking_for_the_newest(self):
        result = self.fetch(name="sound_a.wav")
        self.assertEqual([call[0] for call in self.calls], ["scp"])
        self.assertEqual(self.calls[0][-2], "pi:robot-sound/sound_a.wav")
        self.assertEqual(result, self.folder / "sound_a.wav")
        self.assertIn("it is silent: every sample is 0", self.said)
        # Silent is still played: the person may want to hear that for themselves.
        self.assertEqual(self.played, [result])

    def test_a_name_must_not_be_a_path(self):
        for name in ("../secret.wav", "sub/sound.wav", "..\\sound.wav"):
            with self.assertRaises(RuntimeError):
                self.fetch(name=name)
        self.assertEqual(self.calls, [])

    def test_a_recording_the_pi_does_not_have_is_an_error(self):
        with self.assertRaises(RuntimeError) as caught:
            self.fetch(name="sound_none.wav")
        self.assertIn("No such file", str(caught.exception))
        self.assertEqual(self.played, [])

    def test_no_recording_on_the_pi_is_an_error(self):
        self.newest = ""
        with self.assertRaises(RuntimeError) as caught:
            self.fetch()
        self.assertIn("no recording", str(caught.exception))

    def test_a_pi_that_cannot_be_reached_is_an_error(self):
        self.run_program = lambda arguments: (255, "ssh: connect to host: timed out")
        with self.assertRaises(RuntimeError) as caught:
            self.fetch()
        self.assertIn("timed out", str(caught.exception))

    def test_what_is_not_a_recording_is_copied_but_not_played(self):
        with self.assertRaises(ValueError):
            self.fetch(name="sound_bad.wav")
        self.assertTrue((self.folder / "sound_bad.wav").is_file())
        self.assertEqual(self.played, [])

    def test_a_recording_with_nothing_in_it_is_not_played(self):
        self.fetch(name="sound_empty.wav")
        self.assertIn("there is no sound in it", self.said)
        self.assertEqual(self.played, [])

    def test_a_file_already_here_is_played_where_it_is(self):
        sound = self.file(self.on_pi["sound_b.wav"], "old.wav")
        result = self.fetch(local=sound)
        self.assertEqual(result, sound)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.played, [sound])
        self.assertFalse(self.folder.exists())

    def test_a_file_that_is_not_here_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.fetch(local=self.tmp / "none.wav")

    def test_without_playing_it_is_only_described(self):
        result = self.fetch(play_it=False)
        self.assertTrue(result.is_file())
        self.assertEqual(self.played, [])
        self.assertEqual(self.said[-1], "loudest 50% of full scale, average 18.8%")

    def test_where_it_cannot_be_played_the_person_is_told_where_it_is(self):
        result = self.fetch(can_play=False)
        self.assertEqual(self.said[-1], "play it by hand: %s" % result)

    def test_recordings_are_not_copied_into_the_checkout(self):
        with self.assertRaises(ValueError):
            self.fetch(folder=REPO / "sound")
        self.assertEqual(self.calls, [])
        self.assertFalse((REPO / "sound").exists())

    def test_recordings_are_not_copied_into_a_folder_that_onedrive_copies(self):
        with self.assertRaises(ValueError):
            pi_sound.fetch_and_play(
                folder=self.tmp / "OneDrive" / "Sound", run=self.run_program,
                play=self.played.append, say=self.said.append,
                environ={"OneDrive": str(self.tmp / "OneDrive")})
        self.assertEqual(self.calls, [])


class CommandLineCase(TempCase):
    def test_the_defaults(self):
        options = pi_sound.build_parser().parse_args([])
        self.assertEqual(
            (options.name, options.local, options.folder, options.host, options.play_it),
            (None, None, "~/RobotSound", "pi", True))

    def test_the_options(self):
        options = pi_sound.build_parser().parse_args(
            ["a.wav", "--dir", "there", "--host", "pi-local", "--no-play"])
        self.assertEqual(
            (options.name, options.folder, options.host, options.play_it),
            ("a.wav", "there", "pi-local", False))

    def test_a_problem_is_one_line_and_exit_code_1(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = pi_sound.main(["--file", str(self.tmp / "none.wav")])
        self.assertEqual(code, 1)
        self.assertTrue(errors.getvalue().startswith("error: no such file"))

    def test_a_file_already_here_is_described_without_a_sound(self):
        sound = self.file(wav_bytes([0, 16384, -8192, 0] * 4000))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = pi_sound.main(["--file", str(sound), "--no-play"])
        self.assertEqual(code, 0)
        self.assertEqual(printed.getvalue().splitlines(), [
            "1.0 s, mono, 16000 Hz, 16 bit",
            "loudest 50% of full scale, average 18.8%",
        ])


if __name__ == "__main__":
    unittest.main()
