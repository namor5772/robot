"""Tests for robot.skills: the SKILL.md format, the tree on disk, global and
session modes, the system prompt, and the manage_skills tool.

Everything is written inside a temporary folder that is removed afterwards.
"""

import ast
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import skills
from robot.skills import (
    MODES,
    SkillStore,
    description_warning,
    is_valid_new_name,
    kebabize,
    manage_skills,
    parse_skill_md,
    serialize_skill_md,
    skill_dirname,
)

# The separator between name and description in the system prompt's index of
# on-demand skills. Made from its code point so that this file stays ASCII.
DASH = chr(0x2014)

ENTRY = {"content": "# Do the thing\nStep 1.", "mode": "on_demand",
         "description": "Does the thing. Use when the thing needs doing."}

LISTING_HEAD = ("## On-Demand Skills\n"
                "The following skills are available via the `get_skill` tool. "
                "Call `get_skill` with the skill name when its description matches "
                "the task at hand:\n")

NAME_RULE = ("Error: Skill names must be Agent-Skills kebab-case - lowercase "
             "letters/digits/hyphens, max 64 chars (e.g. 'check-battery').")
BAD_MODE = "Error: Invalid mode 'sometimes'. Valid modes: disabled, enabled, on_demand."
LONG_WARNING = ("Warning: description is 1500 chars; the Agent Skills guideline is "
                "<=1024. Consider shortening it.")

# What the skills tree says, and what one instruction was saved with.
GLOBAL_TREE = {
    "blink-light": "enabled",
    "check-battery": "disabled",
    "drive-forward": "enabled",
    "play-sound": "disabled",
    "read-sensor": "disabled",
    "take-photo": "disabled",
    "wave-arm": "disabled",
}
INSTRUCTION_LAYOUT = {
    "blink-light": "disabled",
    "check-battery": "on_demand",
    "drive-forward": "on_demand",
    "play-sound": "on_demand",
    "read-sensor": "on_demand",
    "take-photo": "disabled",
    "wave-arm": "on_demand",
}


def _folds_case() -> bool:
    """True on a file system where "Wave" and "wave" are the same name."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "CaseProbe").mkdir()
        return (Path(tmp) / "caseprobe").is_dir()


def _left_off(name: str) -> str:
    """The warning for a skill that is on in the store but not in the snapshot."""
    return (f"Skill '{name}': ON in the skills store but absent from this instruction's "
            "skill_modes snapshot - disabled for this session. Add it to the "
            "instruction's skill_modes to keep it on.")


class TreeCase(unittest.TestCase):
    """Gives each test an empty skills folder of its own, and a store on it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tree = Path(tmp.name) / "skills"
        self.store = SkillStore(self.tree)

    def md_path(self, sub):
        return self.tree / sub / "SKILL.md"

    def write_md(self, sub, text, basename="SKILL.md"):
        """Write a file into a skill folder byte for byte (no newline translation)."""
        folder = self.tree / sub
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / basename
        path.write_bytes(text.encode("utf-8"))
        return path

    def put(self, name, content="body", mode="disabled", **more):
        """Put a skill on disk by hand, the way a copied folder arrives."""
        return self.write_md(name, serialize_skill_md(name, dict(more, content=content, mode=mode)))

    def reload(self):
        """What a new run of the program finds on disk."""
        store = SkillStore(self.tree)
        store.load()
        return store

    def act(self, **params):
        return manage_skills(self.store, params)

    def header(self, sub):
        """The header lines of a SKILL.md, without the two fences."""
        text = self.md_path(sub).read_bytes().decode("utf-8")
        return text.split("\n---\n", 1)[0].split("\n")[1:]

    def names_in(self, sub):
        return sorted(path.name for path in (self.tree / sub).iterdir())


# ---- the SKILL.md format ----


class FormatTests(unittest.TestCase):

    def test_the_three_modes_and_the_file_name(self):
        self.assertEqual(MODES, ("disabled", "enabled", "on_demand"))
        self.assertEqual(skills.SKILL_BASENAME, "SKILL.md")

    def test_the_serialised_text_is_exactly_this(self):
        self.assertEqual(
            serialize_skill_md("My Skill", ENTRY),
            "---\n"
            "name: My Skill\n"
            "description: Does the thing. Use when the thing needs doing.\n"
            "mode: on_demand\n"
            "---\n"
            "\n"
            "# Do the thing\n"
            "Step 1.\n")

    def test_the_smallest_files(self):
        self.assertEqual(serialize_skill_md("x", {"content": "body", "mode": "disabled"}),
                         "---\nname: x\nmode: disabled\n---\n\nbody\n")
        # No text: the header and the blank line, with nothing after them.
        self.assertEqual(serialize_skill_md("x", {"content": "", "mode": "enabled"}),
                         "---\nname: x\nmode: enabled\n---\n\n")
        self.assertEqual(serialize_skill_md("x", {}), "---\nname: x\nmode: disabled\n---\n\n")

    def test_header_values_are_put_on_one_line(self):
        entry = {"content": "b", "mode": "enabled", "description": " wrapped\n  by hand\t here "}
        self.assertEqual(
            serialize_skill_md("  Two\n Words ", entry),
            "---\nname: Two Words\ndescription: wrapped by hand here\nmode: enabled\n---\n\nb\n")

    def test_a_blank_description_writes_no_line(self):
        for blank in ("", "   ", None):
            text = serialize_skill_md("x", {"content": "b", "mode": "disabled",
                                            "description": blank})
            self.assertNotIn("description:", text, repr(blank))

    def test_the_text_ends_with_exactly_one_newline(self):
        for content in ("no trailing newline", "one already\n"):
            text = serialize_skill_md("x", {"content": content, "mode": "disabled"})
            self.assertEqual(text, "---\nname: x\nmode: disabled\n---\n\n" + content.rstrip("\n")
                             + "\n")

    def test_round_trip_exact(self):
        for entry in (ENTRY,
                      {"content": "no trailing newline", "mode": "disabled"},
                      {"content": "", "mode": "enabled"},
                      {"content": "keeps\n\ninner blanks\n", "mode": "disabled"}):
            name, parsed = parse_skill_md(serialize_skill_md("A Name", entry), "fallback")
            self.assertEqual(name, "A Name")
            expected = dict(entry)
            # The writer adds one final newline and the reader takes one off:
            # text without one comes back exactly, text with one loses it once
            # and is then stable.
            if expected["content"].endswith("\n"):
                expected["content"] = expected["content"][:-1]
            self.assertEqual(parsed, expected)
            again = parse_skill_md(serialize_skill_md(name, parsed), "fallback")
            self.assertEqual(again, (name, parsed))

    def test_text_without_a_header_is_all_content(self):
        name, entry = parse_skill_md("just some text\nno fences", "Folder Name")
        self.assertEqual(name, "Folder Name")
        self.assertEqual(entry, {"content": "just some text\nno fences", "mode": "disabled"})

    def test_an_unclosed_header_is_all_content(self):
        text = "---\nname: X\nnever closed"
        name, entry = parse_skill_md(text, "F")
        self.assertEqual((name, entry["content"]), ("F", text))

    def test_a_wrapped_description_is_folded(self):
        text = ("---\nname: X\ndescription: first part\n  wrapped second part\n"
                "mode: enabled\n---\n\nbody")
        name, entry = parse_skill_md(text, "F")
        self.assertEqual(name, "X")
        self.assertEqual(entry["description"], "first part wrapped second part")
        self.assertEqual(entry["mode"], "enabled")
        self.assertEqual(entry["content"], "body")

    def test_an_invalid_mode_and_unknown_keys_are_tolerated(self):
        text = "---\nname: X\nmode: bogus\nlicense: MIT\n---\n\nbody"
        _, entry = parse_skill_md(text, "F")
        self.assertEqual(entry, {"content": "body", "mode": "disabled"})

    def test_keys_and_the_mode_may_be_in_any_case(self):
        name, entry = parse_skill_md("---\nNAME: X\nMode: On_Demand\n---\n\nb\n", "F")
        self.assertEqual((name, entry), ("X", {"content": "b", "mode": "on_demand"}))

    def test_a_missing_or_blank_name_takes_the_fallback(self):
        for header in ("mode: enabled", "name:\nmode: enabled", "name:    \nmode: enabled"):
            name, entry = parse_skill_md(f"---\n{header}\n---\n\nb\n", "the-folder")
            self.assertEqual((name, entry["mode"]), ("the-folder", "enabled"), header)
        self.assertEqual(parse_skill_md("no header")[0], "")

    def test_the_separator_line_and_one_final_newline_are_not_content(self):
        _, entry = parse_skill_md("---\nname: X\n---\n\n\nline\n\n", "F")
        # One blank line and one final newline are the format's; the rest stays.
        self.assertEqual(entry["content"], "\nline\n")
        _, entry = parse_skill_md("---\nname: X\n---\nright after the fence", "F")
        self.assertEqual(entry["content"], "right after the fence")

    def test_header_values_of_windows_text_carry_no_carriage_return(self):
        name, entry = parse_skill_md("---\r\nname: X\r\nmode: enabled\r\n---\r\n\r\nb\r\n", "F")
        self.assertEqual((name, entry["mode"]), ("X", "enabled"))

    def test_folder_names(self):
        self.assertEqual(skill_dirname("check-battery"), "check-battery")
        self.assertEqual(skill_dirname('Ro/bot: "arm"?'), "Ro_bot_ _arm__")
        self.assertEqual(skill_dirname("..."), "_skill")
        self.assertEqual(skill_dirname("  "), "_skill")
        self.assertEqual(skill_dirname(" padded. "), "padded")
        self.assertEqual(skill_dirname("CON"), "_CON")
        self.assertEqual(skill_dirname("con.txt"), "_con.txt")
        self.assertEqual(skill_dirname("lpt1"), "_lpt1")
        self.assertEqual(skill_dirname("console"), "console")
        self.assertEqual(skill_dirname("tab\there"), "tab_here")

    def test_section_and_order_follow_mode_and_round_trip(self):
        entry = {"content": "body", "mode": "disabled", "section": "Motion", "order": 3}
        text = serialize_skill_md("arm-a", entry)
        self.assertEqual(text, "---\nname: arm-a\nmode: disabled\nsection: Motion\norder: 3\n"
                               "---\n\nbody\n")
        self.assertEqual(parse_skill_md(text, "fallback"), ("arm-a", entry))

    def test_a_skill_without_section_or_order_keeps_its_old_file(self):
        before = "---\nname: x\ndescription: d\nmode: on_demand\n---\n\nbody\n"
        entry = {"content": "body", "mode": "on_demand", "description": "d"}
        self.assertEqual(serialize_skill_md("x", entry), before)
        self.assertEqual(parse_skill_md(before, "x")[1], entry)

    def test_only_a_real_section_and_a_whole_number_order_are_written_or_read(self):
        for entry in ({"section": "", "order": None}, {"section": "   ", "order": True},
                      {"section": None, "order": "4"}, {"section": 7, "order": 2.0}):
            text = serialize_skill_md("x", dict(entry, content="b", mode="disabled"))
            self.assertNotIn("section:", text, entry)
            self.assertNotIn("order:", text, entry)
        text = "---\nname: x\nmode: disabled\nsection:   Two  Words \norder: three\n---\n\nb\n"
        _, entry = parse_skill_md(text, "x")
        self.assertEqual(entry.get("section"), "Two Words")
        self.assertNotIn("order", entry)
        _, entry = parse_skill_md("---\nname: x\nmode: disabled\norder: -2\n---\n\nb\n", "x")
        self.assertEqual(entry["order"], -2)
        self.assertEqual(serialize_skill_md("x", entry),
                         "---\nname: x\nmode: disabled\norder: -2\n---\n\nb\n")

    def test_an_order_too_long_to_convert_is_dropped(self):
        text = "---\nname: x\nmode: enabled\norder: " + "9" * 5000 + "\n---\n\nb\n"
        name, entry = parse_skill_md(text, "x")
        self.assertEqual((name, entry), ("x", {"content": "b", "mode": "enabled"}))


