# Hands-free

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- Since 2026-11-24, at the owner's request ("build hands-free properly"):
  while the robot waits for a message it listens for a spoken one, and what
  was said is the reply. Typing still works. Off unless asked for:
  `--hands-free` in the chat (`chat.sh --hands-free`), the Hands-free box
  in the interface (Alt+H, kept in `tui_state.json`, and it can be ticked
  and cleared while the robot waits).
- It is not a tool and the model does not know of it: a spoken message
  reaches the agent as the reply to `Console.ask`, like a typed one. So
  every wait listens (the first message, the next one in a conversation,
  the answer to `user_prompt`), and the end words work when spoken:
  `convo_end_word` takes "Bye." for "bye". The line shown and saved is
  `you> (heard) ...`; the model gets the words without the mark.
- `handsfree.Segmenter` is the part that decides what is speech, a tenth
  of a second (3,200 bytes) at a time, and has no microphone in it:
  - A chunk's level is the RMS of its samples around their own average, so
    a steady offset counts as nothing.
  - The first ten chunks are not looked at. Measured on the Pi from a cold
    start: 7,100 and 2,500 (the thump described under "Sound"), then 600
    to 1,300 for seven tenths, in a room that was at 300; it goes on
    sinking for seconds, to about 270.
  - `floor` is the room's own level. The first chunk looked at sets it;
    below it, it follows down fast (0.7 of the old, 0.3 of the new),
    between it and the start level slowly up (0.98 and 0.02). Speech
    starts when 3 of the last 4 chunks are above `max(2.5 x floor, floor
    + 300)`, and ends after 15 chunks in a row below `max(1.6 x floor,
    floor + 150)`. What is cut out is half a second from before the start,
    the speech, and three tenths of the pause; a minute at most; fewer
    than three loud chunks in all is a click and is dropped.
  - Those figures come from one measurement: the speakers' speech was
    1,000 to 4,800 at the microphone, mostly 1,500 to 2,300, and the gaps
    between its sentences, four to five tenths long, went down to the
    room's 270 to 450. The owner's own voice at the microphone was not
    measured: if it is not picked up, the two `max(...)` lines are where
    to look.
  - `not_speech()` is called when a cut-out piece came back without words:
    the floor is raised to half that piece's typical level, so the same
    noise does not start another piece at once.
