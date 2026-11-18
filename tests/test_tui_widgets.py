"""Buttons, boxes, text boxes and lists; the window that holds them; the small dialogs."""

import unittest

from robot.tui.dialogs import ChecklistDialog, MessageBox, TextDialog
from robot.tui.screen import Mouse, Paste
from robot.tui.widgets import (
    Button, Checkbox, Choice, Label, ListBox, TextArea, TextField, Window, flow, split_hot)
from tests.tui_fakes import AppCase, Check, typed


class Form(Window):
    """A window that stacks its widgets, each (widget, width, height), downwards."""

    title = "Form"

    def __init__(self, app, *sized):
        super().__init__(app)
        self.sized = sized
        for widget, _width, _height in sized:
            self.add(widget)

    def layout(self, rows, cols):
        self.y = self.x = 0
        self.h, self.w = rows, cols
        y = 1
        for widget, width, height in self.sized:
            widget.place(y, 2, width, height)
            y += height


class WidgetCase(AppCase):
    def form(self, *sized):
        return Form(self.make_app() if self.app is None else self.app, *sized)

    def run_form(self, sized, *script):
        return self.show(self.form(*sized), *script)


class Labels(unittest.TestCase):
    def test_the_letter_after_an_ampersand_is_the_alt_letter(self):
        self.assertEqual(split_hot("&Save"), ("Save", 0))
        self.assertEqual(split_hot("E&xit"), ("Exit", 1))
        self.assertEqual(split_hot("Plain"), ("Plain", -1))
        self.assertEqual(split_hot("Odd&"), ("Odd&", -1))

    def test_flow_starts_a_new_row_when_the_next_widget_does_not_fit(self):
        buttons = [Button("One", None), Button("Two", None), Button("Three", None)]
        after = flow(buttons, 5, 10, 16)             # "[ One ] [ Two ]" is 15 wide
        self.assertEqual([(b.y, b.x) for b in buttons], [(5, 10), (5, 18), (6, 10)])
        self.assertEqual(after, 7)


class Buttons(WidgetCase):
    def setUp(self):
        super().setUp()
        self.pressed = []
        self.save = Button("&Save", lambda: self.pressed.append("save"))
        self.undo = Button("&Undo", lambda: self.pressed.append("undo"))
        self.sized = [(self.save, 8, 1), (self.undo, 8, 1)]

    def test_how_a_button_looks(self):
        self.run_form(self.sized, Check(lambda screen: (
            self.assertIsNotNone(screen.find("[ Save ]")),
            self.assertEqual(screen.style_at("[ Save ]"), "button_focus"),
            self.assertEqual(screen.style_at("[ Undo ]"), "button"),
            self.assertEqual(screen.style_at("Undo ]"), "button_hot"))))

    def test_enter_and_space_press_the_button_with_the_focus(self):
        self.run_form(self.sized, "enter", " ", "tab", "enter")
        self.assertEqual(self.pressed, ["save", "save", "undo"])

    def test_alt_and_the_letter_presses_from_anywhere(self):
        form = self.run_form(self.sized, "alt+u")
        self.assertEqual(self.pressed, ["undo"])
        self.assertIs(form.focus, self.undo)

    def test_a_click_presses(self):
        self.run_form(self.sized, Mouse("click", 2, 4))
        self.assertEqual(self.pressed, ["undo"])

    def test_a_button_that_is_switched_off_cannot_be_pressed_or_reached(self):
        self.undo.enabled = False
        form = self.run_form(self.sized, "alt+u", Mouse("click", 2, 4), "tab", "enter",
                             Check(lambda screen: self.assertEqual(
                                 screen.style_at("[ Undo ]"), "button_off")))
        self.assertEqual(self.pressed, ["save"])
        self.assertIs(form.focus, self.save)

    def test_a_letter_typed_without_alt_presses_nothing(self):
        self.run_form(self.sized, "s", "u", "S")
        self.assertEqual(self.pressed, [])


class Checkboxes(WidgetCase):
    def test_space_enter_alt_and_a_click_all_toggle(self):
        seen = []
        box = Checkbox("&Loud", False, seen.append)
        self.run_form([(box, 10, 1)], Check(lambda screen: self.assertIsNotNone(
            screen.find("[ ] Loud"))), " ", Check(lambda screen: self.assertIsNotNone(
                screen.find("[x] Loud"))), "enter", "alt+l", Mouse("click", 1, 3))
        self.assertEqual(seen, [True, False, True, False])
        self.assertFalse(box.value)

    def test_a_box_that_is_switched_off_stays_as_it_is(self):
        box = Checkbox("&Loud", True)
        box.enabled = False
        self.run_form([(Button("Go", lambda: None), 6, 1), (box, 10, 1)],
                      "alt+l", Mouse("click", 2, 3))
        self.assertTrue(box.value)


