"""Hearing: a few seconds through the Pi's microphone, turned into text.

Claude takes no sound, so a recording goes to a speech-to-text service (xAI's
Grok Speech to Text) and only the words come back. Recording is done by
`arecord`, which the Pi has; the upload is a plain HTTPS request made with the
standard library. Nothing is written to disk: the recording lives in memory
for the length of one call.
"""

import array
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

KEY_ENV = "XAI_API_KEY"
DEVICE_ENV = "ROBOT_MIC_DEVICE"  # an ALSA device name, to overrule the one found

STT_URL = "https://api.x.ai/v1/stt"
STT_MODEL = "grok-voice-transcribe-2.0"
STT_DOLLARS_PER_SECOND = 0.10 / 3600  # xAI bills by the hour of audio
STT_TIMEOUT = 90

RATE = 16000  # samples a second, mono, 16 bit: what speech models are fed
DEFAULT_SECONDS = 5
MAX_SECONDS = 120  # 3.8 MB of sound; the whole of it is held in memory
# A USB microphone that has been resting starts with a thump. The first second
# of every recording is therefore made and thrown away.
LEAD_IN_SECONDS = 1
# Below this (of 32767) the microphone gave nothing at all: muted, or not
# there. That is not sent anywhere. A quiet room is far above it, and what a
# quiet room holds is left to the speech model, which answers with no words.
SILENCE_PEAK = 50

RESULT_PREFIX = "Microphone transcript"

_CARD_LINE = re.compile(r"^card \d+: (\S+) \[(.*?)\], device (\d+):", re.MULTILINE)


def available() -> bool:
    """Whether hearing can work here: something to record with, and a key."""
    return (os.name == "posix" and shutil.which("arecord") is not None
            and bool(os.environ.get(KEY_ENV, "").strip()))


def find_microphone():
    """The device to record from, as (ALSA device, name to show).

    It is the first capture device `arecord -l` lists, named by its card and
    not by its number, because the numbers change from one board to another.
    """
    given = os.environ.get(DEVICE_ENV, "").strip()
    if given:
        return given, given
    try:
        listing = subprocess.run(["arecord", "-l"], capture_output=True, text=True,
                                 errors="replace", stdin=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"the microphones could not be listed: {error}") from None
    found = _CARD_LINE.search(listing.stdout)
    if found is None:
        raise RuntimeError("no microphone was found (arecord -l lists no capture device)")
    card, label, device = found.groups()
    return f"plughw:CARD={card},DEV={device}", label or card


def seconds_wanted(value) -> int:
    """The whole number of seconds to listen for, from the tool's input."""
    if value is None:
        return DEFAULT_SECONDS
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError("'seconds' must be a positive number")
    if value > MAX_SECONDS:
        raise ValueError(f"'seconds' can be at most {MAX_SECONDS}")
    return math.ceil(value)


def record(seconds: int, device: str) -> bytes:
    """Record `seconds` of sound and return it as 16-bit samples.

    One second more is recorded in front and dropped (see LEAD_IN_SECONDS).
    The recorder is killed if the call is interrupted, so that the microphone
    is free again at once.
    """
    command = ["arecord", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-c", "1",
               "-r", str(RATE), "-d", str(seconds + LEAD_IN_SECONDS)]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        sound, complaint = process.communicate(timeout=seconds + LEAD_IN_SECONDS + 15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("the recording did not end in time and was stopped") from None
    except BaseException:  # Ctrl-C or STOP: do not leave the microphone taken
        process.kill()
        process.wait()
        raise
    if process.returncode != 0:
        reason = " ".join(complaint.decode("utf-8", "replace").split())[:300]
        raise RuntimeError(f"the microphone could not be recorded from: "
                           f"{reason or 'arecord ended with code ' + str(process.returncode)}")
    sound = sound[LEAD_IN_SECONDS * RATE * 2:]
    return sound[:len(sound) - len(sound) % 2]


def peak(sound: bytes) -> int:
    """The loudest sample (0 to 32768) of 16-bit little-endian sound."""
    samples = array.array("h")
    samples.frombytes(sound[:len(sound) - len(sound) % 2])
    if not samples:
        return 0
    if sys.byteorder == "big":
        samples.byteswap()
    return max(-min(samples), max(samples))


def wav_file(sound: bytes) -> bytes:
    """The samples as a WAV file in memory: what is uploaded."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(sound)
    return buffer.getvalue()


def _form(model: str, wav: bytes):
    """The request body, as (content type, bytes). The file must come last."""
    boundary = "robot" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
        f"{model}\r\n".encode("ascii"),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode("ascii"),
        wav,
        f"\r\n--{boundary}--\r\n".encode("ascii"),
    ]
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def transcribe(wav: bytes) -> str:
    """Send a WAV file to the speech-to-text service and return the words.

    An empty answer is a real one: the service heard no speech.
    """
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{KEY_ENV} is not set, so nothing can be transcribed")
    content_type, body = _form(STT_MODEL, wav)
    request = urllib.request.Request(
        STT_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": content_type,
                 "User-Agent": "robot-hearing"})
    try:
        with urllib.request.urlopen(request, timeout=STT_TIMEOUT) as response:
            answer = response.read()
    except urllib.error.HTTPError as error:
        said = " ".join(error.read().decode("utf-8", "replace").split())[:200]
        # xAI answers a wrong key with 400 and "Incorrect API key provided".
        if error.code in (401, 403) or "api key" in said.lower():
            raise RuntimeError(f"xAI rejected the API key: check {KEY_ENV}") from None
        raise RuntimeError(f"xAI speech-to-text answered HTTP {error.code}: {said}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"xAI could not be reached, so nothing was transcribed: "
                           f"{getattr(error, 'reason', error)}") from None
    try:
        text = json.loads(answer).get("text")
    except (ValueError, AttributeError):
        raise RuntimeError("xAI speech-to-text sent an answer that could not be read") from None
    return (text or "").strip()


def listen(tool_input: dict) -> str:
    """The microphone_listen tool: listen, and say what was said."""
    seconds = seconds_wanted(tool_input.get("seconds"))
    device, name = find_microphone()
    sound = record(seconds, device)
    heard = len(sound) / (2 * RATE)
    if heard < 0.2:
        raise RuntimeError(f"nothing was recorded through {name}")
    loudest = peak(sound)
    if loudest < SILENCE_PEAK:
        return (f"{RESULT_PREFIX}: heard only silence for {heard:.1f} s through {name} "
                f"(loudest sample {loudest} of 32767). Nothing was sent for transcription. "
                "The microphone may be muted or unplugged.")
    started = time.monotonic()
    text = transcribe(wav_file(sound))
    detail = (f"{heard:.1f} s through {name}, transcribed by {STT_MODEL} in "
              f"{time.monotonic() - started:.1f} s, about ${heard * STT_DOLLARS_PER_SECOND:.4f}")
    if not text:
        return f"{RESULT_PREFIX}: no speech was recognised ({detail})."
    return f'{RESULT_PREFIX} ({detail}): "{text}"'
