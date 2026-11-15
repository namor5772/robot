# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot.

## Target device

- Raspberry Pi Zero 2 W, 512 MB RAM
- 64-bit Raspberry Pi OS Lite (Trixie)
- Python 3.13.5
- Repo checkout on the Pi: `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API key: `~/robot/.env` (`ANTHROPIC_API_KEY=...`). Never commit it; `.env` is in `.gitignore`.
- Reached with `ssh pi` (no password). The first attempt sometimes fails with
  `Could not resolve hostname robot.local`; just retry.

## Workflow

1. Develop here on Windows.
2. Commit and push to GitHub (`origin`, branch `main`).
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh pi "cd ~/robot && .venv/bin/python -m robot.main"`

Never edit files on the Pi directly. Every change goes through git.

## Layout

- `robot/main.py`: entry point. Loads `.env` and sends one short test message to the Anthropic API, printing the reply.
- `scripts/deploy.sh`: runs on the Pi. `git pull --ff-only`, then `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv`.

## Conventions

- Shell scripts must keep LF line endings (enforced by `.gitattributes`); they run under bash on the Pi.
- The Pi has only 512 MB RAM: keep dependencies light and avoid packages that need compiling on-device.
- Model: `claude-opus-5-5` via the official `anthropic` SDK, with server-side refusal fallbacks enabled.
