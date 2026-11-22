"""Hear a sound recording from the Pi on a PC.

Run on a PC, from the checkout:

    .venv/Scripts/python.exe scripts/pi_sound.py              the newest recording
    .venv/Scripts/python.exe scripts/pi_sound.py NAME.wav     that recording
    .venv/Scripts/python.exe scripts/pi_sound.py --file F.wav a file already here

It copies the recording from the Pi's ~/robot-sound into ~/RobotSound on the
PC, says how long and how loud it is, and plays it to its end through the
PC's speakers. Nothing on the Pi is changed.

The recordings are plain WAV files, which Windows plays as they come: unlike
the photos (scripts/pi_photo.py) they need no repair. The line about the
level is there for whoever cannot listen: it tells a recording with sound in
it from a silent one, and says when the loudest part went over the top.

Recordings are personal. The folder they go to must not be inside the
checkout (the repo is public) or inside a folder that OneDrive copies. That
rule, and the copying, are pi_photo's.
"""

import argparse
import array
import collections
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

import pi_photo  # noqa: E402  (the script beside this one)

try:
    import winsound
except ImportError:  # anywhere but Windows
    winsound = None

SOUND_ON_PI = "robot-sound"  # in the home folder of the Pi's user
FULL_SCALE = 32768  # the largest value a 16-bit sample can have

# seconds, channels, rate and bits as the file has them. loudest and average
# are parts of full scale (0 to 1), or None where they were not measured.
Recording = collections.namedtuple(
    "Recording", "seconds channels rate bits loudest average clipped cut_off")


def read_recording(path):
    """What a WAV file holds. Raises ValueError for a file that is not one."""
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as opened:
            channels = opened.getnchannels()
            rate = opened.getframerate()
            width = opened.getsampwidth()
            promised = opened.getnframes()
            data = opened.readframes(promised)
    except (wave.Error, EOFError) as problem:
        raise ValueError("%s is not a WAV file that can be played (%s)"
                         % (path.name, str(problem) or "it is cut off")) from None
    if channels < 1 or rate < 1 or width < 1:
        raise ValueError("%s is not a WAV file that can be played" % path.name)
    frames = len(data) // (channels * width)
    loudest = average = None
    clipped = False
    if width == 2 and frames:
        samples = array.array("h")
        samples.frombytes(data[:frames * channels * 2])
        if sys.byteorder == "big":
            samples.byteswap()
        highest, lowest = max(samples), min(samples)
        loudest = max(highest, -lowest) / FULL_SCALE
        average = sum(abs(sample) for sample in samples) / len(samples) / FULL_SCALE
        clipped = highest >= FULL_SCALE - 1 or lowest <= -FULL_SCALE
    return Recording(frames / rate, channels, rate, width * 8, loudest, average,
                     clipped, frames < promised)


def describe(recording):
    """The lines that say what a recording holds."""
    kind = {1: "mono", 2: "stereo"}.get(recording.channels,
                                        "%d channels" % recording.channels)
    lines = ["%.1f s, %s, %d Hz, %d bit"
             % (recording.seconds, kind, recording.rate, recording.bits)]
    if recording.cut_off:
        lines.append("the file is shorter than it says: the recording was cut off")
    if recording.seconds == 0:
        lines.append("there is no sound in it")
    elif recording.loudest is None:
        lines.append("its level was not measured (that is done for 16 bit only)")
    elif recording.loudest == 0:
        lines.append("it is silent: every sample is 0")
    else:
        lines.append("loudest %.0f%% of full scale, average %.1f%%"
                     % (recording.loudest * 100, recording.average * 100))
        if recording.clipped:
            lines.append("it reaches full scale: its loudest part is probably distorted")
    return lines


def newest_on_pi(host, run=pi_photo.run_program):
    """The path, on the Pi, of the newest recording there."""
    command = "ls -t %s/*.wav 2>/dev/null | head -n 1" % SOUND_ON_PI
    code, said = run(["ssh", *pi_photo.SSH_OPTIONS, host, command])
    if code != 0:
        raise RuntimeError("could not ask the Pi: %s" % (said or "ssh failed"))
    if not said:
        raise RuntimeError("the Pi has no recording in ~/%s" % SOUND_ON_PI)
    return said.splitlines()[-1].strip()


def play(path):
    """Play the file to its end, where there is a way to ask for that."""
    if winsound is None:
        return False
    # Without SND_NODEFAULT a file that cannot be played gives Windows' own ding.
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    return True


def fetch_and_play(name=None, local=None, folder="~/RobotSound", host="pi",
                   play_it=True, run=pi_photo.run_program, play=play, say=print,
                   environ=None):
    """The whole job. Returns the path of the recording on this PC."""
    if local:
        sound = Path(local).expanduser()
        if not sound.is_file():
            raise RuntimeError("no such file: %s" % sound)
    else:
        folder = pi_photo.safe_folder(folder, environ)
        if name:
            if "/" in name or "\\" in name:
                raise RuntimeError("give the recording's file name only, not a path")
            remote = "%s/%s" % (SOUND_ON_PI, name)
        else:
            remote = newest_on_pi(host, run)
            say("newest on the Pi: %s" % remote.rsplit("/", 1)[-1])
        sound = pi_photo.copy_from_pi(host, remote, folder, run)
        say("copied to: %s" % sound)
    recording = read_recording(sound)
    for line in describe(recording):
        say(line)
    if play_it and recording.seconds > 0:
        say("playing it ...")
        say("played to the end" if play(sound) else "play it by hand: %s" % sound)
    return sound


def build_parser():
    parser = argparse.ArgumentParser(
        description="Copy a sound recording from the Pi to this PC and play it.")
    parser.add_argument("name", nargs="?",
                        help="a recording's file name on the Pi (default: the newest)")
    parser.add_argument("--file", dest="local",
                        help="a recording already on this PC: only play it")
    parser.add_argument("--dir", dest="folder", default="~/RobotSound",
                        help="where copies go on this PC (default: %(default)s)")
    parser.add_argument("--host", default="pi", help="the ssh name of the Pi")
    parser.add_argument("--no-play", dest="play_it", action="store_false",
                        help="do not play it, only say what it holds")
    return parser


def main(arguments=None):
    options = build_parser().parse_args(arguments)
    try:
        fetch_and_play(options.name, options.local, options.folder, options.host,
                       options.play_it)
    except (RuntimeError, ValueError, OSError) as problem:
        print("error: %s" % problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
