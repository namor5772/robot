# CLAUDE.md

This repo is the Anthropic-API agent "brain" for a small robot. It is developed
on a Windows laptop and runs on a Raspberry Pi. Since 2026-11-16 the program is
a terminal port of the owner's MyAgent harness (see "Where it comes from").

## Target device

- Raspberry Pi Zero 2 W, 512 MB RAM (about 415 MB usable), 4 cores
- 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13.5, no tkinter
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API key: `~/robot/.env` (`ANTHROPIC_API_KEY=...`). Never commit it; `.env`
  is in `.gitignore`.
- The program's data: `~/robot-data` (outside the checkout on purpose).
- Passwordless sudo is enabled for `grobliro` (the user set it up on
  2026-11-15 in `/etc/sudoers.d/010_grobliro-nopasswd`).
- `/tmp` is a RAM disk. Importing the Anthropic SDK takes about 15 s and one
  process uses about 77 MB.
- The Pi also has a keyboard and screen attached.

## Reaching the Pi

- `ssh pi` (no password). The `pi` alias in the laptop's `~/.ssh/config` points
  at the Pi's IP address, `10.42.199.40`, with `HostKeyAlias robot.local`. It
  works from both PowerShell and Git Bash.
- That address is assigned by DHCP and can change. If `ssh pi` times out, use
  `ssh pi-local` (same Pi via `robot.local`, PowerShell only), read the new
  address with `hostname -I`, and update `HostName` under `Host pi`.
- `pi-local` uses mDNS, which Git Bash's ssh cannot resolve and which fails
  intermittently from PowerShell; retrying usually works.
- For scripted commands add `-o BatchMode=yes -o ConnectTimeout=15`.

## Workflow

1. Develop here on Windows. Run the tests (below).
2. Commit and push to GitHub (`origin`, branch `main`). The laptop remote is
   HTTPS; the Pi's remote is SSH.
3. Deploy: `ssh pi "bash ~/robot/scripts/deploy.sh"`
4. Run on the Pi: `ssh -t pi "bash ~/robot/scripts/chat.sh"` (inside tmux).

Never edit files on the Pi directly. Every change goes through git; the Pi only
receives code via `git pull --ff-only`, which refuses to run if its checkout
has local edits. `~/robot-data` is the program's own data, not code: the
program and its checks may write there.

Keep README.md and this file up to date when features or scripts are added.
The pattern for every change: tests, commit, push, deploy, check on the Pi,
show the user the output. The user does not want to be asked to test things.

## The GitHub repo is public

- Everything committed is world-readable, including this file, commit
  messages and test fixtures. Never commit secrets, and do not add new
  personal, account or network details to committed files.
- An audit on 2026-11-15 found no secrets in any commit, and only the owner has
  write access. The user reviewed the findings and chose to keep the setup as
  it is. Do not change access, keys or security settings unasked.
- Code adapted from MyAgent gets freshly written comments. MyAgent's own
  comments carry personal and incident details that must not be copied here.

## Running and testing

- Unit tests, no network and no cost, on the laptop (Git Bash):
  `.venv/Scripts/python.exe -m unittest discover -s tests -t .`
  and on the Pi: `.venv/bin/python -m unittest discover -s tests -t .`
  Run both: the Pi has a different Python and real process groups.
- `tests/fakes.py` has a fake client that scripts the model's replies
  (`FakeClient`, `reply`, `tool_use`, ...), a piped console and a terminal
  console. `tests/test_wire.py` drives the real SDK over a mock network with
  recorded replies in `tests/fixtures/*.sse`; `tests/record_fixtures.py`
  re-records them (paid, a few cents; it scrubs signatures and ids).
- Tests write only into temp folders, never into the repo or `~/robot-data`.
- The laptop DOES have an `ANTHROPIC_API_KEY` in its environment. So
  `python -m robot.main` on the laptop makes real, billed calls. Paid checks
  are done on the Pi; on the laptop use the unit tests or `--dry-run`, and set
  `ROBOT_DATA_DIR` to a temp folder so nothing lands in `~/robot-data` there.