class TextFields(WidgetCase):
    def setUp(self):
        super().setUp()
        self.field = TextField("&Name", "")
        self.sized = [(self.field, 16, 1)]            # "Name: " and ten cells to type in

    def test_typing_and_correcting(self):
        self.run_form(self.sized, typed("helo"), "left", "l", "end", "!", "home", "delete",
                      "backspace")
        self.assertEqual(self.field.text, "ello!")

    def test_the_cursor_shows_where_typing_goes(self):
        self.run_form(self.sized, typed("abc"), "left",
                      Check(lambda screen: self.assertEqual(screen.cursor, (1, 2 + 6 + 2))))

    def test_a_long_text_scrolls_inside_the_field(self):
        self.run_form(self.sized, typed("abcdefghijklmnop"), Check(lambda screen: (
            self.assertEqual(screen.line(1)[2:18].rstrip(), "Name: hijklmnop"),
            self.assertEqual(screen.cursor, (1, 2 + 6 + 9)))),
            "home", Check(lambda screen: self.assertEqual(
                screen.line(1)[2:18], "Name: abcdefghij")))
        self.assertEqual(self.field.text, "abcdefghijklmnop")

    def test_ctrl_u_empties_the_field(self):
        self.run_form(self.sized, typed("abc"), "ctrl+u", "x")
        self.assertEqual(self.field.text, "x")

    def test_pasted_lines_become_one_line(self):
        self.run_form(self.sized, Paste("one\ntwo\n"))
        self.assertEqual(self.field.text, "one two")

    def test_left_and_right_stay_in_the_field_but_up_and_down_leave_it(self):
        button = Button("Go", lambda: None)
        form = self.run_form(self.sized + [(button, 6, 1)], "left", "right", "right")
        self.assertIs(form.focus, self.field)
        form = self.show(form, "down")
        self.assertIs(form.focus, button)

    def test_a_click_puts_the_cursor_there(self):
        self.field.set("abcdef")
        self.run_form(self.sized, Mouse("click", 1, 2 + 6 + 2), "X")
        self.assertEqual(self.field.text, "abXcdef")


class TextAreas(WidgetCase):
    def test_typing_wraps_and_enter_starts_a_new_line(self):
        area = TextArea("Te&xt")
        self.run_form([(area, 14, 5)], typed("one two three"), "enter", typed("four"),
                      Check(lambda screen: (
                          self.assertEqual(screen.line(2)[2:16], "|one two     |"),
                          self.assertEqual(screen.line(3)[2:16], "|three       |"),
                          self.assertEqual(screen.line(4)[2:16], "|four        |"),
                          self.assertEqual(screen.cursor, (4, 7)))))
        self.assertEqual(area.text(), "one two three\nfour")

    def test_a_reply_box_sends_on_enter_and_breaks_lines_on_ctrl_j(self):
        sent = []
        area = TextArea("Reply", on_submit=sent.append)
        self.run_form([(area, 20, 5)], typed("one"), "ctrl+j", typed("two"), "alt+enter",
                      typed("three"), "enter")
        self.assertEqual(sent, ["one\ntwo\nthree"])

    def test_moving_about(self):
        area = TextArea("Text", "first line\nsecond line\nthird")
        self.run_form([(area, 30, 6)], "down", "end", "!", "ctrl+home", ">", "ctrl+end", "<",
                      "up", "home", "#", "ctrl+right", "ctrl+right", "@")
        self.assertEqual(area.text(), ">first line\n#second line!@\nthird<")

    def test_a_text_longer_than_the_box_scrolls_with_the_cursor(self):
        area = TextArea("Text", "\n".join(f"line {n}" for n in range(10)))
        self.run_form([(area, 20, 5)], Check(lambda screen: (
            self.assertIsNotNone(screen.find("line 0")),
            self.assertIsNone(screen.find("line 3")))),
            "pgdn", "pgdn", "down", Check(lambda screen: (
                self.assertIsNone(screen.find("line 2")),
                self.assertIsNotNone(screen.find("line 5")),
                self.assertEqual(screen.grid[2][21], "^"),     # there is more above
                self.assertEqual(screen.grid[4][21], "v"))))   # and more below

    def test_a_text_to_read_only_scrolls(self):
        area = TextArea("Text", "\n".join(f"line {n}" for n in range(10)), read_only=True)
        self.run_form([(area, 20, 5)], typed("xyz"), "backspace", Paste("no"), "down", "down",
                      Check(lambda screen: (
                          self.assertIsNone(screen.cursor),
                          self.assertIsNone(screen.find("line 1")),
                          self.assertIsNotNone(screen.find("line 2")))),
                      "end", Check(lambda screen: self.assertIsNotNone(screen.find("line 9"))),
                      "home", Check(lambda screen: self.assertIsNotNone(screen.find("line 0"))))
        self.assertEqual(area.text(), "\n".join(f"line {n}" for n in range(10)))

    def test_pasted_text_keeps_its_lines(self):
        area = TextArea("Text")
        self.run_form([(area, 30, 6)], typed("a"), Paste("b\nc\n"), typed("d"))
        self.assertEqual(area.text(), "ab\nc\nd")

    def test_a_click_puts_the_cursor_there(self):
        area = TextArea("Text", "alpha\nbravo")
        self.run_form([(area, 30, 6)], Mouse("click", 3, 2 + 1 + 2), "X")
        self.assertEqual(area.text(), "alpha\nbrXavo")

    def test_tab_leaves_the_box(self):
        area = TextArea("Text")
        button = Button("Go", lambda: None)
        form = self.run_form([(area, 30, 4), (button, 6, 1)], typed("a"), "tab")
        self.assertIs(form.focus, button)
        self.assertEqual(area.text(), "a")


