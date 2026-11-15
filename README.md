# robot

Anthropic-API agent "brain" for a small robot running on a Raspberry Pi Zero 2 W.

Right now it is a text chatbot: it talks to Claude (`claude-opus-5-5`) and
remembers the conversation for the session. A system prompt (in
`robot/main.py`) tells it that it is the robot and to answer briefly in plain
text. It has three tools: it can search the web, and it can read the Pi's CPU temperature (ask "how hot are you?")
and the current date and time from the Pi's clock. The temperature tool
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

`ssh pi` is an alias in the laptop's `~/.ssh/config` pointing at the Pi's IP address. If it times out, the address has changed; see `CLAUDE.md`.

## Files

- `robot/main.py`: loads `~/robot/.env` and runs an interactive chat loop with the Anthropic API, streaming each reply.
- `robot/tools.py`: tools the model can call (`get_cpu_temperature` and `get_current_datetime` run on the Pi; `web_search` runs on Anthropic's servers); each is probed at startup and skipped if it does not work on this machine.
- `scripts/deploy.sh`: run on the Pi; `git pull --ff-only` and `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv`.
- `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
