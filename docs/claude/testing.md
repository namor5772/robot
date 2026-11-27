# Running and testing: the details

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- A race found that way on 2026-11-19, on Windows only (on the laptop):
  `test_without_answers_the_person_at_this_terminal_is_asked` failed once in
  a full run. On Windows a file that another process has open for reading
  can be neither replaced nor removed, and the two sides of a relay folder
  read each other's files all the time, so the stand-in child died in
  `relay.clear`. `relay._while_not_in_use` now tries again for up to two
  seconds on a `PermissionError`. Linux has no such rule; on the Pi the first
  try is the only one.
- On the desktop the Bash tool does not work (see "The two PCs") and the
  PowerShell tool does its job. What was tried there on 2026-11-22, with
  PowerShell 7.7:
  - The unit tests, `ssh pi "..."` and the deploy are typed as they stand in
    this file.
  - PowerShell has no `<`. A script is fed to the Pi with `Get-Content -Raw
    script.sh | ssh pi "tr -d '\r' | bash -s"`, a Python one with `... | ssh
    pi "cd ~/robot && tr -d '\r' | .venv/bin/python -"`. The `tr` takes the
    carriage returns out: PowerShell ends what it pipes with one, and a file
    written on Windows can have one on every line.
  - The `tar` pipe further down works as it stands: Windows has a `tar`, and
    this PowerShell hands bytes from one program to the next unchanged. The
    files arrive as they are in the working tree. With git's `autocrlf` on,
    as it is there, `.py` files have CRLF line ends in the working tree,
    which Python on the Pi does not mind; `.sh`, `.conf` and `.sse` have LF
    through `.gitattributes`.
  - The tool refused one whole command before running it: a remote command
    quoted in it held an `rm -rf`, and the tool's safety check spoke of a
    local `Remove-Item`. Steps that remove something on the Pi go into the
    script that is fed over stdin.
- The windowed interface has three kinds of test:
  - `tests/test_tui_*.py` except `_terminal` run everywhere, the PCs
    included, on a screen that lives in memory (`tests/tui_fakes.py`:
    `FakeScreen`, and `AppCase` with `drive(...)`). A test is a script of key
    names, `typed("text")`, `Check(function)` to look at the screen so far and
    `Until(function)` to wait for the thread that runs the agent. One call of
    `drive` is one whole session: when the script runs out, every open window
    is gone, so a second call starts again at the main window.
  - `tests/test_tui_terminal.py` starts the real program on a pseudo-terminal
    and sends it real bytes. It needs curses, so it runs on the Pi only (8
    tests, about 30 s) and is skipped on Windows. It gives the program an
    empty API key, with which nothing can be sent.
  - `tests/test_launchers.py` runs `chat.sh` and `ui.sh` with a stand-in for
    tmux that only writes down how it was called: which socket, which
    session, which program with which arguments. Nothing is started. bash
    scripts for the Pi, so it is skipped on Windows too (19 tests).
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
  (`FINISHED: ...`). A background loop on the PC asks once a minute
  whether that line is there. The job then survives a dropped connection and
  a PC that sleeps. Rehearse such a job small first, and once with a
  fault put in on purpose: a check that cannot fail proves nothing.
- `pgrep -f name` run over ssh also finds the shell that ssh started for the
  command, because the name is in that shell's own command line. Write the
  pattern so that it does not match itself: `pgrep -f 'zz-cardful[l]'`.
- To try unfinished work on the Pi without touching the checkout, copy the
  working tree to a scratch folder and run it there with the checkout's
  Python: `tar -cf - --exclude=.venv --exclude=.git . | ssh pi "mkdir -p
  /tmp/robot-try && tar -xf - -C /tmp/robot-try"`, then `cd /tmp/robot-try &&
  ~/robot/.venv/bin/python -m unittest ...`. Give it `ROBOT_DATA_DIR` of its
  own. It finds no `.env` there, so it cannot make paid calls. The suite
  skips 4 tests there where the checkout skips 2: two launcher tests need
  the checkout's own Python, and the copy has no `.venv` (their reason says
  so with `-v`).
