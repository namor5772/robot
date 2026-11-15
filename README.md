# robot

Anthropic-API agent "brain" for a small robot running on a Raspberry Pi Zero 2 W.

It is a text chat agent: it talks to Claude (`claude-opus-5-5`) and remembers
the conversation for the session. A system prompt (in `robot/main.py`) tells it
that it is the robot and to answer briefly in plain text.

## Tools

| Tool | Runs on | What it does |
|---|---|---|
| `run_shell_command` | The Pi | Runs any bash command as the Pi's user and returns the output. |
| `get_current_datetime` | The Pi | Reads the date, time and timezone from the Pi's clock. |
| `get_cpu_temperature` | The Pi | Reads the CPU temperature. Offered only if the sensor can be read. |
| `web_search` | Anthropic's servers | Searches the web, up to 5 searches per request. Billed per search. |

The shell tool is deliberately unrestricted: no confirmation, no allowlist, no
blocked commands, and the Pi has passwordless sudo, so the agent has root. It
can read `~/robot/.env`, change any file, and act on what it reads from the web.
To take root away, run `sudo rm /etc/sudoers.d/010_grobliro-nopasswd` on the Pi.

Each tool call is shown as it happens, for example
`[tool: run_shell_command: {"command": "uptime"}]`.

There is no tool yet for motors or other attached hardware.

## Running it

At the Pi's console:

```bash
cd ~/robot
.venv/bin/python -m robot.main
```

Or from the laptop:

```powershell
ssh -t pi "cd ~/robot && .venv/bin/python -m robot.main"
```

The banner lists the active tools. Type a message at `you>`. Type `exit` or
press Ctrl-D to quit; Ctrl-C stops a reply or a running command.

Over SSH the chat lives inside the connection. If the laptop sleeps or the
connection drops, the chat ends and its conversation is lost; reconnect and
start it again.

## Workflow

Develop on the laptop, push to GitHub, deploy to the Pi. Never edit files on the Pi.

```powershell
git push
ssh pi "bash ~/robot/scripts/deploy.sh"
```

`ssh pi` is an alias in the laptop's `~/.ssh/config` pointing at the Pi's IP
address. If it times out, the address has changed; see `CLAUDE.md`.

## Files

- `robot/main.py`: loads `~/robot/.env` and runs the chat loop, streaming each reply and running the tools the model asks for.
- `robot/tools.py`: the tool definitions. The Pi tools are probed at startup and skipped if they do not work on this machine.
- `scripts/deploy.sh`: run on the Pi; `git pull --ff-only` and `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv`.
- `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
- Passwordless sudo for the Pi's user, if the agent should have root.
