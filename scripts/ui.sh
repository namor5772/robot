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
# running. It has a tmux session of its own, so a chat can be open as well.
#
# Any arguments are passed to the program, for example: ui.sh -l "Name"
set -euo pipefail

ROBOT_MODULE=robot.tui ROBOT_SESSION=robot-ui exec bash "$(dirname "$0")/chat.sh" "$@"
