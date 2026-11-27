"""A run's chat files: its name, its messages as JSON, and its transcript as text."""

import os
import re
import warnings
from datetime import datetime
from pathlib import Path

from robot.datastore import save_store

_PROVIDER = "Anthropic"
# Characters no file name may hold on Windows or Linux, plus control
# characters, which a file system may accept but no listing shows properly.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_STAMP_FORMAT = "%Y-%m-%d_%H%M%S"
_THINKING_KINDS = ("thinking", "redacted_thinking")
_IMAGE_NOTE = "[Image was attached]"
_NESTED_IMAGE_NOTE = "[Screenshot]"
_SCALARS = (str, int, float, bool, type(None))
_MISSING = object()


# ---- names ----


def sanitize_filename(name: str) -> str:
    """Turn a chat name into a file stem (no extension) with no unsafe characters.

    The result never holds a path separator, so it always names a file in
    the folder it is joined to.
    """
    # Dots and spaces at either end go too: Windows drops trailing ones, and a
    # leading dot hides the file on Linux.
    safe = _UNSAFE_CHARS.sub("_", name).strip(". ")
    return safe or "_"


def new_chat_name(instruction_name: str = "", now=None) -> str:
    """Name a run's chat: "<Instruction>_<YYYY-MM-DD_HHMMSS>", or "Agent_<...>".

    `now` is a datetime; the current local time is used when it is left out.
    The name is what the run's files are called, and an instruction name can
    hold any character, so the result has been through sanitize_filename().
    """
    base = " ".join(str(instruction_name or "").split())
    stamp = (datetime.now() if now is None else now).strftime(_STAMP_FORMAT)
    return sanitize_filename(f"{base or 'Agent'}_{stamp}")


def unique_chat_stem(chats_dir, stem: str, pid: int) -> str:
    """Return `stem`, or `stem` with the process id added if a chat already uses it.

    The time in a chat name only goes down to the second, so two runs of one
    instruction can be given the same name. The later one must not write over
    the earlier one's files.
    """
    folder = Path(chats_dir)
    # The names are joined by hand because with_suffix() would cut a stem at
    # its last dot.
    if any((folder / f"{stem}{ext}").exists() for ext in (".json", ".txt")):
        return f"{stem}_{pid}"
    return stem


