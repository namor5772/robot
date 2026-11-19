"""The main window, and how a run and the screen work side by side.

Two threads share the work. The agent loop keeps the main thread, where its
Ctrl-C and shutdown handling live (robot.console.Interrupts): there it runs
one instruction after another, as the screen asks for them. The screen has a
thread of its own that draws and reads the keyboard. Three queues connect the
two (Bridge).
"""

import argparse
import contextlib
import io
import os
import queue
import re
import signal
import sys
import threading
import time
import traceback

from dotenv import load_dotenv

from robot import instructions, models
from robot import main as command_line
from robot.console import Console, Interrupts
from robot.datastore import DataDir, load_store, save_store
from robot.tui.dialogs import MessageBox, PickDialog, TextDialog
from robot.tui.editor import InstructionEditor
from robot.tui.screen import Paste
from robot.tui.skillsui import SkillsManager
from robot.tui.text import clip, text_width, wrap_line
from robot.tui.widgets import (
    Button, Checkbox, TextArea, Widget, Window, draw_frame, draw_scroll_marks, flow, split_hot)

MIN_ROWS = 18
MIN_COLS = 72

STATE_FILE = "tui_state.json"
ERROR_LOG = "tui_errors.log"
_ERROR_LOG_LIMIT = 256 * 1024

# Several copies of the interface can be open at once (ui.sh --session NAME).
# A copy's session name tells it apart: it is shown in the top row and is part
# of the name of the file the copy keeps its settings in. The first copy, the
# one started without a name, is session 1 and has none of that.
_SESSION_NAME = re.compile(r"[A-Za-z0-9_-]{1,12}")
FIRST_SESSION = "1"


def session_name(value) -> str:
    """A --session value as the program keeps it: "" for the first copy."""
    if not _SESSION_NAME.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "a session name is 1 to 12 letters, digits, '-' or '_' (for example: 2)")
    return "" if value == FIRST_SESSION else value


def state_file_name(session="") -> str:
    """The file a copy of the interface keeps what it remembers in."""
    return f"tui_state_{session}.json" if session else STATE_FILE

# The signals a run is stopped or ended with (see robot.console.Interrupts).
_RUN_SIGNALS = {getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP")
                if hasattr(signal, name)}

# The display switches, as the chat's command line has them, and their values
# on first use.
FLAGS = {"activity": True, "thinking": False, "tool_calls": False, "debug": False,
         "save_thinking": False}

HELP_TEXT = """\
GETTING AROUND
  Tab, Shift+Tab   the next or the previous control
  Alt+letter       the control that shows that letter highlighted
  Enter or Space   press a button, tick a box, open a list
  Escape           close a window
  Mouse            click a control; the wheel scrolls. To select
                   text with the mouse, hold Shift while dragging.

THE MAIN WINDOW
  F2   START       run the instruction named in the top line.
                   The output of the run before it is cleared.
  F3   STOP        (or Ctrl+C) stop the reply or the command in
                   progress. While the robot waits for your
                   message, it ends the run.
  F4   Instruction choose, change, create and delete instructions
  F5   Skills      change skills, and switch them on and off
  F10  Quit        (or Ctrl+Q)
  Ctrl+L           draw the screen again

  Output: Up, Down, PgUp, PgDn and Home look back through what
  the run has shown. End returns to the newest line.

  Your message: Enter sends it. Ctrl+J or Alt+Enter starts a new
  line. quit, exit, stop or bye on its own ends a conversation.

  The boxes along the bottom choose what a run shows: Activity
  (tool lines and the cost of each call), Thinking, Tool calls
  (as JSON) and Debug (every request). Save thinking keeps the
  thinking in the saved chat.

TEXT BOXES
  Arrows, Home, End, PgUp and PgDn move the cursor. Ctrl+Left and
  Ctrl+Right move by a word, Ctrl+Home and Ctrl+End to the start
  and the end of the text. Tab leaves the box. Pasted text goes
  in as it is.

THE INSTRUCTION EDITOR
  Moving through the list on the left shows each instruction.
  Save stores the form under the name in the Name box: a new name
  makes a new instruction. Use makes the instruction the one that
  START runs. A run already going keeps the settings it began
  with.

THE SKILLS MANAGER
  Space on the list, or Cycle mode, switches a skill between off,
  ON (its text is in every run's prompt) and OD (on demand: a run
  fetches it when needed). A change takes effect from the next
  run.

INSIDE TMUX
  Ctrl+B then D leaves everything running and returns to the
  shell. The command that started the interface brings it back.

MORE THAN ONE INTERFACE
  ui.sh --session 2 starts a second interface, or brings you back
  to it. Any short name will do in place of the 2. Each one shows
  its name in the top row and remembers its own instruction.
  Ctrl+B then ) goes to the next interface, Ctrl+B then ( to the
  one before, and Ctrl+B then S shows a list of them.
"""


