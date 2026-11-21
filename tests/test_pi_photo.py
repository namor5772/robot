"""scripts/pi_photo.py: a photo from the Pi, made viewable on a PC.

No Pi and no network: ssh and scp are replaced by a stand-in that writes down
how it was called and puts a made-up photo where scp would have put it.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("pi_photo", REPO / "scripts" / "pi_photo.py")
pi_photo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pi_photo)


def segment(marker, body):
    return b"\xff" + bytes([marker]) + (len(body) + 2).to_bytes(2, "big") + body


def photo_bytes(tables=False):
    """A file with a JPEG's segments in a webcam frame's order (not a picture)."""
    parts = [
        b"\xff\xd8",
        segment(0xE0, b"AVI1" + bytes(10)),
        segment(0xDB, bytes(65)),
        segment(0xC0, bytes(15)),
    ]
    if tables:
        parts.append(segment(0xC4, bytes(30)))
    # The picture data may hold bytes that look like a marker: FF C4 here.
    parts += [segment(0xDA, bytes(10)), b"\x12\x34\xff\xc4\x56", b"\xff\xd9"]
    return b"".join(parts)


class TablesCase(unittest.TestCase):
    def test_the_tables_in_the_script_are_sound(self):
        pi_photo.check_tables()

    def test_a_mistyped_table_is_caught(self):
        good = pi_photo.TABLES[1]
        values = bytearray(good[2])
        values[5] = values[6]  # one value twice, another missing
        pi_photo.TABLES[1] = (good[0], good[1], bytes(values))
        self.addCleanup(pi_photo.TABLES.__setitem__, 1, good)
        with self.assertRaises(ValueError):
            pi_photo.check_tables()

    def test_the_segment_is_the_standard_420_bytes(self):
        tables = pi_photo.huffman_segment()
        self.assertEqual(len(tables), 420)
        self.assertEqual(tables[:4], b"\xff\xc4\x01\xa2")


class WithHuffmanTablesCase(unittest.TestCase):
    def test_tables_go_in_just_before_the_picture_data(self):
        data = photo_bytes()
        fixed = pi_photo.with_huffman_tables(data)
        tables = pi_photo.huffman_segment()
        scan_at = data.index(b"\xff\xda")
        self.assertEqual(fixed, data[:scan_at] + tables + data[scan_at:])

    def test_everything_else_is_left_as_it_was(self):
        data = photo_bytes()
        fixed = pi_photo.with_huffman_tables(data)
        self.assertEqual(fixed.replace(pi_photo.huffman_segment(), b""), data)

    def test_a_file_that_has_tables_is_handed_back_untouched(self):
        data = photo_bytes(tables=True)
        self.assertIs(pi_photo.with_huffman_tables(data), data)

    def test_marker_bytes_in_the_picture_data_do_not_count_as_tables(self):
        fixed = pi_photo.with_huffman_tables(photo_bytes())
        markers = [marker for marker, _ in pi_photo.segments(fixed)]
        self.assertEqual(markers, [0xE0, 0xDB, 0xC0, 0xC4, 0xDA])

    def test_what_is_not_a_jpeg_is_refused(self):
        for data in (b"", b"GIF89a" + bytes(20), b"\xff\xd8" + bytes(20)):
            with self.assertRaises(ValueError):
                pi_photo.with_huffman_tables(data)

    def test_a_file_cut_off_before_its_picture_data_is_refused(self):
        data = photo_bytes()
        with self.assertRaises(ValueError):
            pi_photo.with_huffman_tables(data[:data.index(b"\xff\xda")])


class FolderCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def test_an_ordinary_folder_is_taken(self):
        folder = pi_photo.safe_folder(self.tmp / "RobotPhotos", environ={})
        self.assertEqual(folder, self.tmp / "RobotPhotos")

    def test_the_checkout_is_refused(self):
        for folder in (REPO, REPO / "photos", REPO / "tests" / "fixtures"):
            with self.assertRaises(ValueError):
                pi_photo.safe_folder(folder, environ={})

    def test_a_folder_that_onedrive_copies_is_refused(self):
        environ = {"OneDrive": str(self.tmp / "OneDrive")}
        for folder in (self.tmp / "OneDrive", self.tmp / "OneDrive" / "Pictures"):
            with self.assertRaises(ValueError):
                pi_photo.safe_folder(folder, environ=environ)
        pi_photo.safe_folder(self.tmp / "OneDriveNot", environ=environ)


class FetchCase(unittest.TestCase):
    """The whole job, with a stand-in for ssh and scp."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name).resolve() / "RobotPhotos"
        self.calls = []
        self.said = []
        self.shown = []
        self.on_pi = {"photo_b.jpg": photo_bytes(), "photo_a.jpg": photo_bytes(tables=True)}
        self.newest = "/home/someone/robot-photos/photo_b.jpg"

    def run_program(self, arguments):
        self.calls.append(arguments)
        if arguments[0] == "ssh":
            return 0, self.newest
        source, target = arguments[-2], Path(arguments[-1])
        name = source.rsplit("/", 1)[-1]
        if name not in self.on_pi:
            return 1, "scp: %s: No such file or directory" % name
        (target / name).write_bytes(self.on_pi[name])
        return 0, ""

    def fetch(self, **options):
        options.setdefault("folder", self.folder)
        return pi_photo.fetch_and_show(
            run=self.run_program, show=lambda path: self.shown.append(path) or True,
            say=self.said.append, environ={}, **options)

    def test_the_newest_photo_is_copied_made_viewable_and_shown(self):
        result = self.fetch()
        self.assertEqual(result, self.folder / "photo_b_viewable.jpg")
        self.assertEqual(self.shown, [result])
        # The photo as it came is kept beside the copy that is shown.
        self.assertEqual((self.folder / "photo_b.jpg").read_bytes(), photo_bytes())
        self.assertEqual(result.read_bytes(), pi_photo.with_huffman_tables(photo_bytes()))

    def test_the_pi_is_only_asked_and_copied_from(self):
        self.fetch()
        ssh, scp = self.calls
        self.assertEqual(ssh[0], "ssh")
        self.assertEqual(ssh[-2], "pi")
        self.assertIn("ls -t robot-photos/*.jpg", ssh[-1])
        self.assertNotIn("rm", ssh[-1].split())
        self.assertEqual(scp[0], "scp")
        self.assertEqual(scp[-2], "pi:" + self.newest)
        for call in self.calls:
            self.assertIn("BatchMode=yes", call)

    def test_a_named_photo_is_copied_without_asking_for_the_newest(self):
        result = self.fetch(name="photo_a.jpg")
        self.assertEqual([call[0] for call in self.calls], ["scp"])
        self.assertEqual(self.calls[0][-2], "pi:robot-photos/photo_a.jpg")
        # It has its tables, so it is shown as it is and no copy is made.
        self.assertEqual(result, self.folder / "photo_a.jpg")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["photo_a.jpg"])

    def test_a_name_must_not_be_a_path(self):
        for name in ("../secret.jpg", "sub/photo.jpg", "..\\photo.jpg"):
            with self.assertRaises(RuntimeError):
                self.fetch(name=name)
        self.assertEqual(self.calls, [])

    def test_a_photo_the_pi_does_not_have_is_an_error(self):
        with self.assertRaises(RuntimeError) as caught:
            self.fetch(name="photo_none.jpg")
        self.assertIn("No such file", str(caught.exception))
        self.assertEqual(self.shown, [])

    def test_no_photo_on_the_pi_is_an_error(self):
        self.newest = ""
        with self.assertRaises(RuntimeError):
            self.fetch()

    def test_a_file_already_here_is_made_viewable_where_it_is(self):
        self.folder.mkdir(parents=True)
        photo = self.folder / "old.jpg"
        photo.write_bytes(photo_bytes())
        result = self.fetch(local=photo)
        self.assertEqual(result, self.folder / "old_viewable.jpg")
        self.assertEqual(self.calls, [])

    def test_without_opening_nothing_is_shown(self):
        result = self.fetch(open_it=False)
        self.assertTrue(result.is_file())
        self.assertEqual(self.shown, [])

    def test_photos_are_not_copied_into_the_checkout(self):
        with self.assertRaises(ValueError):
            self.fetch(folder=REPO / "photos")
        self.assertEqual(self.calls, [])
        self.assertFalse((REPO / "photos").exists())


if __name__ == "__main__":
    unittest.main()
