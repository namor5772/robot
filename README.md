# robot

The agent "brain" for a small robot running on a Raspberry Pi 3 Model A+
(until 2026-11-22 a Pi Zero 2 W: the same SD card runs on both). It talks to
Anthropic's Claude models and can act on the Pi through tools. With a webcam
and speakers attached it also sees, hears speech and talks out loud (see
"Tools"); the hearing and the voice come from xAI's speech services.

The program is a terminal port of the MyAgent harness: the same way of running
saved instructions, the same skills format, the same Meta tools and Convo
mode, the same cost log. In place of MyAgent's graphical windows it has
windows drawn with characters, which work over SSH and on the Pi's own
screen. It leaves out MyAgent's safety-confirm system and every provider
other than Anthropic.

What it can do, in short:

- **Two faces.** A line-by-line chat (`chat.sh`) and a windowed interface
  (`ui.sh`) with buttons, an Instruction Editor, a Skills Manager and a
  Memories window. Both run inside tmux and survive a dropped connection.
- **Saved instructions.** A task together with its model, thinking level and
  switches, run by name: from the interface, from the command line, headless,
  or by another run as its child.
- **Skills.** Pieces of know-how that every run can draw on, always or on
  demand.
- **Tools.** A shell on the Pi with no restrictions, web search, looking at
  pictures, hearing speech, speaking, and tools with which it manages its own
  instructions, skills and memories.
- **Hands-free.** It listens whenever it waits for you, answers aloud if told
  to, and switches itself off at a spoken "bye".
- **Memory.** An instruction with Memory on wakes up knowing what the robot
  remembers of earlier conversations.
- **Starting by itself.** Switched on, the Pi can come up running an
  instruction and listening, with no screen and no keyboard.

## Contents

