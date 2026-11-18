"""The launcher scripts: which tmux, which session and which program they ask for.

tmux is replaced by a stand-in that only writes down how it was called, so
nothing is started and no real session is touched. The scripts are bash and
run on the Pi, so these tests are skipped on Windows.
"""

import os
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Stands in for tmux. It notes each call, one argument to a line, and answers
# "has-session" with the exit code the test set: 1 says there is no such session.
FAKE_TMUX = r"""#!/bin/sh
echo CALL >> "$FAKE_TMUX_LOG"
for arg in "$@"; do printf '%s\n' "$arg" >> "$FAKE_TMUX_LOG"; done
for arg in "$@"; do
  if [ "$arg" = has-session ]; then exit "$FAKE_TMUX_HAS"; fi
done
exit 0
"""
# chat.sh pauses after saying that arguments are ignored. Tests need not wait.
FAKE_SLEEP = "#!/bin/sh\nexit 0\n"


@unittest.skipIf(os.name == "nt", "the launchers are bash scripts that run on the Pi")
class LauncherCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bin = Path(self._tmp.name) / "bin"
        self.bin.mkdir()
        for name, text in (("tmux", FAKE_TMUX), ("sleep", FAKE_SLEEP)):
            path = self.bin / name
            path.write_text(text, encoding="ascii")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.log = Path(self._tmp.name) / "tmux-calls"

    def launch(self, script, *args, running=False, **variables):
        """Run a launcher. Returns (exit code, what it printed, its calls of tmux).

        `running` says whether tmux should claim the session exists already.
        """
        env = {key: value for key, value in os.environ.items() if not key.startswith("ROBOT_")}
        env.update(PATH=f"{self.bin}{os.pathsep}{env['PATH']}", FAKE_TMUX_LOG=str(self.log),
                   FAKE_TMUX_HAS="0" if running else "1")
        env.update(variables)
        if self.log.exists():
            self.log.unlink()
        done = subprocess.run(
            ["bash", str(REPO / "scripts" / script), *args], env=env, capture_output=True,
            text=True, timeout=120, stdin=subprocess.DEVNULL)
        calls = []
        if self.log.exists():
            for line in self.log.read_text(encoding="utf-8").splitlines():
                if line == "CALL":
                    calls.append([])
                else:
                    calls[-1].append(line)
        return done.returncode, done.stdout + done.stderr, calls

    def started(self, calls):
        """What the last call of tmux starts.

        Returns (socket, session, the arguments the program gets, whatever
        follows the session's command in that call).
        """
        call = calls[-1]
        self.assertEqual(call[0], "-L", call)
        self.assertIn("new-session", call)
        at = call.index("-s")
        words = shlex.split(call[at + 2])
        self.assertEqual(words[0], "bash")
        self.assertTrue(words[1].endswith("scripts/chat.sh"), words)
        self.assertEqual(words[2], "--inside-tmux")
        return call[1], call[at + 1], words[3:], call[at + 3:]


class TheChat(LauncherCase):
    def test_it_starts_the_chat_in_its_own_tmux(self):
        code, _said, calls = self.launch("chat.sh", "--model", "claude-haiku-5-5")
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["-L", "robot", "has-session", "-t", "=robot"])
        socket, session, program, after = self.started(calls)
        self.assertEqual((socket, session), ("robot", "robot"))
        self.assertEqual(program, ["robot.main", "--model", "claude-haiku-5-5"])
        self.assertEqual(after, [])              # the wait after Escape stays as tmux.conf has it

    def test_arguments_with_spaces_arrive_whole(self):
        _code, _said, calls = self.launch("chat.sh", "-l", "Night watch, part 2")
        self.assertEqual(self.started(calls)[2], ["robot.main", "-l", "Night watch, part 2"])

    def test_a_second_start_joins_the_chat_that_is_running(self):
        code, said, calls = self.launch("chat.sh", running=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ["-L", "robot", "attach-session", "-t", "=robot"])
        self.assertNotIn("ignored", said)

    def test_arguments_to_a_chat_that_is_running_are_said_to_be_ignored(self):
        _code, said, calls = self.launch("chat.sh", "-l", "Name", running=True)
        self.assertIn("the arguments are ignored", said)
        self.assertEqual(calls[-1], ["-L", "robot", "attach-session", "-t", "=robot"])

    def test_a_start_without_a_terminal_does_not_join(self):
        code, said, calls = self.launch("chat.sh", running=True, ROBOT_TMUX_DETACHED="1")
        self.assertEqual(code, 0)
        self.assertIn("already running", said)
        self.assertEqual(len(calls), 1)          # it asked whether one runs, and left it at that
        _code, _said, calls = self.launch("chat.sh", ROBOT_TMUX_DETACHED="1")
        self.assertIn("-d", calls[-1])


