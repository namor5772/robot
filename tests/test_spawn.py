"""run_instruction, with a small stand-in program playing the child run."""

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from robot import instructions, relay, spawn
from robot.datastore import DataDir
from tests.fakes import NoWaitInterrupts, Obj

# Plays the part of `python -m robot.main`: it takes the same options and acts
# according to the instruction's name. It never touches the network.
STAND_IN = textwrap.dedent('''
    import argparse, json, os, sys, time
    sys.path.insert(0, os.getcwd())
    from robot import relay

    parser = argparse.ArgumentParser()
    parser.add_argument("-l")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--result-file")
    parser.add_argument("--extra-file")
    parser.add_argument("--prepend-file")
    parser.add_argument("--relay-dir")
    args = parser.parse_args()

    def read(path):
        return open(path, encoding="utf-8").read() if path else ""

    def ask(seq, question):
        relay.write_request(args.relay_dir, seq, question)
        for _ in range(200):
            reply = relay.read_reply(args.relay_dir, seq)
            if reply is not None:
                relay.clear(args.relay_dir)
                return reply
            time.sleep(0.05)
        return None

    def finish(status, text, error=""):
        if args.result_file:
            with open(args.result_file, "w", encoding="utf-8") as out:
                json.dump({"instruction": args.l, "status": status, "error": error,
                           "final_text": text}, out)
        sys.exit(0)

    name = args.l
    if name == "Echo":
        finish("completed", "extra=%r prepend=%r headless=%r depth=%s family=%s" % (
            read(args.extra_file), read(args.prepend_file), args.headless,
            os.environ.get("ROBOT_SPAWN_DEPTH"), os.environ.get("ROBOT_SPAWN_FAMILY")))
    if name == "Family":
        # A child that starts children of its own, as a real child run with
        # Meta on can. It says what came of that in a file, then stays until
        # its children have gone, as a run that waits for them would.
        from robot import spawn
        from robot.datastore import DataDir
        spawn.CHILD_COMMAND = [sys.executable, os.path.abspath(__file__)]
        spawn.MAX_CHILDREN = int(os.environ["TEST_MAX_CHILDREN"])
        spawn.available_memory_mb = lambda: 64000
        spawn._resident_mb = lambda pid: 80
        spawn._POLL_SECONDS = 0.05

        class Me:
            datadir = DataDir(os.environ["TEST_DATA_DIR"])

        replies = [spawn.run_instruction(Me(), {"name": "Slow"})
                   for _ in range(int(os.environ["TEST_GRANDCHILDREN"]))]
        with open(os.environ["TEST_REPORT"] + ".part", "w", encoding="utf-8") as out:
            json.dump(replies, out)
        os.replace(os.environ["TEST_REPORT"] + ".part", os.environ["TEST_REPORT"])
        while spawn.alive_children():
            time.sleep(0.05)
        time.sleep(0.3)   # the helper threads tidy up after the children
        finish("completed", "family done")
    if name == "Ask":
        first = ask(1, "Proceed?")
        if not first:
            finish("stopped", "no answer to the first question")
        second = ask(2, "Are you sure?")
        if not second:
            finish("stopped", "first=%r, then no answer" % first)
        finish("completed", "first=%r second=%r" % (first, second))
    if name == "Chatty":
        # Writes something, as a run does, then asks: whoever answers can
        # look at what has been written so far.
        print("hello from the child", flush=True)
        reply = ask(1, "Seen it?")
        print("the child heard %r" % reply, flush=True)
        finish("completed", "reply=%r" % reply)
    if name == "Slow":
        time.sleep(60)
    if name == "Crash":
        sys.stderr.write("Traceback: something broke badly\\n")
        sys.exit(3)
    if name == "Long":
        finish("completed", "x" * 30000)
    if name == "Failed":
        finish("error", "", error="the model's reply was cut off")
''')


LINUX = sys.platform.startswith("linux")


class SpawnCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.datadir = DataDir(root / "data")
        self.datadir.ensure()
        instructions.save_instructions(self.datadir, {
            name: {"text": "x"}
            for name in ("Echo", "Ask", "Slow", "Crash", "Long", "Failed", "Family",
                         "Chatty")})
        script = root / "stand_in.py"
        script.write_text(STAND_IN, encoding="utf-8")
        # Each test is a first run of its own: no tree name is handed down to
        # it, and it makes one up that no other test has.
        environment = mock.patch.dict(os.environ, {spawn.DEPTH_ENV: "0"})
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(spawn.FAMILY_ENV, None)
        patches = (
            mock.patch.object(spawn, "CHILD_COMMAND", [sys.executable, str(script)]),
            mock.patch.object(spawn, "_children", []),
            mock.patch.object(spawn, "_family_name", ""),
            mock.patch.object(spawn, "_POLL_SECONDS", 0.05),
            mock.patch.object(spawn, "_STOP_GRACE_SECONDS", 3),
            # As where the free memory cannot be read: tests that are about
            # memory say how much there is (MemoryDecides).
            mock.patch.object(spawn, "available_memory_mb", lambda: None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.stopping = False
        self.asked = []
        self.person = []
        self.to_kill = []
        self.notes = []
        self.agent = Obj(datadir=self.datadir,
                         console=Obj(interrupts=NoWaitInterrupts(), note=self.notes.append),
                         stop_requested=lambda: self.stopping, ask_from_pool=self.ask)

    def ask(self, question):
        self.asked.append(question)
        return self.person.pop(0) if self.person else None

    def run_it(self, **params):
        return spawn.run_instruction(self.agent, params)

    def leftovers(self):
        return sorted(path.name for path in self.datadir.tmp_dir.iterdir())

    def wait_until(self, condition, seconds=10):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.05)
        return condition()

    def memory(self, available, held):
        """Say how much memory is available, and how much each child holds:
        a number of MB for all of them, or None for "cannot be read"."""
        for patch in (mock.patch.object(spawn, "available_memory_mb", lambda: available),
                      mock.patch.object(spawn, "_resident_mb", lambda pid: held)):
            patch.start()
            self.addCleanup(patch.stop)

    def start_slow(self, count):
        """Ask for `count` children that would run for a minute. Returns the
        replies. Those that started are killed when the test ends."""
        replies = []
        for _ in range(count):
            reply = self.run_it(name="Slow")
            replies.append(reply)
            self.kill_later(reply)
        return replies

    def kill_later(self, reply):
        """Have the child a reply tells of killed when the test ends."""
        if "(PID " not in reply:
            return
        if not self.to_kill:
            self.addCleanup(self.kill_them)
        self.to_kill.append(int(reply.split("(PID ")[1].split(")")[0]))

    def kill_them(self):
        for pid in self.to_kill:
            try:
                if os.name == "posix":
                    os.kill(pid, 9)
                else:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True)
            except OSError:
                pass
        # Let the helper threads notice and tidy up before the folder is removed.
        self.wait_until(lambda: self.leftovers() == [], seconds=5)


class Refusals(SpawnCase):
    def test_a_name_is_required_and_must_exist(self):
        self.assertEqual(self.run_it(), "Error: 'name' is required.")
        self.assertEqual(self.run_it(name="Nope"),
                         "Error: Instruction 'Nope' not found. Available: Ask, Chatty, Crash, Echo, "
                         "Failed, Family, Long, Slow")

    def test_answers_must_be_a_list_of_strings(self):
        shown = self.run_it(name="Echo", answers=[1, 2])
        self.assertTrue(shown.startswith("Error: 'answers' must be a list of strings"))

    def test_a_child_of_a_child_cannot_start_children(self):
        with mock.patch.dict(os.environ, {spawn.DEPTH_ENV: str(spawn.MAX_DEPTH)}):
            self.assertIn("cannot start further child runs", self.run_it(name="Echo", wait=True))

    def test_too_little_free_memory_refuses_the_start(self):
        with mock.patch.object(spawn, "available_memory_mb", lambda: 40):
            shown = self.run_it(name="Echo", wait=True)
        self.assertIn("not enough free memory to start a child run (40 MB available; a child "
                      "run takes about 80 MB and 30 MB must stay free)", shown)
        self.assertEqual(self.leftovers(), [])

    def test_where_the_free_memory_cannot_be_read_two_at_once_is_the_most(self):
        # Not on the Pi, where it can be read and decides (see MemoryDecides).
        first, second = self.start_slow(2)
        self.assertIn("Launched instruction 'Slow'", first)
        self.assertIn("Launched instruction 'Slow'", second)
        third = self.run_it(name="Echo", wait=True)
        self.assertIn("2 child runs are already running. How much memory is free cannot be "
                      "read on this computer", third)


