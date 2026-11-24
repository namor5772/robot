# robot

The agent "brain" for a small robot running on a Raspberry Pi 3 Model A+
(until 2026-11-22 a Pi Zero 2 W: the same SD card runs on both). It talks to
Anthropic's Claude models and can act on the Pi through tools. With a webcam
and speakers attached it also sees, hears speech and talks out loud (see
"Tools"); the hearing and the voice come from xAI's speech services.

The program is a terminal port of the MyAgent harness: the same way of running
saved instructions, the same skills format, the same Meta tools and Convo
mode, the same cost log. It leaves out MyAgent's windows, its safety-confirm
system and every provider other than Anthropic.

## Starting a chat

From a PC (the laptop or the desktop, see "Working on it"):

```powershell
ssh -t pi "bash ~/robot/scripts/chat.sh"
```

At the Pi's console:

```bash
bash ~/robot/scripts/chat.sh
```

You get a `you>` prompt straight away. What you type first is the task, and
after every reply you are asked for the next message. `quit`, `stop`, `exit`,
`bye` or Ctrl-D end the chat, and so does Enter on an empty line, as in
MyAgent: nothing sent means you are done. (When the robot has asked you a
question, an empty line stops the run.) Ctrl-C stops the reply or command in
progress and returns to the prompt.

To talk instead of typing, start it hands-free:

```powershell
ssh -t pi "bash ~/robot/scripts/chat.sh --hands-free"
```

Whenever the robot waits for you it then listens through its microphone.
Speak, pause for a second and a half, and what you said is sent as your
message, shown as `you> (heard) ...`. Typing still works at the same prompt.
Say "bye" or "stop" on its own to end the conversation; the robot then says
goodbye, and after "bye" it also switches the Pi off (see "Hands-free" further
down). In the windowed
interface the same thing is the Hands-free box in the bottom row (Alt+H),
which can be ticked and cleared at any time; the bottom line shows
"Listening", "Hearing you..." and "Working out what you said...". For the
robot to answer out loud as well, tell it to (a skill or an instruction can
say so for good). See "Hands-free" further down for how it works and what
it costs.

### Starting by itself when the Pi starts

The Pi can start the windowed interface on its own screen when it is switched
on, and begin the run at once, with nothing typed:

```bash
bash ~/robot/scripts/autostart.sh on       # from the next start on
bash ~/robot/scripts/autostart.sh off      # not any more
bash ~/robot/scripts/autostart.sh status
```

What starts is the interface as you left it: the instruction it had last and
its boxes, Hands-free among them. So tick Hands-free and run the instruction
you want once, and from then on the Pi comes up running it and listening. It
first waits (three minutes at most) for the Wi-Fi and for the clock to be
set. It is the ordinary interface: `ssh -t pi "bash ~/robot/scripts/ui.sh"`
joins it from a PC, and when the run has ended (say "bye") you can choose
another instruction there and press START. It starts one run per start of
the Pi and does not start another by itself afterwards. Every start of the
Pi is then a paid run, and with Hands-free the robot answers whoever speaks
near it.

`chat.sh` runs the chat inside tmux, so it belongs to the Pi and not to your
SSH connection. If the PC sleeps or the connection drops, the chat keeps
running, and the same command brings you back to it.

- To leave a chat running on purpose, press Ctrl-B, then D.
- The mouse wheel scrolls back. To select text, hold Shift while dragging.
- When the chat ends, press Enter to close the window.
- If a line such as `11;rgb:0c0c/0c0c/0c0c` or `61;4;6;7c0;10;1c` shows up at
  `you>` without you typing it, it is your terminal's answer to a question
  from tmux that slipped through. Press Enter before typing anything else: it
  is ignored, not sent, and the prompt comes back. It is the one line that is
  ignored; it does not end the chat the way an empty line does.
- While a chat is starting, such answers are thrown away, and so is anything
  you type before the first `you>` appears.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.main`.

## The windowed interface

The same agent behind buttons, lists, text boxes and dialogs, all drawn with
characters. It needs no graphical desktop: it works over SSH and on the Pi's
own screen and keyboard.

From a PC:

```powershell
ssh -t pi "bash ~/robot/scripts/ui.sh"
```

At the Pi's console:

```bash
bash ~/robot/scripts/ui.sh
```

```
 Robot  |  ZZ ui chat  |  claude-haiku-5-5 (Low)  |  conversation
 [ START ] [ STOP ] [ Instruction ] [ Skills ]                [ Help ] [ Quit ]
