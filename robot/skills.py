"""The skills library: its folders on disk, the modes in force for a run, the
part of the system prompt that comes from skills, and the manage_skills tool.

A skill is a folder that holds a SKILL.md file and, optionally, other files
the skill's text refers to. SKILL.md opens with a few "key: value" lines
between two "---" lines, then one blank line, then the text of the skill.
MyAgent reads and writes the same format, so a skill folder can be copied
from one program to the other. What the serialiser writes and what the parser
accepts must therefore stay exactly as they are here.
"""

import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path

MODES = ("disabled", "enabled", "on_demand")
SKILL_BASENAME = "SKILL.md"

_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NAME_LIMIT = 64            # characters in the name of a new skill
_DESCRIPTION_GUIDE = 1024   # characters; a longer description draws a warning
_READ_LIMIT = 200_000       # the most that read_file returns
_BINARY_PROBE = 8192        # bytes searched for a NUL to spot a binary file

# A header line: a key that starts with a letter, a colon, then the value.
_HEADER_LINE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]?(.*)$")

# What MyAgent puts between a skill's name and its description in the system
# prompt. Made from its code point so that this file stays plain ASCII.
_LONG_DASH = chr(0x2014)

# Windows will not create a file or folder with one of these names, whatever
# extension follows it.
_WINDOWS_DEVICES = ({"CON", "PRN", "AUX", "NUL"}
                    | {f"COM{n}" for n in range(1, 10)}
                    | {f"LPT{n}" for n in range(1, 10)})


# ---- the SKILL.md format ----


def skill_dirname(name: str) -> str:
    """The folder name for a skill called `name`.

    The name inside SKILL.md is the skill's real name. The folder only has to
    be a name every system accepts, and always the same one for the same
    skill. Characters that Windows forbids are replaced on Linux too, so a
    tree made on the robot can be copied to a Windows machine.
    """
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not safe:
        return "_skill"
    if safe.split(".")[0].upper() in _WINDOWS_DEVICES:
        safe = "_" + safe
    return safe


def serialize_skill_md(name: str, entry: dict) -> str:
    """The text of SKILL.md for one skill.

    Every header value goes on one line, because the parser reads the header
    line by line. The mode written is the one the entry holds: the store
    passes in an entry that carries the global mode. `section` and `order`
    are written only when the entry has them, so a skill without them keeps
    the file it had. The text ends with exactly one newline, which the parser
    takes off again.
    """
    lines = ["---", "name: " + " ".join(name.split())]
    description = " ".join((entry.get("description") or "").split())
    if description:
        lines.append("description: " + description)
    lines.append("mode: " + entry.get("mode", "disabled"))
    section = entry.get("section")
    section = " ".join(section.split()) if isinstance(section, str) else ""
    if section:
        lines.append("section: " + section)
    order = entry.get("order")
    if isinstance(order, int) and not isinstance(order, bool):  # True is an int too
        lines.append(f"order: {order}")
    lines.append("---")
    body = entry.get("content", "")
    if body and not body.endswith("\n"):
        body += "\n"
    return "\n".join(lines) + "\n\n" + body


