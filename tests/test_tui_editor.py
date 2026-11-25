"""The Instruction Editor, driven through the main window as a person would."""

import unittest

from robot import instructions, models
from robot.datastore import load_store
from robot.skills import SkillStore, manage_skills
from robot.tui.app import STATE_FILE
from tests.tui_fakes import AppCase, Check, typed

REPORT = {
    "text": "Report the temperature.", "notes": "", "provider": "Anthropic",
    "model": "claude-haiku-5-5", "thinking_mode": "low", "fast_mode": False, "meta": False,
    "conversational": False, "blocked_tools": [],
}


class EditorCase(AppCase):
    """F4 opens the editor. The list holds Default, Report and Zebra, in that order."""

    def setUp(self):
        super().setUp()
        self.library(Report=dict(REPORT),
                     Zebra={"text": "Stripes.", "model": "claude-opus-5-5",
                            "thinking_mode": "high", "meta": True, "conversational": True})

    def editor(self, *script):
        return self.drive("f4", *script)

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


class Looking(EditorCase):
    def test_the_editor_opens_on_the_instruction_in_use(self):
        self.editor(self.shows("Instruction Editor: Default", "Default  (in use)", "Report",
                               "Zebra", "Name: Default", "Model: [claude-opus-5-5",
                               "Thinking: [low", "[x] Meta", "[x] Convo"))

    def test_moving_through_the_list_shows_each_instruction(self):
        self.editor("down", self.shows(
            "Instruction Editor: Report", "Name: Report", "Model: [claude-haiku-5-5",
            "[ ] Meta", "[ ] Convo", "Report the temperature.", "Tools: all allowed."),
            "down", self.shows("Name: Zebra", "Thinking: [high", "Stripes."))

    def test_a_letter_jumps_to_an_instruction(self):
        self.editor("z", self.shows("Name: Zebra"))

    def test_an_entry_that_says_little_shows_what_a_run_would_use(self):
        # No model, no thinking level: Opus, which cannot switch thinking off.
        self.library(Bare={"text": "Only text."})
        self.editor("b", self.shows("Name: Bare", "Model: [claude-opus-5-5",
                                    "Thinking: [adaptive", "[ ] Meta", "[ ] Convo"))

    def test_escape_closes_the_editor(self):
        self.editor("esc", self.lacks("Instruction Editor"), self.shows("[ Instruction ]"))


