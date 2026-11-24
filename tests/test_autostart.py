"""Starting by itself when the Pi starts: the interface's --start, the script
with its switch, and the service deploy.sh sets up. Nothing is started for
real: openvt, systemctl and the clock are stand-ins."""

import getpass
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from robot.tui import app as tui_app
from tests.fakes import reply, text_block
from tests.test_launchers import LauncherCase
from tests.test_tui_app import MainCase, said

REPO = Path(__file__).resolve().parent.parent


class TheInterfaceStartsItsRun(MainCase):
    def test_the_option_is_off_unless_given(self):
        parser = tui_app.build_parser()
        self.assertTrue(parser.parse_args(["--start"]).start)
        self.assertFalse(parser.parse_args([]).start)

    def test_with_it_the_run_begins_without_a_key_being_pressed(self):
        client = self.fake_client([reply(text_block("Done."))])
        self.make_app(instruction="Task", autostart=True)
        self.drive(self.ended(), self.shows("Done.", "--- run ended: completed"))
        self.assertEqual(said(client.requests[0]["messages"][0]), "Say that it is done.")
        self.assertEqual(len(client.requests), 1)

    def test_it_starts_once_and_not_again_when_the_run_has_ended(self):
        client = self.fake_client([reply(text_block("Done.")), reply(text_block("Again."))])
        self.make_app(instruction="Task", autostart=True)
        self.drive(self.ended(), "tab", "tab", "tab", self.shows("--- run ended: completed"))
        self.assertEqual(len(client.requests), 1)

    def test_without_it_nothing_starts_by_itself(self):
        client = self.fake_client([reply(text_block("Done."))])
        self.make_app(instruction="Task")
        self.drive("tab", "tab", self.shows("Ready"))
        self.assertEqual(client.requests, [])
        self.assertFalse(self.app.running)

    def fake_client(self, script):
        from tests.fakes import FakeClient
        client = FakeClient(script)
        self.start_runner(client)
        return client


class TheLauncherPassesItOn(LauncherCase):
    def test_start_reaches_the_program(self):
        _code, _said, calls = self.launch("ui.sh", "--start")
        self.assertEqual(self.started(calls)[2], ["robot.tui", "--start"])

    def test_with_a_session_name_too(self):
        _code, _said, calls = self.launch("ui.sh", "--start", "--session", "zzt")
        _socket, session, program, _after = self.started(calls)
        self.assertEqual(session, "robot-ui-zzt")
        self.assertEqual(program, ["robot.tui", "--session", "zzt", "--start"])


# Stand-ins for what the script calls. openvt writes its arguments down, one to
# a line. The clock says "yes" from the call whose number is in CLOCK_FROM on.
FAKES = {
    "openvt": '#!/bin/bash\nfor a in "$@"; do printf \'%s\\n\' "$a" >> "$CALLS"; done\n'
              'exit "${OPENVT_EXIT:-0}"\n',
    "timedatectl": '#!/bin/bash\nn=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n + 1))\n'
                   'echo $n > "$COUNT"\n[ "$n" -ge "${CLOCK_FROM:-1}" ] && echo yes || echo no\n',
    "getent": '#!/bin/bash\nif [ "$1" = hosts ]; then exit "${NET_EXIT:-0}"; fi\n'
              'exec /usr/bin/getent "$@"\n',
    "sleep": '#!/bin/bash\necho "$1" >> "$SLEPT"\n',
    "systemctl": '#!/bin/bash\necho "$*" >> "$SYSTEMCTL"\n'
                 '[ "$1" = is-enabled ] && echo "${ENABLED:-enabled}"\nexit 0\n',
    "sudo": '#!/bin/bash\n[ "$1" = -n ] && shift\nexec "$@"\n',
}