class MemoryDecides(SpawnCase):
    """How many children run at once follows from the memory that is free."""

    def test_with_memory_to_spare_more_than_two_run_at_once(self):
        self.memory(available=4000, held=80)
        replies = self.start_slow(3)
        self.assertTrue(all("Launched instruction 'Slow'" in reply for reply in replies),
                        replies)
        self.assertEqual(len(spawn.alive_children()), 3)

    def test_a_child_that_is_still_starting_has_not_taken_its_memory_yet(self):
        # The kernel goes on calling 200 MB available while the children load,
        # as it does on the Pi in their first seconds. Each has 75 MB to take.
        self.memory(available=200, held=5)
        first, second, third = self.start_slow(3)
        self.assertIn("Launched", first)
        self.assertIn("Launched", second)                    # 200 less 75 is still enough
        self.assertIn("not enough free memory to start a child run (200 MB available, but "
                      "about 150 MB of that will go to the 2 child runs still starting; a "
                      "child run takes about 80 MB and 30 MB must stay free)", third)
        self.assertEqual(len(spawn.alive_children()), 2)

    def test_one_child_still_starting_is_said_in_the_singular(self):
        self.memory(available=180, held=5)
        _first, second = self.start_slow(2)
        self.assertIn("about 75 MB of that will go to the 1 child run still starting;", second)

    def test_what_a_loaded_child_holds_is_not_taken_off_twice(self):
        # Once a child has loaded, its memory has come off the available
        # figure. The second fits here because the first is seen as loaded.
        self.memory(available=115, held=77)
        replies = self.start_slow(2)
        self.assertTrue(all("Launched" in reply for reply in replies), replies)

    def test_a_child_whose_memory_cannot_be_read_counts_as_not_loaded(self):
        self.memory(available=180, held=None)
        _first, second = self.start_slow(2)
        self.assertIn("about 80 MB of that will go to the 1 child run still starting", second)

    def test_a_child_that_has_ended_no_longer_counts(self):
        self.memory(available=120, held=5)
        self.assertIn("Launched", self.run_it(name="Echo"))
        self.assertTrue(self.wait_until(lambda: spawn.alive_children() == []))
        self.assertIn("status=completed", self.run_it(name="Echo", wait=True))

    def test_starts_asked_for_in_the_same_moment_are_judged_one_after_the_other(self):
        # The model can ask for several children in one turn, and those calls
        # run side by side. Each must see the children started before it.
        self.memory(available=200, held=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: self.run_it(name="Slow"), range(4)))
        for reply in replies:
            self.kill_later(reply)
        self.assertEqual(sum("Launched" in reply for reply in replies), 2, replies)
        self.assertEqual(sum("not enough free memory" in reply for reply in replies), 2)

    def test_how_much_a_starting_child_has_yet_to_take(self):
        for held, to_take in ((None, 80), (0, 80), (5, 75), (71, 9), (72, 0), (77, 0), (93, 0)):
            with self.subTest(held=held), \
                    mock.patch.object(spawn, "_resident_mb", lambda pid, held=held: held):
                self.assertEqual(spawn._still_to_take(4242), to_take)

    def test_there_is_a_ceiling_however_much_memory_is_free(self):
        # Every child is a run that is paid for. The ceiling is 8; it is set
        # to 3 here so that the test need not start nine processes.
        self.assertEqual(spawn.MAX_CHILDREN, 8)
        self.memory(available=64000, held=80)
        with mock.patch.object(spawn, "MAX_CHILDREN", 3):
            replies = self.start_slow(4)
        self.assertTrue(all("Launched" in reply for reply in replies[:3]), replies)
        self.assertEqual(
            replies[3],
            "Error: 3 child runs are already running in this tree of runs (the first run's "
            "children and the children those started), which is the most at once. Wait for "
            "one to finish and try again, or do the task in this run.")
        self.assertEqual(len(spawn.alive_children()), 3)

    def test_a_child_that_has_ended_makes_room_under_the_ceiling(self):
        self.memory(available=64000, held=80)
        with mock.patch.object(spawn, "MAX_CHILDREN", 1):
            for _ in range(3):
                self.assertIn("status=completed", self.run_it(name="Echo", wait=True))
            (running,) = self.start_slow(1)
            self.assertIn("Launched", running)
            self.assertIn("1 child runs are already running", self.run_it(name="Echo"))

    def test_below_the_ceiling_memory_still_decides(self):
        self.memory(available=100, held=80)
        with mock.patch.object(spawn, "MAX_CHILDREN", 8):
            self.assertIn("not enough free memory", self.run_it(name="Echo", wait=True))

    def test_the_ceiling_counts_starts_asked_for_in_the_same_moment(self):
        self.memory(available=64000, held=5)
        with mock.patch.object(spawn, "MAX_CHILDREN", 2), \
                concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: self.run_it(name="Slow"), range(4)))
        for reply in replies:
            self.kill_later(reply)
        self.assertEqual(sum("Launched" in reply for reply in replies), 2, replies)
        self.assertEqual(sum("2 child runs are already running" in reply for reply in replies),
                         2)

    def test_the_least_free_memory_is_a_child_and_something_to_spare(self):
        self.assertEqual(spawn.MIN_FREE_MB, spawn.CHILD_MB + spawn.SPARE_MB)
        self.memory(available=spawn.MIN_FREE_MB, held=80)
        self.assertIn("status=completed", self.run_it(name="Echo", wait=True))
        self.memory(available=spawn.MIN_FREE_MB - 1, held=80)
        self.assertIn("not enough free memory", self.run_it(name="Echo", wait=True))