class NameAndDescriptionTests(unittest.TestCase):

    def test_conforming_names_are_accepted(self):
        for name in ("check-battery", "read-sensor", "a", "x1", "a-2-b",
                     "follow-the-line-on-the-floor", "a" * 64):
            self.assertTrue(is_valid_new_name(name), name)

    def test_other_names_are_rejected(self):
        for name in ("Check Battery", "S", "has space", "-leading", "trailing-",
                     "double--hyphen", "UPPER", "under_score", "a" * 65, "", "caf\xe9",
                     "line\n", None, 5):
            self.assertFalse(is_valid_new_name(name), repr(name))

    def test_kebabize(self):
        for raw, want in (("Test_skill", "test-skill"),
                          ("Check Battery", "check-battery"),
                          ("ARM  Wave!", "arm-wave"),
                          ("--Weird--Name--", "weird-name"),
                          ("a" * 70, "a" * 64),
                          ("a" * 63 + "-b", "a" * 63),
                          ("???", "")):
            self.assertEqual(kebabize(raw), want, raw)
            self.assertTrue(want == "" or is_valid_new_name(want), raw)

    def test_description_warning(self):
        self.assertEqual(description_warning(""), "")
        self.assertEqual(description_warning("x" * 1024), "")
        self.assertEqual(description_warning("x" * 1500), LONG_WARNING)
        self.assertIn("1025 chars", description_warning("x" * 1025))


# ---- the tree on disk ----


class SaveLoadTests(TreeCase):

    def test_a_new_store_is_empty_and_reads_nothing(self):
        self.assertEqual(self.store.skills, {})
        self.assertEqual(self.store.skills_dir, self.tree)
        self.assertFalse(self.tree.exists())

    def test_loading_a_missing_tree_gives_no_skills_and_creates_nothing(self):
        self.store.load()
        self.assertEqual(self.store.skills, {})
        self.assertFalse(self.tree.exists())

    def test_save_then_load_round_trips(self):
        entries = {"Alpha": dict(ENTRY), "Beta Two": {"content": "b", "mode": "disabled"}}
        self.store.skills = {name: dict(entry) for name, entry in entries.items()}
        self.store.save()
        self.assertEqual(self.store.save_errors, {})
        self.assertEqual(self.reload().skills, entries)
        self.assertTrue(self.md_path("Alpha").is_file())
        self.assertTrue(self.md_path("Beta Two").is_file())

    def test_the_file_is_utf8_with_lf_newlines(self):
        self.store.skills = {"alpha": {"content": "line one\nline two caf\xe9", "mode": "enabled",
                                       "description": "na\xefve " + DASH + " dash"}}
        self.store.save()
        expected = ("---\nname: alpha\ndescription: na\xefve " + DASH + " dash\n"
                    "mode: enabled\n---\n\nline one\nline two caf\xe9\n")
        raw = self.md_path("alpha").read_bytes()
        self.assertEqual(raw, expected.encode("utf-8"))
        self.assertNotIn(b"\r", raw)
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])  # no temporary file left

    def test_a_body_ending_in_blank_lines_reads_one_newline_shorter_and_its_file_is_kept(self):
        self.store.skills = {"alpha": {"content": "text\n\n\n", "mode": "disabled"}}
        self.store.save()
        raw = self.md_path("alpha").read_bytes()
        self.assertTrue(raw.endswith(b"---\n\ntext\n\n\n"), raw)
        # The reader takes one newline off. The skill did not change by that,
        # so no later save touches the file and the text stays as it is.
        for _ in range(3):
            store = self.reload()
            self.assertEqual(store.skills["alpha"]["content"], "text\n\n")
            store.save()
            self.assertEqual(self.md_path("alpha").read_bytes(), raw)

    def test_a_hostile_name_round_trips_through_the_header(self):
        entries = {'Run: "Fast"/Now?': {"content": "x", "mode": "enabled"}}
        self.store.skills = {name: dict(entry) for name, entry in entries.items()}
        self.store.save()
        self.assertEqual(os.listdir(self.tree), ["Run_ _Fast__Now_"])
        self.assertEqual(self.reload().skills, entries)

    def test_folders_are_read_in_sorted_order(self):
        for name in ("b-skill", "a-skill", "C-skill"):
            self.put(name)
        self.store.load()
        self.assertEqual(list(self.store.skills), ["C-skill", "a-skill", "b-skill"])

    def test_loading_again_replaces_what_was_held(self):
        self.put("alpha", content="one")
        self.store.load()
        self.store.skills["alpha"]["content"] = "changed here, never saved"
        self.store.skills["extra"] = {"content": "x", "mode": "enabled"}
        self.store.load()
        self.assertEqual(self.store.skills, {"alpha": {"content": "one", "mode": "disabled"}})

    def test_an_unchanged_save_does_not_rewrite(self):
        self.store.skills = {"alpha": dict(ENTRY)}
        self.store.save()
        md = self.md_path("alpha")
        before = md.stat().st_mtime_ns
        os.utime(md, ns=(before - 10**9, before - 10**9))
        stamped = md.stat().st_mtime_ns
        self.store.save()
        self.assertEqual(md.stat().st_mtime_ns, stamped)
        # A store that never read the file, holding the same skill, finds the
        # file already right and leaves it too.
        other = SkillStore(self.tree)
        other.skills = {"alpha": dict(ENTRY)}
        other.save()
        self.assertEqual(md.stat().st_mtime_ns, stamped)
        self.assertEqual(other.save_errors, {})

    def test_save_never_deletes(self):
        # A folder the store does not hold survives a save: a store that is
        # behind must not wipe a skill something else put there.
        self.store.skills = {"Keep": {"content": "k", "mode": "disabled"},
                             "Other": {"content": "o", "mode": "disabled"}}
        self.store.save()
        behind = SkillStore(self.tree)
        behind.skills = {"Other": {"content": "o2", "mode": "disabled"}}
        behind.save()
        loaded = self.reload().skills
        self.assertIn("Keep", loaded)
        self.assertEqual(loaded["Other"]["content"], "o2")

    def test_save_writes_only_the_skills_changed_here(self):
        self.put("alpha", content="a1")
        self.put("beta", content="b1")
        first, second = self.reload(), self.reload()
        manage_skills(second, {"action": "update", "name": "alpha",
                               "content": "a2 from the second run", "mode": "enabled"})
        # The first run still holds the old alpha. Saving its own change to
        # beta must not put that old alpha back.
        self.assertEqual(first.skills["alpha"]["content"], "a1")
        manage_skills(first, {"action": "update", "name": "beta",
                              "content": "b2 from the first run"})
        now = self.reload().skills
        self.assertEqual(now["alpha"], {"content": "a2 from the second run", "mode": "enabled"})
        self.assertEqual(now["beta"]["content"], "b2 from the first run")

    def test_a_save_of_other_skills_does_not_bring_back_a_skill_removed_from_disk(self):
        self.put("alpha")
        self.put("beta")
        self.store.load()
        os.remove(self.md_path("alpha"))  # another run of the program deleted it
        os.rmdir(self.tree / "alpha")
        self.act(action="update", name="beta", content="new")
        self.assertEqual(os.listdir(self.tree), ["beta"])

    def test_a_file_edited_by_hand_is_left_alone_by_a_save_of_other_skills(self):
        self.put("alpha")
        self.put("beta")
        self.store.load()
        by_hand = "---\nname: alpha\nlicense: MIT\nmode: enabled\n---\n\nedited in an editor\n"
        self.write_md("alpha", by_hand)
        self.assertEqual(self.act(action="update", name="beta", content="new"),
                         "Skill 'beta' updated successfully.")
        self.assertEqual(self.md_path("alpha").read_bytes(), by_hand.encode("utf-8"))

    def test_a_skill_is_saved_into_the_folder_it_lives_in(self):
        # Folder names are never corrected: the name in the header decides.
        self.write_md("Old-Folder", serialize_skill_md("wave-arm",
                                                       {"content": "c", "mode": "enabled"}))
        self.store.load()
        self.assertEqual(self.store.folder("wave-arm"), self.tree / "Old-Folder")
        self.assertEqual(self.act(action="update", name="wave-arm", content="new"),
                         "Skill 'wave-arm' updated successfully.")
        self.assertEqual(os.listdir(self.tree), ["Old-Folder"])
        self.assertEqual(self.reload().skills["wave-arm"]["content"], "new")

    def test_two_names_that_give_one_folder_name_get_numbered_folders(self):
        self.store.skills = {"A/B": {"content": "1", "mode": "disabled"}}
        self.store.save()
        second = SkillStore(self.tree)
        second.skills = {"A?B": {"content": "2", "mode": "disabled"}}
        second.save()
        self.assertEqual(sorted(os.listdir(self.tree)), ["A_B", "A_B_2"])
        loaded = self.reload().skills
        self.assertEqual(loaded["A/B"]["content"], "1")
        self.assertEqual(loaded["A?B"]["content"], "2")

    def test_two_such_names_in_one_save(self):
        self.store.skills = {"A/B": {"content": "1", "mode": "disabled"},
                             "A?B": {"content": "2", "mode": "disabled"},
                             "A*B": {"content": "3", "mode": "disabled"}}
        self.store.save()
        self.assertEqual(sorted(os.listdir(self.tree)), ["A_B", "A_B_2", "A_B_3"])
        self.assertEqual({name: entry["content"] for name, entry in self.reload().skills.items()},
                         {"A/B": "1", "A?B": "2", "A*B": "3"})

    def test_two_folders_claiming_one_name_the_first_wins_and_both_stay(self):
        one = self.write_md("A", serialize_skill_md("Same", {"content": "one", "mode": "disabled"}))
        two = self.write_md("B", serialize_skill_md("Same", {"content": "two", "mode": "enabled"}))
        before = (one.read_bytes(), two.read_bytes())
        self.store.load()
        self.assertEqual(self.store.skills, {"Same": {"content": "one", "mode": "disabled"}})
        self.assertEqual(self.store.folder("Same"), self.tree / "A")
        self.store.save()
        self.assertEqual((one.read_bytes(), two.read_bytes()), before)
        self.assertEqual(sorted(os.listdir(self.tree)), ["A", "B"])

    def test_a_folder_without_skill_md_is_no_skill_and_is_left_alone(self):
        draft = self.tree / "being-written"
        draft.mkdir(parents=True)
        (draft / "notes.txt").write_bytes(b"notes")
        (self.tree / "empty-one").mkdir()
        (self.tree / "stray-file.txt").write_bytes(b"x")
        old = draft.stat().st_mtime - 3600
        os.utime(draft, (old, old))
        self.put("alpha")
        self.store.load()
        self.assertEqual(list(self.store.skills), ["alpha"])
        self.store.save()
        self.assertEqual(sorted(os.listdir(self.tree)),
                         ["alpha", "being-written", "empty-one", "stray-file.txt"])
        self.assertEqual((draft / "notes.txt").read_bytes(), b"notes")

    def test_a_skill_md_that_cannot_be_read_is_skipped_and_kept(self):
        for sub, raw in (("no-encoding-fits", b"\x81\x8d"), ("half-a-utf16", b"\xff\xfe\x00")):
            folder = self.tree / sub
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_bytes(raw)
        self.put("alpha")
        self.store.load()
        self.assertEqual(list(self.store.skills), ["alpha"])
        self.assertIsNone(self.store.folder("no-encoding-fits"))
        self.assertEqual(self.md_path("no-encoding-fits").read_bytes(), b"\x81\x8d")
        self.assertEqual(self.md_path("half-a-utf16").read_bytes(), b"\xff\xfe\x00")

    def test_a_folder_whose_skill_md_cannot_be_read_is_never_written_over(self):
        folder = self.tree / "check-battery"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_bytes(b"\x81\x8d")
        self.store.load()
        self.assertEqual(self.act(action="create", name="check-battery", content="c"),
                         "Skill 'check-battery' created successfully.")
        self.assertEqual((folder / "SKILL.md").read_bytes(), b"\x81\x8d")
        self.assertEqual(self.store.folder("check-battery"), self.tree / "check-battery_2")

    def test_an_empty_folder_of_the_same_name_is_adopted(self):
        script = self.tree / "check-battery" / "scripts" / "run.sh"
        script.parent.mkdir(parents=True)
        script.write_bytes(b"echo")
        self.store.load()
        self.act(action="create", name="check-battery", content="c")
        self.assertEqual(os.listdir(self.tree), ["check-battery"])
        self.assertEqual(self.store.resources("check-battery"), [("scripts/run.sh", 4)])

    def test_section_and_order_survive_load_and_save(self):
        entries = {
            "arm-b": {"content": "body b", "mode": "on_demand", "section": "Motion",
                      "order": 1, "description": "Second arm skill."},
            "arm-a": {"content": "body a", "mode": "disabled", "section": "Motion", "order": 0},
            "sense-a": {"content": "body s", "mode": "enabled", "section": "Sensors", "order": 2},
            "loose": {"content": "body l", "mode": "disabled"},
        }
        self.store.skills = {name: dict(entry) for name, entry in entries.items()}
        self.store.save()
        loaded = self.reload()
        self.assertEqual(loaded.skills, entries)
        # A change to one skill rewrites that skill's file only, layout kept.
        before = {name: self.md_path(name).read_bytes() for name in entries}
        manage_skills(loaded, {"action": "update", "name": "arm-b", "content": "new body"})
        changed = {name for name in entries if self.md_path(name).read_bytes() != before[name]}
        self.assertEqual(changed, {"arm-b"})
        self.assertEqual(self.header("arm-b"),
                         ["name: arm-b", "description: Second arm skill.", "mode: on_demand",
                          "section: Motion", "order: 1"])

    def test_one_file_that_cannot_be_written_does_not_stop_the_others(self):
        real_write = skills._atomic_write

        def write(path, text, temp_prefix="tmp"):
            if "bad-one" in str(path):
                raise OSError("disk full")
            real_write(path, text, temp_prefix)

        self.store.skills = {"bad-one": {"content": "x", "mode": "disabled"},
                             "good-one": {"content": "y", "mode": "disabled"}}
        with mock.patch.object(skills, "_atomic_write", side_effect=write):
            self.store.save()
        self.assertEqual(self.store.save_errors, {"bad-one": "disk full"})
        self.assertTrue(self.md_path("good-one").is_file())
        self.assertFalse(self.md_path("bad-one").exists())
        # The next save tries the failed one again, and only that one.
        stamp = self.md_path("good-one").stat().st_mtime_ns - 10**9
        os.utime(self.md_path("good-one"), ns=(stamp, stamp))
        stamped = self.md_path("good-one").stat().st_mtime_ns
        self.store.save()
        self.assertEqual(self.store.save_errors, {})
        self.assertTrue(self.md_path("bad-one").is_file())
        self.assertEqual(self.md_path("good-one").stat().st_mtime_ns, stamped)

    def test_a_failed_move_leaves_the_old_file_and_no_temporary_file(self):
        self.put("alpha", content="old")
        self.store.load()
        with mock.patch.object(skills.os, "replace", side_effect=OSError("locked")):
            out = self.act(action="update", name="alpha", content="new")
        self.assertEqual(out, "Error: Skill 'alpha' was updated for this session only: "
                              "writing it to disk failed (locked).")
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])
        self.assertEqual(self.reload().skills["alpha"]["content"], "old")

    def test_a_skills_folder_that_cannot_be_made_is_reported_for_every_pending_skill(self):
        self.tree.parent.joinpath("skills").write_bytes(b"a file where the folder should be")
        self.store.skills = {"alpha": {"content": "x", "mode": "disabled"},
                             "beta": {"content": "y", "mode": "disabled"}}
        self.store.save()
        self.assertEqual(sorted(self.store.save_errors), ["alpha", "beta"])


