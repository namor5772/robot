# robot

The agent "brain" for a small robot running on a Raspberry Pi Zero 2 W. It
talks to Anthropic's Claude models and can act on the Pi through tools.

The program is a terminal port of the MyAgent harness: the same way of running
saved instructions, the same skills format, the same Meta tools and Convo
mode, the same cost log. It leaves out MyAgent's windows, its safety-confirm
system and every provider other than Anthropic.

## Starting a chat

From the laptop:

```powershell
ssh -t pi "bash ~/robot/scripts/chat.sh"
```

At the Pi's console:

```bash
bash ~/robot/scripts/chat.sh
```

You get a `you>` prompt straight away. What you type first is the task, and
after every reply you are asked for the next message. `quit`, `stop`, `exit`,
`bye` or Ctrl-D end the chat. Ctrl-C stops the reply or command in progress
and returns to the prompt.

`chat.sh` runs the chat inside tmux, so it belongs to the Pi and not to your
SSH connection. If the laptop sleeps or the connection drops, the chat keeps
running, and the same command brings you back to it.

- To leave a chat running on purpose, press Ctrl-B, then D.
- The mouse wheel scrolls back. To select text, hold Shift while dragging.
- When the chat ends, press Enter to close the window.
- If a line such as `11;rgb:0c0c/0c0c/0c0c` or `61;4;6;7c0;10;1c` shows up at
  `you>` without you typing it, it is your terminal's answer to a question
  from tmux that slipped through. Press Enter before typing anything else: it
  is ignored, not sent.
- While a chat is starting, such answers are thrown away, and so is anything
  you type before the first `you>` appears.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.main`.

## The windowed interface

The same agent behind buttons, lists, text boxes and dialogs, all drawn with
characters. It needs no graphical desktop: it works over SSH and on the Pi's
own screen and keyboard.

From the laptop:

```powershell
ssh -t pi "bash ~/robot/scripts/ui.sh"
```

At the Pi's console:

```bash
bash ~/robot/scripts/ui.sh
```

```
 Robot  |  ZZ ui chat  |  claude-haiku-5-5 (Low)  |  conversation
 [ START ] [ STOP ] [ Instruction ] [ Skills ]                [ Help ] [ Quit ]
┌─ Output ─────────────────────────────────────────────────────────────────────┐
│This instruction has no saved task. Type it as your message.                  ▲
│you> Say hello in exactly five words.                                         │
│robot> Hello there, friend, nice to meet you.                                 │
│  call 1: $0.0010 this call  |  $0.0010 total  (in:4  out:17                  │
│cache_write:7,604)                                                            │
│you> How hot is your CPU right now? Use your tool, then answer in one         │
│sentence.                                                                     │
│  call 2: $0.0001 this call  |  $0.0011 total  (in:4  out:32  cache_write:45  │
│cache_read:7,604)                                                             │
│[tool: get_cpu_temperature]                                                   │
│robot> My CPU is running at 45.6 degrees Celsius right now.                   │
│  call 3: $0.0001 this call  |  $0.0012 total  (in:2  out:24  cache_write:50  │
│cache_read:7,649)                                                             │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ Your message (Enter sends, Ctrl+J starts a new line) ───────────────────────┐
│                                                                              │
│                                                                              │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
 [x] Activity [ ] Thinking [ ] Tool calls [ ] Debug [ ] Save thinking
 Waiting for your message                  F1 Help  F2 Start  F3 Stop  F10 Quit
