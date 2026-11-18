"""The screen the windows are drawn on, and the keys that are read from it.

`Screen` is what the rest of the interface draws on. `CursesScreen` is the
real one; the tests use one that lives in memory. curses is imported here and
nowhere else, and only when a CursesScreen is made, because Python on Windows
does not have it.

What `read` returns for a key press:
    a single character      something typed: "a", "Z", " ", an accented letter
    a name                  "enter", "tab", "backtab", "esc", "backspace",
                            "delete", "insert", "up", "down", "left", "right",
                            "home", "end", "pgup", "pgdn", "f1" to "f12",
                            "ctrl+a" and so on, "alt+a" and so on, "resize"
    Mouse(kind, y, x)       kind is "click", "wheel_up" or "wheel_down"
    Paste(text)             text pasted into the terminal in one go
"""

import os
from collections import namedtuple

from robot.tui.text import cell_width, clip, printable

Mouse = namedtuple("Mouse", "kind y x")
Paste = namedtuple("Paste", "text")

# Milliseconds. After Escape: is this the start of a longer message, or the
# Escape key? Inside a message: how long its next character may take.
ESC_WAIT_MS = 40
SEQUENCE_WAIT_MS = 500
PASTE_WAIT_MS = 1000

_PASTE_END = "\x1b[201~"

# What follows "ESC [" for the keys a terminal may send that way.
_CSI_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
    "Z": "backtab", "1~": "home", "2~": "insert", "3~": "delete", "4~": "end",
    "5~": "pgup", "6~": "pgdn", "7~": "home", "8~": "end",
    "11~": "f1", "12~": "f2", "13~": "f3", "14~": "f4", "15~": "f5", "17~": "f6",
    "18~": "f7", "19~": "f8", "20~": "f9", "21~": "f10", "23~": "f11", "24~": "f12",
    "1;5A": "ctrl+up", "1;5B": "ctrl+down", "1;5C": "ctrl+right", "1;5D": "ctrl+left",
    "1;5H": "ctrl+home", "1;5F": "ctrl+end",
    "1;3A": "up", "1;3B": "down", "1;3C": "right", "1;3D": "left",
}
# What follows "ESC O".
_SS3_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
    "P": "f1", "Q": "f2", "R": "f3", "S": "f4", "M": "enter",
}
# The Linux console's own F1 to F5 come as "ESC [ [ A" to "ESC [ [ E".
_LINUX_FKEYS = {"A": "f1", "B": "f2", "C": "f3", "D": "f4", "E": "f5"}

# Names curses gives to keys with Ctrl held, on terminals that describe them.
_CURSES_EXTENDED = {
    "kRIT5": "ctrl+right", "kLFT5": "ctrl+left", "kUP5": "ctrl+up", "kDN5": "ctrl+down",
    "kHOM5": "ctrl+home", "kEND5": "ctrl+end",
    "kRIT3": "right", "kLFT3": "left", "kUP3": "up", "kDN3": "down",
}


def _is_char(item) -> bool:
    return isinstance(item, str) and len(item) == 1


def _button_event(button, y, x, pressed=True):
    """A mouse report as an event, or None for one that means nothing here."""
    if button & 64:
        return Mouse("wheel_down" if button & 1 else "wheel_up", y, x)
    if pressed and not button & 32 and button & 3 == 0:
        return Mouse("click", y, x)
    return None


