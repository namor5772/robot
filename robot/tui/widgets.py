"""Buttons, check boxes, text boxes, lists, and the window they sit in.

A widget knows how to draw itself and what to do with a key. A window holds
widgets, gives one of them the focus, and passes keys on:

    Tab, Shift+Tab     the next or the previous widget
    arrow keys         the same, where the widget has no use of its own for them
    Alt+letter         the widget whose label shows that letter highlighted
    Enter, Space       press the button, tick the box, open the list
    Escape             close the window (each window says what that means)

In a label, "&" marks the letter that Alt presses: "&Save" is Alt+S.
"""

from robot.tui.screen import Mouse, Paste
from robot.tui.text import EditBuffer, clip, text_width


def split_hot(label):
    """("Save", 0) for "&Save": the text, and the place of its Alt letter (-1: none)."""
    index = label.find("&")
    if index < 0 or index == len(label) - 1:
        return label, -1
    return label[:index] + label[index + 1:], index


def _hot_letter(text, hot):
    return text[hot].lower() if hot >= 0 else ""


def draw_frame(scr, widget, title, hot, focused, note=""):
    """The box around a list or a text, with its title in the top edge."""
    if not widget.enabled:
        frame = title_style = "frame_off"
    elif focused:
        frame, title_style = "frame_focus", "title_focus"
    else:
        frame, title_style = "frame", "title"
    scr.fill(widget.y, widget.x, widget.h, widget.w)
    scr.box(widget.y, widget.x, widget.h, widget.w, frame)
    room = widget.w - 6
    if not title or room <= 0:
        return
    shown = clip(title, room)
    scr.put(widget.y, widget.x + 2, f" {shown} ", title_style)
    if 0 <= hot < len(shown) and widget.enabled and not focused:
        scr.put(widget.y, widget.x + 3 + hot, shown[hot], "hot")
    room -= text_width(shown) + 3
    if note and room > 3:
        scr.put(widget.y, widget.x + 4 + text_width(shown), f"({clip(note, room)}) ", frame)


def flow(widgets, y, x, width, gap=1) -> int:
    """Place widgets left to right from (y, x), starting a new row when the
    next one does not fit in `width`. Returns the row after the last one used."""
    at = x
    for widget in widgets:
        if at > x and at + widget.w > x + width:
            y += 1
            at = x
        widget.place(y, at)
        at += widget.w + gap
    return y + 1


def draw_scroll_marks(scr, widget, above, below):
    """Arrows in the right edge of a box: there is more above, or below."""
    marks = scr.marks
    if above:
        scr.put(widget.y + 1, widget.x + widget.w - 1, marks["up"], "title")
    if below:
        scr.put(widget.y + widget.h - 2, widget.x + widget.w - 1, marks["down"], "title")


class Widget:
    """Something in a window. The window's layout gives it its place."""

    focusable = False

    def __init__(self):
        self.y = self.x = 0
        self.h = 1
        self.w = 0
        self.visible = True
        self.enabled = True
        self.hotkey = ""
        self.window = None

    def place(self, y, x, w=None, h=None):
        self.y, self.x = y, x
        if w is not None:
            self.w = max(0, w)
        if h is not None:
            self.h = max(0, h)
        return self

    def contains(self, y, x) -> bool:
        return (self.visible and self.y <= y < self.y + self.h
                and self.x <= x < self.x + self.w)

    def can_focus(self) -> bool:
        return self.focusable and self.visible and self.enabled

    def draw(self, scr, focused):
        pass

    def key(self, key) -> bool:
        """Act on a key. True when the key was this widget's to use."""
        return False

    def paste(self, text):
        pass

    def click(self, y, x):
        pass

    def wheel(self, step):
        pass

    def press(self):
        """What the widget's Alt letter does, once it has the focus."""

    def cursor(self):
        """Where the text cursor belongs while this has the focus, or None."""
        return None


class Label(Widget):
    def __init__(self, text="", style="normal"):
        super().__init__()
        self.text = text
        self.style = style
        self.w = text_width(text)

    def draw(self, scr, focused):
        scr.put(self.y, self.x, clip(self.text, self.w), self.style)