class EncodingTests(TreeCase):
    """SKILL.md files that some other program saved are read all the same."""

    TEXT = ("---\nname: alpha\ndescription: caf\xe9 d\xe9j\xe0\nmode: enabled\n---\n\n"
            "line one\nline two\n")
    WANTED = {"content": "line one\nline two", "mode": "enabled",
              "description": "caf\xe9 d\xe9j\xe0"}

    def load_bytes(self, raw):
        folder = self.tree / "alpha"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_bytes(raw)
        self.store.load()
        return self.store.skills

    def test_plain_utf8(self):
        self.assertEqual(self.load_bytes(self.TEXT.encode("utf-8")), {"alpha": self.WANTED})

    def test_utf8_with_a_byte_order_mark(self):
        raw = b"\xef\xbb\xbf" + self.TEXT.encode("utf-8")
        self.assertEqual(self.load_bytes(raw), {"alpha": self.WANTED})

    def test_utf16_in_either_byte_order(self):
        little = b"\xff\xfe" + self.TEXT.encode("utf-16-le")
        big = b"\xfe\xff" + self.TEXT.encode("utf-16-be")
        for raw in (little, big):
            self.assertEqual(self.load_bytes(raw), {"alpha": self.WANTED})

    def test_the_windows_western_code_page(self):
        raw = self.TEXT.encode("cp1252")
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")  # so this really takes the last-resort reading
        self.assertEqual(self.load_bytes(raw), {"alpha": self.WANTED})

    def test_windows_and_old_mac_line_endings(self):
        for ending in ("\r\n", "\r"):
            raw = self.TEXT.replace("\n", ending).encode("utf-8")
            self.assertEqual(self.load_bytes(raw), {"alpha": self.WANTED}, repr(ending))

    def test_a_windows_file_is_left_as_it_is_until_its_skill_changes(self):
        raw = self.TEXT.replace("\n", "\r\n").encode("utf-8")
        self.put("beta")
        self.load_bytes(raw)
        md = self.md_path("alpha")
        self.act(action="update", name="beta", content="a save that does not concern alpha")
        self.assertEqual(md.read_bytes(), raw)
        # A store that holds the same skill without having read the file
        # compares the text, not the bytes, and leaves the file as well.
        other = SkillStore(self.tree)
        other.skills = {"alpha": dict(self.WANTED)}
        other.save()
        self.assertEqual(md.read_bytes(), raw)
        self.act(action="update", name="alpha", content="now it changes")
        self.assertNotIn(b"\r", md.read_bytes())
        self.assertEqual(self.reload().skills["alpha"]["content"], "now it changes")


class CapitalsTests(TreeCase):
    """Windows and macOS treat "Alpha" and "alpha" as one folder name."""

    @unittest.skipUnless(_folds_case(), "needs a file system that ignores capitals")
    def test_a_new_skill_does_not_land_in_another_skills_folder(self):
        self.write_md("Alpha", serialize_skill_md("Alpha", {"content": "old", "mode": "disabled"}))
        self.store.load()
        self.store.skills["alpha"] = {"content": "new", "mode": "enabled"}
        self.store.save()
        loaded = self.reload().skills
        self.assertEqual(loaded["Alpha"]["content"], "old")
        self.assertEqual(loaded["alpha"]["content"], "new")
        self.assertEqual(sorted(os.listdir(self.tree)), ["Alpha", "alpha_2"])

    @unittest.skipUnless(_folds_case(), "needs a file system that ignores capitals")
    def test_a_folder_spelled_with_other_capitals_is_not_adopted(self):
        (self.tree / "Alpha").mkdir(parents=True)
        self.store.skills["alpha"] = {"content": "x", "mode": "disabled"}
        self.store.save()
        self.assertEqual(os.listdir(self.tree / "Alpha"), [])
        self.assertEqual(sorted(os.listdir(self.tree)), ["Alpha", "alpha_2"])
        self.assertEqual(self.reload().skills["alpha"]["content"], "x")

    def test_spelled_differently(self):
        cases = ((["Alpha"], True), (["alpha"], False), (["Alpha", "alpha"], False),
                 (["alpha", "Alpha"], False), ([], False), (["other"], False))
        for entries, want in cases:
            with mock.patch.object(skills.os, "listdir", return_value=entries):
                self.assertIs(skills._spelled_differently("anywhere", "alpha"), want, entries)
        with mock.patch.object(skills.os, "listdir", side_effect=OSError("gone")):
            self.assertIs(skills._spelled_differently("anywhere", "alpha"), False)


