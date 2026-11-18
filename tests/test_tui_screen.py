"""Reading keys: telling key presses from the terminal's own messages, and drawing
within the edges of the screen."""

import unittest

from robot.tui.screen import KeyParser, Mouse, Paste
from tests.tui_fakes import FakeScreen

ESC = "\x1b"
WIDE = chr(0x4e2d)       # a Chinese character: two cells wide
E_ACUTE = chr(0xe9)      # e with an acute accent


def parser_for(*items):
    """A parser fed from a list. A string is delivered one character at a
    time; None is a wait in which nothing arrived; a tuple is the name of a
    key that was recognised before the parser saw it."""
    stream = []
    for item in items:
        if isinstance(item, str):
            stream.extend(item)
        elif isinstance(item, tuple):
            stream.append(item[0])
        else:
            stream.append(item)

    def read(timeout_ms):
        return stream.pop(0) if stream else None

    return KeyParser(read), stream


def events(*items):
    """Everything the parser makes of the input, in order."""
    parser, stream = parser_for(*items)
    found = []
    while stream:
        event = parser.next(0)
        if event is not None:
            found.append(event)
    return found


class Keys(unittest.TestCase):
    def test_typed_characters(self):
        self.assertEqual(events("aZ 9" + E_ACUTE + WIDE), ["a", "Z", " ", "9", E_ACUTE, WIDE])

    def test_keys_that_arrive_as_control_characters(self):
        self.assertEqual(events("\r"), ["enter"])
        self.assertEqual(events("\n"), ["ctrl+j"])
        self.assertEqual(events("\t"), ["tab"])
        self.assertEqual(events("\x7f\x08"), ["backspace", "backspace"])
        self.assertEqual(events("\x03\x11\x0c"), ["ctrl+c", "ctrl+q", "ctrl+l"])

    def test_keys_recognised_before_the_parser_are_passed_on(self):
        self.assertEqual(events(("up",), "a", ("f2",), ("resize",)),
                         ["up", "a", "f2", "resize"])

    def test_escape_on_its_own(self):
        self.assertEqual(events(ESC, None, "a"), ["esc", "a"])

    def test_alt_with_a_letter(self):
        self.assertEqual(events(ESC + "s"), ["alt+s"])
        self.assertEqual(events(ESC + "S"), ["alt+s"])          # Caps Lock makes no difference
        self.assertEqual(events(ESC + "\r"), ["alt+enter"])
        self.assertEqual(events(ESC + "\x7f"), ["alt+backspace"])
        self.assertEqual(events(ESC + "\t"), ["backtab"])       # the Linux console's Shift+Tab

    def test_alt_with_a_letter_that_could_start_a_message(self):
        # ESC P, ESC ] and ESC O also open longer messages. A person's next
        # key does not follow at once; the rest of a message does.
        self.assertEqual(events(ESC + "P", None, "x"), ["alt+p", "x"])
        self.assertEqual(events(ESC + "]", None), ["alt+]"])
        self.assertEqual(events(ESC + "O", None, "k"), ["alt+o", "k"])

    def test_keys_sent_as_escape_sequences(self):
        self.assertEqual(events(ESC + "[A", ESC + "[B", ESC + "[C", ESC + "[D"),
                         ["up", "down", "right", "left"])
        self.assertEqual(events(ESC + "[Z"), ["backtab"])
        self.assertEqual(events(ESC + "[3~", ESC + "[5~", ESC + "[6~"),
                         ["delete", "pgup", "pgdn"])
        self.assertEqual(events(ESC + "[1;5C", ESC + "[1;5D"), ["ctrl+right", "ctrl+left"])
        self.assertEqual(events(ESC + "OP", ESC + "OS", ESC + "[15~", ESC + "[21~"),
                         ["f1", "f4", "f5", "f10"])
        self.assertEqual(events(ESC + "[[A", ESC + "[[E"), ["f1", "f5"])   # the Linux console

    def test_an_escape_sequence_nobody_knows_is_dropped_whole(self):
        self.assertEqual(events(ESC + "[1;2P", "a"), ["a"])


class TerminalAnswers(unittest.TestCase):
    """What a terminal sends in reply to tmux must never reach a window."""

    def test_the_colour_answer(self):
        self.assertEqual(events(ESC + "]11;rgb:0c0c/0c0c/0c0c" + ESC + "\\", "a"), ["a"])
        self.assertEqual(events(ESC + "]10;rgb:cccc/cccc/cccc\x07", "a"), ["a"])   # ended by BEL

    def test_the_type_answers(self):
        self.assertEqual(events(ESC + "[?61;4;6;7;14;21;22;23;24;28;32;42c", "a"), ["a"])
        self.assertEqual(events(ESC + "[>0;10;1c", "a"), ["a"])

    def test_the_same_answer_twice(self):
        # Seen on 2026-11-18: the terminal answered twice and tmux passed the
        # second answer on whole.
        answer = ESC + "[?61;4;6c" + ESC + "[>0;10;1c"
        self.assertEqual(events(answer + answer, "y"), ["y"])

    def test_a_longer_message(self):
        self.assertEqual(events(ESC + "P>|tmux 3.5a" + ESC + "\\", "a"), ["a"])

    def test_an_answer_that_arrives_in_two_pieces(self):
        # The rest came within the wait, so the reader simply went on reading.
        self.assertEqual(events(ESC + "]11;rgb:0c0c/0c", "0c/0c0c" + ESC + "\\", "a"), ["a"])

    def test_an_answer_that_breaks_off_is_dropped_as_far_as_it_came(self):
        self.assertEqual(events(ESC + "]11;rgb:0c0c", None, "a"), ["a"])
        self.assertEqual(events(ESC + "[?61;4", None, "a"), ["a"])