class Button(Widget):
    focusable = True

    def __init__(self, label, action):
        super().__init__()
        self.action = action
        self.text, self.hot = split_hot(label)
        self.hotkey = _hot_letter(self.text, self.hot)
        self.w = text_width(self.text) + 4

    def draw(self, scr, focused):
        shown = f"[ {self.text} ]"
        if not self.enabled:
            scr.put(self.y, self.x, shown, "button_off")
            return
        style = "button_focus" if focused else "button"
        scr.put(self.y, self.x, shown, style)
        if self.hot >= 0:
            scr.put(self.y, self.x + 2 + self.hot, self.text[self.hot], style + "_hot")

    def key(self, key) -> bool:
        if key in ("enter", " "):
            self.press()
            return True
        return False

    def press(self):
        if self.enabled:
            self.action()

    def click(self, y, x):
        self.press()


class Checkbox(Widget):
    focusable = True

    def __init__(self, label, value=False, on_change=None):
        super().__init__()
        self.text, self.hot = split_hot(label)
        self.hotkey = _hot_letter(self.text, self.hot)
        self.value = bool(value)
        self.on_change = on_change
        self.w = text_width(self.text) + 4

    def draw(self, scr, focused):
        shown = f"[{'x' if self.value else ' '}] {self.text}"
        if not self.enabled:
            scr.put(self.y, self.x, shown, "dim")
        elif focused:
            scr.put(self.y, self.x, shown, "selected_focus")
        else:
            scr.put(self.y, self.x, shown, "normal")
            if self.hot >= 0:
                scr.put(self.y, self.x + 4 + self.hot, self.text[self.hot], "hot")

    def toggle(self):
        if self.enabled:
            self.value = not self.value
            if self.on_change is not None:
                self.on_change(self.value)

    def key(self, key) -> bool:
        if key in ("enter", " "):
            self.toggle()
            return True
        return False

    def press(self):
        self.toggle()

    def click(self, y, x):
        self.toggle()


class Choice(Widget):
    """A setting with a fixed set of values, picked from a list that pops up."""

    focusable = True

    def __init__(self, label, options=(), value=None, on_change=None):
        super().__init__()
        self.text, self.hot = split_hot(label)
        self.hotkey = _hot_letter(self.text, self.hot)
        self.options = list(options)
        self.value = value if value is not None else (self.options[0] if self.options else "")
        self.on_change = on_change

    def set_options(self, options, value):
        self.options = list(options)
        self.value = value

    def draw(self, scr, focused):
        label = self.text + ": "
        scr.put(self.y, self.x, label, "normal" if self.enabled else "dim")
        if self.hot >= 0 and self.enabled and not focused:
            scr.put(self.y, self.x + self.hot, self.text[self.hot], "hot")
        room = max(1, self.w - text_width(label) - 4)
        shown = clip(str(self.value), room)
        shown += " " * (room - text_width(shown))
        if not self.enabled:
            style = "button_off"
        else:
            style = "selected_focus" if focused else "field"
        scr.put(self.y, self.x + text_width(label), f"[{shown} {scr.marks['down']}]", style)

    def open(self):
        if not self.enabled or not self.options:
            return
        picked = self.window.app.pick(self.text, self.options, self.value)
        if picked is not None and picked != self.value:
            self.value = picked
            if self.on_change is not None:
                self.on_change(picked)

    def key(self, key) -> bool:
        if key in ("enter", " "):
            self.open()
            return True
        return False

    def press(self):
        self.open()

    def click(self, y, x):
        self.open()


