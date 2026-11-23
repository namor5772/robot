"""Hands-free: while the robot waits for a message, listen for one.

The microphone runs for as long as the wait lasts. A `Segmenter` watches how
loud each tenth of a second is and cuts out what was said: from just before
the sound rose above the room's own level to the pause that follows. An `Ear`
feeds it from `arecord` on a thread of its own, has each cut-out piece turned
into text (see robot.hearing), and holds the words for whoever is waiting.
Pieces in which the service finds no speech are dropped, so a noise is not a
message and silence never is.
"""

import array
import collections
import math
import queue
import subprocess
import threading

from robot import hearing

RATE = hearing.RATE
CHUNK_BYTES = RATE * 2 // 10  # a tenth of a second of 16-bit sound

# A microphone that has been resting starts with a thump and takes most of a
# second to settle (measured on the Pi: 7,100, 2,500, then 600 to 1,300 for
# seven tenths, in a room whose own level was 300). That much is not looked at.
LEAD_IN_CHUNKS = 10
PRE_ROLL_CHUNKS = 5   # kept from before the sound rose: the start of a word is soft
START_WINDOW = 4      # speech has started when 3 of the last 4 tenths were loud
START_LOUD = 3
END_QUIET_CHUNKS = 15  # and has ended after a second and a half of quiet
TAIL_CHUNKS = 3        # of which this much is kept
MAX_CHUNKS = 600       # a minute: longer than that is cut and sent as it is
MIN_LOUD_CHUNKS = 3    # less than this in all was a click, not a word

MIN_FLOOR = 40.0  # a room is never taken to be quieter than this

LISTENING, HEARING, WORKING = "listening", "hearing", "working"


def level(chunk: bytes) -> float:
    """How loud a piece of 16-bit sound is: the RMS of its samples around
    their own average, so that a microphone's steady offset counts as nothing."""
    samples = array.array("h")
    samples.frombytes(chunk[:len(chunk) - len(chunk) % 2])
    if not samples:
        return 0.0
    mean = sum(samples) / len(samples)
    return math.sqrt(max(0.0, sum(s * s for s in samples) / len(samples) - mean * mean))


class Segmenter:
    """Cuts what was said out of a stream of sound, a tenth of a second at a time.

    `feed` takes each chunk and returns the sound of an utterance when one has
    just ended, else None. The room's own level (`floor`) is followed all the
    time, so the same code serves a quiet room and a noisy one.
    """

    def __init__(self):
        self.floor = None
        self.hearing = False
        self._seen = 0
        self._recent = collections.deque(maxlen=START_WINDOW)
        # The pre-roll, and the loud tenths that came before speech was sure.
        self._before = collections.deque(maxlen=PRE_ROLL_CHUNKS + START_LOUD - 1)
        self._kept = []
        self._levels = []
        self._loud = 0
        self._quiet_run = 0
        self.last_levels = []  # of the utterance returned last

    def _start_level(self):
        return max(self.floor * 2.5, self.floor + 300.0)

    def _end_level(self):
        return max(self.floor * 1.6, self.floor + 150.0)

    def feed(self, chunk: bytes):
        self._seen += 1
        if self._seen <= LEAD_IN_CHUNKS:
            return None
        loud = level(chunk)
        if self.floor is None:
            # The first tenth is taken for the room. Should somebody be talking
            # already, the level comes down within a second of their stopping.
            self.floor = max(MIN_FLOOR, loud)
        if not self.hearing:
            return self._while_quiet(chunk, loud)
        return self._while_hearing(chunk, loud)

    def _while_quiet(self, chunk, loud):
        if loud < self.floor:  # the room is quieter than was thought: follow fast
            self.floor = max(MIN_FLOOR, 0.7 * self.floor + 0.3 * loud)
        elif loud < self._start_level():  # a little louder: follow slowly
            self.floor = 0.98 * self.floor + 0.02 * loud
        self._recent.append(loud >= self._start_level())
        if sum(self._recent) >= START_LOUD:
            self.hearing = True
            self._kept = list(self._before) + [chunk]
            self._levels = [loud]
            self._loud = sum(self._recent)
            self._quiet_run = 0
            self._recent.clear()
            self._before.clear()
        else:
            self._before.append(chunk)
        return None

    def _while_hearing(self, chunk, loud):
        self._kept.append(chunk)
        self._levels.append(loud)
        if loud >= self._end_level():
            self._quiet_run = 0
            if loud >= self._start_level():
                self._loud += 1
        else:
            self._quiet_run += 1
        if self._quiet_run < END_QUIET_CHUNKS and len(self._kept) < MAX_CHUNKS:
            return None
        kept, loud_chunks = self._kept, self._loud
        drop = max(0, self._quiet_run - TAIL_CHUNKS)
        if drop:
            kept = kept[:-drop]
        self.last_levels = self._levels
        self.hearing = False
        self._kept, self._quiet_run = [], 0
        if loud_chunks < MIN_LOUD_CHUNKS:
            return None
        return b"".join(kept)

    def not_speech(self):
        """The utterance returned last held no words: it was the room. Take the
        room to be that loud, so that the same noise does not start another."""
        if self.last_levels:
            typical = sorted(self.last_levels)[len(self.last_levels) // 2]
            self.floor = max(self.floor, typical / 2.0)


class Ear:
    """Listens on a thread while the robot waits, and holds what was said.

    start() opens the microphone, take() gives the words of an utterance once
    there are some (else None), stop() closes the microphone. `state` says
    what the ear is doing, and `problem` why it is not listening.
    """

    def __init__(self, transcribe=hearing.transcribe):
        self._transcribe = transcribe
        self._heard = queue.Queue()
        self._process = None
        self._thread = None
        self._stopping = threading.Event()
        self.state = LISTENING
        self.problem = ""   # why listening ended, when it ended by itself
        self.trouble = ""   # the last thing that went wrong without ending it

    def start(self) -> bool:
        """Open the microphone. False, with `problem` set, when that cannot be."""
        if not hearing.available():
            self.problem = (f"there is no microphone recorder here, or {hearing.KEY_ENV} "
                            "is not set")
            return False
        try:
            device, _ = hearing.find_microphone()
            self._process = subprocess.Popen(
                ["arecord", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-c", "1",
                 "-r", str(RATE)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, RuntimeError) as error:
            self.problem = str(error)
            return False
        self._thread = threading.Thread(target=self._listen, name="ear", daemon=True)
        self._thread.start()
        return True

    def take(self):
        """The words of an utterance that has been heard, or None."""
        try:
            return self._heard.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Close the microphone. What is being worked out is dropped."""
        self._stopping.set()
        process = self._process
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        if process is not None:
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

    def _listen(self):
        segmenter = Segmenter()
        read = self._process.stdout.read
        while not self._stopping.is_set():
            chunk = read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:  # the recorder has ended
                if not self._stopping.is_set():
                    said = self._process.stderr.read().decode("utf-8", "replace")
                    self.problem = ("the microphone stopped: "
                                    + (" ".join(said.split())[:200] or "no reason given"))
                return
            sound = segmenter.feed(chunk)
            if sound is None:
                self.state = HEARING if segmenter.hearing else LISTENING
                continue
            self.state = WORKING
            try:
                text = self._transcribe(hearing.wav_file(sound))
            except RuntimeError as error:
                self.trouble = str(error)
                text = ""
            if self._stopping.is_set():
                return
            if text:
                self._heard.put(text)
            else:
                segmenter.not_speech()
            self.state = LISTENING
