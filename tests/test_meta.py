"""The Meta tools: manage_instructions, manage_skills in a run, and upgrade_model."""

import json
import tempfile
import unittest

from robot import instructions, meta, spawn
from robot.agent import Agent
from robot.datastore import DataDir, StoreUnreadableError
from robot.instructions import RunSettings
from robot.meta import manage_instructions
from robot.skills import SkillStore
from robot.tools import available_tools
from tests.fakes import FakeClient, piped_console, reply, text_block, tool_use


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(self._tmp.name)
        self.datadir.ensure()
        self.running = RunSettings(name="Patrol", model="claude-haiku-5-5",
                                   thinking_mode="medium", thinking_budget=4096,
                                   fast_mode=False, blocked_tools=["web_search"])

    def call(self, **params):
        return manage_instructions(self.datadir, self.running, params)

    def entry(self, name):
        return instructions.load_instructions(self.datadir)[name]


class ManageInstructions(LibraryCase):
    def test_an_empty_library_says_so(self):
        self.assertEqual(self.call(action="list"), "No saved instructions.")

    def test_every_action_but_list_needs_a_name(self):
        for action in ("read", "create", "update", "delete"):
            self.assertEqual(self.call(action=action),
                             "Error: 'name' is required for this action.")

    def test_an_unknown_action_is_refused(self):
        self.assertEqual(self.call(action="rename", name="X"),
                         "Error: Unknown action 'rename'.")

    def test_create_takes_unnamed_model_settings_from_the_calling_run(self):
        reply_text = self.call(action="create", name="Check", text="Check the battery.")
        self.assertEqual(reply_text, "Instruction 'Check' created successfully.")
        entry = self.entry("Check")
        self.assertEqual(entry["text"], "Check the battery.")
        self.assertEqual(entry["provider"], "Anthropic")
        self.assertEqual(entry["model"], "claude-haiku-5-5")
        self.assertEqual(entry["thinking_mode"], "medium")
        self.assertEqual(entry["thinking_budget"], 4096)
        self.assertFalse(entry["fast_mode"])
        self.assertFalse(entry["meta"])
        self.assertFalse(entry["conversational"])
        self.assertEqual(entry["blocked_tools"], ["web_search"])
        self.assertEqual(entry["notes"], "")
        # No map of skill modes unless one was asked for.
        self.assertNotIn("skill_modes", entry)
        self.assertNotIn("upgrade_target", entry)

    def test_create_uses_the_settings_it_is_given(self):
        self.call(action="create", name="Deep", text="Think hard.", model="claude-opus-5-5",
                  thinking_mode="Max", meta=True, conversational=True, fast_mode=True,
                  notes="for hard problems", blocked_tools=["b", "a"],
                  skill_modes={"check-battery": "enabled"},
                  upgrade_target={"model": "claude-fable-5-2", "level": "Max"})
        entry = self.entry("Deep")
        self.assertEqual(entry["model"], "claude-opus-5-5")
        self.assertEqual(entry["thinking_mode"], "max")
        self.assertTrue(entry["meta"])
        self.assertTrue(entry["conversational"])
        self.assertTrue(entry["fast_mode"])
        self.assertEqual(entry["notes"], "for hard problems")
        self.assertEqual(entry["blocked_tools"], ["a", "b"])
        self.assertEqual(entry["skill_modes"], {"check-battery": "enabled"})
        self.assertEqual(entry["upgrade_target"],
                         {"model": "claude-fable-5-2", "level": "Max", "fast": False})

    def test_create_refuses_a_taken_name_or_missing_text(self):
        self.call(action="create", name="Check", text="x")
        self.assertEqual(self.call(action="create", name="Check", text="y"),
                         "Error: Instruction 'Check' already exists. Use 'update' to modify it.")
        self.assertEqual(self.call(action="create", name="Other"),
                         "Error: 'text' is required when creating an instruction.")

    def test_a_level_the_model_lacks_is_pointed_out(self):
        shown = self.call(action="create", name="Quiet", text="x", model="claude-opus-5-5",
                          thinking_mode="off")
        self.assertIn("created successfully", shown)
        self.assertIn("claude-opus-5-5 has no thinking level 'off'", shown)

    def test_values_of_the_wrong_kind_are_refused(self):
        cases = (dict(text=5), dict(text="x", meta="yes"), dict(text="x", thinking_budget=-1),
                 dict(text="x", thinking_mode="turbo"), dict(text="x", blocked_tools="web"),
                 dict(text="x", skill_modes={"a": "sometimes"}),
                 dict(text="x", upgrade_target="claude-fable-5-2"))
        for params in cases:
            shown = self.call(action="create", name="Bad", **params)
            self.assertTrue(shown.startswith("Error:"), (params, shown))
        self.assertEqual(instructions.load_instructions(self.datadir), {})

    def test_read_returns_the_entry_as_json(self):
        self.call(action="create", name="Check", text="Check the battery.", meta=True)
        shown = json.loads(self.call(action="read", name="Check"))
        self.assertEqual(shown["name"], "Check")
        self.assertEqual(shown["text"], "Check the battery.")
        self.assertTrue(shown["meta"])
        self.assertEqual(shown["model"], "claude-haiku-5-5")
        self.assertEqual(shown["thinking_mode"], "medium")
        self.assertEqual(shown["skill_modes"], {})
        self.assertEqual(shown["blocked_tools"], ["web_search"])
        self.assertIsNone(shown["upgrade_target"])
        self.assertEqual(self.call(action="read", name="Nope"),
                         "Error: Instruction 'Nope' not found.")

    def test_list_shows_each_instruction(self):
        self.call(action="create", name="Check", text="Check the battery.", meta=True)
        self.call(action="create", name="Alarm", text="Sound the alarm.", conversational=True)
        shown = self.call(action="list")
        self.assertEqual(shown, "- Alarm  [claude-haiku-5-5, Medium] [convo]\n"
                                "  Sound the alarm.\n"
                                "- Check  [claude-haiku-5-5, Medium] [meta]\n"
                                "  Check the battery.")

    def test_update_changes_only_what_it_is_given(self):
        self.call(action="create", name="Check", text="Check the battery.",
                  skill_modes={"a": "enabled"})
        shown = self.call(action="update", name="Check", thinking_mode="HIGH",
                          blocked_tools=["z", "y"], skill_modes={"b": "on_demand"},
                          upgrade_target={"model": ""})
        self.assertEqual(shown, "Instruction 'Check' updated successfully.")
        entry = self.entry("Check")
        self.assertEqual(entry["text"], "Check the battery.")
        self.assertEqual(entry["thinking_mode"], "high")
        self.assertEqual(entry["blocked_tools"], ["y", "z"])
        self.assertEqual(entry["skill_modes"], {"a": "enabled", "b": "on_demand"})
        self.assertEqual(entry["upgrade_target"], {"model": "", "level": "", "fast": False})

    def test_update_can_clear_notes_and_the_blocklist(self):
        self.call(action="create", name="Check", text="x", notes="old")
        self.call(action="update", name="Check", notes="", blocked_tools=[])
        self.assertEqual(self.entry("Check")["notes"], "")
        self.assertEqual(self.entry("Check")["blocked_tools"], [])

    def test_update_needs_something_to_change_and_an_existing_name(self):
        self.call(action="create", name="Check", text="x")
        shown = self.call(action="update", name="Check")
        self.assertTrue(shown.startswith("Error: At least one of 'text', 'notes'"))
        self.assertTrue(shown.endswith("must be provided for update."))
        self.assertEqual(self.call(action="update", name="Nope", text="y"),
                         "Error: Instruction 'Nope' not found. Use 'create' to add it.")

    def test_updating_the_running_instruction_says_when_it_takes_effect(self):
        self.call(action="create", name="Patrol", text="Walk.")
        self.assertEqual(self.call(action="update", name="Patrol", text="Run."),
                         "Instruction 'Patrol' updated on disk. Changes will take effect "
                         "next time it is loaded.")

    def test_a_plain_chat_counts_as_running_the_default(self):
        instructions.ensure_default(self.datadir)
        self.running = RunSettings(name="")
        shown = self.call(action="update", name="Default", model="claude-haiku-5-5")
        self.assertIn("take effect next time it is loaded", shown)
        self.assertEqual(self.entry("Default")["model"], "claude-haiku-5-5")

    def test_delete_removes_the_entry(self):
        self.call(action="create", name="Check", text="x")
        self.assertEqual(self.call(action="delete", name="Check"),
                         "Instruction 'Check' deleted.")
        self.assertEqual(self.call(action="delete", name="Check"),
                         "Error: Instruction 'Check' not found.")
        instructions.ensure_default(self.datadir)
        self.assertIn("re-created with built-in settings",
                      self.call(action="delete", name="Default"))

    def test_keys_of_other_programs_survive_an_update(self):
        instructions.save_instructions(self.datadir, {
            "Mail": {"text": "Check mail", "desktop": True, "section": "Daily"}})
        self.call(action="update", name="Mail", notes="copied from the laptop")
        self.assertEqual(self.entry("Mail"), {"text": "Check mail", "desktop": True,
                                              "section": "Daily",
                                              "notes": "copied from the laptop"})

    def test_an_unreadable_library_is_not_overwritten(self):
        self.datadir.instructions_file.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(StoreUnreadableError):
            self.call(action="create", name="New", text="x")
        self.assertEqual(self.datadir.instructions_file.read_text(encoding="utf-8"),
                         "{ broken")


