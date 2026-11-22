"""The system prompt's fixed text and the paragraph about the run."""

import unittest

from robot.prompts import base_system_prompt, run_paragraph


def one_line(text):
    return " ".join(text.split())


class BasePrompt(unittest.TestCase):
    def test_it_starts_with_the_robots_identity_and_ends_with_the_format_rule(self):
        for conversational in (True, False):
            prompt = base_system_prompt(conversational)
            self.assertTrue(prompt.startswith("You are the brain of a small robot."))
            self.assertTrue(one_line(prompt).endswith("shown in a plain terminal."))
            self.assertIn("Your task is given in the first user message.", prompt)

    def test_it_names_the_board_the_robot_runs_on(self):
        # The program does not find the board out: the sentence is changed by
        # hand when the SD card moves to another one, at the owner's word.
        for conversational in (True, False):
            prompt = one_line(base_system_prompt(conversational))
            self.assertIn("You run as a program on a Raspberry Pi 3 Model A+, which is "
                          "your body's onboard computer.", prompt)
            self.assertNotIn("Zero", prompt)

    def test_a_conversation_is_told_to_just_reply(self):
        prompt = base_system_prompt(True)
        self.assertIn("This is a conversation.", prompt)
        self.assertIn("Keep replies short and conversational", one_line(prompt))
        self.assertNotIn("single task run", prompt)

    def test_a_single_task_is_told_to_ask_through_user_prompt(self):
        prompt = base_system_prompt(False)
        self.assertIn("This is a single task run.", prompt)
        self.assertIn("you must ask with the user_prompt tool", one_line(prompt))
        self.assertNotIn("This is a conversation.", prompt)
        self.assertNotIn("Keep replies short", prompt)


class RunParagraph(unittest.TestCase):
    def test_a_saved_instruction_is_named_with_its_model(self):
        self.assertEqual(
            one_line(run_paragraph("Health check", "claude-haiku-5-5")),
            'About this run: you are running as the saved instruction named "Health check", '
            "on the model claude-haiku-5-5.")

    def test_a_plain_chat_points_at_the_default_instruction(self):
        self.assertEqual(
            one_line(run_paragraph("", "claude-opus-5-5")),
            "About this run: this is a chat started without a saved instruction. Its "
            'settings come from the instruction named "Default". You are running on the '
            "model claude-opus-5-5.")

    def test_a_run_that_can_upgrade_is_told_to_trust_the_tools_result(self):
        for name in ("", "Health check"):
            with_tool = one_line(run_paragraph(name, "claude-opus-5-5", can_upgrade=True))
            without = one_line(run_paragraph(name, "claude-opus-5-5"))
            self.assertEqual(
                with_tool,
                without + " If you have used the upgrade_model tool during this run, you "
                "are now on the model its result named instead.")

    def test_lines_are_wrapped_but_never_inside_a_model_id_or_name(self):
        text = run_paragraph("Night-watch patrol", "claude-haiku-4-5-20251001",
                             can_upgrade=True)
        self.assertIn("claude-haiku-4-5-20251001", text)
        self.assertIn('"Night-watch patrol"', one_line(text))
        self.assertIn("Night-watch", text)
        self.assertGreater(len(text.splitlines()), 1)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 78)

    def test_the_same_run_always_gets_the_same_text(self):
        self.assertEqual(run_paragraph("A", "claude-opus-5-5", True),
                         run_paragraph("A", "claude-opus-5-5", True))


if __name__ == "__main__":
    unittest.main()
