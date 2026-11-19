"""The script that puts the Pi back on the Wi-Fi, against a stand-in for nmcli.

The stand-in answers from small files the test writes (the device's state at
each look, the saved networks, what is in range) and notes how it was called.
No network is touched. The script is bash and runs on the Pi, so these tests
are skipped on Windows.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# "device status" answers with the next line of the file `states` (the last
# line again once they run out). "connection up" succeeds or fails as the file
# `up` says, and a success makes every later state "connected".
FAKE_NMCLI = r"""#!/bin/bash
echo "$*" >> "$FAKE/calls"
case "$*" in
  *"device status"*)
    state="$(head -n 1 "$FAKE/states")"
    if [ "$(wc -l < "$FAKE/states")" -gt 1 ]; then sed -i 1d "$FAKE/states"; fi
    echo "lo:connected (externally)"
    [ "$state" = gone ] || echo "wlan0:$state"
    ;;
  *"connection show")
    cat "$FAKE/saved"
    ;;
  *"802-11-wireless.ssid connection show "*)
    all="$*"
    name="${all##*connection show }"
    sed -n "s/^$name=//p" "$FAKE/ssids"
    ;;
  *"device wifi list"*)
    cat "$FAKE/in_range"
    ;;
  *"connection up "*)
    if [ "$(cat "$FAKE/up")" = ok ]; then
      echo connected > "$FAKE/states"
      echo "Connection successfully activated"
      exit 0
    fi
    echo "Error: Connection activation failed: Secrets were required, but not provided" >&2
    exit 4
    ;;