```

What the main window has:

- **The top line** names the instruction that START will run, with its model,
  its thinking level and whether it is a conversation or a single task. `meta`
  at the end means the instruction's Meta switch is on, which gives its runs
  the group of four Meta tools (see [Tools](#tools)). No other tool is shown
  here. A name too long for the window is shortened with `...`, so that the
  settings after it always stay in view.
- **START** (F2) runs it. What the run shows appears under *Output*, the same
  lines the chat prints. Each START clears *Output* first, as in MyAgent; the
  earlier run's lines are in its saved chat. **STOP** (F3 or Ctrl+C) stops the reply or command in
  progress; while the robot is waiting for your message, it ends the run.
- **Your message** takes the cursor whenever the robot waits for you. Enter
  sends; Ctrl+J starts a new line. `quit`, `exit`, `stop` or `bye` on its own
  ends a conversation, as in the chat.
- **Instruction** (F4) opens the Instruction Editor: a list of the saved
  instructions and a form for the one selected (name, model, thinking level,
  Fast, Meta, Convo, notes, blocked tools, skills, upgrade model, text).
  *Save* stores the form under the name in the Name box, so a new name makes a
  new instruction. *Use* makes it the one START runs.
- **Skills** (F5) opens the Skills Manager: every skill with its mode, text,
  description and bundled files. Space on the list switches a skill between
  off, ON (in every prompt) and OD (on demand).
- **The boxes along the bottom** choose what a run shows: Activity (tool lines
  and the cost of each call), Thinking, Tool calls, Debug. They are remembered.
- **Help** (F1) lists every key. **Quit** is F10.

Getting around:

| Key | What it does |
|---|---|
| Tab, Shift+Tab | The next or the previous control. |
| Alt+letter | The control that shows that letter highlighted. |
| Enter or Space | Press the button, tick the box, open the list. |
| Escape | Close the window. Unsaved changes are asked about first. |
| Up, Down, PgUp, PgDn, Home, End | Move in a list or a text; look back through the output. |
| Mouse | Click a control; the wheel scrolls. Hold Shift to select text. |

Good to know:

- A run started here is always the run of a named instruction, `Default`
  included, so its saved chat and its cost-log line carry that name. An
  instruction with no text asks you for the task.
- One run at a time. The editors can be used while a run is going; what they
  save applies from the next run.
- Like the chat, it runs inside tmux and survives a dropped connection: the
  same command brings you back, and Ctrl-B then D leaves it running. It has a
  tmux of its own, so a chat can be open as well.
- Starting it again joins it. If the interface is already running, the
  command does not start a second one, whether you type it on the laptop or
  at the Pi. There is then one program with several screens: each shows the
  same windows, and any of the keyboards drives them. The window takes the
  size of the screen that was used last.
- At the Pi's own screen it is the same command and the same keys, Shift+Tab
  included. There is no mouse there: the Pi's text screen passes no clicks on
  to a program, so everything is done with the keys.
- Text pasted into the terminal goes into the box that has the cursor, as text.
- It runs on the Pi only: Python on Windows has no curses.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.tui`.

### More than one at a time

Whatever runs an instruction is a program of its own, taking 80 to 95 MB of
the Pi's 415 MB. So there are three limits:

| What | Limit |
|---|---|
| Instructions in one interface | One at a time: START is off while a run is going. |
| Child runs that a run starts itself (`run_instruction`, with Meta on) | As many as there is memory for, and never more than 8 at once in all, counting the children that children start: one is started only while 110 MB is free. On this Pi that comes to two at once. |
| Interfaces and chats open at once | No fixed number. What memory limits is how many are working at the same moment: about three, however they were started. One that is open but idle takes far less (see below). |

A chat and the interface can be open together: `chat.sh` and `ui.sh` each
have a tmux of their own. For a second interface, give it a session name:

```bash
bash ~/robot/scripts/ui.sh --session 2
```

From the laptop that is `ssh -t pi "bash ~/robot/scripts/ui.sh --session 2"`.

At the Pi's own screen every interface can have a text terminal to itself.
Hold Alt and press F2 for the second terminal, log in there (it asks the
first time), and start the interface with `--session 2`. Alt+F1 goes back to
the first terminal, and Alt+F3 to Alt+F6 are four more. The keys work while
an interface is on the screen, and whatever you leave keeps running.

- Any short name will do in place of the 2: up to 12 letters, digits, `-`
  or `_`.
- The same command brings you back to that interface later. Without
  `--session` you get the first one, which is also what `--session 1` means.
- Each interface shows its name in its top row (`Robot 2  |  Default  | ...`)
  and remembers its own instruction in use and its own display boxes.
- `-l "Name"` still works beside it: `ui.sh --session 2 -l "Zero state chat"`.

All the interfaces are in one tmux, and its keys go from one to the other:

| Keys | What happens |
|---|---|
| Ctrl-B then `)` | The next interface. |
| Ctrl-B then `(` | The one before. |
| Ctrl-B then `s` | A list to pick from. |
| Ctrl-B then D | Leave them all running. |

The interfaces share the instructions, the skills and the cost log, and each
keeps its own runs and saved chats.

An interface takes about 80 MB when it starts. One that sits idle gives most
of that back when memory gets short: the Pi squeezes it into compressed
memory, and brings it back when the interface is used again. Measured on
2026-11-19 with no run going in any of them:

