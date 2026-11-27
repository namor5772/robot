# tmux, SSH and the terminal

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

## When the SSH connection drops

- Without tmux the chat belongs to the SSH session: if the PC sleeps or
  its network drops, the session is reset and the chat dies with it. `chat.sh`
  avoids that by running the chat inside tmux, on its own socket and session,
  both named `robot` (`tmux -L robot ...`), with `scripts/tmux.conf`. Run
  again, it reattaches and ignores its arguments. Detach is Ctrl-B then D.
- When the program ends, `chat.sh` runs `stty sane` and then waits for Enter
  so the last lines can be read. The `stty sane` matters: a program killed
  outright leaves the terminal in raw mode, and Enter was not recognised.
- tmux keeps a chat alive across a dropped connection, not across a reboot of
  the Pi. Nothing starts a chat at boot. The interface can be started at
  boot, with its run, since 2026-11-24 (see "Starting by itself").
- `ui.sh` is `chat.sh` with five variables set: `ROBOT_MODULE=robot.tui`,
  `ROBOT_SOCKET=robot-ui` (unless the environment already names a socket,
  which is how a check gets a tmux of its own), `ROBOT_SESSION` (`robot-ui`,
  or `robot-ui-NAME` with `--session NAME`), `ROBOT_ESCAPE_TIME=20` and
  `ROBOT_PROGRAM_ARGS` (the program's `--session NAME`).
  The windowed interface therefore has a tmux server of its own (`tmux -L
  robot-ui ...`), and a chat can run beside it (two processes of about 80 MB).
  The reason for a second server is `escape-time`, which is a setting of the
  whole server: the chat needs 500 ms (see below), and with that the Escape
  key took half a second to close a window. The interface sorts the
  terminal's messages out itself, so its server runs with 20 ms.
- `chat.sh` asks tmux for its session by its exact name (`=robot`), because
  tmux otherwise accepts the start of a name. In a pane target the exact
  form needs a colon: `-t '=robot:'`.
- After a normal Quit the interface's window closes at once. After a crash it
  waits for Enter, so that the traceback can be read.
- To see why an SSH session ended: `sudo journalctl -t sshd-session --since today`
  on the Pi (not `-u ssh`). On a PC, standby shows as Kernel-Power events
  506 and 507 in the System log (seen on the laptop).
- A hang-up or SIGTERM winds the run down properly (cost logged, chat saved).

## Terminal answers that reach the prompt

- Every time tmux attaches it asks the outer terminal for its type and colours,
  and the terminal answers as if typing (`ESC ] 11 ; rgb:... ESC \`). tmux keeps
  a whole answer to itself. One that arrives in two pieces further apart than
  tmux's `escape-time` is passed into the pane as key presses: readline drops
  the escape characters and leaves the text (`11;rgb:0c0c/0c0c/0c0c`) at `you>`,
  and Enter sends it. That happened on 2026-11-16 and cost one call.
- `scripts/tmux.conf` therefore sets `escape-time 500`. tmux 3.5's own default
  is 10 ms; a 100 ms gap reproduced the leak with 10 and not with 500. The
  Pi's Wi-Fi had power saving on then, which delivers packets in bunches (it
  is off since 2026-11-20, see "Getting back on the Wi-Fi"). A gap of
  more than half a second still gets through.
- For that case `Console._ask_terminal` does not take a line that is nothing
  but such answers for a reply (`console.only_terminal_replies`): it says so
  and puts the prompt up again itself. It is not handed on as an empty reply,
  which ends a conversation. Whole lines only: the same characters inside a
  sentence are sent as typed, so the person can ask about them.
- A second way in, seen on 2026-11-18: tmux asks for the terminal's type once
  and keeps one answer. Any further answer is passed into the pane whole,
  whatever `escape-time` is (played back on the Pi: one answer, nothing gets
  through; the same answer twice, the second arrives in the pane complete).
  That day the terminal's type answers (`ESC [ ? 61;4;...c` and
  `ESC [ > 0;10;1c`) arrived twice at the start of a new chat. Why the
  terminal answered twice is not known; tmux itself asked once.
- At the start of a chat such an answer arrives while Python is still
  starting, so two more things deal with it: `chat.sh` turns the pane's echo
  off before starting the program (the answer was printed in front of the
  banner), and `Console._drop_startup_input` discards whatever is waiting just
  before the first prompt (it sat at `you>`, in front of whatever was typed
  next, and with text after it the whole-line check no longer applies) and
  turns echo back on. It must: readline shows typing only when the terminal
  had echo on, and with echo left off nothing typed at `you>` was visible.
  So keys pressed before the first `you>` are lost. An answer that arrives
  later, when rejoining a running chat, is still left to the whole-line check.
- tmux reads its config when its server starts. A chat that is already running
  keeps the old value until it ends, unless it is set by hand:
  `tmux -L robot set -sg escape-time 500`.
- The windowed interface has no prompt for such an answer to land at, but an
  answer would arrive as key presses all the same: letters that press
  buttons, text in a box. There `KeyParser` (`robot/tui/screen.py`) reads
  every escape sequence to its end and drops the ones that are answers (the
  colours, the type, any other message that starts ESC ] or ESC P). Nothing
  depends on `escape-time` (its tmux runs with 20 ms) or on timing at the
  start. Only an answer whose two pieces arrive more than half a second apart
  leaves its second piece as typing. `tests/test_tui_terminal.py` sends the
  real answers to the real program.
- To reproduce a leak without the real terminal, play the terminal from a
  script on the Pi: `pty.fork()`, run `tmux -L <own socket> -f <conf>
  new-session ...` in the child, and from the parent answer `ESC ] 11 ; ? ESC \`
  in two writes with a pause between them. A pane program that reads the
  keyboard (`stty raw -echo; timeout --foreground 4 cat > file`) shows what
  got through. Without `--foreground`, `timeout` stops its command from
  reading the terminal.