- A paid check on the Pi without a terminal: pipe lines in.
  `ssh pi "cd ~/robot && printf 'first\nsecond\n' | .venv/bin/python -m robot.main --model claude-haiku-5-5"`
  Piped lines are echoed, and the end of input ends the conversation.
  `--model claude-haiku-5-5` keeps checks cheap (a whole chat for well under a
  cent); the default Opus chat costs about 5 cents to start.
- A check that needs a real terminal (Ctrl-C, prompts): start the chat in tmux
  detached and drive it. `ROBOT_TMUX_DETACHED=1 bash scripts/chat.sh ...`, then
  `tmux -L robot send-keys -t robot -l -- 'text'`, `send-keys -t robot Enter`,
  `send-keys -t robot C-c`, and `tmux -L robot capture-pane -p -t robot` to
  read the screen. Wait for the last line to be `you>` before typing.
- To run a script on the Pi without writing a file there, feed it over stdin:
  `ssh pi "cd ~/robot && .venv/bin/python -" < script.py` or `bash -s`. An
  `ssh` command inside such a script needs `-n`.
- `--dry-run` prints the exact first request; `--debug` prints every request.
- Paid checks that need saved instructions or skills create them in
  `~/robot-data` with names starting `ZZ ` (instructions) and `zz-` (skills),
  through a small script fed over stdin that uses `robot.instructions` and
  `robot.skills`, and remove them afterwards. The chats and cost-log lines of
  those checks are left in place: they are a true record of what was spent.
- To check that two runs share the prompt cache, start them within five
  minutes of each other: the second one's first `call 1:` line should show a
  large `cache_read` and a small `cache_write`.
- Some tests start real processes (`test_spawn`, `test_costs`). One such test
  was timing-dependent on a busy Pi and was fixed on 2026-11-16; if a test
  fails once and then passes, find the race instead of rerunning until green
  (running the suite with all four cores loaded brought that one out).
- On this laptop, long heredocs with quotes passed to the Bash tool have
  broken several times. Use the Write and Edit tools for file content.

## State on 2026-11-16

- The instruction library on the Pi holds only `Default`, and there are no
  skills. The user has been shown how to create both by asking in a chat.
- 878 tests pass on the laptop and on the Pi.
- No hardware tools exist yet beyond the CPU temperature reading.

## When the SSH connection drops

- Without tmux the chat belongs to the SSH session: if the laptop sleeps or
  its Wi-Fi drops, the session is reset and the chat dies with it. `chat.sh`
  avoids that by running the chat inside tmux, on its own socket and session,
  both named `robot` (`tmux -L robot ...`), with `scripts/tmux.conf`. Run
  again, it reattaches and ignores its arguments. Detach is Ctrl-B then D.
- When the program ends, `chat.sh` runs `stty sane` and then waits for Enter
  so the last lines can be read. The `stty sane` matters: a program killed
  outright leaves the terminal in raw mode, and Enter was not recognised.
- tmux keeps a chat alive across a dropped connection, not across a reboot of
  the Pi. Nothing starts tmux at boot.
- To see why an SSH session ended: `sudo journalctl -t sshd-session --since today`
  on the Pi (not `-u ssh`). On the laptop, standby shows as Kernel-Power events
  506 and 507 in the System log.
- A hang-up or SIGTERM winds the run down properly (cost logged, chat saved).

## Layout

- `robot/main.py`: command line. Chooses the run's settings, shows the banner,
  asks for the task, starts the agent. Imports nothing heavy, so `--list`,
  `--skills` and `--help` are instant; the SDK is loaded on a background
  thread (`ClientLoader`) while the person types.
- `robot/agent.py`: `Agent`, one run from first message to end.
- `robot/api.py`: `build_request` (the one place a request is shaped),
  streaming, and the retry ladder. The only module that imports `anthropic`.