class Saving(EditorCase):
    def test_a_changed_text_is_saved(self):
        self.editor("down", "alt+x", "ctrl+end", typed(" Twice."),
                    self.shows("Instruction Editor: Report (changed)"),
                    "alt+s", self.shows("Saved 'Report'."), self.lacks("(changed)"))
        self.assertEqual(self.saved("Report")["text"], "Report the temperature. Twice.")

    def test_settings_are_saved(self):
        self.editor("down", "alt+e", "alt+c", "alt+s")
        entry = self.saved("Report")
        self.assertIs(entry["meta"], True)
        self.assertIs(entry["conversational"], True)
        self.assertEqual(entry["model"], "claude-haiku-5-5")
        self.assertEqual(entry["thinking_mode"], "low")

    def test_the_memory_box_is_saved_and_shown_again(self):
        self.editor("down", self.shows("[ ] Memory"), "alt+m", "alt+s")
        self.assertIs(self.saved("Report")["memory"], True)
        self.editor("down", self.shows("[x] Memory"), "alt+m", "alt+s")
        self.assertIs(self.saved("Report")["memory"], False)

    def test_what_other_programs_keep_in_an_entry_stays(self):
        self.library(Report=dict(REPORT, section="Daily", order=3, images=["a.png"],
                                 thinking_budget=4096))
        self.editor("down", "alt+x", typed("New: "), "alt+s")
        entry = self.saved("Report")
        self.assertEqual(entry["text"], "New: Report the temperature.")
        self.assertEqual((entry["section"], entry["order"], entry["images"],
                          entry["thinking_budget"]), ("Daily", 3, ["a.png"], 4096))

    def test_the_other_instructions_are_not_touched(self):
        before = instructions.load_instructions(self.datadir)
        self.editor("down", "alt+x", typed("x"), "alt+s")
        after = instructions.load_instructions(self.datadir)
        self.assertEqual(after["Zebra"], before["Zebra"])
        self.assertEqual(after["Default"], before["Default"])

    def test_a_new_name_makes_a_new_instruction(self):
        self.editor("down", "alt+n", typed(" twice"), "alt+s",
                    self.shows("Saved 'Report twice'.", "Instruction Editor: Report twice"))
        library = instructions.load_instructions(self.datadir)
        self.assertEqual(library["Report"], REPORT)
        self.assertEqual(library["Report twice"]["text"], "Report the temperature.")
        self.assertEqual(library["Report twice"]["model"], "claude-haiku-5-5")

    def test_saving_over_another_instruction_asks_first(self):
        over = ["down", "alt+n", "ctrl+u", typed("Zebra"), "alt+s"]
        self.editor(*over, self.shows("An instruction named 'Zebra' already exists."), "n")
        self.assertEqual(self.saved("Zebra")["text"], "Stripes.")
        self.editor(*over, "y")
        self.assertEqual(self.saved("Zebra")["text"], "Report the temperature.")
        self.assertEqual(self.saved("Report"), REPORT)

    def test_a_name_is_needed(self):
        self.editor("alt+w", "alt+x", typed("Some text."), "alt+s",
                    self.shows("Give the instruction a name first."), "enter",
                    typed("Fresh"), "alt+s", self.shows("Saved 'Fresh'."))
        self.assertEqual(self.saved("Fresh")["text"], "Some text.")

    def test_a_new_instruction_starts_empty_with_the_settings_shown(self):
        self.editor("down", "alt+w", self.shows("Instruction Editor: new instruction",
                                                "Model: [claude-haiku-5-5", "Name:"),
                    self.lacks("Report the temperature."),
                    typed("Chat"), "alt+c", "alt+s")
        entry = self.saved("Chat")
        self.assertEqual(entry["text"], "")
        self.assertEqual(entry["model"], "claude-haiku-5-5")
        self.assertEqual(entry["provider"], "Anthropic")
        self.assertIs(entry["conversational"], True)
        self.assertNotIn("skill_modes", entry)
        self.assertNotIn("upgrade_target", entry)

    def test_a_change_made_by_a_run_to_another_instruction_survives_a_save(self):
        def a_run_changes_zebra(screen):
            library = instructions.load_instructions(self.datadir)
            library["Zebra"]["text"] = "Changed by a run."
            library["Added"] = {"text": "Made by a run."}
            instructions.save_instructions(self.datadir, library)

        self.editor("down", "alt+x", typed("x"), Check(a_run_changes_zebra), "alt+s",
                    self.shows("Added"))
        library = instructions.load_instructions(self.datadir)
        self.assertEqual(library["Zebra"]["text"], "Changed by a run.")
        self.assertEqual(library["Added"]["text"], "Made by a run.")
        self.assertEqual(library["Report"]["text"], "xReport the temperature.")

    def test_a_library_that_cannot_be_read_is_not_written_over(self):
        self.datadir.instructions_file.write_text("{ this is not JSON", encoding="utf-8")
        self.editor("alt+n", typed("Name"), "alt+s", self.shows("Could not save"), "enter")
        self.assertEqual(self.datadir.instructions_file.read_text(encoding="utf-8"),
                         "{ this is not JSON")


class ModelSettings(EditorCase):
    def test_choosing_a_model(self):
        self.editor("down", "alt+o", self.shows("claude-fable-5-2", "claude-sonnet-5-5"),
                    "home", "enter", "alt+s")
        self.assertEqual(self.saved("Report")["model"], models.FALLBACK_MODELS[0])

    def test_the_thinking_levels_follow_the_model(self):
        def levels(screen):
            self.assertIsNotNone(screen.find("xhigh"))
            self.assertIsNone(screen.find("off"))     # Opus 5.5 always thinks
        self.editor("alt+h", Check(levels), "end", "enter", "alt+s")
        self.assertEqual(self.saved("Default")["thinking_mode"], "max")

    def test_a_level_the_new_model_lacks_becomes_one_it_has(self):
        # Sonnet 4.6 stops at high and max: xhigh has to go.
        self.library(Deep={"text": "x", "model": "claude-opus-5-5", "thinking_mode": "xhigh"})
        target = "claude-sonnet-4-6"
        steps = ["down"] * models.FALLBACK_MODELS.index(target)
        self.editor("home", self.shows("Name: Deep", "Thinking: [xhigh"),
                    "alt+o", "home", *steps, "enter",
                    self.shows(f"Model: [{target}", "Thinking: [high"), "alt+s")
        entry = self.saved("Deep")
        self.assertEqual((entry["model"], entry["thinking_mode"]), (target, "high"))

    def test_fast_is_only_offered_where_the_model_has_it(self):
        def fast_is_off(screen):
            y, x = screen.find("[ ] Fast")
            self.assertEqual(screen.styles[y][x], "dim")
        self.editor("down", Check(fast_is_off), "alt+f", "alt+s")     # Haiku: no fast mode
        self.assertIs(self.saved("Report")["fast_mode"], False)
        self.editor("home", "alt+f", "alt+s")                         # Opus 5.5 has it
        self.assertIs(self.saved("Default")["fast_mode"], True)

    def test_a_model_this_program_does_not_list_is_kept(self):
        self.library(Old={"text": "x", "model": "claude-opus-4-7", "thinking_mode": "high"})
        self.editor("o", self.shows("Model: [claude-opus-4-7"), "alt+x", typed("y"), "alt+s")
        self.assertEqual(self.saved("Old")["model"], "claude-opus-4-7")