def _split_header(text: str) -> tuple[dict, str]:
    """(header values, body) of SKILL.md text.

    Text that does not start with "---", or never closes the header with a
    second "---", has no header: all of it is the body. Inside the header, a
    line that is not "key: value" continues the value above it, so a long
    description may be wrapped by hand. The blank line after the header and
    the last newline belong to the format, not to the body, and are removed.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    values, key, closed = {}, None, False
    index = 1
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.strip() == "---":
            closed = True
            break
        found = _HEADER_LINE.match(line)
        if found:
            key = found.group(1).strip().lower()
            values[key] = found.group(2).rstrip("\r").strip()
        elif key is not None and line.strip():
            values[key] = (values[key] + " " + line.strip()).strip()
    if not closed:
        return {}, text
    if index < len(lines) and not lines[index].strip():
        index += 1
    body = "\n".join(lines[index:])
    if body.endswith("\n"):
        body = body[:-1]
    return values, body


def parse_skill_md(text: str, fallback_name: str = "") -> tuple[str, dict]:
    """(name, entry) from SKILL.md text.

    The entry always has `content` and a valid `mode`: a missing or unknown
    mode reads as "disabled". `description`, `section` and `order` are there
    only when the file gives them a usable value. Header keys this program
    does not know are ignored. A file that gives no name takes
    `fallback_name`, which the caller sets to the folder's name.
    """
    values, content = _split_header(text)
    name = " ".join((values.get("name") or "").split()) or fallback_name
    mode = (values.get("mode") or "").strip().lower()
    entry = {"content": content, "mode": mode if mode in MODES else "disabled"}
    description = (values.get("description") or "").strip()
    if description:
        entry["description"] = description
    section = " ".join((values.get("section") or "").split())
    if section:
        entry["section"] = section
    order = (values.get("order") or "").strip()
    if re.fullmatch(r"-?\d+", order):
        try:
            entry["order"] = int(order)
        except ValueError:
            pass  # Python refuses to convert a number thousands of digits long
    return name, entry


def is_valid_new_name(name: str) -> bool:
    """True when `name` may be given to a new skill.

    New names are kebab-case: lower-case letters and digits in groups joined
    by single hyphens, 64 characters at most. The rule is applied on create
    only, so a skill copied in under some other kind of name can still be
    read, updated and deleted.
    """
    return (isinstance(name, str) and len(name) <= _NAME_LIMIT
            and bool(_NAME_PATTERN.fullmatch(name)))


def kebabize(name: str) -> str:
    """The valid skill name nearest to `name`, or "" when nothing usable is left."""
    text = re.sub(r"[ _]+", "-", name.strip().lower())
    text = re.sub(r"[^a-z0-9-]+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:_NAME_LIMIT].rstrip("-")


def description_warning(description: str) -> str:
    """A warning for a description longer than the Agent Skills guideline, else "".

    The length is advice, not a rule: the description is saved either way.
    """
    if len(description) > _DESCRIPTION_GUIDE:
        return (f"Warning: description is {len(description)} chars; the Agent Skills "
                f"guideline is <={_DESCRIPTION_GUIDE}. Consider shortening it.")
    return ""


# ---- files ----


def _read_text(path) -> str:
    """The text of a SKILL.md, however it was saved.

    Both programs write UTF-8. A file saved by some other editor is read
    anyway, so that one odd file cannot hide a skill: UTF-8 with a byte-order
    mark, UTF-16 (known by its mark), and the Windows Western code page as the
    last resort. Every kind of line ending is read as a plain line feed.
    Bytes that fit none of these raise UnicodeDecodeError, a ValueError.
    """
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write(path, text: str, temp_prefix: str = "tmp") -> None:
    """Replace the file at `path` with `text` in a single step.

    The text goes into a temporary file in the same folder, which is then
    moved over the target, so the file is never seen half-written. Nothing in
    `text` is translated: its line endings land on disk as they are.
    """
    path = os.fspath(path)
    # Beside the target, because a move is only a single step within one file system.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=temp_prefix,
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            # The robot can lose power at any moment. Without this the move
            # could reach the disk before the content does.
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:  # Ctrl-C included: do not leave the temporary file behind
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _write_skill_md(folder: Path, text: str) -> None:
    """Put `text` in the folder's SKILL.md, unless the file already says just that."""
    md = folder / SKILL_BASENAME
    try:
        if md.is_file() and _read_text(md) == text:
            return
    except (OSError, ValueError):
        pass  # it cannot be read, so it is not what we want: replace it
    os.makedirs(folder, exist_ok=True)
    # The temporary file's name starts with "SKILL.md." so that one left
    # behind by a crash is never taken for one of the skill's bundled files.
    _atomic_write(md, text, SKILL_BASENAME + ".")


def _is_skill_md_family(filename: str) -> bool:
    """True for a top-level file that is the skill's own, not one it bundles.

    That is SKILL.md in any casing (some file systems ignore case), the
    temporary files its writer makes ("SKILL.md.*"), and "SKILL-<label>.md":
    MyAgent takes a file of that shape for a second copy of SKILL.md left by
    a file-sync conflict and merges it away, so the robot must not create one.
    """
    low, base = filename.lower(), SKILL_BASENAME.lower()
    return (low == base or low.startswith(base + ".")
            or (low.startswith("skill-") and low.endswith(".md")))


def _file_size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _bundled_files(folder) -> list[tuple[str, int]]:
    """(path, size in bytes) of every file a skill bundles, in a fixed order.

    Everything in the folder counts except the SKILL.md family at the top
    level. Paths are relative to the folder and use "/" on every system.
    """
    found = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()  # os.walk visits the sub-folders in the order this list is left in
        inside = os.path.relpath(root, folder)
        top = inside == os.curdir
        for filename in sorted(files):
            if top and _is_skill_md_family(filename):
                continue
            relative = filename if top else inside.replace(os.sep, "/") + "/" + filename
            found.append((relative, _file_size(os.path.join(root, filename))))
    return found