- `handsfree.Ear` runs `arecord` with no length on a thread of its own
  (the same command as hearing's otherwise), feeds the segmenter, has each
  piece transcribed with `hearing.transcribe`, and holds the words for
  `take()`. `state` is `listening`, `hearing` or `working`. `problem` is
  set when it stops by itself (no key, no microphone, `arecord` ended:
  "Device or resource busy" when something else has the microphone), and
  `trouble` when one transcription failed and it goes on listening.
  `stop()` kills the recorder; words that arrive after that are dropped.
- The microphone is open only during the wait. The robot's own `speak`
  and `microphone_listen` run between waits, on the same thread that then
  opens the ear, so the robot neither hears itself nor fights itself for
  the microphone. Two interfaces that are both hands-free do: the second
  one's recorder fails and it says so.
- The two places that wait:
  - The interface: `UiConsole._read_reply` looks at the reply queue and at
    the ear every tenth of a second, opens and closes the ear as the box
    changes, and posts an `("ear", state)` event when the state changes,
    which the bottom line shows (`EAR_NOTICES`).
  - The chat: `Console._type_or_speak` waits with `select` on the keyboard
    and looks at the ear. readline's `input()` is not used while
    hands-free is on, because a voice cannot wake it: the line is edited
    by the terminal itself, so there is no history and no arrow keys
    there. What was half typed when a voice came is thrown away
    (`tcflush`). Piped and headless runs never listen.
- A warning is shown once per kind of trouble (`Console._ear_trouble`),
  not at every prompt, and one failed start is not tried again within the
  same wait.
- The interface's bottom row has six boxes now, which do not fit in 72
  columns: `MainWindow.layout` gives them a second row there and the
  output pane one row less.
- Cost: only what is cut out is sent. In the first real test 9.6 seconds
  of sound were uploaded in 40 seconds of listening, with two messages
  spoken; a quiet room uploads nothing.
- Tried for real on the Pi, a session being unable to speak: xAI's voice
  `rex` said the "person's" lines through the speakers.
  - The ear alone, in a scratch copy: two messages eleven seconds apart
    were each handed over 1.3 to 1.9 seconds after the speakers fell
    silent, word for word, the full stop in the middle of each not
    splitting it, and nothing was sent in the 20 quiet seconds after.
  - The interface, in a tmux of the check's own (`zz-ui`, `--session zzt`,
    its `tui_state_zzt.json` written beforehand with the box ticked, an
    instruction `ZZ Talk` on Haiku, `HOME` a scratch folder): a spoken
    first message, the answer spoken by the robot (the owner's
    `robot-identity` skill has it speak its replies), listening again, and
    a spoken "Bye." ending the run. $0.0004.
  - The chat, in a tmux of its own (`zz-chat`): two spoken messages, one
    typed while it listened, each answered aloud, and "Bye." $0.0032.
  - The check's script waited for the listening prompt AND for `pgrep -x
    arecord` before the speakers spoke, then 1.5 seconds more for the
    lead-in.
  - Two mistakes in those scripts, for the next one: a helper that calls
    `robot.speaking` outside the program must load the `.env` itself, and
    `ls` on the Pi sorts `x_2.wav` BEFORE `x.wav` (its locale ignores the
    punctuation), so files to be played in order need names that say so.
  - In the first, failed try the speakers said nothing, and the interface
    still took a message from the room and ran with it. Whose voice that
    was is not known. Hands-free hears whoever speaks: a radio or a
    second person in the room can send a message.
- A conversation ended by a SPOKEN end word (any of the four) gets a
  goodbye first, and after a spoken "bye" the Pi is powered off as well
  (further down). The goodbye is at the
  owner's request and in the owner's words (`agent.FAREWELL`): "I am ending
  this conversation now. Goodbye, till we meet again."
  - Both goodbyes ended "Good to have known you." until 2026-11-26, when
    the owner had that sentence changed. The checks written down below
    are from before: what they showed and heard is left as it was.
  - It is the program that says it, not the model: no call is made.
    `Agent._say_farewell` shows it as a `robot>` line and speaks it with
    `speaking.say`, which plays from a file in the data folder's `tmp` and
    keeps nothing (unlike the `speak` tool). It costs xAI's price for 63
    characters, a tenth of a cent.
  - `Console.last_reply_heard` is how the agent knows: both consoles set it
    with every reply. A typed end word, an empty reply and nobody being
    there end a conversation without the goodbye.
  - Only the conversation's own end (`_next_convo_message`). "exit" in
    answer to `user_prompt`, and an end word as the very first message of
    an instruction without text, end things silently as before.
  - Without a voice (no key, no `aplay`) it is shown and not spoken. A
    failure to speak is a warning; STOP cuts it short; the conversation
    ends either way.
  - After the goodbye the Pi is POWERED OFF, since 2026-11-25, at the
    owner's request and with no question asked ("with no user
    guardrail/prompt"). `_next_convo_message` sets `Agent.power_off`, and
    `Agent.run` calls `power.power_off` after `_end_run`, so the cost is
    logged and the chat saved first, and only when the run ended as
    "completed". `power.power_off` calls `os.sync()` and runs `sudo -n
    poweroff`; systemd's shutdown stops the interface and everything else
    in order and unmounts the card. That is the whole of "safely".
    `ROBOT_POWEROFF_COMMAND` names another command, for tests and checks.
  - The goodbye before a power-off is another sentence, the owner's too
    (`agent.FAREWELL_POWER_OFF`, since 2026-11-25): "I am powering myself
    off now. Goodbye, till we meet again." The three other spoken end
    words keep the first one. Tried, with the wording of that day, with the same paid check and stand-in as
    below ($0.0022): `you> (heard) Bye.`, then `robot> I am powering
    myself off now. Good to have known you.`, the chat saved, the stand-in
    run. The owner then tried it for real after a restart of the Pi, with
    both sentences, and it worked.
  - Only the word "bye" (`agent.POWER_OFF_WORD`), and only SPOKEN, at the
    conversation's own prompt: the owner narrowed it to that the same day
    ("ONLY work if I say the word bye (not write it!)"); for an hour it
    had been all four end words. A spoken "stop", "quit" or "exit" gets
    the goodbye and leaves the Pi on. So do a typed "bye", an empty reply,
    STOP, Quit, "exit" to `user_prompt` and a run that ends by itself. It
    is in the chat and in the interface. `convo_end_word` decides what
    counts as the word: "Bye.", "BYE!" and " bye " do, "bye for now" is
    an ordinary message.
  - Tried on the Pi with a stand-in for the command (`date +%T.%N >
    /tmp/zz-poweroff-asked`, exported before the check's tmux server
    started; `tmux show-environment -g` confirmed it): a paid hands-free
    chat on Haiku ($0.0022), the speakers' "Bye.", then the goodbye,
    "Conversation ended.", the cost-log line, and the line that says
    the Pi is powering off. The saved chat was written at
    10:31:48.76 and the stand-in was run at 10:31:48.83. The check first
    made sure that no run was in progress and nothing else was listening:
    another run hearing its "Bye." would have switched the Pi off. The
    real `sudo poweroff` was not run by a session; passwordless sudo is
    what it needs, and the Pi has that.
  - After the narrowing, the same check with the speakers saying "Stop."
    ($0.0004): `you> (heard) Stop`, the goodbye, "Conversation ended.",
    the cost-log line, and no line about powering off; the stand-in was
    never run.
  - The real thing was tried by the owner that morning, after a restart
    of the Pi that came up through the autostart on this code: "All the
    above changes work well, the Pi is now powered off."
  - Hands-free hears whoever speaks: a "Bye." from a radio switches the
    Pi off. With autostart on, the Pi's life is then: power on, run,
    listen, "bye", off.
  - Tried with a paid hands-free chat on Haiku ($0.0004), in a tmux of
    its own: after the speakers' "Bye." the chat showed `you> (heard) Bye`
    and the `robot>` goodbye, and a `hearing.listen` started the moment
    the chat's recorder was gone heard "This conversation now. Good to
    have known you." (its own first second is thrown away). No file was
    left in `tmp`.
  - That check's first try failed by its own timing: "the last line is
    `you>`" is still true while the message just spoken is being worked
    out, so the next line was played too soon. A check waits for the Nth
    `(listening: speak, or type)` line, the prompt and a running
    `arecord`. The failed try did show the fallback: with the microphone
    taken by the check, the chat said "Hands-free has stopped listening:
    ... Device or resource busy. Type instead." and went on at `you>`.
- `tests/test_handsfree.py` (50 tests; 7 need `select` and are skipped on
  Windows): the segmenter on made-up sound, the ear on a stand-in recorder
  that writes through a real pipe, and both consoles with a stand-in ear.
