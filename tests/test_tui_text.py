"""Measuring and wrapping text, and the text behind a text box."""

import unittest

from robot.tui.text import (
    EditBuffer, cell_width, clip, printable, text_width, wrap_line, wrap_lines, wrap_segments)

WIDE = chr(0x4e2d)       # a Chinese character: two cells wide
ACCENT = chr(0x301)      # a combining acute accent: no cell of its own
JOINER = chr(0x200d)     # zero width joiner: invisible
E_ACUTE = chr(0xe9)      # e with an acute accent, as one character


class Measuring(unittest.TestCase):
    def test_how_many_cells_a_character_takes(self):
        self.assertEqual(cell_width("a"), 1)
        self.assertEqual(cell_width(E_ACUTE), 1)
        self.assertEqual(cell_width(WIDE), 2)
        self.assertEqual(cell_width("\U0001f600"), 2)   # an emoji face
        self.assertEqual(cell_width(ACCENT), 0)
        self.assertEqual(cell_width(JOINER), 0)

    def test_the_width_of_a_text(self):
        self.assertEqual(text_width("abc"), 3)
        self.assertEqual(text_width("a" + WIDE + "b"), 4)
        self.assertEqual(text_width("e" + ACCENT), 1)

    def test_what_can_be_put_on_a_screen(self):
        self.assertEqual(printable("plain text"), "plain text")
        self.assertEqual(printable("a\tb"), "a b")
        self.assertEqual(printable("a\x00b\x1bc"), "a?b?c")
        self.assertEqual(printable("a" + JOINER + "b"), "ab")
        accented = "caf" + E_ACUTE + " " + WIDE
        self.assertEqual(printable(accented), accented)

    def test_what_is_drawn_is_as_wide_as_measured(self):
        for text in ("a\tb", "x\x07y", "a" + JOINER + "b", WIDE + "e" + ACCENT):
            self.assertEqual(text_width(printable(text)), text_width(text), repr(text))

    def test_clip_keeps_what_fits(self):
        self.assertEqual(clip("abcdef", 3), "abc")
        self.assertEqual(clip("abc", 10), "abc")
        self.assertEqual(clip("abc", 0), "")
        self.assertEqual(clip("a" + WIDE + "b", 2), "a")      # half a wide character is none
        self.assertEqual(clip("a" + WIDE + "b", 3), "a" + WIDE)


class Wrapping(unittest.TestCase):
    def pieces(self, line, width):
        return [line[start:end] for start, end in wrap_segments(line, width)]

    def test_a_line_that_fits_is_one_row(self):
        self.assertEqual(wrap_segments("hello", 10), ((0, 5),))
        self.assertEqual(wrap_segments("", 10), ((0, 0),))

    def test_rows_are_cut_after_a_space(self):
        self.assertEqual(self.pieces("one two three", 8), ["one two ", "three"])

    def test_the_space_at_the_cut_may_hang_over_the_edge(self):
        # "abcd efgh" at width 4: the space after "abcd" stays on its row.
        self.assertEqual(self.pieces("abcd efgh", 4), ["abcd ", "efgh"])

    def test_a_word_longer_than_a_row_is_cut_where_it_must_be(self):
        self.assertEqual(self.pieces("abcdefghij", 4), ["abcd", "efgh", "ij"])

    def test_the_rows_cover_the_whole_line_without_gaps(self):
        line = "The quick brown fox  jumps over the extraordinarily lazy dog. " * 3
        for width in (1, 2, 5, 13, 40, 200):
            segments = wrap_segments(line, width)
            self.assertEqual(segments[0][0], 0)
            self.assertEqual(segments[-1][1], len(line))
            for (_start, end), (next_start, _end) in zip(segments, segments[1:]):
                self.assertEqual(end, next_start)
            for start, end in segments[:-1]:
                self.assertLessEqual(text_width(line[start:end]), width + 1)
                self.assertGreater(end, start)

    def test_a_line_that_ends_at_a_cut_gets_an_empty_row_for_the_cursor(self):
        # After the space that hangs over the edge there is no cell left.
        self.assertEqual(self.pieces("abcd ", 4), ["abcd ", ""])
        self.assertEqual(wrap_line("abcd ", 4), ["abcd"])      # not when only showing
        buffer = EditBuffer("abcd ")
        buffer.finish()
        self.assertEqual(buffer.cursor_row(4), (1, 0))
        buffer.col = 4                                         # on the space itself
        self.assertEqual(buffer.cursor_row(4), (0, 4))

    def test_wide_characters_count_double(self):
        self.assertEqual(self.pieces(WIDE * 5, 4), [WIDE * 2, WIDE * 2, WIDE])
        self.assertEqual(self.pieces(WIDE * 2, 1), [WIDE, WIDE])   # wider than the row: alone

    def test_rows_for_showing_drop_the_space_they_were_cut_at(self):
        self.assertEqual(wrap_line("one two three", 8), ["one two", "three"])
        self.assertEqual(wrap_line("ends with space ", 40), ["ends with space "])

    def test_line_breaks_and_blank_lines_are_kept(self):
        self.assertEqual(wrap_lines("one\n\ntwo three", 5), ["one", "", "two", "three"])


