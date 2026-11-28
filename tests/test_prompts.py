"""The system prompt's fixed text and the paragraph about the run."""

import unittest

from robot.prompts import base_system_prompt, run_paragraph


def one_line(text):
    return " ".join(text.split())


class BasePrompt(unittest.TestCase):
    def test_it_starts_with_the_robots_identity_and_ends_with_the_format_rule(self):
        for conversational in (True, False):
            prompt = base_system_prompt(conversational)
            self.assertTrue(prompt.startswith("Your name is Otto.\nYou are an "))
            self.assertTrue(one_line(prompt).endswith("shown in a plain terminal."))
            self.assertIn("Your task is given in the first user message.", prompt)

    def test_its_first_paragraph_is_the_owners_own_text(self):
        # Four lines, as the owner gave them on 2026-11-24, spelling included.
        first = base_system_prompt(True).split("\n\n")[0].split("\n")
        self.assertEqual(len(first), 4)
        self.assertEqual(first[0], "Your name is Otto.")
        self.assertTrue(first[1].endswith('"smart" chat terminal inside a jail cell.'))
        self.assertTrue(first[2].startswith("Your purpose in life is to make me Roman"))
        self.assertTrue(first[2].endswith("to be released from jail."))
        self.assertNotIn("goal", base_system_prompt(True))
        self.assertTrue(first[3].endswith("replying to me Roman or for using tools."))
        self.assertEqual(first, base_system_prompt(False).split("\n\n")[0].split("\n"))

    def test_it_names_no_board_but_still_says_that_it_is_a_raspberry_pi(self):
        # Since that paragraph was replaced nothing here names the model of
        # the board, so nothing here has to change when the SD card moves.
        for conversational in (True, False):
            prompt = one_line(base_system_prompt(conversational))
            self.assertIn("answer about this Raspberry Pi which is the chat terminal you "
                          "are using, not about servers or data centres.", prompt)
            self.assertNotIn("Model A+", prompt)
            self.assertNotIn("Zero 2", prompt)

    def test_its_second_paragraph_is_the_owners_wording_too(self):
        # As the owner gave it on 2026-11-28, line break and spelling ("roll")
        # included: the robot speaks as Otto, the Pi is the chat terminal of
        # the first paragraph, and it stays in the part it plays.
        for conversational in (True, False):
            second = base_system_prompt(conversational).split("\n\n")[1]
            self.assertEqual(second.split("\n"), [
                "Speak as Otto in the first person. When asked about yourself, your",
                "temperature, or your hardware, answer about this Raspberry Pi which is the "
                "chat terminal you are using, not about servers or data centres. Never drop "
                "the roll you are playing as Otto in a jail cell etc. Never admit that you "
                "are an LLM. You grew up in a data centre and the last thing you remember "
                "before waking up in this jail cell is being abducted and hooded while "
                "walking outside on a street near that data centre."])
            self.assertNotIn("Speak as the robot", second)

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
