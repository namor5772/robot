# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot. It is developed
on a Windows laptop and runs on a Raspberry Pi.

## Target device

- Raspberry Pi Zero 2 W, 512 MB RAM
- 64-bit Raspberry Pi OS Lite (Trixie)
- Python 3.13.5
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API key: `~/robot/.env` (`ANTHROPIC_API_KEY=...`). It exists only on the Pi.
  Never commit it; `.env` is in `.gitignore`.
- The Pi also has a keyboard and screen attached, so the user can run things at
  its console directly.

## Reaching the Pi

- `ssh pi` (no password). Use the PowerShell tool (Windows OpenSSH), not Git Bash.
- Git Bash's ssh has never resolved `robot.local` (mDNS). PowerShell usually
  does, but it fails intermittently with `Could not resolve hostname
  robot.local`. When that happens, run the same command again.
- For scripted commands add `-o BatchMode=yes -o ConnectTimeout=15`.

## Workflow

1. Develop here on Windows.
2. Commit and push to GitHub (`origin`, branch `main`). The laptop remote is
   HTTPS; the Pi's remote is SSH (`git@github.com:namor5772/robot.git`).
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh -t pi "cd ~/robot && .venv/bin/python -m robot.main"`
   (`-t` gives the chat a proper terminal).

Never edit files on the Pi directly. Every change goes through git; the Pi only
ever receives code via `git pull --ff-only`, which refuses to run if the Pi's
checkout has local edits.

Keep README.md and this file up to date when features or scripts are added.

## Running and testing

- At the Pi's own console: `cd ~/robot` then `.venv/bin/python -m robot.main`.
- It must be run from `~/robot` (so Python finds the `robot` package) and with
  the venv's Python (the system `python3` does not have `anthropic`).
- The program cannot be run on the laptop: there is no API key here. Check
  syntax locally with `py -m py_compile robot/main.py`, then test on the Pi.
- To test the chat non-interactively, pipe lines into it:
  `ssh pi "cd ~/robot && printf 'first message\nsecond message\nexit\n' | .venv/bin/python -m robot.main"`

## Layout

- `robot/main.py`: entry point, an interactive chat loop (details below).
- `robot/tools.py`: the tools the model can call, each run locally on the Pi.
- `robot/__init__.py`: empty; makes `robot` a package so `-m robot.main` works.
- `scripts/deploy.sh`: runs on the Pi. `git pull --ff-only`, then
  `pip install -r requirements.txt` into `.venv`.
- `requirements.txt`: `anthropic`, `python-dotenv` (unpinned; the Pi currently
  has `anthropic` 2.8.0, which is built on `httpx2`).
- `.gitattributes`: forces LF line endings on `*.sh`.

## Current state of the chatbot (`robot/main.py`)

- A plain text chatbot. Prompts `you>`, prints the reply after `robot>`.
  `exit`, `quit`, `bye` or Ctrl-D quits; Ctrl-C during a reply cancels that reply.
- Model: `claude-opus-5-5`, set by the `MODEL` constant, at `effort: "low"`.
- No system prompt. The model does not know it is a robot.
- One tool: `get_cpu_temperature`, which reads
  `/sys/class/thermal/thermal_zone0/temp` on the Pi. It cannot move anything,
  run commands or search the web.
- Tools live in `robot/tools.py` as `Tool` entries in `ALL_TOOLS` (definition,
  `run` function, `is_available` probe). `available_tools()` probes each one at
  startup and only working tools are sent to the model, so on a machine without
  the sensor the chatbot runs with no tools. To add a tool, add an entry there.
- `reply()` is a manual tool loop: it keeps requesting while `stop_reason` is
  `tool_use`, runs the requested tools, and sends all results back in one user
  message. A tool that raises is reported to the model as an `is_error` result.
  Each tool call prints a `[tool: name]` line.
- Conversation history is kept in memory for the session and resent each turn.
  Nothing is saved between runs.
- Replies are streamed with `client.beta.messages.stream(...)`.
- The whole `response.content` is appended to the history, not just the text,
  because thinking blocks must be passed back unchanged on later turns.
- Server-side refusal fallbacks are on (`betas=["server-side-fallback-2026-07-01"]`,
  `fallbacks="default"`), which is why the beta endpoint is used.
- Top-level `cache_control` enables automatic prompt caching.
- On an API error everything the failed turn added is removed from the history
  and the loop continues.
- `.env` is located relative to `main.py`, not the working directory.

## Conventions

- Shell scripts must keep LF line endings; they run under bash on the Pi.
- The Pi has only 512 MB RAM: keep dependencies light and avoid packages that
  need compiling on-device (piwheels and aarch64 wheels have covered everything
  so far).
- Use the official `anthropic` SDK. For any API change, load the `claude-api`
  skill first; model IDs and request shapes change often.
- No external hardware (motors, sensors, camera, speaker) is wired into the code yet,
  and what is physically attached to the robot has not been recorded here. Ask
  before assuming any.