class KeyParser:
    """Turns what a terminal sends into the events listed at the top.

    `read(timeout_ms)` hands over the next thing that arrived: one character,
    the name of a key that was already recognised, or None when nothing came
    in time.

    A terminal does not only send keys. It answers questions from the
    programs that draw on it (tmux asks for its colours and its type), and
    such an answer arrives exactly like typing. Here every answer is
    recognised by its shape and dropped whole, so none of it reaches a text
    box or presses a button.
    """

    def __init__(self, read):
        self._read = read

    def next(self, timeout_ms):
        """The next event, or None when there is none (yet)."""
        item = self._read(timeout_ms)
        if not _is_char(item):
            return item
        return self._char(item)

    def _char(self, char):
        if char == "\x1b":
            return self._escape()
        if char == "\r":
            return "enter"
        if char == "\n":
            return "ctrl+j"
        if char == "\t":
            return "tab"
        if char in "\x7f\x08":
            return "backspace"
        code = ord(char)
        if code < 32:
            return "ctrl+" + chr(code + 96)
        if 0x80 <= code < 0xa0:
            return None
        return char

    def _escape(self):
        item = self._read(ESC_WAIT_MS)
        if item is None:
            return "esc"
        if not _is_char(item):
            return item  # Alt held with a named key: the key itself
        if item == "[":
            return self._csi()
        if item == "O":
            return self._ss3()
        if item in "]P^_X":
            # The start of a longer message from the terminal, or Alt with
            # this very character. A message goes on at once; a person's next
            # key does not.
            follower = self._read(ESC_WAIT_MS)
            if follower is None:
                return "alt+" + item.lower()
            self._skip_string(follower, bell_ends=item == "]")
            return None
        if item in "\r\n":
            return "alt+enter"
        if item == "\t":
            return "backtab"  # what the Linux console sends for Alt+Tab, its Shift+Tab
        if item == "\x1b":
            return "esc"
        if item in "\x7f\x08":
            return "alt+backspace"
        if ord(item) < 32:
            return "esc"
        return "alt+" + item.lower()

    def _csi(self):
        body = ""
        while True:
            item = self._read(SEQUENCE_WAIT_MS)
            if not _is_char(item):
                return None  # it broke off
            if not body and item == "[":
                key = self._read(SEQUENCE_WAIT_MS)
                return _LINUX_FKEYS.get(key) if _is_char(key) else None
            body += item
            if "@" <= item <= "~":
                break
            if len(body) > 80:
                return None
        if body == "200~":
            return self._paste()
        if body == "M":
            return self._x10_mouse()
        if body[0] == "<" and body[-1] in "Mm":
            return self._sgr_mouse(body)
        # Anything else is a key in the table, or an answer from the terminal
        # (its type: "?61;4;6c", ">0;10;1c") or a key not used here.
        return _CSI_KEYS.get(body)

    def _ss3(self):
        item = self._read(ESC_WAIT_MS)
        if item is None:
            return "alt+o"
        if not _is_char(item):
            return item
        return _SS3_KEYS.get(item)

    def _skip_string(self, first, bell_ends):
        """Read to the end of a message that began with ESC ], ESC P and the like."""
        item, escaped = first, False
        for _ in range(4096):
            if not _is_char(item):
                return  # it broke off
            if escaped and item == "\\":
                return
            if bell_ends and item == "\x07":
                return
            escaped = item == "\x1b"
            item = self._read(SEQUENCE_WAIT_MS)

    def _x10_mouse(self):
        codes = [self._read(SEQUENCE_WAIT_MS) for _ in range(3)]
        if not all(_is_char(code) for code in codes):
            return None
        button, x, y = (ord(code) for code in codes)
        if (button - 32) & 3 == 3 and not (button - 32) & 64:
            return None  # a button was let go
        return _button_event(button - 32, y - 33, x - 33)

    def _sgr_mouse(self, body):
        try:
            button, x, y = (int(part) for part in body[1:-1].split(";"))
        except ValueError:
            return None
        return _button_event(button, y - 1, x - 1, pressed=body[-1] == "M")

    def _paste(self):
        pieces, tail = [], ""
        while True:
            item = self._read(PASTE_WAIT_MS)
            if item is None:
                break
            if not _is_char(item):
                continue
            pieces.append(item)
            tail = (tail + item)[-len(_PASTE_END):]
            if tail == _PASTE_END:
                del pieces[-len(_PASTE_END):]
                break
        text = "".join(pieces).replace("\r\n", "\n").replace("\r", "\n")
        return Paste(text)


