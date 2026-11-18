"""A screen that lives in memory, so the windows can be driven by a script.

The script is a list of what `read` hands over, in order:
    a key name or a character, a Mouse or a Paste     passed on as it is
    typed("some text")                                one character at a time
    Check(function)       called with the screen once the keys before it have
                          been drawn; it asserts something about what shows
    Until(function)       nothing is passed on until the function is true:
                          for waiting on the thread that runs the agent
When the script runs out, `read` raises ScriptDone, which ends the loop.
"""

import collections
import tempfile
import threading
import time
import unittest
from pathlib import Path

from robot import instructions
from robot.datastore import DataDir
from robot.tui.app import App, Bridge, Runner, UiConsole, UiInterrupts
from robot.tui.screen import Screen
from robot.tui.text import cell_width


class ScriptDone(Exception):
    """The script has no more keys."""


class Check:
    def __init__(self, function):
        self.function = function


class Until:
    def __init__(self, function, what="", seconds=30.0):
        self.function = function
        self.seconds = seconds
        self.what = what
        self.deadline = None


def typed(text) -> list:
    return list(text)


class FakeScreen(Screen):
    unicode = False

    def __init__(self, rows=24, cols=80, script=()):
        self.rows, self.cols = rows, cols
        self.script = collections.deque()
        self.feed(*script)
        self.cursor = None
        self.frames = 0
        self.erase()

    def feed(self, *items):
        for item in items:
            if isinstance(item, list):
                self.script.extend(item)
            else:
                self.script.append(item)

    # -- Screen ----------------------------------------------------------------

    def size(self):
        return self.rows, self.cols

    def erase(self):
        self.grid = [[" "] * self.cols for _ in range(self.rows)]
        self.styles = [["normal"] * self.cols for _ in range(self.rows)]

    def _cells(self, y, x, text, style):
        for char in text:
            width = cell_width(char)
            if width == 0:
                continue
            assert 0 <= y < self.rows and 0 <= x and x + width <= self.cols, (y, x, text)
            self.grid[y][x] = char
            self.styles[y][x] = style
            if width == 2:
                self.grid[y][x + 1] = ""
                self.styles[y][x + 1] = style
            x += width

    def set_cursor(self, position):
        self.cursor = position

    def refresh(self):
        self.frames += 1

    def read(self, timeout_ms):
        while True:
            if not self.script:
                raise ScriptDone
            item = self.script[0]
            if isinstance(item, Check):
                self.script.popleft()
                item.function(self)
                continue
            if isinstance(item, Until):
                if item.function():
                    self.script.popleft()
                    return None  # one more turn of the loop, so the result is drawn
                if item.deadline is None:
                    item.deadline = time.monotonic() + item.seconds
                elif time.monotonic() > item.deadline:
                    raise AssertionError(
                        f"waited {item.seconds}s in vain for {item.what or 'a condition'}:\n"
                        + self.text())
                time.sleep(0.005)
                return None
            return self.script.popleft()

    # -- for the tests -----------------------------------------------------------

    def line(self, y) -> str:
        return "".join(self.grid[y]).rstrip()

    def text(self) -> str:
        return "\n".join(self.line(y) for y in range(self.rows))

    def find(self, text):
        """(y, x) of the first place `text` shows, or None."""
        for y in range(self.rows):
            x = "".join(self.grid[y]).find(text)
            if x >= 0:
                return y, x
        return None

    def style_at(self, text) -> str:
        """The style of the first character of `text` where it shows."""
        y, x = self.find(text)
        return self.styles[y][x]


class StubLoader:
    """Stands in for the loader of the API client."""

    def __init__(self, client=None):
        self.client = client

    def is_ready(self):
        return True

    def get(self):
        return self.client


class AppCase(unittest.TestCase):
    """A data folder of its own, and the means to run the interface in it."""

    rows, cols = 24, 80

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(Path(self._tmp.name) / "data")
        self.datadir.ensure()
        self.bridge = Bridge()
        self.interrupts = UiInterrupts()
        self.console = UiConsole(self.bridge, self.interrupts)
        self.screen = FakeScreen(self.rows, self.cols)
        self.app = None

    def library(self, **entries):
        """Save instructions, beside Default. Returns the whole library."""
        library = instructions.ensure_default(self.datadir)
        library.update(entries)
        instructions.save_instructions(self.datadir, library)
        return library

    def saved(self, name):
        return instructions.load_instructions(self.datadir).get(name)

    def make_app(self, **options):
        self.app = App(self.screen, self.bridge, self.datadir, self.console, self.interrupts,
                       **options)
        return self.app

    def drive(self, *script):
        """Run the interface through a script. Returns the screen."""
        if self.app is None:
            self.make_app()
        self.screen.feed(*script)
        try:
            self.app.run()
        except ScriptDone:
            pass
        return self.screen

    def show(self, window, *script):
        """Show one window in front of the main one and run a script in it."""
        if self.app is None:
            self.make_app()
        self.screen.feed(*script)
        try:
            self.app.run_modal(window)
        except ScriptDone:
            pass
        return window

    def start_runner(self, client=None):
        """Run the agent's side on a thread of its own, as the real program
        does on the main thread. It is stopped when the test ends."""
        runner = Runner(self.bridge, self.datadir, self.console, StubLoader(client))
        thread = threading.Thread(target=runner.serve, name="runner", daemon=True)
        thread.start()

        def stop():
            # Ends a run that is still going, a question that is still open
            # included, and then the loop that waits for the next one.
            self.interrupts.press(end_run=True)
            self.bridge.jobs.put(("quit",))
            thread.join(20)
            self.assertFalse(thread.is_alive(), "the runner did not stop")

        self.addCleanup(stop)
        return runner
