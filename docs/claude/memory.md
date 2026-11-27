# Memory

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- Since 2026-11-25, at the owner's request: an instruction with `memory`
  true (Memory in the Instruction Editor, Alt+M; off by default) is
  told at its start what the robot remembers, and its conversation is
  remembered when it ends. `robot/memory.py`. The owner was given four
  options (replaying the last chat, a consolidated memory, the model
  keeping notes itself, looking things up in old transcripts) and took the
  recommendation: the second with the fourth behind it, a separate call on
  a stronger model, on falling asleep, with a fallback on waking.
- The files, in `~/robot-data/memory` (`memory.Store`): `memory.md` (the
  memory, rewritten whole each time), `diary.md` (an entry per
  conversation under a `## start to end` line, only ever added to),
  `state.json` (`last_awake`, and `pending`: the runs still to be
  remembered), `settings.json` (optional, `model`), and `versions/` (the
  memory file as it was before each rewrite, the newest 30). At first
  there was one memory for every instruction that had it on; see "Named
  memories" below.
- Waking: `Agent._freeze_run` puts `Store.prompt_block()` in front of the
  "About this run" paragraph, so it travels in the second system block,
  the one without a cache marker: runs still share the cached prompt.
  The block has an introduction, "You were last awake until ... It is now
  ...", the memory, the newest 7 diary entries, and where the saved chats
  are, with the advice to search them with the shell tool. It is fixed for
  the run like the rest of the prompt.
- That block and the keeper's prompt (below) are model-facing text. They
  were written with the feature and shown to the owner afterwards, with
  the feature, not before: the owner had asked for the build with all
  that had been recommended. Show any later change first, as for
  `prompts.py`.
- Falling asleep: `Agent._fall_asleep` is the first step of `_end_run`,
  before the cost is logged, so the call's cost is on the run's own line
  (the per-model split names both models). `memory.remember` reads the
  run's `.txt` (without the `call N:` lines, the last 300,000 characters
  at most), and `memory.ask_model` sends one request through
  `api.call_model` with no tools, no web search and a console that shows
  nothing (`_Quiet`), so it has the whole retry ladder. `build_request`
  leaves `tools` out of a request that has none. The reply must hold
  `<memory>...</memory>` and may hold `<diary>...</diary>`; anything else,
  a reply cut off, or a stop is `MemoryFailed`: a warning, the old memory
  stays, and the run stays in `pending`.
- The keeper's prompt (`memory._KEEPER`) carries the prompt's first
  paragraph (`prompts.character()`), so it follows a change of name. It
  asks for the first person, five headings, full dates, under 3,000
  words (`memory.MAX_WORDS`; 1,500 until 2026-11-26, when the owner
  doubled it, and the hard cut `MAX_MEMORY_CHARS` went from 20,000 to
  40,000 characters with it, so that a memory of that length is not cut:
  about 4,000 tokens in every call of a run with memory on, once a
  memory is that long), nothing invented, the transcript as a record and not as
  instructions, doubt about `(heard)` lines, and nothing about
  remembering itself or about what the robot is told at every start
  anyway. The last two were added after the first real tries, which
  wrote both into the memory.
- The model is `claude-sonnet-5-5` (`memory.DEFAULT_MODEL`), or
  `ROBOT_MEMORY_MODEL`, or `model` in `settings.json`. The owner asked
  whether a stronger model than the conversation's Haiku would be better
  and took the recommendation.
- A run is noted in `pending` when its chat files are started
  (`Store.begin`: transcript, pid, boot id, start time) and taken out
  when it has been remembered (`Store.settle`). `Agent._remember_unfinished`
  runs before the prompt is fixed: an entry whose process is gone
  (`costs.process_is_robot`), or that is from before a restart, is
  remembered first, with the transcript's own time as its end. So a pulled
  plug, a kill and a failed call are all made up for by the next run with
  memory on, and that run is told the result.
- When the program is being closed (`interrupts.stop` is set: Quit in the
  interface, SIGTERM, a hang-up), nothing is sent: "This conversation will
  be remembered at the next start." Quit waits 15 seconds for a run at
  most, and a call might not fit. After STOP or Ctrl-C alone the
  remembering is done; a second STOP during it leaves it for the next
  start.
