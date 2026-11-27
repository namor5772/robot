#!/usr/bin/env bash
# Start the robot's windowed interface inside tmux, or rejoin it if it is
# still running.
#
#   From the laptop:  ssh -t pi "bash ~/robot/scripts/ui.sh"
#   At the Pi:        bash ~/robot/scripts/ui.sh
#
# It runs instructions and edits instructions and skills, in windows drawn
# with characters: buttons, lists and text boxes. F1 inside it shows the keys.
#
# Like the chat (chat.sh), it runs inside tmux and so survives a dropped
# connection: this same command brings you back to it. Ctrl-B then D leaves it
# running. It has a tmux of its own, so a chat can be open as well.
#
# More than one interface:  ui.sh --session 2
# starts a second one, or brings you back to it if it is running. Any short
# name will do in place of the 2. Each interface shows its name in its top row
# and remembers its own instruction. Ctrl-B then ) or ( goes from one to the
# next, and Ctrl-B then S lists them. Without --session you get the first one,
# which is also what --session 1 means.
#
# A run nobody has to watch:  ui.sh -l "Name" --headless
# starts that instruction's run at once, in an interface of its own that is
# not put on your screen and that closes when the run has ended. It takes the
# first free of the names h1, h2, ... (or the one --session gives it), says
# which, and remembers nothing for the next start. ui.sh --session h1 shows it
# while it runs. The instruction must have a saved task.
#
# Other arguments are passed to the program, for example: ui.sh -l "Name"
set -euo pipefail

refuse() {
  echo "ui.sh: $1" >&2
  exit 2
}

name=""
named=0
headless=0
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --headless)
      headless=1
      shift
      ;;
    --session)
      [ "$#" -ge 2 ] || refuse "--session needs a name or a number after it, for example: --session 2"
      name="$2"
      named=1
      shift 2
      ;;
    --session=*)
      name="${1#--session=}"
      named=1
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

# The name becomes part of a tmux session name and of a file name.
if [ "$named" = 1 ] && ! [[ "$name" =~ ^[A-Za-z0-9_-]{1,12}$ ]]; then
  refuse "a session name is 1 to 12 letters, digits, - or _ (for example: --session 2)"
fi

socket="${ROBOT_SOCKET:-robot-ui}"

# A headless run that was given no name takes the first one that is free, as
# every start of it is a run of its own and must not join anything.
if [ "$headless" = 1 ]; then
  command -v tmux >/dev/null 2>&1 || refuse "a headless run needs tmux, which is not installed"
  if [ "$named" = 0 ]; then
    for number in $(seq 1 99); do
      name="h$number"
      tmux -L "$socket" has-session -t "=robot-ui-$name" 2>/dev/null || break
    done
  fi
fi

session=robot-ui
program_args=""
if [ -n "$name" ] && [ "$name" != 1 ]; then
  session="robot-ui-$name"
  program_args="--session $name"
fi

if [ "$headless" = 1 ]; then
  if tmux -L "$socket" has-session -t "=$session" 2>/dev/null; then
    echo "ui.sh: that interface is already running, and a headless run needs one of its own." >&2
    echo "Leave --session out, or give it another name." >&2
    exit 1
  fi
  # Asked before anything is started: nobody may be looking at the interface
  # when it finds that it has nothing to run.
  here="$(cd "$(dirname "$0")/.." && pwd)"
  # shellcheck disable=SC2086  # the words of program_args are meant to be split
  (cd "$here" && .venv/bin/python -m robot.tui $program_args --headless --can-start "${args[@]}") \
    || exit $?
  ROBOT_MODULE=robot.tui ROBOT_SOCKET="$socket" ROBOT_SESSION="$session" \
    ROBOT_ESCAPE_TIME=20 ROBOT_PROGRAM_ARGS="$program_args --headless" ROBOT_TMUX_DETACHED=1 \
    bash "$(dirname "$0")/chat.sh" "${args[@]}"
  shown="${name:-1}"
  echo "Started as the interface '$shown'. It closes when the run has ended."
  echo "To watch it meanwhile: ui.sh --session $shown"
  exit 0
fi

# One tmux server for every interface (the socket), apart from the chat's,
# because of the last setting: how long tmux holds an Escape character back.
# The chat needs half a second there (see tmux.conf). The interface recognises
# the terminal's messages by their shape, so it can do with 20 ms, and its
# Escape key then acts at once. ROBOT_SOCKET names another tmux for a check,
# so that a test never touches an interface somebody is using.
ROBOT_MODULE=robot.tui ROBOT_SOCKET="$socket" ROBOT_SESSION="$session" \
  ROBOT_ESCAPE_TIME=20 ROBOT_PROGRAM_ARGS="$program_args" \
  exec bash "$(dirname "$0")/chat.sh" "${args[@]}"
