"""Speaking: text turned into a WAV file, and played through the Pi's speakers.

Claude makes no sound, so the text goes to a text-to-speech service (xAI's)
and a WAV file comes back. The file is kept, so that it can be played again,
and `aplay`, which the Pi has, plays it. The request is plain HTTPS made with
the standard library, with the key that hearing uses.

Which voice speaks, and how fast, is kept in a small file in the data folder.
It is read at every call, so a change holds from the next sentence on, in
every run on this Pi.
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

from robot.datastore import DataDir, atomic_write_text
from robot.hearing import KEY_ENV

VOICE_ENV = "ROBOT_VOICE"  # the voice where the settings file names none
DEVICE_ENV = "ROBOT_SPEAKER_DEVICE"  # an ALSA device name, to overrule the one found

TTS_URL = "https://api.x.ai/v1/tts"
VOICES_URL = "https://api.x.ai/v1/tts/voices"
DEFAULT_VOICE = "eve"  # the service's own default
DEFAULT_SPEED = 1.0
MIN_SPEED, MAX_SPEED = 0.7, 1.5  # the service's own limits
TTS_RATE = 24000  # samples a second, the service's default
TTS_TIMEOUT = 120
TTS_DOLLARS_PER_CHAR = 15.00 / 1_000_000  # xAI bills by the character of text
MAX_CHARS = 2000  # about two minutes of speech; the service itself takes 60,000

FOLDER_NAME = "robot-sound"  # in the home folder, beside the robot's recordings
SETTINGS_NAME = "voice_settings.json"  # in the data folder
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


def voice_wanted(value):
    """A voice's name from a tool's input, or None where none was given."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("'voice' must be the name of a voice")
    return value.strip().lower()


def speed_wanted(value):
    """A speed from a tool's input, or None where none was given."""
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not MIN_SPEED <= value <= MAX_SPEED):
        raise ValueError(f"'speed' must be a number from {MIN_SPEED} to {MAX_SPEED} "
                         "(1.0 is the usual speed)")
    return round(float(value), 2)


def settings_file() -> Path:
    return DataDir().root / SETTINGS_NAME


def saved_settings() -> dict:
    """What the settings file holds, as far as it can be used: 'voice' and
    'speed', each only when it is there and makes sense."""
    try:
        raw = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    kept = {}
    if isinstance(raw, dict):
        for name, wanted in (("voice", voice_wanted), ("speed", speed_wanted)):
            try:
                value = wanted(raw.get(name))
            except ValueError:
                continue
            if value is not None:
                kept[name] = value
    return kept


def voice() -> str:
    """The voice in use: the saved one, else the environment's, else the usual."""
    return (saved_settings().get("voice")
            or os.environ.get(VOICE_ENV, "").strip().lower() or DEFAULT_VOICE)


def speed() -> float:
    return saved_settings().get("speed", DEFAULT_SPEED)