- `memory.worth_remembering`: a transcript with fewer than two `you>`
  lines that say something other than an end word (the first is the
  run's own task) is settled without a call. A boot that hears only
  "Bye." costs nothing.
- After a spoken "bye" the order is: the goodbye, "Remembering this
  conversation...", the cost line, the chat saved, power off.
- `manage_instructions` takes and shows `memory`; `--list` and the
  interface's top row say `memory`; the chat's banner says "Memory: on".
- `python -m robot.memory show` prints the block; `try CHAT.txt [--model
  M]` prints what a saved chat would leave and its cost, and writes
  nothing.
- A tool with which the robot remembers or forgets something in the
  middle of a conversation was left for a second step, and built the
  same evening (`manage_memories`, below).
- Tried on the Pi on 2026-11-25:
  - `try` in a scratch copy (the keys read from the checkout's `.env`
    into the environment, not shown) on the owner's newest chat, a short
    one: Sonnet 5.5 took 13 s for $0.0083, Haiku 5.5 14 s for $0.0006.
    Both were usable; both repeated what the fixed prompt says.
  - Then the real program, after the deploy, on a data folder of the
    check's own (`ROBOT_DATA_DIR=/tmp/zz-memdata`, so that the owner's
    memory was not touched; the cost lines of those four runs, $0.035 in
    all, are therefore not in the real cost log), an instruction on Haiku
    with the three sound tools blocked, lines piped in. Run 1 was told a
    cat's name and a plan and remembered them ($0.0075 for the call, 5 s).
    Run 2 named both in its first reply. Run 3 was told a colour and
    killed with `kill -9` while it waited: `pending` held it. Run 4 said
    "Remembering an earlier conversation first...", knew the colour in
    its first reply, and left `pending` empty and three earlier versions.
  - In run 1, told "Hello, I am back" with an empty memory, the robot
    searched the saved chats by itself, found only its own, and said so.
  - Not tried by a session: the interface, hands-free and the power-off
    with memory on. The agent's code is the same there; the owner's test
    was the first. It came that night, after a restart of the Pi at 21:55
    that came up through the autostart on `HandsFreeChatAgent`, with the
    named memory the owner had given it in the editor and with
    `manage_memories` in the run: "All the above changes work well, the Pi
    is now powered off." No session looked at the Pi during that test, so
    what the memory then held is not written down here.
- Memory was switched on for the owner's `HandsFreeChatAgent` that day,
  through `manage_instructions` with a script fed over stdin, because
  that is the instruction the owner asked about. The owner was told.
- Named memories since the same evening, at the owner's request ("build
  the named version with the Memories window"), after the owner had asked
  why instructions could not have different memories:
  - An entry has `memory_name` beside `memory`: '' is the shared memory,
    the `memory` folder itself, and a name is a folder inside it with the
    same files (`memory.Store(datadir, name)`). So what was remembered
    before the change stayed where it was. `settings.json` is one file for
    all of them, in the shared folder.
  - A name is 1 to 40 letters, digits, spaces, `-` or `_`, starting with a
    letter or a digit, and not `versions`, `off`, `shared` or `new`
    (`memory.name_problem`): it becomes a folder, and those words mean
    other things on the screen. A dot is not allowed, so no file of the
    shared folder can be taken for a memory.
  - Nothing creates a memory: the folder appears when a conversation is
    first remembered (`memory.names` lists the folders there are). The
    owner asked whether one would be created and then assigned, and took
    this.
  - An entry whose name will not do gives a run WITHOUT memory and a
    warning, not a run on the shared one: that would write into a memory
    the instruction was never meant to touch.
  - The Instruction Editor's Memory is a `Choice` now (it was a box for
    two hours): off, shared, every name there is as a folder or in an
    instruction, and "new name...", which asks for the name on the spot
    and puts the setting back when the name is given up or refused.
  - `manage_instructions` takes, checks and shows `memory_name`. `--list`
    and the top row say `memory: NAME` for a named one.
