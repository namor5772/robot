# Sound

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- The robot can record sound to a file and cannot listen to a file.
  Nothing in the repo records to a file: the model does it with the shell
  tool, told how by its `record-sound` skill (see "State on 2026-11-18"),
  and there is no tool that takes a sound file in, as `view_image` takes a
  picture. So a run can say that it made a recording and where the file
  is, and nothing about what is on it. What it can do since 2026-11-23 is
  hear speech in the room as it is spoken (see "Hearing").
- The microphone is the webcam's (see "Conventions"). The Pi has it as sound
  card `B100`, with `arecord` installed and the user in the `audio` group,
  so recording needs nothing installed. It gives mono, 16 bit, at 16,000 to
  48,000 samples a second (`arecord -D hw:CARD=B100 --dump-hw-params`), and
  its switch and level are `amixer -c B100 sget Mic` (on, 75%, on
  2026-11-22).
- The skill's recordings are WAV files in `~/robot-sound` on the Pi,
  `sound_<date>_<time>.wav`, mono, 16 bit, 16 kHz: 32 KB a second. Its
  command first records one second that it throws away, because the
  microphone wakes with a thump after a few seconds of rest.
- That thump is the webcam waking from USB power saving (measured on
  2026-11-22, on the 3 A+). The kernel puts the idle webcam to sleep two
  seconds after its last use: in `/sys/bus/usb/devices/1-1/power`,
  `control` is `auto`, `autosuspend_delay_ms` is 2000, and `runtime_status`
  goes from `active` to `suspended`. A recording that starts while it is
  asleep begins with a spike, about a third of full scale in the first
  tenth of a second after five seconds of rest or more, and less after a
  shorter sleep; one that starts while it is still awake has none (the room
  was not quiet, so the smaller figures are rough). So the second that
  is thrown away works by waking the webcam. Keeping it awake (`control`
  set to `on`) should do the same: not tried, and a setting of the Pi.
- A photo and a recording in one go is ONE shell command, and the skill has
  had two of them since 2026-11-22, added at the owner's request with a
  script fed over stdin that calls `manage_skills`. The owner had asked for
  a photo and then a recording, and the recording began about 5 s after the
  camera's light came on.
  - Where that time went, by the transcript and the files' times: the photo
    took 1.7 s, the model's next call 2.4 s (it had to be told the photo was
    done before it asked for the recording), and the second that is thrown
    away 1.2 s.
  - Two shell calls in ONE turn are no cure: `run_shell_command` is not
    `parallel_safe`, so they run one after the other. Asked for both "at the
    same time", the model sent the recording and a photo with `sleep 3` in
    front, expecting them side by side: the photo was taken two seconds
    after the recording had ended.
  - "A photo, then record": the thrown-away second runs in the background
    while the photo is taken, and the recording starts when both are done.
    Measured: 0.03 to 0.08 s from the photo's file to the recording's start.
    "Both at the same time": the recording runs in the background and the
    photo is taken meanwhile, 1.4 s into it. No thump at the start of
    either.
  - Tried through `tools.run_shell_command` with `HOME` set to a scratch
    folder, so that the commands' `~` led there, and then with a paid check
    on Haiku ("Take a photo and then record for 3 seconds"): one tool call,
    two "saved" lines, $0.0023. The check's photo and recording were
    removed.
  - The skill's text grew from 2,763 to 5,399 characters, and it is in
    every run's system prompt: about 650 tokens more.
- When the owner asks to hear a recording the Pi made, on a PC, run
  `.venv/Scripts/python.exe scripts/pi_sound.py` there (since 2026-11-22).
  It copies the Pi's newest recording to `~/RobotSound` on the PC, says what
  it holds and plays it to its end through the PC's speakers. `NAME.wav`
  after it takes that recording instead, `--file F.wav` one that is already
  on the PC, `--no-play` only says what it holds.
  - It returns when the recording has been played to its end, so give the
    command more time than the recording is long. It plays with Python's
    `winsound`, which Windows alone has: elsewhere it copies, describes and
    says where the file is.
  - A session cannot hear what was played. What it can go by is the line
    about the level, which the script prints before playing: the loudest
    sample and the average, as parts of full scale. It says so when every
    sample is 0 (silent), when the loudest reaches full scale (probably
    distorted there), and when the file is shorter than its header says (a
    recording that was cut off). The four recordings of 2026-11-22 had
    averages of 1.2% to 3.8% and loudest samples of 4% to 100%. What a
    quiet room reads was not measured, so a low figure is not proof of
    silence: ask the owner what they heard.
  - Unlike the photos, a recording needs no repair: Windows plays the WAV
    file as it comes.
  - It will not put recordings inside the checkout or inside a folder that
    OneDrive copies (`pi_photo.safe_folder`), and it only reads from the Pi.
    Recordings are personal, as photos are.
  - `tests/test_pi_sound.py` (39 tests, on every machine) gives it stand-ins
    for `ssh`, `scp` and the speakers, and makes its own WAV files. That a
    recording is heard was tried by hand, on the desktop.