- [Starting a chat](#starting-a-chat)
- [The windowed interface](#the-windowed-interface): the main window, more
  than one at a time, starting with the Pi, the Pi's own screen
- [Every way to start a run](#every-way-to-start-a-run): interface, chat,
  headless, child runs
- [Saved instructions](#saved-instructions)
- [Skills](#skills)
- [What the robot is told: the system prompt](#what-the-robot-is-told-the-system-prompt)
- [Models and thinking levels](#models-and-thinking-levels)
- [Tools](#tools): seeing, sound, hearing, speaking, hands-free, child runs
- [Memory](#memory)
- [What you see](#what-you-see) and [What it costs](#what-it-costs)
- [Where things are kept](#where-things-are-kept)
- [Settings in the environment](#settings-in-the-environment)
- [Backing up the Pi](#backing-up-the-pi)
- [Getting back on the Wi-Fi](#getting-back-on-the-wi-fi)
- [Working on it](#working-on-it), [Files](#files) and
  [Setup on the Pi](#setup-on-the-pi)

Commands are shown in full, as `bash ~/robot/scripts/chat.sh`. At the Pi's
own prompt the four scripts typed by hand can be started by name from any
folder (`chat.sh`, `ui.sh`, `autostart.sh`, `deploy.sh`; see "Setup on the
Pi").

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

To run a saved instruction in place of typing the task, name it:
`bash ~/robot/scripts/chat.sh -l "Name"` (see "Saved instructions", and
"Every way to start a run" for all the other ways).

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
- A second `chat.sh` while a chat is open joins that chat. Arguments given
  with it (`-l "Name"`, say) are ignored then, and it says so.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.main`. The chat then
belongs to your terminal and ends with it.

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
 [ START ] [ STOP ] [ Instruction ] [ Skills ] [ Memories ]   [ Help ] [ Quit ]
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
  the group of five Meta tools (see [Tools](#tools)). No other tool is shown
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
  Fast, Meta, Convo, Memory, notes, blocked tools, skills, upgrade model,
  text). Memory is a list: off, shared, each named memory, or a new name
  (see "Memory").
  *Save* stores the form under the name in the Name box, so a new name makes a
  new instruction. *Use* makes it the one START runs.
- **Memories** (F6) opens the Memories window: what the robot remembers,
  memory by memory (see "Memory"). In a window under 78 columns wide the
  Help button gives up its place to this one; F1 still opens the help.
- **Skills** (F5) opens the Skills Manager: every skill with its mode, text,
  description and bundled files. Space on the list switches a skill between
  off, ON (in every prompt) and OD (on demand).
- **The boxes along the bottom** choose what a run shows: Activity (tool lines
  and the cost of each call), Thinking, Tool calls (each call as JSON) and
  Debug (every request sent). **Save thinking** keeps the model's thinking
  in the saved chat. The last one,
  **Hands-free** (Alt+H), has the robot listen for a spoken message whenever
  it waits for you (see "Hands-free" under "Tools"). All six are remembered.
  In a narrow window the boxes take two rows.
- **The bottom line** says what is going on (`Ready`, `Working 0:12`,
  `Waiting for your message`, and with Hands-free `Listening`, `Hearing
  you...`, `Working out what you said...`), then a short message when there
  is one, then a reminder of the main keys.
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
- It needs a window of at least 72 columns by 18 rows, and says so in a
  smaller one until the window is made larger.
- START never has the cursor when the interface opens or a run ends: a
  stray Enter must not start a run that costs money.
- An interface that was open during a deploy keeps the old program until it
  is quit and started again.

Without tmux: `cd ~/robot && .venv/bin/python -m robot.tui`.

Options of `ui.sh`: `-l "Name"` opens on that instruction, `--session NAME`
is a further interface (see "More than one at a time"), `--start` begins the
run without START, and `--headless` is one run nobody has to watch (see "A
headless interface").

### Starting by itself when the Pi starts

The Pi can start the windowed interface on its own screen when it is switched
on, and begin the run at once, with nothing typed:

```bash
bash ~/robot/scripts/autostart.sh on       # from the next start on
bash ~/robot/scripts/autostart.sh off      # not any more
bash ~/robot/scripts/autostart.sh status
```

What starts is the first interface (the one with no session name) as you
left it: the instruction it had last and its boxes, Hands-free among them. So
tick Hands-free and choose the instruction you want once, and from then on
the Pi comes up running it and listening. To have it come up with another
instruction: join the interface over SSH, end the run with STOP (F3) or a
typed "stop", open the Instruction window (F4), pick the instruction and
press *Use*. That is saved at once; the instruction need not be run.

- It first waits (three minutes at most) for the Wi-Fi and for the clock to
  be set. On the Pi 3 A+ a run is listening about 47 seconds after the Pi
  got its power.
- It is the ordinary interface: `ssh -t pi "bash ~/robot/scripts/ui.sh"`
  joins it from a PC, and when the run has ended (say "stop", or type "bye")
  you can choose another instruction there and press START.
- It starts one run per start of the Pi and does not start another by itself
  afterwards.
- Every start of the Pi is then a paid run, and with Hands-free the robot
  answers whoever speaks near it.
- What it did at the start is in `/var/log/robot-autostart.log`.

The Pi needs no screen for any of this, and no keyboard: with none attached,
the SSH command above is how you see the interface. It takes your terminal's
size once you join.

Saying "bye" is different: it ends the conversation and switches the Pi off
(see "Hands-free" under "Tools"). So with autostart on, the robot's day is:
give it power, it comes up and listens, you talk, you say "bye", it switches
itself off, and you can take its power away.

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

#### What an interface remembers, and what it does not

Several interfaces are like several MyAgent windows: separate programs, each
with a run of its own and something it remembers. An interface remembers
two things, in a file of its own (`tui_state.json` for the first,
`tui_state_NAME.json` for one started with `--session NAME`):

- the NAME of the instruction it has in use: the one last chosen with *Use*
  in the Instruction Editor. Running an instruction does not change it, and
  neither does a chat, a headless run or a child run;
- its six bottom-row boxes (the five display boxes and Hands-free).

So there is one remembered instruction per interface, not one for the Pi.
An interface started under a name never used before has no file yet and
opens on `Default`, and so does one whose instruction has been deleted.
`-l "Name"` on the command line takes the place of the remembered one for
that start. The first interface's file is also what decides which
instruction starts with the Pi.

Everything else comes with the instruction, not with the interface. It is
kept in the instruction's own entry and looked up from the name when START
is pressed:

- its text, model, thinking level and fast mode;
- Meta, Convo and Memory, on or off;
- which tools are blocked for it;
- its own skill modes, where it has any;
- its upgrade model;
- which memory it uses: the shared one, or one with a name.

What follows from that:

- Two interfaces with the same instruction in use get the same settings.
  Change its model in the editor from one of them, and the other runs it on
  the new model the next time.
- The settings are read at START. A run that is going keeps what it started
  with.
- A memory belongs to its name, not to an interface: two interfaces whose
  instructions name the same memory read and write the same one.
- To run the same task with different settings in two interfaces, make two
  instructions.

Two things are in neither place:

- Every skill has a general setting (on, on demand or off) that all
  instructions share. An instruction's own skill modes take its place for
  that instruction's runs; an instruction with none uses the general ones.
- All interfaces share the one microphone and the one pair of speakers, so
  only one of them should be listening hands-free.

Compared with MyAgent: there each window is told apart by a number it is
given when it starts (1, 2, 3 in the order of starting), and it remembers
its window's size and place and its model settings as well. Here the name is
the one you type, so session 2 is the same one whatever was started first,
and typing the name again brings that interface back.

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

## Every way to start a run

A run gets started in one of three ways: from the windowed interface, by the
chat program, or by another run as its child. Whether it is a single task or
a conversation is not decided by how it starts but by the instruction (see
"Single task or conversation" below). The commands are as typed on the Pi in
`~/robot`; from a PC put them in `ssh -t pi "..."`.

### From the windowed interface

| How it starts | Command | Notes |
|---|---|---|
| By hand | `bash scripts/ui.sh`, then START | Runs the instruction the interface remembers. It is inside tmux, so it survives a dropped connection. |
| On a named instruction | `bash scripts/ui.sh -l "Name"`, then START | Opens on that instruction instead of the remembered one. |
| A further, separate interface | `bash scripts/ui.sh --session 2` | A run of its own, and its own remembered instruction and boxes. Any short name will do for the 2. |
| Without pressing START | `bash scripts/ui.sh --start` | The run begins by itself; the interface stays afterwards. |
| Headless | `bash scripts/ui.sh -l "Name" --headless` | One run that nobody has to watch, in an interface of its own that closes when the run has ended (see "A headless interface" below). |
| When the Pi starts | `bash scripts/autostart.sh on`, once | Starts the first interface with `--start` on the Pi's own screen (see "Starting by itself when the Pi starts"). |
| Joined from another screen | `bash scripts/ui.sh` again | The same program and the same run, on a second screen. |

You type into its input box, stop a reply with STOP, and speak to it when its
Hands-free box is ticked.

#### A headless interface

`ui.sh -l "Name" --headless` is MyAgent's `--headless` for the robot: the
run of that instruction starts at once, in an interface that is not put on
your screen, and the interface closes by itself when the run has ended.

```
$ ui.sh -l "Night watch" --headless
Started as the interface 'h1'. It closes when the run has ended.
To watch it meanwhile: ui.sh --session h1
```

- Every headless start is an interface of its own: it takes the first free
  of the names `h1`, `h2`, ... and never joins one that is running. Give it
  a name of your choice with `--session NAME`; a name that is in use is
  refused.
- It is a whole interface all the same. `ui.sh --session h1` shows it while
  the run goes, its bottom line says `Headless: closes when the run ends`,
  and you can read along, answer a question or press STOP. Ctrl-B then D
  leaves it running again.
- It remembers nothing: no file is written for `h1`, so the next `h1`
  starts with the boxes at their usual settings (Hands-free off).
- The instruction must be there and must have a saved task. If not,
  `ui.sh` says so at once and starts nothing.
- A question is not answered by anybody unless you join. An instruction
  with Convo on waits for a message after every reply (`ui.sh` says so when
  it starts one): for a run nobody watches, use an instruction with Convo
  off.
- The saved chat and the line in the cost log are written as for any run.

Compared with `robot.main -l "Name" --headless` (the chat program,
headless): that one ends at its first question and cannot be watched or
stopped from a screen; this one waits for you and can be joined at any
time, and it takes the memory of a whole interface.

### With the chat program

| How it starts | Command | Who answers its questions |
|---|---|---|
| In tmux, typing the task | `bash scripts/chat.sh` | You, at `you>` |
| In tmux, a saved instruction | `bash scripts/chat.sh -l "Name"` | You, at `you>` |
| Directly, without tmux | `.venv/bin/python -m robot.main` (with or without `-l "Name"`) | You. The run ends if the terminal goes away. |
| With speech | add `--hands-free` | You, speaking or typing. At a terminal only. |
| Piped | `printf 'first\nsecond\n' \| .venv/bin/python -m robot.main` | The piped lines, in order. The end of the input ends the run. |
| Headless | `.venv/bin/python -m robot.main -l "Name" --headless` | Nobody: a question ends the run. It needs a saved instruction that has text. |
| Headless with a relay | add `--relay-dir DIR` | Another program, through files in that folder. |
| Nothing sent | add `--dry-run` | Prints the first request and costs nothing. |

A second `chat.sh` while a chat is still open in tmux rejoins that chat and
ignores the `-l "Name"` given with it.

These work with any of the above: `--model` and `--mode` (for this run only,
nothing saved changes), `--prepend-file` and `--extra-file` (text in front of
and after the instruction, for this run only), `--result-file` (the outcome
as JSON) and the display options `--thinking`, `--tool-calls`, `--debug` and
`--no-activity`. `--help` lists them all.

### As a child of another run

A run whose instruction has Meta on can start a saved instruction as a child
with its `run_instruction` tool. A child is always the chat program, headless.

| Variant | What the parent run gets | Who answers the child's questions |
|---|---|---|
| Not waited for (the default) | An answer at once, with the child's process number | Nobody: it stops at its first question |
| Waited for (`wait`) | The child's final report | You, at the parent's terminal or interface |
| With `answers` | As above | The prepared answers, in order. When they are used up the child stops. |
| With `show_window` | As above | As above. You can also watch what it writes, in a tmux session `child-NAME-PID`. |

A child may start children of its own; those may not. See "Tools" for how
many can run at once.

### Single task or conversation

- **Convo off**: the run does its task and ends. It can still ask you
  something through its `user_prompt` tool.
- **Convo on**: after every reply it waits for your next message. `quit`,
  `stop`, `exit` or `bye` on its own, or an empty reply, ends it.

### Stopping and ending

- Ctrl-C in the chat, or STOP (F3) in the interface, stops the reply or the
  command in progress. In the interface, STOP while the robot waits for your
  message ends the run.
- An end word (`quit`, `stop`, `exit`, `bye`) or an empty reply ends a
  conversation. An empty reply to a question the robot asked stops the run.
- A SPOKEN "bye" in a hands-free run ends the conversation and powers the Pi
  off. A typed "bye" only ends the run.
- Stopping a run that is waiting for a child stops the child as well.
- Quit (F10) in the interface asks first when a run is going, then stops it
  and waits until its cost is logged and its chat saved.
- Ctrl-B then D leaves a chat or an interface running in tmux and gives you
  your terminal back. It ends nothing.
- The chat program ends with exit code 0, with 1 when the run ended in an
  error, and with 2 when it could not start (no such instruction, no key).

### What is remembered afterwards

- An interface remembers its instruction and its bottom-row boxes, each
  interface under its own name (see "More than one at a time").
- A chat, a piped run, a headless run and a child run remember nothing of
  that kind: the instruction is named with `-l` each time.
- Every run, however it was started, leaves a saved chat and a line in the
  cost log, and its conversation is remembered if its instruction has Memory
  on. A run that was killed leaves its transcript as far as it got, and its
  cost is logged at the next start of any run.

Nothing starts runs on a schedule. The start with the Pi is the only
automatic one; a headless run is what a scheduled job would use.

## Saved instructions

An instruction is a saved task together with the settings to run it with:
model, thinking level, fast mode, Meta on or off, Convo on or off, Memory on
or off (see "Memory"), blocked tools, skill modes and an upgrade model. Its text is the first message of the
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
(for you, never sent to the model), `fast_mode`, `blocked_tools` (a list of
tool names), `skill_modes` (see "Skills"), `upgrade_target` (see "Models and
thinking levels"), `memory` (true or false) and `memory_name` (which memory:
left out or empty is the shared one, see "Memory").

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
  comes in as disabled until you set one. A skill written for MyAgent may
  name tools the robot does not have (`run_command` where the robot has
  `run_shell_command`).

The skills on the Pi on 2026-11-28. They are data on the Pi, not part of
this repository, and `--skills` shows what is there now:

| Skill | What it is for |
|---|---|
| `robot-identity` | How the robot replies: briefly and out loud, and that its voice can be changed. |
| `take-photo` | Taking a photo with the webcam and looking at it with `view_image`. |
| `record-sound` | Recording through the webcam's microphone to a WAV file. |
| `play-sound` | Playing a WAV file through the speakers: one of its recordings, or any other. |
| `cpu-temp` | Reading the CPU temperature, and how hot is hot on this board. |
| `wifi-monitor` | The `robot-wifi` service and its log of drops and reconnects. |
| `weather` | Real weather for a place: forecast and current readings. |
| `share-price` | A near-live share price, index or exchange rate, with the day's change. |

Their modes are not listed here because they change: on that one day the
skills' own modes went from one enabled and seven on demand to all eight
enabled. And an instruction can carry modes of its own, which then count for
its runs: `Default` did, with `robot-identity` off and the other seven on
demand, so a plain chat's prompt held the seven descriptions and no skill's
full text. An enabled skill's text is in every prompt of the runs it is
enabled for; one on demand costs only its description until a run fetches
it. `--dry-run` shows what a given run gets (see the next section).

## What the robot is told: the system prompt

Every run starts with a system prompt: the standing text the model is given
before the task. Its wording is the same for every instruction, and a few
parts of it are filled in from the instruction's settings. The instruction's
own text is not in it: that is sent as the first message, the task.

It is sent in two blocks.

**Block 1, the same for every run that shares its settings:**

| Part | Where it comes from |
|---|---|
| The opening lines: the robot's name and character | The owner's own text, in `robot/prompts.py` |
| Speak as the robot, in the first person; answer about this Raspberry Pi | Fixed wording, in the same file |
| The tools are the only way to sense or act; say plainly what it cannot do; never invent a sensor reading | Fixed |
| Carry the task out fully, chaining tools without asking | Fixed |
| One paragraph that depends on Convo | Convo on: "This is a conversation ... just reply", with `user_prompt` only for an answer needed in the middle of a task. Convo off: a single task, where it must ask through `user_prompt`. |
| Plain text only, no Markdown | Fixed: replies are shown in a plain terminal |
| The text of every skill that is enabled | The skills on the Pi, as that instruction has them |
| The list of on-demand skills, each with its description | The same. With none on demand, the list and the `get_skill` tool are left out. |

**Block 2, different from run to run:**

| Part | When |
|---|---|
| "About this run": the instruction's name (or that it is a chat on `Default`'s settings) and the model it started on | Always |
| A sentence saying that after `upgrade_model` the tool's result names the model | Only when the run has that tool (Meta on) |
| What the robot remembers, its diary of the last conversations, and when it was last awake | Only with Memory on (see "Memory") |

So what differs between two instructions is small: the Convo paragraph, the
skills, and block 2. Two instructions with the same Convo setting and the
same skills have the same block 1 word for word, whatever their text, model
or name. That is on purpose. Block 1 is what is written to the prompt cache
(see "What it costs"), so runs of different instructions started within five
minutes of each other share it, and only the first pays for writing it.
Nothing in the prompt changes during a run: a skill or an instruction made
in the middle of one takes effect from the next.

Not in the system prompt, but sent with it and different per instruction:
the list of tools with their descriptions (Meta adds five, and an
instruction's blocked tools are left out), and the model, thinking level and
fast mode, which are settings of the request.

To see exactly what a run would be told, without sending anything and at no
cost:

```bash
cd ~/robot
printf 'hello\n' | .venv/bin/python -m robot.main --dry-run            # a plain chat
.venv/bin/python -m robot.main -l "Name" --dry-run                     # a saved instruction
```

It prints the banner and then the whole first request: the two `system`
blocks, the tools and the first message. On 2026-11-28 a plain chat's block 1
was 3,470 characters, most of it the seven on-demand skills' descriptions,
and its block 2 was 279.

## Models and thinking levels

Every instruction names its model and a thinking level. The program runs
Anthropic's models only.

| Model | Id | Price per million tokens: input / output |
|---|---|---|
| Opus 5.5 (the default) | `claude-opus-5-5` | $4 / $20 |
| Fable 5.2 | `claude-fable-5-2` | $8 / $40 |
| Sonnet 5.5 | `claude-sonnet-5-5` | $2 / $10 |
| Haiku 5.5 | `claude-haiku-5-5` | $0.10 / $0.50 |

The Instruction Editor's model list also offers the earlier ones the program
knows (Opus 5 and 4.8, Fable 5.1 and 5, Sonnet 5 and 4.6, Haiku 4.5), and any
other id can be typed into an instruction by hand. A model the program has no
price for is warned about when its run starts, and that run is not written to
the cost log.

- **Thinking level**: `off`, `adaptive`, `low`, `medium`, `high`, `xhigh` or
  `max`. Not every model has every level, and one it lacks is replaced by
  the nearest it has. Opus 5.5 and Fable always think: they have no `off`.
- **Fast mode** (`fast_mode`, the Fast box) asks for faster output where the
  model offers it (Opus from 4.8, Fable from 5.2), at twice the price.
- **Upgrade model.** With Meta on, a run can move itself to a stronger model
  once, with its `upgrade_model` tool, when you ask for it ("use the stronger
  model for this"). Where it goes is the instruction's upgrade model
  (`upgrade_target`), and Fable 5.2 at its highest level where none is set.
  Nothing saved changes, and the cost log says from which call on.
- `--model ID` and `--mode LEVEL` on the command line change one run of the
  chat program, and nothing that is saved. `--model claude-haiku-5-5` makes a
  whole chat cost well under a cent.
- There is no temperature setting anywhere: the current models do not take
  one.

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
| `manage_memories` | Meta on | Lists and reads the memories, adds a thing to one at once, corrects one, copies one. It cannot delete one (see "Memory"). |
| `run_instruction` | Meta on | Runs another instruction as a child run. |
| `upgrade_model` | Meta on | Moves the rest of the run to a stronger model. |

Meta is the only group of tools. It is one switch on an instruction, and it
turns the last five on together: the tools with which the robot works on its
own setup. Their descriptions add about 3,500 tokens to every request. The
first nine are not grouped: each is offered on its own, whenever it can work.
The start banner of every run lists the tools that run has.

The model can ask for several tools in one turn. Several `run_instruction`
calls then run side by side (that is how a run starts children that work at
the same time), and so do `get_skill` calls. The rest, the shell among them,
run one after the other.

There is no tool for the CPU temperature any more (there was one until
2026-11-20). Asked how hot it is, the robot reads the Pi's sensor with the
shell tool, told how by its `cpu-temp` skill.

### Seeing

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
changed. Photos are personal: the script keeps them out of this repository
and out of folders that are synced elsewhere.

The robot's photos are in `robot-photos` in the Pi's home folder. The webcam
is a Logitech Brio 100 on the Pi's one USB port; it gives photos of up to
1920 x 1080.

### Recording and playing sound

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

### Hearing

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

### Speaking

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
  this conversation now. Goodbye, till we meet again." A typed end word ends the
  conversation without that.
- **A spoken "bye" also powers the Pi off.** Only that word, and only when
  it was said, not typed. Its goodbye is its own: "I am powering myself off
  now. Goodbye, till we meet again." Then, once the run's cost is logged and its
  chat saved, the Pi runs `sudo poweroff`, without asking. To use it again, take its
  power away and give it back; with autostart on it then comes up running
  and listening. "Stop", "quit" and "exit", spoken or typed, a typed "bye",
  STOP, Quit and an empty message all leave the Pi on.
- If the microphone cannot be used (another program has it, or no xAI key),
  a warning says so once and typing goes on working.
- Every message is one transcription, about a hundredth of a cent, billed by
  xAI and not in the robot's cost log.
- There is one microphone and one pair of speakers. Of two runs that both
  want to listen, the first has the microphone: the second says that it
  cannot listen, and typing goes on working there. Keep to one hands-free
  run at a time.
- In the chat it is the option `--hands-free`, at a terminal only; in the
  interface it is the Hands-free box, which each interface remembers. A
  piped run, a headless run of the chat program and a child run never
  listen this way.

### Switching tools off for one instruction

Any of the fourteen can be switched off for one instruction. In the Instruction
Editor the Tools button shows this list, in this order, with a tick beside
each tool the instruction may use. A cleared tool is blocked for that
instruction only (`blocked_tools` in the file), and a Meta tool needs both
the Meta switch and its tick. While the instruction's Meta box is not ticked,
the five Meta tools show `[-]` and "(needs Meta)" there in place of a box and
cannot be ticked or cleared: no run would get them either way. A block set on
one of them earlier is kept, and shows again once Meta is ticked.

### The shell tool has no restrictions

The shell tool is deliberately unrestricted: no confirmation, no allowlist, no
blocked commands, and the Pi has passwordless sudo, so the agent has root. It
can read `~/robot/.env`, change any file, and act on what it reads from the
web. With Meta on it can also write skills that later runs load, so text it
picked up can outlast a session: the start banner lists the skills in use. To
take root away, run `sudo rm /etc/sudoers.d/010_grobliro-nopasswd` on the Pi.
An instruction's `blocked_tools` list removes tools from its runs.

### Child runs

With Meta on, a run can start a saved instruction as a run of its own with
`run_instruction`, and either go on at once or wait for its report (see "As
a child of another run" for the variants). Ask for it in words: "run the
Health check instruction and tell me what it says".

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

A child run normally works out of sight. When the robot starts one with
`show_window` (ask it to "show the child's window"), what the child writes
appears in a tmux session of its own, named `child-NAME-PID`, beside the
interface or chat the run was started from: Ctrl-B then S lists the sessions,
and Ctrl-B then `)` goes to the next. The robot says the session's name when
the child starts. The window only shows: the child takes no typing there, and
its questions still come to the run that started it. It closes when the child
ends; if you are watching at that moment it waits for Enter (up to five
minutes) so that the last lines can be read, and then takes you back to
another session.

## Memory

A run does not know the runs before it. An instruction with **Memory** on
does: the robot wakes up knowing what it remembers of earlier conversations,
and when the conversation ends it remembers that one too. Choose a memory in
the Instruction Editor's Memory list (Alt+M) and save; it is off unless you
do. The top row of the interface then says `memory`, or `memory: NAME`.

- **Waking up.** At the start of the run the robot is told three things: its
  memory (a text of up to about 3,000 words, in its own words), its diary of
  the last 7 conversations, and when it was last awake and what time it is
  now. It is also told where the word-for-word record of every conversation
  is (`saved_chats`), so that it can look up a detail it no longer remembers.
- **Falling asleep.** When the run ends, however it ends, the program says
  `Remembering this conversation...` and makes one more call, to a model of
  its own (Sonnet 5.5): it reads the conversation and the memory as it was,
  and writes the memory anew and a few lines for the diary. That takes 5 to
  15 seconds and costs about a cent for a short conversation; the cost is on
  the run's line in the cost log. After a spoken "bye" the Pi powers off
  only when this is done.
- **Cut off.** If the power goes or the program is closed before that, nothing
  is lost: the next run with Memory on does the remembering first
  (`Remembering an earlier conversation first...`), from the record on disk.
- A conversation in which you said nothing, or only goodbye, is not sent
  anywhere and costs nothing.
- A memory is not part of an instruction: the instruction only says which
  one it uses. The Memory list offers:
  - **off**: no memory.
  - **shared**: the one memory that instructions use together. Whatever
    the robot was told in one of them it knows in the others.
  - **a name**: a memory of its own. Two instructions that have the same
    name share that memory, and no other instruction sees it.
  - **new name...**: asks for a name (1 to 40 letters, digits, spaces, `-`
    or `_`) and starts an empty memory under it. Nothing has to be created
    first: its files appear when the first conversation has been remembered.
- Deleting or copying an instruction leaves its memory as it is.
- It works the same however the run was started: interface, chat, headless
  or as a child.

### Remember this, forget that

With Meta on, the robot has a tool for its memories, `manage_memories`, so
that it can act in the middle of a conversation and not only when it ends:

- **"Remember that ..."**: it adds the thing to its memory at once, as a dated
  line under "Asked to remember". It is then kept even if the run is cut
  off.
- **"Forget that ..."**, or a correction: it reads its memory and writes it
  again without that, or put right. The text as it was is kept among the
  earlier states, so you can roll it back.
- It can list the memories, read any of them (not only its own), and copy
  one under a new name.
- It **cannot delete** a memory or roll one back: that is for you, in the
  Memories window. With Hands-free on the robot hears whoever speaks, and a
  deleted memory cannot be had back.

What it changes this way it knows from its next waking: within the same
conversation it goes by what was said.

### The Memories window

**Memories** (F6) in the windowed interface lists the shared memory and every
named one. For the one selected it shows which instructions use it, how
large it is, when the robot was last awake with it, and the text and diary.
It opens on the memory of the instruction in use (on the shared one when
that instruction has no memory), and lists that memory even while nothing
has been remembered in it yet.

- **Edit** corrects what is remembered, by hand. The diary is a record and is
  not edited here.
- **Copy** makes a second memory from it under a new name, for an experiment
  that should not touch the original.
- **Roll back** lists the earlier states (the last 30 are kept, one from
  before every change), shows the one you pick, and makes it the memory
  again if you say yes. The state you leave is kept too.
- **Delete** makes the robot forget: the text, the diary and the earlier
  states. It names the instructions that will start again with nothing.
- While a run is using a memory, that memory cannot be changed here: the run
  writes it when it ends.

### The files

The memory is plain text in `~/robot-data/memory`, and yours to read and
correct there as well: `memory.md` is what the robot remembers, `diary.md` its
diary, and `versions/` holds the earlier states of `memory.md`. That folder
is the shared memory; a named one has the same files in a folder of its
name inside it (`~/robot-data/memory/NAME/`).

```bash
.venv/bin/python -m robot.memory list            # the memories, and who uses each
.venv/bin/python -m robot.memory show            # what a run would be told now
.venv/bin/python -m robot.memory show --name NAME   # the same for a named one
.venv/bin/python -m robot.memory try CHAT.txt    # what that saved chat would leave
                                                 # (one paid call, changes nothing)
.venv/bin/python -m robot.memory try CHAT.txt --model claude-haiku-5-5
```

The model that does the remembering is Sonnet 5.5. Another one is set with
`ROBOT_MEMORY_MODEL=...` in `.env`, or with `{"model": "..."}` in
`~/robot-data/memory/settings.json` (one setting for every memory); `try` is
for comparing them on a chat you know.

With Hands-free on, whoever speaks is heard, and what was heard is
remembered: the robot is told to leave out what makes no sense, but a
visitor's words or a radio's can end up in its memory.

## What you see

```
you> How hot are you, and how long have you been up? Check both.
  call 1: $0.0014 this call  |  $0.0014 total  (in:4  out:188  cache_write:10,665)
[tool: run_shell_command: {"command": "cat /sys/class/thermal/thermal_zone0/temp; uptime -p; uptime -s"}]
robot> I'm running at about 49.4°C, which is comfortably cool for this Pi. I've been up for 2 hours and 25 minutes, since 08:56:35 on 2026-11-20.
  call 2: $0.0002 this call  |  $0.0016 total  (in:2  out:117  cache_write:237  cache_read:10,665)
```

(That chat ran on `claude-haiku-5-5`, when the tool list was shorter than it
is now.)

- The start banner names the instruction, the model and its thinking level,
  the tools this run has, the skills in use and whether Memory is on.
- `you>` is you, and `robot>` the model's reply as it arrives.
- `[tool: ...]` is a tool the model called, with what it asked for.
- Each `call` line is one request to the model: what it cost, the total so
  far, and the tokens (`in`, `out`, and what was written to and read from
  the prompt cache).
- At the end the run's total goes into the cost log, and the line that was
  written is shown.

Options for what is shown: `--no-activity` (hide tool and cost lines),
`--thinking`, `--tool-calls`, `--debug`. Others: `--model ID` and `--mode LEVEL`
for one run, `--dry-run` to print the request without sending it, and
`--help` for the rest. In the interface the bottom-row boxes do the same.

## What it costs

Two companies bill for what the robot does: Anthropic for the model, and xAI
for hearing and speaking. The robot's cost log holds Anthropic's part only.

**The model.** The first call of a run costs the most, because the system
prompt and the tool list are written to the prompt cache: about 14,000
tokens with Meta on and the Pi's skills as they are (about 10,000 with Meta
off). Later calls read them back at a fraction of the price, as long as the
next call comes within five minutes.

| | Haiku 5.5 | Opus 5.5 (the default) |
|---|---|---|
| The first call of a run, Meta on | about 0.2 cents | about 7 cents |
| A later call in a short conversation | about 0.02 cents | under 1 cent |
| A web search, on top of its tokens | 1 cent | 1 cent |
| A 1920 x 1080 photo looked at | well under 0.1 cents | about a cent |

A long run costs more with every call, because the whole conversation is
sent again each time (read from the cache, where it can be).

**Remembering.** A run with Memory on makes one more call when it ends, to
Sonnet 5.5: about a cent for a short conversation. It is on the run's line
in the cost log.

**Child runs.** Every child is a run of its own with a first call of its
own, and a line of its own in the cost log.

**Hearing and speaking** (xAI, not in the cost log):

| What | Price | In practice |
|---|---|---|
| Speech to text (`microphone_listen`, hands-free) | $0.10 for an hour of sound | About a hundredth of a cent for a spoken message. Silence is never sent. |
| Text to speech (`speak`) | $15 for a million characters | About a tenth of a cent for a sentence. |

**The cost log** is `~/robot-data/APICostLog_<host>.txt`, one line per run:
when it ended, the model, the cost in dollars, the thinking level, how long
it took, the instruction's name, the number of calls, the tokens, and the
name of its saved chat. A run that upgraded its model has that noted, and a
run that was killed is logged at the next start as unfinished. A run on a
model the program has no price for is not logged at all.

## Where things are kept

On the Pi, outside this repository, in `~/robot-data`:

| Path | Contents |
|---|---|
| `agent_instructions.json` | The instruction library. |
| `skills/<name>/SKILL.md` | The skills. |
| `saved_chats/` | Every run's transcript (`.txt`, written as the run goes) and messages (`.json`). The name is the instruction's (or `Agent`) and the second the run started, as `Night watch_2026-11-28_092150`; a second run of the same instruction started in that same second has its process number added. Chats are a record: they are never loaded back into a run. |
| `APICostLog_<host>.txt` | One line per run: time, model, cost, tokens (see "What it costs"). On this Pi `APICostLog_robot.txt`. |
| `tui_state.json` | What the windowed interface remembers: the instruction in use and the boxes of the bottom row (Hands-free among them). An interface started with `--session 2` has `tui_state_2.json`. |
| `memory/` | What the robot remembers from one run to the next: `memory.md`, `diary.md`, earlier versions, and a folder per named memory (see "Memory"). `memory/settings.json`, if there, names the model that does the remembering. |
| `voice_settings.json` | The voice and the speed `speak` uses, once one has been chosen. |
| `autostart_on` | An empty file: the switch of `autostart.sh`. There while the Pi is to start the interface by itself. |
| `runs/` | One small file per run in progress, removed when the run ends. An empty folder means nothing is running. A file left by a killed run is how its cost gets logged later. |
| `tmp/` | Files that pass between a run and its child runs, removed afterwards. Here and not in `/tmp`, which on the Pi is held in memory. |
| `tui_errors.log` | Anything a library printed while the windows were up (normally empty). |

Elsewhere on the Pi:

| Path | Contents |
|---|---|
| `~/robot` | The checkout of this repository, with `.venv` and `.env` (the keys; never committed). |
| `~/robot-photos` | The photos the robot takes. |
| `~/robot-sound` | The sound it records, and every sentence it has spoken (`speech_<date>_<time>.wav`). |
| `/var/log/robot-wifi.log` | What the `robot-wifi` service did, and when. |
| `/var/log/robot-autostart.log` | What the start with the Pi did. |
| `~/.bashrc` (its last line) | Puts `~/robot/scripts` on the search path (see "Setup on the Pi"). |

The files in `~/robot-data` use MyAgent's formats, so instructions and
skills can be copied between the two programs. Nothing there is backed up by
itself: see "Backing up the Pi". The Pi keeps no system log across restarts
(its journal is in memory), so the two files in `/var/log` are what there is
to read after one.

## Settings in the environment

Nothing here needs setting for ordinary use. The keys go in `~/robot/.env`,
one `NAME=value` to a line; the others are for a single command, as in
`ROBOT_DATA_DIR=/tmp/try bash ~/robot/scripts/chat.sh`.

| Name | What it does |
|---|---|
| `ANTHROPIC_API_KEY` | The key for the model. Without it no run starts. |
| `XAI_API_KEY` | The key for hearing and speaking. Without it `microphone_listen`, `speak`, `voice_settings` and hands-free are not there. |
| `ROBOT_DATA_DIR` | Another data folder in place of `~/robot-data`: its own instructions, skills, memory, chats and cost log. |
| `ROBOT_MEMORY_MODEL` | The model that does the remembering, in place of Sonnet 5.5. |
| `ROBOT_VOICE` | The voice `speak` uses while none has been saved. |
| `ROBOT_MIC_DEVICE`, `ROBOT_SPEAKER_DEVICE` | A sound device by its ALSA name, in place of the first one found. |
| `ROBOT_SOCKET`, `ROBOT_SESSION` | Another tmux and session for `chat.sh` and `ui.sh`, so that a trial never joins a chat or interface in use. `ROBOT_TMUX_DETACHED=1` starts it without putting it on the screen. |
| `ROBOT_CHILD_SOCKET` | The tmux a child run's window goes to, in place of the one the run is in. |
| `ROBOT_POWEROFF_COMMAND` | What is run in place of `sudo poweroff` after a spoken "bye": set it to something harmless to try that out without the Pi going off. |

## Backing up the Pi

There are two kinds of backup, and both are kept on a PC. Either PC can make
them; so far they are on the laptop.

**The data that changes every day.** Instructions, skills, the robot's
memory, chats and the cost log are in `~/robot-data`, a few megabytes. Its
photos and sound are beside it, in `~/robot-photos` and `~/robot-sound`
(`scp -r pi:robot-photos .` in the same way; keep them out of folders that
are synced elsewhere). From PowerShell, in the folder
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
There are about 1,700 of them. Some need what only the Pi has (bash, curses,
tmux, real process groups) and are skipped on Windows, so the suite is run
on the Pi as well after a deploy:

```bash
cd ~/robot && .venv/bin/python -m unittest discover -s tests -t .
```

- `deploy.sh` runs on the Pi: it pulls with `git pull --ff-only` (which
  refuses if the checkout there was edited), installs the pinned packages
  and tmux, and sets up the `robot-wifi` and `robot-autostart` services. It
  never starts or restarts the interface: one that is open keeps the old
  program until it is quit and started again, and the deploy says so.
- The repository is public. Nothing secret or personal is committed: no
  keys, no addresses, no photos or recordings. The keys are in `.env`, which
  git ignores, and the robot's data is outside the checkout.
- Both PCs have an `ANTHROPIC_API_KEY` of their own, so the program run on a
  PC makes real, paid calls. On a PC use the tests or `--dry-run`; a paid
  trial belongs on the Pi, on `--model claude-haiku-5-5`.
- The owner may be using the Pi while work goes on. A trial there uses a
  tmux of its own (`ROBOT_SOCKET`, see "Settings in the environment") and
  never the sockets `robot` and `robot-ui`, and one that uses the microphone
  or the speakers does not start while `~/robot-data/runs` holds a file.

`ssh pi` is an alias in each PC's own `~/.ssh/config` pointing at the Pi's IP
address. That address comes from the router, so it changes when the Pi moves
to another network, and each PC's alias has to be put right separately. If
`ssh pi` times out, the address has changed (or the Pi is off, as after a
spoken "bye"). `ssh pi-local` reaches the same Pi by its name, `robot.local`,
from PowerShell; `hostname -I` there prints the address to put under `Host
pi`. See `CLAUDE.md` ("Reaching the Pi").

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
- `robot/memory.py`: what the robot remembers from one run to the next, the
  call that does the remembering, and the `python -m robot.memory` commands.
- `robot/prompts.py`: the system prompt's wording.
- `robot/models.py`: model and price tables. `robot/costs.py`, `robot/chats.py`, `robot/history.py`, `robot/datastore.py`, `robot/relay.py`: supporting parts.
- `robot/tui/`: the windowed interface. `app.py`: the main window and how a run and the screen work side by side. `editor.py`, `skillsui.py`, `memoryui.py`: the Instruction Editor, the Skills Manager and the Memories window. `widgets.py`, `dialogs.py`: buttons, lists, text boxes and small windows. `screen.py`: the screen and the keyboard (curses). `text.py`: wrapping and editing text.
- `scripts/chat.sh`, `scripts/ui.sh`, `scripts/tmux.conf`: the tmux launchers for the chat and the windowed interface. `scripts/child-window.sh`: what a child run's window runs (started by `run_instruction`, not by hand). `scripts/deploy.sh`: run on the Pi to update it. `scripts/wifi-reconnect.sh`: the `robot-wifi` service, which puts the Pi back on the Wi-Fi. `scripts/autostart.sh`: the switch for starting the interface and its run when the Pi starts, and what the `robot-autostart` service runs. `scripts/pi_photo.py`: run on a PC, fetches a photo from the Pi and opens it. `scripts/pi_sound.py`: the same for a sound recording, which it plays.
- `tests/`: the test suite. `CLAUDE.md`: the rules and the layout for Claude Code sessions; `docs/claude/`: their detailed notes, one file per topic.
- `requirements.txt`: the two packages the program needs beyond Python itself, `anthropic` and `python-dotenv`, each pinned to one version. `.gitattributes`: Unix line endings for the scripts.

## Setup on the Pi

The robot as it stands:

| Part | What |
|---|---|
| Board | Raspberry Pi 3 Model A+: 512 MB of memory (about 415 MB usable), four cores, one USB port. |
| System | 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13, tmux 3.5. No desktop. |
| Card | 32 GB SD card. |
| Camera and microphone | A Logitech Brio 100 webcam on the USB port. |
| Speakers | USB-powered stereo speakers on the headphone socket. |
| Screen | Optional: a text console of 240 columns by 67 rows. No keyboard is needed at the Pi. |
| Network | Wi-Fi. The Pi is `robot.local`, and its address comes from the router. |

Memory is what limits it: every run is a program of 80 to 95 MB.

- Checkout at `~/robot`, venv at `~/robot/.venv` (created with `--system-site-packages`).
- `~/robot/.env` contains `ANTHROPIC_API_KEY=...` and is never committed. An
  `XAI_API_KEY=...` line there as well lets the robot hear and speak (see
  `microphone_listen` and `speak` under "Tools").
- Passwordless sudo for the Pi's user, if the agent should have root.
- `deploy.sh` installs the pinned Python packages and tmux, and sets up the
  `robot-wifi` and `robot-autostart` services (it needs sudo for that). The
  first deploy that brings a new step to `deploy.sh` does not run that step
  yet, because the script that is running is the old one: deploy twice.
- The Pi's user is in the `video` group (for the webcam). Nothing else is
  installed for photos or sound: `v4l2-ctl`, `arecord` and `aplay` come with
  the system.
- The scripts typed by hand (`chat.sh`, `ui.sh`, `autostart.sh`, `deploy.sh`)
  can be started by name from any folder, as in `chat.sh -l "Name"`, since
  2026-11-28: the last line of `~/.bashrc` on the Pi puts `~/robot/scripts`
  on the shell's search path. That line was added by hand, not by
  `deploy.sh`, so a freshly set up Pi needs it again:
  `export PATH="$HOME/robot/scripts:$PATH"`. It holds at the Pi's prompt
  (the screen or `ssh pi`), not for a command given to ssh: there the full
  form stays, `ssh -t pi "bash ~/robot/scripts/chat.sh"`.

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