class Editing(unittest.TestCase):
    def test_typing(self):
        buffer = EditBuffer()
        buffer.insert("hello")
        self.assertEqual((buffer.text(), buffer.row, buffer.col), ("hello", 0, 5))

    def test_inserting_in_the_middle(self):
        buffer = EditBuffer("held")
        buffer.col = 3
        buffer.insert("lo wor")
        self.assertEqual(buffer.text(), "hello word")
        self.assertEqual(buffer.col, 9)

    def test_inserting_several_lines(self):
        buffer = EditBuffer("ad")
        buffer.col = 1
        buffer.insert("b\nmiddle\nc")
        self.assertEqual(buffer.lines, ["ab", "middle", "cd"])
        self.assertEqual((buffer.row, buffer.col), (2, 1))

    def test_line_ends_of_every_kind_become_line_breaks(self):
        buffer = EditBuffer("a\r\nb\rc")
        self.assertEqual(buffer.lines, ["a", "b", "c"])
        buffer.finish()
        buffer.insert("\r\nd")
        self.assertEqual(buffer.lines, ["a", "b", "c", "d"])

    def test_backspace_joins_lines(self):
        buffer = EditBuffer("ab\ncd")
        buffer.row, buffer.col = 1, 0
        buffer.backspace()
        self.assertEqual((buffer.text(), buffer.row, buffer.col), ("abcd", 0, 2))
        buffer.backspace()
        self.assertEqual(buffer.text(), "acd")
        buffer.start()
        buffer.backspace()                      # nothing before the start
        self.assertEqual(buffer.text(), "acd")

    def test_delete_joins_lines(self):
        buffer = EditBuffer("ab\ncd")
        buffer.col = 2
        buffer.delete()
        self.assertEqual(buffer.text(), "abcd")
        buffer.delete()
        self.assertEqual(buffer.text(), "abd")
        buffer.finish()
        buffer.delete()                         # nothing after the end
        self.assertEqual(buffer.text(), "abd")

    def test_left_and_right_cross_line_breaks(self):
        buffer = EditBuffer("ab\ncd")
        buffer.col = 2
        buffer.right()
        self.assertEqual((buffer.row, buffer.col), (1, 0))
        buffer.left()
        self.assertEqual((buffer.row, buffer.col), (0, 2))
        buffer.start()
        buffer.left()
        self.assertEqual((buffer.row, buffer.col), (0, 0))
        buffer.finish()
        buffer.right()
        self.assertEqual((buffer.row, buffer.col), (1, 2))

    def test_moving_by_a_word(self):
        buffer = EditBuffer("one two  three")
        buffer.word_right()
        self.assertEqual(buffer.col, 4)
        buffer.word_right()
        self.assertEqual(buffer.col, 9)
        buffer.word_right()
        self.assertEqual(buffer.col, 14)
        buffer.word_left()
        self.assertEqual(buffer.col, 9)
        buffer.word_left()
        self.assertEqual(buffer.col, 4)

    def test_set_text_can_leave_the_cursor_at_the_end(self):
        buffer = EditBuffer()
        buffer.set_text("one\ntwo", at_end=True)
        self.assertEqual((buffer.row, buffer.col), (1, 3))
        buffer.set_text("fresh")
        self.assertEqual((buffer.row, buffer.col), (0, 0))