class TheWholeTree(SpawnCase):
    """A child can start children of its own. The ceiling and the memory rule
    look at the whole tree, not at one run's own children."""

    def test_a_first_run_makes_up_the_name_of_its_tree_once(self):
        name = spawn.family()
        self.assertTrue(name.startswith(f"{os.getpid()}."), name)
        self.assertEqual(spawn.family(), name)

    def test_a_child_is_told_the_tree_it_belongs_to(self):
        shown = self.run_it(name="Echo", wait=True)
        self.assertIn(f"depth=1 family={spawn.family()}", shown)

    def test_a_child_hands_the_same_name_on_to_its_own_children(self):
        with mock.patch.dict(os.environ, {spawn.FAMILY_ENV: "4242.1", spawn.DEPTH_ENV: "1"}):
            self.assertEqual(spawn.family(), "4242.1")
            shown = self.run_it(name="Echo", wait=True)
        self.assertIn("depth=2 family=4242.1", shown)

    def test_runs_elsewhere_in_the_tree_count_towards_the_ceiling(self):
        # Eight are running, and this run started none of them itself.
        self.memory(available=64000, held=80)
        with mock.patch.object(spawn, "family_members", lambda: list(range(501, 509))):
            shown = self.run_it(name="Echo", wait=True)
        self.assertIn("8 child runs are already running in this tree of runs", shown)
        with mock.patch.object(spawn, "family_members", lambda: list(range(501, 508))):
            self.assertIn("status=completed", self.run_it(name="Echo", wait=True))

    def test_a_run_still_starting_elsewhere_in_the_tree_is_allowed_for(self):
        self.memory(available=200, held=5)
        with mock.patch.object(spawn, "family_members", lambda: [501, 502]):
            shown = self.run_it(name="Echo", wait=True)
        self.assertIn("about 150 MB of that will go to the 2 child runs still starting", shown)

    def test_where_the_tree_cannot_be_seen_a_runs_own_children_are_counted(self):
        self.memory(available=64000, held=80)
        with mock.patch.object(spawn, "family_members", lambda: None), \
                mock.patch.object(spawn, "MAX_CHILDREN", 1):
            (first,) = self.start_slow(1)
            self.assertIn("Launched", first)
            self.assertIn("1 child runs are already running", self.run_it(name="Echo"))

    @unittest.skipUnless(LINUX, "the tree is seen through the kernel's list of processes")
    def test_the_children_of_a_child_count_too(self):
        # A real tree of processes. This run starts one child, then a second
        # that asks for three of its own. Three at once is the most here.
        report = Path(self._tmp.name) / "family-report.json"
        settings = {"TEST_MAX_CHILDREN": "3", "TEST_GRANDCHILDREN": "3",
                    "TEST_DATA_DIR": str(self.datadir.root), "TEST_REPORT": str(report)}
        self.memory(available=64000, held=80)
        with mock.patch.object(spawn, "MAX_CHILDREN", 3), mock.patch.dict(os.environ, settings):
            (first,) = self.start_slow(1)
            self.assertIn("Launched", first)
            self.assertIn("Launched instruction 'Family'", self.run_it(name="Family"))
            self.assertTrue(self.wait_until(report.exists, seconds=30))
            asked = json.loads(report.read_text(encoding="utf-8"))
            for reply in asked:
                self.kill_later(reply)
            in_the_tree = len(spawn.family_members())
            mine = self.run_it(name="Echo")
        # The first child, the second, and the one grandchild it could have.
        self.assertEqual(in_the_tree, 3)
        self.assertEqual(len(spawn.alive_children()), 2)       # of which this run's own: two
        self.assertEqual(sum("Launched instruction 'Slow'" in reply for reply in asked), 1,
                         asked)
        self.assertEqual(
            sum("3 child runs are already running in this tree of runs" in reply
                for reply in asked), 2, asked)
        self.assertIn("3 child runs are already running in this tree of runs", mine)

    @unittest.skipUnless(LINUX, "needs a hold on a folder")
    def test_a_start_waits_while_another_program_of_the_tree_is_starting_one(self):
        import fcntl
        self.datadir.tmp_dir.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.datadir.tmp_dir, os.O_RDONLY)
        fcntl.flock(handle, fcntl.LOCK_EX)                     # the other program, mid-start
        shown = []
        thread = threading.Thread(
            target=lambda: shown.append(self.run_it(name="Echo", wait=True)))
        thread.start()
        try:
            time.sleep(0.6)
            self.assertEqual(shown, [])                        # it is waiting its turn
        finally:
            os.close(handle)
        thread.join(30)
        self.assertIn("status=completed", shown[0])

    @unittest.skipUnless(LINUX, "needs a hold on a folder")
    def test_a_hold_that_is_never_let_go_does_not_stop_starts_for_ever(self):
        import fcntl
        self.datadir.tmp_dir.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.datadir.tmp_dir, os.O_RDONLY)
        self.addCleanup(os.close, handle)
        fcntl.flock(handle, fcntl.LOCK_EX)
        with mock.patch.object(spawn, "_LOCK_WAIT_SECONDS", 0.3):
            self.assertIn("status=completed", self.run_it(name="Echo", wait=True))