# ---- the two threads -------------------------------------------------------


class Bridge:
    """The queues between the thread that runs the agent and the screen's thread."""

    def __init__(self):
        self.events = queue.Queue()   # run -> screen: output, questions, the end of a run
        self.replies = queue.Queue()  # screen -> run: what the person answered
        self.jobs = queue.Queue()     # screen -> run: an instruction to run, or quit


class UiInterrupts(Interrupts):
    """Interrupts set off by a button on the screen, not by Ctrl-C at a prompt."""

    def __init__(self):
        super().__init__()
        self._worker = None  # the thread that runs the agent, once it can be signalled

    def install(self):
        super().install()
        self._worker = threading.get_ident()

    def _on_interrupt(self, signum, frame):
        # Unlike the chat, never leave at once on a third press: that would
        # skip putting the terminal back in order.
        self.interrupt.set()
        if self._depth > 0:
            raise KeyboardInterrupt

    def press(self, end_run=False):
        """STOP, on behalf of the person. Called from the screen's thread.

        Setting the flag is not enough: the agent may be waiting on the
        network or on a command, and only a real signal wakes it there.
        """
        if end_run:
            self.stop.set()
        self.interrupt.set()
        if self._worker is not None and hasattr(signal, "pthread_kill"):
            try:
                signal.pthread_kill(self._worker, signal.SIGINT)
            except (OSError, ValueError):
                pass


class UiConsole(Console):
    """The agent's console, showing in the output pane and asking in the reply box."""

    def __init__(self, bridge, interrupts, **flags):
        super().__init__(interrupts=interrupts, stdin=io.StringIO(""), stdout=io.StringIO(),
                         **flags)
        self.bridge = bridge
        self.tty = True  # a person is there: the forgiving rules of a chat apply

    def _show(self, text, dim):
        self.bridge.events.put(("out", text, dim))

    def _read_reply(self, question, preface, prompt):
        interrupts = self.interrupts
        if interrupts.stop.is_set():
            return None
        replies = self.bridge.replies
        while True:  # an answer left over from an earlier question is not for this one
            try:
                replies.get_nowait()
            except queue.Empty:
                break
        self.bridge.events.put(("ask",))
        try:
            with interrupts.raisable():
                while True:
                    try:
                        reply = replies.get(timeout=0.1)
                        break
                    except queue.Empty:
                        if interrupts.pending():
                            raise KeyboardInterrupt from None
        except KeyboardInterrupt:
            # STOP while the robot waits for the person: nobody is going to answer.
            interrupts.clear()
            return None
        finally:
            self.bridge.events.put(("ask_done",))
        self._line(prompt + reply)
        return reply.strip()


class Runner:
    """Runs instructions one at a time, on the thread that calls serve()."""

    def __init__(self, bridge, datadir, console, loader):
        self.bridge = bridge
        self.datadir = datadir
        self.console = console
        self.loader = loader  # get() gives the API client; is_ready() says if it has loaded
        self.learned = None   # what the API turned down, kept from one run to the next

    def serve(self):
        """Do what the screen asks until it says quit, or the process is told to stop."""
        interrupts = self.console.interrupts
        command_line.fold_in_unfinished_runs(self.datadir, self.console)
        while not interrupts.stop.is_set():
            try:
                job = self.bridge.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if job[0] == "quit":
                break
            if job[0] == "run":
                self._run(job[1], job[2])
        self.bridge.events.put(("quit",))

    def _run(self, name, options):
        console = self.console
        console.interrupts.clear()
        status, cost = "error", None
        try:
            status, cost = self._run_instruction(name, options)
        except KeyboardInterrupt:
            status = "stopped"
        except Exception as error:
            console.error(f"{type(error).__name__}: {error}")
        finally:
            console.end_line()
            self.bridge.events.put(("run_end", status, cost))

    def _run_instruction(self, name, options):
        """One run, set up the way `python -m robot.main -l NAME` sets it up."""
        console, datadir = self.console, self.datadir
        library = command_line.load_library(datadir, console)
        if name not in library:
            console.error(f"No saved instruction named '{name}'.")
            return "error", None
        try:
            settings, warnings = instructions.settings_from_entry(name, library[name])
        except instructions.InstructionError as error:
            console.error(str(error))
            return "error", None
        for warning in warnings:
            console.warn(warning)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            console.error(f"No ANTHROPIC_API_KEY found. It belongs in {command_line.ENV_FILE}.")
            return "error", None
        skills = command_line.load_skills(datadir, settings, console)
        command_line.show_banner(console, settings, skills)
        if not settings.text.strip():
            console.note("This instruction has no saved task. Type it as your message.")
            settings.text = command_line.first_message(console)
            if not settings.text:
                console.note("(nothing was run)")
                return "stopped", None
        if not self.loader.is_ready():
            console.activity("Starting up...")
        from robot.agent import Agent  # waits here while the API library is still loading

        agent = Agent(
            settings=settings, console=console, datadir=datadir, get_client=self.loader.get,
            skills=skills, learned=self.learned,
            save_thinking=bool(options.get("save_thinking")))
        status = agent.run()
        self.learned = agent.learned
        cost = agent.run_cost.total_cost if agent.run_cost.had_usage else None
        return status, cost


