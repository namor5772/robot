"""Measuring and wrapping text, and the editable text behind a text box.

Nothing here touches the screen, so all of it can be tested anywhere.
"""

import functools
import unicodedata


@functools.lru_cache(maxsize=4096)
def cell_width(char) -> int:
    """How many screen cells one character takes: 0, 1 or 2."""
    code = ord(char)
    if code < 0x300:
        return 1  # Latin text, and control characters, which are shown as a placeholder
    category = unicodedata.category(char)
    if category in ("Mn", "Me", "Cf"):
        return 0  # accents that sit on the character before, and invisible marks
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def text_width(text) -> int:
    if text.isascii():
        return len(text)
    return sum(cell_width(char) for char in text)


def _shown(char) -> str:
    if char == "\t":
        return " "
    category = unicodedata.category(char)
    if category == "Cf" and ord(char) >= 0x300:
        return ""
    if category[0] in "CZ" and char != " ":
        return "?"
    return char


def printable(text) -> str:
    """The text as it can be put on a screen, cell for cell.

    A tab becomes a space and other control characters a question mark, so
    that what is drawn is as wide as text_width says.
    """
    if text.isascii() and text.isprintable():
        return text
    return "".join(_shown(char) for char in text)


def clip(text, width) -> str:
    """The start of `text` that fits in `width` cells."""
    if width <= 0:
        return ""
    if text.isascii():
        return text[:width]
    used = 0
    for index, char in enumerate(text):
        used += cell_width(char)
        if used > width:
            return text[:index]
    return text


def wrap_segments(line, width) -> tuple:
    """Where one line (no line breaks in it) is cut to fit `width` cells.

    Returns (start, end) pairs that cover the whole line. A row is cut after
    a space where there is one; a word longer than a row is cut where it must
    be. The space a row is cut at stays on that row and may hang one cell over
    the edge, so a row can be width + 1 cells long. When the line ends with
    such a hanging space, an empty last row follows it: that is where the
    cursor goes after typing the space.
    """
    width = max(1, width)
    length = len(line)
    if length <= width and line.isascii():
        return ((0, length),)
    segments = []
    start = 0
    while True:
        used = 0
        end = start
        while end < length:
            step = cell_width(line[end])
            if used + step > width:
                break
            used += step
            end += 1
        if end >= length:
            segments.append((start, length))
            break
        if line[end] == " ":
            end += 1
        else:
            space = line.rfind(" ", start, end)
            if space >= start:
                end = space + 1
            elif end == start:
                end = start + 1  # a character wider than the whole row
                if end == length:
                    segments.append((start, end))
                    break
        segments.append((start, end))
        start = end
    return tuple(segments)


def wrap_line(line, width) -> list:
    """One line as rows for showing: the space a row was cut at is dropped."""
    segments = wrap_segments(line, width)
    hanging = len(segments) > 1 and segments[-1][0] == segments[-1][1]
    if hanging:
        segments = segments[:-1]  # the row that is only there for a cursor
    last = len(segments) - 1
    return [line[start:end].rstrip(" ") if index < last or hanging else line[start:end]
            for index, (start, end) in enumerate(segments)]


def wrap_lines(text, width) -> list:
    """`text` as rows of at most `width` cells, for showing (not editing)."""
    rows = []
    for line in text.split("\n"):
        rows.extend(wrap_line(line, width))
    return rows


