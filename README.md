# robot

Anthropic-API agent "brain" for a small robot running on a Raspberry Pi Zero 2 W.

## Workflow

Develop on the laptop, push to GitHub, deploy to the Pi:

```bash
git push
ssh pi "bash ~/robot/scripts/deploy.sh"
ssh -t pi "cd ~/robot && .venv/bin/python -m robot.main"
```

## Files

- `robot/main.py`: loads `~/robot/.env` and runs an interactive chat loop with the Anthropic API, streaming each reply. Type `exit` or press Ctrl-D to quit.
- `scripts/deploy.sh`: run on the Pi; `git pull --ff-only` and `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv`.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed.
