# robot

Anthropic-API agent "brain" for a small robot running on a Raspberry Pi Zero 2 W.

Right now it is a text chatbot: it talks to Claude (`claude-opus-5-5`) and
remembers the conversation for the session. It has no system prompt and one
tool: it can read the Pi's CPU temperature (ask "how hot are you?"). The tool
is only offered to the model when the sensor can actually be read. It cannot
control hardware yet.

## Running it

At the Pi's console:

```bash
cd ~/robot
.venv/bin/python -m robot.main
```

Or from the laptop (PowerShell):

```powershell
ssh -t pi "cd ~/robot && .venv/bin/python -m robot.main"
```

Type a message at `you>`. Type `exit` or press Ctrl-D to quit.

## Workflow

Develop on the laptop, push to GitHub, deploy to the Pi. Never edit files on the Pi.

```powershell
git push
ssh pi "bash ~/robot/scripts/deploy.sh"
```

If `ssh pi` fails with `Could not resolve hostname robot.local`, run it again.

## Files

- `robot/main.py`: loads `~/robot/.env` and runs an interactive chat loop with the Anthropic API, streaming each reply.
- `robot/tools.py`: tools the model can call (currently `get_cpu_temperature`); each is probed at startup and skipped if it does not work on this machine.
- `scripts/deploy.sh`: run on the Pi; `git pull --ff-only` and `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv`.
- `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
