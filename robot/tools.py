"""Tools the model can call. Each one runs here on the Pi."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

# The kernel reports the SoC temperature here, in thousandths of a degree C.
CPU_TEMP_FILE = Path("/sys/class/thermal/thermal_zone0/temp")


@dataclass
class Tool:
    definition: dict  # what the model is told about the tool
    run: Callable[[dict], str]  # takes the model's input, returns the result text
    is_available: Callable[[], bool]  # checked once at startup


def read_cpu_temperature() -> float:
    """Return the CPU temperature in degrees Celsius."""
    return int(CPU_TEMP_FILE.read_text().strip()) / 1000


def _cpu_temperature_available() -> bool:
    try:
        read_cpu_temperature()
    except (OSError, ValueError):
        return False
    return True


def read_current_datetime() -> str:
    """Return the Pi's local date and time, with its timezone."""
    now = datetime.now().astimezone()
    return now.strftime("%A %d %B %Y, %H:%M:%S %Z (UTC%z)")


ALL_TOOLS = [
    Tool(
        definition={
            "name": "get_current_datetime",
            "description": (
                "Get the current date, day of the week and local time from the "
                "clock of the Raspberry Pi this program is running on, including "
                "the timezone. Call this whenever the answer depends on the "
                "current date or time; never guess them."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        run=lambda _input: read_current_datetime(),
        is_available=lambda: True,
    ),
    Tool(
        definition={
            "name": "get_cpu_temperature",
            "description": (
                "Read the current temperature of the CPU of the Raspberry Pi this "
                "program is running on, in degrees Celsius. Call this whenever the "
                "user asks how hot or warm the Pi, the CPU or the robot is."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        run=lambda _input: f"{read_cpu_temperature():.1f} degrees Celsius",
        is_available=_cpu_temperature_available,
    ),
]


# Tools that run on Anthropic's servers, not on the Pi. There is nothing to
# implement here: declaring one lets the model use it within a request.
# max_uses caps the number of searches in one request (each search is billed).
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
]


def available_tools() -> dict[str, Tool]:
    """Return the tools that work on this machine, keyed by name."""
    return {t.definition["name"]: t for t in ALL_TOOLS if t.is_available()}
