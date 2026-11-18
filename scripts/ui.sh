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
# Any arguments are passed to the program, for example: ui.sh -l "Name"
set -euo pipefail

# A tmux server of its own (the socket), because of the last setting: how long
# tmux holds an Escape character back. The chat needs half a second there
# (see tmux.conf). The interface recognises the terminal's messages by their
# shape, so it can do with 20 ms, and its Escape key then acts at once.
ROBOT_MODULE=robot.tui ROBOT_SOCKET=robot-ui ROBOT_SESSION=robot-ui ROBOT_ESCAPE_TIME=20 \
  exec bash "$(dirname "$0")/chat.sh" "$@"
