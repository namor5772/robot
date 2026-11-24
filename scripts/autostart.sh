#!/usr/bin/env bash
# Start the robot's windowed interface, and the run of its instruction, when
# the Pi starts: nobody has to type anything.
#
#   bash ~/robot/scripts/autostart.sh on       from the next start of the Pi on
#   bash ~/robot/scripts/autostart.sh off      not any more
#   bash ~/robot/scripts/autostart.sh status   which of the two it is
#
# What starts is the interface as ui.sh starts it, on the Pi's own screen, with
# the instruction and the boxes it had when it was last used (Hands-free among
# them), and the run begins at once. It is the same interface as ever: over
# SSH, "bash ~/robot/scripts/ui.sh" joins it, and when the run has ended
# another instruction can be chosen and started there.
#
# "boot" is what the robot-autostart service runs, as root, when the Pi starts
# (deploy.sh sets that service up). It does nothing unless autostart is on.
set -uo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
# The Pi's user is whoever owns the checkout: the service runs this as root.
user="$(stat -c %U "$repo")"
home="$(getent passwd "$user" | cut -d: -f6)"
data="${ROBOT_DATA_DIR:-$home/robot-data}"
flag="$data/autostart_on"

status() {
  if [ -e "$flag" ]; then
    echo "Autostart is ON: the interface and its instruction start when the Pi starts."
  else
    echo "Autostart is OFF: nothing starts by itself."
  fi
  if command -v systemctl >/dev/null 2>&1 \
      && [ "$(systemctl is-enabled robot-autostart 2>/dev/null)" != enabled ]; then
    echo "note: the robot-autostart service is not set up; run scripts/deploy.sh (twice)."
  fi
}

# The network is up and the clock has been set: without either, the first
# call of the run fails.
ready() {
  [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] \
    && getent hosts api.anthropic.com >/dev/null 2>&1
}

boot() {
  local log="${ROBOT_AUTOSTART_LOG:-/var/log/robot-autostart.log}"
  local limit="${ROBOT_AUTOSTART_WAIT:-180}"
  local console="${ROBOT_AUTOSTART_CONSOLE:-8}"
  local waited=0 lang
  say() { echo "$(date '+%F %T') $*" | tee -a "$log"; }

  if [ ! -e "$flag" ]; then
    say "autostart is off: nothing started"
    return 0
  fi
  until ready; do
    if [ "$waited" -ge "$limit" ]; then
      say "no network or no clock after $limit s: starting all the same"
      break
    fi
    sleep 5
    waited=$((waited + 5))
  done
  # The line characters of the windows need a UTF-8 locale; a service has none.
  lang="$( . /etc/default/locale 2>/dev/null; echo "${LANG:-C.UTF-8}")"
  local environment=(TERM=linux "LANG=$lang")
  [ -n "${ROBOT_SOCKET:-}" ] && environment+=("ROBOT_SOCKET=$ROBOT_SOCKET")
  [ -n "${ROBOT_DATA_DIR:-}" ] && environment+=("ROBOT_DATA_DIR=$ROBOT_DATA_DIR")
  # Words for the launcher beside --start, for a check: "--session zzt".
  local extra=()
  read -r -a extra <<< "${ROBOT_AUTOSTART_ARGS:-}"
  # openvt runs the launcher on a text console of its own and puts the screen
  # on it. It does not wait: the interface goes on running there.
  if openvt -f -c "$console" -s -- sudo -H -u "$user" env "${environment[@]}" \
      bash "$repo/scripts/ui.sh" --start "${extra[@]}"; then
    say "started the interface for $user on console $console, after waiting $waited s"
  else
    say "could not start the interface on console $console"
    return 1
  fi
}

case "${1:-status}" in
  on)
    mkdir -p "$data" && touch "$flag" || exit 1
    status
    ;;
  off)
    rm -f "$flag" || exit 1
    status
    ;;
  status)
    status
    ;;
  boot)
    boot
    ;;
  *)
    echo "autostart.sh: use on, off or status" >&2
    exit 2
    ;;
esac