| Interfaces open | Memory still available | What each held |
|---|---|---|
| Two | 120 MB | 83 MB each |
| Three | 141 to 147 MB | The new one 79 MB, the two older ones 33 and 41 MB |

So three open interfaces left more room than two. Whether a run can start
child runs (110 MB must be free) depends on the memory at that moment, not on
how many interfaces are open.

## Saved instructions

An instruction is a saved task together with the settings to run it with:
model, thinking level, fast mode, Meta on or off, Convo on or off, blocked
tools, skill modes and an upgrade model. Its text is the first message of the
run.

```bash
.venv/bin/python -m robot.main --list            # show the library
.venv/bin/python -m robot.main -l "Name"         # run one
bash scripts/chat.sh -l "Name"                   # run one inside tmux
```

- A run with **Convo off** is a single task: it works until the model is done
  and then ends. If the model needs you, it asks through its `user_prompt`
  tool.
- A run with **Convo on** is a conversation: you are prompted after every reply.
- The entry named **Default** holds the settings of a chat started without a
  name. Change it to change the everyday chat. It is re-created if deleted.

### A chat and an instruction compared

A chat is not a separate mode. It is an ordinary run with no saved task,
using `Default`'s settings, and `Default` has Convo on.

| | Plain chat (no `-l`) | Instruction (`-l "Name"`) |
|---|---|---|
| First message | You type it at `you>` | The instruction's saved text |
| Settings | Borrowed from `Default` | The instruction's own |
| Convo | On, because `Default` has it on | What the instruction says (off unless set) |
| Name in the cost log and saved chat | None (`Agent_<time>`) | The instruction's name |

A plain chat uses only `Default`'s settings: any text saved in `Default` is
ignored unless you run it by name with `-l Default`. An instruction with no
text asks you for the task when run at a terminal.

The robot is told which instruction and which model it is running as, so you
can ask it ("which model are you on?").

### Creating and changing instructions

Three ways:

- **The Instruction Editor** of the windowed interface (above): a form with
  the name, the model, the thinking level, the switches and the text.