class TextField(Widget):
    """One line of text to type into."""

    focusable = True

    def __init__(self, label, text=""):
        super().__init__()
        self.label, self.hot = split_hot(label)
        self.hotkey = _hot_letter(self.label, self.hot)
        self.text = text
        self.pos = len(text)
        self.left = 0  # the first character shown, when the text is longer than the field

    def set(self, text):
        self.text = text
        self.pos = len(text)
        self.left = 0

    def _field(self):
        offset = text_width(self.label) + 2
        return self.x + offset, max(1, self.w - offset)

    def _scroll(self, width):
        if self.pos < self.left:
            self.left = self.pos
        while text_width(self.text[self.left:self.pos]) > width - 1:
            self.left += 1

    def draw(self, scr, focused):
        scr.put(self.y, self.x, self.label + ":", "normal" if self.enabled else "dim")
        if self.hot >= 0 and self.enabled and not focused:
            scr.put(self.y, self.x + self.hot, self.label[self.hot], "hot")
        x, width = self._field()
        self._scroll(width)
        style = "field_focus" if focused else "field" if self.enabled else "dim"
        scr.fill(self.y, x, 1, width, style)
        scr.put(self.y, x, clip(self.text[self.left:], width), style)

    def cursor(self):
        x, width = self._field()
        self._scroll(width)
        return self.y, x + text_width(self.text[self.left:self.pos])

    def _insert(self, text):
        self.text = self.text[:self.pos] + text + self.text[self.pos:]
        self.pos += len(text)

    def key(self, key) -> bool:
        if len(key) == 1:
            self._insert(key)
        elif key == "backspace":
            if self.pos > 0:
                self.text = self.text[:self.pos - 1] + self.text[self.pos:]
                self.pos -= 1
        elif key == "delete":
            self.text = self.text[:self.pos] + self.text[self.pos + 1:]
        elif key == "left":
            self.pos = max(0, self.pos - 1)
        elif key == "right":
            self.pos = min(len(self.text), self.pos + 1)
        elif key == "home":
            self.pos = 0
        elif key == "end":
            self.pos = len(self.text)
        elif key == "ctrl+u":
            self.set("")
        else:
            return False
        return True

    def paste(self, text):
        self._insert(" ".join(text.split("\n")).strip())

    def click(self, y, x):
        start, _width = self._field()
        wanted, pos = max(0, x - start), self.left
        while pos < len(self.text) and text_width(self.text[self.left:pos + 1]) <= wanted:
            pos += 1
        self.pos = pos


class TextArea(Widget):
    """A framed box of text that wraps at its edge. Editable unless read_only.

    With on_submit, Enter hands the text over (a reply box) and Ctrl+J or
    Alt+Enter starts a new line. Without it, Enter starts a new line.
    """

    focusable = True

    def __init__(self, title="", text="", read_only=False, on_submit=None):
        super().__init__()
        self.title, self.hot = split_hot(title)
        self.hotkey = _hot_letter(self.title, self.hot)
        self.buffer = EditBuffer(text)
        self.read_only = read_only
        self.on_submit = on_submit
        self.top = 0   # the first wrapped row shown
        self.note = ""  # a few words after the title

    def text(self) -> str:
        return self.buffer.text()

    def set_text(self, text, at_end=False):
        self.buffer.set_text(text, at_end=at_end)
        self.top = 0

    def _width(self):
        return max(1, self.w - 3)  # the last cell of a row is kept free for the cursor

    def _height(self):
        return max(0, self.h - 2)

    def draw(self, scr, focused):
        draw_frame(scr, self, self.title, self.hot, focused, self.note)
        width, height = self._width(), self._height()
        rows = self.buffer.rows(width)
        if not self.read_only:
            current, _cells = self.buffer.cursor_row(width)
            if current < self.top:
                self.top = current
            elif current >= self.top + height:
                self.top = current - height + 1
        self.top = max(0, min(self.top, len(rows) - height))
        lines = self.buffer.lines
        style = "normal" if self.enabled else "dim"
        for offset in range(height):
            index = self.top + offset
            if index >= len(rows):
                break
            line, start, end = rows[index]
            scr.put(self.y + 1 + offset, self.x + 1, clip(lines[line][start:end], self.w - 2),
                    style)
        draw_scroll_marks(scr, self, self.top > 0, self.top + height < len(rows))

    def cursor(self):
        if self.read_only or not self.enabled:
            return None
        current, cells = self.buffer.cursor_row(self._width())
        row = current - self.top
        if not 0 <= row < self._height():
            return None
        return self.y + 1 + row, self.x + 1 + cells

    def key(self, key) -> bool:
        buffer, width = self.buffer, self._width()
        page = max(1, self._height() - 1)
        if self.read_only:
            steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
            if key in steps:
                self.top = max(0, self.top + steps[key])  # the far end is held when drawn
            elif key in ("home", "ctrl+home"):
                self.top = 0
            elif key in ("end", "ctrl+end"):
                self.top = len(buffer.rows(width))
            else:
                return False
            return True
        if len(key) == 1:
            buffer.insert(key)
        elif key == "enter":
            if self.on_submit is not None:
                self.on_submit(self.text())
            else:
                buffer.insert("\n")
        elif key in ("ctrl+j", "alt+enter"):
            buffer.insert("\n")
        elif key == "backspace":
            buffer.backspace()
        elif key == "delete":
            buffer.delete()
        elif key == "left":
            buffer.left()
        elif key == "right":
            buffer.right()
        elif key == "up":
            buffer.up(width)
        elif key == "down":
            buffer.down(width)
        elif key == "pgup":
            buffer.up(width, page)
        elif key == "pgdn":
            buffer.down(width, page)
        elif key == "home":
            buffer.row_start(width)
        elif key == "end":
            buffer.row_end(width)
        elif key == "ctrl+home":
            buffer.start()
        elif key == "ctrl+end":
            buffer.finish()
        elif key == "ctrl+left":
            buffer.word_left()
        elif key == "ctrl+right":
            buffer.word_right()
        else:
            return False
        return True

    def paste(self, text):
        if not self.read_only:
            self.buffer.insert(text)

    def wheel(self, step):
        if self.read_only:
            self.top = max(0, self.top + 3 * step)
        elif step < 0:
            self.buffer.up(self._width(), 3)
        else:
            self.buffer.down(self._width(), 3)

    def click(self, y, x):
        row, cells = y - self.y - 1, x - self.x - 1
        if not self.read_only and 0 <= row < self._height() and cells >= 0:
            self.buffer.click(self._width(), self.top + row, cells)