class SeeingTheTree(unittest.TestCase):
    """family_members: the child runs of one tree, picked out of the kernel's
    list of processes."""

    COMMAND = ["/venv/bin/python", "-m", "robot.main"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)
        for patch in (mock.patch.object(spawn, "_PROC", self.proc),
                      mock.patch.object(spawn, "CHILD_COMMAND", list(self.COMMAND)),
                      mock.patch.dict(os.environ, {spawn.FAMILY_ENV: "77.1"})):
            patch.start()
            self.addCleanup(patch.stop)

    def process(self, pid, *command, family=None, **environment):
        folder = self.proc / str(pid)
        folder.mkdir()
        (folder / "cmdline").write_bytes(
            b"".join(part.encode() + b"\0" for part in command))
        if family is not None:
            environment[spawn.FAMILY_ENV] = family
        (folder / "environ").write_bytes(
            b"".join(f"{key}={value}".encode() + b"\0" for key, value in environment.items()))

    def test_the_child_runs_of_this_tree(self):
        self.process(10, *self.COMMAND, "-l", "First", "--headless", family="77.1", HOME="/h")
        self.process(11, *self.COMMAND, "-l", "Second", HOME="/h", family="77.1", LANG="C")
        self.assertEqual(sorted(spawn.family_members()), [10, 11])

    def test_runs_of_another_tree_are_not_counted(self):
        self.process(10, *self.COMMAND, "-l", "Theirs", family="88.1")
        self.process(11, *self.COMMAND, "-l", "Nearly", family="77.10")   # starts the same
        self.assertEqual(spawn.family_members(), [])

    def test_a_first_run_is_not_a_child(self):
        # A chat or the interface: nobody handed it the name of a tree.
        self.process(10, "/venv/bin/python", "-m", "robot.main", HOME="/h")
        self.process(11, "/venv/bin/python", "-m", "robot.tui", HOME="/h")
        self.assertEqual(spawn.family_members(), [])

    def test_a_shell_command_started_by_a_child_is_not_a_run(self):
        # It inherits the name of the tree, but it is another program.
        self.process(10, "/bin/bash", "-c", "sleep 60", family="77.1")
        self.process(11, "sleep", "60", family="77.1")
        self.process(12, "/venv/bin/python", "-m", "robot.main_tools", family="77.1")
        self.process(13, "/other/python", "-m", "robot.main", family="77.1")
        self.assertEqual(spawn.family_members(), [])

    def test_what_is_not_a_process_or_cannot_be_read_is_passed_over(self):
        (self.proc / "meminfo").write_text("MemAvailable: 1 kB\n", encoding="ascii")
        (self.proc / "self").mkdir()
        (self.proc / "20").mkdir()                              # gone before it was read
        (self.proc / "21").mkdir()
        (self.proc / "21" / "cmdline").write_bytes(b"\0".join(
            part.encode() for part in self.COMMAND) + b"\0")    # and no environment to read
        self.process(22, *self.COMMAND, family="77.1")
        self.assertEqual(spawn.family_members(), [22])

    def test_a_run_that_has_ended_but_is_not_cleared_away_yet(self):
        self.process(10, family="77.1")                         # no command left: a zombie
        self.assertEqual(spawn.family_members(), [])

    def test_where_there_is_no_list_of_processes(self):
        with mock.patch.object(spawn, "_PROC", self.proc / "nowhere"):
            self.assertIsNone(spawn.family_members())

    def test_a_first_run_looks_for_the_name_it_made_up(self):
        with mock.patch.dict(os.environ), mock.patch.object(spawn, "_family_name", ""):
            del os.environ[spawn.FAMILY_ENV]
            mine = spawn.family()
            self.process(10, *self.COMMAND, family=mine)
            self.process(11, *self.COMMAND, family="77.1")
            self.assertEqual(spawn.family_members(), [10])