# ---- global and session modes ----


class ModeTests(TreeCase):

    def plant(self, modes):
        for name, mode in modes.items():
            self.put(name, content=f"body of {name}", mode=mode)
        self.store.load()

    def session(self, store=None):
        return {name: entry["mode"] for name, entry in (store or self.store).skills.items()}

    def in_store(self):
        return {name: self.store.global_mode(name) for name in self.store.skills}

    def files(self):
        return {path.parent.name: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in sorted(self.tree.glob("*/SKILL.md"))}

    def test_a_fresh_load_runs_every_skill_in_its_global_mode(self):
        self.plant(GLOBAL_TREE)
        self.assertEqual(self.session(), GLOBAL_TREE)
        self.assertEqual(self.in_store(), GLOBAL_TREE)

    def test_an_empty_snapshot_changes_nothing(self):
        self.plant(GLOBAL_TREE)
        for nothing in ({}, None):
            self.assertEqual(self.store.apply_instruction_modes(nothing), [])
            self.assertEqual(self.session(), GLOBAL_TREE)
            self.assertEqual(self.in_store(), GLOBAL_TREE)

    def test_a_snapshot_that_is_not_a_dict_changes_nothing(self):
        self.plant(GLOBAL_TREE)
        for junk in (["blink-light"], "enabled", 7):
            self.assertEqual(self.store.apply_instruction_modes(junk), [])
        self.assertEqual(self.session(), GLOBAL_TREE)

    def test_the_snapshot_is_applied_over_the_global_modes(self):
        self.plant(GLOBAL_TREE)
        warnings = self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.assertEqual(self.session(), INSTRUCTION_LAYOUT)
        self.assertEqual(self.in_store(), GLOBAL_TREE)
        self.assertEqual(warnings, [])  # every skill was in the snapshot

    def test_applying_writes_nothing_and_neither_does_a_save_after_it(self):
        self.plant(GLOBAL_TREE)
        before = self.files()
        self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.assertEqual(self.files(), before)
        self.store.save()
        self.assertEqual(self.files(), before)
        self.assertEqual(self.session(self.reload()), GLOBAL_TREE)

    def test_every_skill_the_snapshot_does_not_name_is_disabled(self):
        self.plant(GLOBAL_TREE)
        self.store.apply_instruction_modes({"read-sensor": "enabled"})
        self.assertEqual(self.session(), dict.fromkeys(GLOBAL_TREE, "disabled")
                         | {"read-sensor": "enabled"})
        self.assertEqual(self.in_store(), GLOBAL_TREE)

    def test_a_warning_for_each_skill_that_was_on(self):
        self.plant({"new-skill": "enabled", "old": "on_demand", "other-new": "on_demand",
                    "quiet": "disabled"})
        warnings = self.store.apply_instruction_modes({"old": "on_demand"})
        self.assertEqual(self.session(), {"new-skill": "disabled", "old": "on_demand",
                                          "other-new": "disabled", "quiet": "disabled"})
        self.assertEqual(warnings, [_left_off("new-skill"), _left_off("other-new")])

    def test_a_skill_that_was_off_already_is_left_out_in_silence(self):
        self.plant({"quiet": "disabled"})
        self.assertEqual(self.store.apply_instruction_modes({"deleted-skill": "enabled"}), [])
        self.assertEqual(self.session(), {"quiet": "disabled"})

    def test_a_snapshot_that_names_only_unknown_skills_still_disables_the_rest(self):
        self.plant({"busy": "enabled"})
        warnings = self.store.apply_instruction_modes({"deleted-skill": "enabled"})
        self.assertEqual(self.session(), {"busy": "disabled"})
        self.assertEqual(warnings, [_left_off("busy")])
        self.assertNotIn("deleted-skill", self.store.skills)

    def test_modes_the_snapshot_names_apply_without_a_warning(self):
        self.plant({"a": "disabled", "b": "enabled", "c": "on_demand"})
        warnings = self.store.apply_instruction_modes(
            {"a": "on_demand", "b": "disabled", "c": "enabled"})
        self.assertEqual(self.session(), {"a": "on_demand", "b": "disabled", "c": "enabled"})
        self.assertEqual(warnings, [])

    def test_a_mode_that_does_not_exist_leaves_that_skill_as_it_is(self):
        self.plant({"a": "enabled", "b": "enabled", "c": "disabled"})
        warnings = self.store.apply_instruction_modes({"a": "sometimes", "b": "", "c": 3})
        self.assertEqual(self.session(), {"a": "enabled", "b": "enabled", "c": "disabled"})
        self.assertEqual(warnings, [])

    def test_a_skill_made_after_the_instruction_was_saved_is_forced_off_with_a_warning(self):
        self.plant(dict(GLOBAL_TREE, **{"brand-new": "enabled"}))
        warnings = self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.assertEqual(self.store.skills["brand-new"]["mode"], "disabled")
        self.assertEqual(self.store.global_mode("brand-new"), "enabled")
        self.assertEqual(warnings, [_left_off("brand-new")])

    def test_applying_again_warns_again(self):
        self.plant({"s": "enabled"})
        first = self.store.apply_instruction_modes({"z": "disabled"})
        second = self.store.apply_instruction_modes({"z": "disabled"})
        self.assertEqual(first, [_left_off("s")])
        self.assertEqual(second, first)
        self.assertEqual(self.session(), {"s": "disabled"})

    def test_a_save_after_applying_writes_the_global_modes(self):
        self.plant(GLOBAL_TREE)
        self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        # Both skills now run in a mode that differs from the one in the tree.
        self.assertEqual(self.act(action="update", name="blink-light", content="new text"),
                         "Skill 'blink-light' updated successfully.")
        self.act(action="update", name="check-battery", description="Reads the voltage.")
        self.assertEqual(self.header("blink-light"), ["name: blink-light", "mode: enabled"])
        self.assertEqual(self.header("check-battery"),
                         ["name: check-battery", "description: Reads the voltage.",
                          "mode: disabled"])
        self.assertEqual(self.session(self.reload()), GLOBAL_TREE)
        self.assertEqual(self.reload().skills["blink-light"]["content"], "new text")
        # The run itself goes on with the instruction's modes.
        self.assertEqual(self.session(), INSTRUCTION_LAYOUT)

    def test_set_mode_changes_both_and_reaches_the_disk_at_the_next_save(self):
        self.plant(GLOBAL_TREE)
        self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.store.set_mode("take-photo", "on_demand")
        self.assertEqual(self.store.skills["take-photo"]["mode"], "on_demand")
        self.assertEqual(self.store.global_mode("take-photo"), "on_demand")
        self.assertEqual(self.session(self.reload())["take-photo"], "disabled")  # not saved yet
        self.store.save()
        self.assertEqual(self.session(self.reload()),
                         dict(GLOBAL_TREE, **{"take-photo": "on_demand"}))

    def test_set_mode_refuses_what_does_not_exist(self):
        self.plant({"a": "enabled"})
        with self.assertRaises(ValueError):
            self.store.set_mode("a", "sometimes")
        with self.assertRaises(KeyError):
            self.store.set_mode("ghost", "enabled")
        self.assertEqual((self.session(), self.in_store()), ({"a": "enabled"}, {"a": "enabled"}))

    def test_the_tool_changes_both_modes(self):
        self.plant(GLOBAL_TREE)
        self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.act(action="update", name="wave-arm", mode="enabled")
        self.assertEqual(self.store.skills["wave-arm"]["mode"], "enabled")
        self.assertEqual(self.store.global_mode("wave-arm"), "enabled")
        self.act(action="create", name="spin-around", content="c", mode="on_demand")
        self.assertEqual(self.store.skills["spin-around"]["mode"], "on_demand")
        self.assertEqual(self.store.global_mode("spin-around"), "on_demand")
        self.assertEqual(self.session(self.reload()),
                         dict(GLOBAL_TREE, **{"wave-arm": "enabled", "spin-around": "on_demand"}))

    def test_a_skill_put_in_the_store_by_hand_keeps_its_mode_on_disk(self):
        self.plant({"old": "enabled"})
        self.store.skills["by-hand"] = {"content": "c", "mode": "enabled"}
        self.assertEqual(self.store.global_mode("by-hand"), "enabled")
        warnings = self.store.apply_instruction_modes({"old": "enabled"})
        self.assertEqual(warnings, [_left_off("by-hand")])
        self.assertEqual(self.store.skills["by-hand"]["mode"], "disabled")
        self.store.save()
        self.assertEqual(self.session(self.reload()), {"old": "enabled", "by-hand": "enabled"})

    def test_the_global_mode_of_an_unknown_skill_is_disabled(self):
        self.assertEqual(self.store.global_mode("ghost"), "disabled")

    def test_loading_again_returns_to_the_global_modes(self):
        self.plant(GLOBAL_TREE)
        self.store.apply_instruction_modes(INSTRUCTION_LAYOUT)
        self.store.load()
        self.assertEqual(self.session(), GLOBAL_TREE)

    def test_a_deleted_skills_mode_is_forgotten(self):
        self.plant({"spin-around": "enabled"})
        self.act(action="delete", name="spin-around")
        self.assertEqual(self.store.global_mode("spin-around"), "disabled")
        self.act(action="create", name="spin-around", content="c")
        self.assertEqual(self.session(self.reload()), {"spin-around": "disabled"})


# ---- the system prompt ----