# ---- the output pane ---------------------------------------------------------


class _Line:
    __slots__ = ("text", "dim", "width", "rows")

    def __init__(self, text, dim):
        self.text = text
        self.dim = dim
        self.width = None  # the width `rows` was wrapped for
        self.rows = [text]


# How a line is coloured by the way it starts: the label alone, or all of it.
_LABELS = (("robot> ", "robot"), ("robot asks> ", "robot"), ("you> ", "you"))
_WHOLE_LINES = (("warning: ", "warn"), ("error: ", "error"))


class OutputBuffer:
    """What the run has shown, line by line, and which part of it is on view."""

    LIMIT = 5000   # lines kept; older ones are dropped
    _SLACK = 500

    def __init__(self):
        self.lines = []
        self.first = 0        # the number of lines[0]; a line's number never changes
        self.follow = True    # the view shows the newest lines
        self.anchor = (0, 0)  # otherwise: (line number, row within that line) at its top
        self._open = False    # the last line has not had its line break yet

    def add(self, text, dim=False):
        parts = text.split("\n")
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            if last and part == "":
                break
            if self._open:
                line = self.lines[-1]
                line.text += part
                line.width = None
            else:
                self.lines.append(_Line(part, dim))
            self._open = last
        if len(self.lines) > self.LIMIT + self._SLACK:
            drop = len(self.lines) - self.LIMIT
            del self.lines[:drop]
            self.first += drop

    def _rows(self, line, width):
        if line.width != width:
            line.rows = wrap_line(line.text, width)
            line.width = width
        return line.rows

    def _count(self, number, width):
        return len(self._rows(self.lines[number - self.first], width))

    def _last(self):
        return self.first + len(self.lines) - 1

    def _held(self, width):
        """The anchor, moved back inside the text if lines were dropped or re-wrapped."""
        number, sub = self.anchor
        if number < self.first:
            return self.first, 0
        number = min(number, self._last())
        return number, max(0, min(sub, self._count(number, width) - 1))

    def _tail_top(self, width, height):
        """Where a view of the newest rows starts."""
        needed = height
        for position in range(len(self.lines) - 1, -1, -1):
            count = len(self._rows(self.lines[position], width))
            if count >= needed:
                return self.first + position, count - needed
            needed -= count
        return self.first, 0

    def top(self, width, height):
        """(line number, row within it) of the first row on view."""
        if not self.lines:
            return self.first, 0
        return self._tail_top(width, height) if self.follow else self._held(width)

    def more_above(self, width, height) -> bool:
        return bool(self.lines) and self.top(width, height) != (self.first, 0)

    def view(self, width, height) -> list:
        """The rows on view, top to bottom, each as a list of (text, style)."""
        if height <= 0 or not self.lines:
            return []
        number, sub = self.top(width, height)
        shown = []
        position = number - self.first
        while position < len(self.lines) and len(shown) < height:
            line = self.lines[position]
            rows = self._rows(line, width)
            for index in range(sub, len(rows)):
                shown.append(self._styled(line, rows[index], index))
                if len(shown) == height:
                    break
            sub = 0
            position += 1
        return shown

    @staticmethod
    def _styled(line, row, index):
        if line.dim:
            return [(row, "dim")]
        for prefix, style in _WHOLE_LINES:
            if line.text.startswith(prefix):
                return [(row, style)]
        if index == 0:
            for prefix, style in _LABELS:
                if line.text.startswith(prefix):
                    label, rest = row[:len(prefix)], row[len(prefix):]
                    return [(label, style), (rest, "normal")] if rest else [(label, style)]
        return [(row, "normal")]

    def scroll(self, width, height, rows):
        """Move the view by `rows` rows; a negative number looks further back."""
        if not self.lines or rows == 0:
            return
        if self.follow:
            if rows > 0:
                return
            self.anchor = self._tail_top(width, height)
            self.follow = False
        number, sub = self._held(width)
        if rows < 0:
            steps = -rows
            while steps > 0:
                if sub >= steps:
                    sub -= steps
                    break
                steps -= sub + 1
                if number == self.first:
                    sub = 0
                    break
                number -= 1
                sub = self._count(number, width) - 1
        else:
            steps, last = rows, self._last()
            while steps > 0:
                count = self._count(number, width)
                if sub + steps < count:
                    sub += steps
                    break
                if number == last:
                    sub = count - 1
                    break
                steps -= count - sub
                number += 1
                sub = 0
        self.anchor = (number, sub)
        self._follow_if_at_end(width, height)

    def _follow_if_at_end(self, width, height):
        number, sub = self.anchor
        rows = -sub
        for position in range(number - self.first, len(self.lines)):
            rows += len(self._rows(self.lines[position], width))
            if rows > height:
                return
        self.follow = True

    def to_start(self, width, height):
        self.anchor = (self.first, 0)
        self.follow = False
        self._follow_if_at_end(width, height)

    def to_end(self):
        self.follow = True

    def clear(self):
        """Empty it, as for a new run: the view is back on the newest lines."""
        self.lines = []
        self.first = 0
        self.follow = True
        self.anchor = (0, 0)
        self._open = False


