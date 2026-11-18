"""The windowed interface on a real terminal, through curses.

The program is started on a pseudo-terminal of its own and gets real bytes,
the way tmux or an SSH session would send them. These tests need curses and
pseudo-terminals, so they run on the Pi and are skipped on Windows. No run is
ever started here: the program is given an empty API key, with which it
refuses to send anything.
"""

import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import curses
    import fcntl
    import pty
    import termios
except ImportError:  # Windows
    curses = None

from robot import instructions
from robot.datastore import DataDir

REPO = Path(__file__).resolve().parent.parent
ESC = b"\x1b"


class Terminal:
    """`python -m robot.tui` running on a pseudo-terminal."""

    def __init__(self, data_dir, rows=24, cols=80, term="xterm-256color", args=()):
        self.output = b""
        self._searched = 0
        self.term = term
        pid, fd = pty.fork()
        if pid == 0:  # the child: becomes the program
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                env = dict(os.environ, TERM=term, ROBOT_DATA_DIR=str(data_dir),
                           ANTHROPIC_API_KEY="", LANG="C.UTF-8", LC_ALL="C.UTF-8")
                os.chdir(REPO)
                os.execve(sys.executable, [sys.executable, "-m", "robot.tui", *args], env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.status = None

    def _read(self, seconds) -> bool:
        """Take in what the program has written. False when it has gone."""
        ready, _, _ = select.select([self.fd], [], [], seconds)
        if not ready:
            return True
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            return False
        self.output += data
        return bool(data)

    def expect(self, marker, seconds=90):
        """Wait until the program has written `marker` since the last expect."""
        deadline = time.monotonic() + seconds
        while True:
            at = self.output.find(marker, self._searched)
            if at >= 0:
                self._searched = at + len(marker)
                return
            if time.monotonic() > deadline or not self._read(0.2):
                tail = self.output[self._searched:][-1500:]
                raise AssertionError(f"{marker!r} did not appear. Written since: {tail!r}")

    def send(self, *pieces, pause=0.3):
        """Type. The pause after each piece keeps separate keys separate."""
        for piece in pieces:
            os.write(self.fd, piece if isinstance(piece, bytes) else piece.encode())
            until = time.monotonic() + pause
            while time.monotonic() < until and self._read(until - time.monotonic()):
                pass

    def key(self, capability) -> bytes:
        """What this kind of terminal sends for a key, by its terminfo name."""
        sequence = subprocess.run(["tput", "-T", self.term, capability],
                                  capture_output=True, check=True).stdout
        assert sequence, f"{self.term} has no {capability}"
        return sequence

    def resize(self, rows, cols):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def modes(self):
        """The terminal's line settings (echo, line editing and so on)."""
        return termios.tcgetattr(self.fd)[:4]

    def wait(self, seconds=60):
        """The program's exit code, once it has ended."""
        deadline = time.monotonic() + seconds
        while self.status is None:
            self._read(0.1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)
            elif time.monotonic() > deadline:
                raise AssertionError(f"the program did not end. Last output: "
                                     f"{self.output[-800:]!r}")
        return self.status

    def close(self):
        if self.status is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass


@unittest.skipIf(curses is None, "needs curses and a pseudo-terminal (not on Windows)")
class OnATerminal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(Path(self._tmp.name) / "data")
        self.datadir.ensure()
        library = instructions.ensure_default(self.datadir)
        library["Spare"] = {"text": "Spare text.", "model": "claude-haiku-5-5"}
        instructions.save_instructions(self.datadir, library)

    def start(self, **options):
        terminal = Terminal(self.datadir.root, **options)
        self.addCleanup(terminal.close)
        return terminal

    def library(self):
        return instructions.load_instructions(self.datadir)

    def leave(self, terminal):
        """Close the window that is open, if one is, and quit."""
        terminal.send(ESC, pause=0.6)   # closes an editor; the main window has no use for it
        terminal.send(b"\x11")          # Ctrl+Q, which the main window takes as Quit
        self.assertEqual(terminal.wait(), 0)

    def test_it_starts_shows_help_and_quits_on_each_kind_of_terminal(self):
        # xterm: an SSH session from the laptop. linux: the Pi's own screen.
        # tmux-256color and screen: inside tmux.
        for term in ("xterm-256color", "linux", "tmux-256color", "screen"):
            with self.subTest(term=term):
                terminal = self.start(term=term)
                before = terminal.modes()
                terminal.expect(b"Default")             # the top line names the instruction
                terminal.expect(b"nstruction")          # and the toolbar is up
                terminal.send(terminal.key("kf1"))
                terminal.expect(b"GETTING")
                terminal.send(ESC, pause=0.6)           # Escape alone closes the help
                terminal.expect(b"nstruction")          # the main window is drawn again
                terminal.send(terminal.key("kf10"))
                self.assertEqual(terminal.wait(), 0)
                self.assertEqual(terminal.modes(), before)   # the terminal is as it was
                terminal.close()

    def test_keys_reach_the_windows_and_the_terminals_own_answers_do_not(self):
        terminal = self.start()
        terminal.expect(b"nstruction")
        terminal.send(terminal.key("kf4"))              # the Instruction Editor
        terminal.expect(b"Editor")
        terminal.send(ESC + b"n")                       # Alt+N: the Name box
        # What a terminal answers when tmux asks for its colours and its type.
        # It arrives like typing, and must not end up in the name.
        terminal.send(ESC + b"]11;rgb:0c0c/0c0c/0c0c" + ESC + b"\\",
                      ESC + b"[?61;4;6;7;14;21;22;23;24;28;32;42c",
                      ESC + b"[>0;10;1c" + ESC + b"[>0;10;1c")
        terminal.send(b" two", ESC + b"s")              # Alt+S: save under the new name
        terminal.expect(b"Saved")
        self.leave(terminal)
        self.assertEqual(sorted(self.library()), ["Default", "Default two", "Spare"])

    def test_enter_and_ctrl_j_are_told_apart(self):
        terminal = self.start()
        terminal.expect(b"nstruction")
        terminal.send(terminal.key("kf4"))
        terminal.expect(b"Editor")
        terminal.send(b"s")                             # jump to Spare in the list
        terminal.expect(b"Spare text")
        terminal.send(ESC + b"d")                       # Alt+D: Delete asks first
        terminal.expect(b"Delete the instruction")
        terminal.send(b"\r")                            # Enter presses the button in focus: No
        terminal.send(ESC + b"d")
        terminal.expect(b"Delete the instruction")
        terminal.send(b"\n")                            # Ctrl+J is not Enter: still asking
        terminal.send(b"y")                             # so this answers Yes
        terminal.expect(b"Deleted")
        self.leave(terminal)
        self.assertEqual(sorted(self.library()), ["Default"])

    def test_pasted_text_and_the_mouse(self):
        terminal = self.start()
        terminal.expect(b"nstruction")
        # A click on Help, which sits at the right of the second row.
        terminal.send(ESC + b"[<0;66;2M" + ESC + b"[<0;66;2m")
        terminal.expect(b"GETTING")
        terminal.send(ESC, pause=0.6)
        terminal.send(terminal.key("kf4"))
        terminal.expect(b"Editor")
        terminal.send(b"s", ESC + b"x")                 # Spare, then Alt+X: its text
        # Pasted text comes between two marks. Its line ends and its letters
        # are text, not Enter and not shortcuts.
        terminal.send(ESC + b"[200~Pasted:\rq" + ESC + b"[201~", ESC + b"s")
        terminal.expect(b"Saved")
        self.leave(terminal)
        self.assertEqual(self.library()["Spare"]["text"], "Pasted:\nqSpare text.")

    def test_a_change_of_size_is_followed(self):
        terminal = self.start()
        terminal.expect(b"nstruction")
        terminal.resize(10, 40)
        terminal.expect(b"too small")
        terminal.resize(30, 100)
        terminal.expect(b"nstruction")
        self.leave(terminal)

    def test_a_signal_to_end_closes_it_cleanly(self):
        for number in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=number.name):
                terminal = self.start()
                before = terminal.modes()
                terminal.expect(b"nstruction")
                os.kill(terminal.pid, number)
                self.assertEqual(terminal.wait(), 0)
                self.assertEqual(terminal.modes(), before)
                terminal.close()

    def test_a_copy_with_a_session_name_shows_it_and_keeps_its_own_settings(self):
        terminal = self.start(args=["--session", "2"])
        terminal.expect(b"Robot 2")                     # the top row says which copy this is
        terminal.expect(b"nstruction")
        terminal.send(ESC + b"t")                       # Alt+T: a display box, which is remembered
        self.leave(terminal)
        self.assertTrue((self.datadir.root / "tui_state_2.json").exists())
        self.assertFalse((self.datadir.root / "tui_state.json").exists())

    def test_ctrl_c_does_not_end_the_program(self):
        terminal = self.start()
        terminal.expect(b"nstruction")
        terminal.send(b"\x03", b"\x03", b"\x03", b"\x1a")    # Ctrl+C three times, Ctrl+Z
        terminal.send(terminal.key("kf1"))
        terminal.expect(b"GETTING")                          # still there, still working
        terminal.send(ESC, pause=0.6)
        self.leave(terminal)


if __name__ == "__main__":
    unittest.main()
