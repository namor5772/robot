"""run_instruction, with a small stand-in program playing the child run."""

import concurrent.futures
import os
import subprocess
import sys
import tempfile
import textwrap
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
        finish("completed", "extra=%r prepend=%r headless=%r depth=%s" % (
            read(args.extra_file), read(args.prepend_file), args.headless,
            os.environ.get("ROBOT_SPAWN_DEPTH")))
    if name == "Ask":
        first = ask(1, "Proceed?")
        if not first:
            finish("stopped", "no answer to the first question")
        second = ask(2, "Are you sure?")
        if not second:
            finish("stopped", "first=%r, then no answer" % first)
        finish("completed", "first=%r second=%r" % (first, second))
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


class SpawnCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.datadir = DataDir(root / "data")
        self.datadir.ensure()
        instructions.save_instructions(self.datadir, {
            name: {"text": "x"} for name in ("Echo", "Ask", "Slow", "Crash", "Long", "Failed")})
        script = root / "stand_in.py"
        script.write_text(STAND_IN, encoding="utf-8")
        patches = (
            mock.patch.object(spawn, "CHILD_COMMAND", [sys.executable, str(script)]),
            mock.patch.object(spawn, "_children", []),
            mock.patch.object(spawn, "_POLL_SECONDS", 0.05),
            mock.patch.object(spawn, "_STOP_GRACE_SECONDS", 3),
            # As where the free memory cannot be read: tests that are about
            # memory say how much there is (MemoryDecides).
            mock.patch.object(spawn, "available_memory_mb", lambda: None),
            mock.patch.dict(os.environ, {spawn.DEPTH_ENV: "0"}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.stopping = False
        self.asked = []
        self.person = []
        self.to_kill = []
        self.agent = Obj(datadir=self.datadir, console=Obj(interrupts=NoWaitInterrupts()),
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
                         "Error: Instruction 'Nope' not found. Available: Ask, Crash, Echo, "
                         "Failed, Long, Slow")

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

    def memory(self, available, held):
        """Say how much memory is available, and how much each child holds:
        a number of MB for all of them, or None for "cannot be read"."""
        for patch in (mock.patch.object(spawn, "available_memory_mb", lambda: available),
                      mock.patch.object(spawn, "_resident_mb", lambda pid: held)):
            patch.start()
            self.addCleanup(patch.stop)

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
        child = Obj(pid=1)
        for held, to_take in ((None, 80), (0, 80), (5, 75), (71, 9), (72, 0), (77, 0), (93, 0)):
            with self.subTest(held=held), \
                    mock.patch.object(spawn, "_resident_mb", lambda pid, held=held: held):
                self.assertEqual(spawn._still_to_take(child), to_take)

    def test_the_least_free_memory_is_a_child_and_something_to_spare(self):
        self.assertEqual(spawn.MIN_FREE_MB, spawn.CHILD_MB + spawn.SPARE_MB)
        self.memory(available=spawn.MIN_FREE_MB, held=80)
        self.assertIn("status=completed", self.run_it(name="Echo", wait=True))
        self.memory(available=spawn.MIN_FREE_MB - 1, held=80)
        self.assertIn("not enough free memory", self.run_it(name="Echo", wait=True))


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
