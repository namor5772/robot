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
- Passwordless sudo is enabled for `grobliro` (the user set it up on
  2026-11-15 in `/etc/sudoers.d/010_grobliro-nopasswd`).
- The Pi also has a keyboard and screen attached, so the user can run things at
  its console directly.

## Reaching the Pi

- `ssh pi` (no password). Since 2026-11-15 the `pi` alias in the laptop's
  `~/.ssh/config` points at the Pi's IP address, `10.42.199.40`, with
  `HostKeyAlias robot.local` so the existing host key still verifies. It works
  from both PowerShell and Git Bash.
- That address is assigned by DHCP and can change. If `ssh pi` times out, the
  address has probably changed: use `ssh pi-local` (same Pi via `robot.local`,
  PowerShell only), read the new address with `hostname -I`, and update
  `HostName` under `Host pi`.
- `pi-local` uses mDNS, which Git Bash's ssh cannot resolve and which fails
  intermittently from PowerShell with `Could not resolve hostname robot.local`;
  retrying usually works.
- For scripted commands add `-o BatchMode=yes -o ConnectTimeout=15`.

## Workflow

1. Develop here on Windows.
2. Commit and push to GitHub (`origin`, branch `main`). The laptop remote is
   HTTPS; the Pi's remote is SSH (`git@github.com:namor5772/robot.git`).
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh -t pi "bash ~/robot/scripts/chat.sh"` (inside tmux; `-t`
   gives it a proper terminal). Without tmux:
   `ssh -t pi "cd ~/robot && .venv/bin/python -m robot.main"`.

Never edit files on the Pi directly. Every change goes through git; the Pi only
ever receives code via `git pull --ff-only`, which refuses to run if the Pi's
checkout has local edits.

Keep README.md and this file up to date when features or scripts are added.
The pattern for every change so far: commit, push, deploy, test on the Pi, and
show the user the output.

## The GitHub repo is public

- The repo has been public since 2026-11-15. Everything committed is
  world-readable, including this file and commit messages. Never commit
  secrets, and do not add new personal, account or network details to
  committed files.
- An audit on 2026-11-15 found no secrets in any commit, and only the owner has
  write access. The user reviewed the findings and chose to keep the setup as
  it is. Do not change access, keys or security settings unasked.

## Running and testing

- At the Pi's own console: `cd ~/robot` then `.venv/bin/python -m robot.main`.
- It must be run from `~/robot` (so Python finds the `robot` package) and with
  the venv's Python (the system `python3` does not have `anthropic`).
- The program cannot be run on the laptop: there is no API key here. Check
  syntax locally with `py -m py_compile robot/main.py robot/tools.py`, then
  test on the Pi.
- To test the chat non-interactively, pipe lines into it:
  `ssh pi "cd ~/robot && printf 'first message\nsecond message\nexit\n' | .venv/bin/python -m robot.main"`
  The piped lines are not echoed, so the output shows only `you>` and replies.
- To test a tool function directly, or probe an API response, feed a Python
  script to the Pi over stdin so nothing is written there (from Git Bash):
  `ssh pi "cd ~/robot && .venv/bin/python -" < script.py`
  The same works for shell scripts with `bash -s`, but an `ssh` command inside
  such a script needs `-n`, or it reads the rest of the script as its input.
- To simulate a missing temperature sensor, set `robot.tools.CPU_TEMP_FILE` to
  a path that does not exist before calling `robot.main.main()`.
- Chat tests cost API credit, and web search tests also cost per search.
- On this laptop, long heredocs with quotes passed to the Bash tool have
  broken twice. Use the Write and Edit tools for file content instead.

## When the SSH connection drops

- The chat runs inside the SSH session. If the laptop goes into standby or its
  Wi-Fi drops, Windows resets the connection and the client prints
  `client_loop: send disconnect: Connection reset`. The Pi then closes the
  session and the robot process ends with it, so that conversation is lost.
  Nothing else is affected: reconnect and start the chat again. First seen on
  2026-11-16, caused by laptop standby.
- `scripts/chat.sh` avoids this by running the chat inside tmux (the user asked
  for it on 2026-11-16). It uses its own tmux socket and session, both named
  `robot`, with `scripts/tmux.conf`, so drive it with `tmux -L robot ...`.
  Run again, it reattaches to a live session and ignores its arguments.
  Detach is Ctrl-B then D. `ROBOT_TMUX_DETACHED=1` starts the session without
  attaching, which is how to test it without a terminal:
  `tmux -L robot send-keys -t robot 'text' Enter` types into it and
  `tmux -L robot capture-pane -p -t robot` reads the screen.
- To see why a session ended, run `sudo journalctl -t sshd-session --since today`
  on the Pi. The close and error lines are not under `-u ssh`: after login the
  session process is moved into its own login scope. On the laptop, standby
  shows as Kernel-Power events 506 (enter) and 507 (leave) in the System log.
- The Pi's Wi-Fi has power saving on by default, and `iw` is not installed.

## Layout

- `robot/main.py`: entry point, the interactive chat loop (details below).
- `robot/tools.py`: the tools the model can call. `ALL_TOOLS` run on the Pi;
  `SERVER_TOOLS` run on Anthropic's servers.
- `robot/__init__.py`: empty; makes `robot` a package so `-m robot.main` works.
- `scripts/deploy.sh`: runs on the Pi. `git pull --ff-only`, then
  `pip install -r requirements.txt` into `.venv`, then installs tmux if it is
  missing. Its body is inside a `main` function so the pull can replace the
  file safely. A change to `deploy.sh` itself only takes effect on the deploy
  after the one that pulls it.
- `scripts/chat.sh`, `scripts/tmux.conf`: the tmux launcher and its settings.
- `requirements.txt`: `anthropic==2.8.0`, `python-dotenv==1.2.4`. Pinned on
  purpose: the engine depends on exact SDK behaviour (2.8.0 sends API version
  2026-10-21, has no `temperature` parameter, and is built on `httpx2`).
- `.venv/` on the laptop (gitignored): Python 3.12 with the same pinned
  packages, for running tests locally with `.venv\Scripts\python.exe`. There is
  still no API key on the laptop.
- `.gitattributes`: forces LF line endings on `*.sh` and `*.conf`.

## Current state of the agent (`robot/main.py`)

A text chat agent with four tools. It prompts `you>` and prints the reply after
`robot>`. `exit`, `quit`, `bye` or Ctrl-D quits; Ctrl-C during a reply cancels
that reply. The startup banner prints a `Tools:` line listing what is active.

### Model and prompt

- Model: `claude-opus-5-5`, set by the `MODEL` constant, at `effort: "low"`.
- System prompt: the `SYSTEM_PROMPT` constant in `main.py`. It tells the model
  it is the robot's brain running on the Pi, to speak in the first person, to
  claim only abilities it has tools for, never to invent sensor readings, and
  to reply briefly in plain text (the Pi console does not render Markdown).
  It names no hardware, personality or user name. The user approved its wording;
  show any proposed change to it before implementing.

### Tools

Three run on the Pi and are `Tool` entries in `ALL_TOOLS` in `robot/tools.py`
(a definition for the model, a `run` function, and an `is_available` probe).
`available_tools()` probes each at startup and only working ones are sent to
the model. To add a Pi tool, add an entry there; `main.py` needs no change.

- `run_shell_command` (inputs: `command`, optional `timeout_seconds`): runs any
  bash command on the Pi as user `grobliro`, and with passwordless sudo that
  means root. The user explicitly asked (2026-11-15) for NO guardrails: no
  confirmation prompt, no allowlist, no blocked commands. Do not add any
  without being asked. What it does have is plumbing only: a model-chosen
  timeout (default 60 s, no cap; the whole process group is killed on timeout
  or Ctrl-C), stdin from `/dev/null` so commands cannot read the chat's
  keyboard, and output trimmed to `MAX_OUTPUT_CHARS` (20,000) per stream. Each
  call is a fresh shell in the home directory. Offered only on POSIX machines
  with bash, so never on the laptop.
- `get_current_datetime` (no inputs): the Pi's local date, weekday, time and
  timezone (Australia/Sydney) from its system clock. Always available. The Pi
  has no battery-backed clock, so the time is wrong if it boots without network.
- `get_cpu_temperature` (no inputs): reads
  `/sys/class/thermal/thermal_zone0/temp`. Offered only if that read succeeds
  at startup.

One runs on Anthropic's servers and is declared in `SERVER_TOOLS` in
`robot/tools.py`:

- `web_search` (`web_search_20260209`, `max_uses: 5` per request; searches are
  billed per use). There is no code for it on the Pi and no availability probe.
  This variant makes the model run internal `code_execution` steps to filter
  results; `main.py` hides those and prints one `[tool: web_search: <query>]`
  line per search. In this mode text blocks carry no citations (`citations` is
  `None`), so sources are not listed; the basic `web_search_20250305` variant
  would be the way to get citations.

Consequences of this combination to keep in mind: the model can read
`~/robot/.env`, can edit the checkout (which would make `git pull --ff-only`
refuse to run), and can act with root on text it reads from web search results.

There is still no purpose-built tool for motors, a camera, a microphone or a
speaker. The shell tool is the catch-all.

### How the loop works

- `reply()` is a manual tool loop: it keeps requesting while `stop_reason` is
  `tool_use`, runs the requested Pi tools, and sends all results back in one
  user message. A tool that raises is reported to the model as an `is_error`
  result. A `pause_turn` stop reason (a server tool still working) is resumed
  by resending, up to `MAX_PAUSES` times.
- Each Pi tool call prints `[tool: name]`, followed by its inputs as JSON when
  it has any, e.g. `[tool: run_shell_command: {"command": "uptime"}]`.
- Replies are streamed with `client.beta.messages.stream(...)`, iterating
  events: `text` events are printed, and `content_block_stop` events are
  checked for web searches.
- Conversation history is kept in memory for the session and resent each turn.
  Nothing is saved between runs.
- The whole `response.content` is appended to the history, not just the text,
  because thinking, tool-use and search-result blocks must be passed back
  unchanged on later requests.
- Server-side refusal fallbacks are on (`betas=["server-side-fallback-2026-07-01"]`,
  `fallbacks="default"`), which is why the beta endpoint is used.
- Top-level `cache_control` enables automatic prompt caching.
- On an API error everything the failed turn added is removed from the history
  and the loop continues.
- `.env` is located relative to `main.py`, not the working directory.

## Conventions

- Shell scripts must keep LF line endings; they run under bash on the Pi.
- The Pi has only 512 MB RAM (about 415 MB usable): keep dependencies light and
  avoid packages that need compiling on-device (piwheels and aarch64 wheels
  have covered everything so far).
- Use the official `anthropic` SDK. For any API change, load the `claude-api`
  skill first; model IDs and request shapes change often.
- No external hardware (motors, sensors, camera, speaker) is wired into the
  code yet, and what is physically attached to the robot has not been recorded
  here. Ask before assuming any.