def _path_inside(folder: Path, relative):
    """(path, None) for a file inside `folder`, or (None, why it is refused).

    `relative` comes from the model and may be anything. It must name a file
    by a relative path that stays inside the folder. Backslashes are taken as
    separators, so a Windows-style path works on Linux as well.
    """
    rel = relative.replace("\\", "/").strip() if isinstance(relative, str) else ""
    if not rel or rel.endswith("/"):
        return None, "file_path must name a file, not a directory"
    # The leading "/" is tested by hand: from Python 3.13, os.path.isabs() on
    # Windows no longer calls a path such as "/x", which names no drive, absolute.
    if rel.startswith("/") or os.path.isabs(rel) or re.match(r"[A-Za-z]:", rel):
        return None, "file_path must be RELATIVE to the skill's folder"
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None, "file_path may not leave the skill's folder ('..')"
    # A colon anywhere, not just at the start: on Windows "sub/Z:x.txt" would
    # name a file on drive Z.
    if any(":" in part for part in parts):
        return None, "file_path must be RELATIVE to the skill's folder (no ':')"
    if len(parts) == 1 and _is_skill_md_family(parts[0]):
        return None, ("SKILL.md (and its conflict forks) are managed by the "
                      "create/update actions, not as resource files")
    return folder.joinpath(*parts), None


def _spelled_differently(parent, sub: str) -> bool:
    """True when `parent` holds `sub` only under other capitals.

    Windows and macOS ignore capitals in file names, so there a path to
    "wave" leads into an existing folder "Wave". Whether a path exists cannot
    tell the two apart; the folder's listing can.
    """
    try:
        entries = os.listdir(parent)
    except OSError:
        return False
    return sub not in entries and any(entry.lower() == sub.lower() for entry in entries)


def _chmod_unless_link(path, mode) -> None:
    # os.chmod acts on what a link points to, and that may lie outside the tree.
    if os.path.islink(path):
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _make_removable(path) -> None:
    """Give the owner back the rights that deleting a tree needs.

    Windows will not delete a read-only file. Linux will not delete anything
    from a folder that its owner cannot write to, list and enter.
    """
    _chmod_unless_link(path, stat.S_IRWXU)
    for root, dirs, files in os.walk(path):
        # os.walk enters these folders only after this pass over them.
        for entry in dirs:
            _chmod_unless_link(os.path.join(root, entry), stat.S_IRWXU)
        for entry in files:
            _chmod_unless_link(os.path.join(root, entry), stat.S_IREAD | stat.S_IWRITE)


def _remove_tree(path) -> bool:
    """Delete a folder and all that is in it. True when it is gone afterwards.

    A failed attempt is repeated after a short pause, because on Windows
    another program (a virus scanner, an indexer) can hold a file for a moment.
    """
    for attempt in range(3):
        if not os.path.exists(path):
            return True
        _make_removable(path)
        try:
            shutil.rmtree(path)
        except OSError:
            pass
        if not os.path.exists(path):
            return True
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    try:
        os.rmdir(path)  # enough when only the emptied folder itself was left
    except OSError:
        pass
    return not os.path.exists(path)


# ---- the store ----


def _on_demand_listing(skills: dict) -> str:
    """The system prompt's index of on-demand skills, or "" when there are none.

    One line per skill: its name and, when it has one, its description. The
    description is what tells the model when to fetch the skill.
    """
    lines = []
    for name, skill in skills.items():
        if skill.get("mode") != "on_demand":
            continue
        description = (skill.get("description") or "").strip()
        lines.append(f"- {name} {_LONG_DASH} {description}" if description else f"- {name}")
    if not lines:
        return ""
    return ("## On-Demand Skills\n"
            "The following skills are available via the `get_skill` tool. "
            "Call `get_skill` with the skill name when its description matches "
            "the task at hand:\n" + "\n".join(lines))