- `robot/console.py`: `Console` (all output and input) and `Interrupts`.
- `robot/tools.py`: the Pi's own tools as `Tool` entries in `ALL_TOOLS`.
- `robot/meta.py`: Meta tool schemas, `manage_instructions`, `meta_tools`.
- `robot/spawn.py`: `run_instruction` (child runs).
- `robot/instructions.py`: `RunSettings`, the library, `settings_from_entry`.
- `robot/skills.py`: `SkillStore`, SKILL.md format, `manage_skills`.
- `robot/models.py`: model lists, capability rules, output caps, price tables.
- `robot/costs.py`: per-call cost, the cost log, the in-progress record.
- `robot/history.py`: trimming and repairing the message history.
- `robot/chats.py`, `robot/datastore.py`, `robot/relay.py`, `robot/prompts.py`.
- `scripts/deploy.sh` (runs on the Pi: pull, pip install, install tmux; its
  body is in a `main` function so the pull can replace the file safely),
  `scripts/chat.sh`, `scripts/tmux.conf`.
- `requirements.txt`: `anthropic==2.8.0`, `python-dotenv==1.2.4`. Pinned on
  purpose: 2.8.0 sends API version 2026-10-21, has no `temperature`
  parameter, sends the key as a Bearer token, and is built on `httpx2`.
- `.venv/` on the laptop (gitignored): Python 3.12 with the same packages.
- `.gitattributes`: LF line endings for `*.sh`, `*.conf`, `*.sse`.

## How the agent works

### A run

- A run has `RunSettings`: name, text, model, thinking_mode, thinking_budget,
  fast_mode, meta, conversational, blocked_tools, skill_modes, upgrade_target.
- With `-l NAME` they come from that entry of `agent_instructions.json`.
  Without it, from the entry named `Default` (created on first use; model
  `claude-opus-5-5`, level Low, Meta on, Convo on), and the task is typed at
  `you>`. `--model` and `--mode` override one run.
- A plain chat borrows only `Default`'s settings: its run has no name (chat
  files are `Agent_<time>`, the cost log's instruction field is empty) and any
  text saved in `Default` is ignored. `-l Default` runs it as a named
  instruction, text included.
- An instruction with no text asks for the task when someone is there
  (`first_message`); with `--headless` or `--result-file` it cannot start.
