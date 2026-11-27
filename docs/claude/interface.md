# The windowed interface

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

`python -m robot.tui`, started through `scripts/ui.sh`. It does what MyAgent's
windows do, as far as a terminal allows: a main window with START, STOP,
Instruction and Skills, an Instruction Editor and a Skills Manager. The agent
underneath is the same code the chat runs; only the console differs.

## A run and the screen

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
- Enter on an empty reply box is an answer, as in MyAgent's dialog and in the
  chat (see "Input, output and Ctrl-C"): it ends a conversation, stops the
  run when the model had asked through `user_prompt`, and at the first
  message of an instruction without text nothing is run. Until 2026-11-19
  the box refused an empty message. Only the reply box sends: Enter with the
  focus elsewhere presses what is focused.
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

## The screen and the keys

- Everything draws on a `Screen`: `put`, `fill`, `box`, clipped at the edges.
  `CursesScreen` is the real one. Tests use `FakeScreen`, a grid in memory,
  because Python on Windows has no curses. Keep curses out of every other
  module, or the tests on Windows stop importing.
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

## The windows

- A `Window` holds widgets; the order they are added is the Tab order. In a
  label, `&` marks the Alt letter (`"&Save"`). Letters are unique per window.
- A dialog is shown with `App.run_modal(window)`, which loops until the
  window closes and returns its result, so asking a question is one line
  (`if self.app.confirm(...)`). The run's events are taken in on every turn of
  every such loop.
