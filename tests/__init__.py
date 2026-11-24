"""The robot's tests."""

import os

# A conversation ended by voice powers the Pi off (robot.power). No test may
# ever do that to the machine it runs on, the Pi least of all: here the
# command is replaced, for every test, by one that does nothing.
os.environ["ROBOT_POWEROFF_COMMAND"] = "true"
