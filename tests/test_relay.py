"""The relay folder's files, and a file that is in use on Windows."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import relay


class RelayFiles(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_a_question_and_its_reply(self):
        relay.write_request(self.folder, 2, "Proceed?")
        self.assertEqual(relay.read_request(self.folder)["text"], "Proceed?")
        self.assertIsNone(relay.read_reply(self.folder, 2))
        relay.write_reply(self.folder, 1, "late, for an earlier question")
        self.assertIsNone(relay.read_reply(self.folder, 2))
        relay.write_reply(self.folder, 2, "yes")
        self.assertEqual(relay.read_reply(self.folder, 2), "yes")
        relay.clear(self.folder)
        self.assertIsNone(relay.read_request(self.folder))
        self.assertEqual(list(self.folder.iterdir()), [])
        relay.clear(self.folder)  # nothing there: no error

    def in_use(self, times):
        """A stand-in for os.replace that fails `times` times as Windows does
        while the other side has the file open, then works."""
        real = relay.os.replace
        calls = []

        def replace(source, target):
            calls.append(target)
            if len(calls) <= times:
                raise PermissionError(13, "The process cannot access the file")
            return real(source, target)
        return calls, replace

    def test_a_file_in_use_is_written_a_moment_later(self):
        calls, replace = self.in_use(3)
        with mock.patch.object(relay.os, "replace", replace), \
                mock.patch.object(relay.time, "sleep"):
            relay.write_reply(self.folder, 1, "yes")
        self.assertEqual(len(calls), 4)
        self.assertEqual(relay.read_reply(self.folder, 1), "yes")

    def test_a_file_in_use_is_removed_a_moment_later(self):
        relay.write_request(self.folder, 1, "Proceed?")
        real = Path.unlink
        calls = []

        def unlink(path, *args, **kwargs):
            calls.append(path.name)
            if len(calls) <= 2:
                raise PermissionError(13, "The process cannot access the file")
            return real(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", unlink), mock.patch.object(relay.time, "sleep"):
            relay.clear(self.folder)
        self.assertEqual(calls[:3], [relay.REQUEST] * 3)
        self.assertIsNone(relay.read_request(self.folder))

    def test_a_file_that_stays_in_use_is_an_error_and_leaves_no_temp_file(self):
        calls, replace = self.in_use(10 ** 6)
        with mock.patch.object(relay.os, "replace", replace), \
                mock.patch.object(relay.time, "sleep"):
            with self.assertRaises(PermissionError):
                relay.write_reply(self.folder, 1, "yes")
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
