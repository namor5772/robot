# Speaking

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- `speak` (in `tools.py`, its work in `speaking.py`, since 2026-11-23, at
  the owner's request) is how the robot talks: a text goes to xAI's
  text-to-speech service, `POST https://api.x.ai/v1/tts`, a WAV file comes
  back, is saved and is played. The owner asked for text made into a WAV
  file that can be played through the speakers; the service and the shape
  (a tool, as for hearing, with the key that was already on the Pi) were
  chosen without asking, and the owner was told. MyAgent has no such tool:
  it speaks through skills.
- The request is JSON: `text`, `voice_id`, `language` (required by the
  service; `auto` is sent) and `output_format` (`codec` `wav`,
  `sample_rate` 24000). The answer is the file's bytes. Read in xAI's REST
  reference that day; the limits there are 60,000 characters a request and
  26 voices (`GET /v1/tts/voices`), `eve` being the default.
- The voice and the speed are settings the robot changes itself, since
  2026-11-24, at the owner's request (they had asked whether the
  `robot-identity` skill or the tool could do it; a skill is only text, so
  it is the tool):
  - They are kept in `~/robot-data/voice_settings.json` (`voice`, `speed`,
    either may be missing). `speaking.voice()` and `speaking.speed()` read
    the file at every call, so a change holds from the next sentence on, in
    every run and interface on the Pi, with no restart. With no voice in
    the file it is `ROBOT_VOICE` from the `.env`, else `eve`; the speed is
    1.0. What makes no sense in the file is passed over.
  - `voice_settings` is the tool. `list` gives the voice and speed in use
    and the service's voices (`GET /v1/tts/voices`: 28 on that day, each
    with `voice_id`, `name`, `gender` and `language`, the last being
    "multilingual" for all). `set` saves a voice, a speed or both. A voice
    is checked against that list first and refused with the names there
    are; when the list cannot be had, nothing is saved.
  - `speak` takes `voice` and `speed` for one call, which saves nothing:
    that is how a voice is tried out.
  - The speed is the service's `speed`, 0.7 to 1.5. It is sent only when it
    is not 1.0. Tried: one sentence was 3.7 s at 0.7, 2.9 s at 1.0 and
    1.95 s at 1.5; 2.0 is an HTTP 400.
  - Tried on the Pi in a scratch copy with a data folder of its own: the
    list, a refused name, `rex` at 1.3 saved, then a sentence in the saved
    voice and one in `eve` at 0.8 for that call only, while the microphone
    listened: both sentences came back word for word, and `rex` at 1.3 was
    still what was saved.
  - Then a paid chat on Haiku ($0.0028), the real program on the real data
    folder: "How many voices do you have? Switch to the voice called orion,
    a little faster than usual, and then say hello out loud" gave `list`,
    `set` with `orion` and 1.15, and `speak`; the answer was "28 voices".
    The settings file that chat left was removed again, there having been
    none before: a paid check of `set` changes the owner's own voice, so
    look first whether the file is there, and put back what was.
  - The `robot-identity` skill, which the owner has rewritten since
    2026-11-18, got one paragraph more the same day at the owner's request,
    through `manage_skills` with a script fed over stdin: that the robot
    can change its voice and speed, and to use `voice_settings` when asked.
    The rest of the skill is the owner's own text and was left as it was.
  - Listing is a second tool and not an action of `speak`, as the owner agreed to when it was put to
    them, so that `speak`'s description stays about speaking. It adds
    about 300 tokens to every request (an estimate).
- An unknown voice is a 404, which the tool reports as such. The text may
  hold the service's speech tags (`[pause]`, `<whisper>...</whisper>` and
  so on); the tool's description does not mention them, and none was tried.
- The WAV file as it comes states a length it does not have: its header
  said 1,073,741,823 frames for a file of 3.8 seconds (it is made while
  the sound is still being produced). `speaking.clean_wav` reads to the
  last sample and writes the file again with a right header, which is also
  how the tool knows the speech's length.
- The file is kept: `~/robot-sound/speech_<date>_<time>.wav`, mono, 16 bit,
  24 kHz, 48 KB a second, beside the recordings, so that `play-sound` can
  play it again. Nothing removes them.
- It is played with `aplay -q -D plughw:CARD=Headphones,DEV=0`: the first
  playback device `aplay -l` lists, named by its card
  (`speaking.find_speakers`; `ROBOT_SPEAKER_DEVICE` overrules it). With
  `play` false the file is made and not played. A failure to play still
  says where the file is.
- One call takes 2,000 characters at most (`MAX_CHARS`), about two minutes
  of speech: the tool returns only when the file has been played to its
  end, and it is not `parallel_safe`, so Ctrl-C and STOP cut the sound off
  (the player is killed on the way out, as hearing's recorder is).
- The cost is xAI's, $15.00 for a million characters (its pricing page on
  2026-11-23), stated in the result as an estimate and, like hearing's,
  not in the run's cost or the cost log. A sentence of 94 characters is
  $0.0014; a full call of 2,000 is three cents.
- The result says "The sound was sent to the speakers; whether it was
  heard is not known": `aplay` cannot tell whether the speakers have power
  (see "Sound").
- The description tells the model not to listen in the same turn as it
  speaks. Both tools run one after the other in any case, in the order the
  model gave.
- How it was tried: the tool spoke a sentence in a scratch copy while
  `hearing.listen` ran on a second thread, and the transcript was the
  sentence, word for word, number included. So the robot's own hearing is
  the check for its voice. `HOME` was a scratch folder, so the check's
  files did not land in the owner's `~/robot-sound`.
- That check went wrong in one way: a run of the owner's was in progress
  (`~/robot-data/runs` held a file, which the check listed and did not
  act on), and the sentence was played into the room during it. A check
  that uses the speakers or the microphone must STOP when that folder is
  not empty, not just show it.
- Then a paid chat on Haiku ($0.0022), the real program with `HOME` a
  scratch folder: "Say out loud, in one short sentence, what day of the
  week it is" gave `get_current_datetime`, then `speak` with "Today is
  Monday.", a file of 76 KB, and the reply that it cannot tell whether
  anyone heard it. Listening and answering aloud in one run was not tried.
- An interface that was open before the deploy keeps the old code: its
  runs get the tool once it has been quit and started again.
- `tests/test_speaking.py` (59 tests, on every machine) gives it stand-ins
  for the service and for `aplay`, among them a file with the header the
  service really sends.