class ReadingMemory(unittest.TestCase):
    """The two figures the rule goes by, read from the kernel's /proc."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)
        for patch in (mock.patch.object(spawn, "_PROC", self.proc),
                      mock.patch.object(spawn, "_page_size", lambda: 4096)):
            patch.start()
            self.addCleanup(patch.stop)

    def process(self, pid, statm):
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "statm").write_text(statm, encoding="ascii")

    def test_what_a_process_holds(self):
        self.process(4242, "30000 19712 2000 1 0 9000 0\n")       # 19,712 pages of 4 KB
        self.assertEqual(spawn._resident_mb(4242), 77)

    def test_pages_of_another_size(self):
        # The Pi 5's own kernel has pages of 16 KB.
        self.process(4242, "7500 4928 500 1 0 2250 0\n")
        with mock.patch.object(spawn, "_page_size", lambda: 16384):
            self.assertEqual(spawn._resident_mb(4242), 77)

    def test_a_process_that_is_gone_or_cannot_be_read(self):
        self.assertIsNone(spawn._resident_mb(4242))
        self.process(11, "")
        self.process(12, "not numbers at all\n")
        self.assertIsNone(spawn._resident_mb(11))
        self.assertIsNone(spawn._resident_mb(12))
        self.assertIsNone(spawn._resident_mb(None))

    def test_the_memory_that_is_available(self):
        (self.proc / "meminfo").write_text(
            "MemTotal:         424992 kB\nMemFree:          100000 kB\n"
            "MemAvailable:     281604 kB\n", encoding="ascii")
        self.assertEqual(spawn.available_memory_mb(), 275)

    def test_available_memory_that_cannot_be_read(self):
        self.assertIsNone(spawn.available_memory_mb())             # no such file
        (self.proc / "meminfo").write_text("MemTotal: 424992 kB\n", encoding="ascii")
        self.assertIsNone(spawn.available_memory_mb())             # no such line

    def test_on_this_machine(self):
        with mock.patch.object(spawn, "_PROC", Path("/proc")):
            held = spawn._resident_mb(os.getpid())
            available = spawn.available_memory_mb()
        if sys.platform.startswith("linux"):
            self.assertGreater(held, 5)
            self.assertGreater(available, 0)
        elif not Path("/proc/meminfo").exists():
            self.assertIsNone(held)
            self.assertIsNone(available)


class WaitedChildren(SpawnCase):
    def test_the_report_carries_the_childs_final_text(self):
        shown = self.run_it(name="Echo", wait=True, extra_text="the kitchen",
                            prepend_text="Tonight:")
        self.assertIn("Instruction 'Echo' finished (status=completed, ", shown)
        self.assertIn("extra='the kitchen' prepend='Tonight:' headless=True depth=1", shown)
        self.assertIn("Questions asked: none.", shown)
        self.assertIn("\nFinal report:\n", shown)
        self.assertEqual(self.leftovers(), [])

    def test_prepared_answers_are_given_in_order(self):
        shown = self.run_it(name="Ask", wait=True, answers=["yes", "quite sure"])
        self.assertIn("status=completed", shown)
        self.assertIn("first='yes' second='quite sure'", shown)
        self.assertIn('#1 "Proceed?" -> answered "yes"', shown)
        self.assertIn('#2 "Are you sure?" -> answered "quite sure"', shown)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.leftovers(), [])

    def test_when_the_answers_run_out_the_child_is_stopped(self):
        shown = self.run_it(name="Ask", wait=True, answers=["yes"])
        self.assertIn("status=stopped", shown)
        self.assertIn('#2 "Are you sure?" -> no answer left: the empty reply stopped the run',
                      shown)

    def test_unused_answers_are_mentioned(self):
        shown = self.run_it(name="Echo", wait=True, answers=["spare"])
        self.assertIn("Questions asked: none (1 answer(s) given, none needed).", shown)

    def test_without_answers_the_person_at_this_terminal_is_asked(self):
        self.person = ["go ahead", "certain"]
        shown = self.run_it(name="Ask", wait=True)
        self.assertEqual(self.asked, ["[child run 'Ask'] Proceed?",
                                      "[child run 'Ask'] Are you sure?"])
        self.assertIn("first='go ahead' second='certain'", shown)
        self.assertIn('#1 "Proceed?" -> the person answered "go ahead"', shown)

    def test_nobody_to_ask_stops_the_child(self):
        shown = self.run_it(name="Ask", wait=True)
        self.assertIn("status=stopped", shown)
        self.assertIn("nobody answered: the empty reply stopped the run", shown)

    def test_a_child_that_runs_too_long_is_stopped(self):
        started = time.monotonic()
        shown = self.run_it(name="Slow", wait=True, timeout_seconds=1)
        self.assertIn("did not finish within 1s; the child run was stopped", shown)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(self.leftovers(), [])

    def test_time_spent_waiting_on_the_person_does_not_count(self):
        def slow_person(question):
            time.sleep(1.5)
            return "yes" if "Proceed" in question else "sure"
        self.agent.ask_from_pool = slow_person
        shown = self.run_it(name="Ask", wait=True, timeout_seconds=2)
        self.assertIn("status=completed", shown)

    def test_stopping_the_parent_stops_the_child(self):
        self.stopping = True
        shown = self.run_it(name="Slow", wait=True)
        self.assertIn("cancelled: this run was stopped while waiting", shown)

    def test_a_child_that_dies_reports_its_error_output(self):
        shown = self.run_it(name="Crash", wait=True)
        self.assertIn("exited (code 3, ", shown)
        self.assertIn("wrote no readable result", shown)
        self.assertIn("something broke badly", shown)
        self.assertEqual(self.leftovers(), [])

    def test_a_childs_own_error_is_passed_on(self):
        shown = self.run_it(name="Failed", wait=True)
        self.assertIn("status=error", shown)
        self.assertIn("Child error: the model's reply was cut off", shown)
        self.assertIn("(No final text.)", shown)

    def test_a_long_report_is_cut(self):
        shown = self.run_it(name="Long", wait=True)
        self.assertIn("...[report truncated at 20000 chars]", shown)
        self.assertLess(len(shown), 21000)

    def test_a_child_that_has_finished_makes_room_for_the_next(self):
        for _ in range(spawn.FALLBACK_MAX_CHILDREN + 1):
            self.assertIn("status=completed", self.run_it(name="Echo", wait=True))
        self.assertEqual(spawn.alive_children(), [])


class UnattendedChildren(SpawnCase):
    def test_it_returns_at_once_and_tidies_up_when_the_child_ends(self):
        shown = self.run_it(name="Echo", extra_text="later", prepend_text="first")
        self.assertRegex(shown, r"^Launched instruction 'Echo' with extra task context with a "
                                r"prompt in front of its instruction \(PID \d+\); nobody answers "
                                r"its questions, so it stops at its first one\.$")
        self.assertTrue(self.wait_until(lambda: self.leftovers() == []))
        # It no longer counts as running.
        self.assertTrue(self.wait_until(lambda: spawn.alive_children() == []))

    def test_prepared_answers_reach_a_child_nobody_waits_for(self):
        shown = self.run_it(name="Ask", answers=["yes", "sure"])
        self.assertIn("its questions are answered from the 2 answer(s) given", shown)
        self.assertTrue(self.wait_until(lambda: self.leftovers() == []))


class ChildWindows(SpawnCase):
    """show_window, with a stand-in for the tmux session."""

    def setUp(self):
        super().setUp()
        self.opened = []
        self.session = "child-Chatty-1"
        self.problem = ""

        def open_window(name, pid, log_path):
            self.opened.append((name, pid, log_path))
            return (self.session, "") if not self.problem else ("", self.problem)

        patch = mock.patch.object(spawn, "_open_window", open_window)
        patch.start()
        self.addCleanup(patch.stop)

    def test_no_window_unless_it_is_asked_for(self):
        shown = self.run_it(name="Echo", wait=True)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.notes, [])
        self.assertNotIn("tmux", shown)

    def test_the_window_shows_what_the_child_writes_as_it_writes_it(self):
        seen = []

        def person(question):
            # The child is waiting for this answer: what it wrote before it
            # asked is in the file the window shows.
            log = Path(self.opened[0][2])
            self.wait_until(lambda: "hello" in log.read_text(encoding="utf-8"))
            seen.append(log.read_text(encoding="utf-8"))
            return "yes"

        self.agent.ask_from_pool = person
        shown = self.run_it(name="Chatty", wait=True, show_window=True)
        self.assertEqual(seen, ["hello from the child\n"])
        self.assertIn("status=completed", shown)
        self.assertIn("reply='yes'", shown)

    def test_a_waited_childs_report_and_the_person_are_told_the_session(self):
        self.person = ["yes"]
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/robot-ui,1,0"}):
            os.environ.pop(spawn.WINDOW_SOCKET_ENV, None)
            shown = self.run_it(name="Chatty", wait=True, show_window=True)
        name, pid, log_path = self.opened[0]
        self.assertEqual(name, "Chatty")
        self.assertIn(f"s). Its output was shown in the tmux session '{self.session}'.\n", shown)
        self.assertEqual(self.notes, [
            f"Child run 'Chatty' can be watched in the tmux session '{self.session}': "
            "Ctrl-B then S lists the sessions."])
        # The file goes with the rest when the child has ended.
        self.assertEqual(self.leftovers(), [])

    def test_a_child_nobody_waits_for_has_its_window_too(self):
        shown = self.run_it(name="Chatty", show_window=True, answers=["ok"])
        self.assertRegex(shown, r"which stops it\. Its output shows in the tmux session "
                                r"'child-Chatty-1'\.$")
        self.assertTrue(Path(self.opened[0][2]).name.startswith("window_"))
        self.assertTrue(self.wait_until(lambda: self.leftovers() == []))

    def test_a_window_that_cannot_be_shown_does_not_stop_the_child(self):
        self.problem = "tmux is not available here"
        self.person = ["yes"]
        shown = self.run_it(name="Chatty", wait=True, show_window=True)
        self.assertIn("status=completed", shown)
        self.assertIn("Its window could not be shown (tmux is not available here); it runs "
                      "without one.", shown)
        self.assertEqual(self.notes, [])
        self.assertEqual(self.leftovers(), [])


class WindowNames(unittest.TestCase):
    def test_a_session_name_tmux_accepts(self):
        self.assertEqual(spawn.window_session("Weather: v1.0 (new)", 42),
                         "child-Weather-v1-0-new-42")
        self.assertEqual(spawn.window_session("An instruction with a very long name", 7),
                         "child-An-instruction-with-7")
        self.assertEqual(spawn.window_session("???", 7), "child-7")

    def test_the_window_goes_to_the_tmux_the_run_is_in(self):
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/robot,1,0"}):
            os.environ.pop(spawn.WINDOW_SOCKET_ENV, None)
            self.assertEqual(spawn.window_server(), [])
            self.assertEqual(spawn.window_hint("child-A-1"), "Ctrl-B then S lists the sessions")

    def test_outside_tmux_it_goes_where_the_interface_lives(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(spawn.WINDOW_SOCKET_ENV, None)
            os.environ.pop("TMUX", None)
            self.assertEqual(spawn.window_server(), ["-L", "robot-ui"])
            self.assertEqual(spawn.window_hint("child-A-1"),
                             "tmux -L robot-ui attach -t child-A-1")

    def test_a_check_names_a_tmux_of_its_own(self):
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/robot,1,0",
                                          spawn.WINDOW_SOCKET_ENV: "zz-check"}):
            self.assertEqual(spawn.window_server(), ["-L", "zz-check"])

    def test_without_tmux_there_is_no_window(self):
        with mock.patch.object(spawn.shutil, "which", lambda name: None):
            self.assertEqual(spawn._open_window("A", 1, "x.log"),
                             ("", "tmux is not available here"))


@unittest.skipUnless(LINUX and shutil.which("tmux"), "needs tmux")
class RealWindows(SpawnCase):
    """show_window with a real tmux, on a socket of the test's own."""

    def setUp(self):
        super().setUp()
        self.socket = f"zz-test-{os.getpid()}"
        environment = mock.patch.dict(os.environ, {spawn.WINDOW_SOCKET_ENV: self.socket})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self.tmux, "kill-server")

    def tmux(self, *words):
        return subprocess.run(["tmux", "-L", self.socket, *words], capture_output=True,
                              text=True, check=False)

    def test_the_session_shows_the_childs_output_and_closes_with_it(self):
        screens = []

        def person(question):
            session = self.notes[0].split("'")[3]
            self.wait_until(lambda: "hello from the child"
                            in self.tmux("capture-pane", "-p", "-t", session).stdout)
            screens.append(self.tmux("capture-pane", "-p", "-t", session).stdout)
            return "yes"

        self.agent.ask_from_pool = person
        shown = self.run_it(name="Chatty", wait=True, show_window=True)
        self.assertIn("status=completed", shown)
        session = self.notes[0].split("'")[3]
        self.assertRegex(session, r"^child-Chatty-\d+$")
        self.assertIn(f"tmux -L {self.socket} attach -t {session}.", self.notes[0])
        self.assertIn("Child run 'Chatty' (process ", screens[0])
        self.assertIn("hello from the child", screens[0])
        # Nobody was watching, so the window goes when the child has.
        self.assertTrue(self.wait_until(
            lambda: self.tmux("has-session", "-t", f"={session}").returncode != 0))
        self.assertEqual(self.leftovers(), [])

    def test_a_tmux_started_for_a_window_knows_nothing_of_the_tree(self):
        self.person = ["yes"]
        self.run_it(name="Slow", show_window=True)
        self.kill_later(f"(PID {spawn.alive_children()[0].pid})")
        known = self.tmux("show-environment", "-g").stdout
        self.assertNotIn(spawn.FAMILY_ENV, known)
        self.assertNotIn(spawn.DEPTH_ENV, known)


