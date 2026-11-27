# Hearing

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- `microphone_listen` (in `tools.py`, its work in `hearing.py`, since
  2026-11-23, at the owner's request) is how the robot hears, and what it
  hears is speech only. Claude takes no sound (MyAgent's audit of
  2026-09-20, and no audio in the API's documentation on 2026-11-23), so
  the tool records some seconds and sends them to xAI's Grok Speech to
  Text, `POST https://api.x.ai/v1/stt`, model `grok-voice-transcribe-2.0`.
  The words are the tool's result, as text. It is MyAgent's tool of the
  same name; MyAgent's Mike button (dictating a reply) is not here.
- The owner chose xAI and this entry point out of four that were put to
  them (a skill alone, this tool, a key in the interface that dictates a
  reply, listening hands-free). Hands-free was built the next day (see
  "Hands-free"). The key that dictates a reply is not built: do not build
  it unasked.
- The key is `XAI_API_KEY` in the Pi's `~/robot/.env`. It was copied there
  from the laptop's environment, where MyAgent uses it, with a pipe that
  never showed it. A call made with it is billed to the owner's xAI
  account. Without the key, or without `arecord`, the tool
  is not offered (`hearing.available`), so a PC's runs never have it.
- Recording: `arecord -q -D plughw:CARD=B100,DEV=0 -t raw -f S16_LE -c 1 -r
  16000 -d N+1`, to a pipe. The device is the first capture device that
  `arecord -l` lists, named by its card (`hearing.find_microphone`;
  `ROBOT_MIC_DEVICE` overrules it). One second more than asked for is
  recorded and dropped, for the thump described under "Sound". 5 seconds
  unless the model says otherwise, 120 at most, rounded up to whole
  seconds. Nothing is written to disk.
- The upload is a multipart form made by hand with `urllib` (no new
  package): the `model` field, then the file, which must come last. The
  answer is JSON with a `text` field. No `language` is sent, so the service
  finds the language itself and leaves numbers as words.
- A recording whose loudest sample is under 50 of 32767 is not sent: that
  is a dead microphone, not a quiet room. A room without speech IS sent,
  and the service answers with no words ("no speech was recognised"):
  three listens of 4 seconds with nothing played said so.
- The cost is xAI's, $0.10 for an hour of sound, and is stated in the
  tool's result as an estimate ("about $0.0003" for 9 seconds). It is not
  in the run's cost and not in the cost log, which is for Anthropic's
  calls. That is MyAgent's way.
- It is not `parallel_safe`: it runs on the main thread, inside the region
  where Ctrl-C and STOP raise, and `hearing.record` kills the recorder on
  the way out. Tried on the Pi: one `arecord` while listening, none half a
  second after a SIGINT.
- The person cannot tell when the robot listens. The tool's description
  tells the model to say so in its reply before the call, and in both paid
  checks it did ("I'm listening now").
- A wrong key is answered by xAI with HTTP 400 and "Incorrect API key
  provided", not 401. `hearing.transcribe` goes by that wording too.
- How it was tried, since a session can neither speak nor hear. A sentence
  was made with Windows' own speech (`System.Speech`, a WAV file), copied
  to the Pi's `/tmp`, and played through the Pi's speakers while the tool
  listened: a loop waited for `pgrep -x arecord` and started `aplay` 1.3
  seconds later, past the second that is dropped. First the tool alone in
  a scratch copy, then two paid chats on Haiku ($0.0020 and $0.0023): asked
  to "listen to me for 10 seconds", the robot repeated the sentence; told
  "I am about to say something out loud. Hear me out and do what I ask", it
  listened, read the clock and answered the spoken question.
- Not understood: in three of the seven real listens that day the transcript
  held one thing more that was not played. "Fifty." from a room with
  nothing played, and "Eight." and "8:50" after the sentence. The owner
  was in the room, so it may have been real sound; it may also be the
  service making words out of the noise at the end. Not looked into.
- The `record-sound` skill said "You can record but not listen" in every
  run's system prompt. Three sentences of it were changed the same day,
  through `manage_skills` with a script fed over stdin: it now sends the
  model to `microphone_listen` for speech, and still says that no tool
  takes a sound FILE in.
- `tests/test_hearing.py` (40 tests, on every machine) gives it stand-ins
  for `arecord` and for the service. The Instruction Editor's Tools dialog
  lists the tool, so an instruction can block it.