def _ask(url, body=None, timeout=TTS_TIMEOUT, doing="spoken", voice_id=None) -> bytes:
    """One request to the service; its answer's bytes, or a RuntimeError that
    says what went wrong."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{KEY_ENV} is not set, so nothing can be {doing}")
    request = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode("utf-8"),
        method="GET" if body is None else "POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "robot-speaking"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        said = " ".join(error.read().decode("utf-8", "replace").split())[:200]
        if error.code in (401, 403) or "api key" in said.lower():
            raise RuntimeError(f"xAI rejected the API key: check {KEY_ENV}") from None
        if error.code == 404 and voice_id:
            raise RuntimeError(f"xAI knows no voice called '{voice_id}'. The voice_settings "
                               "tool lists the voices there are.") from None
        raise RuntimeError(f"xAI text-to-speech answered HTTP {error.code}: {said}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"xAI could not be reached, so nothing was {doing}: "
                           f"{getattr(error, 'reason', error)}") from None


def synthesize(text: str, voice_id=None, pace=None) -> bytes:
    """Send the text to the service and return the sound, as it came."""
    voice_id = voice_id or voice()
    pace = speed() if pace is None else pace
    body = {"text": text, "voice_id": voice_id, "language": "auto",
            "output_format": {"codec": "wav", "sample_rate": TTS_RATE}}
    if pace != DEFAULT_SPEED:
        body["speed"] = pace
    return _ask(TTS_URL, body, voice_id=voice_id)


def list_voices() -> list:
    """The service's voices, as it lists them: dicts with 'voice_id' and, where
    the service says, 'name', 'gender' and 'language'."""
    answer = _ask(VOICES_URL, timeout=30, doing="listed")
    try:
        voices = json.loads(answer)["voices"]
        found = [entry for entry in voices
                 if isinstance(entry, dict) and isinstance(entry.get("voice_id"), str)]
    except (ValueError, TypeError, KeyError):
        found = []
    if not found:
        raise RuntimeError("xAI's list of voices could not be read")
    return sorted(found, key=lambda entry: entry["voice_id"].lower())


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


def say(text: str) -> None:
    """Speak a text in the voice in use and keep nothing: for what the program
    itself has to say, as distinct from what the model says with the tool."""
    wav, seconds = clean_wav(synthesize(text))
    folder = DataDir().tmp_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"say_{os.getpid()}.wav"
    path.write_bytes(wav)
    try:
        device, _ = find_speakers()
        play(path, seconds, device)
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _pace_words(pace: float) -> str:
    return "" if pace == DEFAULT_SPEED else f" at speed {pace:g}"


def speak(tool_input: dict) -> str:
    """The speak tool: make the text into speech, keep the file, play it."""
    text = text_wanted(tool_input.get("text"))
    aloud = tool_input.get("play", True)
    if not isinstance(aloud, bool):
        raise ValueError("'play' must be true or false")
    voice_id = voice_wanted(tool_input.get("voice")) or voice()
    pace = speed_wanted(tool_input.get("speed"))
    pace = speed() if pace is None else pace
    wav, seconds = clean_wav(synthesize(text, voice_id, pace))
    path = save(wav)
    made = (f"{len(text):,} characters as {seconds:.1f} s of speech in the voice "
            f"'{voice_id}'{_pace_words(pace)}, about ${len(text) * TTS_DOLLARS_PER_CHAR:.4f}, "
            f"saved as {path}")
    if not aloud:
        return f"Speech made, not played: {made}."
    try:
        device, name = find_speakers()
        play(path, seconds, device)
    except RuntimeError as error:
        raise RuntimeError(f"{error}. The speech was made and is saved as {path}") from None
    return (f"{RESULT_PREFIX} through {name}: {made}. The sound was sent to the speakers; "
            "whether it was heard is not known.")


def _now_in_use() -> str:
    return f"The voice in use is '{voice()}', at speed {speed():g} (1 is the usual speed)."


def _voice_line(entry: dict) -> str:
    details = [str(entry[name]) for name in ("gender", "language")
               if isinstance(entry.get(name), str) and entry[name]]
    return entry["voice_id"].lower() + (f" ({', '.join(details)})" if details else "")


def voice_settings(tool_input: dict) -> str:
    """The voice_settings tool: list the voices, or change voice and speed."""
    action = tool_input.get("action")
    if action == "list":
        voices = list_voices()
        return (f"{_now_in_use()}\nThe {len(voices)} voices there are:\n"
                + "\n".join(_voice_line(entry) for entry in voices)
                + f"\nThe speed can be set from {MIN_SPEED} to {MAX_SPEED}.")
    if action != "set":
        raise ValueError("'action' must be 'list' or 'set'")
    voice_id = voice_wanted(tool_input.get("voice"))
    pace = speed_wanted(tool_input.get("speed"))
    if voice_id is None and pace is None:
        raise ValueError("give 'voice', 'speed' or both to set")
    if voice_id is not None:
        known = [entry["voice_id"].lower() for entry in list_voices()]
        if voice_id not in known:
            raise ValueError(f"there is no voice called '{voice_id}'. The voices are: "
                             f"{', '.join(known)}")
    settings = saved_settings()
    if voice_id is not None:
        settings["voice"] = voice_id
    if pace is not None:
        settings["speed"] = pace
    atomic_write_text(settings_file(), json.dumps(settings, indent=2) + "\n")
    return f"Saved. {_now_in_use()} It holds from the next thing spoken, in every run."