class SmallWindows(EditorCase):
    def make_skills(self):
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        for name, mode in (("alpha", "enabled"), ("beta", "on_demand"), ("gamma", "disabled")):
            manage_skills(store, {"action": "create", "name": name, "mode": mode,
                                  "content": f"Text of {name}."})

    def test_notes(self):
        self.editor("down", "alt+t", typed("Remember this."), "alt+o",
                    self.shows("Notes: yes."), "alt+s")
        self.assertEqual(self.saved("Report")["notes"], "Remember this.")

    def test_blocking_tools(self):
        self.editor("down", "alt+l", self.shows("Tools this instruction may use",
                                                "[x] run_shell_command", "[x] web_search"),
                    " ", "w", " ", "alt+o", self.shows("Tools: 2 blocked."), "alt+s")
        self.assertEqual(self.saved("Report")["blocked_tools"],
                         ["run_shell_command", "web_search"])

    def test_a_blocked_tool_this_program_does_not_know_stays_blocked(self):
        self.library(Report=dict(REPORT, blocked_tools=["send_mail", "web_search"]))
        self.editor("down", "alt+l", self.shows("[ ] send_mail", "[ ] web_search"),
                    "w", " ", "alt+o", "alt+s")
        self.assertEqual(self.saved("Report")["blocked_tools"], ["send_mail"])

    def test_without_meta_its_four_tools_are_shown_switched_off(self):
        # Report has Meta off. A tick would promise a tool that no run of it gets.
        self.editor("down", "alt+l", self.shows(
            "[-] manage_instructions  (needs Meta)", "[-] manage_skills  (needs Meta)",
            "[-] run_instruction  (needs Meta)", "[-] upgrade_model  (needs Meta)",
            "[x] run_shell_command", "[x] microphone_listen", "[x] get_skill",
            "[x] web_search", "[-] needs the Meta box ticked."),
            self.lacks("[x] manage_skills", "A cleared tool is blocked."),
            "end", " ", "up", " ",              # Space does nothing on those rows
            self.shows("[-] upgrade_model", "[-] run_instruction"),
            "alt+o", self.shows("Tools: all allowed."), self.lacks("(changed)"))

    def test_with_meta_its_four_tools_can_be_ticked_and_cleared(self):
        # Zebra has Meta on.
        self.editor("down", "down", "alt+l", self.shows(
            "[x] manage_instructions", "[x] manage_skills", "[x] run_instruction",
            "[x] upgrade_model", "A cleared tool is blocked."),
            self.lacks("(needs Meta)", "[-]"),
            "end", " ", self.shows("[ ] upgrade_model"), "alt+o", "alt+s")
        self.assertEqual(self.saved("Zebra")["blocked_tools"], ["upgrade_model"])

    def test_the_tools_window_goes_by_the_meta_box_as_it_is_on_the_form(self):
        # Ticked, not yet saved: the four can be used by what would be saved.
        self.editor("down", "alt+e", "alt+l", self.shows("[x] manage_skills"),
                    self.lacks("(needs Meta)"), "esc",
                    "alt+e", "alt+l", self.shows("[-] manage_skills  (needs Meta)"), "esc")

    def test_a_block_on_a_meta_tool_is_kept_while_meta_is_off(self):
        self.library(Report=dict(REPORT, blocked_tools=["run_instruction"]))
        self.editor("down", "alt+l", self.shows("[-] run_instruction  (needs Meta)"),
                    "r", " ",                   # on run_instruction: nothing happens
                    "w", " ", "alt+o", self.shows("Tools: 2 blocked."), "alt+s",
                    # With Meta ticked the block is there to see, and to lift.
                    "alt+e", "alt+l", self.shows("[ ] run_instruction", "[x] manage_skills"),
                    "esc")
        self.assertEqual(self.saved("Report")["blocked_tools"],
                         ["run_instruction", "web_search"])

    def test_cancelling_a_small_window_changes_nothing(self):
        self.editor("down", "alt+l", " ", "esc", "alt+t", typed("x"), "esc", "y",
                    self.shows("Tools: all allowed.", "Notes: none."),
                    self.lacks("(changed)"))

    def test_an_instruction_starts_with_each_skills_own_mode(self):
        self.make_skills()
        self.editor("down", "alt+k", self.shows(
            "[x] Use each skill's own mode", "[ON] alpha", "[OD] beta", "[  ] gamma"),
            "alt+o", "alt+s")
        self.assertNotIn("skill_modes", self.saved("Report"))

    def test_changing_a_skill_gives_the_instruction_a_set_of_its_own(self):
        self.make_skills()
        self.editor("down", "alt+k", "alt+s", "down", "down", " ",
                    self.shows("[ ] Use each skill's own mode", "[ON] gamma"), "alt+o",
                    self.shows("Skills: its own set (3 on)."), "alt+s")
        self.assertEqual(self.saved("Report")["skill_modes"],
                         {"alpha": "enabled", "beta": "on_demand", "gamma": "enabled"})

    def test_a_saved_set_switches_off_the_skills_it_does_not_name(self):
        self.make_skills()
        self.library(Report=dict(REPORT, skill_modes={"beta": "enabled", "gone": "enabled"}))
        self.editor("down", "alt+k", self.shows("[ ] Use each skill's own mode", "[  ] alpha",
                                                "[ON] beta", "[  ] gamma"),
                    "alt+o", "alt+x", typed("x"), "alt+s")
        self.assertEqual(self.saved("Report")["skill_modes"],
                         {"alpha": "disabled", "beta": "enabled", "gamma": "disabled"})

    def test_ticking_the_box_gives_the_set_up_again(self):
        self.make_skills()
        self.library(Report=dict(REPORT, skill_modes={"beta": "enabled"}))
        self.editor("down", "alt+k", "alt+u", self.shows("[ON] alpha", "[OD] beta"), "alt+o",
                    self.shows("Skills: each skill's own mode."), "alt+s")
        self.assertNotIn("skill_modes", self.saved("Report"))

    def test_the_upgrade_target(self):
        self.editor("down", "alt+g", self.shows("Model upgrade", "Upgrade to: [the default"),
                    "alt+t", "down", "enter", "alt+o", self.shows("Upgrade: never."), "alt+s")
        self.assertEqual(self.saved("Report")["upgrade_target"],
                         {"model": "", "level": "", "fast": False})

    def test_an_upgrade_to_a_named_model(self):
        # The list: the default, never, then the models. A model starts at
        # its strongest level.
        model = models.FALLBACK_MODELS[0]
        levels = models.upgrade_levels(model)
        self.editor("down", "alt+g", "alt+t", "down", "down", "enter",
                    self.shows(f"Upgrade to: [{model}", f"Level: [{levels[-1]}"),
                    "alt+l", "home", "enter", "alt+f", "alt+o",
                    self.shows(f"Upgrade: {model}."), "alt+s")
        self.assertEqual(self.saved("Report")["upgrade_target"], {
            "model": model, "level": levels[0], "fast": models.supports_fast_mode(model)})

    def test_going_back_to_the_default_upgrade_removes_the_entry(self):
        self.library(Report=dict(REPORT, upgrade_target={"model": "claude-opus-5-5",
                                                         "level": "High", "fast": True}))
        self.editor("down", self.shows("Upgrade: claude-opus-5-5."), "alt+g",
                    self.shows("Upgrade to: [claude-opus-5-5", "Level: [High", "[x] Fast"),
                    "alt+t", "home", "enter", "alt+o", "alt+s")
        self.assertNotIn("upgrade_target", self.saved("Report"))