class OutputPane(Widget):
    """The framed, scrolling view of what the runs show."""

    focusable = True

    def __init__(self, title):
        super().__init__()
        self.title, self.hot = split_hot(title)
        self.hotkey = self.title[self.hot].lower() if self.hot >= 0 else ""
        self.buffer = OutputBuffer()

    def _inner(self):
        return max(1, self.w - 2), max(0, self.h - 2)

    def draw(self, scr, focused):
        width, height = self._inner()
        buffer = self.buffer
        note = "" if buffer.follow else "looking back: End returns to the newest"
        draw_frame(scr, self, self.title, self.hot, focused, note)
        for offset, row in enumerate(buffer.view(width, height)):
            x = self.x + 1
            for text, style in row:
                scr.put(self.y + 1 + offset, x, text, style)
                x += text_width(text)
        draw_scroll_marks(scr, self, buffer.more_above(width, height), not buffer.follow)

    def key(self, key) -> bool:
        width, height = self._inner()
        page = max(1, height - 1)
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
        if key in steps:
            self.buffer.scroll(width, height, steps[key])
        elif key == "home":
            self.buffer.to_start(width, height)
        elif key == "end":
            self.buffer.to_end()
        else:
            return False
        return True

    def wheel(self, step):
        width, height = self._inner()
        self.buffer.scroll(width, height, 3 * step)


# ---- the main window -----------------------------------------------------------


