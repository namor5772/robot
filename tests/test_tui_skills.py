"""The Skills Manager, driven through the main window as a person would."""

import unittest

from robot.skills import SkillStore, manage_skills, parse_skill_md
from tests.tui_fakes import AppCase, Check, typed


class SkillsCase(AppCase):
    """F5 opens the manager. The list holds identity (ON), monitor (OD) and spare (off)."""

    def setUp(self):
        super().setUp()
        store = self.store()
        for name, mode, description in (
                ("identity", "enabled", "Who the robot is."),
                ("monitor", "on_demand", "How the monitor works."),
                ("spare", "disabled", "")):
            reply = manage_skills(store, {
                "action": "create", "name": name, "mode": mode, "description": description,
                "content": f"Text of {name}."})
            self.assertIn("created", reply)

    def store(self):
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        return store

    def on_disk(self, name):
        """(entry, raw text) of a skill's SKILL.md."""
        folder = self.store().folder(name)
        raw = (folder / "SKILL.md").read_text(encoding="utf-8")
        return parse_skill_md(raw, name)[1], raw

    def manager(self, *script):
        return self.drive("f5", *script)

    def shows(self, *texts):
        def check(screen):
            for text in texts:
                self.assertIsNotNone(screen.find(text), f"{text!r} is not on screen:\n"
                                     + screen.text())
        return Check(check)

    def lacks(self, *texts):
        def check(screen):
            for text in texts:
                self.assertIsNone(screen.find(text), f"{text!r} is on screen:\n" + screen.text())
        return Check(check)


class Looking(SkillsCase):
    def test_the_list_shows_each_skill_with_its_mode(self):
        self.manager(self.shows(
            "Skills Manager: identity", "[ON] identity", "[OD] monitor", "[  ] spare",
            "Name: identity", "Mode: ON (its text is in every run's prompt)",
            "Description: Who the robot is.", "Bundled files: none", "Text of identity."))

    def test_moving_through_the_list_shows_each_skill(self):
        self.manager("down", self.shows("Name: monitor", "Mode: OD (on demand",
                                        "Text of monitor."),
                     "down", self.shows("Name: spare", "Mode: off", "Description: (none)"))

    def test_a_letter_jumps_to_a_skill(self):
        self.manager("s", self.shows("Name: spare"))

    def test_no_skills_at_all(self):
        store = self.store()
        for name in list(store.skills):
            manage_skills(store, {"action": "delete", "name": name})
        self.manager(self.shows("Skills Manager: new skill", "Mode: off"), "down", " ", "esc")


class Saving(SkillsCase):
    def test_a_changed_text_is_saved_and_the_mode_stays(self):
        self.manager("down", "alt+x", "ctrl+end", typed(" More."),
                     self.shows("Skills Manager: monitor (changed)"), "alt+s",
                     self.shows("Skill 'monitor' updated successfully."),
                     self.lacks("(changed)"))
        entry, _raw = self.on_disk("monitor")
        self.assertEqual(entry["content"], "Text of monitor. More.")
        self.assertEqual(entry["mode"], "on_demand")
        self.assertEqual(entry["description"], "How the monitor works.")

    def test_the_other_skills_are_not_rewritten(self):
        before = self.on_disk("identity")[1]
        self.manager("down", "alt+x", typed("x"), "alt+s")
        self.assertEqual(self.on_disk("identity")[1], before)

    def test_the_description(self):
        self.manager("alt+e", self.shows("Description", "Who the robot is."), "ctrl+end",
                     typed(" In\nshort."), "alt+o",
                     self.shows("Description: Who the robot is. In short."), "alt+s")
        self.assertEqual(self.on_disk("identity")[0]["description"],
                         "Who the robot is. In short.")

    def test_an_emptied_description_is_removed(self):
        self.manager("alt+e", "ctrl+home", *["delete"] * 30, "alt+o",
                     self.shows("Description: (none)"), "alt+s")
        entry, raw = self.on_disk("identity")
        self.assertNotIn("description", entry)
        self.assertNotIn("description:", raw)

    def test_a_new_skill(self):
        self.manager("alt+w", self.shows("Skills Manager: new skill"), typed("check-battery"),
                     "alt+x", typed("Read the voltage."), "alt+s",
                     self.shows("Skill 'check-battery' created successfully.",
                                "[  ] check-battery", "Skills Manager: check-battery"))
        entry, _raw = self.on_disk("check-battery")
        self.assertEqual((entry["content"], entry["mode"]), ("Read the voltage.", "disabled"))

    def test_a_new_skill_can_be_given_its_mode_before_it_is_saved(self):
        self.manager("alt+w", typed("on-request"), "alt+c", "alt+c",
                     self.shows("Mode: OD"), "alt+x", typed("Text."), "alt+s",
                     self.shows("[OD] on-request"))
        self.assertEqual(self.on_disk("on-request")[0]["mode"], "on_demand")
        self.assertEqual(len(self.store().skills), 4)

    def test_a_name_that_is_not_allowed_is_explained(self):
        self.manager("alt+w", typed("Check Battery"), "alt+x", typed("Text."), "alt+s",
                     self.shows("kebab-case", "'check-battery'."), "enter",
                     self.shows("Name: Check Battery"))
        self.assertEqual(len(self.store().skills), 3)

    def test_a_skill_needs_a_name_and_a_text(self):
        self.manager("alt+w", "alt+s", self.shows("Give the skill a name first."), "enter",
                     typed("empty-one"), "alt+s",
                     self.shows("'content' is required when creating a skill."), "enter")
        self.assertEqual(len(self.store().skills), 3)

    def test_another_name_makes_a_copy(self):
        self.manager("alt+n", typed("-two"), "alt+s", self.shows("[ON] identity",
                                                                 "identity-two"))
        self.assertEqual(self.on_disk("identity-two")[0]["content"], "Text of identity.")
        self.assertEqual(self.on_disk("identity")[0]["content"], "Text of identity.")

    def test_saving_over_another_skill_asks_first(self):
        over = ["alt+n", "ctrl+u", typed("spare"), "alt+s"]
        self.manager(*over, self.shows("A skill named 'spare' already exists."), "n")
        self.assertEqual(self.on_disk("spare")[0]["content"], "Text of spare.")
        self.manager(*over, "y", self.shows("Skills Manager: spare"))
        entry, _raw = self.on_disk("spare")
        self.assertEqual(entry["content"], "Text of identity.")
        self.assertEqual(entry["mode"], "disabled")            # the mode it had is kept


