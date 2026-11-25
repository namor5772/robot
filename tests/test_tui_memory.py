"""The Memories window, driven through the main window as a person would."""

import datetime
import unittest

from robot import memory
from robot.tui.memoryui import version_label
from tests.tui_fakes import AppCase, Check, FakeScreen, typed

NOON = datetime.datetime(2026, 11, 25, 12, 0)


class MemoriesCase(AppCase):
    """F6 opens the window. There is a shared memory, written twice, and one
    named "night watch"; the instruction Talk uses the shared one."""

    def setUp(self):
        super().setUp()
        self.library(Talk={"text": "Hi", "memory": True},
                     Guard={"text": "Watch", "memory": True, "memory_name": "night watch"},
                     Plain={"text": "x"})
        shared = self.store()
        shared.write("Roman likes coffee.", "We met.", NOON, NOON)
        shared.write("Roman likes tea.", "We talked about tea.", NOON, NOON)
        shared.settle(shared.begin("a.txt", 1), NOON)
        self.store("night watch").write("The door was shut all night.", "A quiet night.",
                                        NOON, NOON)

    def store(self, name=""):
        return memory.Store(self.datadir, name)

    def window(self, *script):
        return self.drive("f6", *script)

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


class Looking(MemoriesCase):
    def test_it_opens_on_the_shared_memory(self):
        self.window(self.shows(
            "Memories: shared", "|shared", "|night watch", "Used by: Talk",
            "3 words. Last awake: 2026-11-25 12:00.", "In the diary: 2 conversations.",
            "Earlier states: 1.", "Roman likes tea.", "--- The diary ---",
            "We talked about tea."))

    def test_moving_down_shows_the_named_one(self):
        self.window("down", self.shows("Memories: night watch", "Used by: Guard",
                                       "The door was shut all night.", "Last awake: never"),
                    self.lacks("Roman likes tea."))

    def test_the_button_on_the_main_window_opens_it(self):
        self.drive("alt+r", self.shows("Memories: shared"), "esc",
                   self.lacks("Memories: shared"), self.shows("[ Memories ]"))

    def test_with_nothing_remembered_it_says_so(self):
        self.store().delete()
        self.window(self.shows("(nothing is remembered yet)", "0 words. Last awake: never"))

    def test_a_memory_nobody_uses_says_so(self):
        self.library(Guard={"text": "Watch"})
        self.window("down", self.shows("Used by: no instruction"))

    def test_an_earlier_state_is_listed_by_its_time_and_size(self):
        path = self.store().versions_dir / "memory_20261125_172509.md"
        path.write_text("one two three four", encoding="utf-8")
        self.assertEqual(version_label(path), "2026-11-25 17:25:09  (4 words)")
        second = path.with_name("memory_20261125_172509_2.md")
        second.write_text("one", encoding="utf-8")
        self.assertEqual(version_label(second), "2026-11-25 17:25:09_2  (1 word)")


