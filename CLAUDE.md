# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot. It is developed
on the owner's two Windows PCs, a laptop and a desktop (see "The two PCs"), and
runs on a Raspberry Pi. The program is a terminal port of the owner's MyAgent
harness (see "Where it comes from"). It has two faces: the line-by-line chat
(`python -m robot.main`) and a windowed interface drawn with curses (`python -m
robot.tui`, see "The windowed interface"). It sees (a webcam and `view_image`),
hears speech and talks (`microphone_listen` and `speak`, through xAI's speech
services), can listen hands-free and start with the Pi, remembers from one run
to the next (see "Memory"), and can run an instruction in an interface nobody
watches (`ui.sh --headless`).

## Where the rest is

This file holds only what every session needs: the rules, the workflow and
the layout. The history and the detail of each topic are in `docs/claude/`.
A reference such as (see "Hearing") names a section: the list below says
which file has it.

Read the file BEFORE working on its topic. It holds what was measured, what
was tried and how, what failed and why, and the owner's decisions.

- `docs/claude/hardware.md`: "Target device" in full. The move from the Pi
  Zero 2 W to the 3 A+, temperature and throttling, the swap, the SD card,
  its backup image and how a card is copied and enlarged.
- `docs/claude/testing.md`: the rest of "Running and testing". The three
  kinds of test of the windowed interface and how to drive it by hand in a
  tmux of the check's own, PowerShell on the desktop, detached jobs on the
  Pi, trying unfinished work in a scratch copy, a race on Windows.
- `docs/claude/state.md`: "State on 2026-11-18". The instructions and the
  skills on the Pi and how each was made, the test count, and what
  changed on which day, up to "State on 2026-11-28" at its end.
- `docs/claude/wifi.md`: "Getting back on the Wi-Fi". NetworkManager, the
  `robot-wifi` service, the saved networks, power saving, the Pi's clock.
