"""Tests for robot.datastore: the data folder layout and the atomic JSON stores.

Everything is written inside a temporary folder that is removed afterwards.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import datastore
from robot.datastore import (
    DataDir,
    StoreUnreadableError,
    atomic_write_text,
    load_store,
    save_store,
    store_unreadable,
)


class TempDirCase(unittest.TestCase):
    """Gives each test a folder of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def names(self, folder=None):
        return sorted(p.name for p in (folder or self.dir).iterdir())

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))


class SaveStoreTests(TempDirCase):

    def test_round_trip_keeps_non_ascii_text_readable(self):
        path = self.dir / "store.json"
        data = {"caf\u00e9": {"text": "\u00fcber"}}
        save_store(path, data)
        self.assertEqual(self.read_json(path), data)
        # Written as the characters themselves, not as \u escapes.
        self.assertIn("caf\u00e9", path.read_text(encoding="utf-8"))

    def test_the_file_is_indented_json_with_lf_newlines(self):
        path = self.dir / "store.json"
        data = {"a": {"b": [1, 2]}, "c": "x"}
        save_store(path, data)
        raw = path.read_bytes()
        self.assertEqual(raw.decode("utf-8"), json.dumps(data, indent=2, ensure_ascii=False))
        self.assertIn(b"\n", raw)
        self.assertNotIn(b"\r", raw)

    def test_saving_again_replaces_the_content(self):
        path = self.dir / "store.json"
        save_store(path, {"a": 1, "gone": True})
        save_store(path, {"a": 2})
        self.assertEqual(self.read_json(path), {"a": 2})

    def test_no_temp_file_is_left_behind(self):
        path = self.dir / "store.json"
        save_store(path, {"a": 1})
        save_store(path, {"a": 2})
        self.assertEqual(self.names(), ["store.json"])

    def test_missing_parent_folders_are_created(self):
        path = self.dir / "one" / "two" / "store.json"
        save_store(path, {"a": 1})
        self.assertEqual(self.read_json(path), {"a": 1})

    def test_a_parent_folder_removed_since_the_last_save_is_recreated(self):
        folder = self.dir / "data"
        path = folder / "store.json"
        save_store(path, {"a": 1})
        path.unlink()
        folder.rmdir()
        save_store(path, {"a": 2})
        self.assertEqual(self.read_json(path), {"a": 2})

    def test_the_path_may_be_text_or_a_path_object(self):
        save_store(str(self.dir / "as_text.json"), {"a": 1})
        save_store(self.dir / "as_path.json", {"a": 2})
        self.assertEqual(self.read_json(self.dir / "as_text.json"), {"a": 1})
        self.assertEqual(self.read_json(self.dir / "as_path.json"), {"a": 2})

    def test_the_content_is_forced_to_disk_before_the_swap(self):
        path = self.dir / "store.json"
        order = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            order.append("fsync")
            return real_fsync(fd)

        def replace(src, dst):
            order.append("replace")
            return real_replace(src, dst)

        with mock.patch.object(datastore.os, "fsync", fsync), \
                mock.patch.object(datastore.os, "replace", replace):
            save_store(path, {"a": 1})
        self.assertEqual(order, ["fsync", "replace"])
        self.assertEqual(self.read_json(path), {"a": 1})

    def test_the_temporary_file_is_beside_the_store(self):
        # A move is only atomic within one file system, so the temporary file
        # has to be in the store's own folder, not in the system's temp folder.
        folder = self.dir / "data"
        path = folder / "store.json"
        moves = []
        real_replace = os.replace

        def replace(src, dst):
            moves.append((Path(src), Path(dst)))
            return real_replace(src, dst)

        with mock.patch.object(datastore.os, "replace", replace):
            save_store(path, {"a": 1})
        ((src, dst),) = moves
        self.assertEqual(dst, path)
        self.assertEqual(src.parent, folder)
        self.assertNotEqual(src.name, path.name)

    def test_data_json_cannot_hold_changes_nothing(self):
        path = self.dir / "store.json"
        save_store(path, {"a": 1})
        with self.assertRaises(TypeError):
            save_store(path, {"a": object()})
        self.assertEqual(self.read_json(path), {"a": 1})
        self.assertEqual(self.names(), ["store.json"])

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(self):
        path = self.dir / "store.json"
        save_store(path, {"a": 1})
        # Half of a surrogate pair cannot be encoded as UTF-8, so the write
        # fails after the temporary file has been created.
        with self.assertRaises(UnicodeEncodeError):
            save_store(path, {"a": "broken \ud83d"})
        self.assertEqual(self.read_json(path), {"a": 1})
        self.assertEqual(self.names(), ["store.json"])

    def test_a_failed_swap_keeps_the_old_file_and_leaves_no_temp_file(self):
        path = self.dir / "store.json"
        save_store(path, {"a": 1})
        with mock.patch.object(datastore.os, "replace", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                save_store(path, {"a": 2})
        self.assertEqual(self.read_json(path), {"a": 1})
        self.assertEqual(self.names(), ["store.json"])


class AtomicWriteTextTests(TempDirCase):

    def test_text_is_written_as_utf8_with_lf_newlines(self):
        path = self.dir / "note.txt"
        text = "one\ntwo \u2603\n"
        atomic_write_text(path, text)
        # Exactly these bytes: no \r\n on Windows, no byte order mark.
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_an_existing_file_is_replaced_and_no_temp_file_is_left(self):
        path = self.dir / "note.txt"
        atomic_write_text(path, "a long first version\n")
        atomic_write_text(path, "second\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "second\n")
        self.assertEqual(self.names(), ["note.txt"])

    def test_missing_parent_folders_are_created(self):
        path = self.dir / "one" / "two" / "note.txt"
        atomic_write_text(str(path), "x")
        self.assertEqual(path.read_text(encoding="utf-8"), "x")

    def test_a_bare_file_name_is_written_in_the_current_folder(self):
        before = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, before)  # runs before the folder is removed
        atomic_write_text("note.txt", "x")
        self.assertEqual((self.dir / "note.txt").read_text(encoding="utf-8"), "x")
        self.assertEqual(self.names(), ["note.txt"])

    def test_empty_text_makes_an_empty_file(self):
        path = self.dir / "note.txt"
        atomic_write_text(path, "")
        self.assertEqual(path.read_bytes(), b"")


class LoadStoreTests(TempDirCase):

    def setUp(self):
        super().setUp()
        self.path = self.dir / "store.json"

    def test_a_saved_store_loads_back(self):
        data = {"Tidy Logs": {"text": "do it", "n": [1, 2]}}
        save_store(self.path, data)
        self.assertEqual(load_store(self.path), data)
        self.assertEqual(load_store(str(self.path)), data)

    def test_a_missing_file_reads_as_empty(self):
        self.assertEqual(load_store(self.path), {})
        self.assertEqual(load_store(self.dir / "no_such_folder" / "store.json"), {})

    def test_an_empty_file_reads_as_empty(self):
        self.path.write_bytes(b"")
        self.assertEqual(load_store(self.path), {})

    def test_garbage_reads_as_empty(self):
        for text in ("{not json", "hello", '{"a": 1,}', '{"a": 1} trailing'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertEqual(load_store(self.path), {})

    def test_json_that_is_not_an_object_reads_as_empty(self):
        for text in ("[1, 2]", '"text"', "42", "null", "true"):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertEqual(load_store(self.path), {})

    def test_bytes_that_are_not_utf8_read_as_empty(self):
        self.path.write_bytes(b'{"Caf\xe9": {"text": "a"}}')
        self.assertEqual(load_store(self.path), {})

    def test_a_folder_at_the_path_reads_as_empty(self):
        self.path.mkdir()
        self.assertEqual(load_store(self.path), {})

    def test_loading_never_changes_the_file(self):
        broken = b'{"a": {"text": "x"},}'
        self.path.write_bytes(broken)
        load_store(self.path)
        self.assertEqual(self.path.read_bytes(), broken)
        self.assertEqual(self.names(), ["store.json"])


class StoreUnreadableTests(TempDirCase):

    def setUp(self):
        super().setUp()
        self.path = self.dir / "store.json"

    def test_a_missing_file_is_not_unreadable(self):
        self.assertFalse(store_unreadable(self.path))
        self.assertFalse(store_unreadable(self.dir / "no_such_folder" / "store.json"))

    def test_a_valid_store_is_not_unreadable(self):
        save_store(self.path, {"Tidy Logs": {"text": "do it"}})
        self.assertFalse(store_unreadable(self.path))
        self.assertFalse(store_unreadable(str(self.path)))

    def test_a_store_emptied_on_purpose_is_not_unreadable(self):
        self.path.write_text("{}", encoding="utf-8")
        self.assertFalse(store_unreadable(self.path))

    def test_an_empty_file_is_not_unreadable(self):
        self.path.write_bytes(b"")
        self.assertFalse(store_unreadable(self.path))

    def test_a_blank_file_is_not_unreadable(self):
        self.path.write_bytes(b" \r\n\t\n")
        self.assertFalse(store_unreadable(self.path))

    def test_a_typo_makes_the_store_unreadable(self):
        # The slip an edit by hand tends to leave: a comma before the last brace.
        self.path.write_text(
            '{"Tidy Logs": {"text": "a"}, "Check Sensors": {"text": "b"},}', encoding="utf-8"
        )
        self.assertTrue(store_unreadable(self.path))

    def test_half_a_file_is_unreadable(self):
        self.path.write_text('{"Tidy Logs": {"text": "a', encoding="utf-8")
        self.assertTrue(store_unreadable(self.path))

    def test_json_that_is_not_an_object_is_unreadable(self):
        for text in ("[1, 2]", '"text"', "42", "null", "true"):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertTrue(store_unreadable(self.path))

    def test_bytes_that_are_not_utf8_are_unreadable(self):
        self.path.write_bytes(b'{"Caf\xe9": {"text": "a"}}')
        self.assertTrue(store_unreadable(self.path))

    def test_a_folder_at_the_path_is_unreadable(self):
        self.path.mkdir()
        self.assertTrue(store_unreadable(self.path))

    def test_an_unreadable_store_loads_as_empty_and_is_left_alone(self):
        # The pair a caller relies on: load_store() serves {} for such a file,
        # and store_unreadable() is how the caller knows not to save over it.
        broken = '{"Tidy Logs": {"text": "a"},}'
        self.path.write_text(broken, encoding="utf-8")
        self.assertEqual(load_store(self.path), {})
        self.assertTrue(store_unreadable(self.path))
        self.assertEqual(self.path.read_text(encoding="utf-8"), broken)

    def test_the_error_for_a_refused_save_is_an_exception(self):
        self.assertTrue(issubclass(StoreUnreadableError, Exception))
        with self.assertRaises(StoreUnreadableError):
            raise StoreUnreadableError("the store could not be read")


class DataDirTests(TempDirCase):

    def patched_env(self, **values):
        """The environment with the data-folder variable removed, then `values` set."""
        patcher = mock.patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        if datastore.DATA_DIR_ENV not in values:
            os.environ.pop(datastore.DATA_DIR_ENV, None)

    def patched_home(self, home):
        patcher = mock.patch.object(Path, "home", return_value=Path(home))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_variable_is_named_as_documented(self):
        self.assertEqual(datastore.DATA_DIR_ENV, "ROBOT_DATA_DIR")

    def test_the_default_is_robot_data_in_the_home_folder(self):
        self.patched_env()
        self.patched_home(self.dir)
        self.assertEqual(DataDir().root, self.dir / "robot-data")

    def test_the_environment_variable_overrides_the_default(self):
        self.patched_env(ROBOT_DATA_DIR=str(self.dir / "from_env"))
        self.patched_home(self.dir / "home")
        self.assertEqual(DataDir().root, self.dir / "from_env")

    def test_an_explicit_root_wins_over_the_environment(self):
        self.patched_env(ROBOT_DATA_DIR=str(self.dir / "from_env"))
        self.patched_home(self.dir / "home")
        self.assertEqual(DataDir(self.dir / "given").root, self.dir / "given")
        self.assertEqual(DataDir(str(self.dir / "given")).root, self.dir / "given")

    def test_an_empty_variable_counts_as_not_set(self):
        self.patched_home(self.dir)
        for value in ("", "   "):
            with self.subTest(value=value):
                self.patched_env(ROBOT_DATA_DIR=value)
                self.assertEqual(DataDir().root, self.dir / "robot-data")

    def test_a_tilde_in_the_variable_means_the_home_folder(self):
        # HOME is what Linux reads and USERPROFILE what Windows reads.
        self.patched_env(ROBOT_DATA_DIR="~/elsewhere", HOME=str(self.dir),
                         USERPROFILE=str(self.dir))
        self.assertEqual(DataDir().root, self.dir / "elsewhere")

    def test_the_root_is_always_absolute(self):
        self.assertTrue(DataDir("some/relative/place").root.is_absolute())
        self.assertEqual(DataDir("some/relative/place").root,
                         Path(os.getcwd()) / "some" / "relative" / "place")

    def test_the_layout(self):
        with mock.patch.object(datastore.socket, "gethostname", return_value="robot"):
            data = DataDir(self.dir)
        self.assertEqual(data.root, self.dir)
        self.assertEqual(data.instructions_file, self.dir / "agent_instructions.json")
        self.assertEqual(data.skills_dir, self.dir / "skills")
        self.assertEqual(data.chats_dir, self.dir / "saved_chats")
        self.assertEqual(data.costlog_file, self.dir / "APICostLog_robot.txt")
        self.assertEqual(data.runs_dir, self.dir / "runs")
        self.assertEqual(data.tmp_dir, self.dir / "tmp")
        for value in vars(data).values():
            self.assertIsInstance(value, Path)

    def test_the_host_name_is_made_safe_for_a_file_name(self):
        cases = [
            ("robot.local", "APICostLog_robot.local.txt"),
            ("My-Host_01", "APICostLog_My-Host_01.txt"),
            ("my host/01", "APICostLog_my_host_01.txt"),
            ("two  spaces", "APICostLog_two__spaces.txt"),  # one underscore for each
            ("a\\b:c*d", "APICostLog_a_b_c_d.txt"),
            ("caf\u00e9", "APICostLog_caf_.txt"),
        ]
        for host, expected in cases:
            with self.subTest(host=host):
                with mock.patch.object(datastore.socket, "gethostname", return_value=host):
                    self.assertEqual(DataDir(self.dir).costlog_file.name, expected)

    def test_no_host_name_falls_back_to_robot(self):
        with mock.patch.object(datastore.socket, "gethostname", return_value=""):
            self.assertEqual(DataDir(self.dir).costlog_file.name, "APICostLog_robot.txt")
        with mock.patch.object(datastore.socket, "gethostname", side_effect=OSError("no name")):
            self.assertEqual(DataDir(self.dir).costlog_file.name, "APICostLog_robot.txt")

    def test_creating_the_object_creates_nothing_on_disk(self):
        root = self.dir / "robot-data"
        self.patched_env()
        self.patched_home(self.dir)
        DataDir()
        DataDir(root)
        self.assertEqual(self.names(), [])

    def test_ensure_creates_the_folders_and_no_files(self):
        root = self.dir / "deep" / "robot-data"
        data = DataDir(root)
        data.ensure()
        self.assertEqual(self.names(root), ["runs", "saved_chats", "skills", "tmp"])
        for name in self.names(root):
            self.assertTrue((root / name).is_dir())
        self.assertFalse(data.instructions_file.exists())
        self.assertFalse(data.costlog_file.exists())

    def test_ensure_can_run_again_and_keeps_what_is_there(self):
        data = DataDir(self.dir / "robot-data")
        data.ensure()
        save_store(data.instructions_file, {"Default": {"text": "hello"}})
        (data.chats_dir / "kept.txt").write_text("kept", encoding="utf-8")
        data.ensure()
        self.assertEqual(load_store(data.instructions_file), {"Default": {"text": "hello"}})
        self.assertEqual((data.chats_dir / "kept.txt").read_text(encoding="utf-8"), "kept")


if __name__ == "__main__":
    unittest.main()