class RelayServing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_no_open_question_means_nothing_to_do(self):
        self.assertFalse(spawn.relay_serve(self.folder, ["a"], []))

    def test_each_question_is_answered_once(self):
        served = []
        relay.write_request(self.folder, 1, "Go?")
        self.assertTrue(spawn.relay_serve(self.folder, ["yes"], served))
        self.assertEqual(relay.read_reply(self.folder, 1), "yes")
        self.assertFalse(spawn.relay_serve(self.folder, ["yes"], served))
        self.assertEqual(served, [{"seq": 1, "question": "Go?", "answer": "yes",
                                   "outcome": "answered"}])

    def test_a_question_with_no_answerer_gets_the_empty_reply(self):
        served = []
        relay.write_request(self.folder, 1, "Go?")
        spawn.relay_serve(self.folder, None, served)
        self.assertEqual(relay.read_reply(self.folder, 1), "")
        self.assertEqual(served[0]["outcome"], "unanswered")

    def test_the_report_clips_long_questions(self):
        served = [{"seq": 1, "question": "word " * 100, "answer": "ok", "outcome": "answered"}]
        report = spawn.relay_report(served, ["ok"])
        self.assertIn("...", report)
        self.assertLess(len(report), 220)


if __name__ == "__main__":
    unittest.main()