class MetaInARun(unittest.TestCase):
    """The Meta tools as a run sees them, with a scripted model."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(self._tmp.name)
        self.datadir.ensure()

    def make(self, script, **settings):
        self.console, self.out = piped_console("")
        self.client = FakeClient(script)
        settings.setdefault("text", "do the task")
        settings.setdefault("meta", True)
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        return Agent(settings=RunSettings(**settings), console=self.console,
                     datadir=self.datadir, get_client=lambda: self.client, skills=store)

    def tool_names(self, request):
        machine = set(available_tools())
        return [tool["name"] for tool in request["tools"] if tool["name"] not in machine]

    def test_meta_on_offers_the_four_tools(self):
        made = self.make([reply(text_block("ok"))])
        made.run()
        self.assertEqual(self.tool_names(self.client.requests[0]),
                         ["user_prompt", "manage_instructions", "manage_skills",
                          "run_instruction", "upgrade_model", "web_search"])

    def test_meta_off_offers_none_of_them(self):
        made = self.make([reply(text_block("ok"))], meta=False)
        made.run()
        self.assertEqual(self.tool_names(self.client.requests[0]),
                         ["user_prompt", "web_search"])

    def test_only_a_run_that_can_upgrade_is_told_about_upgrading(self):
        made = self.make([reply(text_block("ok"))])
        made.run()
        self.assertIn("If you have used the upgrade_model tool",
                      " ".join(self.client.requests[0]["system"][1]["text"].split()))
        made = self.make([reply(text_block("ok"))], meta=False)
        made.run()
        self.assertNotIn("upgrade_model", self.client.requests[0]["system"][1]["text"])
        made = self.make([reply(text_block("ok"))], blocked_tools=["upgrade_model"])
        made.run()
        self.assertNotIn("upgrade_model", self.client.requests[0]["system"][1]["text"])

    def test_the_model_can_create_an_instruction_and_a_skill(self):
        script = [
            reply(tool_use("manage_instructions",
                           {"action": "create", "name": "Night watch",
                            "text": "Report the temperature every hour."}, "i"),
                  tool_use("manage_skills",
                           {"action": "create", "name": "check-battery",
                            "content": "Read the voltage.", "mode": "on_demand",
                            "description": "Reads the battery."}, "s")),
            reply(text_block("Both saved.")),
        ]
        made = self.make(script, model="claude-haiku-5-5")
        self.assertEqual(made.run(), "completed")
        results = made.messages[2]["content"]
        self.assertEqual(results[0]["content"], "Instruction 'Night watch' created successfully.")
        self.assertEqual(results[1]["content"], "Skill 'check-battery' created successfully.")
        saved = instructions.load_instructions(self.datadir)["Night watch"]
        self.assertEqual(saved["model"], "claude-haiku-5-5")
        self.assertTrue((self.datadir.skills_dir / "check-battery" / "SKILL.md").exists())
        # This run's own tools and prompt did not change when the skill appeared.
        first, second = self.client.requests
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(first["system"], second["system"])

    def test_upgrade_moves_the_rest_of_the_run_to_the_stronger_model(self):
        script = [reply(tool_use("upgrade_model", {}, "u")),
                  reply(text_block("Thinking harder."), model="claude-fable-5-2")]
        made = self.make(script, name="Hard")
        self.assertEqual(made.run(), "completed")
        first, second = self.client.requests
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["output_config"], {"effort": "low"})
        self.assertEqual(second["model"], "claude-fable-5-2")
        self.assertEqual(second["output_config"], {"effort": "max"})
        self.assertEqual(first["tools"], second["tools"])
        # The prompt is fixed for the run: it still names the starting model,
        # and tells the model to trust the tool's result over it.
        self.assertEqual(first["system"], second["system"])
        facts = " ".join(second["system"][1]["text"].split())
        self.assertIn('the saved instruction named "Hard", on the model claude-opus-5-5.', facts)
        self.assertIn("you are now on the model its result named instead", facts)
        result = made.messages[2]["content"][0]["content"]
        self.assertEqual(result, "Upgraded: claude-opus-5-5 -> claude-fable-5-2 (Max) for the "
                                 "rest of this run, from your next call on. The saved "
                                 "instruction is unchanged.")
        self.assertIn("Model upgraded for the rest of this run: claude-opus-5-5 -> "
                      "claude-fable-5-2 (Max), from call #2 on.", self.out.getvalue())
        # The run's own settings are untouched; only the live model moved.
        self.assertEqual(made.settings.model, "claude-opus-5-5")
        fields = self.datadir.costlog_file.read_text(encoding="utf-8").strip().split(";")
        self.assertEqual(fields[2], "claude-fable-5-2")
        self.assertEqual(fields[4], "mode=Max, upgraded-from=claude-opus-5-5@call1")
        self.assertIn("claude-opus-5-5,", fields[12])
        self.assertIn("|claude-fable-5-2,", fields[12])

    def test_a_run_upgrades_only_once(self):
        script = [reply(tool_use("upgrade_model", {}, "a")),
                  reply(tool_use("upgrade_model", {}, "b")), reply(text_block("ok"))]
        made = self.make(script)
        made.run()
        self.assertEqual(made.messages[4]["content"][0]["content"],
                         "Nothing changed - this run was already upgraded to claude-fable-5-2.")

    def test_an_instructions_own_target_is_used(self):
        script = [reply(tool_use("upgrade_model", {}, "u")), reply(text_block("ok"))]
        made = self.make(script, model="claude-haiku-5-5",
                         upgrade_target={"model": "claude-sonnet-5-5", "level": "High",
                                         "fast": False})
        made.run()
        self.assertEqual(self.client.requests[1]["model"], "claude-sonnet-5-5")
        self.assertEqual(self.client.requests[1]["output_config"], {"effort": "high"})

    def test_no_target_or_the_same_model_changes_nothing(self):
        script = [reply(tool_use("upgrade_model", {}, "u")), reply(text_block("ok"))]
        made = self.make(script, upgrade_target={"model": "", "level": "", "fast": False})
        made.run()
        self.assertEqual(made.messages[2]["content"][0]["content"],
                         "Nothing changed - no upgrade model is set for this instruction.")
        self.assertEqual(self.client.requests[1]["model"], "claude-opus-5-5")

        script = [reply(tool_use("upgrade_model", {}, "u")), reply(text_block("ok"))]
        made = self.make(script, model="claude-fable-5-2")
        made.run()
        self.assertEqual(made.messages[2]["content"][0]["content"],
                         "Nothing changed - this run is already on claude-fable-5-2.")

    def test_the_model_is_told_what_limits_child_runs(self):
        # The description is what the model plans by. It names the ceiling
        # that spawn enforces, taken from the same number.
        described = meta.RUN_INSTRUCTION_TOOL["description"]
        self.assertEqual(spawn.MAX_CHILDREN, 8)
        self.assertIn("depends on how much memory is free, and is never more than 8.",
                      described)
        self.assertNotIn("at most two", described)

    def test_the_tool_schemas_are_well_formed(self):
        for tool in (meta.MANAGE_INSTRUCTIONS_TOOL, meta.MANAGE_SKILLS_TOOL,
                     meta.RUN_INSTRUCTION_TOOL, meta.UPGRADE_MODEL_TOOL):
            self.assertEqual(tool["input_schema"]["type"], "object")
            self.assertTrue(tool["description"].isascii(), tool["name"])
            json.dumps(tool)


if __name__ == "__main__":
    unittest.main()
