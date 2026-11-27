# State on 2026-11-18

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- The instruction library on the Pi holds `Default` (Opus, Medium, Convo on,
  Meta on) and `Zero state chat` (Opus, Medium, Convo on, Meta off, no text).
  The owner moved both from Low to Medium that evening, in the Instruction
  Editor.
- The Pi had two skills on that day, both made by the owner in chats, in
  `~/robot-data/skills`:
  - `robot-identity` (enabled, so its text is in every run's system prompt):
    the robot's name and one sentence on what it is. Since 2026-11-24 the
    name and the character are in the fixed prompt instead (see "The
    system prompt"), and the skill holds only how to reply (briefly, and
    aloud before typing) and that the voice can be changed.
  - `wifi-monitor` (on demand, fetched with `get_skill`): describes a Wi-Fi
    monitor the robot set up on 2026-11-18. That monitor is not part of this
    repo: a bash loop in `~/wifimon` that pings the gateway every 10 s, logs
    each change to `~/wifimon/wifi.log`, and starts at boot from the user's
    crontab.
- A third skill since 2026-11-20, `cpu-temp` (on demand), made at the owner's
  request to stand in for the removed `get_cpu_temperature` tool: it gives
  the model the one shell command that prints the CPU temperature the way
  the tool did ("45.1 degrees Celsius"), and says when to run it. It was
  created with a script fed over stdin that calls `manage_skills`. It was
  made enabled, and the owner had it set to on demand the same day: a
  reading now takes a `get_skill` call and then the shell command (three
  model calls in all, where the tool took two). It needs `run_shell_command`: an instruction
  that blocks that tool cannot read the temperature.
  - Its one sentence "for scale" gives the board's own figures. Since
    2026-11-23, at the owner's request, it says that the 3 A+ starts to
    slow down at 60 degrees, its clock dropping from 1.4 to 1.2 GHz
    (measured, see "Target device"), and further from 80, with 85 as the
    limit (the documentation). Until then it said 80, as on the Zero 2 W.
  - The change was one line, made through `manage_skills` with a script
    fed over stdin that left the rest as it was, and tried with a paid
    question on Haiku ("How hot are you right now, and is that hot for
    you?"): a reading of 45.1 degrees, "comfortably cool", and that the
    clock does not slow down until about 60.
- A fourth skill since 2026-11-20, `take-photo` (on demand), made the same
  way at the owner's request: one shell command that takes a 1920 x 1080
  photo with the webcam (see "Conventions") and saves it as
  `~/robot-photos/photo_<date>_<time>.jpg` on the Pi, printing "saved PATH"
  or "no photo". Its second step is the `view_image` tool (see "Pictures"),
  with the path the command printed: that is how the robot sees. The skill
  tells the model to describe only what it has looked at, and to take a new
  photo to see what is in front of it now. Its first version, from before
  that tool existed, said that the robot could not look at photos.
- The owner's instruction `WebcamTest` ("Take a photo and tell me what you
  see", Sonnet 5.5, with `take-photo` and `cpu-temp` enabled for its runs)
  was run on 2026-11-20: a photo, `view_image`, and a description that
  matched the picture, in three calls for $0.04.
- A fifth skill, `record-sound` (enabled, so its text is in every run's
  system prompt), was on the Pi on 2026-11-22: one shell command that
  records with the webcam's microphone (see "Sound") and saves
  `~/robot-sound/sound_<date>_<time>.wav` on the Pi, printing "saved PATH"
  with the length and size, or "no recording". It tells the model that it
  cannot listen to a recording, and never to describe or guess what one
  holds; since 2026-11-23 it sends the model to `microphone_listen` for
  speech (see "Hearing"). It also has two commands that take a photo and record in
  one go (see "Sound").
- A sixth skill since 2026-11-23, `play-sound` (on demand), made at the
  owner's request with a script fed over stdin that calls `manage_skills`:
  one shell command that plays a WAV file through the speakers on the
  headphone socket (see "Sound"), printing "played PATH in N seconds" or
  "nothing played" with the reason. It tells the model that it cannot hear
  what it plays, and that "played" only means that the sound was sent.
  - `WebcamTest` carries a skill list of its own, and a skill made after
    such a list was saved is off in that instruction's runs. So the skill
    was added to that list as enabled, through `manage_instructions`. That
    was not asked for in so many words: the owner was told.
  - The three other instructions with a list of their own were left alone.
    The skill is off in their runs, and by the code such a run says so in
    a warning at its start, as for any skill its list does not name.
- Because one skill is on demand, every run now also offers `get_skill`.
- The modes above are as each skill was made. The owner changes them in the
  Skills Manager: on 2026-11-24 `take-photo` was enabled, not on demand, and
  `robot-identity` went off and on again that day (see "The system
  prompt"). The next point says where to look.
- `.venv/bin/python -m robot.main --skills` and `--list` on the Pi show the
  current skills and instructions; check there instead of trusting this list.
- The figures of this point are of 2026-11-26; those of 2026-11-28 are at
  the end of this file.
- 1,645 tests pass (counted on 2026-11-26, on the laptop and on the Pi).
  On the Pi 2 are skipped, on Windows 67, among them the 16 of the
  autostart script (bash), the 7 of hands-free
  at the chat's prompt (they need `select`), the 13 of the Wi-Fi
  service (bash), the 8 real-terminal tests (they need curses), the 19
  launcher tests (they need bash) and 3 that build a real tree of child runs
  (they need the kernel's list of processes). `tests/test_spawn.py` starts real
  processes and is the slow one on the laptop, where starting and stopping a
  process takes a second or so: about a minute there, 12 s on the Pi (the
  Zero 2 W). The whole suite takes 35 s on the desktop, and on the Pi 80 s
  on the Zero 2 W and 70 s on the 3 A+.
- The windowed interface was added on this day. Its state is in
  `~/robot-data/tui_state.json`. The owner used it the same evening, over SSH
  from the laptop and at the Pi's own screen.
- On 2026-11-19 the Pi moved from its 16 GB card to a 32 GB one (see "Target
  device"), and the owner ran three interfaces at once at its own screen.
- On 2026-11-22 the Pi was put on another Wi-Fi network (see "Getting back on
  the Wi-Fi"), and the desktop became the second PC the repo is worked on
  from (see "The two PCs"). In the evening of that day the SD card went from
  the Pi Zero 2 W into a Raspberry Pi 3 Model A+ (see "Target device").
- Two tools use hardware since 2026-11-23: `microphone_listen` (the
  webcam's microphone, see "Hearing") and `speak` (the speakers, see
  "Speaking"). There is none for anything else. The one there was before,
  `get_cpu_temperature`, was removed on 2026-11-20 at the owner's request: the model reads the sensor
  with the shell tool when asked (`/sys/class/thermal/thermal_zone0/temp`,
  or `vcgencmd measure_temp`). An instruction that still has the name in its
  `blocked_tools` is unharmed: the Instruction Editor keeps a blocked name it
  does not know.

## State on 2026-11-28

Read from the Pi that morning, and from the code.

- The program: the chat (`robot.main`), the windowed interface
  (`robot.tui`) with its Instruction Editor, Skills Manager and Memories
  window, fourteen tools (nine ordinary ones and the five Meta tools),
  hands-free, the start with the Pi, memory with named memories, child
  runs with `show_window`, and since that day `ui.sh --headless`.
- Eight skills on the Pi (`--skills`): `robot-identity` enabled, and on
  demand `cpu-temp`, `play-sound`, `record-sound`, `share-price`,
  `take-photo`, `weather` and `wifi-monitor`. So against the list above:
  `record-sound` is on demand now and no longer in every prompt,
  `take-photo` is on demand again, and `share-price` and `weather` are
  the owner's own, made since, and not described in these notes.
- Autostart is on. The first interface's `tui_state.json` names the
  owner's `HandsFreeChatAgent` with Hands-free ticked, so that is what a
  start of the Pi runs. `tui_state_2.json` and `tui_state_3.json` are
  there from the three interfaces of 2026-11-19.
- The data folder holds `agent_instructions.json`, the cost log (260
  lines), `autostart_on`, `memory`, `runs`, `saved_chats`, `skills`,
  `tmp`, `tui_errors.log`, the three state files and
  `voice_settings.json` (so a voice has been chosen). It also holds a
  `system_prompt_boilerplate.txt` that nothing in the program reads or
  writes: the owner's, left alone.
- The card: 29 GB, 3.0 GB used. tmux 3.5a, Python 3.13.5.
- The size of a request: the first call of a run on the Pi wrote 13,756
  tokens to the cache with Meta on (a plain instruction, the eight skills
  as above), 9,803 with Meta off, and 6,815 with Meta off and five tools
  blocked (the three sound tools, the shell and `view_image`). On Haiku
  5.5 those first calls cost 0.18, 0.13 and 0.09 cents; the first of them
  on Opus 5.5 is about 7 cents (the cache write alone, at $5 a million).
- 1,684 tests pass (2026-11-28, on the laptop and on the Pi). On the Pi 2
  are skipped (they need a file system that ignores capitals), on Windows
  75: besides those listed above, the 6 of `ui.sh --headless` (bash) and
  the 2 that open a child's window in a real tmux. The whole suite takes
  33 s on the laptop and 89 s on the Pi 3 A+ (70 s on 2026-11-23, with
  fewer tests). Counted by file with `grep -c "    def test_"`: the
  largest are `test_costs` (162), `test_skills` (152), `test_models`
  (120) and `test_tui_app` (103).
- What was done on 2026-11-27 and 2026-11-28, each in its topic's file:
  `show_window` for `run_instruction` ("Meta tools and child runs"), the
  scripts by name on the Pi ("The scripts by name"), `ui.sh --headless`
  ("A headless interface"), saved chats that no longer share a name
  ("Cost, chats, records"), and the README brought up to date: it has a
  section "Every way to start a run", and sections on the models, the
  costs, the files and the environment's settings.
- The Pi could not be reached on the evening of 2026-11-27 (see "Reaching
  the Pi") and answered again the next morning at its old address. Why is
  not known: nothing was looked at before it was back.
