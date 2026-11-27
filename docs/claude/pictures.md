# Pictures

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- `view_image` (in `tools.py`, since 2026-11-20, at the owner's request) is
  the one way a picture reaches the model. Its result is not text but a list
  of two blocks: a line naming the file, and an `image` block with the
  file's bytes in base64. `Agent._run_tool` passes a list on as the
  `tool_result`'s content. The API takes that (checked on Haiku with SDK
  2.8.0; no beta header).
- The kind of picture is read from the file's first bytes, not from its
  name: JPEG, PNG, GIF, WebP. A file over `MAX_IMAGE_BYTES` (3.5 MB) is
  refused with the reason, because the API's limit is 5 MB after encoding.
  A path may be absolute, start with `~`, or be relative to the home
  folder, where the shell tool also starts. Nothing is resized: there is no
  image library on the Pi, and none is wanted (see "Conventions").
- A picture is billed by its pixels. A 1920 x 1080 photo was about 2,800
  input tokens on Haiku and on Sonnet 5.5. It stays in the history, so every
  later call of the run carries it (read from the cache).
- Three places must not treat it as text, and do not: the saved chat's
  `.json` keeps a note in its place (`chats._clean_result_content`, which
  was there already; the line naming the file is kept), `--debug` and
  `--dry-run` print only how long its data is (`api._without_image_data`),
  and the history's size estimate counts it as a picture inside a tool
  result too (`history.estimate_content_tokens`). The transcript `.txt`
  never held tool results.
- The tool's description is model-facing text: it says that this is how the
  robot sees, and never to describe an image it has not looked at.
- MyAgent attaches images to an instruction or a message. That is still not
  here: a picture gets in only as a file on the Pi that the model asks to
  see.
- When the owner asks to see a photo the Pi took, on a PC, run
  `.venv/Scripts/python.exe scripts/pi_photo.py` there (since 2026-11-22).
  It copies the Pi's newest photo to `~/RobotPhotos` on the PC and opens it
  in the PC's own viewer. `NAME.jpg` after it takes that photo instead,
  `--file F.jpg` one that is already on the PC, `--no-open` leaves the
  viewer shut.
  - Why a script and not a copy: a frame of the webcam's MJPG stream is a
    JPEG file without its Huffman tables (it has no `FF C4` segment). The
    stream's convention is that the standard tables are meant. The API and
    lenient decoders fill them in. Windows' decoder does not: the viewer
    opened and showed no picture, and GDI+ said "A generic error occurred".
  - So the script writes `NAME_viewable.jpg` beside the copy, with the
    standard tables (420 bytes) put in front of the picture data, and opens
    that. The picture data is not touched and the photo as it came is kept.
  - It will not put photos inside the checkout or inside a folder that
    OneDrive copies. It only reads from the Pi (`ssh` for the newest name,
    `scp` for the file).
  - Nothing was changed on the Pi, at the owner's word ("no stuff needed on
    the Pi"): the `take-photo` skill still saves frames as they come, so
    every photo needs this on Windows.
  - `tests/test_pi_photo.py` (21 tests, on every machine) gives it a
    stand-in for `ssh` and `scp`. No test decodes a picture: that was looked
    at by hand, on the desktop, with two photos.
