"""Switching the Pi off, when the person has said goodbye to it.

A conversation that is ended by the spoken word "bye" (see robot.handsfree)
ends with the Pi powering itself off: no question is asked first, at the
owner's word. Typed, the word does not do it, and neither do the other end
words, spoken or typed. The run is over by then, its cost logged and its chat
saved, and the system's own shutdown does the rest in order: it stops what is
running, writes what is unwritten and unmounts the card.
"""

import os
import subprocess

# What is run to power off. The environment can name another command, so that
# a test or a check on the Pi never switches off the machine it runs on.
COMMAND = "sudo -n poweroff"
COMMAND_ENV = "ROBOT_POWEROFF_COMMAND"


def command() -> str:
    return os.environ.get(COMMAND_ENV, "").strip() or COMMAND


def power_off(console) -> bool:
    """Power the Pi off. True when the shutdown was started.

    It returns at once: the system then takes some seconds to stop everything,
    this program included.
    """
    if os.name != "posix":
        console.note("(this is not the Pi: nothing is powered off)")
        return False
    console.note("Powering the Pi off now: you said bye.")
    try:
        os.sync()  # what is unwritten goes to the card before anything else
    except OSError:
        pass
    try:
        done = subprocess.run(["/bin/bash", "-c", command()], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        console.warn(f"The Pi could not be powered off: {error}")
        return False
    if done.returncode != 0:
        reason = " ".join((done.stderr or done.stdout).split())[:200]
        console.warn("The Pi could not be powered off: "
                     + (reason or f"the command ended with code {done.returncode}"))
        return False
    return True
