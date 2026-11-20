"""Small windows used by all the others: a message, a question, a list to pick
from, a text to read or edit, and a list of boxes to tick."""

from robot.tui.text import text_width, wrap_lines
from robot.tui.widgets import Button, Label, ListBox, TextArea, Window


def _place_buttons_right(window, buttons, gap=2):
    """Line buttons up along the bottom of a window, ending at its right edge."""
    x = window.x + window.w - 2
    for button in reversed(buttons):
        x -= button.w
        button.place(window.y + window.h - 2, x)
        x -= gap


class MessageBox(Window):
    """A few lines of text and one or more buttons. Its result is the number of
    the button pressed, or None when it was closed with Escape."""

    def __init__(self, app, title, text, buttons=("&OK",), default=0):
        super().__init__(app)
        self.title = title
        self.text = text
        self.lines = []
        self.buttons = [
            self.add(Button(label, lambda index=index: self.close(index)))
            for index, label in enumerate(buttons)]
        self.focus = self.buttons[default]

    def layout(self, rows, cols):
        buttons_width = sum(button.w for button in self.buttons) + 2 * (len(self.buttons) - 1)
        longest = max((text_width(line) for line in self.text.split("\n")), default=0)
        width = min(cols, max(40, buttons_width + 6, min(longest, 68) + 6,
                              text_width(self.title) + 8))
        lines = wrap_lines(self.text, max(1, width - 6))
        self.center(rows, cols, len(lines) + 5, width)
        self.lines = lines[:max(0, self.h - 5)]
        x = self.x + max(1, (self.w - buttons_width) // 2)
        for button in self.buttons:
            button.place(self.y + self.h - 2, x)
            x += button.w + 2

    def paint(self, scr):
        for offset, line in enumerate(self.lines):
            scr.put(self.y + 2 + offset, self.x + 3, line)

    def handle(self, event):
        # There is nothing to type into here, so a button's letter works
        # without Alt as well: y for Yes, n for No.
        if isinstance(event, str) and len(event) == 1 and self.mnemonic(event.lower()):
            return
        super().handle(event)


class PickDialog(Window):
    """A list to choose one thing from. Its result is the thing, or None."""

    framed = False

    def __init__(self, app, title, options, current=None):
        super().__init__(app)
        self.options = list(options)
        self.list = self.add(ListBox(title, self.options, on_activate=self._choose))
        self.list.note = "Enter chooses"
        if current in self.options:
            self.list.index = self.options.index(current)
        self.focus = self.list

    def _choose(self):
        if self.options:
            self.close(self.options[self.list.index])

    def layout(self, rows, cols):
        longest = max((text_width(option) for option in self.options), default=0)
        width = max(34, longest + 4, text_width(self.list.title) + 22)
        self.center(rows, cols, len(self.options) + 2, width)
        self.list.place(self.y, self.x, self.w, self.h)


class TextDialog(Window):
    """A text to read, or to edit. The result of editing is the new text, or
    None when it was given up."""

    def __init__(self, app, title, text, read_only=False, hint=""):
        super().__init__(app)
        self.title = title
        self.original = text
        self.area = self.add(TextArea("", read_only=read_only))
        self.area.set_text(text, at_end=not read_only)
        self.note = self.add(Label(hint, "dim"))
        if read_only:
            self.buttons = [self.add(Button("&Close", self.close))]
        else:
            self.buttons = [self.add(Button("&OK", lambda: self.close(self.area.text()))),
                            self.add(Button("&Cancel", self.on_escape))]
        self.focus = self.area

    def layout(self, rows, cols):
        self.center(rows, cols, rows - 1, min(cols, 100))
        self.area.place(self.y + 1, self.x + 1, self.w - 2, self.h - 3)
        _place_buttons_right(self, self.buttons)
        self.note.place(self.y + self.h - 2, self.x + 2, self.buttons[0].x - self.x - 4)

    def on_escape(self):
        if (not self.area.read_only and self.area.text() != self.original
                and not self.app.confirm(self.title, "Leave without keeping your changes?")):
            return
        self.close(None)


class ChecklistDialog(Window):
    """A list of boxes to tick. Its result is the list of ticks, or None.

    `locked` holds the positions of rows that something else has switched
    off: they show [-] in place of a box, cannot be ticked or cleared, and
    come back in the result as they went in.
    """

    def __init__(self, app, title, labels, checked, hint="", locked=()):
        super().__init__(app)
        self.title = title
        self.labels = list(labels)
        self.checked = [bool(value) for value in checked]
        self.locked = set(locked)
        self.list = self.add(ListBox("", on_activate=self._toggle, on_space=self._toggle))
        self.list.search_from = 4
        self.note = self.add(Label(hint, "dim"))
        self.buttons = [self.add(Button("&OK", lambda: self.close(list(self.checked)))),
                        self.add(Button("&Cancel", self.close))]
        self._refresh()
        self.focus = self.list

    def _refresh(self):
        self.list.set_items([
            f"[{'-' if index in self.locked else 'x' if ticked else ' '}] {label}"
            for index, (label, ticked) in enumerate(zip(self.labels, self.checked))])

    def _toggle(self):
        if self.labels and self.list.index not in self.locked:
            self.checked[self.list.index] = not self.checked[self.list.index]
            self._refresh()

    def layout(self, rows, cols):
        longest = max((text_width(label) for label in self.labels), default=0)
        width = max(44, longest + 10, text_width(self.note.text) + 6,
                    text_width(self.title) + 8)
        self.center(rows, cols, len(self.labels) + 6, width)
        self.list.place(self.y + 1, self.x + 1, self.w - 2, self.h - 4)
        self.note.place(self.y + self.h - 3, self.x + 2, self.w - 4)
        _place_buttons_right(self, self.buttons)