@unittest.skipIf(os.name == "nt", "a bash script that runs on the Pi")
class ScriptCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.bin = self.folder / "bin"
        self.bin.mkdir()
        for name, text in FAKES.items():
            path = self.bin / name
            path.write_text(text, encoding="ascii")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.data = self.folder / "data"
        self.log = self.folder / "autostart.log"

    def env(self, **more):
        env = {key: value for key, value in os.environ.items() if not key.startswith("ROBOT_")}
        env.update(PATH=f"{self.bin}{os.pathsep}{env['PATH']}", ROBOT_DATA_DIR=str(self.data),
                   ROBOT_AUTOSTART_LOG=str(self.log), CALLS=str(self.folder / "calls"),
                   COUNT=str(self.folder / "count"), SLEPT=str(self.folder / "slept"),
                   SYSTEMCTL=str(self.folder / "systemctl"))
        env.update(more)
        return env

    def run_it(self, word, **more):
        done = subprocess.run(["bash", str(REPO / "scripts" / "autostart.sh"), word],
                              env=self.env(**more), capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout + done.stderr

    def lines(self, name):
        path = self.folder / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class TheSwitch(ScriptCase):
    def test_it_is_off_until_switched_on(self):
        code, told = self.run_it("status")
        self.assertEqual(code, 0)
        self.assertIn("Autostart is OFF", told)

    def test_on_and_off(self):
        code, told = self.run_it("on")
        self.assertEqual(code, 0)
        self.assertIn("Autostart is ON", told)
        self.assertTrue((self.data / "autostart_on").exists())
        self.assertIn("Autostart is ON", self.run_it("status")[1])
        self.assertIn("Autostart is OFF", self.run_it("off")[1])
        self.assertFalse((self.data / "autostart_on").exists())
        self.assertEqual(self.run_it("off")[0], 0)  # off when it is off already

    def test_it_says_when_the_service_is_not_set_up(self):
        self.assertNotIn("not set up", self.run_it("status")[1])
        self.assertIn("robot-autostart service is not set up",
                      self.run_it("status", ENABLED="disabled")[1])

    def test_another_word_is_refused(self):
        code, told = self.run_it("sometimes")
        self.assertEqual(code, 2)
        self.assertIn("use on, off or status", told)
        self.assertEqual(self.lines("calls"), [])


class WhenThePiStarts(ScriptCase):
    def test_switched_off_nothing_is_started(self):
        code, told = self.run_it("boot")
        self.assertEqual(code, 0)
        self.assertIn("autostart is off: nothing started", told)
        self.assertEqual(self.lines("calls"), [])
        self.assertIn("autostart is off", self.log.read_text(encoding="utf-8"))

    def test_switched_on_the_interface_goes_on_the_screen_with_start(self):
        self.run_it("on")
        code, told = self.run_it("boot")
        self.assertEqual(code, 0, told)
        calls = self.lines("calls")
        user = getpass.getuser()
        self.assertEqual(calls[:9], ["-f", "-c", "8", "-s", "--", "sudo", "-H", "-u", user])
        self.assertEqual(calls[9:11], ["env", "TERM=linux"])
        self.assertRegex(calls[11], r"^LANG=.+")
        self.assertEqual(calls[-3:], ["bash", str(REPO / "scripts" / "ui.sh"), "--start"])
        self.assertIn(f"started the interface for {user} on console 8, after waiting 0 s", told)
        self.assertEqual(self.lines("slept"), [])

    def test_the_data_folder_of_this_test_goes_along(self):
        self.run_it("on")
        self.run_it("boot")
        self.assertIn(f"ROBOT_DATA_DIR={self.data}", self.lines("calls"))

    def test_it_waits_for_the_clock_to_be_set(self):
        self.run_it("on")
        code, told = self.run_it("boot", CLOCK_FROM="4")
        self.assertEqual(code, 0)
        self.assertEqual(self.lines("slept"), ["5", "5", "5"])
        self.assertIn("after waiting 15 s", told)
        self.assertEqual(self.lines("calls")[-1], "--start")

    def test_it_waits_for_the_network_too_but_not_for_ever(self):
        self.run_it("on")
        code, told = self.run_it("boot", NET_EXIT="2", ROBOT_AUTOSTART_WAIT="20")
        self.assertEqual(code, 0)
        self.assertEqual(self.lines("slept"), ["5"] * 4)
        self.assertIn("no network or no clock after 20 s: starting all the same", told)
        self.assertEqual(self.lines("calls")[-1], "--start")

    def test_a_check_can_have_its_own_tmux_console_and_session(self):
        self.run_it("on")
        self.run_it("boot", ROBOT_SOCKET="zz-ui", ROBOT_AUTOSTART_CONSOLE="9",
                    ROBOT_AUTOSTART_ARGS="--session zzt")
        calls = self.lines("calls")
        self.assertEqual(calls[1:3], ["-c", "9"])
        self.assertIn("ROBOT_SOCKET=zz-ui", calls)
        self.assertEqual(calls[-3:], ["--start", "--session", "zzt"])

    def test_a_screen_that_cannot_be_had_is_a_failure_that_is_written_down(self):
        self.run_it("on")
        code, told = self.run_it("boot", OPENVT_EXIT="1")
        self.assertEqual(code, 1)
        self.assertIn("could not start the interface on console 8", told)
        self.assertIn("could not start", self.log.read_text(encoding="utf-8"))


@unittest.skipIf(os.name == "nt", "a bash script that runs on the Pi")
class TheServiceDeployInstalls(ScriptCase):
    """deploy.sh's install_autostart_service."""

    def install(self, existing=None):
        units = self.folder / "units"
        units.mkdir(exist_ok=True)
        if existing is not None:
            (units / "robot-autostart.service").write_text(existing, encoding="ascii")
        (self.folder / "systemctl").write_text("", encoding="ascii")
        source = (REPO / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        self.assertTrue(source.rstrip().endswith('main "$@"'))
        script = source.rstrip()[:-len('main "$@"')] + "\ninstall_autostart_service\n"
        done = subprocess.run(["bash", "-s"], input=script, cwd=str(REPO), text=True,
                              env=self.env(ROBOT_SYSTEMD_DIR=str(units)), capture_output=True,
                              timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return ((units / "robot-autostart.service").read_text(encoding="ascii"),
                self.lines("systemctl"), done.stdout)

    def test_the_service_runs_this_checkouts_script_once_at_the_start(self):
        unit, calls, told = self.install()
        self.assertIn(f"ExecStart=/bin/bash {REPO}/scripts/autostart.sh boot\n", unit)
        self.assertIn("Type=oneshot\n", unit)
        self.assertIn("After=network-online.target time-sync.target", unit)
        # Stopping the service must not take the interface with it.
        self.assertIn("KillMode=process\n", unit)
        self.assertIn("WantedBy=multi-user.target\n", unit)
        self.assertEqual(calls, ["daemon-reload", "enable --quiet robot-autostart"])
        self.assertIn("Setting up the robot-autostart service...", told)

    def test_a_deploy_never_starts_or_restarts_it(self):
        unit, _calls, _told = self.install()
        again, calls, told = self.install(existing=unit)
        self.assertEqual(again, unit)
        self.assertEqual(calls, ["enable --quiet robot-autostart"])
        self.assertEqual(told, "")

    def test_the_whole_deploy_sets_it_up_after_the_wifi_service(self):
        source = (REPO / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        self.assertLess(source.index("install_wifi_service ||"),
                        source.index("install_autostart_service ||"))


if __name__ == "__main__":
    unittest.main()
