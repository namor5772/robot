#!/usr/bin/env bash
# Start the robot chat inside tmux, or rejoin one that is still running.
#
# Inside tmux the chat belongs to the Pi, not to your SSH connection: if the
# laptop sleeps or the connection drops, the chat keeps running, and this same
# command brings you back to it.
#
#   From the laptop:  ssh -t pi "bash ~/robot/scripts/chat.sh"
#   At the Pi:        bash ~/robot/scripts/chat.sh
#
# Any arguments are passed to the program, for example: chat.sh -l "Name"
#
# ui.sh starts the windowed interface through this same script, by naming
# another program and another tmux session in the two variables below.
set -euo pipefail

cd "$(dirname "$0")/.."

SOCKET=robot
MODULE="${ROBOT_MODULE:-robot.main}"
SESSION="${ROBOT_SESSION:-robot}"

# Called by tmux as the session's command: run the program, then keep the
# window open until Enter so the last lines can be read.
if [ "${1:-}" = "--inside-tmux" ]; then
  module="$2"
  shift 2
  status=0
  # Until the program shows its prompt, nothing that arrives is typing: it is
  # the terminal answering tmux. Do not print it. The prompt does its own echo.
  stty -echo 2>/dev/null || true
  .venv/bin/python -m "$module" "$@" || status=$?
  # A program that was killed outright cannot put the terminal back the way it
  # found it, and then Enter would not be recognised below.
  stty sane 2>/dev/null || true
  # The windowed interface clears the screen as it leaves, so after a normal
  # Quit there is nothing left to read.
  if [ "$module" = "robot.tui" ] && [ "$status" -eq 0 ]; then
    exit 0
  fi
  echo
  read -r -p "Ended (exit code $status). Press Enter to close. " _ || true
  exit 0
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed, so this will end if the connection drops." >&2
  exec .venv/bin/python -m "$MODULE" "$@"
fi

if tmux -L "$SOCKET" has-session -t "=$SESSION" 2>/dev/null; then
  if [ "${ROBOT_TMUX_DETACHED:-}" = "1" ]; then
    echo "It is already running in tmux; not starting another." >&2
    exit 0
  fi
  if [ "$#" -gt 0 ]; then
    echo "It is already running. Rejoining it; the arguments are ignored." >&2
    sleep 2
  fi
  exec tmux -L "$SOCKET" attach-session -t "=$SESSION"
fi

# Quote the arguments so they survive tmux handing the command to a shell.
inner="bash $(printf '%q' "$PWD/scripts/chat.sh") --inside-tmux $(printf '%q' "$MODULE")"
for arg in "$@"; do
  inner+=" $(printf '%q' "$arg")"
done

# ROBOT_TMUX_DETACHED=1 starts the session without attaching (used for tests).
detached=()
if [ "${ROBOT_TMUX_DETACHED:-}" = "1" ]; then
  detached=(-d)
fi

exec tmux -L "$SOCKET" -f scripts/tmux.conf new-session "${detached[@]}" -s "$SESSION" "$inner"
