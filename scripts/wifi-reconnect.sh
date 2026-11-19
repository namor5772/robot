#!/usr/bin/env bash
# Runs on the Pi, as a service (robot-wifi, set up by deploy.sh): puts the Pi
# back on the Wi-Fi when a network it knows comes back.
#
# NetworkManager, the system's own network service, rejoins a network by
# itself, and most of the time that is all it takes. But it can give up on a
# network (after a join that failed at the wrong moment it waits for somebody
# to connect by hand), and then the Pi stays off the air until it is restarted.
# This is that somebody: every half minute it looks, and when the Pi is off
# the Wi-Fi while a saved network is in range, it connects to it, the way
# "nmcli connection up" does when typed. If that keeps failing it restarts
# NetworkManager, at most once an hour.
#
# It knows no network by name: it uses the Wi-Fi networks saved on the Pi
# that are set to connect automatically, the one with the highest priority
# first. What it did is in /var/log/robot-wifi.log.
#
#   See it:    systemctl status robot-wifi     tail /var/log/robot-wifi.log
#   Stop it:   sudo systemctl stop robot-wifi      (until the next start of the Pi)
#   Remove it: sudo systemctl disable --now robot-wifi
set -u

DEVICE="${ROBOT_WIFI_DEVICE:-wlan0}"
INTERVAL="${ROBOT_WIFI_INTERVAL:-30}"            # seconds between looks
LOG="${ROBOT_WIFI_LOG:-/var/log/robot-wifi.log}"
RESTART_AFTER="${ROBOT_WIFI_RESTART_AFTER:-10}"  # failed joins in a row before the restart
RESTART_GAP="${ROBOT_WIFI_RESTART_GAP:-3600}"    # seconds between two restarts, at least
TICKS="${ROBOT_WIFI_TICKS:-0}"                   # for the tests: stop after this many looks
LOG_LIMIT=200000                                 # bytes; beyond that the older half goes

say() {
  echo "$(date '+%F %T') $*" >> "$LOG"
  if [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt "$LOG_LIMIT" ]; then
    tail -c $((LOG_LIMIT / 2)) "$LOG" > "$LOG.part" && mv "$LOG.part" "$LOG"
  fi
}

# "connected", "connecting (...)", "disconnected", "unavailable", or nothing
# when NetworkManager does not answer.
device_state() {
  nmcli -t -f DEVICE,STATE device status 2>/dev/null |
    awk -F: -v device="$DEVICE" '$1 == device { print $2; exit }'
}

# The saved Wi-Fi networks that connect automatically, by their saved names,
# the highest priority first.
saved_networks() {
  nmcli -t -f AUTOCONNECT-PRIORITY,AUTOCONNECT,TYPE,NAME connection show 2>/dev/null |
    sort -t: -k1,1nr -s |
    sed -n 's/^[-0-9]*:yes:802-11-wireless://p'
}

# The first saved network that is in range now, by its saved name.
network_in_range() {
  local in_range name ssid
  in_range="$(nmcli -t -f SSID device wifi list ifname "$DEVICE" --rescan yes 2>/dev/null)"
  [ -n "$in_range" ] || return 1
  while IFS= read -r name; do
    # nmcli puts a backslash in front of a colon in a name it lists.
    name="${name//\\:/:}"
    ssid="$(nmcli -g 802-11-wireless.ssid connection show "$name" 2>/dev/null < /dev/null)"
    if [ -n "$ssid" ] && grep -Fxq -- "$ssid" <<< "$in_range"; then
      printf '%s\n' "$name"
      return 0
    fi
  done < <(saved_networks)
  return 1
}

off_for=0        # looks in a row that found the Pi off the Wi-Fi
failed=0         # joins in a row that failed
waiting_said=0   # "nothing in range" is said once per outage, not every half minute
last_restart=0
looks=0

look() {
  local state name answer now
  state="$(device_state)"
  case "$state" in
    connected*)
      if [ "$off_for" -gt 0 ]; then
        say "$DEVICE is connected again"
      fi
      off_for=0; failed=0; waiting_said=0
      return ;;
    connecting*)
      return ;;  # a join is under way: let it finish
  esac

  off_for=$((off_for + 1))
  if [ "$off_for" -eq 1 ]; then
    # NetworkManager gets the first go: most of the time it rejoins by itself.
    say "$DEVICE is off the Wi-Fi (${state:-no answer from NetworkManager})"
    return
  fi

  if ! name="$(network_in_range)"; then
    if [ "$waiting_said" -eq 0 ]; then
      say "no saved network is in range: waiting for one"
      waiting_said=1
    fi
    return
  fi
  waiting_said=0

  say "'$name' is in range and $DEVICE is not on it: connecting"
  if answer="$(nmcli --wait 60 connection up "$name" ifname "$DEVICE" 2>&1)"; then
    say "connected to '$name'"
    off_for=0; failed=0
    return
  fi
  failed=$((failed + 1))
  say "that failed ($failed in a row): $(printf '%s' "$answer" | tr '\n' ' ' | cut -c1-200)"

  now="$(date +%s)"
  if [ "$failed" -ge "$RESTART_AFTER" ] && [ $((now - last_restart)) -ge "$RESTART_GAP" ]; then
    say "restarting NetworkManager"
    systemctl restart NetworkManager >> "$LOG" 2>&1
    last_restart="$now"
    failed=0
  fi
}

say "watching $DEVICE"
while :; do
  look
  looks=$((looks + 1))
  if [ "$TICKS" -gt 0 ] && [ "$looks" -ge "$TICKS" ]; then
    break
  fi
  sleep "$INTERVAL"
done