class WrappedRows(unittest.TestCase):
    def setUp(self):
        # At width 8: "one two " / "three " / "four", then the second line.
        self.buffer = EditBuffer("one two three four\nend")
        self.width = 8

    def test_the_rows(self):
        rows = self.buffer.rows(self.width)
        lines = self.buffer.lines
        self.assertEqual([lines[line][start:end] for line, start, end in rows],
                         ["one two ", "three ", "four", "end"])

    def test_where_the_cursor_shows(self):
        buffer = self.buffer
        self.assertEqual(buffer.cursor_row(self.width), (0, 0))
        buffer.col = 7                           # on the space the first row was cut at
        self.assertEqual(buffer.cursor_row(self.width), (0, 7))
        buffer.col = 8                           # the first character of the second row
        self.assertEqual(buffer.cursor_row(self.width), (1, 0))
        buffer.col = 18                          # after the last character of the line
        self.assertEqual(buffer.cursor_row(self.width), (2, 4))
        buffer.row, buffer.col = 1, 3
        self.assertEqual(buffer.cursor_row(self.width), (3, 3))

    def test_up_and_down_go_by_wrapped_rows_and_keep_the_column(self):
        buffer = self.buffer
        buffer.col = 6
        buffer.down(self.width)
        self.assertEqual(buffer.cursor_row(self.width), (1, 5))   # "three " is shorter
        buffer.down(self.width)
        self.assertEqual(buffer.cursor_row(self.width), (2, 4))
        buffer.down(self.width)
        self.assertEqual(buffer.cursor_row(self.width), (3, 3))
        buffer.up(self.width, 3)
        self.assertEqual(buffer.cursor_row(self.width), (0, 6))   # back at the column it had

    def test_up_at_the_top_and_down_at_the_bottom_stay(self):
        buffer = self.buffer
        buffer.col = 2
        buffer.up(self.width)
        self.assertEqual((buffer.row, buffer.col), (0, 2))
        buffer.finish()
        buffer.down(self.width, 5)
        self.assertEqual((buffer.row, buffer.col), (1, 3))

    def test_home_and_end_work_on_the_wrapped_row(self):
        buffer = self.buffer
        buffer.col = 10                          # in "three "
        buffer.row_start(self.width)
        self.assertEqual(buffer.col, 8)
        buffer.row_end(self.width)
        self.assertEqual(buffer.col, 13)         # on the cut space: 14 is the next row
        self.assertEqual(buffer.cursor_row(self.width)[0], 1)
        buffer.col = 15                          # in "four", the last row of the line
        buffer.row_end(self.width)
        self.assertEqual(buffer.col, 18)

    def test_a_click_puts_the_cursor_there(self):
        buffer = self.buffer
        buffer.click(self.width, 1, 2)
        self.assertEqual((buffer.row, buffer.col), (0, 10))
        buffer.click(self.width, 3, 40)          # beyond the end of the row
        self.assertEqual((buffer.row, buffer.col), (1, 3))
        buffer.click(self.width, 99, 0)          # below the last row
        self.assertEqual((buffer.row, buffer.col), (1, 0))

    def test_rows_follow_every_change(self):
        buffer = self.buffer
        buffer.rows(self.width)
        buffer.finish()
        buffer.insert(" of it all")
        lines = buffer.lines
        self.assertEqual([lines[line][start:end] for line, start, end in buffer.rows(self.width)],
                         ["one two ", "three ", "four", "end of ", "it all"])
        # Another width is another layout.
        self.assertEqual(len(buffer.rows(40)), 2)

    def test_wide_characters_place_the_cursor_by_cells(self):
        buffer = EditBuffer(WIDE * 3)
        buffer.col = 2
        self.assertEqual(buffer.cursor_row(10), (0, 4))
        buffer.click(10, 0, 3)                   # in the middle of the second character
        self.assertEqual(buffer.col, 1)


if __name__ == "__main__":
    unittest.main()