class ListBoxes(WidgetCase):
    def setUp(self):
        super().setUp()
        self.moves = []
        self.box = ListBox("&Fruit", ["apple", "banana", "cherry", "date", "elder", "fig"],
                           on_move=self.moves.append)
        self.sized = [(self.box, 16, 5)]              # three rows show

    def test_arrows_move_the_selection_and_the_list_scrolls_with_it(self):
        self.run_form(self.sized, "down", "down", "down", Check(lambda screen: (
            self.assertIsNone(screen.find("apple")),
            self.assertEqual(screen.style_at("date"), "selected_focus"),
            self.assertEqual(screen.style_at("cherry"), "normal"))),
            "end", "home", "up")
        self.assertEqual(self.moves, [1, 2, 3, 5, 0])
        self.assertEqual(self.box.index, 0)

    def test_the_window_can_refuse_a_move(self):
        self.box.on_move = lambda index: index != 2
        self.run_form(self.sized, "down", "down", "down")
        self.assertEqual(self.box.index, 1)

    def test_a_letter_jumps_to_the_next_row_that_starts_with_it(self):
        self.run_form(self.sized, "d", Check(lambda screen: self.assertEqual(
            self.box.index, 3)), "a")
        self.assertEqual(self.box.index, 0)

    def test_enter_and_space_are_the_windows_to_use(self):
        seen = []
        self.box.on_activate = lambda: seen.append(("enter", self.box.index))
        self.box.on_space = lambda: seen.append(("space", self.box.index))
        self.run_form(self.sized, "down", "enter", " ")
        self.assertEqual(seen, [("enter", 1), ("space", 1)])

    def test_a_click_selects_and_a_second_click_chooses(self):
        seen = []
        self.box.on_activate = lambda: seen.append(self.box.index)
        self.run_form(self.sized, Mouse("click", 3, 4), Mouse("click", 3, 4))
        self.assertEqual((self.box.index, seen), (1, [1]))

    def test_the_wheel_moves_the_selection(self):
        self.run_form(self.sized, Mouse("wheel_down", 2, 4), Mouse("wheel_down", 2, 4),
                      Mouse("wheel_up", 2, 4))
        self.assertEqual(self.box.index, 1)

    def test_an_empty_list(self):
        self.box.set_items([])
        self.run_form(self.sized, "down", "enter", "x", "end")
        self.assertEqual(self.box.index, 0)


