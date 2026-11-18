# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot. It is developed
on a Windows laptop and runs on a Raspberry Pi. Since 2026-11-16 the program is
a terminal port of the owner's MyAgent harness (see "Where it comes from").
Since 2026-11-18 it has two faces: the line-by-line chat (`python -m
robot.main`) and a windowed interface drawn with curses (`python -m robot.tui`,
see "The windowed interface").

## Target device

- Raspberry Pi Zero 2 W, 512 MB RAM (about 415 MB usable), 4 cores
- 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13.5, no tkinter
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API key: `~/robot/.env` (`ANTHROPIC_API_KEY=...`). Never commit it; `.env`
  is in `.gitignore`.
- The program's data: `~/robot-data` (outside the checkout on purpose).
- Passwordless sudo is enabled for `grobliro` (the user set it up on
  2026-11-15 in `/etc/sudoers.d/010_grobliro-nopasswd`).
- `/tmp` is a RAM disk. Importing the Anthropic SDK takes about 15 s and one
  process uses about 77 MB.
- Swap is compressed memory, not the SD card: a zram device of 415 MB with
  zstd, set up by the `rpi-swap` package, swappiness 60. What sits idle is
  squeezed to about a quarter of its size once memory gets short (121 MB
  into 30 MB, measured on 2026-11-19). So a program that is open but idle
  costs far less than its size, and the kernel's "available" figure, which
  counts only what can be had without swapping, can rise when one more
  program is started.
- The SD card is a 32 GB card (29.1 GiB) since 2026-11-19, and the system
  partition fills it: 29 GB, of which 2.7 GB is used. Before that it was a
  16 GB card. The owner keeps an image of the 16 GB card on the laptop (the
  state of that morning; it fits any card of 16 GB or more). What the move
  showed, since restoring a backup goes the same way:
  - The image was read with Win32 Disk Imager, with the Pi shut down, and
    written to the new card with Raspberry Pi Imager ("Use custom"). The
    copy started as the same machine: same name, same keys, `ssh pi` without
    a warning.
  - The system had been set up through cloud-init: Raspberry Pi Imager put
    `user-data` and `meta-data` on the boot partition, and `cmdline.txt`
    carries `ds=nocloud;i=<instance>`. A copy has the same instance name, so
    nothing is set up again. Writing a copy WITH the Imager's customisation
    settings would give it a new one, and the first start could then reset
    the name, the password and the keys.
  - The system does not enlarge itself on a larger card, cloud-init or not.
    `sudo growpart /dev/mmcblk0 2` (try `--dry-run` first) and `sudo
    resize2fs /dev/mmcblk0p2` did it while the Pi was running, with no
    restart and with an interface of the owner's open. The partition keeps
    its start and the disk its identifier, which is all that
    `root=PARTUUID=...` in `cmdline.txt` goes by. `raspi-config
    --expand-rootfs` does it with `fdisk` and a step at the next start (read
    in its script, not tried here).
  - A copy onto a card writes and verifies only the image's own length, here
    the first 14.6 GB. The rest of the new card was therefore tested in
    full: 23.8 GB written over the free space, in files whose every 4 KB
    block carries a stamp of its place, and all of it read back right, up to
    the card's last block (16 MB/s writing, 22 MB/s reading, 50 minutes).
    Its size is proven and needs no second test. The script was fed over
    ssh and is not in the repo.
  - `sudo dpkg --verify` checks every installed system file against its
    checksum (two minutes). On this Pi it always reports one file,
    `/usr/lib/modprobe.d/g_ether.conf`, which the tool of its own package
    (`rpi-usb-gadget`) rewrites. That is not damage.
  - A backup of the card as it is now is a 29 GB file and needs a card of
    32 GB or more.
  - The Pi keeps no log across restarts (the journal is in memory), so the
    messages of an earlier start cannot be read afterwards.
- The Pi also has a keyboard and screen attached. The screen is a text
  console (tty1) of 240 columns by 67 rows on 1920 x 1080, in UTF-8, with the
  kernel's own font and no mouse service.

## Reaching the Pi

- `ssh pi` (no password). The `pi` alias in the laptop's `~/.ssh/config` points
  at the Pi's IP address, `10.42.199.40`, with `HostKeyAlias robot.local`. It
  works from both PowerShell and Git Bash.
- That address is assigned by DHCP and can change. If `ssh pi` times out, use
  `ssh pi-local` (same Pi via `robot.local`, PowerShell only), read the new
  address with `hostname -I`, and update `HostName` under `Host pi`.
- `pi-local` uses mDNS, which Git Bash's ssh cannot resolve and which fails
  intermittently from PowerShell; retrying usually works.
- For scripted commands add `-o BatchMode=yes -o ConnectTimeout=15`.

## Workflow