class SkillStore:
    """The skills tree plus the modes in force for this run.

    Each skill has a GLOBAL mode (what SKILL.md says) and a SESSION mode (what
    this run uses). They differ only after an instruction's skill_modes were
    applied. Saving always writes global modes: a run's session modes never
    reach the disk.
    """

    def __init__(self, skills_dir):
        self.skills_dir = Path(skills_dir)
        self.skills = {}         # name -> entry; entry["mode"] is the SESSION mode
        self.save_errors = {}    # name -> why the last save() could not write it
        self._global_modes = {}  # name -> the mode that belongs in SKILL.md
        # name -> the skill as this program last read or wrote it, in the form
        # the serialiser gives it. A skill that still matches needs no saving.
        self._on_disk = {}

    # -- disk --

    def _scan(self):
        """Yield (folder, name, entry) for each readable SKILL.md, in sorted folder order."""
        try:
            subs = sorted(os.listdir(self.skills_dir))
        except OSError:
            return
        for sub in subs:
            folder = self.skills_dir / sub
            md = folder / SKILL_BASENAME
            if not md.is_file():
                continue
            try:
                name, entry = parse_skill_md(_read_text(md), sub)
            except (OSError, ValueError):
                continue  # unreadable: left out for now, and never deleted
            yield folder, name, entry

    def load(self) -> None:
        """Read the tree from disk. Every skill starts in its global mode."""
        skills = {}
        for _folder, name, entry in self._scan():
            # Two folders can claim one name. The first in sorted order is the
            # skill; the other is left untouched for its owner to sort out.
            skills.setdefault(name, entry)
        self.skills = skills
        self._global_modes = {name: entry["mode"] for name, entry in skills.items()}
        self._on_disk = {name: serialize_skill_md(name, entry)
                         for name, entry in skills.items()}
        self.save_errors = {}

    def save(self) -> None:
        """Write the SKILL.md of every skill that changed here. Never deletes.

        Only skills whose text differs from what this program last read or
        wrote are written. A skill left alone here is left alone on disk too,
        so an edit made meanwhile by another run of the program survives. A
        file that cannot be written does not stop the others: it is noted in
        `save_errors` and tried again by the next save.
        """
        self.save_errors = {}
        pending = {}
        for name, entry in self.skills.items():
            if not isinstance(entry, dict):
                continue
            text = serialize_skill_md(name, self._stored_form(name, entry))
            if self._on_disk.get(name) != text:
                pending[name] = text
        if not pending:
            return
        try:
            os.makedirs(self.skills_dir, exist_ok=True)
        except OSError as error:
            self.save_errors = {name: str(error) for name in pending}
            return
        homes = {}
        for folder, name, _entry in self._scan():
            homes.setdefault(name, folder)
        for name, text in pending.items():
            try:
                _write_skill_md(homes.get(name) or self._free_folder(name), text)
            except (OSError, ValueError) as error:
                # ValueError: text holding a character UTF-8 cannot encode.
                self.save_errors[name] = str(error) or type(error).__name__
                continue
            self._on_disk[name] = text

    def _stored_form(self, name: str, entry: dict) -> dict:
        """The entry as SKILL.md should hold it: with the skill's global mode."""
        # A skill seen here for the first time has no session of its own yet,
        # so the mode it carries is its global mode.
        mode = self._global_modes.setdefault(name, entry.get("mode", "disabled"))
        return entry if entry.get("mode") == mode else dict(entry, mode=mode)

    def _free_folder(self, name: str) -> Path:
        """A folder for a skill that has none: its own name, or a numbered one.

        A number is added while something else is in the way, so that two
        skills whose names give the same folder name never share a folder.
        """
        base = skill_dirname(name)
        sub, number = base, 2
        while True:
            folder = self.skills_dir / sub
            if (folder / SKILL_BASENAME).is_file():
                pass  # another skill's, or one that cannot be read: never write over it
            elif folder.is_dir() and _spelled_differently(self.skills_dir, sub):
                pass  # the path leads into a folder with other capitals: not ours
            else:
                return folder  # free, or a folder of exactly this name without a SKILL.md
            sub, number = f"{base}_{number}", number + 1

    def folder(self, name: str):
        """The folder that holds skill `name` on disk, or None.

        The name inside SKILL.md decides, not the folder's own name. The tree
        is searched afresh each time, because folders can be added, renamed
        or removed while the program runs.
        """
        for folder, found, _entry in self._scan():
            if found == name:
                return folder
        return None

    def delete(self, name: str) -> bool:
        """Remove a skill: its entry here and its folder with everything in it.

        False when no such skill is loaded, in which case nothing is touched,
        and when a folder could not be removed. The entry is dropped either
        way, so in the second case the skill may be back after the next load.
        """
        if name not in self.skills:
            return False
        del self.skills[name]
        self._global_modes.pop(name, None)
        self._on_disk.pop(name, None)
        # Every folder that claims the name goes, or a second one would bring
        # the skill back at the next start.
        folders = [folder for folder, found, _entry in self._scan() if found == name]
        gone = True
        for folder in folders:
            gone = _remove_tree(folder) and gone
        return gone

    def resources(self, name: str) -> list[tuple[str, int]]:
        """The files skill `name` bundles: (relative path with "/", bytes) pairs.

        SKILL.md itself is not one of them. Empty when the skill bundles
        nothing or has no folder on disk.
        """
        folder = self.folder(name)
        return _bundled_files(folder) if folder is not None else []

    def resource_path(self, name: str, relative: str):
        """(path, None) for a bundled file of skill `name`, or (None, reason).

        The file itself need not exist yet. The reason is a phrase to put
        after "Error: ".
        """
        _folder, path, reason = self._locate(name, relative)
        return path, reason

    def _locate(self, name: str, relative):
        """(skill folder, file path, reason): resource_path plus the folder it searched."""
        folder = self.folder(name)
        if folder is None:
            return None, None, f"skill '{name}' has no folder on disk yet - save the skill first"
        path, reason = _path_inside(folder, relative)
        return folder, path, reason

    # -- modes --

    def global_mode(self, name: str) -> str:
        """The mode SKILL.md holds for `name`; "disabled" for a skill that is not loaded."""
        entry = self.skills.get(name)
        own = entry.get("mode", "disabled") if isinstance(entry, dict) else "disabled"
        return self._global_modes.get(name, own)

    def set_mode(self, name: str, mode: str) -> None:
        """Change a skill's mode for good: for this run, and on disk at the next save().

        Raises KeyError for a skill that is not loaded and ValueError for a
        mode that does not exist.
        """
        if mode not in MODES:
            raise ValueError(f"Invalid skill mode {mode!r}. Valid modes: {', '.join(MODES)}.")
        self.skills[name]["mode"] = mode
        self._global_modes[name] = mode

    def apply_instruction_modes(self, skill_modes: dict) -> list[str]:
        """Put an instruction's saved skill modes in force for this run only.

        An empty snapshot changes nothing. Otherwise each skill the snapshot
        names takes the mode saved for it, and every skill it does not name
        is disabled for the run: the snapshot is the whole set of skills the
        instruction was saved with. A skill that is on in the store but
        missing from the snapshot (one created after the instruction was
        saved, say) would vanish from the run without a word, so a warning is
        returned for each. Nothing is written to disk.
        """
        if not skill_modes or not isinstance(skill_modes, dict):
            return []
        warnings = []
        for name, entry in self.skills.items():
            # Noted before the session mode changes, so a later save still
            # writes the mode the skill had in the store.
            in_store = self._global_modes.setdefault(name, entry.get("mode", "disabled"))
            wanted = skill_modes.get(name)
            if wanted is None:
                if in_store != "disabled":
                    warnings.append(
                        f"Skill '{name}': ON in the skills store but absent from this "
                        "instruction's skill_modes snapshot - disabled for this session. "
                        "Add it to the instruction's skill_modes to keep it on.")
                entry["mode"] = "disabled"
            elif wanted in MODES:
                entry["mode"] = wanted
        return warnings

    # -- what a run uses --

    def on_demand_names(self) -> list[str]:
        """The skills this run can fetch with get_skill, in the store's order."""
        return [name for name, skill in self.skills.items() if skill.get("mode") == "on_demand"]

    def get_on_demand(self, name: str) -> str | None:
        """The text of an on-demand skill, or None when `name` is not one in this run.

        Read from the live store, so text changed during the run is returned
        as it is now.
        """
        skill = self.skills.get(name) if isinstance(name, str) else None
        if isinstance(skill, dict) and skill.get("mode") == "on_demand":
            return skill.get("content", "")
        return None

    def compose_system_prompt(self, base_prompt: str) -> str:
        """The system prompt: the base, each enabled skill in full, then the on-demand index.

        The session modes decide. The caller composes this once when a run
        starts and keeps the result: the system prompt opens the cached part
        of every request, so a change in the middle of a run would throw the
        cache away.
        """
        parts = [base_prompt]
        for name, skill in self.skills.items():
            if skill.get("mode") == "enabled":
                parts.append(f"## Skill: {name}\n{skill.get('content', '')}")
        listing = _on_demand_listing(self.skills)
        if listing:
            parts.append(listing)
        return "\n\n".join(parts)


