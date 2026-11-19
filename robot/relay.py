"""Relay folder: lets another process answer the agent's questions.

A run started with --relay-dir asks its questions through three small files
in that folder instead of (or as well as) the terminal:

  request.json   {"seq": n, "text": "...", "written": ts}
      written by the run when it asks something
  reply.json     {"seq": n, "text": "..."}
      written by whoever answers: a parent run with prepared answers, or a
      listener passing the question on to a person elsewhere
  answered.json  {"seq": n}
      written by the run when the question was answered at its own terminal,
      so a listener can withdraw it

`seq` counts the run's questions from 1, so a late reply to an earlier
question is never taken for the current one. Every write goes through a temp
file and os.replace, so a reader never sees a half-written file.

The file format is the same as MyAgent's relay, so its tools can talk to it.
"""

import json
import os
import tempfile
import time
from pathlib import Path

REQUEST = "request.json"
REPLY = "reply.json"
ANSWERED = "answered.json"


def _while_not_in_use(action):
    """Do `action`, trying again for a moment while Windows says the file is in use.

    On Windows a file that another process has open for reading can be neither
    replaced nor removed, and the two sides of a relay folder read each
    other's files every fraction of a second. Linux has no such rule, so on
    the Pi the first try is the only one.
    """
    for _ in range(200):
        try:
            return action()
        except PermissionError:
            time.sleep(0.01)
    return action()


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    try:
        _while_not_in_use(lambda: os.replace(tmp, path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path):
    """The file's JSON object, or None when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unlink(path):
    try:
        _while_not_in_use(Path(path).unlink)
    except FileNotFoundError:
        pass


def write_request(relay_dir, seq, text):
    """The run: a question is waiting."""
    _write(Path(relay_dir) / REQUEST, {"seq": int(seq), "text": str(text),
                                       "written": time.time()})


def read_request(relay_dir):
    """The answerer: the open question as {"seq", "text", "written"}, or None."""
    data = _read(Path(relay_dir) / REQUEST)
    if data is None or "seq" not in data:
        return None
    return data


def write_reply(relay_dir, seq, text):
    """The answerer: the reply to question `seq`."""
    _write(Path(relay_dir) / REPLY, {"seq": int(seq), "text": str(text)})


def read_reply(relay_dir, seq):
    """The run: the reply to question `seq` once it has arrived, else None."""
    data = _read(Path(relay_dir) / REPLY)
    if data is None or data.get("seq") != int(seq):
        return None
    return str(data.get("text", ""))


def clear(relay_dir):
    """The run: the question is over, however it was answered."""
    _unlink(Path(relay_dir) / REQUEST)
    _unlink(Path(relay_dir) / REPLY)


def mark_answered(relay_dir, seq):
    """The run: question `seq` was answered at its own terminal."""
    _write(Path(relay_dir) / ANSWERED, {"seq": int(seq)})


def take_answered(relay_dir):
    """The answerer: the seq of a question answered at the run's terminal,
    consuming the marker, else None."""
    path = Path(relay_dir) / ANSWERED
    data = _read(path)
    if data is None:
        return None
    _unlink(path)
    return data.get("seq")