class PromptTests(TreeCase):

    def test_the_base_alone_when_there_are_no_skills(self):
        self.assertEqual(self.store.compose_system_prompt("BASE"), "BASE")
        self.assertEqual(self.store.compose_system_prompt(""), "")
        self.assertEqual(self.store.on_demand_names(), [])

    def test_no_index_when_nothing_is_on_demand(self):
        self.store.skills = {"a": {"content": "x", "mode": "enabled"},
                             "b": {"content": "y", "mode": "disabled"}}
        self.assertEqual(self.store.compose_system_prompt("BASE"), "BASE\n\n## Skill: a\nx")
        self.assertEqual(self.store.on_demand_names(), [])

    def test_the_whole_prompt(self):
        self.store.skills = {
            "house-style": {"content": "ENABLED-BODY", "mode": "enabled"},
            "read-sensor": {"content": "od-body", "mode": "on_demand",
                            "description": "Do X. Use when Y."},
            "bare": {"content": "bare-body", "mode": "on_demand"},
            "unused": {"content": "unused-body", "mode": "disabled", "description": "Never."},
        }
        prompt = self.store.compose_system_prompt("BASE")
        self.assertEqual(prompt,
                         "BASE\n\n## Skill: house-style\nENABLED-BODY\n\n" + LISTING_HEAD
                         + "- read-sensor " + DASH + " Do X. Use when Y.\n- bare")
        # The text of an on-demand skill is fetched, not put in the prompt,
        # and a disabled skill is not mentioned at all.
        self.assertNotIn("od-body", prompt)
        self.assertNotIn("unused", prompt)
        self.assertEqual(self.store.on_demand_names(), ["read-sensor", "bare"])

    def test_a_blank_description_is_no_description(self):
        self.store.skills = {"s": {"content": "c", "mode": "on_demand", "description": "   "}}
        self.assertEqual(self.store.compose_system_prompt("B"), "B\n\n" + LISTING_HEAD + "- s")

    def test_skills_appear_in_the_stores_order(self):
        for name in ("b-skill", "a-skill"):
            self.put(name, content=f"text of {name}", mode="enabled")
        self.store.load()
        self.store.skills["0-added-later"] = {"content": "late", "mode": "enabled"}
        self.assertEqual(self.store.compose_system_prompt("BASE"),
                         "BASE\n\n## Skill: a-skill\ntext of a-skill\n\n## Skill: b-skill\n"
                         "text of b-skill\n\n## Skill: 0-added-later\nlate")

    def test_the_session_modes_decide(self):
        for name, mode in (("a", "enabled"), ("b", "on_demand"), ("c", "disabled")):
            self.put(name, content=f"text of {name}", mode=mode)
        self.store.load()
        self.store.apply_instruction_modes({"a": "on_demand", "c": "enabled"})
        self.assertEqual(self.store.compose_system_prompt("BASE"),
                         "BASE\n\n## Skill: c\ntext of c\n\n" + LISTING_HEAD + "- a")
        self.assertEqual(self.store.on_demand_names(), ["a"])
        self.assertEqual(self.store.get_on_demand("a"), "text of a")
        self.assertIsNone(self.store.get_on_demand("b"))  # on demand in the tree, off in this run

    def test_get_on_demand(self):
        self.store.skills = {"od": {"content": "od-body", "mode": "on_demand"},
                             "on": {"content": "on-body", "mode": "enabled"},
                             "off": {"content": "off-body", "mode": "disabled"}}
        self.assertEqual(self.store.get_on_demand("od"), "od-body")
        self.assertIsNone(self.store.get_on_demand("on"))
        self.assertIsNone(self.store.get_on_demand("off"))
        self.assertIsNone(self.store.get_on_demand("ghost"))
        for junk in (None, 7, ["od"]):
            self.assertIsNone(self.store.get_on_demand(junk))
        # It reads the live store: a change is there at once.
        self.store.skills["od"]["content"] = "edited"
        self.assertEqual(self.store.get_on_demand("od"), "edited")

    def test_a_prompt_composed_earlier_is_what_the_caller_keeps(self):
        self.store.skills = {
            "listen": {"mode": "on_demand", "description": "Record audio.", "content": "# Rec"},
            "house-style": {"mode": "enabled", "description": "", "content": "Be brief."},
            "unused": {"mode": "disabled", "description": "", "content": "x"},
        }
        kept = self.store.compose_system_prompt("You are an agent.")
        self.assertIn("- listen " + DASH + " Record audio.", kept)
        # What a run's manage_skills calls do to the live skills.
        self.act(action="update", name="listen", description="Record audio to a file.")
        self.act(action="update", name="house-style", content="Be very brief.")
        self.act(action="create", name="new-skill", content="y", mode="on_demand",
                 description="New.")
        self.assertNotIn("new-skill", kept)
        self.assertIn("Be brief.", kept)
        # Composing again follows the live skills: that is the next run's prompt.
        later = self.store.compose_system_prompt("You are an agent.")
        self.assertIn("- listen " + DASH + " Record audio to a file.", later)
        self.assertIn("## Skill: house-style\nBe very brief.", later)
        self.assertIn("- new-skill " + DASH + " New.", later)
        self.assertNotIn("Record audio.\n", later)

    def test_an_empty_base_is_joined_like_any_other(self):
        self.store.skills = {"late": {"mode": "enabled", "content": "z"}}
        self.assertEqual(self.store.compose_system_prompt(""), "\n\n## Skill: late\nz")


# ---- bundled files ----


class ResourcePathTests(TreeCase):

    def setUp(self):
        super().setUp()
        self.put("alpha")
        self.store.load()

    def path(self, relative):
        return self.store.resource_path("alpha", relative)

    def test_valid_paths_resolve_inside_the_folder(self):
        for relative, parts in (("notes.txt", ("notes.txt",)),
                                ("references/palette.md", ("references", "palette.md")),
                                ("scripts\\run.py", ("scripts", "run.py")),
                                ("./refs/a.txt", ("refs", "a.txt")),
                                ("  notes.txt  ", ("notes.txt",)),
                                ("a//b.txt", ("a", "b.txt"))):
            with self.subTest(relative=relative):
                path, reason = self.path(relative)
                self.assertIsNone(reason)
                self.assertIsInstance(path, Path)
                self.assertEqual(path, self.tree.joinpath("alpha", *parts))

    def test_escapes_and_non_files_are_refused(self):
        outside = "file_path may not leave the skill's folder ('..')"
        relative = "file_path must be RELATIVE to the skill's folder"
        no_file = "file_path must name a file, not a directory"
        for given, why in (("../other/x.txt", outside), ("refs/../../x.txt", outside),
                           ("..", outside), (".", outside), ("..\\x.txt", outside),
                           ("/abs/x.txt", relative), ("\\abs\\x.txt", relative),
                           ("C:/evil.txt", relative), ("C:\\evil.txt", relative),
                           ("c:evil.txt", relative),
                           ("sub/Z:evil.txt", relative + " (no ':')"),
                           ("notes.txt:stream", relative + " (no ':')"),
                           ("", no_file), ("   ", no_file), ("refs/", no_file),
                           ("refs\\", no_file), (None, no_file), (7, no_file)):
            with self.subTest(given=given):
                self.assertEqual(self.path(given), (None, why))

    def test_skill_md_and_its_kin_are_refused_at_the_top_only(self):
        why = ("SKILL.md (and its conflict forks) are managed by the create/update "
               "actions, not as resource files")
        for given in ("SKILL.md", "skill.md", "./SKILL.md", "SKILL-Laptop.md",
                      "skill-notes.md", "SKILL.md.abc.tmp"):
            with self.subTest(given=given):
                self.assertEqual(self.path(given), (None, why))
        # Inside a sub-folder the same names are ordinary files, and so are
        # names that only look alike.
        for given in ("references/SKILL.md", "SKILLS.md", "skill-notes.txt", "my-SKILL.md"):
            with self.subTest(given=given):
                path, reason = self.path(given)
                self.assertIsNone(reason)
                self.assertEqual(path, self.tree.joinpath("alpha", *given.split("/")))

    def test_a_skill_without_a_folder_names_the_problem(self):
        self.assertEqual(self.store.resource_path("ghost", "a.txt"),
                         (None, "skill 'ghost' has no folder on disk yet - save the skill first"))


class ResourceListTests(TreeCase):

    def test_nested_files_in_a_fixed_order_without_skill_md_and_its_kin(self):
        self.put("alpha")
        self.write_md("alpha", "another copy", basename="SKILL-Laptop.md")
        self.write_md("alpha", "left by a crash", basename="SKILL.md.abc.tmp")
        for relative, size in (("zz.txt", 5), ("references/b.md", 2), ("references/a.md", 1),
                               ("scripts/deep/run.py", 3), ("references/SKILL.md", 4)):
            path = self.tree / "alpha" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * size)
        self.store.load()
        self.assertEqual(self.store.resources("alpha"),
                         [("zz.txt", 5), ("references/SKILL.md", 4), ("references/a.md", 1),
                          ("references/b.md", 2), ("scripts/deep/run.py", 3)])
        self.assertEqual(self.store.folder("alpha"), self.tree / "alpha")
        # Loading and saving leave the look-alike files where they are: no
        # second copy of SKILL.md is merged in or cleared away here.
        self.act(action="update", name="alpha", content="changed")
        self.assertEqual((self.tree / "alpha" / "SKILL-Laptop.md").read_bytes(), b"another copy")
        self.assertEqual((self.tree / "alpha" / "SKILL.md.abc.tmp").read_bytes(),
                         b"left by a crash")
        self.assertEqual(list(self.reload().skills), ["alpha"])

    def test_no_folder_and_no_files_are_both_empty(self):
        self.assertEqual(self.store.resources("ghost"), [])
        self.assertIsNone(self.store.folder("ghost"))
        self.put("alpha")
        self.store.load()
        self.assertEqual(self.store.resources("alpha"), [])

    def test_the_folder_is_found_by_the_name_in_the_header(self):
        self.write_md("alpha", serialize_skill_md("something-else",
                                                  {"content": "x", "mode": "disabled"}))
        self.write_md("alpha_2", serialize_skill_md("alpha", {"content": "y", "mode": "disabled"}))
        (self.tree / "alpha_2" / "notes.md").write_bytes(b"12")
        self.store.load()
        self.assertEqual(self.store.folder("alpha"), self.tree / "alpha_2")
        self.assertEqual(self.store.resources("alpha"), [("notes.md", 2)])
        self.assertEqual(self.store.resources("something-else"), [])


