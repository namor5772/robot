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

Without tmux: `cd ~/robot && .venv/bin/python -m robot.main`.

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

There is no editor. Ask the agent: with Meta on it creates, changes and
deletes instructions and skills itself ("save this as an instruction called
Night watch", "make the default model Haiku"). Changes apply from the next
run, not the one you are in.

The library is one JSON file, `~/robot-data/agent_instructions.json`, so it can
also be edited by hand. Each instruction is a named block, for example:

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
| `web_search` | always | Searches the web on Anthropic's servers, up to 5 searches per request. |
| `user_prompt` | always | Asks you a question and waits for the answer. |
| `get_skill` | if a skill is on demand | Fetches an on-demand skill's text. |
| `manage_instructions` | Meta on | Lists, reads, creates, updates and deletes instructions. |
| `manage_skills` | Meta on | The same for skills and their bundled files. |
| `run_instruction` | Meta on | Runs another instruction as a child run. |
| `upgrade_model` | Meta on | Moves the rest of the run to a stronger model. |

The shell tool is deliberately unrestricted: no confirmation, no allowlist, no
blocked commands, and the Pi has passwordless sudo, so the agent has root. It
can read `~/robot/.env`, change any file, and act on what it reads from the
web. With Meta on it can also write skills that later runs load, so text it
picked up can outlast a session: the start banner lists the skills in use. To
take root away, run `sudo rm /etc/sudoers.d/010_grobliro-nopasswd` on the Pi.
An instruction's `blocked_tools` list removes tools from its runs.

A child run is a second copy of the program. On the Pi Zero it takes about 15
seconds to start and about 80 MB of memory, so at most two run at once.

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

These files use MyAgent's formats, so instructions and skills can be copied
between the two programs. Nothing in `~/robot-data` is backed up.

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
- `scripts/chat.sh`, `scripts/tmux.conf`: the tmux launcher. `scripts/deploy.sh`: run on the Pi to update it.
- `tests/`: the test suite. `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
- Passwordless sudo for the Pi's user, if the agent should have root.
- `deploy.sh` installs the pinned Python packages and tmux.
