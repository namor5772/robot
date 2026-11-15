"""run_instruction, with a small stand-in program playing the child run."""

import os
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
            mock.patch.object(spawn, "_slots", threading.BoundedSemaphore(spawn.MAX_CHILDREN)),
            mock.patch.object(spawn, "_POLL_SECONDS", 0.05),
            mock.patch.object(spawn, "_STOP_GRACE_SECONDS", 3),
            mock.patch.object(spawn, "available_memory_mb", lambda: None),
            mock.patch.dict(os.environ, {spawn.DEPTH_ENV: "0"}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.stopping = False
        self.asked = []
        self.person = []
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
        self.assertIn("not enough free memory to start a child run (40 MB available", shown)
        self.assertEqual(self.leftovers(), [])

    def test_only_two_children_run_at_once(self):
        first = self.run_it(name="Slow")
        second = self.run_it(name="Slow")
        self.assertIn("Launched instruction 'Slow'", first)
        self.assertIn("Launched instruction 'Slow'", second)
        third = self.run_it(name="Echo", wait=True)
        self.assertIn("2 child runs are already running", third)
        for line in (first, second):
            pid = int(line.split("(PID ")[1].split(")")[0])
            self.addCleanup(self.kill, pid)

    def kill(self, pid):
        try:
            if os.name == "posix":
                os.kill(pid, 9)
            else:
                import subprocess
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        except OSError:
            pass
        # Let the helper thread notice and tidy up before the folder is removed.
        self.wait_until(lambda: self.leftovers() == [], seconds=5)


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

    def test_the_place_is_free_again_afterwards(self):
        for _ in range(spawn.MAX_CHILDREN + 1):
            self.assertIn("status=completed", self.run_it(name="Echo", wait=True))


class UnattendedChildren(SpawnCase):
    def test_it_returns_at_once_and_tidies_up_when_the_child_ends(self):
        shown = self.run_it(name="Echo", extra_text="later", prepend_text="first")
        self.assertRegex(shown, r"^Launched instruction 'Echo' with extra task context with a "
                                r"prompt in front of its instruction \(PID \d+\); nobody answers "
                                r"its questions, so it stops at its first one\.$")
        self.assertTrue(self.wait_until(lambda: self.leftovers() == []))
        # Its place is free again: two more can start.
        self.assertTrue(self.wait_until(lambda: self.free_places() == spawn.MAX_CHILDREN))

    def free_places(self):
        taken = 0
        while spawn._slots.acquire(blocking=False):
            taken += 1
        for _ in range(taken):
            spawn._slots.release()
        return taken

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