class FileToolTests(TreeCase):
    """The four manage_skills actions on the files a skill bundles."""

    def setUp(self):
        super().setUp()
        self.put("alpha")
        self.store.load()

    def test_write_list_read_delete(self):
        out = self.act(action="write_file", name="alpha",
                       file_path="references/palette.md", file_content="colors")
        self.assertEqual(out, "Wrote 'references/palette.md' in skill 'alpha' (6 bytes).")
        self.assertEqual(self.act(action="list_files", name="alpha"),
                         "Bundled resource files of 'alpha':\n"
                         "- references/palette.md  (6 bytes)")
        self.assertEqual(self.act(action="read_file", name="alpha",
                                  file_path="references/palette.md"), "colors")
        out = self.act(action="write_file", name="alpha",
                       file_path="references/palette.md", file_content="colors v2")
        self.assertEqual(out, "Replaced 'references/palette.md' in skill 'alpha' (9 bytes).")
        out = self.act(action="delete_file", name="alpha", file_path="references/palette.md")
        self.assertEqual(out, "Deleted 'references/palette.md' from skill 'alpha'.")
        # The emptied sub-folder is gone; the skill's own folder is not.
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])
        self.assertEqual(self.act(action="list_files", name="alpha"),
                         "Skill 'alpha' has no bundled resource files (SKILL.md only).")

    def test_several_files_are_listed_one_per_line(self):
        for relative, text in (("b.txt", "22"), ("a.txt", "1"), ("sub/c.txt", "333")):
            self.act(action="write_file", name="alpha", file_path=relative, file_content=text)
        self.assertEqual(self.act(action="list_files", name="alpha"),
                         "Bundled resource files of 'alpha':\n- a.txt  (1 bytes)\n"
                         "- b.txt  (2 bytes)\n- sub/c.txt  (3 bytes)")

    def test_the_text_is_written_as_given(self):
        text = "one\r\ntwo\nthree caf\xe9"
        out = self.act(action="write_file", name="alpha", file_path="scripts\\run.py",
                       file_content=text)
        # The path is echoed as the model gave it; the size is in UTF-8 bytes.
        self.assertEqual(out, "Wrote 'scripts\\run.py' in skill 'alpha' (20 bytes).")
        self.assertEqual((self.tree / "alpha" / "scripts" / "run.py").read_bytes(),
                         b"one\r\ntwo\nthree caf\xc3\xa9")
        self.assertEqual(self.names_in("alpha/scripts"), ["run.py"])  # no temporary file
        self.assertEqual(self.act(action="write_file", name="alpha", file_path="empty.txt",
                                  file_content=""),
                         "Wrote 'empty.txt' in skill 'alpha' (0 bytes).")
        self.assertEqual((self.tree / "alpha" / "empty.txt").read_bytes(), b"")

    def test_escapes_and_skill_md_are_refused(self):
        before = self.md_path("alpha").read_bytes()
        for relative in ("../evil.txt", "sub/../../evil.txt", "SKILL.md", "C:\\evil.txt",
                         "/abs/evil.txt"):
            for action in ("write_file", "read_file", "delete_file"):
                with self.subTest(relative=relative, action=action):
                    out = self.act(action=action, name="alpha", file_path=relative,
                                   file_content="x")
                    self.assertTrue(out.startswith("Error: "), out)
                    self.assertTrue(out.endswith("."), out)
        self.assertEqual(self.act(action="write_file", name="alpha", file_path="../evil.txt",
                                  file_content="x"),
                         "Error: file_path may not leave the skill's folder ('..').")
        self.assertEqual(sorted(os.listdir(self.tree)), ["alpha"])
        self.assertEqual(sorted(os.listdir(self.tree.parent)), ["skills"])
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])
        self.assertEqual(self.md_path("alpha").read_bytes(), before)

    def test_guards(self):
        for action in ("list_files", "read_file", "write_file", "delete_file"):
            self.assertEqual(self.act(action=action, name="ghost", file_path="a.txt",
                                      file_content="x"),
                             "Error: Skill 'ghost' not found.")
        self.assertEqual(self.act(action="write_file", name="alpha", file_path="a.txt"),
                         "Error: 'file_content' is required for write_file.")
        self.assertEqual(self.act(action="write_file", name="alpha", file_path="a.txt",
                                  file_content=5),
                         "Error: 'file_content' must be a string (the file's text) - got int.")
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="a.txt"),
                         "Error: 'a.txt' does not exist in skill 'alpha' (use list_files).")
        self.assertEqual(self.act(action="delete_file", name="alpha", file_path="a.txt"),
                         "Error: 'a.txt' does not exist in skill 'alpha'.")
        for action in ("read_file", "delete_file"):
            self.assertEqual(self.act(action=action, name="alpha"),
                             "Error: file_path must name a file, not a directory.")
            self.assertEqual(self.act(action=action, name="alpha", file_path=["a.txt"]),
                             "Error: file_path must name a file, not a directory.")
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])

    def test_a_folder_is_not_a_file(self):
        (self.tree / "alpha" / "refs").mkdir()
        self.assertEqual(self.act(action="write_file", name="alpha", file_path="refs",
                                  file_content="x"),
                         "Error: 'refs' is a folder in skill 'alpha' - name a file.")
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="refs"),
                         "Error: 'refs' does not exist in skill 'alpha' (use list_files).")
        self.assertEqual(self.act(action="delete_file", name="alpha", file_path="refs"),
                         "Error: 'refs' does not exist in skill 'alpha'.")
        self.assertTrue((self.tree / "alpha" / "refs").is_dir())

    def test_a_skill_with_no_folder_yet(self):
        self.store.skills["in-memory"] = {"content": "c", "mode": "disabled"}
        self.assertEqual(self.act(action="list_files", name="in-memory"),
                         "Skill 'in-memory' has no folder on disk yet - its bundled files "
                         "appear after the first save.")
        self.assertEqual(self.act(action="write_file", name="in-memory", file_path="a.txt",
                                  file_content="x"),
                         "Error: skill 'in-memory' has no folder on disk yet - save the "
                         "skill first.")

    def test_a_binary_file_is_reported_not_dumped(self):
        (self.tree / "alpha" / "blob.bin").write_bytes(b"\x00\x01\x02")
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="blob.bin"),
                         "'blob.bin' is a binary file (3 bytes) - read_file returns text only.")

    def test_only_the_first_8192_bytes_are_searched_for_a_nul(self):
        (self.tree / "alpha" / "edge.bin").write_bytes(b"a" * 8191 + b"\x00")
        self.assertIn("is a binary file (8192 bytes)",
                      self.act(action="read_file", name="alpha", file_path="edge.bin"))
        (self.tree / "alpha" / "late.txt").write_bytes(b"a" * 8192 + b"\x00" + b"b")
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="late.txt"),
                         "a" * 8192 + "\x00" + "b")

    def test_a_long_file_is_cut_at_200000_bytes(self):
        (self.tree / "alpha" / "exact.txt").write_bytes(b"a" * 200_000)
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="exact.txt"),
                         "a" * 200_000)
        (self.tree / "alpha" / "long.txt").write_bytes(b"a" * 200_001)
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="long.txt"),
                         "a" * 200_000 + "\n...[truncated at 200,000 bytes]")
        (self.tree / "alpha" / "longer.txt").write_bytes(b"a" * 300_000)
        self.assertEqual(len(self.act(action="read_file", name="alpha", file_path="longer.txt")),
                         200_000 + len("\n...[truncated at 200,000 bytes]"))

    def test_bytes_that_are_not_utf8_are_shown_as_replacement_characters(self):
        (self.tree / "alpha" / "latin.txt").write_bytes(b"caf\xe9 au lait")
        self.assertEqual(self.act(action="read_file", name="alpha", file_path="latin.txt"),
                         "caf" + chr(0xFFFD) + " au lait")

    def test_text_that_utf8_cannot_encode_is_refused_and_leaves_nothing(self):
        out = self.act(action="write_file", name="alpha", file_path="sub/bad.txt",
                       file_content="half a pair " + chr(0xD800))
        self.assertTrue(out.startswith("Error writing 'sub/bad.txt': "), out)
        self.assertEqual(self.names_in("alpha/sub"), [])

    def test_deleting_removes_the_folders_it_empties_and_no_others(self):
        for relative in ("a/b/c.txt", "a/keep.txt", "top.txt"):
            self.act(action="write_file", name="alpha", file_path=relative, file_content="x")
        self.act(action="delete_file", name="alpha", file_path="a/b/c.txt")
        self.assertEqual(self.store.resources("alpha"), [("top.txt", 1), ("a/keep.txt", 1)])
        self.assertFalse((self.tree / "alpha" / "a" / "b").exists())
        self.act(action="delete_file", name="alpha", file_path="a\\keep.txt")
        self.assertFalse((self.tree / "alpha" / "a").exists())
        self.act(action="delete_file", name="alpha", file_path="top.txt")
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])
        self.assertEqual(os.listdir(self.tree), ["alpha"])

    def test_a_deep_chain_of_emptied_folders_goes_in_one_call(self):
        self.act(action="write_file", name="alpha", file_path="a/b/c/d.txt", file_content="x")
        self.act(action="delete_file", name="alpha", file_path="./a/b//c/d.txt")
        self.assertEqual(self.names_in("alpha"), ["SKILL.md"])


# ---- the manage_skills tool on skills ----