class Choices(WidgetCase):
    def test_enter_opens_a_list_to_pick_from(self):
        seen = []
        choice = Choice("&Size", ["small", "medium", "large"], "small", seen.append)
        self.run_form([(choice, 20, 1)],
                      Check(lambda screen: self.assertIsNotNone(screen.find("Size: [small"))),
                      "enter", Check(lambda screen: self.assertIsNotNone(screen.find("large"))),
                      "down", "down", "enter",
                      Check(lambda screen: self.assertIsNotNone(screen.find("Size: [large"))))
        self.assertEqual((choice.value, seen), ("large", ["large"]))

    def test_escape_in_the_list_changes_nothing(self):
        seen = []
        choice = Choice("&Size", ["small", "medium", "large"], "medium", seen.append)
        self.run_form([(choice, 20, 1)], "alt+s", "down", "esc")
        self.assertEqual((choice.value, seen), ("medium", []))

    def test_arrow_keys_do_not_change_the_setting(self):
        # A setting must not change because someone moved through the form.
        choice = Choice("&Size", ["small", "medium", "large"], "medium")
        button = Button("Go", lambda: None)
        form = self.run_form([(choice, 20, 1), (button, 6, 1)], "down", "up", "right", "left")
        self.assertEqual(choice.value, "medium")
        self.assertIs(form.focus, choice)


class Windows(WidgetCase):
    def setUp(self):
        super().setUp()
        self.one = Button("&One", lambda: None)
        self.two = Button("&Two", lambda: None)
        self.field = TextField("&Name")
        self.three = Button("T&hree", lambda: None)
        self.sized = [(self.one, 7, 1), (self.two, 7, 1), (self.field, 20, 1),
                      (Label("just words"), 10, 1), (self.three, 9, 1)]

    def test_tab_goes_round_in_the_order_of_adding(self):
        form = self.form(*self.sized)
        seen = []
        note = Check(lambda screen: seen.append(form.focus))
        self.show(form, note, "tab", note, "tab", note, "tab", note, "tab", note,
                  "backtab", note)
        self.assertEqual(seen, [self.one, self.two, self.field, self.three, self.one,
                                self.three])

    def test_tab_skips_what_is_switched_off_or_hidden(self):
        self.two.enabled = False
        self.field.visible = False
        form = self.run_form(self.sized, "tab")
        self.assertIs(form.focus, self.three)

    def test_the_focus_moves_on_when_its_widget_is_switched_off(self):
        form = self.form(*self.sized)
        self.show(form, "tab", Check(lambda screen: setattr(self.two, "enabled", False)), "tab")
        # The focus fell back to the first widget, and Tab went on from there.
        self.assertIs(form.focus, self.field)

    def test_alt_and_a_letter_goes_to_a_field(self):
        form = self.run_form(self.sized, "alt+n", typed("abc"))
        self.assertIs(form.focus, self.field)
        self.assertEqual(self.field.text, "abc")

    def test_escape_closes_the_window(self):
        form = self.run_form(self.sized, "esc")
        self.assertTrue(form.closed)
        self.assertIsNone(form.result)

    def test_a_click_gives_the_focus(self):
        form = self.run_form(self.sized, Mouse("click", 3, 12), "z")
        self.assertIs(form.focus, self.field)
        self.assertEqual(self.field.text, "z")

    def test_a_click_on_nothing_does_nothing(self):
        form = self.run_form(self.sized, Mouse("click", 20, 60), Mouse("click", 4, 3))
        self.assertIs(form.focus, self.one)

    def test_a_window_key_works_wherever_the_focus_is(self):
        seen = []
        form = self.form(*self.sized)
        form.keys["f2"] = lambda: seen.append("f2")
        self.show(form, "f2", "alt+n", "f2")
        self.assertEqual(seen, ["f2", "f2"])


class Messages(WidgetCase):
    def test_a_message_shows_its_text_and_closes_on_enter(self):
        box = MessageBox(self.make_app(), "Careful", "First line.\nSecond line that is longer.")
        self.show(box, Check(lambda screen: (
            self.assertIsNotNone(screen.find("Careful")),
            self.assertIsNotNone(screen.find("First line.")),
            self.assertIsNotNone(screen.find("Second line that is longer.")),
            self.assertIsNotNone(screen.find("[ OK ]")))), "enter")
        self.assertEqual(box.result, 0)

    def test_a_long_message_is_wrapped(self):
        box = MessageBox(self.make_app(), "Long", "word " * 60)
        self.show(box, Check(lambda screen: self.assertGreater(len(box.lines), 3)))
        for line in box.lines:
            self.assertLessEqual(len(line), box.w - 6)

    def test_a_question_answers_no_unless_told_yes(self):
        app = self.make_app()
        answers = []
        for script in (["enter"], ["esc"], ["n"], ["y"], ["alt+y"], ["left", "enter"],
                       ["tab", "enter"]):
            self.screen.feed(*script)
            answers.append(app.confirm("Sure?", "Really do it?"))
        self.assertEqual(answers, [False, False, False, True, True, True, True])

    def test_a_question_with_buttons_of_its_own(self):
        app = self.make_app()
        self.screen.feed("c")
        self.assertEqual(app.choose("Save?", "Save first?", ("&Save and use", "&Cancel")), 1)
        self.screen.feed("enter")
        self.assertEqual(app.choose("Save?", "Save first?", ("&Save and use", "&Cancel")), 0)
        self.screen.feed("esc")
        self.assertIsNone(app.choose("Save?", "Save first?", ("&Save and use", "&Cancel")))