class MainWindow(Window):
    framed = False
    hint = "F1 Help  F2 Start  F3 Stop  F10 Quit"

    def __init__(self, app):
        super().__init__(app)
        self.start = self.add(Button("&START", app.start))
        self.stop = self.add(Button("STO&P", app.stop))
        self.instruction = self.add(Button("&Instruction", app.open_editor))
        self.skills = self.add(Button("S&kills", app.open_skills))
        self.help = self.add(Button("H&elp", app.open_help))
        self.quit = self.add(Button("&Quit", app.quit))
        self.output = self.add(OutputPane("&Output"))
        self.reply = self.add(TextArea("Your &message", on_submit=self._send))
        self.checks = [
            self.add(Checkbox(label, app.flags[name],
                              lambda value, name=name: app.set_flag(name, value)))
            for name, label in (("activity", "&Activity"), ("thinking", "&Thinking"),
                                ("tool_calls", "Tool &calls"), ("debug", "&Debug"),
                                ("save_thinking", "Sa&ve thinking"))]
        self.keys = {
            "f1": app.open_help, "f2": app.start, "f3": app.stop, "f4": app.open_editor,
            "f5": app.open_skills, "f10": app.quit, "ctrl+c": app.stop, "ctrl+q": app.quit,
            "ctrl+l": app.redraw,
        }
        self.stop.enabled = False
        self.reply_over()
        # Not START: Enter presses the button with the focus, and a stray
        # Enter must never be what starts a run that costs money.
        self.focus = self.instruction

    def layout(self, rows, cols):
        self.y = self.x = 0
        self.h, self.w = rows, cols
        flow((self.start, self.stop, self.instruction, self.skills), 1, 1, cols)
        right = cols - 1
        for button in (self.quit, self.help):
            right -= button.w
            button.place(1, right)
            right -= 1
        reply_height = 5
        self.output.place(2, 0, cols, max(3, rows - 3 - reply_height))
        self.reply.place(2 + self.output.h, 0, cols, reply_height)
        flow(self.checks, rows - 1, 1, cols)

    def paint(self, scr):
        scr.fill(0, 0, 1, self.w, "bar")
        scr.put(0, 1, top_line(self.app.summary, self.w - 2, self.app.session), "bar")

    def on_escape(self):
        pass  # nothing to close: Quit is how to leave

    def handle(self, event):
        # Typing while the robot waits for a message belongs in the reply box,
        # wherever the focus happens to be.
        typed = isinstance(event, Paste) or (
            isinstance(event, str) and len(event) == 1 and event != " ")
        if typed and self.reply.enabled:
            self.focus = self.reply
        super().handle(event)

    def _send(self, text):
        if not text.strip():
            self.app.status = "Type a message first."
            return
        if self.app.send_reply(text.strip()):
            self.reply.set_text("")
            self.reply_over()

    # -- what a run does to the window -----------------------------------------

    def await_reply(self):
        self.reply.enabled = True
        self.reply.note = "Enter sends, Ctrl+J starts a new line"
        self.focus = self.reply

    def reply_over(self):
        self.reply.enabled = False
        self.reply.note = "the robot is not waiting for one"
        if self.focus is self.reply:
            self.focus = self.output

    def run_started(self):
        self.start.enabled = False
        self.stop.enabled = True
        # A new run starts on an empty pane, as in MyAgent. What the run before
        # it showed is in that run's saved chat.
        self.output.buffer.clear()
        if self.focus is self.start:
            self.focus = self.output

    def run_ended(self, note):
        self.start.enabled = True
        self.stop.enabled = False
        self.reply_over()
        self.output.buffer.add(note + "\n", dim=True)
        if self.focus is self.stop:
            self.focus = self.output  # not START: see where the focus begins


# ---- the application -------------------------------------------------------------


def describe_instruction(datadir, name) -> list:
    """What the top row says about the instruction START would run: its name,
    then each thing worth knowing about it, as separate parts (see top_line)."""
    entry = instructions.load_instructions(datadir).get(name)
    if entry is None:
        return [name, "not saved yet"]
    try:
        settings, _warnings = instructions.settings_from_entry(name, entry)
    except instructions.InstructionError:
        return [name, f"set up for {entry.get('provider')}: it cannot be run here"]
    mode = models.mode_label(settings.model, settings.thinking_mode,
                             thinking_budget=settings.thinking_budget)
    kind = "conversation" if settings.conversational else "single task"
    parts = [name, f"{settings.model} ({mode})", kind]
    if settings.meta:
        parts.append("meta")
    return parts


# How far a name that is too long is cut down, its three dots included: this
# far while the word Robot still stands in front of it, this far before the
# dividers close up, and this far (one letter and the dots) at the very most.
_NAME_BESIDE_ROBOT = 16
_NAME_FLOOR = 8
_NAME_LEAST = 4


def _shortened(text, width) -> str:
    """`text` in at most `width` cells; where it is cut, three dots say so."""
    if text_width(text) <= width:
        return text
    return clip(text, max(0, width - 3)).rstrip() + "..."


def top_line(parts, width, session="") -> str:
    """The top row of the main window: Robot, then the parts, the name first.

    The name is the one part that can be any length, and what follows it (the
    model, the kind of run, meta) is what the row is there to show. So a row
    too long for the window gives up, in this order: the end of the name,
    which three dots then mark; the word Robot, which never says anything
    new, once the name beside it would get short; more of the name; the
    space around the dividers; and the name down to its first letter. What
    follows the name stays whole. Only when all of that is not enough is the
    end of the row cut off.

    A copy of the interface with a session name shows it after the word
    Robot, and keeps it when the word goes: it is what tells the copies apart.
    """
    name, details = parts[0], list(parts[1:])
    whole = [f"Robot {session}"] if session else ["Robot"]
    mark = [session] if session else []
    stages = ((whole, "  |  ", _NAME_BESIDE_ROBOT), (mark, "  |  ", _NAME_FLOOR),
              (mark, " | ", _NAME_FLOOR), (mark, " | ", _NAME_LEAST))
    row = ""
    for lead, gap, least in stages:
        room = width - text_width(gap.join(lead + [""] + details))  # what is left for the name
        if text_width(name) <= room:
            return gap.join(lead + [name] + details)
        if room >= least:
            return gap.join(lead + [_shortened(name, room)] + details)
        row = gap.join(lead + [_shortened(name, _NAME_FLOOR)] + details)
    return clip(row, width)