# ---- the manage_skills tool ----


def _file_argument(params: dict) -> str:
    """The file_path the model gave. Anything that is not text counts as none."""
    value = params.get("file_path", "")
    return value if isinstance(value, str) else ""


def _save_and_report(store: SkillStore, name: str, done: str) -> str:
    """Save after a create or an update, and say how it really went."""
    # The skill the model just named is checked against the disk whatever the
    # store remembers of it, so "successfully" always means the file is there
    # and says this, even if something removed or changed it meanwhile.
    store._on_disk.pop(name, None)
    store.save()
    problem = store.save_errors.get(name)
    if problem:
        return (f"Error: Skill '{name}' was {done} for this session only: "
                f"writing it to disk failed ({problem}).")
    return f"Skill '{name}' {done} successfully."


def _with_description_warning(reply: str, description: str) -> str:
    warning = description_warning(description)
    return f"{reply}\n{warning}" if warning else reply


def _list_skills(store: SkillStore) -> str:
    if not store.skills:
        return "No skills defined."
    lines = []
    for name in sorted(store.skills):
        skill = store.skills[name]
        description = (skill.get("description") or "").strip()
        # A skill without a description is shown by the start of its text.
        info = description or skill.get("content", "")[:100].replace("\n", " ") + "..."
        lines.append(f"- {name}  [{skill.get('mode', 'disabled')}]\n  {info}")
    return "\n".join(lines)