- The Pi can make sound as well, since the evening of 2026-11-22: the owner
  plugged USB-powered stereo speakers into the 3 A+'s headphone socket.
  Their power comes from elsewhere, the Pi's one USB port having the
  webcam. The robot plays a sound file with the shell tool, told how by
  its `play-sound` skill (since 2026-11-23, see the next point). The one
  thing in the repo that plays sound is the `speak` tool, which plays the
  speech it has just made (see "Speaking").
  - A WAV file is played with `aplay -q -D plughw:CARD=Headphones,DEV=0
    FILE.wav`. `plughw` converts what the file has into what the socket
    takes, so the robot's own recordings (16 kHz, mono) play as they are;
    files of 44.1 and 48 kHz, mono and stereo, played too. The Pi has no
    sound server: `aplay` goes straight to the card.
  - The socket's own volume is `amixer -c Headphones sget PCM`: 0 dB, which
    it shows as 96%, and not muted, on that day. `amixer -c Headphones sset
    PCM 6dB-` lowers it by 6 dB and `6dB+` raises it again; `mute` and
    `unmute` in place of the figure switch it (tried on 2026-11-23: three
    steps down made a tone 17.7 dB quieter at the microphone). The speakers
    have a knob of their own.
  - How strong the speakers are at the microphone, with the socket at 0 dB
    and the knob where the owner had it: a tone came back at 1.6 to 2.2
    times the strength it was sent with that first evening (two pitches),
    and at 0.8 to 1.4 times on 2026-11-23 (four pitches). So a recording
    played back is about as strong there as the sound it holds was, or
    stronger. Captures held samples at the microphone's limit on both days.
    That alone does not show that the speakers are too loud: in one capture
    of 2026-11-23 a burst showed a second before anything was played.
  - `aplay` ends with code 0 whether or not anything sounds: it cannot know
    if speakers are plugged in, powered or turned up. The first tries that
    evening all "worked" that way while the speakers had no power.
  - A session cannot hear the speakers, but the Pi can: its microphone is
    in the same room. The test that settled it played a stereo file made
    on the spot (beeps of 880 and 1320 Hz in turn for six seconds, then
    660 Hz on the left channel alone and 1760 Hz on the right alone) while
    `arecord` listened, and then measured each pitch, in tenths of a
    second, at the times it should sound and at the times it should not.
    Without power every pitch stayed where the room's noise was (3 dB at
    most between the two); with power they stood 48 to 69 dB above it, both
    channels and every beep from the first. Typing and talking cannot make
    such a pattern.
  - A simpler test before it proved nothing: one tone, a spoken sample and
    a recording, judged by loudness alone. The owner was typing, and the
    bursts of that could have been taken for the speakers. Comparing the
    rise and fall of what was heard with that of the file told them apart
    (0.73 and 1.00 for the two real files once the speakers had power).
  - The scripts were fed over stdin and are not in the repo. They used the
    microphone for up to 20 s: see "Running and testing" on checks that
    use the webcam.
- Playing is ONE shell command as well, in the `play-sound` skill (since
  2026-11-23, see "State on 2026-11-18"). `f=""` at its start names the
  file: a path, a name alone for a recording in `~/robot-sound`, or nothing
  for the newest recording there. It plays the file to its end and prints
  "played PATH in N seconds", or "nothing played" with the reason.
  - It refuses a file that does not begin as a WAV file does (`RIFF`, four
    bytes of length, `WAVE`). `aplay` takes a file it does not know for raw
    samples, which would be noise from the speakers (its known behaviour,
    not tried here). A WAV file that `aplay` cannot play and a sound card
    that is not there come back as "nothing played" with `aplay`'s message.
  - Because it returns only at the file's end, the shell tool's limit of
    60 seconds matters: the skill has the model set `timeout_seconds` to
    600, and it did in both paid checks.
  - A play that is killed (that limit, STOP, Ctrl-C) stops at once. The
    kernel then logs `bcm2835-audio: failed to close VCHI service
    connection (status=-11)`, every time, and nothing is wrong: the audio
    service is gone from `/sys/kernel/debug/vchiq/state` as it is after a
    play that ended by itself, and what was played next was heard. `aplay`
    ended with SIGTERM leaves no such line.
  - Two plays at once are mixed. The socket has eight sub-devices (`aplay
    -l`): two files started 0.3 s apart were both heard, and neither
    waited for the other.
  - Tried through `tools.run_shell_command` with `HOME` set to a scratch
    folder, as the recording commands were, while the microphone listened.
    The files were soft beeps, each file with a pitch of its own, so that
    what was heard says WHICH file was played: the newest, the one named,
    one with spaces in its path. Each stood 52 to 63 dB above the room, the
    refused files left silence, and a file cut off by the tool's limit was
    heard up to there.
  - Then two paid checks on Haiku ($0.0026 and $0.0024), the real program
    on the real data folder (`ROBOT_DATA_DIR`) with `HOME` a scratch
    folder. A plain chat, "Play the newest recording": `get_skill`, then
    the skill's command to the letter, and the beeps of the newest file
    were heard. And an instruction with the skill list of `WebcamTest`,
    "Record sound for 5 seconds, then play that recording back": beeps
    were played while it recorded, and they were heard a second time when
    it played its recording. Both times the robot said that it could not
    hear what it had played.
  - The first try that morning heard nothing at all, while every command
    said "played": the speakers had no power, as on the evening they came.
    A test that hears nothing asks first whether they are on.
  - Strength in one pitch is a weaker proof than the pattern of the
    evening before. With people in the room its own noise reached 29 dB
    above the quiet level in a narrow filter, and a burst once 39 dB,
    where the test tones stood at 52 to 63. The times at which a pitch
    should and should not sound tell more.
