"""The command line: choosing a run's settings, the listings, and failing to start."""

import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import instructions, main
from robot.datastore import DataDir
from robot.skills import SkillStore, manage_skills
from tests.fakes import piped_console


class MainCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "data"
        self.datadir = DataDir(self.root)
        self.datadir.ensure()
        self.console, self.out = piped_console("")
        # main() installs signal handlers; put the test runner's own back.
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            if hasattr(signal, name):
                number = getattr(signal, name)
                self.addCleanup(signal.signal, number, signal.getsignal(number))

    def args(self, *argv):
        return main.build_parser().parse_args(list(argv))

    def save(self, **entries):
        library = instructions.ensure_default(self.datadir)
        library.update(entries)
        instructions.save_instructions(self.datadir, library)
        return library

    def run_main(self, *argv, stdin="", env=None):
        """Run main() with its own stdin, stdout and data folder."""
        out = io.StringIO()
        environment = {"ROBOT_DATA_DIR": str(self.root)}
        environment.update(env or {})
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out):
            code = main.main(list(argv))
        return code, out.getvalue()


class ChoosingSettings(MainCase):
    def test_a_chat_without_a_name_borrows_the_default_settings(self):
        library = self.save()
        library["Default"]["model"] = "claude-haiku-5-5"
        library["Default"]["text"] = "ignored for a typed chat"
        settings = main.resolve_settings(self.args(), library, self.console)
        self.assertEqual(settings.name, "")
        self.assertEqual(settings.text, "")
        self.assertEqual(settings.model, "claude-haiku-5-5")
        self.assertTrue(settings.conversational)
        self.assertTrue(settings.meta)

    def test_a_named_instruction_supplies_text_and_settings(self):
        library = self.save(Patrol={"text": "Walk the hall.", "model": "claude-haiku-5-5",
                                    "thinking_mode": "low"})
        settings = main.resolve_settings(self.args("-l", "Patrol"), library, self.console)
        self.assertEqual(settings.name, "Patrol")
        self.assertEqual(settings.text, "Walk the hall.")
        self.assertFalse(settings.conversational)

    def test_an_unknown_name_cannot_start_and_lists_what_exists(self):
        library = self.save(Patrol={"text": "Walk."})
        with self.assertRaises(main.CannotStart) as caught:
            main.resolve_settings(self.args("-l", "Petrol"), library, self.console)
        self.assertIn("No saved instruction named 'Petrol'", str(caught.exception))
        self.assertIn("Default, Patrol", str(caught.exception))

    def test_an_empty_library_still_gives_built_in_settings(self):
        settings = main.resolve_settings(self.args(), {}, self.console)
        self.assertEqual(settings.model, "claude-opus-5-5")
        self.assertEqual(settings.thinking_mode, "low")

    def test_model_and_mode_options_override_the_run_only(self):
        library = self.save()
        settings = main.resolve_settings(self.args(), library, self.console)
        main.apply_overrides(settings, self.args("--model", "claude-haiku-5-5",
                                                 "--mode", "medium"), self.console)
        self.assertEqual(settings.model, "claude-haiku-5-5")
        self.assertEqual(settings.thinking_mode, "medium")
        self.assertEqual(instructions.load_instructions(self.datadir)["Default"]["model"],
                         "claude-opus-5-5")

    def test_settings_warnings_are_shown(self):
        library = self.save(Odd={"text": "x", "model": "claude-sonnet-5-5", "fast_mode": True})
        main.resolve_settings(self.args("-l", "Odd"), library, self.console)
        self.assertIn("warning: claude-sonnet-5-5 has no fast mode", self.out.getvalue())


class SkillsAndTools(MainCase):
    def skills(self):
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        manage_skills(store, {"action": "create", "name": "check-battery",
                              "content": "Read the voltage.", "mode": "enabled",
                              "description": "Reads the battery."})
        manage_skills(store, {"action": "create", "name": "tidy-logs",
                              "content": "Delete old logs.", "mode": "on_demand",
                              "description": "Clears old log files."})
        manage_skills(store, {"action": "create", "name": "unused", "content": "Nothing."})
        return store

    def test_the_banner_names_the_skills_in_use(self):
        self.skills()
        settings = instructions.RunSettings(conversational=True)
        store = main.load_skills(self.datadir, settings, self.console)
        main.show_banner(self.console, settings, store)
        shown = self.out.getvalue()
        self.assertIn("Robot agent: chat. Conversation on claude-opus-5-5 (Low).", shown)
        self.assertIn("Skills: enabled: check-battery; on demand: tidy-logs", shown)
        self.assertNotIn("unused", shown)
        self.assertIn("get_skill", shown)

    def test_an_instructions_skill_modes_apply_to_the_run_and_warn(self):
        self.skills()
        settings = instructions.RunSettings(skill_modes={"tidy-logs": "enabled"})
        store = main.load_skills(self.datadir, settings, self.console)
        self.assertEqual(store.skills["tidy-logs"]["mode"], "enabled")
        self.assertEqual(store.skills["check-battery"]["mode"], "disabled")
        self.assertIn("warning:", self.out.getvalue())
        self.assertIn("check-battery", self.out.getvalue())
        # Nothing on disk changed: a fresh load still sees the saved modes.
        fresh = SkillStore(self.datadir.skills_dir)
        fresh.load()
        self.assertEqual(fresh.skills["check-battery"]["mode"], "enabled")

    def test_offered_tools_follow_skills_and_the_blocklist(self):
        store = self.skills()
        settings = instructions.RunSettings()
        names = main.offered_tool_names(settings, store)
        self.assertEqual(names[-3:], ["user_prompt", "get_skill", "web_search"])
        settings.blocked_tools = ["web_search", "get_skill"]
        self.assertEqual(main.offered_tool_names(settings, store)[-1], "user_prompt")
        self.assertNotIn("get_skill", main.offered_tool_names(instructions.RunSettings(), None))