class UnsavedChanges(EditorCase):
    def test_moving_on_asks_and_no_stays(self):
        self.editor("down", "alt+x", typed("x"), "alt+i", "down",
                    self.shows("Leave this instruction without saving your changes?"), "n",
                    self.shows("Name: Report", "(changed)"))

    def test_moving_on_asks_and_yes_drops_the_changes(self):
        self.editor("down", "alt+x", typed("x"), "alt+i", "down", "y",
                    self.shows("Name: Zebra"), self.lacks("(changed)"))
        self.assertEqual(self.saved("Report"), REPORT)

    def test_closing_asks(self):
        self.editor("down", "alt+x", typed("x"), "esc",
                    self.shows("Close the editor without saving your changes?"), "n",
                    self.shows("Instruction Editor: Report (changed)"),
                    "esc", "y", self.lacks("Instruction Editor"))
        self.assertEqual(self.saved("Report"), REPORT)

    def test_nothing_changed_means_no_question(self):
        self.editor("down", "down", "up", "esc", self.lacks("Instruction Editor"))

    def test_a_new_instruction_asks_before_dropping_changes(self):
        self.editor("down", "alt+x", typed("x"), "alt+w", "n", self.shows("Name: Report"),
                    "alt+w", "y", self.shows("Instruction Editor: new instruction"))


