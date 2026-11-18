"""Terminal input and output for the agent: what the person sees and types."""

import contextlib
import os
import re
import signal
import sys
import threading
import time

try:
    import readline  # noqa: F401  (line editing and history for input())
except ImportError:
    pass  # not available on Windows

LABEL = "robot> "
PROMPT = "you> "
ASK_LABEL = "robot asks> "

# Returned by Console.ask when Ctrl-C was pressed at the prompt.
INTERRUPTED = object()

# A reply that is exactly one of these words ends a conversation.
CONVO_END_WORDS = ("quit", "exit", "stop", "bye")
_END_PUNCTUATION = ".!?…,;:"


def convo_end_word(text):
    """The end word a reply consists of, or None.

    Case and closing punctuation are ignored: "Stop." counts, "stop the
    motor" is an ordinary reply.
    """
    word = (text or "").strip().rstrip(_END_PUNCTUATION).strip().lower()
    return word if word in CONVO_END_WORDS else None


# A terminal answers questions from the program that draws on it by sending
# the answer as if it were typed. tmux asks for the terminal's colours and
# type every time it attaches, and normally keeps the answers to itself. When
# one reaches our prompt instead, readline takes its escape characters as key
# presses and keeps the rest as text. What is left, measured with readline 8.2:
#     colours  ESC ] 11 ; rgb:0c0c/0c0c/0c0c ESC \   leaves  11;rgb:0c0c/0c0c/0c0c
#     type     ESC [ ? 61 ; 4 ; 6 c                  leaves  61;4;6c
#     type     ESC [ > 0 ; 10 ; 1 c                  leaves  0;10;1c
_HEX = "[0-9a-fA-F]"
_COLOUR_REPLY = f"1[0-9];rgb:{_HEX}{{1,4}}/{_HEX}{{1,4}}/{_HEX}{{1,4}}"
_TYPE_REPLY = r"[0-9]{1,5}(?:;[0-9]{1,5})+c"
_ONLY_TERMINAL_REPLIES = re.compile(f"(?:{_COLOUR_REPLY}|{_TYPE_REPLY})+")


def only_terminal_replies(line) -> bool:
    """True when a line holds nothing but answers from the terminal itself.

    Only a whole line counts. The same characters inside a sentence are left
    alone: there they are something the person typed, such as a question
    about them.
    """
    return bool(_ONLY_TERMINAL_REPLIES.fullmatch((line or "").strip()))


_DIM = "\033[2m"
_RESET = "\033[0m"
_RELAY_POLL_SECONDS = 0.5


