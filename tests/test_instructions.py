"""The instruction library and the settings a run takes from an entry."""

import json
import tempfile
import unittest

from robot import instructions
from robot.datastore import DataDir, StoreUnreadableError
from robot.instructions import (DEFAULT_NAME, InstructionError, describe, ensure_default,
                                load_instructions, merge_extra_text, merge_prepend_text,
                                save_instructions, settings_from_entry)


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(self._tmp.name)
        self.datadir.ensure()
        self.path = self.datadir.instructions_file


class Library(LibraryCase):
    def test_loading_a_missing_library_creates_nothing(self):
        self.assertEqual(load_instructions(self.datadir), {})
        self.assertFalse(self.path.exists())

    def test_the_default_entry_is_created_once(self):
        library = ensure_default(self.datadir)
        self.assertEqual(list(library), [DEFAULT_NAME])
        entry = library[DEFAULT_NAME]
        self.assertEqual(entry["model"], "claude-opus-5-5")
        self.assertEqual(entry["thinking_mode"], "low")
        self.assertTrue(entry["meta"])
        self.assertTrue(entry["conversational"])
        self.assertEqual(entry["provider"], "Anthropic")
        # No snapshot of skill modes: one would switch off every later skill.
        self.assertNotIn("skill_modes", entry)
        first = self.path.read_text(encoding="utf-8")
        ensure_default(self.datadir)
        self.assertEqual(self.path.read_text(encoding="utf-8"), first)

    def test_an_edited_default_is_left_alone(self):
        ensure_default(self.datadir)
        library = load_instructions(self.datadir)
        library[DEFAULT_NAME]["model"] = "claude-haiku-5-5"
        save_instructions(self.datadir, library)
        self.assertEqual(ensure_default(self.datadir)[DEFAULT_NAME]["model"], "claude-haiku-5-5")

    def test_other_entries_survive_the_default_being_added(self):
        self.path.write_text(json.dumps({"Patrol": {"text": "Walk the hall."}}), encoding="utf-8")
        library = ensure_default(self.datadir)
        self.assertEqual(sorted(library), [DEFAULT_NAME, "Patrol"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["Patrol"],
                         {"text": "Walk the hall."})

    def test_an_entry_that_is_only_text_is_read_as_one(self):
        self.path.write_text(json.dumps({"Old": "Just the text", "Bad": 7}), encoding="utf-8")
        self.assertEqual(load_instructions(self.datadir), {"Old": {"text": "Just the text"}})

    def test_an_unreadable_library_is_never_overwritten(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        with self.assertRaises(StoreUnreadableError):
            save_instructions(self.datadir, {"New": {"text": "x"}})
        with self.assertRaises(StoreUnreadableError):
            ensure_default(self.datadir)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ this is not json")

    def test_keys_this_program_does_not_use_are_kept_on_a_round_trip(self):
        entry = {"text": "Check mail", "desktop": True, "section": "Daily", "order": 3,
                 "disabled_confirm_patterns": ["rm"], "images": []}
        save_instructions(self.datadir, {"Mail": entry})
        self.assertEqual(load_instructions(self.datadir)["Mail"], entry)


class Settings(unittest.TestCase):
    def test_a_full_entry(self):
        entry = {"text": "Report the temperature.", "model": "claude-haiku-5-5",
                 "thinking_mode": "Medium", "fast_mode": False, "meta": True,
                 "conversational": True, "blocked_tools": ["web_search", "get_skill", "web_search"],
                 "skill_modes": {"check-battery": "enabled"}, "thinking_budget": 4096}
        settings, warnings = settings_from_entry("Temp", entry)
        self.assertEqual(warnings, [])
        self.assertEqual(settings.name, "Temp")
        self.assertEqual(settings.text, "Report the temperature.")
        self.assertEqual(settings.model, "claude-haiku-5-5")
        self.assertEqual(settings.thinking_mode, "medium")
        self.assertEqual(settings.thinking_budget, 4096)
        self.assertTrue(settings.meta)
        self.assertTrue(settings.conversational)
        self.assertEqual(settings.blocked_tools, ["get_skill", "web_search"])
        self.assertEqual(settings.skill_modes, {"check-battery": "enabled"})
        self.assertIsNone(settings.upgrade_target)

    def test_a_bare_entry_gets_the_defaults(self):
        settings, warnings = settings_from_entry("Bare", {"text": "Go."})
        self.assertEqual(settings.model, "claude-opus-5-5")
        self.assertFalse(settings.meta)
        self.assertFalse(settings.conversational)
        self.assertFalse(settings.fast_mode)
        self.assertEqual(settings.blocked_tools, [])
        self.assertEqual(settings.skill_modes, {})
        self.assertEqual(settings.thinking_budget, 8192)
        self.assertEqual(warnings, [])

    def test_another_providers_instruction_is_refused(self):
        with self.assertRaises(InstructionError) as caught:
            settings_from_entry("Mail", {"text": "x", "provider": "OpenAI", "model": "gpt-6"})
        self.assertIn("Anthropic models only", str(caught.exception))

    def test_a_level_the_model_lacks_is_corrected_with_a_warning(self):
        settings, warnings = settings_from_entry(
            "Deep", {"text": "x", "model": "claude-sonnet-4-6", "thinking_mode": "xhigh"})
        self.assertIn(settings.thinking_mode, ("high", "max"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("xhigh", warnings[0])

    def test_off_on_an_always_on_model_becomes_a_level_it_has(self):
        settings, warnings = settings_from_entry(
            "Quiet", {"text": "x", "model": "claude-opus-5-5", "thinking_mode": "off"})
        self.assertNotEqual(settings.thinking_mode, "off")
        self.assertEqual(len(warnings), 1)

    def test_an_old_entry_without_a_mode_uses_its_enabled_and_effort_fields(self):
        settings, _ = settings_from_entry(
            "Old", {"text": "x", "model": "claude-opus-5", "thinking_enabled": True,
                    "thinking_effort": "high"})
        self.assertEqual(settings.thinking_mode, "high")
        settings, _ = settings_from_entry(
            "Old", {"text": "x", "model": "claude-opus-5", "thinking_enabled": False,
                    "thinking_effort": "high"})
        self.assertEqual(settings.thinking_mode, "off")

    def test_a_budget_model_follows_its_on_off_switch(self):
        settings, _ = settings_from_entry(
            "Small", {"text": "x", "model": "claude-haiku-4-5-20251001",
                      "thinking_enabled": False, "thinking_mode": "high"})
        self.assertEqual(settings.thinking_mode, "off")

    def test_fast_mode_on_a_model_without_it_warns(self):
        settings, warnings = settings_from_entry(
            "Quick", {"text": "x", "model": "claude-sonnet-5-5", "fast_mode": True})
        self.assertTrue(any("no fast mode" in warning for warning in warnings))

    def test_bad_values_fall_back_quietly(self):
        settings, _ = settings_from_entry(
            "Odd", {"text": None, "thinking_budget": "lots", "blocked_tools": "web_search",
                    "skill_modes": ["a"], "upgrade_target": "claude-fable-5-2"})
        self.assertEqual(settings.text, "")
        self.assertEqual(settings.thinking_budget, 8192)
        self.assertEqual(settings.blocked_tools, [])
        self.assertEqual(settings.skill_modes, {})

    def test_an_upgrade_target_is_cleaned_up(self):
        settings, _ = settings_from_entry(
            "Up", {"text": "x", "upgrade_target": {"provider": "Anthropic",
                                                    "model": "claude-fable-5-2",
                                                    "level": "Max", "fast": False}})
        self.assertEqual(settings.upgrade_target["model"], "claude-fable-5-2")
        self.assertEqual(settings.upgrade_target["level"], "Max")


class Describing(unittest.TestCase):
    def test_a_listing_line_names_model_level_and_flags(self):
        shown = describe("Patrol", {"text": "Walk the hall and report.", "meta": True,
                                    "conversational": True, "model": "claude-haiku-5-5",
                                    "thinking_mode": "low"})
        self.assertEqual(shown, "- Patrol  [claude-haiku-5-5, Low] [meta, convo]\n"
                                "  Walk the hall and report.")

    def test_long_text_is_cut_and_an_empty_task_is_explained(self):
        shown = describe("Long", {"text": "word " * 60})
        self.assertTrue(shown.endswith("..."))
        self.assertLessEqual(len(shown.splitlines()[1]), 110)
        self.assertIn("no task text", describe("Empty", {"text": ""}))

    def test_an_entry_for_another_provider_says_so(self):
        self.assertIn("cannot be run here", describe("Mail", {"text": "x", "provider": "Google"}))


class PerRunTexts(unittest.TestCase):
    def test_prepend_goes_in_front_and_extra_goes_after_under_a_heading(self):
        self.assertEqual(merge_prepend_text("task", "first"), "first\n\ntask")
        self.assertEqual(merge_extra_text("task", "more"),
                         f"task\n\n{instructions.EXTRA_TEXT_HEADING}\nmore")

    def test_empty_additions_change_nothing(self):
        self.assertEqual(merge_prepend_text("task", ""), "task")
        self.assertEqual(merge_extra_text("task", ""), "task")


if __name__ == "__main__":
    unittest.main()