def _create_skill(store: SkillStore, name: str, params: dict) -> str:
    if name in store.skills:
        return f"Error: Skill '{name}' already exists. Use 'update' to modify it."
    if not is_valid_new_name(name):
        hint = kebabize(name)
        suggestion = f" Try '{hint}'." if hint else ""
        return ("Error: Skill names must be Agent-Skills kebab-case - lowercase "
                f"letters/digits/hyphens, max 64 chars (e.g. 'check-battery').{suggestion}")
    content = params.get("content", "")
    if not isinstance(content, str) or not content:
        return "Error: 'content' is required when creating a skill."
    mode = params.get("mode", "disabled")
    if mode not in MODES:
        return f"Error: Invalid mode '{mode}'. Valid modes: disabled, enabled, on_demand."
    description = params.get("description") or ""
    if not isinstance(description, str):
        return "Error: 'description' must be a string."
    description = description.strip()
    entry = {"content": content, "mode": mode}
    if description:
        entry["description"] = description
    store.skills[name] = entry
    store.set_mode(name, mode)
    return _with_description_warning(_save_and_report(store, name, "created"), description)


def _read_skill(store: SkillStore, name: str, params: dict) -> str:
    skill = store.skills[name]
    return json.dumps({"name": name, "content": skill.get("content", ""),
                       "mode": skill.get("mode", "disabled"),
                       "description": skill.get("description", "")}, indent=2)


def _update_skill(store: SkillStore, name: str, params: dict) -> str:
    content = params.get("content")
    mode = params.get("mode")
    description = params.get("description")
    if content is None and mode is None and description is None:
        return ("Error: At least one of 'content', 'mode' or 'description' must be "
                "provided for update.")
    # Everything is checked before anything is changed.
    if content is not None and not isinstance(content, str):
        return "Error: 'content' must be a string."
    if mode is not None and mode not in MODES:
        return f"Error: Invalid mode '{mode}'. Valid modes: disabled, enabled, on_demand."
    if description is not None and not isinstance(description, str):
        return "Error: 'description' must be a string."
    entry = store.skills[name]
    if content is not None:
        entry["content"] = content
    if mode is not None:
        store.set_mode(name, mode)
    given = ""
    if description is not None:
        given = description.strip()
        if given:
            entry["description"] = given
        else:
            entry.pop("description", None)  # an empty description removes it
    return _with_description_warning(_save_and_report(store, name, "updated"), given)


def _delete_skill(store: SkillStore, name: str, params: dict) -> str:
    removed = store.delete(name)
    store.save()
    if not removed:
        return (f"Error: Skill '{name}' was removed from this session, but its folder "
                "could not be deleted from disk. It may be back at the next start.")
    return f"Skill '{name}' deleted."