class Picking(WidgetCase):
    def test_the_list_opens_on_the_current_value(self):
        app = self.make_app()
        self.screen.feed(Check(lambda screen: self.assertEqual(
            screen.style_at("two"), "selected_focus")), "down", "enter")
        self.assertEqual(app.pick("Number", ["one", "two", "three"], "two"), "three")

    def test_escape_picks_nothing(self):
        app = self.make_app()
        self.screen.feed("down", "esc")
        self.assertIsNone(app.pick("Number", ["one", "two", "three"], "one"))

    def test_a_list_longer_than_the_screen_scrolls(self):
        app = self.make_app()
        options = [f"option {n}" for n in range(60)]
        self.screen.feed("end", Check(lambda screen: self.assertIsNotNone(
            screen.find("option 59"))), "enter")
        self.assertEqual(app.pick("Many", options), "option 59")


class TextDialogs(WidgetCase):
    def test_editing_a_text(self):
        app = self.make_app()
        self.screen.feed(typed(" more"), "enter", typed("next"), "alt+o")
        self.assertEqual(app.edit_text("Notes", "some"), "some more\nnext")

    def test_cancel_gives_nothing_back(self):
        app = self.make_app()
        self.screen.feed("alt+c")
        self.assertIsNone(app.edit_text("Notes", "some"))

    def test_escape_asks_before_dropping_changes(self):
        app = self.make_app()
        self.screen.feed("x", "esc", Check(lambda screen: self.assertIsNotNone(
            screen.find("without keeping your changes"))), "n", "y", "alt+o")
        self.assertEqual(app.edit_text("Notes", "some"), "somexy")
        self.screen.feed("x", "esc", "y")
        self.assertIsNone(app.edit_text("Notes", "some"))
        self.screen.feed("esc")                       # nothing changed: no question
        self.assertIsNone(app.edit_text("Notes", "some"))

    def test_a_text_to_read(self):
        dialog = TextDialog(self.make_app(), "Read me", "words to read", read_only=True)
        self.show(dialog, typed("zzz"), Check(lambda screen: (
            self.assertIsNotNone(screen.find("words to read")),
            self.assertIsNotNone(screen.find("[ Close ]")))), "esc")
        self.assertTrue(dialog.closed)
        self.assertEqual(dialog.area.text(), "words to read")


class Checklists(WidgetCase):
    def test_space_ticks_and_clears(self):
        dialog = ChecklistDialog(self.make_app(), "Tools", ["hammer", "saw", "drill"],
                                 [True, True, False], hint="Space ticks or clears.")
        self.show(dialog, Check(lambda screen: (
            self.assertIsNotNone(screen.find("[x] hammer")),
            self.assertIsNotNone(screen.find("[ ] drill")),
            self.assertIsNotNone(screen.find("Space ticks or clears.")))),
            " ", "down", "down", " ", "alt+o")
        self.assertEqual(dialog.result, [False, True, True])

    def test_cancel_and_escape_give_nothing_back(self):
        for key in ("alt+c", "esc"):
            dialog = ChecklistDialog(self.make_app(), "Tools", ["hammer"], [True])
            self.show(dialog, " ", key)
            self.assertIsNone(dialog.result)

    def test_a_letter_jumps_to_the_name(self):
        dialog = ChecklistDialog(self.make_app(), "Tools", ["hammer", "saw", "drill"],
                                 [True, True, True])
        self.show(dialog, "d", " ", "alt+o")
        self.assertEqual(dialog.result, [True, True, False])


if __name__ == "__main__":
    unittest.main()