class Changing(MemoriesCase):
    def test_the_text_is_corrected_by_hand_and_the_old_one_is_kept(self):
        self.window("alt+e", self.shows("What 'shared' remembers"), "ctrl+end",
                    typed(" And cake."), "alt+o",
                    self.shows("Saved what 'shared' remembers.", "Earlier states: 2."))
        self.assertEqual(self.store().memory(), "Roman likes tea. And cake.")
        self.assertEqual(len(self.store().versions()), 2)
        self.assertEqual(len(self.store().diary()), 2)

    def test_an_edit_given_up_changes_nothing(self):
        self.window("alt+e", "esc", self.shows("Earlier states: 1."))
        self.assertEqual(self.store().memory(), "Roman likes tea.")

    def test_a_copy_gets_the_text_the_diary_and_a_place_in_the_list(self):
        self.window("alt+y", self.shows("Name of the copy"), typed("trial"), "alt+o",
                    self.shows("Memories: trial", "Copied 'shared' to 'trial'.",
                               "Used by: no instruction", "Roman likes tea."))
        copy = self.store("trial")
        self.assertEqual(copy.memory(), "Roman likes tea.")
        self.assertEqual(len(copy.diary()), 2)
        self.assertEqual(copy.last_awake(), self.store().last_awake())
        self.assertEqual(copy.versions(), [])

    def test_a_copy_is_not_made_over_a_memory_that_is_there(self):
        self.window("alt+y", typed("night watch"), "alt+o",
                    self.shows("There is a memory named 'night watch' already."), "enter")
        self.assertEqual(self.store("night watch").memory(), "The door was shut all night.")

    def test_a_copy_needs_a_name_that_will_do(self):
        self.window("alt+y", typed("a/b"), "alt+o", self.shows("A memory's name is 1 to 40"),
                    "enter", self.shows("Memories: shared"))
        self.assertEqual(memory.names(self.datadir), ["night watch"])

    def test_rolling_back_shows_the_earlier_state_and_asks(self):
        self.window("alt+b", self.shows("Go back to the memory as it was before", "(3 words)"),
                    "enter", self.shows("Roman likes coffee."), "esc",
                    self.shows("Make this the memory again?"), "y",
                    self.shows("Roman likes coffee.", "Earlier states: 2."))
        self.assertEqual(self.store().memory(), "Roman likes coffee.")

    def test_a_no_leaves_the_memory_as_it_is(self):
        self.window("alt+b", "enter", "esc", "n")
        self.assertEqual(self.store().memory(), "Roman likes tea.")

    def test_with_no_earlier_state_there_is_nothing_to_go_back_to(self):
        self.window("down", "alt+b", self.shows("No earlier state of this memory"), "enter")

    def test_deleting_a_named_memory_names_who_loses_it(self):
        self.window("down", "alt+d",
                    self.shows("Delete everything 'night watch' remembers",
                               "Guard will start again with no memories."), "y",
                    self.shows("Deleted the memory 'night watch'.", "Memories: shared"),
                    self.lacks("|night watch"))
        self.assertFalse(self.store("night watch").folder.exists())
        self.assertEqual(self.store().memory(), "Roman likes tea.")

    def test_deleting_the_shared_memory_leaves_the_named_ones(self):
        self.window("alt+d", "y", self.shows("(nothing is remembered yet)", "|night watch"))
        self.assertFalse(self.store().exists())
        self.assertEqual(self.store().versions(), [])
        self.assertEqual(self.store("night watch").memory(), "The door was shut all night.")

    def test_a_no_deletes_nothing(self):
        self.window("alt+d", "n")
        self.assertEqual(self.store().memory(), "Roman likes tea.")

    def test_an_empty_memory_has_nothing_to_delete_or_copy(self):
        self.store().delete()
        self.window("alt+d", self.shows("there is nothing to delete"), "enter",
                    "alt+y", self.shows("there is nothing to copy"), "enter")

    def test_the_memory_of_the_run_in_progress_is_left_alone(self):
        self.make_app()
        self.app.instruction = "Talk"
        self.app.running = True
        self.window("alt+d", self.shows("The run in progress uses this memory"), "enter",
                    "alt+e", self.shows("The run in progress uses this memory"), "enter",
                    "alt+m", "down", "alt+d", self.shows("Delete everything 'night watch'"), "n")
        self.app.running = False
        self.assertEqual(self.store().memory(), "Roman likes tea.")


class NarrowWindow(MemoriesCase):
    def test_the_smallest_window_keeps_every_button_but_help(self):
        self.screen = FakeScreen(18, 72)
        self.drive(self.shows("[ START ]", "[ Skills ]", "[ Memories ]", "[ Quit ]", "F1 Help"),
                   self.lacks("[ Help ]"), "f1", self.shows("GETTING AROUND"), "esc",
                   "f6", self.shows("Memories: shared", "[ Roll back ]", "[ Close ]"))

    def test_a_wider_one_has_help_as_well(self):
        self.drive(self.shows("[ Memories ]", "[ Help ]", "[ Quit ]"))


if __name__ == "__main__":
    unittest.main()
