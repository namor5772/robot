#!/usr/bin/env bash
# Runs on the Pi: update the checkout and install dependencies into the venv.
set -euo pipefail

# Everything is inside a function so bash has read the whole script before
# "git pull" replaces this file underneath it.
main() {
  cd "$(dirname "$0")/.."

  git pull --ff-only
  .venv/bin/python -m pip install -r requirements.txt

  # tmux keeps a chat alive when the SSH connection drops (see chat.sh).
  # A failed install must not fail the deploy: chat.sh works without tmux.
  if ! command -v tmux >/dev/null 2>&1; then
    echo "Installing tmux..."
    if ! { sudo -n apt-get update -qq && sudo -n apt-get install -y -qq tmux; }; then
      echo "warning: could not install tmux; chat.sh will run without it" >&2
    fi
  fi

  install_wifi_service || echo "warning: could not set up the robot-wifi service" >&2
  install_autostart_service || echo "warning: could not set up the robot-autostart service" >&2

  # Anchored at the start of the command line, so a shell whose own command
  # merely mentions the program is not mistaken for a running one. Either way
  # of running it counts: the chat, or the windowed interface.
  if pgrep -f "^[^ ]*python[^ ]* -m robot\.(main|tui)" >/dev/null 2>&1; then
    echo "note: the robot program is running and keeps the old code until it is restarted"
  fi
}

# The service that puts the Pi back on the Wi-Fi (see wifi-reconnect.sh). Its
# description for systemd is written here and not kept as a file, because it
# names the folder this checkout is in. A failure here must not fail the
# deploy. ROBOT_SYSTEMD_DIR is for the tests.
install_wifi_service() {
  local unit_dir="${ROBOT_SYSTEMD_DIR:-/etc/systemd/system}"
  local unit="$unit_dir/robot-wifi.service"
  local script="$PWD/scripts/wifi-reconnect.sh"
  local wanted
  command -v systemctl >/dev/null 2>&1 || return 0
  command -v nmcli >/dev/null 2>&1 || return 0
  wanted="[Unit]
Description=Robot: put the Pi back on the Wi-Fi when a saved network returns
After=NetworkManager.service

[Service]
ExecStart=/bin/bash $script
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target"
  if [ "$(cat "$unit" 2>/dev/null)" != "$wanted" ]; then
    echo "Setting up the robot-wifi service..."
    printf '%s\n' "$wanted" | sudo -n tee "$unit" >/dev/null || return 1
    sudo -n systemctl daemon-reload || return 1
  fi
  sudo -n systemctl enable --quiet robot-wifi || return 1
  # Restarted every time, so that it runs the script as it is now.
  sudo -n systemctl restart robot-wifi || return 1
}

# The service that starts the interface, and the run of its instruction, when
# the Pi starts (see autostart.sh, which also holds the switch for it). It is
# only enabled here, never started or restarted: a deploy must not put an
# interface on the screen, nor touch one that is running.
install_autostart_service() {
  local unit_dir="${ROBOT_SYSTEMD_DIR:-/etc/systemd/system}"
  local unit="$unit_dir/robot-autostart.service"
  local script="$PWD/scripts/autostart.sh"
  local wanted
  command -v systemctl >/dev/null 2>&1 || return 0
  command -v openvt >/dev/null 2>&1 || return 0
  wanted="[Unit]
Description=Robot: start the interface and its instruction when the Pi starts
After=network-online.target time-sync.target systemd-user-sessions.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
KillMode=process
ExecStart=/bin/bash $script boot

[Install]
WantedBy=multi-user.target"
  if [ "$(cat "$unit" 2>/dev/null)" != "$wanted" ]; then
    echo "Setting up the robot-autostart service..."
    printf '%s\n' "$wanted" | sudo -n tee "$unit" >/dev/null || return 1
    sudo -n systemctl daemon-reload || return 1
  fi
  sudo -n systemctl enable --quiet robot-autostart || return 1
}

main "$@"