- **Ask the agent.** With Meta on it creates, changes and deletes instructions
  and skills itself ("save this as an instruction called Night watch", "make
  the default model Haiku").
- **Edit the file by hand** (below).

Whichever way, a change applies from the next run, not the one in progress.

The library is one JSON file, `~/robot-data/agent_instructions.json`. Each
instruction is a named block, for example:

```json
{
  "Default": {
    "text": "",
    "model": "claude-opus-5-5",
    "thinking_mode": "low",
    "meta": true,
    "conversational": true
  },
  "Health check": {
    "text": "Report your CPU temperature, free memory and disk space in three short lines.",
    "model": "claude-haiku-5-5",
    "thinking_mode": "low",
    "meta": false,
    "conversational": false
  }
}
```

Only `text` is needed; anything left out takes a default (Opus 5.5 at its
Adaptive thinking level, Meta off, Convo off). `thinking_mode` is one of
`off`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max`; a level the model
lacks is replaced by the nearest it has, with a warning. Other fields: `notes`
(for you, never sent to the model), `fast_mode`, `blocked_tools`,
`skill_modes`, `upgrade_target`.

- After a hand edit, check the file:
  `python3 -m json.tool ~/robot-data/agent_instructions.json`. If it cannot be
  read, the robot leaves it alone, warns, and runs with built-in settings.
- Meta is what lets a chat manage instructions. If you turn Meta off in
  `Default`, the plain chat can no longer change anything, including turning
  it back on: edit the file, or delete the `Default` block so it is re-created.
- Entries copied from MyAgent's library work. Settings the robot does not have
  are ignored, and an entry for another provider is refused when run.

## Skills

An instruction is something to do; a skill is something to know. A skill is a
piece of know-how in its own folder, which any run can draw on:

```
~/robot-data/skills/
  check-power/
    SKILL.md
    scripts/report.sh        (optional: any files and sub-folders)
```

`SKILL.md` is a short header followed by the skill's text:

```
---
name: check-power
description: How to check the robot's power supply. Use when asked about power.
mode: on_demand
---

To check the power supply, run `vcgencmd get_throttled` with the shell tool.
throttled=0x0 means the supply has been fine since boot.
```

Each skill has a mode:

- **enabled**: its text is part of every system prompt.
- **on_demand**: only its description is listed; the agent fetches the text
  with `get_skill` when it applies. Write the description as what the skill
  does and when to use it, because that line is how the model decides.
- **disabled**: not used. This is what a new skill gets unless you say otherwise.

`.venv/bin/python -m robot.main --skills` lists them.

- **Creating one:** ask in a chat, naming the skill, its mode, its description
  and its content. A good way is to have the robot do the job once and then
  say "save what you just did as a skill". It applies from the next chat.
- **Reading and changing them:** the Skills Manager of the windowed interface
  shows every skill, its text, its description and its bundled files, and
  switches its mode with one key.
- **Bundled files:** the robot can list, read, write and delete files inside a
  skill's folder. When it fetches a skill that has such files it is told where
  the folder is, so it can run a bundled script with the shell.
- **Per instruction:** an instruction may carry its own `skill_modes`, a list of
  skills with the mode each has for its runs. Then every skill it does not
  name is off for those runs. Without one, the instruction follows each
  skill's own mode. Only the run is affected; the skills are not changed.
- **Copying skills in:** the format is MyAgent's, so a skill folder copied from
  there works as it is. A plain Anthropic-format skill has no `mode` line and
  comes in as disabled until you set one.

## Tools

| Tool | When | What it does |
|---|---|---|
| `run_shell_command` | always | Runs any bash command on the Pi as its user, with sudo. |
| `get_current_datetime` | always | Reads the Pi's clock. |
| `get_cpu_temperature` | if the sensor can be read | Reads the CPU temperature. |
| `user_prompt` | always | Asks you a question and waits for the answer. |
| `get_skill` | if a skill is on demand | Fetches an on-demand skill's text. |
| `web_search` | always | Searches the web on Anthropic's servers, up to 5 searches per request. |
| `manage_instructions` | Meta on | Lists, reads, creates, updates and deletes instructions. |
| `manage_skills` | Meta on | The same for skills and their bundled files. |
| `run_instruction` | Meta on | Runs another instruction as a child run. |
| `upgrade_model` | Meta on | Moves the rest of the run to a stronger model. |

Meta is the only group of tools. It is one switch on an instruction, and it
turns the last four on together: the tools with which the robot works on its
own setup. Their descriptions add about 3,000 tokens to every request. The
first six are not grouped: each is offered on its own, whenever it can work.

Any of the ten can be switched off for one instruction. In the Instruction
Editor the Tools button shows this list, in this order, with a tick beside
each tool the instruction may use. A cleared tool is blocked for that
instruction only (`blocked_tools` in the file), and a Meta tool needs both
the Meta switch and its tick.

The shell tool is deliberately unrestricted: no confirmation, no allowlist, no
blocked commands, and the Pi has passwordless sudo, so the agent has root. It
can read `~/robot/.env`, change any file, and act on what it reads from the
web. With Meta on it can also write skills that later runs load, so text it
picked up can outlast a session: the start banner lists the skills in use. To
take root away, run `sudo rm /etc/sudoers.d/010_grobliro-nopasswd` on the Pi.
An instruction's `blocked_tools` list removes tools from its runs.

A child run is a second copy of the program. On the Pi Zero it takes about 15
seconds to start and about 80 MB of memory. How many run at once is decided
by the memory that is free, not by a fixed number: a child is started only
while 110 MB is free (80 for it, 30 to spare), and memory that children still
starting have yet to take counts as taken. On the Pi Zero that comes to two at
once, as before. A computer with more memory, such as a Pi 5, runs as many as
fit, with no change to the program, up to a ceiling of 8 at once: every child
is a run that is paid for. The 8 is for the whole tree of runs. A child may
start children of its own (those may not start any), and they all count
together: the first run's children and the children those started.

## What you see

```
you> How hot are you, and how long have you been up? Check both.
  call 1: $0.0541 this call  |  $0.05 total  (in:4  out:83  cache_write:10,478)
[tool: get_cpu_temperature]
[tool: run_shell_command: {"command": "uptime -p"}]
robot> My CPU is at 45.1°C, which is a comfortable temperature. I've been up for 3 hours and 13 minutes.
  call 2: $0.0039 this call  |  $0.06 total  (in:2  out:44  cache_write:187  cache_read:10,478)
```

Each `call` line is one request to the model and what it cost. The first call
of a chat costs the most, because the system prompt and tool list (about
10,000 tokens with Meta on) are written to the prompt cache. Later calls read
them back at a fraction of the price, as long as you reply within five minutes.

Options for what is shown: `--no-activity` (hide tool and cost lines),
`--thinking`, `--tool-calls`, `--debug`. Others: `--model ID` and `--mode LEVEL`
for one run, `--dry-run` to print the request without sending it, and
`--help` for the rest.

## Where things are kept

On the Pi, outside this repository, in `~/robot-data`:

| Path | Contents |
|---|---|
| `agent_instructions.json` | The instruction library. |
| `skills/<name>/SKILL.md` | The skills. |
| `saved_chats/` | Every run's transcript (`.txt`) and messages (`.json`). |
| `APICostLog_<host>.txt` | One line per run: time, model, cost, tokens. |
| `tui_state.json` | What the windowed interface remembers: the instruction in use and the display boxes. An interface started with `--session 2` has `tui_state_2.json`. |
| `tui_errors.log` | Anything a library printed while the windows were up (normally empty). |

These files use MyAgent's formats, so instructions and skills can be copied
between the two programs. Nothing in `~/robot-data` is backed up by itself:
see the next section.

## Backing up the Pi

There are two kinds of backup, and both are kept on the laptop.

**The data that changes every day.** Instructions, skills, chats and the cost
log are in `~/robot-data`, a few megabytes. From PowerShell, in the folder
that is to hold the copy:

```powershell
scp -r pi:robot-data .
```

**The whole SD card.** One file, an exact copy of the card. Written back to a
card, it gives the Pi as it was that day: the system, the program and its
key. (The code alone is on GitHub.)

1. Shut the Pi down with `sudo poweroff`, wait until the green light stays
   off, and take the card out.
2. Put the card in the laptop. If Windows offers to format a disk, cancel.
3. In Win32 Disk Imager, name a new image file, choose the card's drive
   letter (the drive called `bootfs`) and press **Read**. Write would
   overwrite the card with the file.

To restore, write the file to a card with Raspberry Pi Imager, with "Use
custom" as the operating system. If it asks about customisation settings,
answer No: with them the Pi sets itself up as a new machine at its first
start and may reset its name, password and keys.

- Keep the file private, and out of folders that are synced elsewhere: it
  holds the API key, the Wi-Fi password and the Pi's keys.
- The file is as large as the card, whatever is on it, and fits only a card
  of that size or larger. Cards sold as the same size differ a little, so a
  larger one is the safe choice.
- A copy has the same name and keys as the original. Two Pis must not run
  from the two cards on one network at the same time.

On a larger card the system does not use the extra room by itself: `df -h /`
still shows the old size. These two commands claim it while the Pi runs,
without a restart:

```bash
sudo growpart /dev/mmcblk0 2
sudo resize2fs /dev/mmcblk0p2
```

That is how the Pi moved from a 16 GB card to a 32 GB one on 2026-11-19.

## Working on it

Develop on the laptop, push to GitHub, deploy to the Pi. Never edit files on
the Pi.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
git push
ssh pi "bash ~/robot/scripts/deploy.sh"
```

The tests need no API key and make no network calls: a fake client scripts the
model's replies, and recorded API replies are replayed through the real SDK.

`ssh pi` is an alias in the laptop's `~/.ssh/config` pointing at the Pi's IP
address. If it times out, the address has changed; see `CLAUDE.md`.

## Files

- `robot/main.py`: the command line.
- `robot/agent.py`: the run loop. `robot/api.py`: the model call and its retries.
- `robot/console.py`: everything printed and typed, and Ctrl-C handling.
- `robot/tools.py`: the Pi's own tools. `robot/meta.py`, `robot/spawn.py`: the Meta tools and child runs.
- `robot/instructions.py`, `robot/skills.py`: the library and the skills.
- `robot/prompts.py`: the system prompt's wording.
- `robot/models.py`: model and price tables. `robot/costs.py`, `robot/chats.py`, `robot/history.py`, `robot/datastore.py`, `robot/relay.py`: supporting parts.
- `robot/tui/`: the windowed interface. `app.py`: the main window and how a run and the screen work side by side. `editor.py`, `skillsui.py`: the Instruction Editor and the Skills Manager. `widgets.py`, `dialogs.py`: buttons, lists, text boxes and small windows. `screen.py`: the screen and the keyboard (curses). `text.py`: wrapping and editing text.
- `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`: the tmux launchers for the chat and the windowed interface. `scripts/deploy.sh`: run on the Pi to update it.
- `tests/`: the test suite. `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
- Passwordless sudo for the Pi's user, if the agent should have root.
- `deploy.sh` installs the pinned Python packages and tmux.