- `docs/claude/terminal.md`: "The scripts by name" (the Pi's search path),
  "When the SSH connection drops" and "Terminal answers that reach the
  prompt". tmux, `chat.sh` and `ui.sh`, which sessions there are on which
  tmux, `escape-time`.
- `docs/claude/agent.md`: "How the agent works". "A run", "The system
  prompt", "Tools", "Input, output and Ctrl-C", "The request", "Cost,
  chats, records", "Meta tools and child runs" (the memory rule for child
  runs, and a child's window, `show_window`).
- `docs/claude/pictures.md`: "Pictures". `view_image`, and
  `scripts/pi_photo.py`.
- `docs/claude/hearing.md`: "Hearing". `microphone_listen` and xAI's speech
  to text.
- `docs/claude/handsfree.md`: "Hands-free". The segmenter, the ear, the
  spoken goodbye and the power-off.
- `docs/claude/memory.md`: "Memory". The files, waking and falling asleep,
  named memories, the Memories window, `manage_memories`.
- `docs/claude/speaking.md`: "Speaking". `speak`, `voice_settings` and
  xAI's text to speech.
- `docs/claude/sound.md`: "Sound". Recording and playing files, the
  `record-sound` and `play-sound` skills, the speakers,
  `scripts/pi_sound.py`.
- `docs/claude/interface.md`: "The windowed interface". "A run and the
  screen", "The screen and the keys", "The windows", "Starting by itself"
  (the autostart), "A headless interface" (`ui.sh --headless`), "Several
  screens, several interfaces".

Keeping it that way:

- What is new about a topic (a measurement, a check and its cost, a
  decision of the owner's) goes into that topic's file, in the same commit
  as the change. A new topic gets a file of its own and a line in the list
  above.
- This file gets a line only for a rule that every session must know
  without having looked anything up: something that must not be done, or
  that must always be done. Keep it under 40,000 characters.
- These files are in the public repo like everything else (see "The GitHub
  repo is public").

## Target device

The full section, with everything that was measured, is in
`docs/claude/hardware.md`.

- Raspberry Pi 3 Model A+ since the evening of 2026-11-22: 512 MB RAM (about
  415 MB usable, and 414 MB of compressed swap), 4 cores at up to 1.4 GHz.
  Until then a Raspberry Pi Zero 2 W; the owner moved the SD card (32 GB)
  from the one board to the other. What is dated before that evening was
  measured on the Zero 2 W.
- The board has ONE USB port, and the webcam is in it. Its headphone socket
  has the speakers. The webcam's microphone is the sound card NAMED `B100`.
- 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13.5, no tkinter
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API keys: `~/robot/.env` (`ANTHROPIC_API_KEY=...`, and since 2026-11-23
  `XAI_API_KEY=...` for hearing and speaking). Never commit it; `.env` is
  in `.gitignore`.
- The program's data: `~/robot-data` (outside the checkout on purpose).
- Passwordless sudo is enabled for `grobliro`.
- `/tmp` is a RAM disk. Importing the Anthropic SDK takes about 10 s and one
  process uses about 77 MB. Memory is what limits the Pi: mind it in every
  check that starts a program.
- The Pi keeps no log across restarts (the journal is in memory), and it has
  no clock of its own: started with no network, it carries an old date
  until a network gives it the time.
- The Pi also has a screen attached: a text console (tty1) of 240 columns
  by 67 rows, in UTF-8, with no mouse service.
- The settings of the Pi itself (its networks, power saving, USB, sound
  levels, security) are the owner's: not changed unasked.

## The two PCs

- The repo is checked out on two Windows PCs of the owner's: a laptop, where
  all the work up to 2026-11-20 was done, and since 2026-11-22 a desktop. The
  work goes the same way on both: tests, commit, push, deploy, check on the
  Pi.
- This file is the same on both, so it cannot say which PC a session is on.
  Look: the desktop's key, `~/.ssh/id_ed25519.pub`, ends in `robot-desktop`.
  Where this file says "the laptop" or "the desktop" it means that PC and not
  the other; what holds on both says "a PC" or "Windows".
- Start every piece of work with `git pull --ff-only`: the other PC may have
  pushed since. End it with a push. What is not pushed is on one PC only.
  That goes for Claude's own notes as well (its memory folder is kept per
  PC): what both PCs must know belongs in this file.
- What a PC needs for this repo, and both have:
  - A key of its own that the Pi accepts, and `pi` and `pi-local` in its
    `~/.ssh/config` (see "Reaching the Pi"). The Pi's
    `~/.ssh/authorized_keys` holds two keys, one per PC; the desktop's is
    marked `robot-desktop`. A key there decides who gets into the Pi: one is
    added only when the owner asks, and the owner does the adding. The
    desktop's was made and added on 2026-11-22.
  - `.venv` in the checkout, for the unit tests. The desktop's was made with
    `py -3.13 -m venv .venv` and `.venv/Scripts/python.exe -m pip install -r
    requirements.txt`; it has Python 3.13.5, as the Pi has, and the laptop's
    has 3.12.
- A session on one PC can be worked from the other without the other's
  checkout coming into it (the owner did so on 2026-11-26): `/remote-control`
  typed in the session on the laptop, and the session then showed in the
  Claude app on the desktop. Everything still runs on the PC the session
  was started on, with its checkout, its key and its tools, and that PC
  must stay on with the terminal open. The other PC's checkout is not
  touched: it needs its `git pull --ff-only` as ever.
- What differs: Git Bash does not work on the desktop, and so neither does
  the Bash tool. Its tries end in `dofork: child -1 - forked process ...
  died unexpectedly, ... exit code 0xC0000142`, or in an exit code and
  nothing else: Git Bash cannot start a second process there. `git` itself
  works, and PowerShell does everything else (see "Running and testing").
  The reason, as far as it was looked into on 2026-11-22: Windows is set there
  to load every program at a random address, for the whole system ("Force
  randomization for images (Mandatory ASLR)" under Exploit protection;
  `(Get-ProcessMitigation -System).ASLR` says `ForceRelocateImages : ON`), and
  Git Bash is known to fail in just this way with that. It was not switched
  off to prove it: it is a security setting of that PC, not to be changed
  unasked.

## Reaching the Pi

- `ssh pi` (no password), from either PC. Each has a `pi` entry in its own
  `~/.ssh/config`: the Pi's IP address as `HostName`, `User grobliro`, and
  `HostKeyAlias robot.local`, which has ssh look the Pi's host key up under
  that name whatever the address is. On the laptop it works from both
  PowerShell and Git Bash; the desktop has PowerShell only.
- That address is given out by the router of the network the Pi is on (DHCP).
  It can change there, and on another network it is a different one. A PC's
  entry holds the address the Pi had when the entry was last put right, so
  after the Pi has moved to another network (as on 2026-11-22, see "Getting
  back on the Wi-Fi") `ssh pi` times out on a PC not used since. The same
  happens when the SD card moves to another board, as on the evening of
  that day: the router goes by the radio's own address, which belongs to
  the board, and gives the Pi another one. The addresses are not written
  down here.
- If `ssh pi` times out, use `ssh pi-local` (same Pi via `robot.local`,
  PowerShell only), read the new address with `hostname -I`, and update
  `HostName` under `Host pi` on that PC.
- `pi-local` uses mDNS, which Git Bash's ssh cannot resolve and which fails
  intermittently from PowerShell; retrying usually works.
- When `ssh pi` times out AND `pi-local` says "Could not resolve hostname"
  twice over, the Pi is off (a spoken "bye" does that) or on a network the
  PC is not on. Nothing a session does brings it back: say so, finish what
  needs no Pi, and name what is still owed there. So it was on the evening
  of 2026-11-27; the next morning the Pi answered at its old address.
- For scripted commands add `-o BatchMode=yes -o ConnectTimeout=15`. A
  session's command can neither type a password nor answer a question: with
  these two, a login that is not set up fails at once instead of waiting.
- A PC is set up for this once, as the desktop was on 2026-11-22: a key
  (`ssh-keygen -t ed25519`), the two entries in `~/.ssh/config`, and the
  Pi's host keys in `~/.ssh/known_hosts` under the name `robot.local`,
  copied from the lines of the address at which the owner had accepted
  them. Then the owner adds the public key on the Pi; until then every
  login from that PC's sessions is refused.

## Workflow

1. Develop here on Windows, on either PC, after a `git pull --ff-only` (see
   "The two PCs"). Run the tests (below).
2. Commit and push to GitHub (`origin`, branch `main`). The PCs' remotes are
   HTTPS; the Pi's remote is SSH.
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh -t pi "bash ~/robot/scripts/chat.sh"` for the chat, or
   `ssh -t pi "bash ~/robot/scripts/ui.sh"` for the windowed interface (both
   inside tmux). At the Pi's own prompt the owner types `chat.sh` and
   `ui.sh` by name (see "The scripts by name"); a command given to ssh
   keeps the full form.

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

- Unit tests, no network and no cost, on a PC (Git Bash or PowerShell):
  `.venv/Scripts/python.exe -m unittest discover -s tests -t .`
  and on the Pi: `.venv/bin/python -m unittest discover -s tests -t .`
  Run both: the Pi has real process groups, curses and bash, and its Python
  (3.13.5) is not the laptop's (3.12).
- `tests/fakes.py` has a fake client that scripts the model's replies
  (`FakeClient`, `reply`, `tool_use`, ...), a piped console and a terminal
  console. `tests/test_wire.py` drives the real SDK over a mock network with
  recorded replies in `tests/fixtures/*.sse`; `tests/record_fixtures.py`
  re-records them (paid, a few cents; it scrubs signatures and ids).
- Tests write only into temp folders, never into the repo or `~/robot-data`.
- Both PCs DO have an `ANTHROPIC_API_KEY` in their environment. So
  `python -m robot.main` on a PC makes real, billed calls. Paid checks
  are done on the Pi; on a PC use the unit tests or `--dry-run`, and set
  `ROBOT_DATA_DIR` to a temp folder so nothing lands in `~/robot-data` there.
- A paid check on the Pi without a terminal: pipe lines in.
  `ssh pi "cd ~/robot && printf 'first\nsecond\n' | .venv/bin/python -m robot.main --model claude-haiku-5-5"`
  Piped lines are echoed, and the end of input ends the conversation.
  `--model claude-haiku-5-5` keeps checks cheap (a whole chat for well under a
  cent); the default Opus chat costs about 7 cents to start (about 14,000
  tokens written to the cache with Meta on, measured on 2026-11-28).
- The instruction of a paid check blocks the tools it has no use for
  (`blocked_tools`: `speak`, `microphone_listen`, `voice_settings`, and
  the shell where it is not needed), and its text says "use no tools"
  where none is meant. On 2026-11-28 a check's child, told to "count
  aloud", spoke through the speakers unplanned.
- What Windows cannot run (bash, tmux, curses, `/proc`) has its tests
  skipped there, so green tests on a PC say nothing about it. Try such
  code on the Pi in a scratch copy BEFORE pushing it (see "Running and
  testing: the details"). When the Pi cannot be reached, the commit and
  the notes say that it is untried. The first `show_window` went out that
  way on 2026-11-27 and failed on the Pi's tmux the next morning.
- A conversation ended by a SPOKEN "bye" powers the Pi off (see
  "Hands-free"), and a Pi that is off stays off until somebody takes its
  power away and gives it back. So:
  - `tests/__init__.py` sets `ROBOT_POWEROFF_COMMAND=true` for every test:
    no test can switch off the machine it runs on. Leave that line alone.
  - A check on the Pi in which anything says "bye" to a hands-free run
    (the speakers included) exports
    `ROBOT_POWEROFF_COMMAND` with a harmless command BEFORE it starts the
    program or its tmux server, for example `touch /tmp/zz-poweroff-asked`.
  - The real `sudo poweroff` is not for a session to try: it ends the
    session's own access to the Pi, and the Pi stays off until the owner
    gives it power again. Then `ssh pi` times out, and so does a deploy:
    what was pushed meanwhile reaches the Pi with the next deploy after it
    is back (as on 2026-11-25, when a docs commit waited that way).
- With autostart on (`bash scripts/autostart.sh status`, see "Starting by
  itself"), every restart of the Pi starts a paid run of the owner's that
  listens to the room and may speak. A piece of work that has to restart
  the Pi for another reason switches it off first and on again after, and
  says so.
- The owner uses the Pi while work goes on. A chat may be open in tmux on the
  socket `robot`, and the windowed interface on `robot-ui` (further
  interfaces, headless ones and the windows of child runs are sessions on
  that socket too). A check must
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
  kill-server`. `ui.sh` takes `ROBOT_SOCKET` the same way, and a run that
  may open a child's window outside tmux gets `ROBOT_CHILD_SOCKET`:
  without it the window's session goes onto the owner's `robot-ui`.
- The webcam is one device, and the owner's runs use it too. A check that
  records or takes a photo can collide with a run that does the same. On
  2026-11-22 a test's recording started in the second in which a run of the
  owner's was taking a photo: `arecord` said "Unable to install hw params"
  and the kernel `usb_set_interface failed (-71)`. The run's photo was
  unharmed, the kernel reset the webcam at its next use, and 24 further
  tries with nothing else going on all worked. An empty `~/robot-data/runs`
  at the start of a check says nothing about the minute after: say
  beforehand that the camera and the microphone are about to be used, keep
  such a check to seconds, and when one fails look at the times of the
  newest files in `~/robot-photos`, `~/robot-sound` and
  `~/robot-data/saved_chats` before blaming the hardware.
- To run a script on the Pi without writing a file there, feed it over stdin:
  `ssh pi "cd ~/robot && .venv/bin/python -" < script.py` or `bash -s`. An
  `ssh` command inside such a script needs `-n`. That is Git Bash's way;
  PowerShell's is in `docs/claude/testing.md`, in the point "On the desktop".
- `--dry-run` prints the exact first request; `--debug` prints every request.
- Paid checks that need saved instructions or skills create them in
  `~/robot-data` with names starting `ZZ ` (instructions) and `zz-` (skills),
  through a small script fed over stdin that uses `robot.instructions` and
  `robot.skills`, and remove them afterwards. The chats and cost-log lines of
  those checks are left in place: they are a true record of what was spent.
- A paid check whose shell commands must not touch the owner's folders (a
  recording, a photo, a file to play) runs the real program with `HOME` set
  to a scratch folder and `ROBOT_DATA_DIR` to the real data folder. The key
  is still found (`.env` is looked for beside the code, not in the home
  folder), the real skills and instructions are used, and the chat and its
  cost are recorded as for any run. Only the `~` of the shell tool leads
  elsewhere: `~/robot-sound` and `~/robot-photos` are then the scratch
  folder's. Done on 2026-11-23 for the `play-sound` skill (see "Sound").
- To check that two runs share the prompt cache, start them within five
  minutes of each other: the second one's first `call 1:` line should show a
  large `cache_read` and a small `cache_write`.
- Some tests start real processes (`test_spawn`, `test_costs`). One such test
  was timing-dependent on a busy Pi and was fixed on 2026-11-16; if a test
  fails once and then passes, find the race instead of rerunning until green
  (running the suite with all four cores loaded brought that one out).
- On the laptop, long heredocs with quotes passed to the Bash tool have
  broken several times, and backslashes in them are rewritten (a `\x11` in a
  heredoc reached the file as the control character itself). Use the Write
  and Edit tools for file content, scripts included. A script for the Pi
  is written to the scratch folder and fed with `<` (it broke again on
  2026-11-28, on a Python heredoc with quotes in it).
- A commit message with double quotes in it does not survive `git commit
  -m` in PowerShell 5.1 on the laptop: the quotes are dropped on the way
  to git, which then takes the words for file names ("pathspec ... did not
  match") and commits nothing (2026-11-26). Write the message to a file in
  the scratch folder and use `git commit -F FILE`.
- The Write and Edit tools turn a `\uXXXX` in the text they are given into
  the character itself. To keep a source file plain ASCII, spell such a
  character as `chr(0x2500)`.
- A check that uses the speakers or the microphone must STOP when
  `~/robot-data/runs` is not empty, not just show it: a run of the owner's
  is in progress then, and the check would play into it or be heard by it.
- A paid check of a run with memory on writes into the owner's memory, and
  one that has the robot `set` its voice changes the owner's voice: give
  such a check a data folder of its own (`ROBOT_DATA_DIR`), or look first
  and put back what was.
- A check that takes the Pi off the network runs detached, puts the Wi-Fi
  back at its end whatever happened, and does not start while a run is in
  progress (see "Getting back on the Wi-Fi").
- An interface that was open before a deploy keeps the old code until it
  has been quit and started again. The deploy that first brings a new step
  to `deploy.sh` does not run it: deploy twice.
- More in `docs/claude/testing.md`: the three kinds of test of the windowed
  interface and how to drive it by hand, PowerShell on the desktop (how a
  script is fed to the Pi there), a job on the Pi that outlasts an ssh
  command, `pgrep -f` over ssh, and trying unfinished work on the Pi in a
  scratch copy.

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
- `robot/hearing.py`: recording through the microphone and sending it to
  xAI's speech-to-text service (see "Hearing"). Standard library only.
- `robot/handsfree.py`: `Segmenter` (cuts what was said out of the
  microphone's sound) and `Ear` (the thread that listens while the robot
  waits). See "Hands-free". Standard library only.
- `robot/memory.py`: what the robot remembers from one run to the next,
  and the call that does the remembering (see "Memory").
- `robot/power.py`: `power_off`, which switches the Pi off after a spoken
  goodbye (see "Hands-free").
- `robot/speaking.py`: having xAI turn a text into a WAV file, and playing
  it (see "Speaking"). Standard library only.
- `robot/meta.py`: Meta tool schemas, `manage_instructions`, `meta_tools`.
- `robot/spawn.py`: `run_instruction` (child runs, and the tmux session
  that shows one with `show_window`).
- `robot/instructions.py`: `RunSettings`, the library, `settings_from_entry`.
- `robot/skills.py`: `SkillStore`, SKILL.md format, `manage_skills`.
- `robot/models.py`: model lists, capability rules, output caps, price tables.
- `robot/costs.py`: per-call cost, the cost log, the in-progress record.
- `robot/history.py`: trimming and repairing the message history.
- `robot/chats.py`, `robot/datastore.py`, `robot/relay.py`, `robot/prompts.py`.
- `robot/tui/`: the windowed interface (see "The windowed interface").
  - `text.py`: cell widths, wrapping, and `EditBuffer`, the text of a text box.
  - `screen.py`: `Screen` (what everything draws on), `CursesScreen`, and
    `KeyParser`. The only module that imports `curses`, and only inside
    `CursesScreen`.
  - `widgets.py`: `Button`, `Checkbox`, `Choice`, `TextField`, `TextArea`,
    `ListBox`, and `Window` (focus, Tab order, Alt letters, the mouse).
  - `dialogs.py`: `MessageBox`, `PickDialog`, `TextDialog`, `ChecklistDialog`.
  - `editor.py`: `InstructionEditor` and its two small windows.
    `skillsui.py`: `SkillsManager`. `memoryui.py`: `MemoriesWindow`.
  - `app.py`: `App` and `MainWindow`, the output pane, and the three classes
    that join a run to the screen (`UiConsole`, `UiInterrupts`, `Runner`).
- `scripts/deploy.sh` (runs on the Pi: pull, pip install, install tmux, set
  up the `robot-wifi` service; its body is in a `main` function so the pull
  can replace the file safely), `scripts/wifi-reconnect.sh` (that service),
  `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`,
  `scripts/child-window.sh` (the window of a child run, see "Meta tools and
  child runs"), `scripts/autostart.sh` (the interface and its run when the Pi starts, see
  "Starting by itself").
- `scripts/pi_photo.py` runs on a PC, not on the Pi: it fetches a photo from
  the Pi and opens it in the PC's viewer (see "Pictures").
  `scripts/pi_sound.py` does the same for a sound recording and plays it
  (see "Sound"); it takes the copying, and the rule about where such files
  may go, from `pi_photo.py`.
- `docs/claude/`: the detailed notes for sessions, one file per topic (see
  "Where the rest is").
- `requirements.txt`: `anthropic==2.8.0`, `python-dotenv==1.2.4`. Pinned on
  purpose: 2.8.0 sends API version 2026-10-21, has no `temperature`
  parameter, sends the key as a Bearer token, and is built on `httpx2`.
- `RandomCommands.txt` in the checkout is the owner's own notes file, not
  part of the program: it is in `.gitignore` since 2026-11-25, on both
  PCs, and is left alone.
- `.venv/` on each PC (gitignored): the same packages, under Python 3.12 on
  the laptop and 3.13.5 on the desktop.
- `.gitattributes`: LF line endings for `*.sh`, `*.conf`, `*.sse`.

## How the agent works: the standing rules

How it works is in `docs/claude/agent.md` and the files of the single
topics (see "Where the rest is"). What follows are the owner's decisions
and the rules that a change must not break. Each is explained in its
topic's file.

- A run is one `Agent` with `RunSettings`, from an entry of
  `agent_instructions.json`. Its system prompt and tool list are built once
  (`Agent._freeze_run`) and do not change during the run: the prompt cache
  and the model's saved reasoning are tied to them. What differs from run
  to run (the "About this run" paragraph, the memory) travels in a second
  system block with no cache marker. Nothing else dynamic goes into the
  system prompt.
- `api.build_request` is the one place a request is shaped, and `api.py`
  the only module that imports `anthropic`. No temperature anywhere.
- The wording of the system prompt (`robot/prompts.py`) was approved by the
  owner: show any proposed change before implementing it. Its first
  paragraph is the owner's own text, kept as given, spelling and line
  breaks included. The same goes for the memory's block and the keeper's
  prompt in `robot/memory.py`. Tool descriptions are model-facing text
  too: treat changes with care.
- The shell tool has NO guardrails by the owner's explicit choice
  (2026-11-15): no confirmation, no allowlist, no blocked commands. Do not
  add any unasked.
- An empty reply is an answer everywhere: it ends a conversation. Do not
  bring back the skipping of empty lines unasked.
- A conversation ended by a SPOKEN "bye", and only that, powers the Pi off,
  with no question asked, at the owner's request (see "Hands-free").
  Hands-free hears whoever speaks.
- `manage_memories` has no `delete` and no `roll_back`, at the owner's
  word. Do not add the two actions unasked.
- Not built, and not to be built unasked: a key that dictates a reply
  (MyAgent's Mike button), and a mouse at the Pi's own screen.
- In the windowed interface the focus is never left on START: a stray
  Enter must not start a run that costs money. The runs that start
  without START are the one `--start` asks for and the one of a headless
  interface (`--headless`, see "A headless interface").
- `curses` is imported in `robot/tui/screen.py` only, inside
  `CursesScreen`. Anywhere else, the tests on Windows stop importing.
- The agent keeps the main thread (its Ctrl-C handling works through
  signals); the interface's screen has a thread of its own.
- Child runs are limited by free memory and by `spawn.MAX_CHILDREN` (8, for
  the whole tree), the owner's figure. A child is always headless and
  always its parent's own process: `show_window` only shows what it
  writes. Do not have tmux start the child.
- A headless interface (`ui.sh --headless`) is an interface of its own
  every time (`h1`, `h2`, ...), never joins one that is running, and
  writes no state file.
- `hearing.py`, `handsfree.py` and `speaking.py` use the standard library
  only. xAI's costs are stated in the tools' results and are not in the
  cost log, which is for Anthropic's calls.

## Where it comes from

- MyAgent is the owner's tkinter agent app, in the folder
  `Claude_Python_Testbed` next to this one on both PCs. Its package cannot
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
  its Apply of an unsaved draft, images, the Mike button that dictates a
  reply, and window colours are not there.
- MyAgent's ways of running unattended, and what they are here:
  `MyAgent.py -l NAME --headless` is `ui.sh -l NAME --headless` (see "A
  headless interface"), and also `python -m robot.main -l NAME --headless`,
  which has no window at all and ends at its first question. Of
  `run_instruction`'s parameters `show_window` is here (a tmux session
  that shows the child's output) and `headless` is not: a robot child is
  always headless. MyAgent numbers its instances by itself (1, 2, 3 in
  the order of starting); here an interface has the name given with
  `--session`.
- Left out on purpose: MyAgent's tkinter code, the safety confirm system,
  other providers, MyAgent's file, document, desktop, browser, mail and MCP
  tools, OneDrive sharing, images, voice input for replies (the Mike
  button and Voice Setup; `microphone_listen` IS here, see "Hearing"), the
  live model listing. MyAgent runs
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
- The code knows two pieces of hardware beyond the Pi itself, and both
  only through the Pi's own programs: a microphone (`arecord`, in
  `hearing.py`) and speakers (`aplay`, in `speaking.py`). Neither is named
  in the code: each is the first device its program lists. No motors,
  sensors or camera are wired into the code. Ask before assuming any
  hardware that is not listed here.
- Attached since 2026-11-20: a Logitech Brio 100 webcam on the Pi's USB
  port: the data port of the Zero 2 W, and since 2026-11-22 the one port of
  the 3 A+ (see "Target device"). As `config.txt` stands, its
  `dtoverlay=dwc2,dr_mode=host` is under `[cm5]` and applies to neither
  board. The
  kernel's `uvcvideo` driver takes it as `/dev/video0` (`/dev/video1` is its
  metadata; the `/dev/video10` and up are the Pi's own codecs, not cameras),
  and its microphone as a USB sound card. It offers YUYV and MJPG up to
  1920 x 1080. Nothing in the repo takes photos: the robot does that with
  the shell tool, told how by its `take-photo` skill, and looks at the file
  with the `view_image` tool. A photo needs nothing
  installed, since an MJPG frame is a JPEG file as it comes:
  `v4l2-ctl -d /dev/video0
  --set-fmt-video=width=1920,height=1080,pixelformat=MJPG --stream-mmap
  --stream-skip=30 --stream-count=1 --stream-to=/tmp/photo.jpg` (the 30
  frames skipped give the camera a second to set its exposure). The user is
  in the `video` group. Photos are personal: never put one in the repo, and
  on a PC keep them out of folders that OneDrive copies (on the laptop
  Pictures is one; the first went to `RobotPhotos` in the user's home folder
  there). `scripts/pi_photo.py` fetches one to `~/RobotPhotos` on either PC
  and makes it viewable on Windows (see "Pictures"). The same goes for
  sound recordings from its microphone: `scripts/pi_sound.py` fetches one to
  `~/RobotSound` and plays it (see "Sound"). The microphone is also what
  the `microphone_listen` tool listens through (see "Hearing").
- Attached since the evening of 2026-11-22: USB-powered stereo speakers on
  the headphone socket of the 3 A+ (see "Sound"). The robot plays files
  through them with the shell tool, told how by its `play-sound` skill, and
  talks through them with the `speak` tool (see "Speaking").
