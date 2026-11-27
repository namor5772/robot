#!/usr/bin/env bash
# The window of a child run: what run_instruction's show_window puts in a tmux
# session of its own. Nobody starts this by hand.
#
#   child-window.sh LOG PID NAME
#
# The child run writes into the file LOG, and this shows the file as it grows,
# until the process PID has ended. The child is not started from here and does
# not read this keyboard: closing the window leaves it running.
set -u

log="$1"
pid="$2"
name="$3"

echo "Child run '$name' (process $pid)."
echo "This window only shows what it writes. It takes no typing: its questions"
echo "are answered from the run that started it."
echo

# From the first line on, and to the end once the child has gone.
tail -n +1 -s 0.2 --pid="$pid" -f "$log" 2>/dev/null

# With somebody watching, leave the last lines to be read. With nobody, close
# at once: a window nobody looks at should not stay for ever.
session="$(tmux display-message -p '#{session_name}' 2>/dev/null || true)"
if [ -n "$session" ] && [ -n "$(tmux list-clients -t "=$session" 2>/dev/null)" ]; then
  echo
  read -r -t 300 -p "The child run has ended. Press Enter to close this window. " _ || true
fi
exit 0