class SkillToolTests(TreeCase):

    def test_list_with_no_skills(self):
        self.assertEqual(self.act(action="list"), "No skills defined.")
        self.assertEqual(self.act(action="list", name="ignored"), "No skills defined.")

    def test_list_shows_the_description_or_else_the_start_of_the_text(self):
        self.store.skills = {
            "read-sensor": {"content": "body-A", "mode": "on_demand", "description": "Desc-A"},
            "blink-light": {"content": "body-B\nsecond line", "mode": "enabled"},
            "long-one": {"content": "x" * 150, "mode": "disabled", "description": "  "},
        }
        self.assertEqual(self.act(action="list"),
                         "- blink-light  [enabled]\n  body-B second line...\n"
                         "- long-one  [disabled]\n  " + "x" * 100 + "...\n"
                         "- read-sensor  [on_demand]\n  Desc-A")

    def test_list_and_read_say_nothing_of_sections(self):
        self.put("arm-a", content="body a", mode="disabled", section="Motion", order=0)
        self.store.load()
        self.assertEqual(self.act(action="list"), "- arm-a  [disabled]\n  body a...")
        self.assertEqual(json.loads(self.act(action="read", name="arm-a")),
                         {"name": "arm-a", "content": "body a", "mode": "disabled",
                          "description": ""})

    def test_read(self):
        self.store.skills = {"read-sensor": {"content": "line one\nline two caf\xe9",
                                             "mode": "on_demand", "description": "What. When."}}
        out = self.act(action="read", name="read-sensor")
        wanted = {"name": "read-sensor", "content": "line one\nline two caf\xe9",
                  "mode": "on_demand", "description": "What. When."}
        self.assertEqual(out, json.dumps(wanted, indent=2))
        self.assertEqual(json.loads(out), wanted)
        self.assertEqual(list(json.loads(out)), ["name", "content", "mode", "description"])
        self.assertTrue(out.isascii())
        self.assertEqual(self.act(action="read", name="ghost"), "Error: Skill 'ghost' not found.")

    def test_every_action_but_list_needs_a_name(self):
        for action in ("read", "create", "update", "delete", "list_files", "read_file",
                       "write_file", "delete_file", "nonsense", ""):
            for params in ({}, {"name": ""}, {"name": None}, {"name": 7}, {"name": ["x"]}):
                self.assertEqual(manage_skills(self.store, dict(params, action=action)),
                                 "Error: 'name' is required for this action.", (action, params))
        self.assertEqual(manage_skills(self.store, {}),
                         "Error: 'name' is required for this action.")
        self.assertEqual(manage_skills(self.store, None),
                         "Error: 'name' is required for this action.")

    def test_an_unknown_action(self):
        self.assertEqual(self.act(action="explode", name="x"), "Error: Unknown action 'explode'.")
        self.assertEqual(self.act(name="x"), "Error: Unknown action ''.")
        self.assertEqual(self.act(action=["list"], name="x"),
                         "Error: Unknown action '['list']'.")

    def test_create_writes_the_skill(self):
        out = self.act(action="create", name="check-battery", content="Read the voltage.",
                       mode="on_demand", description=" What. When. ")
        self.assertEqual(out, "Skill 'check-battery' created successfully.")
        self.assertEqual(self.store.skills["check-battery"],
                         {"content": "Read the voltage.", "mode": "on_demand",
                          "description": "What. When."})
        self.assertEqual(self.md_path("check-battery").read_bytes(),
                         b"---\nname: check-battery\ndescription: What. When.\n"
                         b"mode: on_demand\n---\n\nRead the voltage.\n")
        self.assertIn('"description": "What. When."',
                      self.act(action="read", name="check-battery"))
        self.assertEqual(self.reload().skills, self.store.skills)

    def test_create_defaults_to_disabled_and_no_description(self):
        self.assertEqual(self.act(action="create", name="tidy-skill", content="c"),
                         "Skill 'tidy-skill' created successfully.")
        self.assertEqual(self.store.skills["tidy-skill"], {"content": "c", "mode": "disabled"})
        self.assertEqual(self.header("tidy-skill"), ["name: tidy-skill", "mode: disabled"])
        self.act(action="create", name="blank-desc", content="c", description="   ")
        self.assertNotIn("description", self.store.skills["blank-desc"])

    def test_create_ignores_a_section(self):
        out = self.act(action="create", name="tidy-skill", content="c", section="Motion")
        self.assertEqual(out, "Skill 'tidy-skill' created successfully.")
        self.assertEqual(self.store.skills["tidy-skill"], {"content": "c", "mode": "disabled"})
        self.assertEqual(self.header("tidy-skill"), ["name: tidy-skill", "mode: disabled"])

    def test_create_refuses_a_name_that_is_taken(self):
        self.act(action="create", name="check-battery", content="first")
        self.assertEqual(self.act(action="create", name="check-battery", content="second"),
                         "Error: Skill 'check-battery' already exists. Use 'update' to modify it.")
        self.assertEqual(self.store.skills["check-battery"]["content"], "first")

    def test_create_refuses_a_nonconforming_name_and_suggests_one(self):
        out = self.act(action="create", name="Title Case", content="c")
        self.assertEqual(out, NAME_RULE + " Try 'title-case'.")
        self.assertEqual(self.store.skills, {})
        self.assertFalse(self.tree.exists())  # nothing was saved

    def test_create_refuses_an_unconvertible_name_without_a_suggestion(self):
        self.assertEqual(self.act(action="create", name="???", content="c"), NAME_RULE)
        self.assertEqual(self.act(action="create", name="a" * 65, content="c"),
                         NAME_RULE + " Try '" + "a" * 64 + "'.")

    def test_create_needs_content(self):
        for params in ({}, {"content": ""}, {"content": None}, {"content": ["text"]}):
            self.assertEqual(self.act(action="create", name="check-battery", **params),
                             "Error: 'content' is required when creating a skill.", params)
        self.assertEqual(self.store.skills, {})

    def test_create_refuses_a_mode_that_does_not_exist(self):
        self.assertEqual(self.act(action="create", name="check-battery", content="c",
                                  mode="sometimes"), BAD_MODE)
        self.assertEqual(self.act(action="create", name="check-battery", content="c", mode=None),
                         "Error: Invalid mode 'None'. Valid modes: disabled, enabled, on_demand.")
        self.assertEqual(self.store.skills, {})

    def test_create_refuses_a_description_that_is_not_text(self):
        self.assertEqual(self.act(action="create", name="check-battery", content="c",
                                  description=["a", "b"]),
                         "Error: 'description' must be a string.")
        self.assertEqual(self.store.skills, {})

    def test_a_long_description_warns_but_is_saved(self):
        long_desc = "x" * 1500
        out = self.act(action="create", name="desc-skill", content="c", description=long_desc)
        self.assertEqual(out, "Skill 'desc-skill' created successfully.\n" + LONG_WARNING)
        self.assertEqual(self.reload().skills["desc-skill"]["description"], long_desc)
        out = self.act(action="update", name="desc-skill", description="y" * 1500)
        self.assertEqual(out, "Skill 'desc-skill' updated successfully.\n" + LONG_WARNING)
        # A long description that is already there draws no warning later on.
        self.assertEqual(self.act(action="update", name="desc-skill", content="c2"),
                         "Skill 'desc-skill' updated successfully.")

    def test_update_the_description_alone(self):
        self.put("some-skill", content="c")
        self.store.load()
        self.assertEqual(self.act(action="update", name="some-skill", description=" D "),
                         "Skill 'some-skill' updated successfully.")
        self.assertEqual(self.store.skills["some-skill"],
                         {"content": "c", "mode": "disabled", "description": "D"})
        self.assertEqual(self.reload().skills, self.store.skills)

    def test_update_with_an_empty_description_removes_it(self):
        self.put("some-skill", content="c", description="D")
        self.store.load()
        self.act(action="update", name="some-skill", description="")
        self.assertNotIn("description", self.store.skills["some-skill"])
        self.assertEqual(self.header("some-skill"), ["name: some-skill", "mode: disabled"])

    def test_update_of_the_content_keeps_the_description(self):
        self.put("some-skill", content="c", description="D")
        self.store.load()
        self.act(action="update", name="some-skill", content="c2")
        self.assertEqual(self.reload().skills["some-skill"],
                         {"content": "c2", "mode": "disabled", "description": "D"})

    def test_update_may_empty_the_content(self):
        self.put("some-skill", content="c")
        self.store.load()
        self.assertEqual(self.act(action="update", name="some-skill", content=""),
                         "Skill 'some-skill' updated successfully.")
        self.assertEqual(self.reload().skills["some-skill"]["content"], "")

    def test_update_with_nothing_to_change_is_an_error(self):
        self.put("some-skill")
        self.store.load()
        wanted = ("Error: At least one of 'content', 'mode' or 'description' must be "
                  "provided for update.")
        self.assertEqual(self.act(action="update", name="some-skill"), wanted)
        # A section is not something this tool files skills under.
        self.assertEqual(self.act(action="update", name="some-skill", section="Motion"), wanted)

    def test_update_checks_everything_before_changing_anything(self):
        self.put("some-skill", content="c", mode="enabled", description="D")
        self.store.load()
        before = self.md_path("some-skill").read_bytes()
        self.assertEqual(self.act(action="update", name="some-skill", content="c2",
                                  mode="sometimes"), BAD_MODE)
        self.assertEqual(self.act(action="update", name="some-skill", content=5),
                         "Error: 'content' must be a string.")
        self.assertEqual(self.act(action="update", name="some-skill", content="c2",
                                  mode="disabled", description=5),
                         "Error: 'description' must be a string.")
        self.assertEqual(self.store.skills["some-skill"],
                         {"content": "c", "mode": "enabled", "description": "D"})
        self.assertEqual(self.store.global_mode("some-skill"), "enabled")
        self.assertEqual(self.md_path("some-skill").read_bytes(), before)

    def test_an_update_puts_the_file_back_when_it_was_removed_meanwhile(self):
        self.put("alpha", content="text")
        self.store.load()
        os.remove(self.md_path("alpha"))
        os.rmdir(self.tree / "alpha")
        # Nothing about the skill changes here, but the model asked for it to
        # be saved, so "successfully" has to mean that it is on disk.
        self.assertEqual(self.act(action="update", name="alpha", content="text"),
                         "Skill 'alpha' updated successfully.")
        self.assertEqual(self.reload().skills, {"alpha": {"content": "text", "mode": "disabled"}})

    def test_an_update_wins_over_another_runs_edit_of_the_same_skill(self):
        self.put("alpha", content="a1")
        first, second = self.reload(), self.reload()
        manage_skills(second, {"action": "update", "name": "alpha", "content": "a2"})
        self.assertEqual(manage_skills(first, {"action": "update", "name": "alpha",
                                               "content": "a1"}),
                         "Skill 'alpha' updated successfully.")
        self.assertEqual(self.reload().skills["alpha"]["content"], "a1")

    def test_an_update_that_changes_nothing_does_not_rewrite_the_file(self):
        self.put("alpha", content="text", mode="enabled")
        self.store.load()
        md = self.md_path("alpha")
        stamp = md.stat().st_mtime_ns - 10**9
        os.utime(md, ns=(stamp, stamp))
        stamped = md.stat().st_mtime_ns
        self.assertEqual(self.act(action="update", name="alpha", content="text",
                                  mode="enabled"),
                         "Skill 'alpha' updated successfully.")
        self.assertEqual(md.stat().st_mtime_ns, stamped)

    def test_update_of_a_skill_that_is_not_there(self):
        self.assertEqual(self.act(action="update", name="ghost", content="c"),
                         "Error: Skill 'ghost' not found. Use 'create' to add it.")

    def test_a_skill_with_an_old_style_name_can_still_be_changed_and_deleted(self):
        self.put("Legacy Name", content="old", mode="enabled")
        self.store.load()
        self.assertEqual(self.act(action="update", name="Legacy Name", content="new"),
                         "Skill 'Legacy Name' updated successfully.")
        self.assertEqual(self.reload().skills["Legacy Name"]["content"], "new")
        self.assertEqual(self.act(action="delete", name="Legacy Name"),
                         "Skill 'Legacy Name' deleted.")
        self.assertEqual(self.reload().skills, {})

    def test_an_update_keeps_section_and_order_in_the_file(self):
        self.put("arm-a", content="body a", mode="disabled", section="Motion", order=0)
        self.store.load()
        self.assertEqual(self.act(action="update", name="arm-a",
                                  description="Added by the tool."),
                         "Skill 'arm-a' updated successfully.")
        self.assertEqual(self.header("arm-a"),
                         ["name: arm-a", "description: Added by the tool.", "mode: disabled",
                          "section: Motion", "order: 0"])
        self.act(action="update", name="arm-a", description="")
        self.assertEqual(self.header("arm-a"),
                         ["name: arm-a", "mode: disabled", "section: Motion", "order: 0"])
        self.assertEqual(self.reload().skills["arm-a"],
                         {"content": "body a", "mode": "disabled", "section": "Motion",
                          "order": 0})

    def test_delete_removes_the_folder_with_its_bundled_files(self):
        self.act(action="create", name="check-battery", content="c", mode="enabled")
        self.act(action="write_file", name="check-battery", file_path="scripts/read.py",
                 file_content="print(1)")
        self.put("other")
        self.assertEqual(self.act(action="delete", name="check-battery"),
                         "Skill 'check-battery' deleted.")
        self.assertNotIn("check-battery", self.store.skills)
        self.assertEqual(os.listdir(self.tree), ["other"])
        self.assertEqual(list(self.reload().skills), ["other"])
        self.assertEqual(self.act(action="delete", name="check-battery"),
                         "Error: Skill 'check-battery' not found.")

    def test_a_failed_write_is_told_and_tried_again(self):
        with mock.patch.object(skills, "_atomic_write", side_effect=OSError("disk full")):
            out = self.act(action="create", name="check-battery", content="c")
        self.assertEqual(out, "Error: Skill 'check-battery' was created for this session only: "
                              "writing it to disk failed (disk full).")
        self.assertEqual(self.store.save_errors, {"check-battery": "disk full"})
        self.assertIn("check-battery", self.store.skills)
        self.assertFalse(self.md_path("check-battery").exists())
        self.store.save()  # the disk works again
        self.assertEqual(self.store.save_errors, {})
        self.assertEqual(self.reload().skills["check-battery"]["content"], "c")

    def test_text_that_utf8_cannot_encode_fails_alone(self):
        self.put("alpha")
        self.store.load()
        out = self.act(action="create", name="odd-text", content="half a pair " + chr(0xD800))
        self.assertTrue(out.startswith("Error: Skill 'odd-text' was created for this session "
                                       "only: writing it to disk failed ("), out)
        self.assertEqual(self.names_in("odd-text"), [])
        # The skill that cannot be written does not get in the way of others.
        self.assertEqual(self.act(action="update", name="alpha", content="still saved"),
                         "Skill 'alpha' updated successfully.")
        self.assertEqual(self.reload().skills, {"alpha": {"content": "still saved",
                                                           "mode": "disabled"}})

    def test_every_reply_is_plain_ascii(self):
        self.put("Old Name", content="caf\xe9", description="d")
        self.store.load()
        replies = [
            self.act(action="list"),
            self.act(action="read", name="Old Name"),
            self.act(action="read", name="ghost"),
            self.act(action="read"),
            self.act(action="explode", name="x"),
            self.act(action="create", name="Bad Name", content="c"),
            self.act(action="create", name="???", content="c"),
            self.act(action="create", name="new-one"),
            self.act(action="create", name="new-one", content="c", mode="x"),
            self.act(action="create", name="new-one", content="c", description="x" * 1100),
            self.act(action="create", name="new-one", content="c"),
            self.act(action="update", name="new-one"),
            self.act(action="update", name="ghost", content="c"),
            self.act(action="update", name="new-one", mode="on_demand"),
            self.act(action="list_files", name="new-one"),
            self.act(action="write_file", name="new-one", file_path="a/b.txt", file_content="x"),
            self.act(action="write_file", name="new-one", file_path="a/b.txt", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="a", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="a/b.txt", file_content=1),
            self.act(action="write_file", name="new-one", file_path="a/b.txt"),
            self.act(action="write_file", name="new-one", file_path="../x", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="/x", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="a:b", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="SKILL.md", file_content="y"),
            self.act(action="write_file", name="new-one", file_path="", file_content="y"),
            self.act(action="list_files", name="new-one"),
            self.act(action="read_file", name="new-one", file_path="nope.txt"),
            self.act(action="delete_file", name="new-one", file_path="nope.txt"),
            self.act(action="delete_file", name="new-one", file_path="a/b.txt"),
            self.act(action="delete", name="new-one"),
            self.act(action="delete", name="new-one"),
            description_warning("x" * 2000),
        ]
        (self.tree / "Old Name" / "blob.bin").write_bytes(b"\x00")
        replies.append(self.act(action="read_file", name="Old Name", file_path="blob.bin"))
        self.store.skills["in-memory"] = {"content": "c", "mode": "enabled"}
        replies.append(self.act(action="list_files", name="in-memory"))
        replies.append(self.act(action="read_file", name="in-memory", file_path="a.txt"))
        replies.extend(self.store.apply_instruction_modes({"Old Name": "enabled"}))
        self.assertEqual(len(replies), 36)
        for reply in replies:
            self.assertTrue(reply, "an empty reply")
            self.assertTrue(reply.isascii(), reply)