def claim_chat_stem(chats_dir, stem: str, pid: int) -> str:
    """Take a name for a run's chat files that no other run has, and hold it.

    Looking whether a name is free and then using it is two steps, and two
    runs started in the same second both found it free before either had made
    a file: the later one's files replaced the earlier one's. So the name is
    taken by making the transcript's file in one step that fails if the file
    is there already. Only one run can win that, and the others go on to the
    name with their process id (and a number after it, for one program that
    starts the same instruction twice within a second).

    The file is left empty for Transcript to append to. Where no file can be
    made at all, the name is chosen the old way: opening the transcript will
    say what is wrong.
    """
    folder = Path(chats_dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:  # FileExistsError among them: something else has the folder's name
        return unique_chat_stem(folder, stem, pid)
    candidates = [stem, f"{stem}_{pid}"] + [f"{stem}_{pid}_{count}" for count in range(2, 100)]
    for candidate in candidates:
        if (folder / f"{candidate}.json").exists():
            continue
        try:
            handle = os.open(folder / f"{candidate}.txt",
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            continue
        except OSError:
            return unique_chat_stem(folder, stem, pid)
        os.close(handle)
        return candidate
    return f"{stem}_{pid}"


# ---- messages ----


def _get(block, name, default=None):
    """Read one field of a block, which may be a dict or an SDK object."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _fields_of(obj):
    """The fields of an SDK-style object as a dict; empty or None if it shows none."""
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            # The SDK warns when a block has a shape newer than its own type
            # definitions. With a pinned SDK that is to be expected, and it is
            # of no use to someone reading the console, so it is not shown.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                data = dump()
        except Exception:  # use the attributes instead, rather than lose the block
            data = None
        if isinstance(data, dict) and data:
            return data
    try:
        attributes = vars(obj)
    except TypeError:  # a string, a number: nothing that has fields
        return None
    return {
        key: value
        for key, value in attributes.items()
        if isinstance(key, str) and not key.startswith("_")
    }


def _plain(value, _open=()):
    """Copy `value` into what JSON can hold: dicts, lists, text and numbers.

    Objects become dicts of their fields and anything else becomes text, so
    json never meets a type it cannot write. The copy shares nothing with the
    original.
    """
    if isinstance(value, _SCALARS):
        return value
    if id(value) in _open:  # it contains itself: stop rather than go round for ever
        return str(value)
    _open = _open + (id(value),)
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else str(key): _plain(item, _open)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item, _open) for item in value]
    fields = _fields_of(value)
    return _plain(fields, _open) if fields else str(value)


def _whole_block(block, kind) -> dict:
    """Keep every field of a block: server tool calls, their results, unknown kinds."""
    saved = _plain(block)
    if not isinstance(saved, dict):
        if kind is None:
            # Not a block at all (a bare string, say): keep what it says as text.
            return {"type": "text", "text": str(block)}
        saved = {}
    if kind is not None and "type" not in saved:
        # A type declared on the class is not among the object's own fields.
        saved = {"type": _plain(kind), **saved}
    return saved


def _clean_result_content(content):
    """A tool result's content: a list is cleaned part by part, text is kept."""
    if not isinstance(content, (list, tuple)):
        return _plain(content)
    parts = []
    for part in content:
        if isinstance(part, _SCALARS):
            parts.append(part)
        elif _get(part, "type") == "image":
            parts.append({"type": "text", "text": _NESTED_IMAGE_NOTE})
        else:
            parts.append(_clean_block(part))
    return parts


def _clean_block(block) -> dict:
    """One content block as a plain dict holding only what a saved chat needs."""
    kind = _get(block, "type")
    if kind == "text":
        return {"type": "text", "text": _plain(_get(block, "text", ""))}
    if kind == "thinking":
        return {
            "type": "thinking",
            "thinking": _plain(_get(block, "thinking", "")),
            "signature": _plain(_get(block, "signature", "")),
        }
    if kind == "redacted_thinking":
        return {"type": "redacted_thinking", "data": _plain(_get(block, "data", ""))}
    if kind == "tool_use":
        return {
            "type": "tool_use",
            "id": _plain(_get(block, "id")),
            "name": _plain(_get(block, "name")),
            "input": _plain(_get(block, "input")),
        }
    if kind == "tool_result":
        saved = {"type": "tool_result", "tool_use_id": _plain(_get(block, "tool_use_id"))}
        content = _get(block, "content", _MISSING)
        if content is not _MISSING:
            saved["content"] = _clean_result_content(content)
        # Whether a tool call failed is part of the record.
        is_error = _get(block, "is_error")
        if is_error is not None:
            saved["is_error"] = _plain(is_error)
        return saved
    if kind == "image":
        # The picture is megabytes of encoded data; a note is enough here.
        return {"type": "text", "text": _IMAGE_NOTE}
    return _whole_block(block, kind)


def serialize_messages(messages: list, save_thinking: bool = False) -> list:
    """Copy a conversation into plain data for a chat's .json.

    Blocks may be dicts or SDK objects; every one comes out as a dict. The
    model's thinking is left out unless `save_thinking` is set. The messages
    passed in are not changed.
    """
    saved = []
    for message in messages:
        role = _get(message, "role")
        content = _get(message, "content")
        if isinstance(content, str):
            saved.append({"role": role, "content": content})
        elif isinstance(content, (list, tuple)):
            blocks = [
                _clean_block(block)
                for block in content
                if save_thinking or _get(block, "type") not in _THINKING_KINDS
            ]
            if blocks:  # a turn that was nothing but dropped thinking leaves no entry
                saved.append({"role": role, "content": blocks})
        else:
            saved.append({"role": role, "content": str(content)})
    return saved


def chat_payload(
    *,
    name: str,
    messages: list,
    tools: list,
    system_prompt: str,
    instruction: str,
    model: str,
    thinking_mode: str,
    save_thinking: bool = False,
) -> dict:
    """Build what a chat's .json holds, ready for save_chat_json()."""
    # The key names and their order are those of MyAgent's saved chats, so
    # anything that reads one can read the other. Its temperature and its
    # separate thinking switches are left out: the robot has neither.
    return {
        "messages": serialize_messages(messages, save_thinking),
        "tools": _plain(tools),
        "system_prompt": system_prompt,
        "agent_instruction_name": instruction,
        "provider": _PROVIDER,
        "model": model,
        "thinking_mode": thinking_mode,
        "name": name,
    }


def save_chat_json(path, payload: dict) -> None:
    """Write a chat's .json so that a kill part-way never leaves half a file.

    Unlike the transcript this can raise, when the payload or the disk will
    not take the write. An earlier copy of the file is then left as it was.
    """
    save_store(path, payload)


# ---- transcript ----


class Transcript:
    """The run's .txt, appended live so a killed run still leaves its transcript.

    Opening can fail (OSError) and the caller should expect that. After that
    no trouble with the file is ever raised: a transcript must not stop a run.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # backslashreplace: a character that cannot be encoded is written as an
        # escape instead of costing the whole piece of text.
        self._file = open(
            self.path, "a", encoding="utf-8", errors="backslashreplace", newline="\n"
        )

    def write(self, text: str) -> None:
        """Add `text` to the end of the transcript."""
        if not text:
            return
        try:
            self._file.write(text if isinstance(text, str) else str(text))
            # Hand it to the system at once, as the process may be killed at any
            # moment. It is not forced onto the disk: doing that for every piece
            # of a reply would be slow and hard on an SD card.
            self._file.flush()
        except (OSError, ValueError):  # disk full, file gone, or already closed
            pass

    def close(self) -> None:
        """Close the file. Calling it again, or writing afterwards, does nothing."""
        try:
            self._file.close()
        except (OSError, ValueError):
            pass