class Interrupts:
    """Ctrl-C and shutdown handling for a loop that runs on the main thread.

    A signal handler that always raised could cut the loop in the middle of
    its bookkeeping and leave a tool call without its result. So the handler
    only sets a flag, and raises KeyboardInterrupt solely while the loop is
    inside a region it has declared safe to abandon (waiting on the network,
    a sleep, a prompt, a tool).
    """

    def __init__(self):
        self.interrupt = threading.Event()  # Ctrl-C: abandon what is running now
        self.stop = threading.Event()  # end the whole run (SIGTERM, hang-up)
        self._depth = 0
        self._presses = []

    def install(self):
        """Take over SIGINT, SIGTERM and SIGHUP. Main thread only."""
        signal.signal(signal.SIGINT, self._on_interrupt)
        signal.signal(signal.SIGTERM, self._on_stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._on_stop)

    def _on_interrupt(self, signum, frame):
        now = time.monotonic()
        self._presses = [t for t in self._presses if now - t < 3.0] + [now]
        if len(self._presses) >= 3:
            # Three presses in three seconds: the person wants out now. The
            # in-progress cost record on disk covers what this run spent.
            os._exit(130)
        self.interrupt.set()
        if self._depth > 0:
            raise KeyboardInterrupt

    def _on_stop(self, signum, frame):
        self.stop.set()
        self.interrupt.set()
        if self._depth > 0:
            raise KeyboardInterrupt

    @contextlib.contextmanager
    def raisable(self):
        """A region that Ctrl-C may abandon by raising KeyboardInterrupt."""
        self._depth += 1
        try:
            if self.interrupt.is_set():
                raise KeyboardInterrupt
            yield
        finally:
            self._depth -= 1

    def clear(self):
        """Forget a Ctrl-C that has been dealt with. A stop request stays."""
        if not self.stop.is_set():
            self.interrupt.clear()

    def pending(self) -> bool:
        return self.interrupt.is_set() or self.stop.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep, waking at once on Ctrl-C or a stop. True if interrupted."""
        try:
            with self.raisable():
                self.stop.wait(seconds)
        except KeyboardInterrupt:
            return True
        return self.pending()


def _isatty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Console:
    """Everything shown to the person, and every line read from them.

    The display switches mirror MyAgent's checkboxes: Activity (tool lines,
    retries, cost per call), Show Thinking, Tool Calls and Debug.
    """

    def __init__(self, *, activity=True, show_thinking=False, tool_calls=False, debug=False,
                 headless=False, relay_dir=None, interrupts=None, stdin=None, stdout=None):
        self.activity_on = activity
        self.show_thinking = show_thinking
        self.tool_calls_on = tool_calls
        self.debug_on = debug
        self.headless = headless
        self.relay_dir = relay_dir
        self.interrupts = interrupts or Interrupts()
        self._in = stdin if stdin is not None else sys.stdin
        self._out = stdout if stdout is not None else sys.stdout
        # A person is at the keyboard only when both ends are a terminal.
        self.tty = (not headless) and _isatty(self._in) and _isatty(self._out)
        self._styled = _isatty(self._out)
        self._lock = threading.RLock()
        self._transcript = None
        self._at_line_start = True
        self._label_due = True
        self._in_thinking = False
        self._relay_seq = 0
        self._parent_pid = os.getppid()
        self.input_wait_secs = 0.0  # time spent waiting on the person, not working
        self._startup_input_dropped = False

    def _drop_startup_input(self):
        """Before the first prompt, throw away what arrived while starting up.

        A terminal's answers to tmux can land here during the seconds the
        program takes to start (see only_terminal_replies). Left alone they
        would sit at the first prompt, in front of whatever is typed next.
        Only the first prompt: later on, typing ahead of the prompt is wanted.

        chat.sh starts the program with the terminal's echo off, so that such
        an answer is not printed either. Echo goes back on here: readline
        shows what is typed only when the terminal had echo on.
        """
        if self._startup_input_dropped:
            return
        self._startup_input_dropped = True
        try:
            import termios
            fd = self._in.fileno()
            termios.tcflush(fd, termios.TCIFLUSH)
            attrs = termios.tcgetattr(fd)
            attrs[3] |= termios.ECHO
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:  # no termios (Windows), or not a real terminal
            pass

    def set_transcript(self, transcript):
        self._transcript = transcript

    # -- output ------------------------------------------------------------

    def _show(self, text, dim):
        """Put text in front of the person. The windowed interface replaces this."""
        shown = f"{_DIM}{text}{_RESET}" if dim and self._styled else text
        try:
            self._out.write(shown)
            self._out.flush()
        except (OSError, ValueError, UnicodeError):
            pass  # the terminal is gone (hang-up) or cannot show this text

    def _emit(self, text, dim=False):
        if not text:
            return
        with self._lock:
            self._show(text, dim)
            if self._transcript is not None:
                self._transcript.write(text)
            self._at_line_start = text.endswith("\n")

    def _line(self, text, dim=False):
        """Print whole lines, starting on a fresh line."""
        with self._lock:
            if not self._at_line_start:
                self._emit("\n")
            self._emit(text.rstrip("\n") + "\n", dim=dim)
            self._label_due = True

    def text(self, delta):
        """A piece of the model's reply as it streams."""
        if not delta:
            return
        with self._lock:
            if self._in_thinking:
                self.thinking_end()
            if self._label_due:
                if not self._at_line_start:
                    self._emit("\n")
                self._emit(LABEL)
                self._label_due = False
            self._emit(delta)

    def thinking_start(self):
        if self.show_thinking:
            with self._lock:
                if not self._at_line_start:
                    self._emit("\n")
                self._emit("[thinking] ", dim=True)
                self._in_thinking = True

    def thinking_delta(self, delta):
        if self.show_thinking and delta:
            self._emit(delta, dim=True)

    def thinking_end(self):
        with self._lock:
            if self._in_thinking:
                self._in_thinking = False
                if not self._at_line_start:
                    self._emit("\n")
                self._label_due = True

    def activity(self, message):
        """A line about what the agent is doing. Shown with Activity on."""
        if self.activity_on:
            indented = "\n".join("  " + part for part in message.rstrip().splitlines())
            self._line(indented, dim=True)

    def tool_line(self, name, detail=""):
        if self.activity_on:
            self._line(f"[tool: {name}{': ' + detail if detail else ''}]", dim=True)

    def cost(self, call_num, cost_text):
        if self.activity_on:
            self._line(f"  call {call_num}: {cost_text.strip()}", dim=True)

    def warn(self, message):
        self._line("warning: " + message.strip())

    def error(self, message):
        self._line("error: " + message.strip())

    def note(self, message):
        """A plain line that is always shown."""
        self._line(message)

    def call_header(self, call_num):
        if self.debug_on or self.tool_calls_on:
            self._line(f"--- call #{call_num} ---", dim=True)

    def tool_call_json(self, text):
        if self.tool_calls_on:
            self._line("--- tool call ---\n" + text, dim=True)

    def debug_payload(self, text):
        if self.debug_on:
            self._line("--- request ---\n" + text, dim=True)

    def end_line(self):
        with self._lock:
            if self._in_thinking:
                self.thinking_end()
            if not self._at_line_start:
                self._emit("\n")
            self._label_due = True

    # -- input -------------------------------------------------------------

    def ask(self, *, question="", preface="", prompt=PROMPT):
        """Get one reply from the person.

        Returns the line they typed ("" for an empty line), None when nobody
        can answer (end of input, a headless run with no relay, a stop), or
        INTERRUPTED when Ctrl-C was pressed at the prompt.

        `question` is what the model asked through user_prompt; it is shown
        before the prompt. `preface` is what the model said just before
        asking: it is already on screen, so it only goes to a relay folder.
        """
        self.end_line()
        if question:
            self._line(ASK_LABEL + question.strip())
        started = time.monotonic()
        try:
            return self._read_reply(question, preface, prompt)
        finally:
            self.input_wait_secs += time.monotonic() - started

    def _read_reply(self, question, preface, prompt):
        if self.interrupts.stop.is_set():
            return None
        if self.headless:
            if not self.relay_dir:
                return None  # unattended and nobody is relaying answers
            return self._ask_relay(question, preface)
        if self.tty:
            return self._ask_terminal(question, preface, prompt)
        return self._ask_piped(prompt)

    def _ask_terminal(self, question, preface, prompt):
        seq = self._relay_announce(question, preface)
        self._emit("\n")
        self._drop_startup_input()
        try:
            with self.interrupts.raisable():
                line = input(prompt)
        except EOFError:
            self._after_terminal_line(prompt, None)
            return None
        except KeyboardInterrupt:
            self.interrupts.clear()
            self._after_terminal_line(prompt, None)
            return None if self.interrupts.stop.is_set() else INTERRUPTED
        finally:
            self._relay_answered(seq)
        self._after_terminal_line(prompt, line)
        if only_terminal_replies(line):
            # Nobody typed this, so it is no more an answer than a bare Enter.
            self._line("(ignored: that line came from your terminal, not from the keyboard)")
            return ""
        return line.strip()

    def _after_terminal_line(self, prompt, line):
        # The terminal echoed what was typed, so _emit never saw it: record it.
        with self._lock:
            if line is None:
                try:
                    self._out.write("\n")
                    self._out.flush()
                except (OSError, ValueError):
                    pass
            if self._transcript is not None:
                self._transcript.write(f"{prompt}{line if line is not None else ''}\n")
            self._at_line_start = True
            self._label_due = True

    def _ask_piped(self, prompt):
        self._emit("\n" + prompt)
        try:
            with self.interrupts.raisable():
                line = self._in.readline()
        except KeyboardInterrupt:
            self._emit("\n")
            return None
        except (OSError, ValueError):
            line = ""
        if line == "":  # end of input
            self._emit("\n")
            return None
        line = line.rstrip("\r\n")
        self._emit(line + "\n")  # echo, so a piped log reads like a chat
        with self._lock:
            self._label_due = True
        return line.strip()

    # A relay folder lets another process answer for the person: a parent run
    # with canned answers, or a phone listener. See robot/relay.py.

    def _relay_text(self, question, preface):
        parts = [part.strip() for part in (preface, question) if part and part.strip()]
        return "\n\n".join(parts) or "(the agent is waiting for a reply)"

    def _relay_announce(self, question, preface):
        if not self.relay_dir:
            return None
        from robot import relay
        self._relay_seq += 1
        try:
            relay.write_request(self.relay_dir, self._relay_seq, self._relay_text(question, preface))
        except OSError:
            return None
        return self._relay_seq

    def _relay_answered(self, seq):
        if seq is None:
            return
        from robot import relay
        try:
            relay.clear(self.relay_dir)
            relay.mark_answered(self.relay_dir, seq)
        except OSError:
            pass

    def _ask_relay(self, question, preface):
        from robot import relay
        seq = self._relay_announce(question, preface)
        if seq is None:
            return None
        while True:
            reply = relay.read_reply(self.relay_dir, seq)
            if reply is not None:
                try:
                    relay.clear(self.relay_dir)
                except OSError:
                    pass
                self._line(PROMPT + reply)
                return reply.strip()
            # Give up when nobody can answer any more: the folder was removed
            # or the process that started this run has gone.
            if not os.path.isdir(self.relay_dir) or os.getppid() != self._parent_pid:
                return None
            if self.interrupts.wait(_RELAY_POLL_SECONDS):
                return None