┌─ Output ─────────────────────────────────────────────────────────────────────┐
│This instruction has no saved task. Type it as your message.                  ▲
│you> Say hello in exactly five words.                                         │
│  Starting up...                                                              │
│robot> Hello there, friend, nice to meet you.                                 │
│  call 1: $0.0010 this call  |  $0.0010 total  (in:4  out:15                  │
│cache_write:7,579)                                                            │
│you> How hot is your CPU right now? Check, then answer in one sentence.       │
│  call 2: $0.0001 this call  |  $0.0011 total  (in:4  out:71  cache_write:40  │
│cache_read:7,579)                                                             │
│[tool: run_shell_command: {"command": "cat                                    │
│/sys/class/thermal/thermal_zone0/temp"}]                                      │
│robot> My CPU is currently at about 49.4 °C (49388 millidegrees from the Pi's │
│thermal sensor).                                                              │
│  call 3: $0.0001 this call  |  $0.0012 total  (in:2  out:40  cache_write:93  │
│cache_read:7,619)                                                             │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ Your message (Enter sends, empty Enter ends, Ctrl+J new line) ──────────────┐
│                                                                              │
│                                                                              │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
 [x] Activity [ ] Thinking [ ] Tool calls [ ] Debug [ ] Save thinking
 [ ] Hands-free
 Waiting for your message                  F1 Help  F2 Start  F3 Stop  F10 Quit
```

What the main window has:

- **The top line** names the instruction that START will run, with its model,
  its thinking level and whether it is a conversation or a single task. `meta`
  at the end means the instruction's Meta switch is on, which gives its runs
  the group of four Meta tools (see [Tools](#tools)). No other tool is shown
  here. A name too long for the window is shortened with `...`, so that the
  settings after it always stay in view.
- **START** (F2) runs it. What the run shows appears under *Output*, the same
  lines the chat prints. Each START clears *Output* first, as in MyAgent; the
  earlier run's lines are in its saved chat. **STOP** (F3 or Ctrl+C) stops the reply or command in
  progress; while the robot is waiting for your message, it ends the run.
- **Your message** takes the cursor whenever the robot waits for you. Enter
  sends; Ctrl+J starts a new line. `quit`, `exit`, `stop` or `bye` on its own
  ends a conversation, as in the chat. Enter on an empty box ends it too, as
  in MyAgent and in the chat: a conversation ends, and when the robot has
  asked a question the run stops.
- **Instruction** (F4) opens the Instruction Editor: a list of the saved
  instructions and a form for the one selected (name, model, thinking level,
  Fast, Meta, Convo, notes, blocked tools, skills, upgrade model, text).
  *Save* stores the form under the name in the Name box, so a new name makes a
  new instruction. *Use* makes it the one START runs.
- **Skills** (F5) opens the Skills Manager: every skill with its mode, text,
  description and bundled files. Space on the list switches a skill between
  off, ON (in every prompt) and OD (on demand).
- **The boxes along the bottom** choose what a run shows: Activity (tool lines
  and the cost of each call), Thinking, Tool calls, Debug. The last one,
  **Hands-free** (Alt+H), has the robot listen for a spoken message whenever
  it waits for you (see "Hands-free" under "Tools"). They are remembered. In a
  narrow window the boxes take two rows.
- **Help** (F1) lists every key. **Quit** is F10.

Getting around:

| Key | What it does |
|---|---|
| Tab, Shift+Tab | The next or the previous control. |
| Alt+letter | The control that shows that letter highlighted. |
| Enter or Space | Press the button, tick the box, open the list. |
| Escape | Close the window. Unsaved changes are asked about first. |
| Up, Down, PgUp, PgDn, Home, End | Move in a list or a text; look back through the output. |
| Mouse | Click a control; the wheel scrolls. Hold Shift to select text. |

Good to know:

- A run started here is always the run of a named instruction, `Default`
  included, so its saved chat and its cost-log line carry that name. An
  instruction with no text asks you for the task.
- One run at a time. The editors can be used while a run is going; what they
  save applies from the next run.
- Like the chat, it runs inside tmux and survives a dropped connection: the
  same command brings you back, and Ctrl-B then D leaves it running. It has a
  tmux of its own, so a chat can be open as well.
- Starting it again joins it. If the interface is already running, the
  command does not start a second one, whether you type it on a PC or
  at the Pi. There is then one program with several screens: each shows the
  same windows, and any of the keyboards drives them. The window takes the
  size of the screen that was used last.
- At the Pi's own screen it is the same command and the same keys, Shift+Tab
  included. There is no mouse there: the Pi's text screen passes no clicks on
  to a program, so everything is done with the keys.
- Text pasted into the terminal goes into the box that has the cursor, as text.
- It runs on the Pi only: Python on Windows has no curses.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.tui`.

### More than one at a time

Whatever runs an instruction is a program of its own, taking 80 to 95 MB of
the Pi's 415 MB. So there are three limits:

| What | Limit |
|---|---|
| Instructions in one interface | One at a time: START is off while a run is going. |
| Child runs that a run starts itself (`run_instruction`, with Meta on) | As many as there is memory for, and never more than 8 at once in all, counting the children that children start: one is started only while 110 MB is free. On this Pi that comes to two at once. |
| Interfaces and chats open at once | No fixed number. What memory limits is how many are working at the same moment: about three, however they were started. One that is open but idle takes far less (see below). |

A chat and the interface can be open together: `chat.sh` and `ui.sh` each
have a tmux of their own. For a second interface, give it a session name:

```bash
bash ~/robot/scripts/ui.sh --session 2
```

From a PC that is `ssh -t pi "bash ~/robot/scripts/ui.sh --session 2"`.

At the Pi's own screen every interface can have a text terminal to itself.
Hold Alt and press F2 for the second terminal, log in there (it asks the
first time), and start the interface with `--session 2`. Alt+F1 goes back to
the first terminal, and Alt+F3 to Alt+F6 are four more. The keys work while
an interface is on the screen, and whatever you leave keeps running.

- Any short name will do in place of the 2: up to 12 letters, digits, `-`
  or `_`.
- The same command brings you back to that interface later. Without
  `--session` you get the first one, which is also what `--session 1` means.
- Each interface shows its name in its top row (`Robot 2  |  Default  | ...`)
  and remembers its own instruction in use and its own display boxes.
- `-l "Name"` still works beside it: `ui.sh --session 2 -l "Zero state chat"`.

All the interfaces are in one tmux, and its keys go from one to the other:

| Keys | What happens |
|---|---|
| Ctrl-B then `)` | The next interface. |
| Ctrl-B then `(` | The one before. |
| Ctrl-B then `s` | A list to pick from. |
| Ctrl-B then D | Leave them all running. |

The interfaces share the instructions, the skills and the cost log, and each
keeps its own runs and saved chats.

An interface takes about 80 MB when it starts. One that sits idle gives most
of that back when memory gets short: the Pi squeezes it into compressed
memory, and brings it back when the interface is used again. Measured on
2026-11-19 with no run going in any of them:

| Interfaces open | Memory still available | What each held |
|---|---|---|
| Two | 120 MB | 83 MB each |
| Three | 141 to 147 MB | The new one 79 MB, the two older ones 33 and 41 MB |

So three open interfaces left more room than two. Whether a run can start
child runs (110 MB must be free) depends on the memory at that moment, not on
how many interfaces are open.

### On the Pi's screen with no keyboard there

The Pi 3 A+ has one USB port, so with the webcam in it there is no keyboard
at the Pi. Its screen can still show what you do from a PC. Over SSH, this
puts the interface on the Pi's screen:

```bash
sudo openvt -c 8 -s -- sudo -u $USER env TERM=linux bash ~/robot/scripts/ui.sh
```

Then `bash ~/robot/scripts/ui.sh` in the same SSH terminal joins it: the
screen and your terminal show the same windows, and your keyboard drives
them. If the interface was running already, the first line joins it too.

For a plain terminal in place of the interface, start a tmux session and put
that on the screen:

```bash
tmux new -A -s shared
sudo openvt -c 8 -s -- sudo -u $USER env TERM=linux tmux attach -t shared
```

- The picture takes the size of your SSH window, as always with two screens.
  The Pi's screen has 240 columns and 67 rows, so a smaller window sits in
  its top left corner. `sudo setfont -C /dev/tty8
  /usr/share/consolefonts/Uni3-TerminusBold32x16.psf.gz` doubles the letters
  on that screen, which then has 120 columns and 33 rows.
- `sudo chvt 1` puts the screen back on its usual terminal, and `sudo chvt
  8` shows the other one again. Whatever runs keeps running.
- `openvt -c 8` uses the Pi's eighth text terminal, which nothing else uses,
  and `-s` switches the screen to it.

## Saved instructions

An instruction is a saved task together with the settings to run it with:
model, thinking level, fast mode, Meta on or off, Convo on or off, blocked
tools, skill modes and an upgrade model. Its text is the first message of the
run.

```bash
.venv/bin/python -m robot.main --list            # show the library
.venv/bin/python -m robot.main -l "Name"         # run one
bash scripts/chat.sh -l "Name"                   # run one inside tmux
```

- A run with **Convo off** is a single task: it works until the model is done
  and then ends. If the model needs you, it asks through its `user_prompt`
  tool.
- A run with **Convo on** is a conversation: you are prompted after every reply.
- The entry named **Default** holds the settings of a chat started without a
  name. Change it to change the everyday chat. It is re-created if deleted.

### A chat and an instruction compared

A chat is not a separate mode. It is an ordinary run with no saved task,
using `Default`'s settings, and `Default` has Convo on.

| | Plain chat (no `-l`) | Instruction (`-l "Name"`) |
|---|---|---|
| First message | You type it at `you>` | The instruction's saved text |
| Settings | Borrowed from `Default` | The instruction's own |
| Convo | On, because `Default` has it on | What the instruction says (off unless set) |
| Name in the cost log and saved chat | None (`Agent_<time>`) | The instruction's name |

A plain chat uses only `Default`'s settings: any text saved in `Default` is
ignored unless you run it by name with `-l Default`. An instruction with no
text asks you for the task when run at a terminal.

The robot is told which instruction and which model it is running as, so you
can ask it ("which model are you on?").

### Creating and changing instructions

Three ways:

- **The Instruction Editor** of the windowed interface (above): a form with
  the name, the model, the thinking level, the switches and the text.
- **Ask the agent.** With Meta on it creates, changes and deletes instructions
  and skills itself ("save this as an instruction called Night watch", "make
  the default model Haiku").
- **Edit the file by hand** (below).

Whichever way, a change applies from the next run, not the one in progress.

The library is one JSON file, `~/robot-data/agent_instructions.json`. Each
instruction is a named block, for example:

```json
{
  "Default": {
    "text": "",
    "model": "claude-opus-5-5",
    "thinking_mode": "low",
    "meta": true,
    "conversational": true
  },
  "Health check": {
    "text": "Report your CPU temperature, free memory and disk space in three short lines.",
    "model": "claude-haiku-5-5",
    "thinking_mode": "low",
    "meta": false,
    "conversational": false
  }
}
```

Only `text` is needed; anything left out takes a default (Opus 5.5 at its
Adaptive thinking level, Meta off, Convo off). `thinking_mode` is one of
`off`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max`; a level the model
lacks is replaced by the nearest it has, with a warning. Other fields: `notes`
(for you, never sent to the model), `fast_mode`, `blocked_tools`,
`skill_modes`, `upgrade_target`.

- After a hand edit, check the file:
  `python3 -m json.tool ~/robot-data/agent_instructions.json`. If it cannot be
  read, the robot leaves it alone, warns, and runs with built-in settings.
- Meta is what lets a chat manage instructions. If you turn Meta off in
  `Default`, the plain chat can no longer change anything, including turning
  it back on: edit the file, or delete the `Default` block so it is re-created.
- Entries copied from MyAgent's library work. Settings the robot does not have
  are ignored, and an entry for another provider is refused when run.

## Skills

An instruction is something to do; a skill is something to know. A skill is a
piece of know-how in its own folder, which any run can draw on:

```
~/robot-data/skills/
  check-power/
    SKILL.md
    scripts/report.sh        (optional: any files and sub-folders)
```

`SKILL.md` is a short header followed by the skill's text:

```
---
name: check-power
description: How to check the robot's power supply. Use when asked about power.
mode: on_demand
---

To check the power supply, run `vcgencmd get_throttled` with the shell tool.
throttled=0x0 means the supply has been fine since boot.
```

Each skill has a mode:

- **enabled**: its text is part of every system prompt.
- **on_demand**: only its description is listed; the agent fetches the text
  with `get_skill` when it applies. Write the description as what the skill
  does and when to use it, because that line is how the model decides.
- **disabled**: not used. This is what a new skill gets unless you say otherwise.

`.venv/bin/python -m robot.main --skills` lists them.

- **Creating one:** ask in a chat, naming the skill, its mode, its description
  and its content. A good way is to have the robot do the job once and then
  say "save what you just did as a skill". It applies from the next chat.
- **Reading and changing them:** the Skills Manager of the windowed interface
  shows every skill, its text, its description and its bundled files, and
  switches its mode with one key.
- **Bundled files:** the robot can list, read, write and delete files inside a
  skill's folder. When it fetches a skill that has such files it is told where
  the folder is, so it can run a bundled script with the shell.
- **Per instruction:** an instruction may carry its own `skill_modes`, a list of
  skills with the mode each has for its runs. Then every skill it does not
  name is off for those runs. Without one, the instruction follows each
  skill's own mode. Only the run is affected; the skills are not changed.
- **Copying skills in:** the format is MyAgent's, so a skill folder copied from
  there works as it is. A plain Anthropic-format skill has no `mode` line and
  comes in as disabled until you set one.

## Tools

| Tool | When | What it does |
|---|---|---|
| `run_shell_command` | always | Runs any bash command on the Pi as its user, with sudo. |
| `get_current_datetime` | always | Reads the Pi's clock. |
| `view_image` | always | Shows the model an image file on the Pi (a photo it took, for instance), so that it can say what is in it. |
| `microphone_listen` | if the Pi has a microphone's recorder and an xAI key | Listens through the Pi's microphone for some seconds and gives the model what was said, as text. |
| `speak` | if the Pi has a sound player and an xAI key | Says a text out loud through the Pi's speakers, and keeps the speech as a WAV file. |
| `voice_settings` | with `speak` | Lists the voices there are, and saves the voice and the speed that `speak` uses. |
| `user_prompt` | always | Asks you a question and waits for the answer. |
| `get_skill` | if a skill is on demand | Fetches an on-demand skill's text. |
| `web_search` | always | Searches the web on Anthropic's servers, up to 5 searches per request. |
| `manage_instructions` | Meta on | Lists, reads, creates, updates and deletes instructions. |
| `manage_skills` | Meta on | The same for skills and their bundled files. |
| `run_instruction` | Meta on | Runs another instruction as a child run. |
| `upgrade_model` | Meta on | Moves the rest of the run to a stronger model. |

Meta is the only group of tools. It is one switch on an instruction, and it
turns the last four on together: the tools with which the robot works on its
own setup. Their descriptions add about 3,000 tokens to every request. The
first nine are not grouped: each is offered on its own, whenever it can work.

There is no tool for the CPU temperature any more (there was one until
2026-11-20). Asked how hot it is, the robot reads the Pi's sensor with the
shell tool.

`view_image` is how the robot sees. It takes a photo with the shell tool (a
webcam on the Pi's USB port, and a skill that says how), then looks at the
file with `view_image` and describes it. The tool takes JPEG, PNG, GIF and
WebP files of up to 3.5 MB. A picture costs by its size in pixels, not in
bytes: a 1920 x 1080 photo is a few thousand tokens, about a cent on the
default model, and it stays in the conversation for the rest of the run. The
saved chat keeps a note in place of each picture, and `--debug` shows only
how long its data was.

To look at one of the robot's photos yourself, on a PC, in the checkout:

```powershell
.venv\Scripts\python.exe scripts\pi_photo.py
```

It copies the Pi's newest photo to `RobotPhotos` in your home folder and
opens it in the PC's viewer. Put a photo's file name after it for another
one. The file it opens is `NAME_viewable.jpg`: the webcam's photos leave out
a part that Windows insists on, and opened as they come the viewer shows
nothing. The photo as it came is kept beside it, and nothing on the Pi is
changed.

The webcam has a microphone as well, and with a skill that says how, the
robot records sound with the shell tool: WAV files in `robot-sound` in the
Pi's home folder. No tool takes a sound file in, so of a recording it has
made it can say where the file is, and nothing about what is on it. To hear
one yourself, on a PC, in the checkout:

```powershell
.venv\Scripts\python.exe scripts\pi_sound.py
```

It copies the Pi's newest recording to `RobotSound` in your home folder,
says how long and how loud it is, and plays it to its end through the PC's
speakers. Put a recording's file name after it for another one, or
`--no-play` to have it only described. Nothing on the Pi is changed.

With speakers on the Pi's headphone socket (the Pi 3 A+ has one, the Zero
2 W does not) and a skill that says how, the robot also plays sound with the
shell tool: one of its recordings, or any other WAV file. It cannot hear what
it plays, and it cannot tell whether the speakers are switched on: when it
says that it played a file, the sound was sent to them.

`microphone_listen` is how the robot hears, and what it hears is speech
only. Claude takes no sound, so the tool records through the webcam's
microphone (5 seconds unless the model asks for another length, 120 at most)
and sends the recording to xAI's speech-to-text service
(`grok-voice-transcribe-2.0`); the words come back as the tool's result. It
gets no voices, no tone and no other sounds. The robot cannot be spoken to
out of the blue: it listens when the model calls the tool, so ask for it
("listen to me for ten seconds") or give an instruction that says when. The
service costs $0.10 for an hour of sound, so a call is a fraction of a cent;
that is billed by xAI and is not in the robot's cost log. A recording made
this way is kept nowhere on the Pi. It needs `XAI_API_KEY=...` in
`~/robot/.env`: without the key the tool is not offered.

`speak` is how the robot talks. It sends a text of up to 2,000 characters
to xAI's text-to-speech service, saves what comes back as
`speech_<date>_<time>.wav` in `robot-sound` in the Pi's home folder, and
plays it through the speakers on the headphone socket; the tool returns when
the file has been played to its end. Asked for the file alone (`play` false),
it makes it and does not play it. The service costs $15 for
a million characters, about a tenth of a cent for a sentence; like hearing,
that is billed by xAI and is not in the robot's cost log. The robot cannot
hear itself and cannot tell whether the speakers are on. Together with
`microphone_listen` it can be talked with: tell it, typed, to listen, and to
answer aloud.

The voice and its speed are yours to choose: ask the robot which voices
it has, to switch to one, or to speak faster or slower. `voice_settings`
lists the service's voices (28 of them, each a name and whether it is male
or female) and saves a voice, a speed from 0.7 to 1.5, or both, in
`voice_settings.json` in the data folder. A saved choice holds from the next
sentence on, in every chat and interface on the Pi, until it is changed.
Nothing describes how a voice sounds, so ask to hear a sentence in the ones
you are curious about: `speak` takes a voice and a speed for one call, which
changes nothing that is saved. With nothing saved the voice is `eve` at
speed 1.

### Hands-free

With hands-free on (see "Starting a chat") the robot listens whenever it
waits for a message: the first one, the next one in a conversation, or the
answer to a question it asked. It does not listen while it is working or
speaking, so it does not hear itself.

- The microphone's sound is watched a tenth of a second at a time. Sound
  that stands clearly above the room's own level starts a message; a second
  and a half of quiet ends it. Only that piece is sent to xAI's
  speech-to-text service, so silence costs nothing and a quiet room is never
  uploaded.
- A piece in which the service finds no words (a door, a cough) is dropped
  and the robot goes on listening. It never counts as an empty message,
  which would end the conversation.
- The room's level is followed all the time, so it works in a quiet room and
  in a noisy one. In a noisy one you have to speak up.
- A message can be a minute long at most. The first second after the robot
  starts listening is not heard: the microphone needs it to settle.
- "Bye", "stop", "quit" or "exit" said alone ends a conversation, as when
  typed. When it was said, the robot first answers out loud: "I am ending
  this conversation now. Good to have known you." A typed end word ends the
  conversation without that.
- **A spoken "bye" also powers the Pi off.** Only that word, and only when
  it was said, not typed: once the run's cost is logged and its chat saved,
  the Pi runs `sudo poweroff`, without asking. To use it again, take its
  power away and give it back; with autostart on it then comes up running
  and listening. "Stop", "quit" and "exit", spoken or typed, a typed "bye",
  STOP, Quit and an empty message all leave the Pi on.
- If the microphone cannot be used (another program has it, or no xAI key),
  a warning says so once and typing goes on working.
- Every message is one transcription, about a hundredth of a cent, billed by
  xAI and not in the robot's cost log.

Any of the thirteen can be switched off for one instruction. In the Instruction
Editor the Tools button shows this list, in this order, with a tick beside
each tool the instruction may use. A cleared tool is blocked for that
instruction only (`blocked_tools` in the file), and a Meta tool needs both
the Meta switch and its tick. While the instruction's Meta box is not ticked,
the four Meta tools show `[-]` and "(needs Meta)" there in place of a box and
cannot be ticked or cleared: no run would get them either way. A block set on
one of them earlier is kept, and shows again once Meta is ticked.

The shell tool is deliberately unrestricted: no confirmation, no allowlist, no
blocked commands, and the Pi has passwordless sudo, so the agent has root. It
can read `~/robot/.env`, change any file, and act on what it reads from the
web. With Meta on it can also write skills that later runs load, so text it
picked up can outlast a session: the start banner lists the skills in use. To
take root away, run `sudo rm /etc/sudoers.d/010_grobliro-nopasswd` on the Pi.
An instruction's `blocked_tools` list removes tools from its runs.

A child run is a second copy of the program. It takes about 10 seconds to
start on the Pi 3 A+ (15 on the Pi Zero 2 W) and about 80 MB of memory. How
many run at once is decided by the memory that is free, not by a fixed
number: a child is started only while 110 MB is free (80 for it, 30 to
spare), and memory that children still starting have yet to take counts as
taken. With the 512 MB that both of these boards have, that comes to two at
once, as before. A computer with more memory, such as a Pi 5, runs as many as
fit, with no change to the program, up to a ceiling of 8 at once: every child
is a run that is paid for. The 8 is for the whole tree of runs. A child may
start children of its own (those may not start any), and they all count
together: the first run's children and the children those started.

## What you see

```
you> How hot are you, and how long have you been up? Check both.
  call 1: $0.0014 this call  |  $0.0014 total  (in:4  out:188  cache_write:10,665)
[tool: run_shell_command: {"command": "cat /sys/class/thermal/thermal_zone0/temp; uptime -p; uptime -s"}]
robot> I'm running at about 49.4°C, which is comfortably cool for this Pi. I've been up for 2 hours and 25 minutes, since 08:56:35 on 2026-11-20.
  call 2: $0.0002 this call  |  $0.0016 total  (in:2  out:117  cache_write:237  cache_read:10,665)
```

(That chat ran on `claude-haiku-5-5`. On the default model the first call costs
about 5 cents.)

Each `call` line is one request to the model and what it cost. The first call
of a chat costs the most, because the system prompt and tool list (about
10,000 tokens with Meta on) are written to the prompt cache. Later calls read
them back at a fraction of the price, as long as you reply within five minutes.

Options for what is shown: `--no-activity` (hide tool and cost lines),
`--thinking`, `--tool-calls`, `--debug`. Others: `--model ID` and `--mode LEVEL`
for one run, `--dry-run` to print the request without sending it, and
`--help` for the rest.

## Where things are kept

On the Pi, outside this repository, in `~/robot-data`:

| Path | Contents |
|---|---|
| `agent_instructions.json` | The instruction library. |
| `skills/<name>/SKILL.md` | The skills. |
| `saved_chats/` | Every run's transcript (`.txt`) and messages (`.json`). |
| `APICostLog_<host>.txt` | One line per run: time, model, cost, tokens. |
| `tui_state.json` | What the windowed interface remembers: the instruction in use and the boxes of the bottom row (Hands-free among them). An interface started with `--session 2` has `tui_state_2.json`. |
| `tui_errors.log` | Anything a library printed while the windows were up (normally empty). |

These files use MyAgent's formats, so instructions and skills can be copied
between the two programs. Nothing in `~/robot-data` is backed up by itself:
see the next section.

## Backing up the Pi

There are two kinds of backup, and both are kept on a PC. Either PC can make
them; so far they are on the laptop.

**The data that changes every day.** Instructions, skills, chats and the cost
log are in `~/robot-data`, a few megabytes. From PowerShell, in the folder
that is to hold the copy:

```powershell
scp -r pi:robot-data .
```

**The whole SD card.** One file, an exact copy of the card. Written back to a
card, it gives the Pi as it was that day: the system, the program and its
key. (The code alone is on GitHub.)

1. Shut the Pi down with `sudo poweroff`, wait until the green light stays
   off, and take the card out.
2. Put the card in the PC. If Windows offers to format a disk, cancel.
3. In Win32 Disk Imager, name a new image file, choose the card's drive
   letter (the drive called `bootfs`) and press **Read**. Write would
   overwrite the card with the file.

To restore, write the file to a card with Raspberry Pi Imager, with "Use
custom" as the operating system. If it asks about customisation settings,
answer No: with them the Pi sets itself up as a new machine at its first
start and may reset its name, password and keys.

- Keep the file private, and out of folders that are synced elsewhere: it
  holds the API key, the Wi-Fi password and the Pi's keys.
- The file is as large as the card, whatever is on it, and fits only a card
  of that size or larger. Cards sold as the same size differ a little, so a
  larger one is the safe choice.
- A copy has the same name and keys as the original. Two Pis must not run
  from the two cards on one network at the same time.

On a larger card the system does not use the extra room by itself: `df -h /`
still shows the old size. These two commands claim it while the Pi runs,
without a restart:

```bash
sudo growpart /dev/mmcblk0 2
sudo resize2fs /dev/mmcblk0p2
```

That is how the Pi moved from a 16 GB card to a 32 GB one on 2026-11-19.

## Getting back on the Wi-Fi

When a Wi-Fi network the Pi knows goes away and comes back (a phone's
hotspot, for instance), the Pi rejoins it by itself. Two things see to that:

- NetworkManager, the system's own network service, rejoins a saved network
  when it sees it again. Most of the time that is all it takes.
- Sometimes NetworkManager gives up on a network and waits for somebody to
  connect by hand; the Pi then stayed off the air until it was restarted. So a
  small service, `robot-wifi`, looks every half minute. When the Pi is off the
  Wi-Fi while a saved network is in range, it connects to it. If that fails
  ten times in a row it restarts NetworkManager, at most once an hour.

Expect the Pi back about a minute after the network returns. The service
knows no network by name: it uses the Wi-Fi networks saved on the Pi that are
set to connect automatically, the one with the highest priority first.
`deploy.sh` sets it up, and it starts with the Pi.

```bash
systemctl status robot-wifi          # is it running
tail /var/log/robot-wifi.log         # what it did, and when
sudo systemctl stop robot-wifi       # stop it until the Pi is next started
sudo systemctl disable --now robot-wifi   # switch it off for good
```

### Joining a new network

A network the Pi has never joined is added at the Pi's own keyboard and
screen, which need no network.

1. List the networks the Pi can see. Press `q` if the list waits at the
   bottom.

   ```bash
   sudo nmcli device wifi list --rescan yes
   ```

2. Join one. Type its name exactly as the list shows it, capitals and spaces
   included, in quotes. The password is asked for and not shown.

   ```bash
   sudo nmcli --ask device wifi connect "Network Name"
   ```

3. Check. `wlan0` should say `connected`, and `hostname -I` prints the Pi's
   address on this network.

   ```bash
   nmcli device status
   hostname -I
   ping -c 3 1.1.1.1
   ```

4. On each PC, put that address under `Host pi` in `~/.ssh/config` (see
   "Working on it").

`sudo nmtui`, then "Activate a connection", does steps 1 and 2 with menus.

The network is saved: from then on the Pi joins it by itself, and
`robot-wifi` brings the Pi back onto it like the other saved networks.

If it does not work:

- The network is not in the list. The Pi 3 A+ sees both Wi-Fi bands. A Pi
  Zero 2 W has the 2.4 GHz band only: there a network that is sent on 5 GHz
  alone is not shown. Switch on the router's 2.4 GHz band.
- The password is refused. Try once with it visible, to see what the
  keyboard really produces: `sudo nmcli device wifi connect "Network Name"
  password 'the password'`.
- A failed try has left the network among the saved ones (`nmcli connection
  show` lists them). Remove it with `sudo nmcli connection delete "Network
  Name"` and join again; otherwise `robot-wifi` keeps trying it.
- The times in the logs look wrong. The Pi has no clock of its own: after a
  start it goes on from where its clock stood at the last shutdown, until a
  network gives it the time. What was logged before the join carries that
  old time.

## Working on it

Develop on a PC, push to GitHub, deploy to the Pi. Never edit files on the
Pi. The repo is on two Windows PCs, a laptop and a desktop, and the work is
the same on both. Start with a pull, because the other PC may have pushed
since, and end with a push: what is not pushed is on one PC only.

```powershell
git pull --ff-only
.venv\Scripts\python.exe -m unittest discover -s tests -t .
git push
ssh pi "bash ~/robot/scripts/deploy.sh"
```

The tests need no API key and make no network calls: a fake client scripts the
model's replies, and recorded API replies are replayed through the real SDK.

`ssh pi` is an alias in each PC's own `~/.ssh/config` pointing at the Pi's IP
address. That address comes from the router, so it changes when the Pi moves
to another network, and each PC's alias has to be put right separately. If
`ssh pi` times out, the address has changed; see `CLAUDE.md`.

A PC needs three things for this: a key of its own that the Pi accepts, the
`pi` alias, and a `.venv` in its checkout for the tests. Both PCs have them.
`CLAUDE.md` ("The two PCs") says how they were set up and where the two
differ: the desktop has PowerShell only, the laptop also Git Bash.

## Files

- `robot/main.py`: the command line.
- `robot/agent.py`: the run loop. `robot/api.py`: the model call and its retries.
- `robot/console.py`: everything printed and typed, and Ctrl-C handling.
- `robot/tools.py`: the Pi's own tools. `robot/hearing.py`: recording through the microphone and having the speech in it turned into text. `robot/handsfree.py`: listening for a spoken message while the robot waits for one. `robot/speaking.py`: having a text turned into speech, and playing it. `robot/power.py`: switching the Pi off after a spoken goodbye. `robot/meta.py`, `robot/spawn.py`: the Meta tools and child runs.
- `robot/instructions.py`, `robot/skills.py`: the library and the skills.
- `robot/prompts.py`: the system prompt's wording.
- `robot/models.py`: model and price tables. `robot/costs.py`, `robot/chats.py`, `robot/history.py`, `robot/datastore.py`, `robot/relay.py`: supporting parts.
- `robot/tui/`: the windowed interface. `app.py`: the main window and how a run and the screen work side by side. `editor.py`, `skillsui.py`: the Instruction Editor and the Skills Manager. `widgets.py`, `dialogs.py`: buttons, lists, text boxes and small windows. `screen.py`: the screen and the keyboard (curses). `text.py`: wrapping and editing text.
- `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`: the tmux launchers for the chat and the windowed interface. `scripts/deploy.sh`: run on the Pi to update it. `scripts/wifi-reconnect.sh`: the `robot-wifi` service, which puts the Pi back on the Wi-Fi. `scripts/autostart.sh`: the switch for starting the interface and its run when the Pi starts, and what the `robot-autostart` service runs. `scripts/pi_photo.py`: run on a PC, fetches a photo from the Pi and opens it. `scripts/pi_sound.py`: the same for a sound recording, which it plays.
- `tests/`: the test suite. `CLAUDE.md`: detailed notes for Claude Code sessions.

## Setup on the Pi

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed. An
  `XAI_API_KEY=...` line there as well lets the robot hear and speak (see
  `microphone_listen` and `speak` under "Tools").
- Passwordless sudo for the Pi's user, if the agent should have root.
- `deploy.sh` installs the pinned Python packages and tmux, and sets up the
  `robot-wifi` service (it needs sudo for that).

### Another board

On 2026-11-22 the SD card went from the Pi Zero 2 W into a Pi 3 Model A+ as
it was, and started there as the same machine, on the Wi-Fi by itself. Three
things to know when the card moves:

- The router gives the other board another address, so `ssh pi` times out on
  the PCs. `ssh pi-local` still works: `hostname -I` there prints the new
  address, which goes under `Host pi` in `~/.ssh/config` on each PC (see
  "Working on it").
- The Pi 3 A+ has one USB port. The webcam and the keyboard's receiver need
  a hub to be in at the same time.
- Two texts tell the robot about its board, and neither follows the card by
  itself. The first sentence of the system prompt names the Pi it runs on
  (`robot/prompts.py`: a change in the repo, then a deploy). And the
  `cpu-temp` skill on the Pi says how hot is hot: the 3 A+ lowers its clock
  from 1.4 to 1.2 GHz at 60 degrees already (measured), while a Zero 2 W
  slows down only from 80 (by Raspberry Pi's documentation). Both texts
  still described the Zero 2 W the morning after the move and were put right
  on 2026-11-23.
