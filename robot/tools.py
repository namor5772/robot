"""Tools the model can call. Each one runs here on the Pi."""

import os
import shutil
import signal
import subprocess
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


MAX_OUTPUT_CHARS = 20000  # longer command output is trimmed in the middle


def _trim(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    dropped = len(text) - 2 * half
    return f"{text[:half]}\n[... {dropped} characters omitted ...]\n{text[-half:]}"


def run_shell_command(tool_input: dict) -> str:
    """Run a bash command on the Pi and return its exit code and output."""
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("'command' must be a non-empty string")
    timeout = tool_input.get("timeout_seconds", 60)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("'timeout_seconds' must be a positive number")

    process = subprocess.Popen(
        ["/bin/bash", "-c", command],
        cwd=Path.home(),
        stdin=subprocess.DEVNULL,  # commands must not read the chat's keyboard
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,  # own process group, so everything can be killed
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    except BaseException:  # e.g. Ctrl-C: do not leave the command running
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise

    parts = [
        f"timed out after {timeout} seconds and was killed"
        if timed_out
        else f"exit code: {process.returncode}"
    ]
    if stdout:
        parts.append(f"stdout:\n{_trim(stdout)}")
    if stderr:
        parts.append(f"stderr:\n{_trim(stderr)}")
    return "\n".join(parts)


ALL_TOOLS = [
    Tool(
        definition={
            "name": "run_shell_command",
            "description": (
                "Run a bash command on the Raspberry Pi this program is running on "
                "and get back its exit code, stdout and stderr. The command runs as "
                "the robot's own user with that user's full access. sudo only works "
                "if passwordless sudo is set up on this Pi, because a password "
                "cannot be typed; check with 'sudo -n true'. Use "
                "it for anything on the Pi that no other tool covers: inspecting "
                "the system, reading and writing files, installing software, "
                "running scripts, controlling hardware. Each call starts a fresh "
                "shell in the home directory, so 'cd' and variables do not carry "
                "over between calls: chain steps with '&&' in one command. "
                "Commands get no keyboard input, so use non-interactive flags "
                "(for example 'apt-get -y'). To leave something running in the "
                "background, detach it: 'nohup CMD >/dev/null 2>&1 &'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command line to run.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": (
                            "How long to wait before killing the command. "
                            "Defaults to 60. Set it higher for slow commands "
                            "such as package installs."
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        run=run_shell_command,
        is_available=lambda: os.name == "posix" and shutil.which("bash") is not None,
    ),
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
