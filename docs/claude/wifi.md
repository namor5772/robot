# Getting back on the Wi-Fi

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- The Pi's network is run by NetworkManager (`nmcli`). Its saved Wi-Fi
  networks all connect automatically; the one in everyday use has the
  highest priority. `nmcli connection show` on the Pi lists them: they are
  not named here.
- NetworkManager rejoins a saved network by itself when it sees it again. But
  it can give up: on the night of 2026-11-19 the network went away and came
  back several times, and from 23:26 the Pi stayed off it until the owner
  restarted the Pi in the morning. Why is not known: the Pi keeps no log
  across restarts. A likely cause is a join that fails at the wrong moment,
  after which NetworkManager waits for somebody to connect by hand.
- So since 2026-11-20 a service, `robot-wifi`, is that somebody
  (`scripts/wifi-reconnect.sh`, run as root by systemd, started with the Pi).
  Every 30 s it reads `wlan0`'s state. Connected or connecting: nothing, not
  even a scan. Off the Wi-Fi at one look: NetworkManager gets its own go. Off
  at the next: it scans, and when a saved network that connects automatically
  is in range (highest priority first) it runs `nmcli connection up` for it.
  Ten failures in a row restart NetworkManager, at most once an hour. Nothing
  in range is said once and waited out.
- The script names no network (the repo is public). Its log is
  `/var/log/robot-wifi.log`, events only, cut to its newer half at 200 KB.
- `deploy.sh` sets the service up (`install_wifi_service`): it writes
  `/etc/systemd/system/robot-wifi.service`, whose text is in `deploy.sh`
  because it names the checkout's folder, enables it, and restarts it on
  every deploy so that it runs the script as it is now. A failure there only
  warns. The deploy that first brings a new step to `deploy.sh` does not run
  it: bash has the old script in memory by then. Deploy twice.
- Tried for real on 2026-11-20 with a detached job (see "Running and
  testing"): `sudo nmcli device disconnect wlan0` leaves the Pi as
  NetworkManager is when it has given up. With the service stopped it stayed
  off for the 100 s that were watched; once the service was started it was
  back after 34 s. `tests/test_wifi_reconnect.py` runs the script against a
  stand-in for `nmcli` (13 tests, bash, so skipped on Windows).
- Such a check takes the Pi off the network for minutes. It must run
  detached, must put the Wi-Fi back by hand at its end whatever happened, and
  must not start while a run is in progress (`~/robot-data/runs` holds a file
  then).
- Until 2026-11-22 only the network in everyday use had ever been joined. The
  Pi also has two saved profiles for a second network (one had a wrong letter
  in the network's name until 2026-11-20), and a join tried with each that day
  failed before any password was looked at: the access point did not answer
  the Pi's request to authenticate ("Authentication ... timed out", then
  NetworkManager's "no-secrets"). It announces WPA2 with WPA3 and Wi-Fi 6.
  The cause is not known and may lie in the access point's settings. Left to
  connect automatically, both profiles were tried and failed over and over
  whenever the first network was away. So the owner had automatic connecting
  switched off for the two of them on 2026-11-20 (`nmcli connection modify
  NAME connection.autoconnect no`): neither NetworkManager nor `robot-wifi`
  tries them now, and the Pi waits for the first network. Once that second
  network can be joined, `connection.autoconnect yes` brings them back.
- That makes the opening of this section out of date in one point: not all
  saved Wi-Fi networks connect automatically any more.
- That second network was joined on 2026-11-23, on the 3 A+, and the cause
  was in the Pi's profile, not in the access point: the profile had
  protected management frames switched off (`802-11-wireless-security.pmf`
  was `1`, "disable"). An access point that announces WPA2 with WPA3 wants
  them at least offered. With the setting at its default (`sudo nmcli
  connection modify NAME 802-11-wireless-security.pmf 0`) the same profile,
  with the password it already held, joined at the first try, on 5 GHz.
  - What the refusal looked like in `sudo journalctl -u wpa_supplicant`:
    `CTRL-EVENT-ASSOC-REJECT ... status_code=16` a fraction of a second
    after each "Trying to associate", five times over, and a line "MBO:
    Disable MBO/OCE due to misbehaving AP not having enabled PMF".
    NetworkManager then asked for a password ("no-secrets"), which
    misleads: no password had been looked at.
  - Only one profile for that network was left by then. It connects
    automatically again, with priority 0, so the network in everyday use
    (10) still wins where both are in range. Three profiles are saved.
  - It was done with no keyboard at the Pi: the Pi and the laptop were both
    on the everyday network, and a detached job (see "Running and testing")
    tried the profile, wrote down what happened and went back to that
    network, so that its log could be read over ssh. A join that needs a
    password typed can go the same way: `ssh -t pi "sudo nmcli --ask device
    wifi connect NAME"`, where the session freezes once the Pi changes
    network.
  - PowerShell 5.1 on the laptop puts a byte-order mark in front of a
    script piped to `ssh` (`bash: line 1: ...cat: command not found`).
    There the script is fed with Git Bash's `<`.
- A network the Pi has never joined is added at its own console (keyboard
  and screen), which needs no network: `sudo nmcli device wifi list --rescan
  yes` shows what the Pi sees, and `sudo nmcli --ask device wifi connect
  "NAME"` joins one, asking for the password without showing it (`sudo
  nmtui` does the same with menus). The Zero 2 W's radio had the 2.4 GHz
  band only (`iw list` showed one band), so a network sent on 5 GHz alone
  was not in that list; the 3 A+ has both bands (see "Target device"). The
  owner did this on 2026-11-22, on the Zero 2 W, at a router the Pi had
  never seen.
- The profile made that way connects automatically, with priority 0; the first
  network has 10 and so wins where both are in range. Four profiles are
  saved now: these two, and the two that do not connect automatically. Power
  saving is off on the new network as well, the setting being for every
  network. `robot-wifi` did as it should that morning: with no network it
  knew in range it said so once and waited, and it noted the join. The
  robot's own monitor reads the gateway from the routing table, so it
  follows the Pi to another network.
- The Pi has no clock of its own. Started with no network, it goes on from
  about where its clock stood when it was last shut down, until a network
  gives it the time: on 2026-11-22 it started at 06:27 thinking it was 20:09
  on the 20th, and was put right at 06:48, on joining. What `robot-wifi`,
  the monitor and the journal wrote in between carries the old date. `sudo
  journalctl -b | grep timesyncd` shows when the clock was set, and `uptime
  -s` when the Pi really started.
- The Wi-Fi monitor the robot made (`~/wifimon`, see "State on 2026-11-18")
  is separate and only writes down changes: it pings the gateway, so its log
  also shows short losses during which the Pi never left the network.
- Wi-Fi power saving is off since 2026-11-20, at the owner's request. It is a
  setting of the Pi, not of the repo:
  `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` holds `[connection]`
  and `wifi.powersave = 2` (2 is NetworkManager's "disable"), for every
  network, read with `sudo nmcli general reload conf`. NetworkManager applies
  it each time a network is joined; `sudo iw dev wlan0 set power_save off`
  did it at once, without leaving the network. Checked: switched on again by
  hand, then the network joined afresh, and `iw dev wlan0 get power_save`
  said off. A card written from an image older than that day does not have
  the file.
- What it changed in 40 pings to the gateway, a quarter of a second apart:
  14 ms on average with it on, 9 ms with it off, none lost either way. So
  the short losses in the monitor's log were not shown to come from power
  saving; whether there are fewer of them now is for that log to say.
