# How the agent works

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

## A run

- A run has `RunSettings`: name, text, model, thinking_mode, thinking_budget,
  fast_mode, meta, conversational, blocked_tools, skill_modes, upgrade_target,
  memory (see "Memory").
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

## The system prompt

- `robot/prompts.py`. The owner approved its wording on 2026-11-16: show any
  proposed change before implementing it. It has the robot's identity, a task
  paragraph, one paragraph that depends on Convo (in a conversation: just
  reply; in a single task: you must ask through `user_prompt`), and a
  plain-text rule. Enabled skills and the on-demand skill list are appended by
  `SkillStore.compose_system_prompt`.
- Its first paragraph is the owner's own text since 2026-11-24: four lines
  that give the robot its name and its character, typed by the owner and
  put in as given, spelling and line breaks included (one word was changed
  later that day at the owner's word: "goal" became "jail", twice; and on
  2026-11-25 the name in its first line was changed, with the two saved
  instructions on the Pi whose text greets the robot by name) (the other paragraphs
  are wrapped at 78 columns; these lines are not). It took the place of
  "You are the brain of a small robot. You run as a program on a Raspberry
  Pi 3 Model A+ ... The person talking to you is typing at a keyboard
  connected to the robot, or over SSH."
  - So the fixed text no longer says what the robot runs on, nor that it
    is a robot. The second paragraph still says "answer about this
    Raspberry Pi", and the skills and the tool descriptions name the Pi.
    The owner was told and asked for the replacement as it is.
  - The same sentences are in the owner's `robot-identity` skill, which
    the owner had set to disabled by then, so a run gets them once. With
    the skill off, two things it said are in no run's prompt: to speak
    every reply before typing it, and that the voice can be changed with
    `voice_settings`. So the owner had the skill trimmed the same day
    ("trim robot identity"): the two paragraphs that are now in the fixed
    text were taken out, those two things were kept, its description was
    changed to say what it holds now, and it was set to enabled again.
    Enabling it was not asked for in so many words: the owner was told.
  - Nothing in the fixed text names the board's model any more. Until then
    it did, and went on saying "Zero 2 W" from the evening the SD card
    moved (see "Target device") until the next morning. When the card
    moves to another board, what is left to look at is what the skills on
    the Pi say about it: the `cpu-temp` skill's "this Pi starts to slow
    itself down at 80 degrees" was the Zero 2 W's figure (see "State on
    2026-11-18").
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

## Tools

- Always: `run_shell_command`, `get_current_datetime`, `view_image` (see
  "Pictures"), `user_prompt`, server-side `web_search`
  (`models.web_search_tool`: `web_search_20260209`, `max_uses` 5; its
  definition alone is about 6,000 tokens of every request).
- `microphone_listen` where `arecord` exists and `XAI_API_KEY` is set (see
  "Hearing"), and `speak` with `voice_settings` where `aplay` exists and
  the key is set (see "Speaking"). On a PC none of the three is ever
  offered.
- `get_skill` when a skill is on demand. Its result adds the skill's folder
  path when the skill has bundled files, so they can be run with the shell.
- With Meta on: `manage_instructions`, `manage_skills`, `manage_memories`
  (see "Memory"), `run_instruction`, `upgrade_model` (about 3,500 more
  tokens).
- `blocked_tools` removes tools from the offer and refuses them at dispatch.
- The shell tool has NO guardrails by the owner's explicit choice (2026-11-15):
  no confirmation, no allowlist, no blocked commands, and MyAgent's
  blocked-command list is not ported either. Do not add any unasked. Its
  timeout, `/dev/null` stdin and output trimming are plumbing.
- Consequence: the model can read `~/robot/.env`, edit the checkout (which
  would make `git pull --ff-only` refuse), act as root on text from a web
  search, and write skills that later runs load. The banner lists the skills
  in use for that reason.

## Input, output and Ctrl-C

- `Console` prints: `robot>` before each stretch of reply text, `[tool: ...]`
  lines, indented activity and `call N: <cost>` lines (hidden by
  `--no-activity`), `warning:` and `error:` lines (always shown), thinking
  with `--thinking`. Everything shown also goes to the chat's `.txt`.
- Input modes: a terminal (readline `input()`), piped stdin (lines are replies,
  end of input means nobody is there), `--headless` (never reads stdin: a relay
  folder answers, or nobody does). At a terminal, and in the interface, a
  message can also be spoken when hands-free is on (see "Hands-free"); the
  prompt is then read without readline.
- At a terminal the chat is forgiving in two ways, unlike MyAgent's dialog:
  Ctrl-C cancels the reply or command and returns to `you>`, and an API error
  returns to `you>`.
- An empty reply is an answer everywhere, as in MyAgent: it ends a
  conversation, and an empty reply or `exit` to `user_prompt` stops the run
  (`quit` and `stop` there go to the model). At the first `you>` it means no
  task, and the chat ends. Until 2026-11-19 the chat at a terminal ignored an
  empty line and asked again; the owner asked for MyAgent's rule in the
  interface and then in the chat ("ignore nothing"). Do not bring the
  skipping back unasked.