- The focus is never left on START: Enter presses the focused button, and a
  stray Enter must not start a run that costs money. It starts on Instruction
  (as in MyAgent) and goes to the output pane when a run ends. The one run
  that starts without START is the one `--start` asks for (see "Starting
  by itself").
- START empties the output pane before the run begins
  (`OutputBuffer.clear`, called from `MainWindow.run_started`), as MyAgent
  empties its display. Until 2026-11-19 a run's lines were added under the
  earlier run's; the owner asked for MyAgent's behaviour. A START that is
  refused (no such instruction) leaves the pane as it was. The earlier run's
  lines are in its saved chat.
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
- `~/robot-data/tui_state.json` holds the instruction in use and the six
  boxes of the bottom row (five display boxes and Hands-free) (`tui_state_NAME.json` for a copy started with a session
  name). Nothing a run needs is in it.
- The Tools dialog lists `editor.TOOL_NAMES`: the nine ordinary tools first,
  the five Meta tools last, then any blocked name the program does not know
  (one copied in from MyAgent, or one of a tool since removed), so that such a block is not lost on saving.
  The README's tool table is in the same order. Nothing marks where the Meta
  group starts. `meta` in the top row stands for that group of five.
- A tick in that dialog says only "not blocked". With the form's Meta box
  clear, the five Meta tools (`editor.META_TOOL_NAMES`) are therefore shown
  as `[-] name  (needs Meta)` and are locked (`ChecklistDialog`'s `locked`):
  until 2026-11-20 they showed ticked, which the owner took, fairly, for
  "offered". They are not shown unticked, because a cleared box is saved as
  a block, and the tools would then stay blocked after Meta is ticked. A
  block already set on one of them is kept as it is. The dialog goes by the
  box as it is on the form, saved or not.

## Starting by itself

- Since 2026-11-24, at the owner's request: when the Pi starts, the
  interface comes up on the Pi's own screen and the run of its instruction
  begins, with nothing typed. The owner's conditions: it must still be
  joinable over ssh, and after "bye" another instruction must be
  startable there. So it is the ordinary interface, started once, and
  nothing starts a second run. (The next day the owner had a SPOKEN "bye"
  power the Pi off, see "Hands-free": to end a run and go on in the same
  interface, the word is said as "stop", or "bye" is typed.)
- Three parts:
  - `python -m robot.tui --start`: `App(autostart=True)` calls `start()`
    once, on the first turn of the loop in which the main window is in
    front. It is the one way a run starts without START being pressed;
    without the option nothing has changed. `ui.sh --start` passes it on,
    and a second `ui.sh` that joins a running interface ignores it, as it
    ignores every argument.
  - `scripts/autostart.sh`: `on`, `off` and `status` are the switch, a
    file `autostart_on` in the data folder. `boot` is what the service
    runs, as root: nothing when the switch is off; else it waits for the
    clock to be set (`timedatectl show -p NTPSynchronized`) and for a name
    to resolve, 180 seconds at most and then starts all the same, and
    runs `openvt -f -c 8 -s -- sudo -H -u USER env TERM=linux LANG=... bash
    scripts/ui.sh --start`. USER is the owner of the checkout. `LANG` is
    read from `/etc/default/locale`: a service has no locale, and the
    windows' lines need UTF-8. It writes what it did to
    `/var/log/robot-autostart.log`.
  - `deploy.sh` (`install_autostart_service`) writes
    `/etc/systemd/system/robot-autostart.service` and enables it. It never
    starts or restarts it: a deploy must not put an interface on the
    screen. `Type=oneshot` with `RemainAfterExit=yes`, and
    `KillMode=process` so that stopping the service leaves the interface
    alone. The first deploy with this step did not run it (see "Getting
    back on the Wi-Fi": deploy twice).
- Which instruction, and whether it listens, is whatever the interface
  remembers (`tui_state.json`): the last instruction used and the boxes as
  they were. "Used" means chosen with *Use* in the Instruction Editor
  (`App.set_instruction` saves the file there and then), not run: so the
  way to change what the Pi comes up with is to choose another one once
  (the owner asked how on 2026-11-25). A run from the chat, or a check's
  run, changes nothing in that file. With Hands-free ticked the Pi comes up listening. An
  instruction that has been deleted since falls back to `Default`, as it
  does at any start of the interface.
- The same console 8 and the same command as putting the interface on the
  screen by hand (see "Several screens, several interfaces"); `sudo chvt
  1` gives the screen back to console 1.
- With no screen attached to the Pi it works as well: the owner started
  the Pi that way on 2026-11-25, with no keyboard either, used the robot
  and ended with a spoken "bye", and reported "All the above changes work
  well, the Pi is now powered off." Nothing in it needs a monitor: the
  text consoles are there without one, and the interface is joined over
  ssh as ever. No session looked at the Pi during that start, so the size
  console 8 has without a monitor is still not known (80 x 25 is the
  guess; the interface needs 72 x 18, and takes the size of the ssh
  terminal once somebody joins). If a start ever fails that way, read
  `/var/log/robot-autostart.log` first.
- `ROBOT_AUTOSTART_CONSOLE`, `ROBOT_AUTOSTART_WAIT`, `ROBOT_AUTOSTART_LOG`
  and `ROBOT_AUTOSTART_ARGS` (more words for `ui.sh`, as `--session zzt`)
  are for checks, with `ROBOT_SOCKET` and `ROBOT_DATA_DIR` passed on.
- Tried with a real restart of the Pi that evening, the switch on and
  nothing of the owner's running: the Pi started at 23:43:54, the log says
  "started the interface for ... on console 8, after waiting 20 s" at
  23:44:41, and half a minute later the screen showed console 8 with the
  interface at 240 x 67 in proper line characters, the owner's
  `InterfacesTest` in the top row, a run in progress
  (`~/robot-data/runs` held its file), one `arecord`, and "Hearing
  you..." in the bottom line. So 47 seconds from the start of the Pi to a
  run that listens. The switch was left on, as the owner had asked for
  the feature.
- No rehearsal on a console of the check's own came before it: the owner
  was using the Pi, and the script always puts the screen on its console.
- `tests/test_autostart.py` (20 tests, 16 of them bash and skipped on
  Windows): the interface's `--start` on the screen in memory, the script
  with stand-ins for `openvt`, the clock and the network, and the service
  `deploy.sh` writes.

## A headless interface

- Since 2026-11-28, at the owner's request ("add the headless command-line
  flag to ui.sh like MyAgent"): `ui.sh -l "Name" --headless`. MyAgent's
  flag hides the main window, leaves its dialogs, never writes the state
  file and closes the program when the loop ends. Here that is:
  - `python -m robot.tui --headless`: `App(headless=True)`. The run starts
    by itself (it counts as `--start`), `save_state` does nothing, and
    `_run_ended` sets `quitting`, so the loop ends with the run. The
    program's exit code is 1 when the run ended in `error`, as the
    headless chat's is, and 0 otherwise.
  - `ui.sh --headless`: starts the session detached
    (`ROBOT_TMUX_DETACHED=1`), so nothing is put on the caller's screen and
    no terminal is needed (`ssh pi "bash ~/robot/scripts/ui.sh -l Name
    --headless"` works without `-t`, and so would a scheduled job).
    Without `--session` it takes the first of `h1` to `h99` for which tmux
    has no session: every headless start is an interface of its own, as
    every headless MyAgent is an instance of its own. With `--session
    NAME` and that session running it refuses (exit 1) and does not join.
  - `chat.sh --inside-tmux` leaves at once for `robot.tui` with
    `--headless` among its arguments, whatever the exit code: otherwise a
    failed run would leave "Ended (exit code 1). Press Enter to close."
    in a session nobody looks at, for ever.
- Asked BEFORE anything is started (`headless_check`, reached through
  `python -m robot.tui --headless --can-start ...`, which needs no
  terminal and exits 2 with the reason): is the instruction there, and
  has it a text. Inside the detached session nobody would read why
  nothing ran, and an instruction with no text would wait for its task
  for ever. With no `-l` the instruction is the one that session
  remembers; an `hN` session remembers none, so there `-l` is needed. The
  program itself makes the same check when started with `--headless`
  alone. `ui.sh` calls `.venv/bin/python` for it, about a second on the
  Pi.
- An instruction with Convo on is started, with a note: after each reply
  it waits for a message until somebody joins. That is MyAgent's
  behaviour as well (its docs say to save the scheduled variant with
  Convo off). A `user_prompt` question waits the same way. Nothing ends a
  headless interface that waits: no timeout was built.
- It is a whole interface, so it can be joined (`ui.sh --session h1`),
  watched, answered and stopped. The bottom line shows `Headless: closes
  when the run ends` (`HEADLESS_NOTICE`) whenever there is no other
  message: the status of a `--start` is wiped by the first question, and
  somebody who joins later must still be told.
- Not written for a headless copy: the state file, also when a box is
  ticked or another instruction is chosen with Use while it runs. So an
  `hN` always starts with the default boxes, Hands-free off. A headless
  start under a name that HAS a file (`--session 2 --headless`, or
  `--session 1`) reads it: with the first interface's file that means the
  remembered instruction and, as things stand on the Pi, Hands-free on.
- An instruction deleted between the check and the start: `start()` shows
  no message box in a headless copy (nobody would close it) and quits
  with the outcome `error`.
- Memory: a headless interface is an interface, about 80 MB, where the
  headless chat (`robot.main --headless`) is one too. The difference
  between the two is what happens at a question: the chat ends, the
  interface waits and can be joined.
- Tests: `tests/test_headless_ui.py`. The program on the screen in memory
  (6), `headless_check` and `main` with `--can-start` (7), and `ui.sh`
  with the stand-in tmux and the real program for the check (6, skipped
  where the checkout has no `.venv/bin/python`: Windows, and a scratch
  copy unless `.venv` is linked into it).
- Tried on the Pi on 2026-11-28 in a scratch copy, on the socket `zz-ui`
  with a data folder of its own. There is no key in a scratch copy, so
  the run ended in `error` at once, which is the path that used to leave
  a session behind: "ZZ Nope" and an instruction with no text were
  refused with exit 2 and their reason; a start said "Started as the
  interface 'h1'", a second beside it took `h2`; both sessions and the
  tmux server were gone seconds later, and no `tui_state` file was
  written.

## Several screens, several interfaces

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
  the PC's terminal that reports them. `gpm` (not installed) would not
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
- With no keyboard at the Pi (the 3 A+'s one USB port has the webcam), an
  ssh login puts something on its screen with `openvt`: `sudo openvt -c 8
  -s -- sudo -u $USER env TERM=linux bash ~/robot/scripts/ui.sh` starts or
  joins the interface on console 8 and switches the screen to it, and `tmux
  attach -t NAME` in place of the script shows any tmux session. Tried on
  2026-11-23, at the owner's question, on sockets of the check's own:
  - `TERM=linux` has to be given: the command inherits the ssh terminal's
    type. Console 8, because 2 to 6 ask for a login when they are shown
    (see above) and nothing uses 7 and up.
  - tmux lists the client on a pty, not on `/dev/tty8`: this sudo runs its
    command in a pty of its own and passes everything on, the console's
    size too, also when that changes.
  - A second terminal that joined (110 x 30, as over ssh) opened the Help
    window, and console 8 showed it: one program, two screens, as above.
    The window took the size of the terminal used last and sat in the top
    left corner of the screen's 240 x 67.
  - `sudo setfont -C /dev/tty8
    /usr/share/consolefonts/Uni3-TerminusBold32x16.psf.gz` doubles the font
    on that console alone: it had 33 rows of 120 columns then, console 1
    still 67 of 240, and the client followed.
  - `sudo chvt 1` puts the screen back on console 1, and `sudo deallocvt 8`
    frees console 8 once nothing runs on it. `sudo fgconsole` says which
    console the screen shows.
  - A session cannot see the screen, but it can read it. `sudo cat
    /dev/vcs8 | fold -w 240` is the text on console 8, row by row (the
    width is the console's own), with other bytes for what is not ASCII.
    `/dev/vcsu8` has every cell as four bytes of Unicode: read that way,
    the interface's frame was the proper line characters. Started through
    `sudo` like this, the interface had the login's `LANG`, `TERM=linux`
    and the user's home folder.
  - That day console 1 held a `bash` of the owner's own login, from before
    the keyboard's receiver came out. Nothing can type into it without a
    keyboard, and the tries left it alone.
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
    all. The tests caught it; a Windows PC cannot run the program to show it.
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