1. Develop here on Windows. Run the tests (below).
2. Commit and push to GitHub (`origin`, branch `main`). The laptop remote is
   HTTPS; the Pi's remote is SSH.
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh -t pi "bash ~/robot/scripts/chat.sh"` for the chat, or
   `ssh -t pi "bash ~/robot/scripts/ui.sh"` for the windowed interface (both
   inside tmux).

Never edit files on the Pi directly. Every change goes through git; the Pi only
receives code via `git pull --ff-only`, which refuses to run if its checkout
has local edits. `~/robot-data` is the program's own data, not code: the
program and its checks may write there.

Keep README.md and this file up to date when features or scripts are added.
The pattern for every change: tests, commit, push, deploy, check on the Pi,
show the user the output. The user does not want to be asked to test things.

## The GitHub repo is public

- Everything committed is world-readable, including this file, commit
  messages and test fixtures. Never commit secrets, and do not add new
  personal, account or network details to committed files.
- An audit on 2026-11-15 found no secrets in any commit, and only the owner has
  write access. The user reviewed the findings and chose to keep the setup as
  it is. Do not change access, keys or security settings unasked.
- Code adapted from MyAgent gets freshly written comments. MyAgent's own
  comments carry personal and incident details that must not be copied here.

## Running and testing

- Unit tests, no network and no cost, on the laptop (Git Bash):
  `.venv/Scripts/python.exe -m unittest discover -s tests -t .`
  and on the Pi: `.venv/bin/python -m unittest discover -s tests -t .`
  Run both: the Pi has a different Python and real process groups.
- `tests/fakes.py` has a fake client that scripts the model's replies
  (`FakeClient`, `reply`, `tool_use`, ...), a piped console and a terminal
  console. `tests/test_wire.py` drives the real SDK over a mock network with
  recorded replies in `tests/fixtures/*.sse`; `tests/record_fixtures.py`
  re-records them (paid, a few cents; it scrubs signatures and ids).
- Tests write only into temp folders, never into the repo or `~/robot-data`.
- The laptop DOES have an `ANTHROPIC_API_KEY` in its environment. So
  `python -m robot.main` on the laptop makes real, billed calls. Paid checks
  are done on the Pi; on the laptop use the unit tests or `--dry-run`, and set
  `ROBOT_DATA_DIR` to a temp folder so nothing lands in `~/robot-data` there.
- A paid check on the Pi without a terminal: pipe lines in.
  `ssh pi "cd ~/robot && printf 'first\nsecond\n' | .venv/bin/python -m robot.main --model claude-haiku-5-5"`
  Piped lines are echoed, and the end of input ends the conversation.
  `--model claude-haiku-5-5` keeps checks cheap (a whole chat for well under a
  cent); the default Opus chat costs about 5 cents to start.
- The owner uses the Pi while work goes on. A chat may be open in tmux on the
  socket `robot`, and the windowed interface on `robot-ui`. A check must
  NEVER use those two sockets: no `kill-server`, no `send-keys`, and neither
  `chat.sh` nor `ui.sh` with their own socket, because a second start joins
  whatever is running there and the keys that follow are typed into the
  owner's session. On 2026-11-18 a check that used `robot-ui` was running when
  the owner opened the interface: they were joined to the check's session,
  and it closed under them four seconds later. Eight seconds earlier, the
  check's `kill-server` would have ended a session of theirs.
- So a check that needs a real terminal (Ctrl-C, prompts) runs in a tmux of
  its own. `chat.sh` takes the socket and the session from the environment:
  `ROBOT_SOCKET=zz-chat ROBOT_SESSION=zz-chat ROBOT_TMUX_DETACHED=1 bash
  scripts/chat.sh ...`, then `tmux -L zz-chat send-keys -t zz-chat -l --
  'text'`, `send-keys -t zz-chat Enter`, `send-keys -t zz-chat C-c`, and
  `tmux -L zz-chat capture-pane -p -t zz-chat` to read the screen. Wait for
  the last line to be `you>` before typing. End with `tmux -L zz-chat
  kill-server`.
- To run a script on the Pi without writing a file there, feed it over stdin:
  `ssh pi "cd ~/robot && .venv/bin/python -" < script.py` or `bash -s`. An
  `ssh` command inside such a script needs `-n`.
- `--dry-run` prints the exact first request; `--debug` prints every request.
- Paid checks that need saved instructions or skills create them in
  `~/robot-data` with names starting `ZZ ` (instructions) and `zz-` (skills),
  through a small script fed over stdin that uses `robot.instructions` and
  `robot.skills`, and remove them afterwards. The chats and cost-log lines of
  those checks are left in place: they are a true record of what was spent.
- To check that two runs share the prompt cache, start them within five
  minutes of each other: the second one's first `call 1:` line should show a
  large `cache_read` and a small `cache_write`.
- Some tests start real processes (`test_spawn`, `test_costs`). One such test
  was timing-dependent on a busy Pi and was fixed on 2026-11-16; if a test
  fails once and then passes, find the race instead of rerunning until green
  (running the suite with all four cores loaded brought that one out).
- On this laptop, long heredocs with quotes passed to the Bash tool have
  broken several times, and backslashes in them are rewritten (a `\x11` in a
  heredoc reached the file as the control character itself). Use the Write
  and Edit tools for file content, scripts included.
- The Write and Edit tools turn a `\uXXXX` in the text they are given into
  the character itself. To keep a source file plain ASCII, spell such a
  character as `chr(0x2500)`.
- The windowed interface has three kinds of test:
  - `tests/test_tui_*.py` except `_terminal` run everywhere, the laptop
    included, on a screen that lives in memory (`tests/tui_fakes.py`:
    `FakeScreen`, and `AppCase` with `drive(...)`). A test is a script of key
    names, `typed("text")`, `Check(function)` to look at the screen so far and
    `Until(function)` to wait for the thread that runs the agent. One call of
    `drive` is one whole session: when the script runs out, every open window
    is gone, so a second call starts again at the main window.
  - `tests/test_tui_terminal.py` starts the real program on a pseudo-terminal
    and sends it real bytes. It needs curses, so it runs on the Pi only (8
    tests, about 30 s) and is skipped on the laptop. It gives the program an
    empty API key, with which nothing can be sent.
  - `tests/test_launchers.py` runs `chat.sh` and `ui.sh` with a stand-in for
    tmux that only writes down how it was called: which socket, which
    session, which program with which arguments. Nothing is started. bash
    scripts for the Pi, so it is skipped on the laptop too (19 tests).
  - By hand on the Pi, in a tmux of the check's own (see above: never the
    owner's `robot-ui`). `ui.sh` takes another socket from the environment:
    `ROBOT_SOCKET=zz-ui ROBOT_TMUX_DETACHED=1 bash scripts/ui.sh`. The
    session in it is still called `robot-ui`. Then `tmux -L zz-ui send-keys
    -t robot-ui F4` (keys by name: `F2`, `Enter`, `Escape`, `M-s` for Alt+S,
    `C-c`), `send-keys -t robot-ui -l -- 'text'` to type, `tmux -L zz-ui
    capture-pane -p -t robot-ui` to read the screen (`-e` keeps the colour
    codes), and `tmux -L zz-ui resize-window -t robot-ui -x 72 -y 24` for
    another window size. Leave a fifth of a second after Escape before the
    next key, or the two are read as Alt+key. Wait for `Waiting for your
    message` in the bottom line before typing a reply. A paid check is cheap
    on an instruction set to `claude-haiku-5-5`. A check that starts no run
    can have a data folder of its own (`ROBOT_DATA_DIR`, exported before the
    tmux server starts). To act as a person at a terminal (joining, Ctrl-B
    keys), run the launcher under `pty.fork()` and write the keys to it.
    Mind the memory: every interface started is another 80 MB or so beside
    whatever the owner has open.
- A job on the Pi that outlasts an ssh command (the card test of 2026-11-19
  took 50 minutes) is started detached, `setsid nohup python3 -u /tmp/x.py >
  /tmp/x.log 2>&1 < /dev/null &`, and ends its log with a line that says so
  (`FINISHED: ...`). A background loop on the laptop asks once a minute
  whether that line is there. The job then survives a dropped connection and
  a laptop that sleeps. Rehearse such a job small first, and once with a
  fault put in on purpose: a check that cannot fail proves nothing.
- `pgrep -f name` run over ssh also finds the shell that ssh started for the
  command, because the name is in that shell's own command line. Write the
  pattern so that it does not match itself: `pgrep -f 'zz-cardful[l]'`.
- To try unfinished work on the Pi without touching the checkout, copy the
  working tree to a scratch folder and run it there with the checkout's
  Python: `tar -cf - --exclude=.venv --exclude=.git . | ssh pi "mkdir -p
  /tmp/robot-try && tar -xf - -C /tmp/robot-try"`, then `cd /tmp/robot-try &&
  ~/robot/.venv/bin/python -m unittest ...`. Give it `ROBOT_DATA_DIR` of its
  own. It finds no `.env` there, so it cannot make paid calls.

## State on 2026-11-18

- The instruction library on the Pi holds `Default` (Opus, Medium, Convo on,
  Meta on) and `Zero state chat` (Opus, Medium, Convo on, Meta off, no text).
  The owner moved both from Low to Medium that evening, in the Instruction
  Editor.
- The Pi has two skills, both made by the owner in chats, in
  `~/robot-data/skills`:
  - `robot-identity` (enabled, so its text is in every run's system prompt):
    the robot's name and one sentence on what it is.
  - `wifi-monitor` (on demand, fetched with `get_skill`): describes a Wi-Fi
    monitor the robot set up on 2026-11-18. That monitor is not part of this
    repo: a bash loop in `~/wifimon` that pings the gateway every 10 s, logs
    each change to `~/wifimon/wifi.log`, and starts at boot from the user's
    crontab.
- Because one skill is on demand, every run now also offers `get_skill`.
- `.venv/bin/python -m robot.main --skills` and `--list` on the Pi show the
  current skills and instructions; check there instead of trusting this list.
- 1,242 tests pass (counted on 2026-11-19). On the Pi 2 are skipped, on the
  laptop 31, among them the 8 real-terminal tests (they need curses), the 19
  launcher tests (they need bash) and 3 that build a real tree of child runs
  (they need the kernel's list of processes). `tests/test_spawn.py` starts real
  processes and is the slow one on the laptop, where starting and stopping a
  process takes a second or so: about a minute there, 12 s on the Pi.
- The windowed interface was added on this day. Its state is in
  `~/robot-data/tui_state.json`. The owner used it the same evening, over SSH
  from the laptop and at the Pi's own screen.
- On 2026-11-19 the Pi moved from its 16 GB card to a 32 GB one (see "Target
  device"), and the owner ran three interfaces at once at its own screen.
- No hardware tools exist yet beyond the CPU temperature reading.

## When the SSH connection drops

- Without tmux the chat belongs to the SSH session: if the laptop sleeps or
  its Wi-Fi drops, the session is reset and the chat dies with it. `chat.sh`
  avoids that by running the chat inside tmux, on its own socket and session,
  both named `robot` (`tmux -L robot ...`), with `scripts/tmux.conf`. Run
  again, it reattaches and ignores its arguments. Detach is Ctrl-B then D.
- When the program ends, `chat.sh` runs `stty sane` and then waits for Enter
  so the last lines can be read. The `stty sane` matters: a program killed
  outright leaves the terminal in raw mode, and Enter was not recognised.
- tmux keeps a chat alive across a dropped connection, not across a reboot of
  the Pi. Nothing starts tmux at boot.
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
  on the Pi (not `-u ssh`). On the laptop, standby shows as Kernel-Power events
  506 and 507 in the System log.
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
  Pi's Wi-Fi has power saving on, which delivers packets in bunches. A gap of
  more than half a second still gets through.
- For that case `Console._ask_terminal` treats a line that is nothing but such
  answers as a bare Enter (`console.only_terminal_replies`): it says so and
  the prompt comes back. Whole lines only: the same characters inside a
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

## Layout

- `robot/main.py`: command line. Chooses the run's settings, shows the banner,
  asks for the task, starts the agent. Imports nothing heavy, so `--list`,
  `--skills` and `--help` are instant; the SDK is loaded on a background
  thread (`ClientLoader`) while the person types.
- `robot/agent.py`: `Agent`, one run from first message to end.
- `robot/api.py`: `build_request` (the one place a request is shaped),
  streaming, and the retry ladder. The only module that imports `anthropic`.
- `robot/console.py`: `Console` (all output and input) and `Interrupts`.
- `robot/tools.py`: the Pi's own tools as `Tool` entries in `ALL_TOOLS`.
- `robot/meta.py`: Meta tool schemas, `manage_instructions`, `meta_tools`.
- `robot/spawn.py`: `run_instruction` (child runs).
- `robot/instructions.py`: `RunSettings`, the library, `settings_from_entry`.
- `robot/skills.py`: `SkillStore`, SKILL.md format, `manage_skills`.
- `robot/models.py`: model lists, capability rules, output caps, price tables.
- `robot/costs.py`: per-call cost, the cost log, the in-progress record.
- `robot/history.py`: trimming and repairing the message history.
- `robot/chats.py`, `robot/datastore.py`, `robot/relay.py`, `robot/prompts.py`.
- `robot/tui/`: the windowed interface (see its section below).
  - `text.py`: cell widths, wrapping, and `EditBuffer`, the text of a text box.
  - `screen.py`: `Screen` (what everything draws on), `CursesScreen`, and
    `KeyParser`. The only module that imports `curses`, and only inside
    `CursesScreen`.
  - `widgets.py`: `Button`, `Checkbox`, `Choice`, `TextField`, `TextArea`,
    `ListBox`, and `Window` (focus, Tab order, Alt letters, the mouse).
  - `dialogs.py`: `MessageBox`, `PickDialog`, `TextDialog`, `ChecklistDialog`.
  - `editor.py`: `InstructionEditor` and its two small windows.
    `skillsui.py`: `SkillsManager`.
  - `app.py`: `App` and `MainWindow`, the output pane, and the three classes
    that join a run to the screen (`UiConsole`, `UiInterrupts`, `Runner`).
- `scripts/deploy.sh` (runs on the Pi: pull, pip install, install tmux; its
  body is in a `main` function so the pull can replace the file safely),
  `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`.
- `requirements.txt`: `anthropic==2.8.0`, `python-dotenv==1.2.4`. Pinned on
  purpose: 2.8.0 sends API version 2026-10-21, has no `temperature`
  parameter, sends the key as a Bearer token, and is built on `httpx2`.
- `.venv/` on the laptop (gitignored): Python 3.12 with the same packages.
- `.gitattributes`: LF line endings for `*.sh`, `*.conf`, `*.sse`.

## How the agent works

### A run

- A run has `RunSettings`: name, text, model, thinking_mode, thinking_budget,
  fast_mode, meta, conversational, blocked_tools, skill_modes, upgrade_target.
- With `-l NAME` they come from that entry of `agent_instructions.json`.
  Without it, from the entry named `Default` (created on first use; model
  `claude-opus-5-5`, level Low, Meta on, Convo on), and the task is typed at
  `you>`. `--model` and `--mode` override one run.
- A plain chat borrows only `Default`'s settings: its run has no name (chat
  files are `Agent_<time>`, the cost log's instruction field is empty) and any
  text saved in `Default` is ignored. `-l Default` runs it as a named
  instruction, text included.
- An instruction with no text asks for the task when someone is there
  (`first_message`); with `--headless` or `--result-file` it cannot start.
- An entry needs only `text`. Missing settings default to `claude-opus-5-5`,
  Meta off, Convo off, and no stated thinking level, which on that model
  becomes Adaptive (the API's default effort, costlier than Low).
- `settings_from_entry` corrects values the model cannot honour (a thinking
  level it lacks) and warns. An entry for another provider is refused.
- The task is the first user message. The system prompt and the tool list are
  built once (`Agent._freeze_run`) and do not change during the run: the
  prompt cache and the model's saved reasoning are both tied to them. So a
  skill or instruction created mid-run takes effect from the next run.
- The loop (`Agent._loop`) has no step limit. Tool calls run and their results
  go back; `pause_turn` is resumed; a cut-off reply warns. When the model ends
  its turn: with Convo on the person is asked for the next message; otherwise
  the run ends (after up to three nudges if the model had been asking through
  `user_prompt` and stopped).
- Tools marked `parallel_safe` run together on a thread pool first; the rest
  run in order on the main thread. Every call gets a result, run or not.
- At the end (`_end_run`, every step best-effort): cost-log line, in-progress
  record removed, result file, chat saved.

### The system prompt

- `robot/prompts.py`. The owner approved its wording on 2026-11-16: show any
  proposed change before implementing it. It has the robot's identity, a task
  paragraph, one paragraph that depends on Convo (in a conversation: just
  reply; in a single task: you must ask through `user_prompt`), and a
  plain-text rule. Enabled skills and the on-demand skill list are appended by
  `SkillStore.compose_system_prompt`.
- The last thing in the system prompt is the "About this run" paragraph
  (`prompts.run_paragraph`, wording also approved on 2026-11-16): the
  instruction's name, or that it is a plain chat on the `Default` settings, and
  the model the run started on. It is sent as a second system block with no
  cache marker (`api.cache_system`), so runs of different instructions still
  share the cached prompt in front of it. It is fixed like the rest: after an
  `upgrade_model` it still names the starting model, and its last sentence
  (present only when the run has that tool) tells the model to trust the
  tool's result instead.
- Apart from that paragraph nothing dynamic goes into the system prompt.
- Tool descriptions are in `agent.py` (`user_prompt`, `get_skill`), `meta.py`
  and `tools.py`. They are model-facing text too: treat changes with care.

### Tools

- Always: `run_shell_command`, `get_current_datetime`, `get_cpu_temperature`
  (only if the sensor reads at start), `user_prompt`, server-side `web_search`
  (`models.web_search_tool`: `web_search_20260209`, `max_uses` 5; its
  definition alone is about 6,000 tokens of every request).
- `get_skill` when a skill is on demand. Its result adds the skill's folder
  path when the skill has bundled files, so they can be run with the shell.
- With Meta on: `manage_instructions`, `manage_skills`, `run_instruction`,
  `upgrade_model` (about 3,000 more tokens).
- `blocked_tools` removes tools from the offer and refuses them at dispatch.
- The shell tool has NO guardrails by the owner's explicit choice (2026-11-15):
  no confirmation, no allowlist, no blocked commands, and MyAgent's
  blocked-command list is not ported either. Do not add any unasked. Its
  timeout, `/dev/null` stdin and output trimming are plumbing.
- Consequence: the model can read `~/robot/.env`, edit the checkout (which
  would make `git pull --ff-only` refuse), act as root on text from a web
  search, and write skills that later runs load. The banner lists the skills
  in use for that reason.

### Input, output and Ctrl-C

- `Console` prints: `robot>` before each stretch of reply text, `[tool: ...]`
  lines, indented activity and `call N: <cost>` lines (hidden by
  `--no-activity`), `warning:` and `error:` lines (always shown), thinking
  with `--thinking`. Everything shown also goes to the chat's `.txt`.
- Input modes: a terminal (readline `input()`), piped stdin (lines are replies,
  end of input means nobody is there), `--headless` (never reads stdin: a relay
  folder answers, or nobody does).
- At a terminal the chat is forgiving, unlike MyAgent's dialog: an empty line is
  ignored (and so is a line that came from the terminal itself, see "Terminal
  answers that reach the prompt"), Ctrl-C cancels the reply or command and
  returns to `you>`, an API error returns to `you>`. Everywhere else MyAgent's rules hold: an empty reply
  ends a conversation, and an empty reply or `exit` to `user_prompt` stops the
  run (`quit` and `stop` there go to the model).
- `Interrupts`: the loop runs on the main thread. The SIGINT handler sets a
  flag and raises `KeyboardInterrupt` only inside `raisable()` regions (the
  stream, backoff waits, `input()`, sequential tools), so bookkeeping is never
  cut in half. SIGTERM and SIGHUP set the stop flag. Three Ctrl-Cs in three
  seconds exit at once.
- Only the main thread reads the terminal. A tool on a pool thread that needs
  the person (a waited child's question) uses `Agent.ask_from_pool`.
- `history.repair_tool_pairs` runs before every request, so a tool call is
  never sent without its result.

### The request

- `api.build_request`: model, system as one cached block, messages with cache
  markers on the two newest user turns, tools, `max_tokens` at the model's
  ceiling (128,000), `thinking {adaptive, display summarized, block_binding
  drop_block}`, `output_config.effort` from the thinking level, `fallbacks
  "default"`, `speed "fast"` when fast mode applies, and the matching betas.
  No temperature anywhere.
- A finished reply is kept in the history whole (thinking and search results
  included); a reply that was cut off, refused or interrupted is kept as text.
  MyAgent keeps text only in every case.
- Retry ladder (`api.call_model`, 10 attempts): rate limits, overload and
  connection errors back off; a feature the API refuses (fast mode, fallbacks,
  binding, the newer search tool, a too-high output cap) is recorded in
  `Learned` and no longer sent; a context overflow trims the oldest rounds in
  place and retries. The rungs match on the API's error wording.

### Cost, chats, records

- `models.PRICING` and friends price each call by the model and speed that
  served it, plus the web search fee. The cost log is
  `~/robot-data/APICostLog_<host>.txt`, one line per run in MyAgent's format.
- `~/robot-data/runs/agent_run_<pid>.json` is rewritten after every call and
  removed at the end. A leftover from a killed run is logged at the next start
  with `unfinished@call<N>`.
- Every run saves `saved_chats/<Instruction or Agent>_<timestamp>.json` and a
  live `.txt`. Chats are never loaded back.
- An interrupted call is costed from what had streamed (an estimate).

### Meta tools and child runs

- `manage_instructions` (in `meta.py`): `create` takes model settings it is not
  given from the calling run, and writes no `skill_modes` unless asked (a map
  switches off every skill it does not name). Keys of other programs in an
  entry are preserved.
- `manage_skills` (in `skills.py`) works on the run's `SkillStore`. Saving
  writes global modes only, never a run's session modes, and only the skills
  this run changed.
- `upgrade_model` (`Agent.do_upgrade_model`): once per run, to the
  instruction's `upgrade_target` or the default `claude-fable-5-2` at Max. The
  cost log gets `upgraded-from=<model>@call<N>` and a per-model split.
- `run_instruction` (`spawn.py`): a child is `python -m robot.main -l NAME
  --headless ...` in its own session. A child of a child cannot start
  children. A waited child reports through a result file; its questions go
  through a relay folder and are answered from `answers`, or put to the person
  at the parent's terminal. A child nobody waits for and nobody answers stops
  at its first question. Temp files are in `~/robot-data/tmp`.
- How many children run at once is decided by free memory, up to a ceiling
  of 8 (since 2026-11-19, at the owner's request, so that the same code suits
  a Pi 5; until then it was two, fixed). `spawn._why_not_another` starts a child
  only while `MIN_FREE_MB` (110) is available: `CHILD_MB` (80) for the child
  and `SPARE_MB` (30) left over.
  - A child that has just been started holds almost nothing, and the kernel's
    figure does not know what it is about to take. So what each child still
    starting has yet to take (`CHILD_MB` less what it holds now, read from
    `/proc/<pid>/statm`) is taken off the available figure first. Without
    that, several children asked for in one turn would all be started: those
    calls run side by side on the thread pool. `_spawn_lock` makes them be
    judged one after the other.
  - Measured on the Pi on 2026-11-19: a run holds 5 MB at its start and 77 MB
    eleven seconds later; available memory falls by 57 MB, less than the 77,
    because the runs share what they load from the same files. Six children
    asked for at once with 261 MB available: two started, four were refused
    ("... will go to the 2 child runs still starting"), and a third was
    allowed once the two had loaded and 143 MB was left. With a real parent
    run beside them the Pi Zero still comes to two, as before.
  - The available figure is what can be had without pushing anything into
    swap, and the swap here is compressed memory (see "Target device").
    What idle programs would give up to it is not counted until the kernel
    has moved it. So the rule is on the careful side, and the same programs
    can leave less before a squeeze than after one: 120 MB was available
    with two idle interfaces open and 141 to 147 MB with three (2026-11-19,
    see "Several screens, several interfaces").
  - On top of that there is a ceiling, `MAX_CHILDREN` = 8 alive at once,
    which the owner set on 2026-11-19: every child is a paid run, and with
    gigabytes free memory alone would allow dozens. It is checked first and
    has a refusal of its own. On the Pi Zero memory stops a run long before
    it.
  - The 8 is for the WHOLE TREE, at the owner's word: the first run's
    children and the children those start (`MAX_DEPTH` lets a child start
    children, and those none), counted together. The old limit of two was
    per program. The memory allowance for children still starting is for the
    whole tree as well.
  - How the runs of a tree see each other. The first run makes up a name
    (`spawn.family()`); every child gets it in `ROBOT_SPAWN_FAMILY` and
    hands it on. `family_members()` then reads the kernel's list: a process
    counts when its command line starts with `CHILD_COMMAND` and its
    environment carries the tree's name. Nothing is kept in files, so a run
    that is killed drops out of the count by itself. The shell commands a
    child starts inherit the name, which is why the command is looked at
    too. The first run is not a member: nobody handed it a name.
  - Two programs of a tree can be starting a child at the same moment (a
    child and its parent). `_one_start_at_a_time` therefore holds, besides
    the lock between threads, an exclusive hold (`flock`) on the data
    folder's `tmp` while a start is judged and made. A hold that cannot be
    had in ten seconds is done without. Python opens that folder so that a
    child does not inherit the hold.
  - Off Linux none of this can be read, and a program counts its own
    children, as before. `tests/test_spawn.py` builds made-up `/proc` trees
    for the laptop, and on the Pi a real tree: its stand-in child `Family`
    starts children of its own (3 tests, skipped on the laptop).
  - Where the free memory cannot be read (anywhere but Linux: the laptop's
    tests), `FALLBACK_MAX_CHILDREN` (2) applies.
  - The tool's description in `meta.py` said "at most two can run at the same
    time". It now says that the number depends on the memory that is free and
    is never more than 8 in all, the children of child runs included; the 8
    is taken from `spawn.MAX_CHILDREN`, so the two cannot drift apart.

## The windowed interface

`python -m robot.tui`, started through `scripts/ui.sh`. It does what MyAgent's
windows do, as far as a terminal allows: a main window with START, STOP,
Instruction and Skills, an Instruction Editor and a Skills Manager. The agent
underneath is the same code the chat runs; only the console differs.

### A run and the screen

- Two threads. The agent keeps the MAIN thread, because its Ctrl-C handling
  (`Interrupts`) works through signals, and Python delivers those to the main
  thread only. The screen has a thread of its own. `app.main` starts both.
- They share a `Bridge` of three queues: `events` (run to screen: output,
  "the robot is waiting", "the run ended"), `replies` (screen to run: what was
  typed), `jobs` (screen to run: run this instruction, or quit).
- `Runner.serve` (main thread) takes a job and sets the run up with the same
  functions `robot.main` uses (`load_library`, `load_skills`, `show_banner`,
  `first_message`), then `Agent.run()`. One run at a time. `api.Learned` is
  carried from one run to the next.
- A run here is always the run of a NAMED instruction, `Default` included
  (like `-l Default`): chat files and the cost log carry the name. The plain
  chat's nameless run exists only in `robot.main`.
- `UiConsole` is a `Console` whose `_show` posts to the screen and whose
  `_read_reply` waits for the reply box. `tty` is True, so the forgiving
  rules of a chat at a terminal apply. The transcript is written as before.
- STOP is `UiInterrupts.press()`: it sets the flag and sends the main thread
  a real SIGINT (`signal.pthread_kill`). The flag alone would not do: the
  agent may be blocked in a network read or a 60 s shell command, and only a
  signal wakes it there. From then on it is the chat's Ctrl-C path, unchanged.
  The screen's thread blocks SIGINT, SIGTERM and SIGHUP for itself, so that a
  signal from outside also lands on the main thread.
- STOP while the robot waits for a message ends the run (`_read_reply`
  returns None, "nobody is there"). The chat's "press Ctrl-C again" does not
  exist here, and neither does its "three presses leave at once", which would
  skip putting the terminal back.
- Quit during a run asks, then presses stop with `end_run` and waits up to
  15 s for the run to wind down (cost logged, chat saved) before the window
  goes.
- `costs.process_is_robot` counts a `robot.tui` process as the program. It
  must: otherwise a chat started beside the interface would take the
  interface's in-progress cost record for a dead run and log it.

### The screen and the keys

- Everything draws on a `Screen`: `put`, `fill`, `box`, clipped at the edges.
  `CursesScreen` is the real one. Tests use `FakeScreen`, a grid in memory,
  because Python on Windows has no curses. Keep curses out of every other
  module, or the laptop's tests stop importing.
- Drawing is immediate: each frame erases, draws every open window in order,
  and lets curses send only what changed. A frame is drawn only when
  something happened (`App.dirty`). There are no curses sub-windows.
- The terminal is in raw mode with `nonl`: Ctrl-C, Ctrl-Q and Ctrl-Z arrive
  as keys, and Enter (CR) is told apart from Ctrl+J (LF), which the reply box
  uses for a new line.
- `KeyParser` turns bytes into key names. curses recognises the keys the
  terminal's description lists; the parser does the rest: Alt+letter (ESC,
  then the letter at once), pasted text (bracketed paste is switched on, so a
  paste arrives between two marks and goes into a box as text), the mouse,
  and the terminal's own answers, which it drops.
- Importing `readline` (the chat's console does) takes the window-size signal
  for itself, and curses then never hears of a resize. `app.main` gives the
  signal back before curses starts, and `CursesScreen` also asks the terminal
  for its size whenever a read times out. Either one is enough.
- curses must start AFTER `Interrupts.install()`: it leaves alone the signals
  that already have a handler, and takes over the ones that do not.
- While the windows are up, Python's stdout and stderr and the process's
  error stream go to `~/robot-data/tui_errors.log`: anything printed straight
  to the terminal would land in the middle of the windows.
- The smallest screen is 72 x 18. Below that a message asks for a larger one.

### The windows

- A `Window` holds widgets; the order they are added is the Tab order. In a
  label, `&` marks the Alt letter (`"&Save"`). Letters are unique per window.
- A dialog is shown with `App.run_modal(window)`, which loops until the
  window closes and returns its result, so asking a question is one line
  (`if self.app.confirm(...)`). The run's events are taken in on every turn of
  every such loop.
- The focus is never left on START: Enter presses the focused button, and a
  stray Enter must not start a run that costs money. It starts on Instruction
  (as in MyAgent) and goes to the output pane when a run ends.
- A letter typed without Alt presses nothing, except in a message box (y, n).
  Typing while the robot waits goes to the reply box wherever the focus is.
- A `Choice` changes only through its list. Arrow keys never change a
  setting, they move the focus.
- Both editors read their store afresh before every write, and write one
  entry: a change a run made meanwhile to another instruction or skill
  survives. The Skills Manager makes every change through `manage_skills`,
  the tool's own code, so rules and messages are the same.
- The Instruction Editor keeps the keys of other programs in an entry
  (`section`, `order`, ...). An entry for another provider can be read but
  not saved or used. "New" keeps the settings on the form and clears the
  rest. There is no rename: a new name saves a copy.
- Saving writes `thinking_mode` explicitly, also for an entry that had none
  (which ran at Adaptive on Opus): the form shows what a run would use.
- The top row (`app.top_line`) never loses what follows the name: the model,
  the kind of run and `meta` are what it is there to show, and the name is
  the one part of any length. A row too long for the window gives up the end
  of the name first, marked with three dots (while 16 cells of it are left),
  then the word Robot, then more of the name (down to 8 cells), then the
  space around the dividers, then the name down to one letter and its dots.
  Even the longest settings there are fit the smallest window that way, also
  with a short session name in front. `describe_instruction` returns the
  parts, not a finished line, so that this can be done.
- `~/robot-data/tui_state.json` holds the instruction in use and the five
  display boxes (`tui_state_NAME.json` for a copy started with a session
  name). Nothing a run needs is in it.
- The Tools dialog lists `editor.TOOL_NAMES`: the six ordinary tools first,
  the four Meta tools last, then any blocked name the program does not know
  (one copied in from MyAgent), so that such a block is not lost on saving.
  The README's tool table is in the same order. Nothing marks where the Meta
  group starts. `meta` in the top row stands for that group of four.

### Several screens, several interfaces

- `ui.sh` run a second time JOINS the interface that is running: one program,
  several screens (`tmux -L robot-ui list-clients` shows them), each showing
  the same windows, any keyboard driving them. The window takes the size of
  the screen used last (tmux's `window-size latest`), so another screen may
  show it cut off or padded.
- At the Pi's own screen (`TERM=linux`, 240 x 67) it is the same command. The
  owner has used it there. Shift+Tab works: the console's keymap sends ESC
  Tab for it, which is the back-tab of the `linux` terminal description and
  which `KeyParser` takes for one as well.
  Alt with an F-key switches text consoles and never reaches a program, which
  costs nothing here: the interface's F-keys are used without Alt.
- There is no mouse at the Pi's own screen. The kernel sees the owner's
  mouse, but the text console hands no clicks to a program: over SSH it is
  the laptop's terminal that reports them. `gpm` (not installed) would not
  change that, because tmux takes the mouse only from a terminal that
  reports it. The interface could read `/dev/input/mice` itself and draw a
  pointer (the user is in the `input` group). The owner was asked on
  2026-11-19 and is content with the keyboard there: do not build that
  unasked.
- The text consoles give each interface a screen to itself at the Pi. Alt+F2
  shows tty2 (the keymap has `Console_2` on it), which asks for a login the
  first time: nothing runs on tty2 to tty6 until one is shown. `ui.sh
  --session 2` there, and Alt+F1 and Alt+F2 go between the two. The keys
  work with an interface on the screen: curses' raw mode is a setting of the
  terminal's line handling, and the kernel goes on reading the keyboard
  itself (`kbd_mode -C /dev/tty1` says Unicode with the interface up). On
  2026-11-19 the owner ran three that way, on tty1, tty2 and tty3.
- A second, separate interface: `ui.sh --session 2` (added 2026-11-19). The
  name is 1 to 12 letters, digits, `-` or `_`; `ui.sh` checks it before
  anything starts, because it becomes part of a tmux session name and of a
  file name, and the program checks it again (`app.session_name`). Session 1
  is the first interface, the one started without the option.
  - `ui.sh` takes the option out of the arguments and does two things with
    it. The tmux session becomes `robot-ui-2`, on the same socket, so every
    interface is in one tmux and its keys go between them: Ctrl-B then `)`,
    `(` or `s`. And the program is started with `--session 2`, which
    `chat.sh` gets through `ROBOT_PROGRAM_ARGS`, not among the person's own
    arguments: "the arguments are ignored" is then only ever said of
    something the person typed.
  - In the program the name does two things. It is shown in the top row
    (`Robot 2  |  ...`) and stays there when the word Robot gives way, since
    it is what tells the copies apart. And the copy keeps its settings in
    `tui_state_2.json`, so each remembers its own instruction and boxes, the
    way MyAgent's instance N has its own `agent_state_N.json`.
  - `--session` has no string default in `build_parser`: argparse puts a
    default that is a string through the option's `type`, and `session_name`
    refuses an empty name. With `default=""` the program did not start at
    all. The tests caught it; the laptop cannot run the program to show it.
  - Tried for real on the Pi on 2026-11-19, on a socket of the check's own:
    two interfaces, a terminal that joined one and went to the other and back
    with tmux's keys, and a settings file each.
- The interfaces share the instruction library and the skills (each editor
  reads afresh before it writes) and the cost log (lines are appended). Runs,
  saved chats, in-progress cost records and remembered settings are each
  copy's own.
- Memory decides how many instructions run at once, not a count: there is no
  limit on interfaces or chats, and the limit on child runs is a memory rule
  (see "Meta tools and child runs"). What counts is how many are WORKING at
  the same moment, not how many are open: the swap is compressed memory (see
  "Target device"), and an interface that sits idle is squeezed into it.
  - 2026-11-18: an interface takes 84 MB when started and 93 MB after half
    an hour of use. With one open about 190 MB was available.
  - 2026-11-19, the owner's interfaces after a reboot, no run going in any.
    Two open: 83 MB each, 72 MB of it their own and the rest shared, 2 MB in
    swap, 120 MB available. Three open, the third two minutes old: 141 to
    147 MB available, which is more than with two. Starting the third had
    made the kernel move about 50 MB of each older interface into swap: they
    then held 33 and 41 MB, the new one 79 MB, and the swap held 121 MB in
    30 MB of memory. `spawn._why_not_another` would have started a child run
    at that moment.
  - So an open interface costs about 80 MB while it works and 30 to 40 MB
    once it has been squeezed (what it still holds, and its swapped part at
    a quarter of the size). Using it again brings that memory back first.
  - Until that day this file said that a second interface leaves about
    100 MB, so that `run_instruction` is refused in both, and that three
    running instructions in all is the most. Neither held for interfaces
    that are merely open. About three WORKING at once is still the estimate
    (a run with its two children has been seen); it has not been tried with
    three interfaces each in a run.

## Where it comes from

- MyAgent is the owner's tkinter agent app, in the folder
  `Claude_Python_Testbed` next to this one on the laptop. Its package cannot
  be imported on the Pi (every module imports tkinter), so its engine logic
  was copied and adapted here. That repo documents itself in its `CLAUDE.md`
  and `docs/claude/myagent/`.
- Mapping: `streaming_mixin.py` (loop, cost) -> `agent.py`, `costs.py`;
  `anthropic_mixin.py` -> `api.py`; `ui_mixin.py` capability helpers and the
  tables in `constants.py` -> `models.py`; `helpers.py` -> `history.py`;
  `instructions_mixin.py` -> `instructions.py`, `meta.py`; `skills_mixin.py`
  and `datapaths.py` -> `skills.py`, `spawn.py`, `datastore.py`;
  `chat_mixin.py` -> `chats.py`; `relay.py` -> `relay.py`.
- `robot/tui` is new code, not a port: MyAgent's windows are tkinter. It
  follows MyAgent's layout and habits (START / STOP / Instruction, the
  editor's list beside its form, the skill list's `[ON]` and `[OD]`, Cycle
  Mode, where the focus starts). MyAgent's sections in the instruction list,
  its Apply of an unsaved draft, images, voice and window colours are not
  there.
- Left out on purpose: MyAgent's tkinter code, the safety confirm system,
  other providers, MyAgent's file, document, desktop, browser, mail and MCP
  tools, OneDrive sharing, images, voice, the live model listing. MyAgent runs
  on SDK 0.84.0;
  this runs on 2.8.0, which is why temperature and several of MyAgent's
  workarounds are gone.
- File formats match MyAgent's (`agent_instructions.json`, `SKILL.md`, the
  cost log, the relay files), so data can be copied across. MyAgent skills
  name tools the robot lacks (`run_command`, not `run_shell_command`).
- When Anthropic releases a model, update `robot/models.py`: `FALLBACK_MODELS`,
  `MAX_OUTPUT_TOKENS`, the capability rules if the family behaves differently,
  and `PRICING` (plus `FAST_PRICING` and `LONG_CONTEXT_PRICING` where they
  apply). A model with no price row is warned about at run start and its runs
  are not written to the cost log. MyAgent and SelfBot hold the other two
  copies of these tables.

## Conventions

- Shell scripts and tmux config keep LF line endings.
- Keep dependencies light: 512 MB RAM, and nothing that needs compiling on the
  Pi. The program itself uses the standard library plus the two pinned packages.
- For any Anthropic API change, load the `claude-api` skill first; model IDs
  and request shapes change often. Test what the API accepts with a paid check
  on Haiku before relying on it.
- No hardware beyond the Pi itself (motors, sensors, camera, speaker) is wired
  into the code, and what is attached to the robot has not been recorded here.
  Ask before assuming any.