class PastedText(unittest.TestCase):
    def test_a_paste_arrives_as_one_event(self):
        self.assertEqual(events(ESC + "[200~one\rtwo\r\nthree" + ESC + "[201~", "x"),
                         [Paste("one\ntwo\nthree"), "x"])

    def test_keys_inside_a_paste_are_text(self):
        # Without the marks, the letters would press buttons and Enter would send.
        self.assertEqual(events(ESC + "[200~q\ty" + ESC + "[201~"), [Paste("q\ty")])

    def test_a_paste_that_never_ends_gives_what_came(self):
        self.assertEqual(events(ESC + "[200~half", None), [Paste("half")])

    def test_an_empty_paste(self):
        self.assertEqual(events(ESC + "[200~" + ESC + "[201~"), [Paste("")])


class MouseReports(unittest.TestCase):
    def test_a_click(self):
        self.assertEqual(events(ESC + "[<0;10;5M"), [Mouse("click", 4, 9)])

    def test_letting_go_is_not_a_second_click(self):
        self.assertEqual(events(ESC + "[<0;10;5M", ESC + "[<0;10;5m"), [Mouse("click", 4, 9)])

    def test_the_wheel(self):
        self.assertEqual(events(ESC + "[<64;3;7M", ESC + "[<65;3;7M"),
                         [Mouse("wheel_up", 6, 2), Mouse("wheel_down", 6, 2)])

    def test_other_buttons_and_dragging_mean_nothing(self):
        self.assertEqual(events(ESC + "[<2;3;7M", ESC + "[<32;3;7M", "a"), ["a"])

    def test_the_older_way_of_reporting(self):
        self.assertEqual(events(ESC + "[M" + chr(32) + chr(33 + 9) + chr(33 + 4)),
                         [Mouse("click", 4, 9)])
        self.assertEqual(events(ESC + "[M" + chr(35) + chr(42) + chr(37), "a"), ["a"])  # let go
        self.assertEqual(events(ESC + "[M" + chr(96) + chr(33) + chr(33)),
                         [Mouse("wheel_up", 0, 0)])


class Drawing(unittest.TestCase):
    def setUp(self):
        self.screen = FakeScreen(4, 10)

    def test_text_is_cut_at_the_right_edge(self):
        self.screen.put(1, 6, "abcdefgh")
        self.assertEqual(self.screen.line(1), "      abcd")

    def test_text_left_of_the_screen_loses_its_start(self):
        self.screen.put(0, -2, "abcdef")
        self.assertEqual(self.screen.line(0), "cdef")

    def test_rows_off_the_screen_are_ignored(self):
        self.screen.put(-1, 0, "above")
        self.screen.put(4, 0, "below")
        self.screen.put(2, 10, "beside")
        self.assertEqual(self.screen.text().strip(), "")

    def test_half_a_wide_character_is_not_drawn(self):
        self.screen.put(0, 7, "a" + WIDE + WIDE)
        self.assertEqual(self.screen.line(0), "       a" + WIDE)

    def test_control_characters_are_shown_as_placeholders(self):
        self.screen.put(0, 0, "a\tb\x00c")
        self.assertEqual(self.screen.line(0), "a b?c")

    def test_a_box(self):
        self.screen.box(0, 1, 3, 5)
        self.assertEqual(self.screen.text(), " +---+\n |   |\n +---+\n")

    def test_a_box_too_small_to_have_an_inside_is_not_drawn(self):
        self.screen.box(0, 0, 1, 5)
        self.screen.box(0, 0, 3, 1)
        self.assertEqual(self.screen.text().strip(), "")

    def test_a_line_across_with_ends(self):
        self.screen.hline(1, 0, 6, tees=True)
        self.screen.hline(2, 0, 3)
        self.assertEqual(self.screen.line(1), "+----+")
        self.assertEqual(self.screen.line(2), "---")

    def test_fill(self):
        self.screen.fill(1, 2, 2, 3, "bar")
        self.assertEqual(self.screen.styles[1][2:6], ["bar", "bar", "bar", "normal"])
        self.assertEqual(self.screen.styles[3][2], "normal")


if __name__ == "__main__":
    unittest.main()