class ListBox(Widget):
    """A framed list with one row selected."""

    focusable = True

    def __init__(self, title="", items=(), on_move=None, on_activate=None, on_space=None):
        super().__init__()
        self.title, self.hot = split_hot(title)
        self.hotkey = _hot_letter(self.title, self.hot)
        self.items = list(items)
        self.index = 0
        self.top = 0
        # on_move(new index) is asked before the selection moves, and may
        # answer False to keep it where it is.
        self.on_move = on_move
        self.on_activate = on_activate
        self.on_space = on_space
        self.search_from = 0  # where a row's name starts, for jumping to it by a letter
        self.note = ""

    def set_items(self, items, index=None):
        self.items = list(items)
        if index is not None:
            self.index = index
        self.index = max(0, min(self.index, len(self.items) - 1))

    def _height(self):
        return max(0, self.h - 2)

    def move_to(self, index):
        """Select a row the way the person does: the window may refuse."""
        if not self.items:
            return
        index = max(0, min(len(self.items) - 1, index))
        if index == self.index:
            return
        if self.on_move is not None and self.on_move(index) is False:
            return
        self.index = index

    def draw(self, scr, focused):
        draw_frame(scr, self, self.title, self.hot, focused, self.note)
        height, width = self._height(), self.w - 2
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + height:
            self.top = self.index - height + 1
        self.top = max(0, min(self.top, len(self.items) - height))
        for offset in range(height):
            index = self.top + offset
            if index >= len(self.items):
                break
            if index == self.index and self.enabled:
                style = "selected_focus" if focused else "selected"
                scr.fill(self.y + 1 + offset, self.x + 1, 1, width, style)
            else:
                style = "normal" if self.enabled else "dim"
            scr.put(self.y + 1 + offset, self.x + 1, clip(self.items[index], width), style)
        draw_scroll_marks(scr, self, self.top > 0, self.top + height < len(self.items))

    def _jump(self, letter):
        letter = letter.lower()
        count = len(self.items)
        for step in range(1, count + 1):
            index = (self.index + step) % count
            if self.items[index][self.search_from:].lower().startswith(letter):
                self.move_to(index)
                return

    def key(self, key) -> bool:
        page = max(1, self._height() - 1)
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
        if key in steps:
            self.move_to(self.index + steps[key])
        elif key == "home":
            self.move_to(0)
        elif key == "end":
            self.move_to(len(self.items) - 1)
        elif key == "enter" and self.on_activate is not None:
            self.on_activate()
        elif key == " " and self.on_space is not None:
            self.on_space()
        elif len(key) == 1 and key != " " and self.items:
            self._jump(key)
        else:
            return False
        return True

    def wheel(self, step):
        self.move_to(self.index + step)

    def click(self, y, x):
        row = y - self.y - 1
        if not 0 <= row < self._height():
            return
        index = self.top + row
        if index >= len(self.items):
            return
        if index == self.index:
            if self.on_activate is not None:
                self.on_activate()  # a second click on the selected row
        else:
            self.move_to(index)