class App:
    """The windows on the screen, and the loop that draws them and reads keys."""

    def __init__(self, screen, bridge, datadir, console, interrupts, sdk_ready=None,
                 instruction=None, session=""):
        self.screen = screen
        self.bridge = bridge
        self.datadir = datadir
        self.console = console
        self.interrupts = interrupts
        self.sdk_ready = sdk_ready or (lambda: True)
        self.stack = []        # the open windows, the one in front last
        self.dirty = True
        self.quitting = False
        self.too_small = False
        self.running = False   # a run is in progress
        self.asking = False    # and it is waiting for the person
        self.started = 0.0
        self.status = ""       # a short message in the bottom line, until the next key
        self._seconds_shown = None
        self._ready_shown = None

        # This copy's name when several are open, "" for the first. Each copy
        # remembers its own instruction and display boxes.
        self.session = session
        self.state_path = datadir.root / state_file_name(session)
        state = load_store(self.state_path)
        self.flags = {name: bool(state.get(name, default)) for name, default in FLAGS.items()}
        self._apply_flags()
        self.instruction = instruction or state.get("instruction") or instructions.DEFAULT_NAME
        self.summary = [self.instruction]  # the parts of the top row, the name first
        self.refresh_instruction()
        self.main = MainWindow(self)

    # -- settings that outlive the program ------------------------------------------

    def _apply_flags(self):
        console, flags = self.console, self.flags
        console.activity_on = flags["activity"]
        console.show_thinking = flags["thinking"]
        console.tool_calls_on = flags["tool_calls"]
        console.debug_on = flags["debug"]

    def set_flag(self, name, value):
        self.flags[name] = bool(value)
        self._apply_flags()
        self.save_state()

    def save_state(self):
        try:
            save_store(self.state_path, {"instruction": self.instruction, **self.flags})
        except (OSError, ValueError):
            pass  # only what the window remembers; a run does not depend on it

    def refresh_instruction(self):
        """Bring the top line up to date with the library."""
        try:
            library = instructions.ensure_default(self.datadir)
        except Exception:  # an unreadable library: say what is known and carry on
            library = instructions.load_instructions(self.datadir)
        if self.instruction not in library and instructions.DEFAULT_NAME in library:
            self.instruction = instructions.DEFAULT_NAME
        self.summary = describe_instruction(self.datadir, self.instruction)
        self.dirty = True

    def set_instruction(self, name):
        self.instruction = name
        self.refresh_instruction()
        self.save_state()

    # -- the loop -----------------------------------------------------------------------

    def run(self):
        """Show the main window until Quit."""
        self.run_modal(self.main)

    def run_modal(self, window):
        """Show a window in front of the others until it closes; return its result."""
        self.stack.append(window)
        rows, cols = self.screen.size()
        window.layout(rows - 1, cols)
        self.dirty = True
        try:
            while not window.closed and not self.quitting:
                self.tick()
        finally:
            self.stack.remove(window)
            self.dirty = True
        return window.result

    def tick(self):
        """One turn of the loop: take in what the run sent, draw, read one key."""
        self.pump()
        if self.running and not self.asking:
            seconds = int(time.monotonic() - self.started)
            if seconds != self._seconds_shown:
                self.dirty = True
        ready = self.sdk_ready()
        if ready != self._ready_shown:
            self._ready_shown = ready
            self.dirty = True
        if self.dirty:
            self.draw()
        event = self.screen.read(50 if self.running else 200)
        if event is None or event == "unknown":
            return
        self.dirty = True
        if event == "resize":
            self.relayout()
            return
        if self.too_small or not self.stack:
            return
        self.status = ""
        self.stack[-1].handle(event)

    def relayout(self):
        rows, cols = self.screen.size()
        for window in self.stack:
            window.layout(rows - 1, cols)
        self.dirty = True

    def redraw(self):
        self.screen.redraw()
        self.relayout()

    def pump(self):
        """Take in everything the run has sent since the last look."""
        if self.interrupts.stop.is_set():
            self.quitting = True  # the process was told to end
        events = self.bridge.events
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                return
            self.dirty = True
            kind = event[0]
            if kind == "out":
                self.main.output.buffer.add(event[1], event[2])
            elif kind == "ask":
                self.asking = True
                self.status = ""  # a "Stopping..." has done its work by now
                self.main.await_reply()
            elif kind == "ask_done":
                self.asking = False
                self.main.reply_over()
            elif kind == "run_end":
                self._run_ended(event[1], event[2])
            elif kind == "quit":
                self.quitting = True

    def draw(self):
        scr = self.screen
        rows, cols = scr.size()
        scr.erase()
        self.too_small = rows < MIN_ROWS or cols < MIN_COLS
        if self.too_small:
            scr.put(0, 0, f"This window is too small: {cols} x {rows}.")
            scr.put(1, 0, f"Make it at least {MIN_COLS} x {MIN_ROWS}.")
            scr.set_cursor(None)
        else:
            for window in self.stack:
                window.draw(scr)
            self._draw_status(scr, rows - 1, cols)
            scr.set_cursor(self.stack[-1].cursor() if self.stack else None)
        scr.refresh()
        self.dirty = False

    def _draw_status(self, scr, y, cols):
        scr.fill(y, 0, 1, cols, "bar")
        style = "bar"
        if self.asking:
            left, style = " Waiting for your message ", "bar_notice"
        elif self.running:
            self._seconds_shown = int(time.monotonic() - self.started)
            left = f" Working {self._seconds_shown // 60}:{self._seconds_shown % 60:02d} "
        elif not self.sdk_ready():
            left = " Getting ready... "
        else:
            left = " Ready "
        scr.put(y, 0, left, style)
        # A message comes before the reminder of the keys: the reminder is
        # shown only in the room the message leaves.
        used = len(left)
        if self.status:
            shown = clip(self.status, cols - used - 2)
            scr.put(y, used + 1, shown, "bar")
            used += 1 + text_width(shown)
        hint = getattr(self.stack[-1], "hint", "") if self.stack else ""
        hint_x = cols - text_width(hint) - 1
        if hint and hint_x >= used + 2:
            scr.put(y, hint_x, hint, "bar")

    # -- small windows ---------------------------------------------------------------------

    def message(self, title, text):
        self.run_modal(MessageBox(self, title, text))

    def confirm(self, title, text) -> bool:
        """A yes or no question. Escape, like No, is a no."""
        return self.run_modal(MessageBox(self, title, text, ("&Yes", "&No"), default=1)) == 0

    def choose(self, title, text, buttons, default=0):
        """A question with buttons of its own: the number of the one pressed, or None."""
        return self.run_modal(MessageBox(self, title, text, buttons, default=default))

    def pick(self, title, options, current=None):
        return self.run_modal(PickDialog(self, title, options, current))

    def edit_text(self, title, text, hint=""):
        """A text to change: the new text, or None when it was given up."""
        return self.run_modal(TextDialog(self, title, text, hint=hint))

    def show_text(self, title, text):
        self.run_modal(TextDialog(self, title, text, read_only=True,
                                  hint="Arrows and PgUp/PgDn scroll. Esc closes."))

    def open_help(self):
        self.show_text("Help", HELP_TEXT)

    def open_editor(self):
        self.run_modal(InstructionEditor(self))
        self.refresh_instruction()

    def open_skills(self):
        self.run_modal(SkillsManager(self))

    # -- runs ----------------------------------------------------------------------------------

    def start(self):
        if self.running:
            return
        if self.instruction not in instructions.load_instructions(self.datadir):
            self.message("Start", f"There is no saved instruction named '{self.instruction}'. "
                                  "Choose one with the Instruction button.")
            return
        self.running = True
        self.started = time.monotonic()
        self.status = ""
        self.main.run_started()
        self.bridge.jobs.put(
            ("run", self.instruction, {"save_thinking": self.flags["save_thinking"]}))

    def stop(self):
        if self.running:
            self.interrupts.press()
            self.status = "Stopping..."

    def send_reply(self, text) -> bool:
        if not self.asking:
            return False
        self.asking = False
        self.started = time.monotonic()  # the clock shows the work, not the wait before it
        self.bridge.replies.put(text)
        return True

    def _run_ended(self, status, cost):
        self.running = False
        self.asking = False
        spent = f", ${cost:.4f}" if cost is not None else ""
        self.main.run_ended(f"--- run ended: {status}{spent} ---")
        self.status = f"Run ended: {status}{spent}"

    def quit(self):
        if self.running:
            if not self.confirm("Quit", "A run is in progress. Stop it and quit?"):
                return
            if self.running:
                # Give the run time to wind down: its cost is logged and its
                # chat saved before the window goes.
                self.interrupts.press(end_run=True)
                self.status = "Stopping the run..."
                deadline = time.monotonic() + 15
                while self.running and time.monotonic() < deadline:
                    self.pump()
                    self.draw()
                    time.sleep(0.05)
        self.save_state()
        self.quitting = True


