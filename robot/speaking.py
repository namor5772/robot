"""Speaking: text turned into a WAV file, and played through the Pi's speakers.

Claude makes no sound, so the text goes to a text-to-speech service (xAI's)
and a WAV file comes back. The file is kept, so that it can be played again,
and `aplay`, which the Pi has, plays it. The request is plain HTTPS made with
the standard library, with the key that hearing uses.
"""

import io
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

from robot.hearing import KEY_ENV

VOICE_ENV = "ROBOT_VOICE"  # one of the service's voices, to overrule DEFAULT_VOICE
DEVICE_ENV = "ROBOT_SPEAKER_DEVICE"  # an ALSA device name, to overrule the one found

TTS_URL = "https://api.x.ai/v1/tts"
DEFAULT_VOICE = "eve"  # the service's own default
TTS_RATE = 24000  # samples a second, the service's default
TTS_TIMEOUT = 120
TTS_DOLLARS_PER_CHAR = 15.00 / 1_000_000  # xAI bills by the character of text
MAX_CHARS = 2000  # about two minutes of speech; the service itself takes 60,000

FOLDER_NAME = "robot-sound"  # in the home folder, beside the robot's recordings
RESULT_PREFIX = "Spoken"

_CARD_LINE = re.compile(r"^card \d+: (\S+) \[(.*?)\], device (\d+):", re.MULTILINE)


def available() -> bool:
    """Whether speaking can work here: something to play with, and a key."""
    return (os.name == "posix" and shutil.which("aplay") is not None
            and bool(os.environ.get(KEY_ENV, "").strip()))


def find_speakers():
    """The device to play through, as (ALSA device, name to show).

    It is the first playback device `aplay -l` lists, named by its card.
    """
    given = os.environ.get(DEVICE_ENV, "").strip()
    if given:
        return given, given
    try:
        listing = subprocess.run(["aplay", "-l"], capture_output=True, text=True,
                                 errors="replace", stdin=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"the sound outputs could not be listed: {error}") from None
    found = _CARD_LINE.search(listing.stdout)
    if found is None:
        raise RuntimeError("no sound output was found (aplay -l lists no playback device)")
    card, label, device = found.groups()
    return f"plughw:CARD={card},DEV={device}", label or card


def text_wanted(value) -> str:
    """The text to speak, from the tool's input."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("'text' must be the words to speak")
    text = value.strip()
    if len(text) > MAX_CHARS:
        raise ValueError(f"'text' is {len(text):,} characters, more than the {MAX_CHARS:,} "
                         "that one call speaks. Say it in several calls, or say less.")
    return text


def voice() -> str:
    return os.environ.get(VOICE_ENV, "").strip() or DEFAULT_VOICE


def synthesize(text: str) -> bytes:
    """Send the text to the service and return the sound, as it came."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{KEY_ENV} is not set, so nothing can be spoken")
    body = json.dumps({"text": text, "voice_id": voice(), "language": "auto",
                       "output_format": {"codec": "wav", "sample_rate": TTS_RATE}})
    request = urllib.request.Request(
        TTS_URL, data=body.encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "robot-speaking"})
    try:
        with urllib.request.urlopen(request, timeout=TTS_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        said = " ".join(error.read().decode("utf-8", "replace").split())[:200]
        if error.code in (401, 403) or "api key" in said.lower():
            raise RuntimeError(f"xAI rejected the API key: check {KEY_ENV}") from None
        if error.code == 404:
            raise RuntimeError(f"xAI knows no voice called '{voice()}': check {VOICE_ENV}"
                               ) from None
        raise RuntimeError(f"xAI text-to-speech answered HTTP {error.code}: {said}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"xAI could not be reached, so nothing was spoken: "
                           f"{getattr(error, 'reason', error)}") from None


def clean_wav(answer: bytes):
    """The service's answer as a proper WAV file: (file's bytes, seconds).

    The answer is read to its last sample whatever its header says of its
    length, and written again with a header that is right: a file made while
    the sound was still being produced can state a length of nothing.
    """
    try:
        with wave.open(io.BytesIO(answer), "rb") as came:
            channels, width, rate = came.getnchannels(), came.getsampwidth(), came.getframerate()
            sound = came.readframes(came.getnframes())
            if not sound:
                sound = came.readframes(len(answer))
    except (wave.Error, EOFError):
        raise RuntimeError("xAI text-to-speech sent something that is not a WAV file") from None
    frame = channels * width
    sound = sound[:len(sound) - len(sound) % frame]
    if not sound:
        raise RuntimeError("xAI text-to-speech sent a WAV file with no sound in it")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(sound)
    return buffer.getvalue(), len(sound) / (frame * rate)


def save(wav: bytes, now=None) -> Path:
    """Keep the file beside the robot's recordings and return its path."""
    folder = Path.home() / FOLDER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"speech_{stamp}.wav"
    count = 1
    while path.exists():  # two in one second
        count += 1
        path = folder / f"speech_{stamp}_{count}.wav"
    path.write_bytes(wav)
    return path


def play(path: Path, seconds: float, device: str) -> None:
    """Play a WAV file to its end. The player is killed if the call is
    interrupted, so that the sound stops at once."""
    process = subprocess.Popen(["aplay", "-q", "-D", device, str(path)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    try:
        _, complaint = process.communicate(timeout=seconds + 15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("the playing did not end in time and was stopped") from None
    except BaseException:  # Ctrl-C or STOP
        process.kill()
        process.wait()
        raise
    if process.returncode != 0:
        reason = " ".join(complaint.decode("utf-8", "replace").split())[:300]
        raise RuntimeError(f"the file could not be played: "
                           f"{reason or 'aplay ended with code ' + str(process.returncode)}")


def speak(tool_input: dict) -> str:
    """The speak tool: make the text into speech, keep the file, play it."""
    text = text_wanted(tool_input.get("text"))
    aloud = tool_input.get("play", True)
    if not isinstance(aloud, bool):
        raise ValueError("'play' must be true or false")
    wav, seconds = clean_wav(synthesize(text))
    path = save(wav)
    made = (f"{len(text):,} characters as {seconds:.1f} s of speech in the voice "
            f"'{voice()}', about ${len(text) * TTS_DOLLARS_PER_CHAR:.4f}, saved as {path}")
    if not aloud:
        return f"Speech made, not played: {made}."
    try:
        device, name = find_speakers()
        play(path, seconds, device)
    except RuntimeError as error:
        raise RuntimeError(f"{error}. The speech was made and is saved as {path}") from None
    return (f"{RESULT_PREFIX} through {name}: {made}. The sound was sent to the speakers; "
            "whether it was heard is not known.")