def _list_files(store: SkillStore, name: str, params: dict) -> str:
    folder = store.folder(name)
    if folder is None:
        return (f"Skill '{name}' has no folder on disk yet - its bundled "
                "files appear after the first save.")
    files = _bundled_files(folder)
    if not files:
        return f"Skill '{name}' has no bundled resource files (SKILL.md only)."
    lines = [f"- {relative}  ({size} bytes)" for relative, size in files]
    return f"Bundled resource files of '{name}':\n" + "\n".join(lines)


def _read_file(store: SkillStore, name: str, params: dict) -> str:
    shown = _file_argument(params)
    _folder, path, reason = store._locate(name, shown)
    if reason:
        return f"Error: {reason}."
    if not path.is_file():
        return f"Error: '{shown}' does not exist in skill '{name}' (use list_files)."
    try:
        with open(path, "rb") as f:
            raw = f.read(_READ_LIMIT + 1)  # one byte more shows whether there is more
    except OSError as error:
        return f"Error reading '{shown}': {error}"
    if b"\x00" in raw[:_BINARY_PROBE]:
        return (f"'{shown}' is a binary file ({_file_size(path)} bytes) - "
                "read_file returns text only.")
    text = raw.decode("utf-8", errors="replace")
    if len(raw) > _READ_LIMIT:
        text = text[:_READ_LIMIT] + "\n...[truncated at 200,000 bytes]"
    return text


def _write_file(store: SkillStore, name: str, params: dict) -> str:
    content = params.get("file_content")
    if content is None:
        return "Error: 'file_content' is required for write_file."
    if not isinstance(content, str):
        return ("Error: 'file_content' must be a string (the file's text) - "
                f"got {type(content).__name__}.")
    shown = _file_argument(params)
    _folder, path, reason = store._locate(name, shown)
    if reason:
        return f"Error: {reason}."
    if path.is_dir():
        return f"Error: '{shown}' is a folder in skill '{name}' - name a file."
    existed = path.is_file()
    try:
        os.makedirs(path.parent, exist_ok=True)
        _atomic_write(path, content)
    except (OSError, ValueError) as error:  # ValueError: a character UTF-8 cannot encode
        return f"Error writing '{shown}': {error}"
    verb = "Replaced" if existed else "Wrote"
    return f"{verb} '{shown}' in skill '{name}' ({len(content.encode('utf-8'))} bytes)."


def _delete_file(store: SkillStore, name: str, params: dict) -> str:
    shown = _file_argument(params)
    folder, path, reason = store._locate(name, shown)
    if reason:
        return f"Error: {reason}."
    if not path.is_file():
        return f"Error: '{shown}' does not exist in skill '{name}'."
    try:
        os.remove(path)
    except OSError as error:
        return f"Error deleting '{shown}': {error}"
    # Sub-folders this emptied go too. The walk is limited to the folders the
    # path names, so it can never reach the skill's own folder.
    parent = path.parent
    for _ in range(len(path.relative_to(folder).parts) - 1):
        try:
            os.rmdir(parent)  # works only on an empty folder
        except OSError:
            break
        parent = parent.parent
    return f"Deleted '{shown}' from skill '{name}'."


# The actions that work on a skill that must already exist.
_ON_EXISTING = {
    "read": _read_skill,
    "update": _update_skill,
    "delete": _delete_skill,
    "list_files": _list_files,
    "read_file": _read_file,
    "write_file": _write_file,
    "delete_file": _delete_file,
}


def manage_skills(store: SkillStore, tool_input: dict) -> str:
    """Carry out one manage_skills call from the model and return the reply text.

    Actions: list, read, create, update, delete, and for the files a skill
    bundles list_files, read_file, write_file and delete_file. A call that
    cannot be carried out is answered with a reply that starts with "Error";
    nothing is raised for bad input. A change is made in the store and saved
    straight away.
    """
    params = tool_input if isinstance(tool_input, dict) else {}
    action = params.get("action", "")
    name = params.get("name", "")
    if action == "list":
        return _list_skills(store)
    if not isinstance(name, str) or not name:
        return "Error: 'name' is required for this action."
    if action == "create":
        return _create_skill(store, name, params)
    handler = _ON_EXISTING.get(action) if isinstance(action, str) else None
    if handler is None:
        return f"Error: Unknown action '{action}'."
    if name not in store.skills:
        advice = " Use 'create' to add it." if action == "update" else ""
        return f"Error: Skill '{name}' not found.{advice}"
    return handler(store, name, params)