# Line-drawing characters and two arrows, by code point so that this file
# stays plain ASCII. All of them are in the font of the Linux console too.
_UNICODE_MARKS = {
    "h": chr(0x2500), "v": chr(0x2502), "tl": chr(0x250c), "tr": chr(0x2510),
    "bl": chr(0x2514), "br": chr(0x2518), "lt": chr(0x251c), "rt": chr(0x2524),
    "up": chr(0x25b2), "down": chr(0x25bc),
}
_ASCII_MARKS = {
    "h": "-", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+", "lt": "+", "rt": "+",
    "up": "^", "down": "v",
}


class Screen:
    """A grid of character cells to draw on. Drawing outside it is cut off."""

    unicode = True

    @property
    def marks(self):
        return _UNICODE_MARKS if self.unicode else _ASCII_MARKS

    # -- for a real screen to fill in -----------------------------------------

    def size(self):
        """(rows, columns)."""
        raise NotImplementedError

    def _cells(self, y, x, text, style):
        """Put text that is known to fit, starting at (y, x)."""
        raise NotImplementedError

    def erase(self):
        raise NotImplementedError

    def set_cursor(self, position):
        """Show the text cursor at (y, x), or hide it when given None."""
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError

    def read(self, timeout_ms):
        """The next key, mouse or paste event; None when none came in time."""
        raise NotImplementedError

    def redraw(self):
        """Paint everything again from scratch at the next refresh."""

    def close(self):
        pass

    # -- drawing -----------------------------------------------------------------

    def put(self, y, x, text, style="normal"):
        rows, cols = self.size()
        if not text or y < 0 or y >= rows or x >= cols:
            return
        text = printable(text)
        while text and x < 0:
            x += cell_width(text[0])
            text = text[1:]
        text = clip(text, cols - x)
        if text:
            self._cells(y, x, text, style)

    def fill(self, y, x, height, width, style="normal"):
        if width <= 0:
            return
        blank = " " * width
        for row in range(y, y + height):
            self.put(row, x, blank, style)

    def hline(self, y, x, width, style="frame", tees=False):
        if width <= 0:
            return
        marks = self.marks
        if tees and width >= 2:
            self.put(y, x, marks["lt"] + marks["h"] * (width - 2) + marks["rt"], style)
        else:
            self.put(y, x, marks["h"] * width, style)

    def box(self, y, x, height, width, style="frame"):
        if height < 2 or width < 2:
            return
        marks = self.marks
        self.put(y, x, marks["tl"] + marks["h"] * (width - 2) + marks["tr"], style)
        for row in range(y + 1, y + height - 1):
            self.put(row, x, marks["v"], style)
            self.put(row, x + width - 1, marks["v"], style)
        self.put(y + height - 1, x,
                 marks["bl"] + marks["h"] * (width - 2) + marks["br"], style)