class Deleting(EditorCase):
    def test_delete_asks_first(self):
        self.editor("down", "alt+d", self.shows("Delete the instruction 'Report'?"), "n")
        self.assertIn("Report", instructions.load_instructions(self.datadir))
        self.editor("down", "alt+d", "y", self.shows("Deleted 'Report'."),
                    self.lacks("Name: Report"))
        self.assertEqual(sorted(instructions.load_instructions(self.datadir)),
                         ["Default", "Zebra"])

    def test_deleting_the_instruction_in_use_falls_back_to_default(self):
        self.make_app(instruction="Zebra")
        self.editor(self.shows("Zebra  (in use)"), "alt+d", "y", "esc",
                    self.shows("Robot  |  Default"))
        self.assertEqual(self.app.instruction, "Default")

    def test_deleting_default_puts_it_back_as_built_in(self):
        self.library(Default=dict(instructions.default_entry(), model="claude-haiku-5-5",
                                  text="changed"))
        self.editor("alt+d", "y", self.shows("Default is back at its built-in settings.",
                                             "Model: [claude-opus-5-5"))
        self.assertEqual(self.saved("Default"), instructions.default_entry())

    def test_an_unsaved_instruction_has_nothing_to_delete(self):
        self.editor("alt+w", "alt+d", self.shows("nothing to delete"), "enter")
        self.assertEqual(len(instructions.load_instructions(self.datadir)), 3)


class Using(EditorCase):
    def test_use_makes_it_the_instruction_start_runs(self):
        self.editor("down", "alt+u", self.lacks("Instruction Editor"),
                    self.shows("Robot  |  Report  |  claude-haiku-5-5 (Low)  |  single task"))
        self.assertEqual(self.app.instruction, "Report")
        self.assertEqual(load_store(self.datadir.root / STATE_FILE)["instruction"], "Report")

    def test_the_choice_is_remembered_by_the_next_start_of_the_program(self):
        self.editor("down", "alt+u")
        self.app = None
        self.drive(self.shows("Robot  |  Report"))

    def test_use_with_unsaved_changes_offers_to_save(self):
        change = ["down", "alt+x", typed("x"), "alt+u"]
        self.editor(*change, self.shows("Save this instruction first?"), "c",
                    self.shows("Instruction Editor: Report (changed)"))
        self.assertEqual(self.app.instruction, "Default")
        self.assertEqual(self.saved("Report"), REPORT)
        self.editor(*change, "s", self.lacks("Instruction Editor"))
        self.assertEqual(self.app.instruction, "Report")
        self.assertEqual(self.saved("Report")["text"], "xReport the temperature.")

    def test_a_new_instruction_is_saved_before_it_is_used(self):
        self.editor("alt+w", typed("Fresh"), "alt+u", "enter", self.shows("Robot  |  Fresh"))
        self.assertIn("Fresh", instructions.load_instructions(self.datadir))

    def test_the_list_marks_the_instruction_in_use(self):
        self.editor("down", "alt+u", "f4", self.shows("Report  (in use)"),
                    self.lacks("Default  (in use)"))


class OtherPrograms(EditorCase):
    """Instructions MyAgent saved for another provider are in the same file."""

    def setUp(self):
        super().setUp()
        self.entry = {"text": "Ask the other model.", "provider": "OpenAI", "model": "gpt-9",
                      "thinking_mode": "none"}
        self.library(Other=dict(self.entry))

    def test_it_can_be_read(self):
        self.editor("o", self.shows("Name: Other", "Ask the other model.",
                                    "Set up for OpenAI by another program."))

    def test_it_cannot_be_saved_or_used(self):
        self.editor("o", "alt+x", typed("x"), "alt+s",
                    self.shows("It can be read here, but not changed or run."), "enter",
                    "alt+n", typed("copy"), "alt+s", "enter", "alt+u", "enter")
        library = instructions.load_instructions(self.datadir)
        self.assertEqual(library["Other"], self.entry)
        self.assertNotIn("Othercopy", library)
        self.assertEqual(self.app.instruction, "Default")

    def test_the_top_line_says_so_when_it_was_chosen_some_other_way(self):
        self.make_app(instruction="Other")
        self.drive(self.shows("Other  |  set up for OpenAI: it cannot be run here"))


if __name__ == "__main__":
    unittest.main()