class TheInterface(LauncherCase):
    def test_it_starts_the_interface_in_a_tmux_of_its_own(self):
        code, _said, calls = self.launch("ui.sh")
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["-L", "robot-ui", "has-session", "-t", "=robot-ui"])
        socket, session, program, after = self.started(calls)
        self.assertEqual((socket, session), ("robot-ui", "robot-ui"))
        self.assertEqual(program, ["robot.tui"])
        # Its tmux holds an Escape back for 20 ms, not for the chat's half second.
        self.assertEqual(after, [";", "set-option", "-sg", "escape-time", "20"])

    def test_other_arguments_go_to_the_program(self):
        _code, _said, calls = self.launch("ui.sh", "-l", "Zero state chat")
        self.assertEqual(self.started(calls)[2], ["robot.tui", "-l", "Zero state chat"])

    def test_a_second_start_joins_the_interface_that_is_running(self):
        _code, said, calls = self.launch("ui.sh", running=True)
        self.assertEqual(calls[-1], ["-L", "robot-ui", "attach-session", "-t", "=robot-ui"])
        self.assertNotIn("ignored", said)

    def test_a_check_can_name_a_tmux_of_its_own(self):
        _code, _said, calls = self.launch("ui.sh", ROBOT_SOCKET="zz-check")
        self.assertEqual(self.started(calls)[:2], ("zz-check", "robot-ui"))


class Sessions(LauncherCase):
    def test_a_session_is_a_second_interface_in_the_same_tmux(self):
        code, _said, calls = self.launch("ui.sh", "--session", "2")
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["-L", "robot-ui", "has-session", "-t", "=robot-ui-2"])
        socket, session, program, after = self.started(calls)
        self.assertEqual((socket, session), ("robot-ui", "robot-ui-2"))
        self.assertEqual(program, ["robot.tui", "--session", "2"])   # the program is told its name
        self.assertEqual(after, [";", "set-option", "-sg", "escape-time", "20"])

    def test_the_option_can_stand_anywhere_and_be_written_with_an_equals_sign(self):
        _code, _said, calls = self.launch("ui.sh", "-l", "My name", "--session=garden")
        _socket, session, program, _after = self.started(calls)
        self.assertEqual(session, "robot-ui-garden")
        self.assertEqual(program, ["robot.tui", "--session", "garden", "-l", "My name"])

    def test_session_1_is_the_first_interface(self):
        _code, _said, calls = self.launch("ui.sh", "--session", "1")
        _socket, session, program, _after = self.started(calls)
        self.assertEqual((session, program), ("robot-ui", ["robot.tui"]))

    def test_the_same_command_brings_you_back_to_a_session(self):
        code, said, calls = self.launch("ui.sh", "--session", "2", running=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ["-L", "robot-ui", "attach-session", "-t", "=robot-ui-2"])
        # --session is the launcher's own word, not an argument that goes unused.
        self.assertNotIn("ignored", said)

    def test_only_what_you_typed_for_the_program_is_said_to_be_ignored(self):
        _code, said, _calls = self.launch("ui.sh", "--session", "2", "-l", "Name", running=True)
        self.assertIn("the arguments are ignored", said)

    def test_a_name_that_will_not_do_is_refused_before_anything_starts(self):
        for bad in ("two words", "a/b", "x" * 13, "semi;colon", "..", "$HOME"):
            with self.subTest(name=bad):
                code, said, calls = self.launch("ui.sh", "--session", bad)
                self.assertEqual(code, 2)
                self.assertIn("a session name is 1 to 12 letters, digits, - or _", said)
                self.assertEqual(calls, [])

    def test_a_missing_or_empty_name_is_refused(self):
        code, said, calls = self.launch("ui.sh", "--session")
        self.assertEqual((code, calls), (2, []))
        self.assertIn("--session needs a name or a number", said)
        code, said, calls = self.launch("ui.sh", "--session=")
        self.assertEqual((code, calls), (2, []))
        self.assertIn("a session name is", said)

    def test_names_of_letters_digits_dashes_and_underscores_are_taken(self):
        for good in ("3", "garden", "Night_2", "a-b", "x" * 12):
            with self.subTest(name=good):
                _code, _said, calls = self.launch("ui.sh", "--session", good)
                self.assertEqual(self.started(calls)[1], f"robot-ui-{good}")


@unittest.skipUnless((REPO / ".venv" / "bin" / "python").exists(),
                     "needs the checkout's own Python, as on the Pi")
class InsideTmux(LauncherCase):
    """What tmux runs as the session's command: the program, then a wait for Enter."""

    def test_the_program_gets_the_arguments(self):
        code, said, _calls = self.launch("chat.sh", "--inside-tmux", "robot.tui", "--help")
        self.assertEqual(code, 0)
        self.assertIn("--session NAME", said)

    def test_the_program_knows_the_same_names_as_the_launcher(self):
        code, said, _calls = self.launch("chat.sh", "--inside-tmux", "robot.tui",
                                         "--session", "not a name")
        self.assertEqual(code, 0)                # the launcher itself ends well either way
        self.assertIn("a session name is 1 to 12 letters, digits", said)


if __name__ == "__main__":
    unittest.main()