class Window:
    """A frame with widgets in it. Keys go to the widget that has the focus."""

    title = ""
    framed = True
    hint = "Tab: next   Esc: close"  # shown at the right of the bottom line

    def __init__(self, app):
        self.app = app
        self.widgets = []
        self.focus = None
        self.closed = False
        self.result = None
        self.keys = {}  # key name -> what that key does anywhere in this window
        self.y = self.x = 0
        self.h = self.w = 0

    def add(self, widget):
        """Add a widget. The order of adding is the order Tab goes through."""
        widget.window = self
        self.widgets.append(widget)
        return widget

    def layout(self, rows, cols):
        """Place the window and its widgets on a screen of this size."""
        raise NotImplementedError

    def center(self, rows, cols, height, width):
        self.h = max(3, min(height, rows))
        self.w = max(10, min(width, cols))
        self.y = max(0, (rows - self.h) // 2)
        self.x = max(0, (cols - self.w) // 2)

    def close(self, result=None):
        self.result = result
        self.closed = True

    def on_escape(self):
        self.close(None)

    def on_enter(self):
        """Enter, when the widget with the focus had no use for it."""

    # -- focus -----------------------------------------------------------------

    def set_focus(self, widget):
        if widget is not None and widget.can_focus():
            self.focus = widget

    def focused(self):
        """The widget with the focus. One that can no longer hold it gives it up."""
        if self.focus is None or not self.focus.can_focus():
            self.focus = next((widget for widget in self.widgets if widget.can_focus()), None)
        return self.focus

    def focus_step(self, step):
        order = [widget for widget in self.widgets if widget.can_focus()]
        current = self.focused()
        if current is not None:
            self.focus = order[(order.index(current) + step) % len(order)]

    def mnemonic(self, letter) -> bool:
        """Alt+letter: go to the widget that shows the letter, and press it."""
        for widget in self.widgets:
            if widget.hotkey == letter and widget.visible and widget.enabled:
                if widget.can_focus():
                    self.focus = widget
                widget.press()
                return True
        return False

    # -- drawing -----------------------------------------------------------------

    def draw(self, scr):
        if self.framed:
            scr.fill(self.y, self.x, self.h, self.w)
            scr.box(self.y, self.x, self.h, self.w, "frame")
            if self.title:
                scr.put(self.y, self.x + 2, f" {clip(self.title, self.w - 6)} ", "title")
        self.paint(scr)
        focused = self.focused()
        for widget in self.widgets:
            if widget.visible:
                widget.draw(scr, widget is focused)

    def paint(self, scr):
        """What the window draws itself, underneath its widgets."""

    def cursor(self):
        focused = self.focused()
        return focused.cursor() if focused is not None else None

    # -- input -------------------------------------------------------------------

    def handle(self, event):
        if isinstance(event, Mouse):
            self._mouse(event)
            return
        focused = self.focused()
        if isinstance(event, Paste):
            if focused is not None:
                focused.paste(event.text)
            return
        if focused is not None and focused.key(event):
            return
        action = self.keys.get(event)
        if action is not None:
            action()
        elif event in ("tab", "down", "right"):
            self.focus_step(1)
        elif event in ("backtab", "up", "left"):
            self.focus_step(-1)
        elif event == "esc":
            self.on_escape()
        elif event == "enter":
            self.on_enter()
        elif event.startswith("alt+") and len(event) == 5:
            self.mnemonic(event[4])

    def _mouse(self, event):
        target = None
        for widget in reversed(self.widgets):
            if widget.contains(event.y, event.x):
                target = widget
                break
        if target is None or not target.enabled:
            return
        if event.kind == "click":
            if target.can_focus():
                self.focus = target
            target.click(event.y, event.x)
        else:
            target.wheel(-1 if event.kind == "wheel_up" else 1)