class EditBuffer:
    """The text of a text box, with a cursor.

    The text is kept as lines. Movement up and down goes by the rows the text
    is wrapped into, which depend on the width of the box, so those methods
    take the width.
    """

    def __init__(self, text=""):
        self.lines = [""]
        self.row = 0
        self.col = 0
        self._want = None  # the column that moving up and down tries to keep
        self._version = 0
        self._layout_key = None
        self._layout = ([], [])
        self._segments = {}  # line -> where it is cut, for the width below
        self._segments_width = None
        self.set_text(text)

    # -- the text ------------------------------------------------------------

    def text(self) -> str:
        return "\n".join(self.lines)

    def set_text(self, text, at_end=False):
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        self.lines = text.split("\n")
        if at_end:
            self.row = len(self.lines) - 1
            self.col = len(self.lines[-1])
        else:
            self.row = self.col = 0
        self._changed()

    def _changed(self):
        self._version += 1
        self._want = None

    def insert(self, text):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        line = self.lines[self.row]
        head, tail = line[:self.col], line[self.col:]
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[self.row] = head + text + tail
            self.col += len(text)
        else:
            new = [head + parts[0]] + parts[1:-1] + [parts[-1] + tail]
            self.lines[self.row:self.row + 1] = new
            self.row += len(parts) - 1
            self.col = len(parts[-1])
        self._changed()

    def backspace(self):
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
        elif self.row > 0:
            above = self.lines[self.row - 1]
            self.col = len(above)
            self.lines[self.row - 1:self.row + 1] = [above + self.lines[self.row]]
            self.row -= 1
        else:
            return
        self._changed()

    def delete(self):
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
        elif self.row < len(self.lines) - 1:
            self.lines[self.row:self.row + 2] = [line + self.lines[self.row + 1]]
        else:
            return
        self._changed()

    # -- moving along the text -------------------------------------------------

    def left(self):
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])
        self._want = None

    def right(self):
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row < len(self.lines) - 1:
            self.row += 1
            self.col = 0
        self._want = None

    def word_left(self):
        self.left()
        line = self.lines[self.row]
        while self.col > 0 and line[self.col - 1] == " ":
            self.col -= 1
        while self.col > 0 and line[self.col - 1] != " ":
            self.col -= 1

    def word_right(self):
        line = self.lines[self.row]
        if self.col >= len(line):
            self.right()
            return
        while self.col < len(line) and line[self.col] != " ":
            self.col += 1
        while self.col < len(line) and line[self.col] == " ":
            self.col += 1
        self._want = None

    def start(self):
        self.row = self.col = 0
        self._want = None

    def finish(self):
        self.row = len(self.lines) - 1
        self.col = len(self.lines[-1])
        self._want = None

    # -- the wrapped rows --------------------------------------------------------

    def rows(self, width) -> list:
        """Every row of the wrapped text as (line index, start, end)."""
        return self._laid_out(width)[0]

    def _laid_out(self, width):
        key = (self._version, width)
        if self._layout_key != key:
            # Lines that are still here keep the cuts worked out for them, so
            # typing in one line of a long text re-wraps that line only.
            known = self._segments if self._segments_width == width else {}
            kept = {}
            rows, first = [], []
            for index, line in enumerate(self.lines):
                segments = known.get(line)
                if segments is None:
                    segments = wrap_segments(line, width)
                kept[line] = segments
                first.append(len(rows))
                for start, end in segments:
                    rows.append((index, start, end))
            self._segments, self._segments_width = kept, width
            self._layout_key = key
            self._layout = (rows, first)
        return self._layout

    def cursor_row(self, width) -> tuple:
        """(row among the wrapped rows, cells from the left) of the cursor."""
        rows, first = self._laid_out(width)
        index = first[self.row]
        while (index + 1 < len(rows) and rows[index + 1][0] == self.row
               and rows[index + 1][1] <= self.col):
            index += 1
        start = rows[index][1]
        return index, text_width(self.lines[self.row][start:self.col])

    def _row_limits(self, rows, index):
        """(line index, first column, last column the cursor can have) of a row."""
        line_index, start, end = rows[index]
        # On a row that is followed by more of the same line, the place after
        # its last character is the start of the next row, not part of this one.
        last = index + 1 >= len(rows) or rows[index + 1][0] != line_index
        return line_index, start, end if last else max(start, end - 1)

    def place(self, width, row, cells):
        """Put the cursor on a wrapped row, `cells` from the left or as near as it gets."""
        rows, _ = self._laid_out(width)
        row = max(0, min(len(rows) - 1, row))
        line_index, start, limit = self._row_limits(rows, row)
        line = self.lines[line_index]
        col, used = start, 0
        while col < limit:
            step = cell_width(line[col])
            if used + step > cells:
                break
            used += step
            col += 1
        self.row, self.col = line_index, col

    def click(self, width, row, cells):
        """Put the cursor where the mouse pointed."""
        self.place(width, row, cells)
        self._want = None

    def _move_rows(self, width, count):
        current, cells = self.cursor_row(width)
        if self._want is None:
            self._want = cells
        target = max(0, min(len(self.rows(width)) - 1, current + count))
        if target != current:
            self.place(width, target, self._want)

    def up(self, width, count=1):
        self._move_rows(width, -count)

    def down(self, width, count=1):
        self._move_rows(width, count)

    def row_start(self, width):
        rows = self.rows(width)
        index, _ = self.cursor_row(width)
        self.col = rows[index][1]
        self._want = None

    def row_end(self, width):
        rows = self.rows(width)
        index, _ = self.cursor_row(width)
        self.col = self._row_limits(rows, index)[2]
        self._want = None