# ---- deleting ----


class DeleteTests(TreeCase):

    def test_delete_of_an_unknown_skill_touches_nothing(self):
        self.put("alpha")  # on disk, but never loaded into this store
        self.assertIs(self.store.delete("alpha"), False)
        self.assertTrue(self.md_path("alpha").is_file())

    def test_delete_removes_the_entry_and_the_folder(self):
        self.put("gone")
        (self.tree / "gone" / "helper.sh").write_bytes(b"echo hi")
        self.put("stays")
        self.store.load()
        self.assertIs(self.store.delete("gone"), True)
        self.assertEqual(list(self.store.skills), ["stays"])
        self.assertEqual(os.listdir(self.tree), ["stays"])

    def test_delete_goes_by_the_name_in_the_header_not_the_folder(self):
        self.write_md("weird_folder", serialize_skill_md("True Name",
                                                         {"content": "x", "mode": "disabled"}))
        self.put("stays")
        self.store.load()
        self.assertEqual(self.act(action="delete", name="True Name"), "Skill 'True Name' deleted.")
        self.assertEqual(os.listdir(self.tree), ["stays"])

    def test_delete_removes_every_folder_that_claims_the_name(self):
        self.write_md("A", serialize_skill_md("Same", {"content": "one", "mode": "disabled"}))
        self.write_md("B", serialize_skill_md("Same", {"content": "two", "mode": "disabled"}))
        self.put("stays")
        self.store.load()
        self.assertIs(self.store.delete("Same"), True)
        self.assertEqual(os.listdir(self.tree), ["stays"])
        self.assertEqual(list(self.reload().skills), ["stays"])

    def test_delete_leaves_a_folder_without_skill_md_alone(self):
        # Even one that carries the deleted skill's own folder name.
        self.write_md("elsewhere", serialize_skill_md("check-battery",
                                                      {"content": "x", "mode": "disabled"}))
        draft = self.tree / "check-battery"
        draft.mkdir()
        (draft / "notes.txt").write_bytes(b"notes")
        self.store.load()
        self.assertIs(self.store.delete("check-battery"), True)
        self.assertEqual(os.listdir(self.tree), ["check-battery"])
        self.assertEqual((draft / "notes.txt").read_bytes(), b"notes")

    def test_delete_copes_with_read_only_files_and_folders(self):
        self.put("locked")
        inner = self.tree / "locked" / "inner"
        inner.mkdir()
        for path in (self.tree / "locked" / "readonly.txt", inner / "deep.txt"):
            path.write_bytes(b"r")
            os.chmod(path, stat.S_IREAD)
        os.chmod(inner, stat.S_IREAD | stat.S_IEXEC)
        self.store.load()
        self.assertIs(self.store.delete("locked"), True)
        self.assertFalse((self.tree / "locked").exists())

    def test_a_folder_that_will_not_go_is_told(self):
        self.put("alpha")
        self.store.load()
        with mock.patch.object(skills.shutil, "rmtree", side_effect=OSError("held")), \
                mock.patch.object(skills.os, "rmdir", side_effect=OSError("held")), \
                mock.patch.object(skills.time, "sleep") as sleep:
            out = self.act(action="delete", name="alpha")
        self.assertEqual(out, "Error: Skill 'alpha' was removed from this session, but its "
                              "folder could not be deleted from disk. It may be back at the "
                              "next start.")
        self.assertEqual(sleep.call_count, 2)  # three attempts, a pause between them
        self.assertNotIn("alpha", self.store.skills)
        self.assertIn("alpha", self.reload().skills)

    def test_a_second_attempt_can_succeed(self):
        self.put("alpha")
        self.store.load()
        real_rmtree = skills.shutil.rmtree
        calls = []

        def rmtree(path):
            calls.append(path)
            if len(calls) == 1:
                raise OSError("held for a moment")
            real_rmtree(path)

        with mock.patch.object(skills.shutil, "rmtree", side_effect=rmtree), \
                mock.patch.object(skills.time, "sleep"):
            self.assertIs(self.store.delete("alpha"), True)
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.tree / "alpha").exists())

    def test_rights_are_never_changed_through_a_link(self):
        changed = []
        folder = str(self.tree / "alpha")
        link = os.path.join(folder, "link.txt")
        walk = [(folder, ["sub"], ["link.txt", "plain.txt"])]
        with mock.patch.object(skills.os, "walk", return_value=walk), \
                mock.patch.object(skills.os.path, "islink", side_effect=lambda p: p == link), \
                mock.patch.object(skills.os, "chmod",
                                  side_effect=lambda path, mode: changed.append(path)):
            skills._make_removable(folder)
        self.assertEqual(changed, [folder, os.path.join(folder, "sub"),
                                   os.path.join(folder, "plain.txt")])

    def test_delete_leaves_what_a_link_points_to_as_it_was(self):
        outside = self.tree.parent / "outside"
        outside.mkdir()
        target = outside / "keep.txt"
        target.write_bytes(b"keep")
        os.chmod(target, stat.S_IREAD)  # a change of rights through the link would show
        self.addCleanup(os.chmod, target, stat.S_IREAD | stat.S_IWRITE)
        self.put("alpha")
        try:
            os.symlink(target, self.tree / "alpha" / "link.txt")
            os.symlink(outside, self.tree / "alpha" / "linked-folder", target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"cannot make symbolic links here: {error}")
        before = (stat.S_IMODE(target.stat().st_mode), stat.S_IMODE(outside.stat().st_mode))
        self.store.load()
        self.assertIs(self.store.delete("alpha"), True)
        self.assertFalse((self.tree / "alpha").exists())
        self.assertEqual(target.read_bytes(), b"keep")
        self.assertEqual((stat.S_IMODE(target.stat().st_mode),
                          stat.S_IMODE(outside.stat().st_mode)), before)


# ---- the module itself ----


class ModuleTests(unittest.TestCase):

    def test_it_imports_the_standard_library_only(self):
        tree = ast.parse(Path(skills.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"json", "os", "pathlib", "re", "shutil", "stat",
                                    "tempfile", "time"})


if __name__ == "__main__":
    unittest.main()
