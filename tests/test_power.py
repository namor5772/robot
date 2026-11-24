"""Powering the Pi off after a spoken goodbye. No machine is switched off: the
command is a stand-in in every test (see tests/__init__.py), and here it is
watched as well."""

import os
import subprocess
import unittest
from unittest import mock

from robot import agent as agent_module
from robot import power, speaking
from tests.fakes import piped_console, reply, text_block
from tests.test_agent import LoopCase
from tests.test_handsfree import HeardConsole


class NoTestSwitchesAMachineOff(unittest.TestCase):
    def test_the_command_is_a_stand_in_for_every_test(self):
        self.assertEqual(os.environ.get(power.COMMAND_ENV), "true")
        self.assertEqual(power.command(), "true")

    def test_without_that_it_is_the_real_one(self):
        with mock.patch.dict("os.environ", {power.COMMAND_ENV: " "}):
            self.assertEqual(power.command(), "sudo -n poweroff")


class PoweringOff(unittest.TestCase):
    def power_off(self, done=None, error=None, system="posix"):
        self.console, self.out = piped_console()
        done = done or subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(power.os, "name", system), \
                mock.patch.object(power.os, "sync", create=True) as sync, \
                mock.patch.object(power.subprocess, "run", return_value=done,
                                  side_effect=error) as run:
            result = power.power_off(self.console)
        self.sync, self.run = sync, run
        return result

    def test_it_writes_what_is_unwritten_and_runs_the_command(self):
        self.assertTrue(self.power_off())
        self.sync.assert_called_once_with()
        self.assertEqual(self.run.call_args.args[0], ["/bin/bash", "-c", "true"])
        self.assertIs(self.run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("Powering the Pi off now", self.out.getvalue())

    def test_a_command_that_fails_is_a_warning_with_its_reason(self):
        refused = subprocess.CompletedProcess([], 1, stdout="",
                                              stderr="sudo: a password is required\n")
        self.assertFalse(self.power_off(done=refused))
        self.assertIn("warning: The Pi could not be powered off: sudo: a password is required",
                      self.out.getvalue())

    def test_a_command_that_cannot_run_is_a_warning_too(self):
        self.assertFalse(self.power_off(error=OSError("no bash")))
        self.assertIn("could not be powered off: no bash", self.out.getvalue())

    def test_off_the_pi_nothing_is_run(self):
        self.assertFalse(self.power_off(system="nt"))
        self.run.assert_not_called()
        self.assertIn("nothing is powered off", self.out.getvalue())


class AfterASpokenGoodbye(LoopCase):
    def end_with(self, replies, spoken, script=None):
        console = HeardConsole(replies)
        console.spoken = spoken
        made = self.make(script or [reply(text_block("Hi."))], console=console,
                         conversational=True)
        order = []
        wind_down = made._end_run

        def end_run():
            wind_down()
            order.append("run wound down")

        with mock.patch.object(speaking, "available", return_value=True), \
                mock.patch.object(speaking, "say",
                                  side_effect=lambda text: order.append("goodbye")), \
                mock.patch.object(agent_module.power, "power_off",
                                  side_effect=lambda console: order.append("power off")) as off, \
                mock.patch.object(made, "_end_run", side_effect=end_run):
            self.status = made.run()
        self.order = order
        return off

    def test_the_pi_is_powered_off_once_the_run_is_wound_down(self):
        for word in ("Bye.", "Stop.", "quit", "Exit!"):
            with self.subTest(word=word):
                off = self.end_with([word], spoken=(word,))
                off.assert_called_once()
                self.assertEqual(self.status, "completed")
                # The goodbye, then the cost and the chat, then the power.
                self.assertEqual(self.order, ["goodbye", "run wound down", "power off"])

    def test_a_typed_end_word_leaves_the_pi_on(self):
        for word in ("bye", "stop"):
            self.end_with([word], spoken=()).assert_not_called()

    def test_an_empty_reply_and_nobody_there_leave_it_on(self):
        for replies in ([""], [None]):
            self.end_with(replies, spoken=()).assert_not_called()

    def test_something_else_said_leaves_it_on(self):
        off = self.end_with(["Bye for now, see you tomorrow.", None],
                            spoken=("Bye for now, see you tomorrow.",),
                            script=[reply(text_block("Hi.")), reply(text_block("See you."))])
        off.assert_not_called()

    def test_it_is_powered_off_for_real_through_the_stand_in(self):
        # Nothing is patched here but the voice: the command of the tests runs.
        console = HeardConsole(["Bye."])
        console.spoken = ("Bye.",)
        made = self.make([reply(text_block("Hi."))], console=console, conversational=True)
        with mock.patch.object(speaking, "available", return_value=False):
            made.run()
        shown = console.out.getvalue()
        said = "Powering the Pi off now" if os.name == "posix" else "nothing is powered off"
        self.assertIn(said, shown)
        self.assertNotIn("could not be powered off", shown)
        self.assertLess(shown.index("Logged API cost"), shown.index(said))


if __name__ == "__main__":
    unittest.main()