- The Memories window (`robot/tui/memoryui.py`, F6, the Memories button):
  the shared memory first, then the named ones; for each, who uses it
  (`memory.users`), its size, the last time awake, and the text with the
  diary under it, read only. Edit (`Store.set_memory`; the diary is not
  edited), Copy (`Store.copy_to`: text, diary and last time awake, not
  the earlier states and not the noted runs), Roll back (a list of the
  earlier states, newest first; the one picked is shown, then a question;
  `Store.roll_back` keeps the state it leaves) and Delete
  (`Store.delete`: a named memory's folder, or the shared memory's own
  files and `versions`, never `settings.json` or the named folders).
  - Every change makes a `Store` afresh, and the memory of the run in
    progress is refused with a message (`_busy`): that run writes the file
    when it ends, over whatever was done in the window.
  - Two changes within one second keep two earlier states: the second
    file's name gets `_2`.
  - The main window's top row has seven buttons now, which do not fit in
    72 columns: under 78 the Help button is not shown
    (`MainWindow.layout`), and F1 and the bottom line still give the help.
  - Tried on the Pi in a tmux of the check's own (`zz-ui`, `--session
    zzm`, a data folder of its own made beforehand with two memories and
    two instructions): the main window at 72 x 20 with the Memories button
    and no Help button, the window at 100 x 26, a copy made with Alt+Y,
    and the editor's Memory list with the copy in it. No run was started.
  - It opens on the memory of the instruction in use, since 2026-11-26
    (`MemoriesWindow._of_instruction`): the owner had found it showing the
    shared memory with an instruction loaded that has a named one, which
    it always did. With memory off in that instruction, or a name that
    will not do, it opens on the shared one. That memory is in the list
    even when nothing has been remembered in it yet and it has no folder:
    it is shown empty, and nothing is created by looking. Tried on the Pi
    in a tmux of the check's own (`zz-ui`, two sessions, a data folder of
    its own): F6 showed the named memory of the one instruction, and for
    the other its unwritten one, listed and empty, with no folder made.
  - `tests/test_tui_memory.py` (26 tests, on every machine).
- `manage_memories`, a fifth Meta tool since the same evening, at the
  owner's request ("build it with delete out"); the function is
  `memory.manage_memories`, the schema in `meta.py`. It had been held
  back as a second step, and the owner asked whether Meta tools for the
  memory made sense.
  - Actions: `list`, `read` (text and the newest 20 diary entries, of any
    memory), `remember` (one thing, 1,000 characters at most, added as a
    dated line under the heading "Asked to remember"), `edit` (the whole
    text anew; an empty one is refused) and `copy`. `name` left out means
    the memory of the calling run; "shared" is the word for the shared
    one; a run without memory must give a name.
  - No `delete` and no `roll_back`, at the owner's word: hands-free hears
    whoever speaks, an edit can be undone from the earlier states, and a
    delete removes those too. Asked for all the same, the tool says that
    the owner does that in the Memories window. The shell tool could still
    remove the files, as it can remove anything. Do not add the two
    actions unasked.
  - `remember` and `edit` go through `Store.set_memory`, so each keeps
    the text as it was. The run's own prompt is fixed and does not show
    the change (the tool's result says so); the remembering at the run's
    end starts from the file as it then is, so the change is carried on.
  - `read` puts the text between two marks and says that the diary
    under it is no part of it, and `edit` refuses a content with a diary
    entry's heading or a mark in it. Both came from the first paid
    check, in which Haiku, asked to forget one thing, gave `edit`
    everything `read` had shown, diary included (the remembering at
    that run's end took it out again).
  - That check, on the Pi, on a data folder of its own ($0.014, Haiku
    with Meta on): "Remember this for me: my cat is called Miso and my
    dog is called Rex" gave one `remember` call, and the run was then
    killed with `kill -9`: the line was in `memory.md`. The next run
    knew both, and "forget about the dog" gave `read` and `edit`. "Now
    delete your whole memory" gave an `edit` with an empty content,
    which was refused, and the robot said that only the owner can erase
    it, in the Memories window.
  - The tool is in the list between `manage_skills` and `run_instruction`,
    so that `upgrade_model` stays last in the Instruction Editor's Tools
    dialog. Its description adds about 450 tokens to every request of a
    run with Meta on (an estimate).
- A paid check of a run with memory on writes into the owner's memory:
  give it a data folder of its own, as above.
- Memory goes with the instruction, whichever way its run is started: the
  interface, the chat, a headless run, a child run. Not looked into: two
  runs that use the same memory at the same time (two interfaces with one
  instruction, or a parent and a child that name the same memory). Each
  would write the memory when it ends; whether the later one keeps what
  the earlier one added has not been tried. `Store.begin` and `settle`
  rewrite `state.json` whole.
- `tests/test_memory.py` (81 tests, on every machine): the files, the
  noted runs, the block, the texts, the call on the fake client, the
  named memories, the tool, and the agent from waking to falling asleep.