- An entry needs only `text`. Missing settings default to `claude-opus-5-5`,
  Meta off, Convo off, and no stated thinking level, which on that model
  becomes Adaptive (the API's default effort, costlier than Low).
- `settings_from_entry` corrects values the model cannot honour (a thinking
  level it lacks) and warns. An entry for another provider is refused.
- The task is the first user message. The system prompt and the tool list are
  built once (`Agent._freeze_run`) and do not change during the run: the
  prompt cache and the model's saved reasoning are both tied to them. So a
  skill or instruction created mid-run takes effect from the next run.
- The loop (`Agent._loop`) has no step limit. Tool calls run and their results
  go back; `pause_turn` is resumed; a cut-off reply warns. When the model ends
  its turn: with Convo on the person is asked for the next message; otherwise
  the run ends (after up to three nudges if the model had been asking through
  `user_prompt` and stopped).
- Tools marked `parallel_safe` run together on a thread pool first; the rest
  run in order on the main thread. Every call gets a result, run or not.
- At the end (`_end_run`, every step best-effort): cost-log line, in-progress
  record removed, result file, chat saved.

### The system prompt

- `robot/prompts.py`. The owner approved its wording on 2026-11-16: show any
  proposed change before implementing it. It has the robot's identity, a task
  paragraph, one paragraph that depends on Convo (in a conversation: just
  reply; in a single task: you must ask through `user_prompt`), and a
  plain-text rule. Enabled skills and the on-demand skill list are appended by
  `SkillStore.compose_system_prompt`.
- The last thing in the system prompt is the "About this run" paragraph
  (`prompts.run_paragraph`, wording also approved on 2026-11-16): the
  instruction's name, or that it is a plain chat on the `Default` settings, and
  the model the run started on. It is sent as a second system block with no
  cache marker (`api.cache_system`), so runs of different instructions still
  share the cached prompt in front of it. It is fixed like the rest: after an
  `upgrade_model` it still names the starting model, and its last sentence
  (present only when the run has that tool) tells the model to trust the
  tool's result instead.
- Apart from that paragraph nothing dynamic goes into the system prompt.
- Tool descriptions are in `agent.py` (`user_prompt`, `get_skill`), `meta.py`
  and `tools.py`. They are model-facing text too: treat changes with care.

### Tools

- Always: `run_shell_command`, `get_current_datetime`, `get_cpu_temperature`
  (only if the sensor reads at start), `user_prompt`, server-side `web_search`
  (`models.web_search_tool`: `web_search_20260209`, `max_uses` 5; its
  definition alone is about 6,000 tokens of every request).
- `get_skill` when a skill is on demand. Its result adds the skill's folder
  path when the skill has bundled files, so they can be run with the shell.
- With Meta on: `manage_instructions`, `manage_skills`, `run_instruction`,
  `upgrade_model` (about 3,000 more tokens).
- `blocked_tools` removes tools from the offer and refuses them at dispatch.
- The shell tool has NO guardrails by the owner's explicit choice (2026-11-15):
  no confirmation, no allowlist, no blocked commands, and MyAgent's
  blocked-command list is not ported either. Do not add any unasked. Its
  timeout, `/dev/null` stdin and output trimming are plumbing.
- Consequence: the model can read `~/robot/.env`, edit the checkout (which
  would make `git pull --ff-only` refuse), act as root on text from a web
  search, and write skills that later runs load. The banner lists the skills
  in use for that reason.

### Input, output and Ctrl-C

- `Console` prints: `robot>` before each stretch of reply text, `[tool: ...]`
  lines, indented activity and `call N: <cost>` lines (hidden by
  `--no-activity`), `warning:` and `error:` lines (always shown), thinking
  with `--thinking`. Everything shown also goes to the chat's `.txt`.
- Input modes: a terminal (readline `input()`), piped stdin (lines are replies,
  end of input means nobody is there), `--headless` (never reads stdin: a relay
  folder answers, or nobody does).
- At a terminal the chat is forgiving, unlike MyAgent's dialog: an empty line is
  ignored, Ctrl-C cancels the reply or command and returns to `you>`, an API
  error returns to `you>`. Everywhere else MyAgent's rules hold: an empty reply
  ends a conversation, and an empty reply or `exit` to `user_prompt` stops the
  run (`quit` and `stop` there go to the model).
- `Interrupts`: the loop runs on the main thread. The SIGINT handler sets a
  flag and raises `KeyboardInterrupt` only inside `raisable()` regions (the
  stream, backoff waits, `input()`, sequential tools), so bookkeeping is never
  cut in half. SIGTERM and SIGHUP set the stop flag. Three Ctrl-Cs in three
  seconds exit at once.
- Only the main thread reads the terminal. A tool on a pool thread that needs
  the person (a waited child's question) uses `Agent.ask_from_pool`.
- `history.repair_tool_pairs` runs before every request, so a tool call is
  never sent without its result.

### The request

- `api.build_request`: model, system as one cached block, messages with cache
  markers on the two newest user turns, tools, `max_tokens` at the model's
  ceiling (128,000), `thinking {adaptive, display summarized, block_binding
  drop_block}`, `output_config.effort` from the thinking level, `fallbacks
  "default"`, `speed "fast"` when fast mode applies, and the matching betas.
  No temperature anywhere.
- A finished reply is kept in the history whole (thinking and search results
  included); a reply that was cut off, refused or interrupted is kept as text.
  MyAgent keeps text only in every case.
- Retry ladder (`api.call_model`, 10 attempts): rate limits, overload and
  connection errors back off; a feature the API refuses (fast mode, fallbacks,
  binding, the newer search tool, a too-high output cap) is recorded in
  `Learned` and no longer sent; a context overflow trims the oldest rounds in
  place and retries. The rungs match on the API's error wording.

### Cost, chats, records

- `models.PRICING` and friends price each call by the model and speed that
  served it, plus the web search fee. The cost log is
  `~/robot-data/APICostLog_<host>.txt`, one line per run in MyAgent's format.
- `~/robot-data/runs/agent_run_<pid>.json` is rewritten after every call and
  removed at the end. A leftover from a killed run is logged at the next start
  with `unfinished@call<N>`.
- Every run saves `saved_chats/<Instruction or Agent>_<timestamp>.json` and a
  live `.txt`. Chats are never loaded back.
- An interrupted call is costed from what had streamed (an estimate).

### Meta tools and child runs

- `manage_instructions` (in `meta.py`): `create` takes model settings it is not
  given from the calling run, and writes no `skill_modes` unless asked (a map
  switches off every skill it does not name). Keys of other programs in an
  entry are preserved.
- `manage_skills` (in `skills.py`) works on the run's `SkillStore`. Saving
  writes global modes only, never a run's session modes, and only the skills
  this run changed.
- `upgrade_model` (`Agent.do_upgrade_model`): once per run, to the
  instruction's `upgrade_target` or the default `claude-fable-5-2` at Max. The
  cost log gets `upgraded-from=<model>@call<N>` and a per-model split.
- `run_instruction` (`spawn.py`): a child is `python -m robot.main -l NAME
  --headless ...` in its own session. At most two alive per parent, none when
  free memory is under 110 MB, and a child of a child cannot start children.
  A waited child reports through a result file; its questions go through a
  relay folder and are answered from `answers`, or put to the person at the
  parent's terminal. A child nobody waits for and nobody answers stops at its
  first question. Temp files are in `~/robot-data/tmp`.

## Where it comes from

- MyAgent is the owner's tkinter agent app, in the folder
  `Claude_Python_Testbed` next to this one on the laptop. Its package cannot
  be imported on the Pi (every module imports tkinter), so its engine logic
  was copied and adapted here. That repo documents itself in its `CLAUDE.md`
  and `docs/claude/myagent/`.
- Mapping: `streaming_mixin.py` (loop, cost) -> `agent.py`, `costs.py`;
  `anthropic_mixin.py` -> `api.py`; `ui_mixin.py` capability helpers and the
  tables in `constants.py` -> `models.py`; `helpers.py` -> `history.py`;
  `instructions_mixin.py` -> `instructions.py`, `meta.py`; `skills_mixin.py`
  and `datapaths.py` -> `skills.py`, `spawn.py`, `datastore.py`;
  `chat_mixin.py` -> `chats.py`; `relay.py` -> `relay.py`.
- Left out on purpose: all GUI, the safety confirm system, other providers,
  MyAgent's file, document, desktop, browser, mail and MCP tools, OneDrive
  sharing, images, voice, the live model listing. MyAgent runs on SDK 0.84.0;
  this runs on 2.8.0, which is why temperature and several of MyAgent's
  workarounds are gone.
- File formats match MyAgent's (`agent_instructions.json`, `SKILL.md`, the
  cost log, the relay files), so data can be copied across. MyAgent skills
  name tools the robot lacks (`run_command`, not `run_shell_command`).
- When Anthropic releases a model, update `robot/models.py`: `FALLBACK_MODELS`,
  `MAX_OUTPUT_TOKENS`, the capability rules if the family behaves differently,
  and `PRICING` (plus `FAST_PRICING` and `LONG_CONTEXT_PRICING` where they
  apply). A model with no price row is warned about at run start and its runs
  are not written to the cost log. MyAgent and SelfBot hold the other two
  copies of these tables.

## Conventions

- Shell scripts and tmux config keep LF line endings.
- Keep dependencies light: 512 MB RAM, and nothing that needs compiling on the
  Pi. The program itself uses the standard library plus the two pinned packages.
- For any Anthropic API change, load the `claude-api` skill first; model IDs
  and request shapes change often. Test what the API accepts with a paid check
  on Haiku before relying on it.
- No hardware beyond the Pi itself (motors, sensors, camera, speaker) is wired
  into the code, and what is attached to the robot has not been recorded here.
  Ask before assuming any.
