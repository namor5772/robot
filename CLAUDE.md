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

- `ssh pi` (no password). Since 2026-11-15 the `pi` alias in the laptop's
  `~/.ssh/config` points at the Pi's IP address, `10.42.199.40`, with
  `HostKeyAlias robot.local` so the existing host key still verifies. It works
  from both PowerShell and Git Bash.
- That address comes from the router and is not known to be reserved. If
  `ssh pi` times out, the address has probably changed: use `ssh pi-local`
  (same Pi via `robot.local`, PowerShell only), read the new address with
  `hostname -I`, and update `HostName` under `Host pi`.
- `pi-local` uses mDNS, which Git Bash's ssh cannot resolve and which fails
  intermittently from PowerShell with `Could not resolve hostname robot.local`;
  retrying usually works.
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
- System prompt: the `SYSTEM_PROMPT` constant in `main.py`. It tells the model
  it is the robot's brain running on the Pi, to speak in the first person, to
  claim only abilities it has tools for, never to invent sensor readings, and
  to reply briefly in plain text (the Pi console does not render Markdown).
  It names no hardware, personality or user name. The user approved its wording;
  show any proposed change to it before implementing.
- Two tools: `get_cpu_temperature`, which reads
  `/sys/class/thermal/thermal_zone0/temp` on the Pi, and `get_current_datetime`,
  which returns the Pi's local date, time and timezone from its system clock
  (always available).
- Shell tool: `run_shell_command` runs any bash command on the Pi as user
  `grobliro`. The user enabled passwordless sudo on the Pi on 2026-11-15
  (`/etc/sudoers.d/010_grobliro-nopasswd`), so the tool, and `ssh pi`, can run
  anything as root with `sudo`. The user explicitly asked (2026-11-15) for NO
  guardrails: no confirmation prompt, no allowlist, no blocked commands. Do not
  add any without being asked. What it does have is plumbing only: a
  model-chosen timeout (default 60 s, no cap; the whole process group is killed
  on timeout or Ctrl-C), stdin from `/dev/null` so commands cannot read the
  chat's keyboard, and output trimmed to `MAX_OUTPUT_CHARS` per stream. Each
  call is a fresh shell in the home directory. Offered only on POSIX machines
  with bash, so never on the laptop. Tool calls with inputs print them, e.g.
  `[tool: run_shell_command: {"command": "uptime"}]`.
- Consequence to keep in mind: with the shell tool the model can read
  `~/robot/.env`, edit the checkout (which would break `git pull --ff-only`),
  and act on text it reads from web search results.
- Web search: `SERVER_TOOLS` in `robot/tools.py` declares Anthropic's
  server-side `web_search_20260209` tool (`max_uses: 5` per request; searches
  are billed per use). It runs on Anthropic's servers, so there is no code for
  it on the Pi and no availability probe. This variant makes the model run
  internal `code_execution` steps to filter results; `main.py` hides those and
  prints one `[tool: web_search: <query>]` line per search. In this mode text
  blocks carry no citations (`citations` is `None`), so sources are not listed;
  the basic `web_search_20250305` variant would be the way to get citations.
  A `pause_turn` stop reason is resumed by resending, up to `MAX_PAUSES` times.
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