esac
exit 0
"""
FAKE_SYSTEMCTL = '#!/bin/bash\necho "systemctl $*" >> "$FAKE/calls"\nexit 0\n'

SAVED = """\
0:yes:802-11-wireless:Home
10:yes:802-11-wireless:Phone
5:no:802-11-wireless:Cafe
0:yes:802-3-ethernet:Wired
0:no:loopback:lo
"""
SSIDS = "Home=HomeNet\nPhone=My Phone\nCafe=CafeNet\n"


@unittest.skipIf(os.name == "nt", "a bash script that runs on the Pi")
class Reconnecting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake = Path(self._tmp.name)
        self.bin = self.fake / "bin"
        self.bin.mkdir()
        for name, text in (("nmcli", FAKE_NMCLI), ("systemctl", FAKE_SYSTEMCTL)):
            path = self.bin / name
            path.write_text(text, encoding="ascii")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        (self.fake / "saved").write_text(SAVED, encoding="ascii")
        (self.fake / "ssids").write_text(SSIDS, encoding="ascii")
        self.log = self.fake / "log"

    def watch(self, states, in_range=(), up="ok", looks=None, **variables):
        """Run the script for one look per state. Returns (its log, the calls)."""
        (self.fake / "states").write_text("\n".join(states) + "\n", encoding="ascii")
        (self.fake / "in_range").write_text("".join(name + "\n" for name in in_range),
                                            encoding="ascii")
        (self.fake / "up").write_text(up, encoding="ascii")
        env = {key: value for key, value in os.environ.items() if not key.startswith("ROBOT_")}
        env.update(PATH=f"{self.bin}{os.pathsep}{env['PATH']}", FAKE=str(self.fake),
                   ROBOT_WIFI_LOG=str(self.log), ROBOT_WIFI_INTERVAL="0",
                   ROBOT_WIFI_TICKS=str(looks or len(states)))
        env.update(variables)
        done = subprocess.run(["bash", str(REPO / "scripts" / "wifi-reconnect.sh")], env=env,
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        calls = (self.fake / "calls").read_text(encoding="utf-8").splitlines()
        return self.log.read_text(encoding="utf-8"), calls

    @staticmethod
    def joins(calls):
        return [call for call in calls if "connection up" in call]

    def test_a_connected_pi_is_left_alone(self):
        log, calls = self.watch(["connected"] * 4, in_range=["My Phone"])
        self.assertEqual(self.joins(calls), [])
        self.assertEqual(len(log.splitlines()), 1)           # only "watching wlan0"
        self.assertFalse([call for call in calls if "wifi list" in call])  # no scanning either

    def test_network_manager_gets_the_first_go(self):
        log, calls = self.watch(["disconnected", "connected"], in_range=["My Phone"])
        self.assertEqual(self.joins(calls), [])
        self.assertIn("wlan0 is off the Wi-Fi (disconnected)", log)
        self.assertIn("wlan0 is connected again", log)

    def test_a_saved_network_in_range_is_joined_at_the_second_look(self):
        log, calls = self.watch(["disconnected"] * 3, in_range=["Other", "My Phone"])
        self.assertEqual(self.joins(calls), ["--wait 60 connection up Phone ifname wlan0"])
        self.assertIn("'Phone' is in range and wlan0 is not on it: connecting", log)
        self.assertIn("connected to 'Phone'", log)

    def test_the_highest_priority_in_range_is_the_one_joined(self):
        _log, calls = self.watch(["disconnected"] * 2, in_range=["HomeNet", "My Phone"])
        self.assertEqual(self.joins(calls), ["--wait 60 connection up Phone ifname wlan0"])
        os.remove(self.fake / "calls")
        _log, calls = self.watch(["disconnected"] * 2, in_range=["HomeNet"])
        self.assertEqual(self.joins(calls), ["--wait 60 connection up Home ifname wlan0"])

    def test_a_network_not_set_to_connect_by_itself_is_never_joined(self):
        log, calls = self.watch(["disconnected"] * 3, in_range=["CafeNet", "Stranger"])
        self.assertEqual(self.joins(calls), [])
        self.assertEqual(log.count("no saved network is in range: waiting for one"), 1)

    def test_nothing_in_range_is_said_once_and_then_waited_out(self):
        log, calls = self.watch(["disconnected"] * 6)
        self.assertEqual(self.joins(calls), [])
        self.assertEqual(log.count("waiting for one"), 1)
        self.assertEqual(len(log.splitlines()), 3)

    def test_a_join_under_way_is_not_disturbed(self):
        _log, calls = self.watch(["disconnected", "connecting (getting IP configuration)",
                                  "connecting (configuring)", "connected"],
                                 in_range=["My Phone"])
        self.assertEqual(self.joins(calls), [])

    def test_a_device_that_is_not_there_is_waited_for(self):
        log, calls = self.watch(["gone", "gone", "unavailable"])
        self.assertIn("wlan0 is off the Wi-Fi (no answer from NetworkManager)", log)
        self.assertEqual(self.joins(calls), [])

    def test_joins_that_keep_failing_restart_network_manager_once(self):
        log, calls = self.watch(["disconnected"], in_range=["My Phone"], up="fail", looks=9,
                                ROBOT_WIFI_RESTART_AFTER="3")
        self.assertEqual(len(self.joins(calls)), 8)
        self.assertIn("that failed (1 in a row): Error: Connection activation failed", log)
        self.assertEqual(calls.count("systemctl restart NetworkManager"), 1)   # once an hour
        self.assertEqual(log.count("restarting NetworkManager"), 1)

    def test_a_join_that_works_after_failures_starts_the_count_again(self):
        self.watch(["disconnected"], in_range=["My Phone"], up="fail", looks=3,
                   ROBOT_WIFI_RESTART_AFTER="3")
        log, calls = self.watch(["disconnected"] * 2, in_range=["My Phone"],
                                ROBOT_WIFI_RESTART_AFTER="3")
        self.assertIn("connected to 'Phone'", log)
        self.assertNotIn("systemctl restart NetworkManager", calls)

    def test_a_long_log_loses_its_older_half(self):
        self.log.write_text("old line\n" * 30000, encoding="ascii")
        log, _calls = self.watch(["connected"])
        self.assertLess(len(log), 110000)
        self.assertTrue(log.endswith("watching wlan0\n"))


@unittest.skipIf(os.name == "nt", "a bash script that runs on the Pi")
class TheServiceDeployInstalls(unittest.TestCase):
    """deploy.sh's install_wifi_service, with sudo and systemctl stood in for."""

    def run_it(self, existing=None):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bin_dir = folder / "bin"
            bin_dir.mkdir()
            fakes = {"sudo": '#!/bin/bash\n[ "$1" = -n ] && shift\nexec "$@"\n',
                     "systemctl": '#!/bin/bash\necho "$*" >> "$CALLS"\n',
                     "nmcli": "#!/bin/bash\n"}
            for name, text in fakes.items():
                path = bin_dir / name
                path.write_text(text, encoding="ascii")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            units = folder / "units"
            units.mkdir()
            if existing is not None:
                (units / "robot-wifi.service").write_text(existing, encoding="ascii")
            calls = folder / "calls"
            calls.touch()
            # The function alone: deploy.sh's last line, which runs the deploy, is left out.
            source = (REPO / "scripts" / "deploy.sh").read_text(encoding="utf-8")
            self.assertTrue(source.rstrip().endswith('main "$@"'))
            script = source.rstrip()[:-len('main "$@"')] + "\ninstall_wifi_service\n"
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                       ROBOT_SYSTEMD_DIR=str(units), CALLS=str(calls))
            done = subprocess.run(["bash", "-s"], input=script, env=env, cwd=str(REPO),
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            return ((units / "robot-wifi.service").read_text(encoding="ascii"),
                    calls.read_text(encoding="ascii").splitlines(), done.stdout)

    def test_the_service_runs_the_script_of_this_checkout(self):
        unit, calls, said = self.run_it()
        self.assertIn(f"ExecStart=/bin/bash {REPO}/scripts/wifi-reconnect.sh\n", unit)
        self.assertIn("Restart=always\n", unit)
        self.assertIn("WantedBy=multi-user.target\n", unit)
        self.assertEqual(calls, ["daemon-reload", "enable --quiet robot-wifi",
                                 "restart robot-wifi"])
        self.assertIn("Setting up the robot-wifi service...", said)

    def test_a_second_deploy_only_restarts_it(self):
        unit, _calls, _said = self.run_it()
        again, calls, said = self.run_it(existing=unit)
        self.assertEqual(again, unit)
        self.assertEqual(calls, ["enable --quiet robot-wifi", "restart robot-wifi"])
        self.assertEqual(said, "")


if __name__ == "__main__":
    unittest.main()