# ---- starting up -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m robot.tui",
        description="The robot's agent in windows drawn in the terminal: run saved "
                    "instructions, and edit instructions and skills.")
    parser.add_argument("-l", "--load", metavar="NAME",
                        help="start with this saved instruction chosen")
    # No default of "": argparse would put a default that is a string through
    # session_name as well, which refuses an empty name.
    parser.add_argument("--session", metavar="NAME", type=session_name,
                        help="a name for this copy of the interface when more than one is "
                             "open, for example 2: it is shown in the top row, and the copy "
                             "remembers its own instruction and display boxes (1 is the "
                             "first copy, the one started without this option)")
    return parser


def _file_size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


@contextlib.contextmanager
def _streams_to_log(path):
    """Send stray output to a file while the windows are up.

    Anything written straight to the terminal would land in the middle of the
    windows. Python's own stdout and stderr go to the file, and so does what
    libraries write to the error stream underneath Python. curses keeps the
    terminal: it holds its own way to it.
    """
    log = None
    saved_fd = None
    streams = sys.stdout, sys.stderr
    try:
        try:
            oversized = os.path.getsize(path) > _ERROR_LOG_LIMIT
        except OSError:
            oversized = False
        log = open(path, "w" if oversized else "a", encoding="utf-8", errors="replace",
                   buffering=1)
        saved_fd = os.dup(2)
        os.dup2(log.fileno(), 2)
        sys.stdout = sys.stderr = log
    except OSError:
        pass
    try:
        yield
    finally:
        sys.stdout, sys.stderr = streams
        if saved_fd is not None:
            os.dup2(saved_fd, 2)
            os.close(saved_fd)
        if log is not None:
            log.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("This interface needs a terminal. Over SSH, ask for one with -t:\n"
              '  ssh -t pi "bash ~/robot/scripts/ui.sh"', file=sys.stderr)
        return command_line.EXIT_CANNOT_START
    load_dotenv(command_line.ENV_FILE)
    datadir = DataDir()
    try:
        datadir.ensure()
    except OSError as error:
        print(f"Cannot use the data folder {datadir.root}: {error}", file=sys.stderr)
        return command_line.EXIT_CANNOT_START

    # Before the screen starts: curses leaves alone the signals that already
    # have a handler, and these must stay ours.
    interrupts = UiInterrupts()
    interrupts.install()
    if hasattr(signal, "SIGWINCH"):
        # Python's line-editing module, which the chat uses, takes the signal
        # for a change of window size when it is imported. curses only puts
        # its own handler in when nobody has one, so give the signal back.
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
    bridge = Bridge()
    console = UiConsole(bridge, interrupts)
    crashes = []
    log_path = datadir.root / ERROR_LOG

    def screen_thread(loader):
        screen = None
        try:
            # Signals that end or interrupt a run must arrive on the thread
            # that runs the agent, where they wake it from whatever it is
            # waiting on. A signal sent to the process goes to any thread
            # that accepts it, so this one does not.
            if hasattr(signal, "pthread_sigmask"):
                signal.pthread_sigmask(signal.SIG_BLOCK, _RUN_SIGNALS)
            from robot.tui.screen import CursesScreen
            screen = CursesScreen()
            App(screen, bridge, datadir, console, interrupts, sdk_ready=loader.is_ready,
                instruction=args.load, session=args.session or "").run()
        except BaseException:
            crashes.append(traceback.format_exc())
        finally:
            if screen is not None:
                screen.close()
            # Whatever is still running ends with the screen.
            interrupts.press(end_run=True)
            bridge.jobs.put(("quit",))

    size_before = _file_size(log_path)
    with _streams_to_log(log_path):
        # From here on nothing but curses may write to the terminal. The slow
        # import of the API library starts now, in the background.
        loader = command_line.ClientLoader()
        runner = Runner(bridge, datadir, console, loader)
        thread = threading.Thread(target=screen_thread, args=(loader,), name="screen",
                                  daemon=True)
        thread.start()
        try:
            runner.serve()
        finally:
            bridge.events.put(("quit",))
            thread.join()
    if crashes:
        print(crashes[0], file=sys.stderr)
        return command_line.EXIT_RUN_ERROR
    if _file_size(log_path) > size_before:
        print(f"Something was printed while the windows were up. It is in {log_path}",
              file=sys.stderr)
    return command_line.EXIT_OK
