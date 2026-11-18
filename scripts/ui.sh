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
# Other arguments are passed to the program, for example: ui.sh -l "Name"
set -euo pipefail

refuse() {
  echo "ui.sh: $1" >&2
  exit 2
}

name=""
named=0
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
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

session=robot-ui
program_args=""
if [ -n "$name" ] && [ "$name" != 1 ]; then
  session="robot-ui-$name"
  program_args="--session $name"
fi

# One tmux server for every interface (the socket), apart from the chat's,
# because of the last setting: how long tmux holds an Escape character back.
# The chat needs half a second there (see tmux.conf). The interface recognises
# the terminal's messages by their shape, so it can do with 20 ms, and its
# Escape key then acts at once. ROBOT_SOCKET names another tmux for a check,
# so that a test never touches an interface somebody is using.
ROBOT_MODULE=robot.tui ROBOT_SOCKET="${ROBOT_SOCKET:-robot-ui}" ROBOT_SESSION="$session" \
  ROBOT_ESCAPE_TIME=20 ROBOT_PROGRAM_ARGS="$program_args" \
  exec bash "$(dirname "$0")/chat.sh" "${args[@]}"
