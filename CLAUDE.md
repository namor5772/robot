# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot. It is developed
on the owner's two Windows PCs, a laptop and a desktop (see "The two PCs"), and
runs on a Raspberry Pi. Since 2026-11-16 the program is a terminal port of the
owner's MyAgent harness (see "Where it comes from").
Since 2026-11-18 it has two faces: the line-by-line chat (`python -m
robot.main`) and a windowed interface drawn with curses (`python -m robot.tui`,
see "The windowed interface"). Since 2026-11-20 it sees (a webcam and
`view_image`), and since 2026-11-23 it hears speech and talks
(`microphone_listen` and `speak`, through xAI's speech services).

## Target device

- Raspberry Pi 3 Model A+ since the evening of 2026-11-22: 512 MB RAM (about
  415 MB usable), 4 cores at up to 1.4 GHz. Until then a Raspberry Pi Zero
  2 W: the same memory, 1.0 GHz. The owner moved the SD card from the one
  board to the other and changed nothing else. What the move showed:
  - The card started on the other board as the same machine: same name, same
    keys, same user, checkout and data as they were, `ssh` without a
    warning. cloud-init ran its stages and set nothing up again (it is the
    same instance, see the card's own move below).
  - It joined the Wi-Fi by itself, at the second start of that evening
    within a minute. The saved networks are tied to `wlan0`, not to a
    radio's own address. The other board has another radio, though, and the
    router gave it another IP address: `ssh pi` timed out on the PC and
    `ssh pi-local` worked at the first try (see "Reaching the Pi").
  - Memory is the same (415 MB, and 414 MB of compressed swap), so the
    memory figures in this file hold, and with them the rule for child runs.
    Times do not: importing the SDK takes 10 s here (15 on the Zero), and
    the test suite 70 s in the checkout (80). What this file dates before
    that evening was measured on the Zero 2 W.
  - The radio has both bands here: `iw list` shows 13 channels from
    2,412 MHz and 19 from 5,180 MHz, and a scan found 10 networks on the one
    band and 6 on the other. The Zero had the first band only. The Pi stayed
    on the network and the band it was on, with power saving off as before.
  - The board has ONE USB port, a full-size one, and it is a host port as
    built (`lsusb -t`: a `dwc_otg` root hub with one port). The webcam and
    the keyboard's receiver cannot both be in it without a hub: that evening
    the receiver was in it at the start and the webcam from 21:19 (`sudo
    dmesg -T | grep usb`).
  - The webcam is `/dev/video0` as before. Its microphone is still the sound
    card NAMED `B100`, but its number went from 1 to 2: this board has a
    headphone socket, which is card 0 (`bcm2835 Headphones`). The skills
    name the card, so they work unchanged: all four commands of
    `take-photo` and `record-sound` were run on this board, and so were two
    runs of the owner's with a photo and a recording.
  - That headphone socket is a way to make sound that the Zero did not
    have. Later that evening the owner put speakers on it (see "Sound").
  - `vcgencmd get_throttled` said `0x80000` from the first look, 37 minutes
    after the start: bit 19, "soft temperature limit has occurred". The
    limit is 60 degrees by default, where the firmware lowers the clock
    (from 1.4 to 1.2 GHz; the documentation's text names the 3 B+, and its
    `temp_soft_limit` entry says "3A+/3B+ only"). That evening it was not
    seen to happen: 44 to 46 degrees idle, 50.5 at the hottest during the
    test suite, the clock at 1,400 MHz. No bit for low voltage was set.
  - It was seen on 2026-11-23, with all four cores loaded (`sha256sum
    /dev/zero` four times): from 41 degrees the Pi was at 60 within 20
    seconds. There bit 3 came on ("soft temperature limit active",
    `0x80008`), `vcgencmd measure_clock arm` went from 1,400 to 1,200 MHz
    and the core's voltage from 1.365 to 1.26 V. For the 20 seconds
    watched it switched on and off about once a second and the temperature
    stayed at 59 to 60; with one core loaded it was back at full speed at
    58. So one busy half minute is enough to set bit 19. Stronger
    throttling, by the documentation, comes between 80 and 85 degrees on
    every model, 85 being the limit: not reached here. The kernel's own
    trip point is 110 degrees (`critical`).
- 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13.5, no tkinter
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API keys: `~/robot/.env` (`ANTHROPIC_API_KEY=...`, and since 2026-11-23
  `XAI_API_KEY=...` for hearing and speaking, see "Hearing" and "Speaking"). Never commit it; `.env` is
  in `.gitignore`.
- The program's data: `~/robot-data` (outside the checkout on purpose).
- Passwordless sudo is enabled for `grobliro` (the user set it up on
  2026-11-15 in `/etc/sudoers.d/010_grobliro-nopasswd`).
- `/tmp` is a RAM disk. Importing the Anthropic SDK takes about 10 s (15 s
  on the Zero 2 W) and one process uses about 77 MB.
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
  kernel's own font and no mouse service. The screen is the same on the
  3 A+; the keyboard's receiver shares that board's one USB port with the
  webcam (see above).

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
  PowerShell's is in the point "On the desktop" below.
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
- A race found that way on 2026-11-19, on Windows only (on the laptop):
  `test_without_answers_the_person_at_this_terminal_is_asked` failed once in
  a full run. On Windows a file that another process has open for reading
  can be neither replaced nor removed, and the two sides of a relay folder
  read each other's files all the time, so the stand-in child died in
  `relay.clear`. `relay._while_not_in_use` now tries again for up to two
  seconds on a `PermissionError`. Linux has no such rule; on the Pi the first
  try is the only one.
- On the laptop, long heredocs with quotes passed to the Bash tool have
  broken several times, and backslashes in them are rewritten (a `\x11` in a
  heredoc reached the file as the control character itself). Use the Write
  and Edit tools for file content, scripts included.
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
- The Write and Edit tools turn a `\uXXXX` in the text they are given into
  the character itself. To keep a source file plain ASCII, spell such a
  character as `chr(0x2500)`.
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

## State on 2026-11-18

- The instruction library on the Pi holds `Default` (Opus, Medium, Convo on,
  Meta on) and `Zero state chat` (Opus, Medium, Convo on, Meta off, no text).
  The owner moved both from Low to Medium that evening, in the Instruction
  Editor.
- The Pi had two skills on that day, both made by the owner in chats, in
  `~/robot-data/skills`:
  - `robot-identity` (enabled, so its text is in every run's system prompt):
    the robot's name and one sentence on what it is.
  - `wifi-monitor` (on demand, fetched with `get_skill`): describes a Wi-Fi
    monitor the robot set up on 2026-11-18. That monitor is not part of this
    repo: a bash loop in `~/wifimon` that pings the gateway every 10 s, logs
    each change to `~/wifimon/wifi.log`, and starts at boot from the user's
    crontab.
- A third skill since 2026-11-20, `cpu-temp` (on demand), made at the owner's
  request to stand in for the removed `get_cpu_temperature` tool: it gives
  the model the one shell command that prints the CPU temperature the way
  the tool did ("45.1 degrees Celsius"), and says when to run it. It was
  created with a script fed over stdin that calls `manage_skills`. It was
  made enabled, and the owner had it set to on demand the same day: a
  reading now takes a `get_skill` call and then the shell command (three
  model calls in all, where the tool took two). It needs `run_shell_command`: an instruction
  that blocks that tool cannot read the temperature.
  - Its one sentence "for scale" gives the board's own figures. Since
    2026-11-23, at the owner's request, it says that the 3 A+ starts to
    slow down at 60 degrees, its clock dropping from 1.4 to 1.2 GHz
    (measured, see "Target device"), and further from 80, with 85 as the
    limit (the documentation). Until then it said 80, as on the Zero 2 W.
  - The change was one line, made through `manage_skills` with a script
    fed over stdin that left the rest as it was, and tried with a paid
    question on Haiku ("How hot are you right now, and is that hot for
    you?"): a reading of 45.1 degrees, "comfortably cool", and that the
    clock does not slow down until about 60.
- A fourth skill since 2026-11-20, `take-photo` (on demand), made the same
  way at the owner's request: one shell command that takes a 1920 x 1080
  photo with the webcam (see "Conventions") and saves it as
  `~/robot-photos/photo_<date>_<time>.jpg` on the Pi, printing "saved PATH"
  or "no photo". Its second step is the `view_image` tool (see "Pictures"),
  with the path the command printed: that is how the robot sees. The skill
  tells the model to describe only what it has looked at, and to take a new
  photo to see what is in front of it now. Its first version, from before
  that tool existed, said that the robot could not look at photos.
- The owner's instruction `WebcamTest` ("Take a photo and tell me what you
  see", Sonnet 5.5, with `take-photo` and `cpu-temp` enabled for its runs)
  was run on 2026-11-20: a photo, `view_image`, and a description that
  matched the picture, in three calls for $0.04.
- A fifth skill, `record-sound` (enabled, so its text is in every run's
  system prompt), was on the Pi on 2026-11-22: one shell command that
  records with the webcam's microphone (see "Sound") and saves
  `~/robot-sound/sound_<date>_<time>.wav` on the Pi, printing "saved PATH"
  with the length and size, or "no recording". It tells the model that it
  cannot listen to a recording, and never to describe or guess what one
  holds; since 2026-11-23 it sends the model to `microphone_listen` for
  speech (see "Hearing"). It also has two commands that take a photo and record in
  one go (see "Sound").
- A sixth skill since 2026-11-23, `play-sound` (on demand), made at the
  owner's request with a script fed over stdin that calls `manage_skills`:
  one shell command that plays a WAV file through the speakers on the
  headphone socket (see "Sound"), printing "played PATH in N seconds" or
  "nothing played" with the reason. It tells the model that it cannot hear
  what it plays, and that "played" only means that the sound was sent.
  - `WebcamTest` carries a skill list of its own, and a skill made after
    such a list was saved is off in that instruction's runs. So the skill
    was added to that list as enabled, through `manage_instructions`. That
    was not asked for in so many words: the owner was told.
  - The three other instructions with a list of their own were left alone.
    The skill is off in their runs, and by the code such a run says so in
    a warning at its start, as for any skill its list does not name.
- Because one skill is on demand, every run now also offers `get_skill`.
- `.venv/bin/python -m robot.main --skills` and `--list` on the Pi show the
  current skills and instructions; check there instead of trusting this list.
- 1,500 tests pass (counted on 2026-11-24, on the laptop and on the Pi).
  On the Pi 2 are skipped, on Windows 51, among them the 7 of hands-free
  at the chat's prompt (they need `select`), the 13 of the Wi-Fi
  service (bash), the 8 real-terminal tests (they need curses), the 19
  launcher tests (they need bash) and 3 that build a real tree of child runs
  (they need the kernel's list of processes). `tests/test_spawn.py` starts real
  processes and is the slow one on the laptop, where starting and stopping a
  process takes a second or so: about a minute there, 12 s on the Pi (the
  Zero 2 W). The whole suite takes 35 s on the desktop, and on the Pi 80 s
  on the Zero 2 W and 70 s on the 3 A+.
- The windowed interface was added on this day. Its state is in
  `~/robot-data/tui_state.json`. The owner used it the same evening, over SSH
  from the laptop and at the Pi's own screen.
- On 2026-11-19 the Pi moved from its 16 GB card to a 32 GB one (see "Target
  device"), and the owner ran three interfaces at once at its own screen.
- On 2026-11-22 the Pi was put on another Wi-Fi network (see "Getting back on
  the Wi-Fi"), and the desktop became the second PC the repo is worked on
  from (see "The two PCs"). In the evening of that day the SD card went from
  the Pi Zero 2 W into a Raspberry Pi 3 Model A+ (see "Target device").
- Two tools use hardware since 2026-11-23: `microphone_listen` (the
  webcam's microphone, see "Hearing") and `speak` (the speakers, see
  "Speaking"). There is none for anything else. The one there was before,
  `get_cpu_temperature`, was removed on 2026-11-20 at the owner's request: the model reads the sensor
  with the shell tool when asked (`/sys/class/thermal/thermal_zone0/temp`,
  or `vcgencmd measure_temp`). An instruction that still has the name in its
  `blocked_tools` is unharmed: the Instruction Editor keeps a blocked name it
  does not know.

## Getting back on the Wi-Fi

- The Pi's network is run by NetworkManager (`nmcli`). Its saved Wi-Fi
  networks all connect automatically; the one in everyday use has the
  highest priority. `nmcli connection show` on the Pi lists them: they are
  not named here.
- NetworkManager rejoins a saved network by itself when it sees it again. But
  it can give up: on the night of 2026-11-19 the network went away and came
  back several times, and from 23:26 the Pi stayed off it until the owner
  restarted the Pi in the morning. Why is not known: the Pi keeps no log
  across restarts. A likely cause is a join that fails at the wrong moment,
  after which NetworkManager waits for somebody to connect by hand.
- So since 2026-11-20 a service, `robot-wifi`, is that somebody
  (`scripts/wifi-reconnect.sh`, run as root by systemd, started with the Pi).
  Every 30 s it reads `wlan0`'s state. Connected or connecting: nothing, not
  even a scan. Off the Wi-Fi at one look: NetworkManager gets its own go. Off
  at the next: it scans, and when a saved network that connects automatically
  is in range (highest priority first) it runs `nmcli connection up` for it.
  Ten failures in a row restart NetworkManager, at most once an hour. Nothing
  in range is said once and waited out.
- The script names no network (the repo is public). Its log is
  `/var/log/robot-wifi.log`, events only, cut to its newer half at 200 KB.
- `deploy.sh` sets the service up (`install_wifi_service`): it writes
  `/etc/systemd/system/robot-wifi.service`, whose text is in `deploy.sh`
  because it names the checkout's folder, enables it, and restarts it on
  every deploy so that it runs the script as it is now. A failure there only
  warns. The deploy that first brings a new step to `deploy.sh` does not run
  it: bash has the old script in memory by then. Deploy twice.
- Tried for real on 2026-11-20 with a detached job (see "Running and
  testing"): `sudo nmcli device disconnect wlan0` leaves the Pi as
  NetworkManager is when it has given up. With the service stopped it stayed
  off for the 100 s that were watched; once the service was started it was
  back after 34 s. `tests/test_wifi_reconnect.py` runs the script against a
  stand-in for `nmcli` (13 tests, bash, so skipped on Windows).
- Such a check takes the Pi off the network for minutes. It must run
  detached, must put the Wi-Fi back by hand at its end whatever happened, and
  must not start while a run is in progress (`~/robot-data/runs` holds a file
  then).
- Until 2026-11-22 only the network in everyday use had ever been joined. The
  Pi also has two saved profiles for a second network (one had a wrong letter
  in the network's name until 2026-11-20), and a join tried with each that day
  failed before any password was looked at: the access point did not answer
  the Pi's request to authenticate ("Authentication ... timed out", then
  NetworkManager's "no-secrets"). It announces WPA2 with WPA3 and Wi-Fi 6.
  The cause is not known and may lie in the access point's settings. Left to
  connect automatically, both profiles were tried and failed over and over
  whenever the first network was away. So the owner had automatic connecting
  switched off for the two of them on 2026-11-20 (`nmcli connection modify
  NAME connection.autoconnect no`): neither NetworkManager nor `robot-wifi`
  tries them now, and the Pi waits for the first network. Once that second
  network can be joined, `connection.autoconnect yes` brings them back.
- That makes the opening of this section out of date in one point: not all
  saved Wi-Fi networks connect automatically any more.
- That second network was joined on 2026-11-23, on the 3 A+, and the cause
  was in the Pi's profile, not in the access point: the profile had
  protected management frames switched off (`802-11-wireless-security.pmf`
  was `1`, "disable"). An access point that announces WPA2 with WPA3 wants
  them at least offered. With the setting at its default (`sudo nmcli
  connection modify NAME 802-11-wireless-security.pmf 0`) the same profile,
  with the password it already held, joined at the first try, on 5 GHz.
  - What the refusal looked like in `sudo journalctl -u wpa_supplicant`:
    `CTRL-EVENT-ASSOC-REJECT ... status_code=16` a fraction of a second
    after each "Trying to associate", five times over, and a line "MBO:
    Disable MBO/OCE due to misbehaving AP not having enabled PMF".
    NetworkManager then asked for a password ("no-secrets"), which
    misleads: no password had been looked at.
  - Only one profile for that network was left by then. It connects
    automatically again, with priority 0, so the network in everyday use
    (10) still wins where both are in range. Three profiles are saved.
  - It was done with no keyboard at the Pi: the Pi and the laptop were both
    on the everyday network, and a detached job (see "Running and testing")
    tried the profile, wrote down what happened and went back to that
    network, so that its log could be read over ssh. A join that needs a
    password typed can go the same way: `ssh -t pi "sudo nmcli --ask device
    wifi connect NAME"`, where the session freezes once the Pi changes
    network.
  - PowerShell 5.1 on the laptop puts a byte-order mark in front of a
    script piped to `ssh` (`bash: line 1: ...cat: command not found`).
    There the script is fed with Git Bash's `<`.
- A network the Pi has never joined is added at its own console (keyboard
  and screen), which needs no network: `sudo nmcli device wifi list --rescan
  yes` shows what the Pi sees, and `sudo nmcli --ask device wifi connect
  "NAME"` joins one, asking for the password without showing it (`sudo
  nmtui` does the same with menus). The Zero 2 W's radio had the 2.4 GHz
  band only (`iw list` showed one band), so a network sent on 5 GHz alone
  was not in that list; the 3 A+ has both bands (see "Target device"). The
  owner did this on 2026-11-22, on the Zero 2 W, at a router the Pi had
  never seen.
- The profile made that way connects automatically, with priority 0; the first
  network has 10 and so wins where both are in range. Four profiles are
  saved now: these two, and the two that do not connect automatically. Power
  saving is off on the new network as well, the setting being for every
  network. `robot-wifi` did as it should that morning: with no network it
  knew in range it said so once and waited, and it noted the join. The
  robot's own monitor reads the gateway from the routing table, so it
  follows the Pi to another network.
- The Pi has no clock of its own. Started with no network, it goes on from
  about where its clock stood when it was last shut down, until a network
  gives it the time: on 2026-11-22 it started at 06:27 thinking it was 20:09
  on the 20th, and was put right at 06:48, on joining. What `robot-wifi`,
  the monitor and the journal wrote in between carries the old date. `sudo
  journalctl -b | grep timesyncd` shows when the clock was set, and `uptime
  -s` when the Pi really started.
- The Wi-Fi monitor the robot made (`~/wifimon`, see "State on 2026-11-18")
  is separate and only writes down changes: it pings the gateway, so its log
  also shows short losses during which the Pi never left the network.
- Wi-Fi power saving is off since 2026-11-20, at the owner's request. It is a
  setting of the Pi, not of the repo:
  `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` holds `[connection]`
  and `wifi.powersave = 2` (2 is NetworkManager's "disable"), for every
  network, read with `sudo nmcli general reload conf`. NetworkManager applies
  it each time a network is joined; `sudo iw dev wlan0 set power_save off`
  did it at once, without leaving the network. Checked: switched on again by
  hand, then the network joined afresh, and `iw dev wlan0 get power_save`
  said off. A card written from an image older than that day does not have
  the file.
- What it changed in 40 pings to the gateway, a quarter of a second apart:
  14 ms on average with it on, 9 ms with it off, none lost either way. So
  the short losses in the monitor's log were not shown to come from power
  saving; whether there are fewer of them now is for that log to say.

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
- `robot/speaking.py`: having xAI turn a text into a WAV file, and playing
  it (see "Speaking"). Standard library only.
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
- `scripts/deploy.sh` (runs on the Pi: pull, pip install, install tmux, set
  up the `robot-wifi` service; its body is in a `main` function so the pull
  can replace the file safely), `scripts/wifi-reconnect.sh` (that service),
  `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`.
- `scripts/pi_photo.py` runs on a PC, not on the Pi: it fetches a photo from
  the Pi and opens it in the PC's viewer (see "Pictures").
  `scripts/pi_sound.py` does the same for a sound recording and plays it
  (see "Sound"); it takes the copying, and the rule about where such files
  may go, from `pi_photo.py`.
- `requirements.txt`: `anthropic==2.8.0`, `python-dotenv==1.2.4`. Pinned on
  purpose: 2.8.0 sends API version 2026-10-21, has no `temperature`
  parameter, sends the key as a Bearer token, and is built on `httpx2`.
- `.venv/` on each PC (gitignored): the same packages, under Python 3.12 on
  the laptop and 3.13.5 on the desktop.
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
- Its first paragraph is the owner's own text since 2026-11-24: four lines
  that give the robot its name and its character, typed by the owner and
  put in as given, spelling and line breaks included (the other paragraphs
  are wrapped at 78 columns; these lines are not). It took the place of
  "You are the brain of a small robot. You run as a program on a Raspberry
  Pi 3 Model A+ ... The person talking to you is typing at a keyboard
  connected to the robot, or over SSH."
  - So the fixed text no longer says what the robot runs on, nor that it
    is a robot. The second paragraph still says "answer about this
    Raspberry Pi", and the skills and the tool descriptions name the Pi.
    The owner was told and asked for the replacement as it is.
  - The same sentences are in the owner's `robot-identity` skill, which is
    enabled, so a run gets them twice. The skill is the owner's: left
    alone.
  - Nothing in the fixed text names the board's model any more. Until then
    it did, and went on saying "Zero 2 W" from the evening the SD card
    moved (see "Target device") until the next morning. When the card
    moves to another board, what is left to look at is what the skills on
    the Pi say about it: the `cpu-temp` skill's "this Pi starts to slow
    itself down at 80 degrees" was the Zero 2 W's figure (see "State on
    2026-11-18").
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

- Always: `run_shell_command`, `get_current_datetime`, `view_image` (see
  "Pictures"), `user_prompt`, server-side `web_search`
  (`models.web_search_tool`: `web_search_20260209`, `max_uses` 5; its
  definition alone is about 6,000 tokens of every request).
- `microphone_listen` where `arecord` exists and `XAI_API_KEY` is set (see
  "Hearing"), and `speak` with `voice_settings` where `aplay` exists and
  the key is set (see "Speaking"). On a PC none of the three is ever
  offered.
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

### Pictures

- `view_image` (in `tools.py`, since 2026-11-20, at the owner's request) is
  the one way a picture reaches the model. Its result is not text but a list
  of two blocks: a line naming the file, and an `image` block with the
  file's bytes in base64. `Agent._run_tool` passes a list on as the
  `tool_result`'s content. The API takes that (checked on Haiku with SDK
  2.8.0; no beta header).
- The kind of picture is read from the file's first bytes, not from its
  name: JPEG, PNG, GIF, WebP. A file over `MAX_IMAGE_BYTES` (3.5 MB) is
  refused with the reason, because the API's limit is 5 MB after encoding.
  A path may be absolute, start with `~`, or be relative to the home
  folder, where the shell tool also starts. Nothing is resized: there is no
  image library on the Pi, and none is wanted (see "Conventions").
- A picture is billed by its pixels. A 1920 x 1080 photo was about 2,800
  input tokens on Haiku and on Sonnet 5.5. It stays in the history, so every
  later call of the run carries it (read from the cache).
- Three places must not treat it as text, and do not: the saved chat's
  `.json` keeps a note in its place (`chats._clean_result_content`, which
  was there already; the line naming the file is kept), `--debug` and
  `--dry-run` print only how long its data is (`api._without_image_data`),
  and the history's size estimate counts it as a picture inside a tool
  result too (`history.estimate_content_tokens`). The transcript `.txt`
  never held tool results.
- The tool's description is model-facing text: it says that this is how the
  robot sees, and never to describe an image it has not looked at.
- MyAgent attaches images to an instruction or a message. That is still not
  here: a picture gets in only as a file on the Pi that the model asks to
  see.
- When the owner asks to see a photo the Pi took, on a PC, run
  `.venv/Scripts/python.exe scripts/pi_photo.py` there (since 2026-11-22).
  It copies the Pi's newest photo to `~/RobotPhotos` on the PC and opens it
  in the PC's own viewer. `NAME.jpg` after it takes that photo instead,
  `--file F.jpg` one that is already on the PC, `--no-open` leaves the
  viewer shut.
  - Why a script and not a copy: a frame of the webcam's MJPG stream is a
    JPEG file without its Huffman tables (it has no `FF C4` segment). The
    stream's convention is that the standard tables are meant. The API and
    lenient decoders fill them in. Windows' decoder does not: the viewer
    opened and showed no picture, and GDI+ said "A generic error occurred".
  - So the script writes `NAME_viewable.jpg` beside the copy, with the
    standard tables (420 bytes) put in front of the picture data, and opens
    that. The picture data is not touched and the photo as it came is kept.
  - It will not put photos inside the checkout or inside a folder that
    OneDrive copies. It only reads from the Pi (`ssh` for the newest name,
    `scp` for the file).
  - Nothing was changed on the Pi, at the owner's word ("no stuff needed on
    the Pi"): the `take-photo` skill still saves frames as they come, so
    every photo needs this on Windows.
  - `tests/test_pi_photo.py` (21 tests, on every machine) gives it a
    stand-in for `ssh` and `scp`. No test decodes a picture: that was looked
    at by hand, on the desktop, with two photos.

### Hearing

- `microphone_listen` (in `tools.py`, its work in `hearing.py`, since
  2026-11-23, at the owner's request) is how the robot hears, and what it
  hears is speech only. Claude takes no sound (MyAgent's audit of
  2026-09-20, and no audio in the API's documentation on 2026-11-23), so
  the tool records some seconds and sends them to xAI's Grok Speech to
  Text, `POST https://api.x.ai/v1/stt`, model `grok-voice-transcribe-2.0`.
  The words are the tool's result, as text. It is MyAgent's tool of the
  same name; MyAgent's Mike button (dictating a reply) is not here.
- The owner chose xAI and this entry point out of four that were put to
  them (a skill alone, this tool, a key in the interface that dictates a
  reply, listening hands-free). Hands-free was built the next day (see
  "Hands-free"). The key that dictates a reply is not built: do not build
  it unasked.
- The key is `XAI_API_KEY` in the Pi's `~/robot/.env`. It was copied there
  from the laptop's environment, where MyAgent uses it, with a pipe that
  never showed it. A call made with it is billed to the owner's xAI
  account. Without the key, or without `arecord`, the tool
  is not offered (`hearing.available`), so a PC's runs never have it.
- Recording: `arecord -q -D plughw:CARD=B100,DEV=0 -t raw -f S16_LE -c 1 -r
  16000 -d N+1`, to a pipe. The device is the first capture device that
  `arecord -l` lists, named by its card (`hearing.find_microphone`;
  `ROBOT_MIC_DEVICE` overrules it). One second more than asked for is
  recorded and dropped, for the thump described under "Sound". 5 seconds
  unless the model says otherwise, 120 at most, rounded up to whole
  seconds. Nothing is written to disk.
- The upload is a multipart form made by hand with `urllib` (no new
  package): the `model` field, then the file, which must come last. The
  answer is JSON with a `text` field. No `language` is sent, so the service
  finds the language itself and leaves numbers as words.
- A recording whose loudest sample is under 50 of 32767 is not sent: that
  is a dead microphone, not a quiet room. A room without speech IS sent,
  and the service answers with no words ("no speech was recognised"):
  three listens of 4 seconds with nothing played said so.
- The cost is xAI's, $0.10 for an hour of sound, and is stated in the
  tool's result as an estimate ("about $0.0003" for 9 seconds). It is not
  in the run's cost and not in the cost log, which is for Anthropic's
  calls. That is MyAgent's way.
- It is not `parallel_safe`: it runs on the main thread, inside the region
  where Ctrl-C and STOP raise, and `hearing.record` kills the recorder on
  the way out. Tried on the Pi: one `arecord` while listening, none half a
  second after a SIGINT.
- The person cannot tell when the robot listens. The tool's description
  tells the model to say so in its reply before the call, and in both paid
  checks it did ("I'm listening now").
- A wrong key is answered by xAI with HTTP 400 and "Incorrect API key
  provided", not 401. `hearing.transcribe` goes by that wording too.
- How it was tried, since a session can neither speak nor hear. A sentence
  was made with Windows' own speech (`System.Speech`, a WAV file), copied
  to the Pi's `/tmp`, and played through the Pi's speakers while the tool
  listened: a loop waited for `pgrep -x arecord` and started `aplay` 1.3
  seconds later, past the second that is dropped. First the tool alone in
  a scratch copy, then two paid chats on Haiku ($0.0020 and $0.0023): asked
  to "listen to me for 10 seconds", the robot repeated the sentence; told
  "I am about to say something out loud. Hear me out and do what I ask", it
  listened, read the clock and answered the spoken question.
- Not understood: in three of the seven real listens that day the transcript
  held one thing more that was not played. "Fifty." from a room with
  nothing played, and "Eight." and "8:50" after the sentence. The owner
  was in the room, so it may have been real sound; it may also be the
  service making words out of the noise at the end. Not looked into.
- The `record-sound` skill said "You can record but not listen" in every
  run's system prompt. Three sentences of it were changed the same day,
  through `manage_skills` with a script fed over stdin: it now sends the
  model to `microphone_listen` for speech, and still says that no tool
  takes a sound FILE in.
- `tests/test_hearing.py` (40 tests, on every machine) gives it stand-ins
  for `arecord` and for the service. The Instruction Editor's Tools dialog
  lists the tool, so an instruction can block it.

### Hands-free

- Since 2026-11-24, at the owner's request ("build hands-free properly"):
  while the robot waits for a message it listens for a spoken one, and what
  was said is the reply. Typing still works. Off unless asked for:
  `--hands-free` in the chat (`chat.sh --hands-free`), the Hands-free box
  in the interface (Alt+H, kept in `tui_state.json`, and it can be ticked
  and cleared while the robot waits).
- It is not a tool and the model does not know of it: a spoken message
  reaches the agent as the reply to `Console.ask`, like a typed one. So
  every wait listens (the first message, the next one in a conversation,
  the answer to `user_prompt`), and the end words work when spoken:
  `convo_end_word` takes "Bye." for "bye". The line shown and saved is
  `you> (heard) ...`; the model gets the words without the mark.
- `handsfree.Segmenter` is the part that decides what is speech, a tenth
  of a second (3,200 bytes) at a time, and has no microphone in it:
  - A chunk's level is the RMS of its samples around their own average, so
    a steady offset counts as nothing.
  - The first ten chunks are not looked at. Measured on the Pi from a cold
    start: 7,100 and 2,500 (the thump described under "Sound"), then 600
    to 1,300 for seven tenths, in a room that was at 300; it goes on
    sinking for seconds, to about 270.
  - `floor` is the room's own level. The first chunk looked at sets it;
    below it, it follows down fast (0.7 of the old, 0.3 of the new),
    between it and the start level slowly up (0.98 and 0.02). Speech
    starts when 3 of the last 4 chunks are above `max(2.5 x floor, floor
    + 300)`, and ends after 15 chunks in a row below `max(1.6 x floor,
    floor + 150)`. What is cut out is half a second from before the start,
    the speech, and three tenths of the pause; a minute at most; fewer
    than three loud chunks in all is a click and is dropped.
  - Those figures come from one measurement: the speakers' speech was
    1,000 to 4,800 at the microphone, mostly 1,500 to 2,300, and the gaps
    between its sentences, four to five tenths long, went down to the
    room's 270 to 450. The owner's own voice at the microphone was not
    measured: if it is not picked up, the two `max(...)` lines are where
    to look.
  - `not_speech()` is called when a cut-out piece came back without words:
    the floor is raised to half that piece's typical level, so the same
    noise does not start another piece at once.
- `handsfree.Ear` runs `arecord` with no length on a thread of its own
  (the same command as hearing's otherwise), feeds the segmenter, has each
  piece transcribed with `hearing.transcribe`, and holds the words for
  `take()`. `state` is `listening`, `hearing` or `working`. `problem` is
  set when it stops by itself (no key, no microphone, `arecord` ended:
  "Device or resource busy" when something else has the microphone), and
  `trouble` when one transcription failed and it goes on listening.
  `stop()` kills the recorder; words that arrive after that are dropped.
- The microphone is open only during the wait. The robot's own `speak`
  and `microphone_listen` run between waits, on the same thread that then
  opens the ear, so the robot neither hears itself nor fights itself for
  the microphone. Two interfaces that are both hands-free do: the second
  one's recorder fails and it says so.
- The two places that wait:
  - The interface: `UiConsole._read_reply` looks at the reply queue and at
    the ear every tenth of a second, opens and closes the ear as the box
    changes, and posts an `("ear", state)` event when the state changes,
    which the bottom line shows (`EAR_NOTICES`).
  - The chat: `Console._type_or_speak` waits with `select` on the keyboard
    and looks at the ear. readline's `input()` is not used while
    hands-free is on, because a voice cannot wake it: the line is edited
    by the terminal itself, so there is no history and no arrow keys
    there. What was half typed when a voice came is thrown away
    (`tcflush`). Piped and headless runs never listen.
- A warning is shown once per kind of trouble (`Console._ear_trouble`),
  not at every prompt, and one failed start is not tried again within the
  same wait.
- The interface's bottom row has six boxes now, which do not fit in 72
  columns: `MainWindow.layout` gives them a second row there and the
  output pane one row less.
- Cost: only what is cut out is sent. In the first real test 9.6 seconds
  of sound were uploaded in 40 seconds of listening, with two messages
  spoken; a quiet room uploads nothing.
- Tried for real on the Pi, a session being unable to speak: xAI's voice
  `rex` said the "person's" lines through the speakers.
  - The ear alone, in a scratch copy: two messages eleven seconds apart
    were each handed over 1.3 to 1.9 seconds after the speakers fell
    silent, word for word, the full stop in the middle of each not
    splitting it, and nothing was sent in the 20 quiet seconds after.
  - The interface, in a tmux of the check's own (`zz-ui`, `--session zzt`,
    its `tui_state_zzt.json` written beforehand with the box ticked, an
    instruction `ZZ Talk` on Haiku, `HOME` a scratch folder): a spoken
    first message, the answer spoken by the robot (the owner's
    `robot-identity` skill has it speak its replies), listening again, and
    a spoken "Bye." ending the run. $0.0004.
  - The chat, in a tmux of its own (`zz-chat`): two spoken messages, one
    typed while it listened, each answered aloud, and "Bye." $0.0032.
  - The check's script waited for the listening prompt AND for `pgrep -x
    arecord` before the speakers spoke, then 1.5 seconds more for the
    lead-in.
  - Two mistakes in those scripts, for the next one: a helper that calls
    `robot.speaking` outside the program must load the `.env` itself, and
    `ls` on the Pi sorts `x_2.wav` BEFORE `x.wav` (its locale ignores the
    punctuation), so files to be played in order need names that say so.
  - In the first, failed try the speakers said nothing, and the interface
    still took a message from the room and ran with it. Whose voice that
    was is not known. Hands-free hears whoever speaks: a radio or a
    second person in the room can send a message.
- A conversation ended by a SPOKEN end word gets a goodbye first, at the
  owner's request and in the owner's words (`agent.FAREWELL`): "I am ending
  this conversation now. Good to have known you."
  - It is the program that says it, not the model: no call is made.
    `Agent._say_farewell` shows it as a `robot>` line and speaks it with
    `speaking.say`, which plays from a file in the data folder's `tmp` and
    keeps nothing (unlike the `speak` tool). It costs xAI's price for 58
    characters, a tenth of a cent.
  - `Console.last_reply_heard` is how the agent knows: both consoles set it
    with every reply. A typed end word, an empty reply and nobody being
    there end a conversation without the goodbye.
  - Only the conversation's own end (`_next_convo_message`). "exit" in
    answer to `user_prompt`, and an end word as the very first message of
    an instruction without text, end things silently as before.
  - Without a voice (no key, no `aplay`) it is shown and not spoken. A
    failure to speak is a warning; STOP cuts it short; the conversation
    ends either way.
  - Tried with a paid hands-free chat on Haiku ($0.0004), in a tmux of
    its own: after the speakers' "Bye." the chat showed `you> (heard) Bye`
    and the `robot>` goodbye, and a `hearing.listen` started the moment
    the chat's recorder was gone heard "This conversation now. Good to
    have known you." (its own first second is thrown away). No file was
    left in `tmp`.
  - That check's first try failed by its own timing: "the last line is
    `you>`" is still true while the message just spoken is being worked
    out, so the next line was played too soon. A check waits for the Nth
    `(listening: speak, or type)` line, the prompt and a running
    `arecord`. The failed try did show the fallback: with the microphone
    taken by the check, the chat said "Hands-free has stopped listening:
    ... Device or resource busy. Type instead." and went on at `you>`.
- `tests/test_handsfree.py` (50 tests; 7 need `select` and are skipped on
  Windows): the segmenter on made-up sound, the ear on a stand-in recorder
  that writes through a real pipe, and both consoles with a stand-in ear.

### Speaking

- `speak` (in `tools.py`, its work in `speaking.py`, since 2026-11-23, at
  the owner's request) is how the robot talks: a text goes to xAI's
  text-to-speech service, `POST https://api.x.ai/v1/tts`, a WAV file comes
  back, is saved and is played. The owner asked for text made into a WAV
  file that can be played through the speakers; the service and the shape
  (a tool, as for hearing, with the key that was already on the Pi) were
  chosen without asking, and the owner was told. MyAgent has no such tool:
  it speaks through skills.
- The request is JSON: `text`, `voice_id`, `language` (required by the
  service; `auto` is sent) and `output_format` (`codec` `wav`,
  `sample_rate` 24000). The answer is the file's bytes. Read in xAI's REST
  reference that day; the limits there are 60,000 characters a request and
  26 voices (`GET /v1/tts/voices`), `eve` being the default.
- The voice and the speed are settings the robot changes itself, since
  2026-11-24, at the owner's request (they had asked whether the
  `robot-identity` skill or the tool could do it; a skill is only text, so
  it is the tool):
  - They are kept in `~/robot-data/voice_settings.json` (`voice`, `speed`,
    either may be missing). `speaking.voice()` and `speaking.speed()` read
    the file at every call, so a change holds from the next sentence on, in
    every run and interface on the Pi, with no restart. With no voice in
    the file it is `ROBOT_VOICE` from the `.env`, else `eve`; the speed is
    1.0. What makes no sense in the file is passed over.
  - `voice_settings` is the tool. `list` gives the voice and speed in use
    and the service's voices (`GET /v1/tts/voices`: 28 on that day, each
    with `voice_id`, `name`, `gender` and `language`, the last being
    "multilingual" for all). `set` saves a voice, a speed or both. A voice
    is checked against that list first and refused with the names there
    are; when the list cannot be had, nothing is saved.
  - `speak` takes `voice` and `speed` for one call, which saves nothing:
    that is how a voice is tried out.
  - The speed is the service's `speed`, 0.7 to 1.5. It is sent only when it
    is not 1.0. Tried: one sentence was 3.7 s at 0.7, 2.9 s at 1.0 and
    1.95 s at 1.5; 2.0 is an HTTP 400.
  - Tried on the Pi in a scratch copy with a data folder of its own: the
    list, a refused name, `rex` at 1.3 saved, then a sentence in the saved
    voice and one in `eve` at 0.8 for that call only, while the microphone
    listened: both sentences came back word for word, and `rex` at 1.3 was
    still what was saved.
  - Then a paid chat on Haiku ($0.0028), the real program on the real data
    folder: "How many voices do you have? Switch to the voice called orion,
    a little faster than usual, and then say hello out loud" gave `list`,
    `set` with `orion` and 1.15, and `speak`; the answer was "28 voices".
    The settings file that chat left was removed again, there having been
    none before: a paid check of `set` changes the owner's own voice, so
    look first whether the file is there, and put back what was.
  - The `robot-identity` skill, which the owner has rewritten since
    2026-11-18, got one paragraph more the same day at the owner's request,
    through `manage_skills` with a script fed over stdin: that the robot
    can change its voice and speed, and to use `voice_settings` when asked.
    The rest of the skill is the owner's own text and was left as it was.
  - Listing is a second tool and not an action of `speak`, as the owner agreed to when it was put to
    them, so that `speak`'s description stays about speaking. It adds
    about 300 tokens to every request (an estimate).
- An unknown voice is a 404, which the tool reports as such. The text may
  hold the service's speech tags (`[pause]`, `<whisper>...</whisper>` and
  so on); the tool's description does not mention them, and none was tried.
- The WAV file as it comes states a length it does not have: its header
  said 1,073,741,823 frames for a file of 3.8 seconds (it is made while
  the sound is still being produced). `speaking.clean_wav` reads to the
  last sample and writes the file again with a right header, which is also
  how the tool knows the speech's length.
- The file is kept: `~/robot-sound/speech_<date>_<time>.wav`, mono, 16 bit,
  24 kHz, 48 KB a second, beside the recordings, so that `play-sound` can
  play it again. Nothing removes them.
- It is played with `aplay -q -D plughw:CARD=Headphones,DEV=0`: the first
  playback device `aplay -l` lists, named by its card
  (`speaking.find_speakers`; `ROBOT_SPEAKER_DEVICE` overrules it). With
  `play` false the file is made and not played. A failure to play still
  says where the file is.
- One call takes 2,000 characters at most (`MAX_CHARS`), about two minutes
  of speech: the tool returns only when the file has been played to its
  end, and it is not `parallel_safe`, so Ctrl-C and STOP cut the sound off
  (the player is killed on the way out, as hearing's recorder is).
- The cost is xAI's, $15.00 for a million characters (its pricing page on
  2026-11-23), stated in the result as an estimate and, like hearing's,
  not in the run's cost or the cost log. A sentence of 94 characters is
  $0.0014; a full call of 2,000 is three cents.
- The result says "The sound was sent to the speakers; whether it was
  heard is not known": `aplay` cannot tell whether the speakers have power
  (see "Sound").
- The description tells the model not to listen in the same turn as it
  speaks. Both tools run one after the other in any case, in the order the
  model gave.
- How it was tried: the tool spoke a sentence in a scratch copy while
  `hearing.listen` ran on a second thread, and the transcript was the
  sentence, word for word, number included. So the robot's own hearing is
  the check for its voice. `HOME` was a scratch folder, so the check's
  files did not land in the owner's `~/robot-sound`.
- That check went wrong in one way: a run of the owner's was in progress
  (`~/robot-data/runs` held a file, which the check listed and did not
  act on), and the sentence was played into the room during it. A check
  that uses the speakers or the microphone must STOP when that folder is
  not empty, not just show it.
- Then a paid chat on Haiku ($0.0022), the real program with `HOME` a
  scratch folder: "Say out loud, in one short sentence, what day of the
  week it is" gave `get_current_datetime`, then `speak` with "Today is
  Monday.", a file of 76 KB, and the reply that it cannot tell whether
  anyone heard it. Listening and answering aloud in one run was not tried.
- An interface that was open before the deploy keeps the old code: its
  runs get the tool once it has been quit and started again.
- `tests/test_speaking.py` (59 tests, on every machine) gives it stand-ins
  for the service and for `aplay`, among them a file with the header the
  service really sends.

### Sound

- The robot can record sound to a file and cannot listen to a file.
  Nothing in the repo records to a file: the model does it with the shell
  tool, told how by its `record-sound` skill (see "State on 2026-11-18"),
  and there is no tool that takes a sound file in, as `view_image` takes a
  picture. So a run can say that it made a recording and where the file
  is, and nothing about what is on it. What it can do since 2026-11-23 is
  hear speech in the room as it is spoken (see "Hearing").
- The microphone is the webcam's (see "Conventions"). The Pi has it as sound
  card `B100`, with `arecord` installed and the user in the `audio` group,
  so recording needs nothing installed. It gives mono, 16 bit, at 16,000 to
  48,000 samples a second (`arecord -D hw:CARD=B100 --dump-hw-params`), and
  its switch and level are `amixer -c B100 sget Mic` (on, 75%, on
  2026-11-22).
- The skill's recordings are WAV files in `~/robot-sound` on the Pi,
  `sound_<date>_<time>.wav`, mono, 16 bit, 16 kHz: 32 KB a second. Its
  command first records one second that it throws away, because the
  microphone wakes with a thump after a few seconds of rest.
- That thump is the webcam waking from USB power saving (measured on
  2026-11-22, on the 3 A+). The kernel puts the idle webcam to sleep two
  seconds after its last use: in `/sys/bus/usb/devices/1-1/power`,
  `control` is `auto`, `autosuspend_delay_ms` is 2000, and `runtime_status`
  goes from `active` to `suspended`. A recording that starts while it is
  asleep begins with a spike, about a third of full scale in the first
  tenth of a second after five seconds of rest or more, and less after a
  shorter sleep; one that starts while it is still awake has none (the room
  was not quiet, so the smaller figures are rough). So the second that
  is thrown away works by waking the webcam. Keeping it awake (`control`
  set to `on`) should do the same: not tried, and a setting of the Pi.
- A photo and a recording in one go is ONE shell command, and the skill has
  had two of them since 2026-11-22, added at the owner's request with a
  script fed over stdin that calls `manage_skills`. The owner had asked for
  a photo and then a recording, and the recording began about 5 s after the
  camera's light came on.
  - Where that time went, by the transcript and the files' times: the photo
    took 1.7 s, the model's next call 2.4 s (it had to be told the photo was
    done before it asked for the recording), and the second that is thrown
    away 1.2 s.
  - Two shell calls in ONE turn are no cure: `run_shell_command` is not
    `parallel_safe`, so they run one after the other. Asked for both "at the
    same time", the model sent the recording and a photo with `sleep 3` in
    front, expecting them side by side: the photo was taken two seconds
    after the recording had ended.
  - "A photo, then record": the thrown-away second runs in the background
    while the photo is taken, and the recording starts when both are done.
    Measured: 0.03 to 0.08 s from the photo's file to the recording's start.
    "Both at the same time": the recording runs in the background and the
    photo is taken meanwhile, 1.4 s into it. No thump at the start of
    either.
  - Tried through `tools.run_shell_command` with `HOME` set to a scratch
    folder, so that the commands' `~` led there, and then with a paid check
    on Haiku ("Take a photo and then record for 3 seconds"): one tool call,
    two "saved" lines, $0.0023. The check's photo and recording were
    removed.
  - The skill's text grew from 2,763 to 5,399 characters, and it is in
    every run's system prompt: about 650 tokens more.
- When the owner asks to hear a recording the Pi made, on a PC, run
  `.venv/Scripts/python.exe scripts/pi_sound.py` there (since 2026-11-22).
  It copies the Pi's newest recording to `~/RobotSound` on the PC, says what
  it holds and plays it to its end through the PC's speakers. `NAME.wav`
  after it takes that recording instead, `--file F.wav` one that is already
  on the PC, `--no-play` only says what it holds.
  - It returns when the recording has been played to its end, so give the
    command more time than the recording is long. It plays with Python's
    `winsound`, which Windows alone has: elsewhere it copies, describes and
    says where the file is.
  - A session cannot hear what was played. What it can go by is the line
    about the level, which the script prints before playing: the loudest
    sample and the average, as parts of full scale. It says so when every
    sample is 0 (silent), when the loudest reaches full scale (probably
    distorted there), and when the file is shorter than its header says (a
    recording that was cut off). The four recordings of 2026-11-22 had
    averages of 1.2% to 3.8% and loudest samples of 4% to 100%. What a
    quiet room reads was not measured, so a low figure is not proof of
    silence: ask the owner what they heard.
  - Unlike the photos, a recording needs no repair: Windows plays the WAV
    file as it comes.
  - It will not put recordings inside the checkout or inside a folder that
    OneDrive copies (`pi_photo.safe_folder`), and it only reads from the Pi.
    Recordings are personal, as photos are.
  - `tests/test_pi_sound.py` (39 tests, on every machine) gives it stand-ins
    for `ssh`, `scp` and the speakers, and makes its own WAV files. That a
    recording is heard was tried by hand, on the desktop.
- The Pi can make sound as well, since the evening of 2026-11-22: the owner
  plugged USB-powered stereo speakers into the 3 A+'s headphone socket.
  Their power comes from elsewhere, the Pi's one USB port having the
  webcam. The robot plays a sound file with the shell tool, told how by
  its `play-sound` skill (since 2026-11-23, see the next point). The one
  thing in the repo that plays sound is the `speak` tool, which plays the
  speech it has just made (see "Speaking").
  - A WAV file is played with `aplay -q -D plughw:CARD=Headphones,DEV=0
    FILE.wav`. `plughw` converts what the file has into what the socket
    takes, so the robot's own recordings (16 kHz, mono) play as they are;
    files of 44.1 and 48 kHz, mono and stereo, played too. The Pi has no
    sound server: `aplay` goes straight to the card.
  - The socket's own volume is `amixer -c Headphones sget PCM`: 0 dB, which
    it shows as 96%, and not muted, on that day. `amixer -c Headphones sset
    PCM 6dB-` lowers it by 6 dB and `6dB+` raises it again; `mute` and
    `unmute` in place of the figure switch it (tried on 2026-11-23: three
    steps down made a tone 17.7 dB quieter at the microphone). The speakers
    have a knob of their own.
  - How strong the speakers are at the microphone, with the socket at 0 dB
    and the knob where the owner had it: a tone came back at 1.6 to 2.2
    times the strength it was sent with that first evening (two pitches),
    and at 0.8 to 1.4 times on 2026-11-23 (four pitches). So a recording
    played back is about as strong there as the sound it holds was, or
    stronger. Captures held samples at the microphone's limit on both days.
    That alone does not show that the speakers are too loud: in one capture
    of 2026-11-23 a burst showed a second before anything was played.
  - `aplay` ends with code 0 whether or not anything sounds: it cannot know
    if speakers are plugged in, powered or turned up. The first tries that
    evening all "worked" that way while the speakers had no power.
  - A session cannot hear the speakers, but the Pi can: its microphone is
    in the same room. The test that settled it played a stereo file made
    on the spot (beeps of 880 and 1320 Hz in turn for six seconds, then
    660 Hz on the left channel alone and 1760 Hz on the right alone) while
    `arecord` listened, and then measured each pitch, in tenths of a
    second, at the times it should sound and at the times it should not.
    Without power every pitch stayed where the room's noise was (3 dB at
    most between the two); with power they stood 48 to 69 dB above it, both
    channels and every beep from the first. Typing and talking cannot make
    such a pattern.
  - A simpler test before it proved nothing: one tone, a spoken sample and
    a recording, judged by loudness alone. The owner was typing, and the
    bursts of that could have been taken for the speakers. Comparing the
    rise and fall of what was heard with that of the file told them apart
    (0.73 and 1.00 for the two real files once the speakers had power).
  - The scripts were fed over stdin and are not in the repo. They used the
    microphone for up to 20 s: see "Running and testing" on checks that
    use the webcam.
- Playing is ONE shell command as well, in the `play-sound` skill (since
  2026-11-23, see "State on 2026-11-18"). `f=""` at its start names the
  file: a path, a name alone for a recording in `~/robot-sound`, or nothing
  for the newest recording there. It plays the file to its end and prints
  "played PATH in N seconds", or "nothing played" with the reason.
  - It refuses a file that does not begin as a WAV file does (`RIFF`, four
    bytes of length, `WAVE`). `aplay` takes a file it does not know for raw
    samples, which would be noise from the speakers (its known behaviour,
    not tried here). A WAV file that `aplay` cannot play and a sound card
    that is not there come back as "nothing played" with `aplay`'s message.
  - Because it returns only at the file's end, the shell tool's limit of
    60 seconds matters: the skill has the model set `timeout_seconds` to
    600, and it did in both paid checks.
  - A play that is killed (that limit, STOP, Ctrl-C) stops at once. The
    kernel then logs `bcm2835-audio: failed to close VCHI service
    connection (status=-11)`, every time, and nothing is wrong: the audio
    service is gone from `/sys/kernel/debug/vchiq/state` as it is after a
    play that ended by itself, and what was played next was heard. `aplay`
    ended with SIGTERM leaves no such line.
  - Two plays at once are mixed. The socket has eight sub-devices (`aplay
    -l`): two files started 0.3 s apart were both heard, and neither
    waited for the other.
  - Tried through `tools.run_shell_command` with `HOME` set to a scratch
    folder, as the recording commands were, while the microphone listened.
    The files were soft beeps, each file with a pitch of its own, so that
    what was heard says WHICH file was played: the newest, the one named,
    one with spaces in its path. Each stood 52 to 63 dB above the room, the
    refused files left silence, and a file cut off by the tool's limit was
    heard up to there.
  - Then two paid checks on Haiku ($0.0026 and $0.0024), the real program
    on the real data folder (`ROBOT_DATA_DIR`) with `HOME` a scratch
    folder. A plain chat, "Play the newest recording": `get_skill`, then
    the skill's command to the letter, and the beeps of the newest file
    were heard. And an instruction with the skill list of `WebcamTest`,
    "Record sound for 5 seconds, then play that recording back": beeps
    were played while it recorded, and they were heard a second time when
    it played its recording. Both times the robot said that it could not
    hear what it had played.
  - The first try that morning heard nothing at all, while every command
    said "played": the speakers had no power, as on the evening they came.
    A test that hears nothing asks first whether they are on.
  - Strength in one pitch is a weaker proof than the pattern of the
    evening before. With people in the room its own noise reached 29 dB
    above the quiet level in a narrow filter, and a burst once 39 dB,
    where the test tones stood at 52 to 63. The times at which a pitch
    should and should not sound tell more.

### Input, output and Ctrl-C

- `Console` prints: `robot>` before each stretch of reply text, `[tool: ...]`
  lines, indented activity and `call N: <cost>` lines (hidden by
  `--no-activity`), `warning:` and `error:` lines (always shown), thinking
  with `--thinking`. Everything shown also goes to the chat's `.txt`.
- Input modes: a terminal (readline `input()`), piped stdin (lines are replies,
  end of input means nobody is there), `--headless` (never reads stdin: a relay
  folder answers, or nobody does).
- At a terminal the chat is forgiving in two ways, unlike MyAgent's dialog:
  Ctrl-C cancels the reply or command and returns to `you>`, and an API error
  returns to `you>`.
- An empty reply is an answer everywhere, as in MyAgent: it ends a
  conversation, and an empty reply or `exit` to `user_prompt` stops the run
  (`quit` and `stop` there go to the model). At the first `you>` it means no
  task, and the chat ends. Until 2026-11-19 the chat at a terminal ignored an
  empty line and asked again; the owner asked for MyAgent's rule in the
  interface and then in the chat ("ignore nothing"). Do not bring the
  skipping back unasked.
- The one line still ignored at a terminal is one that came from the terminal
  itself (see "Terminal answers that reach the prompt"). `_ask_terminal` asks
  again by itself for that, so the agent never sees it: returned as an empty
  reply it would now end the chat.
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
    for Windows, and on the Pi a real tree: its stand-in child `Family`
    starts children of its own (3 tests, skipped on Windows).
  - Where the free memory cannot be read (anywhere but Linux: the PCs'
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

### The screen and the keys

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
  the four Meta tools last, then any blocked name the program does not know
  (one copied in from MyAgent, or one of a tool since removed), so that such a block is not lost on saving.
  The README's tool table is in the same order. Nothing marks where the Meta
  group starts. `meta` in the top row stands for that group of four.
- A tick in that dialog says only "not blocked". With the form's Meta box
  clear, the four Meta tools (`editor.META_TOOL_NAMES`) are therefore shown
  as `[-] name  (needs Meta)` and are locked (`ChecklistDialog`'s `locked`):
  until 2026-11-20 they showed ticked, which the owner took, fairly, for
  "offered". They are not shown unticked, because a cleared box is saved as
  a block, and the tools would then stay blocked after Meta is ticked. A
  block already set on one of them is kept as it is. The dialog goes by the
  box as it is on the form, saved or not.

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