class Modes(SkillsCase):
    def test_space_on_the_list_switches_the_mode_at_once(self):
        self.manager("down", "down", " ", self.shows("[ON] spare", "Mode: ON",
                                                     "'spare' is now ON."))
        self.assertEqual(self.on_disk("spare")[0]["mode"], "enabled")

    def test_the_modes_go_round(self):
        seen = []
        note = Check(lambda screen: seen.append(self.on_disk("identity")[0]["mode"]))
        self.manager(note, "alt+c", note, "alt+c", note, "alt+c", note)
        self.assertEqual(seen, ["enabled", "on_demand", "disabled", "enabled"])

    def test_switching_the_mode_leaves_unsaved_text_alone(self):
        self.manager("alt+x", typed("Draft: "), "alt+c",
                     self.shows("Draft: Text of identity.", "(changed)", "[OD] identity"))
        entry, _raw = self.on_disk("identity")
        self.assertEqual(entry["mode"], "on_demand")
        self.assertEqual(entry["content"], "Text of identity.")   # the draft was not written

    def test_a_text_changed_by_a_run_meanwhile_is_not_written_over(self):
        def a_run_rewrites_the_skill(screen):
            manage_skills(self.store(), {"action": "update", "name": "identity",
                                         "content": "Rewritten by a run."})

        self.manager(Check(a_run_rewrites_the_skill), "alt+c")
        entry, _raw = self.on_disk("identity")
        self.assertEqual(entry["content"], "Rewritten by a run.")
        self.assertEqual(entry["mode"], "on_demand")


class UnsavedChanges(SkillsCase):
    def test_moving_on_asks(self):
        self.manager("alt+x", typed("x"), "alt+k", "down",
                     self.shows("Leave this skill without saving your changes?"), "n",
                     self.shows("Name: identity"), "down", "y", self.shows("Name: monitor"))
        self.assertEqual(self.on_disk("identity")[0]["content"], "Text of identity.")

    def test_closing_asks(self):
        self.manager("alt+x", typed("x"), "esc",
                     self.shows("Close the Skills Manager without saving your changes?"), "n",
                     self.shows("Skills Manager: identity (changed)"), "esc", "y",
                     self.lacks("Skills Manager"))

    def test_nothing_changed_means_no_question(self):
        self.manager("down", "up", "alt+e", "esc", "esc", self.lacks("Skills Manager"))


class Deleting(SkillsCase):
    def test_delete_asks_first(self):
        self.manager("down", "alt+d", self.shows("Delete the skill 'monitor'?"), "n")
        self.assertIn("monitor", self.store().skills)
        self.manager("down", "alt+d", "y", self.shows("Skill 'monitor' deleted."),
                     self.lacks("[OD] monitor"))
        self.assertEqual(sorted(self.store().skills), ["identity", "spare"])
        self.assertIsNone(self.store().folder("monitor"))

    def test_an_unsaved_skill_has_nothing_to_delete(self):
        self.manager("alt+w", "alt+d", self.shows("nothing to delete"), "enter")
        self.assertEqual(len(self.store().skills), 3)


class BundledFiles(SkillsCase):
    def setUp(self):
        super().setUp()
        store = self.store()
        for path, content in (("scripts/check.sh", "#!/bin/sh\necho checked\n"),
                              ("notes.txt", "Some notes.")):
            manage_skills(store, {"action": "write_file", "name": "monitor",
                                  "file_path": path, "file_content": content})

    def test_the_files_are_listed_and_can_be_read(self):
        self.manager("down", self.shows("Bundled files (2): notes.txt, scripts/check.sh"),
                     "alt+f", self.shows("Bundled files", "notes.txt  (11 bytes)",
                                         "scripts/check.sh"),
                     "down", "enter", self.shows("scripts/check.sh", "echo checked"),
                     "esc", "esc", self.shows("Skills Manager: monitor"))

    def test_a_skill_without_files_says_so(self):
        self.manager("alt+f", self.shows("This skill has no bundled files"), "enter")

    def test_deleting_warns_that_the_files_go_too(self):
        folder = self.store().folder("monitor")
        self.manager("down", "alt+d", self.shows("Its bundled files go with it."), "y")
        self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