class CursesScreen(Screen):
    """The terminal, through curses."""

    def __init__(self):
        import curses
        import locale

        self.curses = curses
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        encoding = (locale.getpreferredencoding(False) or "").lower()
        self.unicode = "utf" in encoding
        try:
            # How long curses itself waits after Escape. Its default, a whole
            # second, would make the Escape key feel stuck.
            curses.set_escdelay(25)
        except (AttributeError, curses.error):
            pass
        self.win = curses.initscr()
        self._closed = False
        try:
            curses.noecho()
            curses.raw()  # Ctrl-C, Ctrl-Z and Ctrl-S arrive as keys
            curses.nonl()  # Enter is told apart from Ctrl-J
            self.win.keypad(True)
            self._styles = self._make_styles()
            self._keys = self._make_keys()
            self._cursor = None
            self._cursor_shown = None
            self._show_cursor(False)
            self._wheel_down = getattr(curses, "BUTTON5_PRESSED", 0x200000)
            try:
                curses.mousemask(curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
                                 | curses.BUTTON4_PRESSED | self._wheel_down)
                curses.mouseinterval(0)
            except curses.error:
                pass
            curses.flushinp()  # whatever arrived while the program was starting
            self._send(b"\x1b[?2004h")  # have pasted text marked as such
            self.parser = KeyParser(self._read_raw)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _send(data):
        try:
            os.write(1, data)
        except OSError:
            pass

    def _make_styles(self):
        c = self.curses
        mono = {
            "normal": 0, "dim": c.A_DIM, "bold": c.A_BOLD, "bar": c.A_REVERSE,
            "bar_notice": c.A_REVERSE | c.A_BOLD, "frame": 0, "frame_focus": c.A_BOLD,
            "frame_off": c.A_DIM, "title": c.A_BOLD, "title_focus": c.A_BOLD,
            "button": c.A_BOLD, "button_hot": c.A_BOLD | c.A_UNDERLINE,
            "button_focus": c.A_REVERSE, "button_focus_hot": c.A_REVERSE | c.A_UNDERLINE,
            "button_off": c.A_DIM, "hot": c.A_UNDERLINE | c.A_BOLD, "field": c.A_UNDERLINE,
            "field_focus": c.A_UNDERLINE | c.A_BOLD, "selected": c.A_BOLD,
            "selected_focus": c.A_REVERSE, "robot": c.A_BOLD, "you": c.A_BOLD,
            "warn": c.A_BOLD, "error": c.A_BOLD, "good": 0,
        }
        try:
            c.start_color()
            if not c.has_colors():
                return mono
            try:
                c.use_default_colors()
                default = -1
            except c.error:
                default = c.COLOR_BLACK
            number = [0]

            def colours(fg, bg=default):
                number[0] += 1
                c.init_pair(number[0], fg, bg)
                return c.color_pair(number[0])

            return {
                "normal": 0,
                "dim": c.A_DIM,
                "bold": c.A_BOLD,
                "bar": colours(c.COLOR_BLACK, c.COLOR_CYAN),
                "bar_notice": colours(c.COLOR_BLACK, c.COLOR_YELLOW),
                "frame": colours(c.COLOR_CYAN),
                "frame_focus": colours(c.COLOR_YELLOW) | c.A_BOLD,
                "frame_off": c.A_DIM,
                "title": colours(c.COLOR_CYAN) | c.A_BOLD,
                "title_focus": colours(c.COLOR_YELLOW) | c.A_BOLD,
                "button": colours(c.COLOR_BLACK, c.COLOR_WHITE),
                "button_hot": colours(c.COLOR_RED, c.COLOR_WHITE),
                "button_focus": colours(c.COLOR_BLACK, c.COLOR_YELLOW),
                "button_focus_hot": colours(c.COLOR_RED, c.COLOR_YELLOW),
                "button_off": c.A_DIM,
                "hot": colours(c.COLOR_YELLOW) | c.A_BOLD,
                "field": colours(c.COLOR_WHITE, c.COLOR_BLUE),
                "field_focus": colours(c.COLOR_WHITE, c.COLOR_BLUE) | c.A_BOLD,
                "selected": colours(c.COLOR_BLACK, c.COLOR_WHITE),
                "selected_focus": colours(c.COLOR_BLACK, c.COLOR_YELLOW),
                "robot": colours(c.COLOR_GREEN) | c.A_BOLD,
                "you": colours(c.COLOR_CYAN) | c.A_BOLD,
                "warn": colours(c.COLOR_YELLOW),
                "error": colours(c.COLOR_RED) | c.A_BOLD,
                "good": colours(c.COLOR_GREEN),
            }
        except c.error:
            return mono

    def _make_keys(self):
        c = self.curses
        names = {
            "KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
            "KEY_HOME": "home", "KEY_END": "end", "KEY_PPAGE": "pgup", "KEY_NPAGE": "pgdn",
            "KEY_BACKSPACE": "backspace", "KEY_DC": "delete", "KEY_IC": "insert",
            "KEY_BTAB": "backtab", "KEY_ENTER": "enter", "KEY_A1": "home", "KEY_C1": "end",
            "KEY_A3": "pgup", "KEY_C3": "pgdn", "KEY_SLEFT": "left", "KEY_SRIGHT": "right",
            "KEY_FIND": "home", "KEY_SELECT": "end",
        }
        keys = {}
        for attribute, name in names.items():
            code = getattr(c, attribute, None)
            if code is not None:
                keys[code] = name
        for number in range(1, 13):
            keys[c.KEY_F0 + number] = f"f{number}"
        return keys

    # -- Screen ------------------------------------------------------------------

    def size(self):
        return self.win.getmaxyx()

    def _cells(self, y, x, text, style):
        try:
            self.win.addstr(y, x, text, self._styles.get(style, 0))
        except self.curses.error:
            pass  # writing the last cell of the screen reports an error after drawing it
        except (UnicodeError, ValueError):
            try:
                self.win.addstr(y, x, "?" * len(text), self._styles.get(style, 0))
            except self.curses.error:
                pass

    def erase(self):
        self.win.erase()

    def set_cursor(self, position):
        self._cursor = position

    def _show_cursor(self, shown):
        if shown != self._cursor_shown:
            self._cursor_shown = shown
            try:
                self.curses.curs_set(1 if shown else 0)
            except self.curses.error:
                pass

    def refresh(self):
        rows, cols = self.size()
        position = self._cursor
        if position is not None and 0 <= position[0] < rows and 0 <= position[1] < cols:
            self._show_cursor(True)
            try:
                self.win.move(position[0], position[1])
            except self.curses.error:
                pass
        else:
            self._show_cursor(False)
        self.win.noutrefresh()
        self.curses.doupdate()

    def redraw(self):
        self.win.clearok(True)

    def read(self, timeout_ms):
        return self.parser.next(timeout_ms)

    def _read_raw(self, timeout_ms):
        self.win.timeout(max(0, int(timeout_ms)))
        try:
            key = self.win.get_wch()
        except self.curses.error:
            # Nothing came in time. A quiet moment is also when to look
            # whether the terminal has changed size without curses noticing.
            return "resize" if self._size_changed() else None
        if isinstance(key, str):
            return key
        return self._named(key)

    def _size_changed(self) -> bool:
        """Take on the terminal's size if it is no longer the one curses has.

        curses hears of a new size through a signal (SIGWINCH), and only if
        its own handler for it is in place. Asking the terminal directly does
        not depend on that.
        """
        try:
            size = os.get_terminal_size(1)
        except (OSError, ValueError):
            return False
        if (size.lines, size.columns) == self.win.getmaxyx() or min(size) < 1:
            return False
        try:
            self.curses.resizeterm(size.lines, size.columns)
        except self.curses.error:
            return False
        return True

    def _named(self, key):
        c = self.curses
        if key == c.KEY_RESIZE:
            return "resize"
        if key == c.KEY_MOUSE:
            return self._mouse()
        name = self._keys.get(key)
        if name:
            return name
        try:
            described = c.keyname(key).decode("ascii", "replace")
        except (ValueError, c.error):
            return "unknown"
        return _CURSES_EXTENDED.get(described, "unknown")

    def _mouse(self):
        c = self.curses
        try:
            _device, x, y, _z, state = c.getmouse()
        except c.error:
            return "unknown"
        if state & c.BUTTON4_PRESSED:
            return Mouse("wheel_up", y, x)
        if state & self._wheel_down:
            return Mouse("wheel_down", y, x)
        if state & (c.BUTTON1_PRESSED | c.BUTTON1_CLICKED):
            return Mouse("click", y, x)
        return "unknown"

    def close(self):
        """Give the terminal back the way it was found."""
        if self._closed:
            return
        self._closed = True
        c = self.curses
        self._send(b"\x1b[?2004l")
        # flushinp: keys pressed while the program was leaving must not end up
        # typed at the shell.
        for undo in (c.flushinp, lambda: self.win.keypad(False), c.noraw, c.nl, c.echo,
                     lambda: c.curs_set(1), c.endwin):
            try:
                undo()
            except c.error:
                pass