- The one line still ignored at a terminal is one that came from the terminal
  itself (see "Terminal answers that reach the prompt"). `_ask_terminal` asks
  again by itself for that, so the agent never sees it: returned as an empty
  reply it would now end the chat.
- `Interrupts`: the loop runs on the main thread. The SIGINT handler sets a
  flag and raises `KeyboardInterrupt` only inside `raisable()` regions (the
  stream, backoff waits, `input()`, sequential tools), so bookkeeping is never
  cut in half. SIGTERM and SIGHUP set the stop flag. Three Ctrl-Cs in three
  seconds exit at once.
- Only the main thread reads the terminal. A tool on a pool thread that needs
  the person (a waited child's question) uses `Agent.ask_from_pool`.
- `history.repair_tool_pairs` runs before every request, so a tool call is
  never sent without its result.

## The request

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

## Cost, chats, records

- `models.PRICING` and friends price each call by the model and speed that
  served it, plus the web search fee. The cost log is
  `~/robot-data/APICostLog_<host>.txt`, one line per run in MyAgent's format.
- `~/robot-data/runs/agent_run_<pid>.json` is rewritten after every call and
  removed at the end. A leftover from a killed run is logged at the next start
  with `unfinished@call<N>`.
- Every run saves `saved_chats/<Instruction or Agent>_<timestamp>.json` and a
  live `.txt`. Chats are never loaded back.
- Two runs of one instruction started in the same second get different
  names since 2026-11-28 (`chats.claim_chat_stem`): the second is
  `<name>_<pid>`, and a third from the same program `<name>_<pid>_2`.
  Until then the name was only LOOKED UP as free
  (`unique_chat_stem`, still there for the case where no file can be
  made), and both runs looked before either had made a file, so the later
  one's `.json` and `.txt` replaced the earlier one's while the cost log
  kept both lines. Seen with two headless interfaces started by a script
  (see "A headless interface"). Now the name is taken by creating the
  `.txt` with `O_CREAT | O_EXCL`, which only one run can do; `Transcript`
  then appends to that empty file.
- An interrupted call is costed from what had streamed (an estimate).

## Meta tools and child runs

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
  --headless ...` in its own session. A child of a child cannot start
  children. A waited child reports through a result file; its questions go
  through a relay folder and are answered from `answers`, or put to the person
  at the parent's terminal. A child nobody waits for and nobody answers stops
  at its first question. Temp files are in `~/robot-data/tmp`.
- `show_window` (2026-11-27, at the owner's request, after MyAgent's
  parameter of that name): the child's output in a tmux session the person
  can switch to. MyAgent's `headless=false` is not there: a robot child is
  always headless.
  - The child is started exactly as before, by the parent, as its own
    process. Only its stdout goes to a file (`window_*.log` in the data
    folder's `tmp`) in place of nowhere, and a tmux session
    (`child-NAME-PID`, `spawn.window_session`) runs
    `scripts/child-window.sh`, which is `tail --pid` on that file. So the
    waiting, the timeout, the stopping, the memory rule and the count of the
    tree are untouched: tmux owns the viewer, not the child. The other way,
    the child started BY tmux, was not taken: it would be the tmux server's
    child, with the server's environment (no tree name, no depth) and
    nothing for the parent to wait on.
  - Which tmux (`spawn.window_server`): the one the run is in (`$TMUX` is
    set, so no `-L`), which puts the window beside the interface or chat
    the person is looking at; outside tmux the socket `robot-ui`. A check
    names a socket of its own in `ROBOT_CHILD_SOCKET`, which comes first: a
    check run outside tmux would otherwise put a session on the owner's
    `robot-ui`.
  - If that call has to START the tmux server, the server keeps the
    caller's environment for everything started there later. So
    `ROBOT_SPAWN_DEPTH` and `ROBOT_SPAWN_FAMILY` are taken out of it first:
    an interface started on that server afterwards must not count as part
    of some tree, or as a child that may not start children.
  - The session has `detach-on-destroy off`: somebody watching when it
    closes is taken to another session, not out of tmux (at the Pi's own
    screen under the autostart that would end the display). With a client
    attached at the end the script waits for Enter, at most 300 s; with
    none it closes at once.
  - The person is told the session's name by a `console.note` at the start
    (a waited child's report comes only at the end), and the tool's result
    names it for the model. A window that cannot be opened (no tmux, as on
    Windows) is said in the result and the child runs without one.
  - The window shows plain text, no dim lines: the child's stdout is a
    file, not a terminal.
  - Tests: `ChildWindows` (a stand-in for the session), `WindowNames`, and
    `RealWindows` (2 tests with a real tmux on a socket of their own,
    skipped on Windows).
  - The first version went to the Pi untried (the Pi could not be reached
    on 2026-11-27) and `RealWindows` failed there the next morning: tmux
    3.5a refused `set-option -t =NAME` with "no such session: =NAME", so
    the whole call counted as failed although the session had been made.
    That command's target is a pane, and `NAME:` is what it takes. The
    `=NAME` form is fine where a session is the target (`has-session`,
    `list-clients`).
  - Tried by hand on the Pi on 2026-11-28, on sockets of the check's own
    (`zz-try`, and `zz-outer` to give a watching client a terminal): the
    window showed the header and the file's lines; with nobody watching
    the session was gone once the process had ended; with a client
    attached it showed "The child run has ended. Press Enter to close this
    window.", and after Enter the session was gone and the client was on
    the other session of that tmux.
  - A paid check that morning, on Haiku, piped, with
    `ROBOT_CHILD_SOCKET=zz-kid`: a parent with Meta on called
    `run_instruction` with `wait` and `show_window` for a child that
    counted to five. The parent printed "Child run '...' can be watched in
    the tmux session 'child-ZZ-Window-Child-3816': tmux -L zz-kid attach -t
    ...", the session showed the child's banner, its reply and its cost
    lines while it ran, and afterwards the tmux server was gone and `tmp`
    was empty. 0.20 cents for the parent, 0.14 for the child.
  - That check's child was told to "count aloud" and used the `speak`
    tool: the count came out of the speakers, unplanned, with a run of the
    owner's listed in `~/robot-data/runs`. A check's instruction must say
    "use no tools" in so many words BEFORE anything that sounds like
    speaking, or block `speak` and `microphone_listen` in its entry
    (`blocked_tools`).
  - A catch in such a check: `tail --pid` waits while the process is still
    in the kernel's list, and one that has ended but was not waited for by
    its parent still is. The real parent polls its child, so there it ends
    at once; a check that starts a `sleep` must wait for it too.
- How many children run at once is decided by free memory, up to a ceiling
  of 8 (since 2026-11-19, at the owner's request, so that the same code suits
  a Pi 5; until then it was two, fixed). `spawn._why_not_another` starts a child
  only while `MIN_FREE_MB` (110) is available: `CHILD_MB` (80) for the child
  and `SPARE_MB` (30) left over.
  - A child that has just been started holds almost nothing, and the kernel's
    figure does not know what it is about to take. So what each child still
    starting has yet to take (`CHILD_MB` less what it holds now, read from
    `/proc/<pid>/statm`) is taken off the available figure first. Without
    that, several children asked for in one turn would all be started: those
    calls run side by side on the thread pool. `_spawn_lock` makes them be
    judged one after the other.
  - Measured on the Pi on 2026-11-19: a run holds 5 MB at its start and 77 MB
    eleven seconds later; available memory falls by 57 MB, less than the 77,
    because the runs share what they load from the same files. Six children
    asked for at once with 261 MB available: two started, four were refused
    ("... will go to the 2 child runs still starting"), and a third was
    allowed once the two had loaded and 143 MB was left. With a real parent
    run beside them the Pi Zero still comes to two, as before.
  - The available figure is what can be had without pushing anything into
    swap, and the swap here is compressed memory (see "Target device").
    What idle programs would give up to it is not counted until the kernel
    has moved it. So the rule is on the careful side, and the same programs
    can leave less before a squeeze than after one: 120 MB was available
    with two idle interfaces open and 141 to 147 MB with three (2026-11-19,
    see "Several screens, several interfaces").
  - On top of that there is a ceiling, `MAX_CHILDREN` = 8 alive at once,
    which the owner set on 2026-11-19: every child is a paid run, and with
    gigabytes free memory alone would allow dozens. It is checked first and
    has a refusal of its own. On the Pi Zero memory stops a run long before
    it.
  - The 8 is for the WHOLE TREE, at the owner's word: the first run's
    children and the children those start (`MAX_DEPTH` lets a child start
    children, and those none), counted together. The old limit of two was
    per program. The memory allowance for children still starting is for the
    whole tree as well.
  - How the runs of a tree see each other. The first run makes up a name
    (`spawn.family()`); every child gets it in `ROBOT_SPAWN_FAMILY` and
    hands it on. `family_members()` then reads the kernel's list: a process
    counts when its command line starts with `CHILD_COMMAND` and its
    environment carries the tree's name. Nothing is kept in files, so a run
    that is killed drops out of the count by itself. The shell commands a
    child starts inherit the name, which is why the command is looked at
    too. The first run is not a member: nobody handed it a name.
  - Two programs of a tree can be starting a child at the same moment (a
    child and its parent). `_one_start_at_a_time` therefore holds, besides
    the lock between threads, an exclusive hold (`flock`) on the data
    folder's `tmp` while a start is judged and made. A hold that cannot be
    had in ten seconds is done without. Python opens that folder so that a
    child does not inherit the hold.
  - Off Linux none of this can be read, and a program counts its own
    children, as before. `tests/test_spawn.py` builds made-up `/proc` trees
    for Windows, and on the Pi a real tree: its stand-in child `Family`
    starts children of its own (3 tests, skipped on Windows).
  - Where the free memory cannot be read (anywhere but Linux: the PCs'
    tests), `FALLBACK_MAX_CHILDREN` (2) applies.
  - The tool's description in `meta.py` said "at most two can run at the same
    time". It now says that the number depends on the memory that is free and
    is never more than 8 in all, the children of child runs included; the 8
    is taken from `spawn.MAX_CHILDREN`, so the two cannot drift apart.
