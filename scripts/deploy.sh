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

  # Anchored at the start of the command line, so a shell whose own command
  # merely mentions the program is not mistaken for a running chat.
  if pgrep -f "^[^ ]*python[^ ]* -m robot\.main" >/dev/null 2>&1; then
    echo "note: a robot chat is running and keeps the old code until it is restarted"
  fi
}

main "$@"
