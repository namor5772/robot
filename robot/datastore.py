"""Where the robot keeps its data, and safe reading and writing of its JSON stores."""

import json
import os
import re
import socket
import tempfile
from pathlib import Path

# Set this variable to keep the data somewhere other than the default folder.
DATA_DIR_ENV = "ROBOT_DATA_DIR"
_DEFAULT_DIR_NAME = "robot-data"


class StoreUnreadableError(Exception):
    """A store file is there but cannot be read, so nothing may be saved over it."""


def _host_label() -> str:
    """This machine's name, reduced to characters that are safe in a file name."""
    try:
        name = socket.gethostname()
    except OSError:
        name = ""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "robot"


class DataDir:
    """Where the robot keeps its data. Outside the git checkout on purpose.

    The checkout is public and is updated with a fast-forward pull, so nothing
    the robot writes may live inside it. Creating a DataDir only works out the
    paths; ensure() is what creates the folders.
    """

    def __init__(self, root=None):
        if not root:
            root = os.environ.get(DATA_DIR_ENV, "").strip() or Path.home() / _DEFAULT_DIR_NAME
        # Made absolute so every path still means the same place if the working
        # directory changes later. This reads nothing and creates nothing.
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self.instructions_file = self.root / "agent_instructions.json"
        self.skills_dir = self.root / "skills"
        self.chats_dir = self.root / "saved_chats"
        # The machine's name is part of the file name so that logs collected
        # from several machines can sit in one folder.
        self.costlog_file = self.root / f"APICostLog_{_host_label()}.txt"
        self.runs_dir = self.root / "runs"
        # Temporary files go here rather than in /tmp, which on the Pi is held
        # in memory.
        self.tmp_dir = self.root / "tmp"

    def ensure(self) -> None:
        """Create the data folder and its sub-folders where they are missing."""
        for folder in (self.root, self.skills_dir, self.chats_dir, self.runs_dir, self.tmp_dir):
            folder.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path, text: str) -> None:
    """Write `text` to `path` so that the file is always whole.

    The text goes into a temporary file beside the target, is forced onto the
    disk, and is then moved over the target in a single step. Whatever happens
    part-way (a crash, a kill, a power cut), `path` holds either its old
    content or the new content, never a mixture and never half a file.
    """
    path = os.fspath(path)
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    # Beside the target because a move is only atomic within one file system.
    # The name is unique so two processes saving at once never share a file.
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            # Without this the move can reach the disk before the content does,
            # and a power cut would then leave an empty file under the real name.
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:  # Ctrl-C included: do not leave the temporary file behind
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def save_store(path, data: dict) -> None:
    """Save a JSON store atomically (see atomic_write_text)."""
    # Turned into text in full first, so data that JSON cannot express fails
    # here, before anything on disk has been touched.
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def load_store(path) -> dict:
    """Read a JSON store. A missing, unreadable or malformed file reads as empty.

    Reading never fails and never writes. Before saving anything built on the
    result, check store_unreadable(): an empty result may only mean that the
    file has a typo in it, and saving would then replace everything it holds.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):  # ValueError: malformed JSON, or bytes that do not decode
        return {}
    return data if isinstance(data, dict) else {}


def store_unreadable(path) -> bool:
    """True when the file at `path` holds something that is not a JSON object.

    load_store() reads such a file as empty, and saving that back would wipe
    whatever the file holds. A missing file, a blank file and a valid empty
    object have nothing in them to lose, so none of those counts as unreadable.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if not raw.strip():
            return False
        return not isinstance(json.loads(raw.decode("utf-8")), dict)
    except (OSError, ValueError):  # there, but locked, damaged or not UTF-8
        return True