class Listings(MainCase):
    def test_list_shows_the_library_and_creates_the_default(self):
        code, shown = self.run_main("--list")
        self.assertEqual(code, 0)
        self.assertIn("- Default  [claude-opus-5-5, Low] [meta, convo]", shown)
        self.assertTrue(self.datadir.instructions_file.exists())

    def test_skills_listing(self):
        code, shown = self.run_main("--skills")
        self.assertEqual(code, 0)
        self.assertIn("(none yet", shown)
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        manage_skills(store, {"action": "create", "name": "check-battery", "content": "x",
                              "mode": "on_demand", "description": "Reads the battery."})
        code, shown = self.run_main("--skills")
        self.assertIn("- check-battery  [on_demand]\n  Reads the battery.", shown)


class AskingForTheTask(MainCase):
    def test_a_line_from_the_terminal_itself_is_not_taken_as_the_task(self):
        # What a terminal's answer to tmux left at the prompt on 2026-11-16,
        # followed by Enter. It was sent to the model as the first message.
        self.console.tty = True
        typed = ["11;rgb:0c0c/0c0c/0c0c", "how hot are you?"]
        with mock.patch("builtins.input", side_effect=typed):
            self.assertEqual(main.first_message(self.console), "how hot are you?")
        self.assertEqual(self.out.getvalue().count("(ignored: that line came from"), 1)

    def test_an_empty_line_at_a_terminal_means_no_task(self):
        self.console.tty = True
        with mock.patch("builtins.input", side_effect=["", "how hot are you?"]) as asked:
            self.assertEqual(main.first_message(self.console), "")
        self.assertEqual(asked.call_count, 1)


class StartingAndFailing(MainCase):
    def test_a_dry_run_prints_the_request_and_spends_nothing(self):
        code, shown = self.run_main("--dry-run", stdin="How hot are you?\n")
        self.assertEqual(code, 0)
        self.assertIn("you> How hot are you?", shown)
        self.assertIn('"model": "claude-opus-5-5"', shown)
        self.assertIn("This is a conversation", shown)
        self.assertIn("About this run: your chat terminal was started without a saved instruction.",
                      shown)
        self.assertEqual(list(self.datadir.chats_dir.glob("*")), [])

    def test_a_model_override_is_what_the_run_is_told(self):
        _, shown = self.run_main("--dry-run", "--model", "claude-haiku-5-5",
                                 stdin="How hot are you?\n")
        self.assertIn("It is running on the\\nmodel claude-haiku-5-5.", shown)

    def test_leaving_at_the_first_prompt_ends_quietly(self):
        code, shown = self.run_main("--dry-run", stdin="exit\n")
        self.assertEqual(code, 0)
        self.assertNotIn('"model"', shown)

    def test_a_named_instruction_runs_as_a_single_task(self):
        self.save(Patrol={"text": "Walk the hall.", "model": "claude-haiku-5-5"})
        code, shown = self.run_main("-l", "Patrol", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Robot agent: instruction 'Patrol'. Single task on claude-haiku-5-5", shown)
        self.assertIn("Walk the hall.", shown)
        self.assertIn("single task run", shown)
        self.assertIn("About this run: your chat terminal is running the saved instruction named", shown)
        self.assertIn('\\"Patrol\\"', shown)

    def test_prepend_and_extra_files_wrap_the_task(self):
        self.save(Patrol={"text": "Walk the hall."})
        before = Path(self._tmp.name) / "before.txt"
        after = Path(self._tmp.name) / "after.txt"
        before.write_text("Tonight only:", encoding="utf-8")
        after.write_text("Skip the kitchen.", encoding="utf-8")
        _, shown = self.run_main("-l", "Patrol", "--dry-run", "--prepend-file", str(before),
                                 "--extra-file", str(after))
        self.assertIn("Tonight only:\\n\\nWalk the hall.\\n\\n--- ADDITIONAL TASK CONTEXT", shown)
        self.assertIn("Skip the kitchen.", shown)

    def test_an_unknown_instruction_fails_and_tells_a_waiting_parent(self):
        result = Path(self._tmp.name) / "result.json"
        code, shown = self.run_main("-l", "Missing", "--headless", "--result-file", str(result))
        self.assertEqual(code, 2)
        self.assertIn("error: No saved instruction named 'Missing'", shown)
        saved = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["instruction"], "Missing")
        self.assertIn("No saved instruction", saved["error"])

    def test_an_unattended_run_of_an_instruction_without_text_cannot_start(self):
        self.save(Blank={"text": "   "})
        code, shown = self.run_main("-l", "Blank", "--headless", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("has no text", shown)

    def test_without_a_key_a_real_run_cannot_start(self):
        with mock.patch.object(main, "load_dotenv", lambda *args, **kwargs: None):
            code, shown = self.run_main(stdin="hello\n", env={"ANTHROPIC_API_KEY": ""})
        self.assertEqual(code, 2)
        self.assertIn("No ANTHROPIC_API_KEY found", shown)


if __name__ == "__main__":
    unittest.main()
