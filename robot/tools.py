"""Tools the model can call. Each one runs here on the Pi."""

import base64
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

@dataclass
class Tool:
    definition: dict  # what the model is told about the tool
    # Takes the model's input and returns the result: text, or a list of
    # content blocks when the result is more than text (view_image's picture).
    run: Callable[[dict], object]
    is_available: Callable[[], bool]  # checked once at startup
    # Safe to run alongside other calls of the same turn: it only reads, and
    # needs nothing from the person at the keyboard.
    parallel_safe: bool = False


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


# What the API takes as a picture, told by the first bytes of the file, not by
# its name: a photo saved as "shot.jpg" is whatever its content says it is.
MAX_IMAGE_BYTES = 3_500_000  # the API's limit is 5 MB once encoded, a third larger


def _image_media_type(head: bytes):
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def view_image(tool_input: dict) -> list:
    """Hand an image file on the Pi to the model, as a picture it can see.

    The result is a list, not text: a line that says which file it is, then
    the image itself. The agent passes such a list on as the tool's result.
    """
    path_text = tool_input.get("path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError("'path' must be the path of an image file")
    path = Path(path_text.strip()).expanduser()
    if not path.is_absolute():
        path = Path.home() / path  # as in the shell tool, which starts in the home folder
    if not path.is_file():
        raise ValueError(f"there is no file at {path}")
    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{path} is empty")
    if size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"{path} is {size:,} bytes, more than the {MAX_IMAGE_BYTES:,} that can be sent. "
            "Make a smaller copy first, for example a photo at a lower resolution.")
    data = path.read_bytes()
    media_type = _image_media_type(data[:16])
    if media_type is None:
        raise ValueError(f"{path} is not a JPEG, PNG, GIF or WebP image")
    return [
        {"type": "text", "text": f"The image {path} ({media_type}, {size:,} bytes):"},
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.standard_b64encode(data).decode("ascii")}},
    ]


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
        parallel_safe=True,
    ),
    Tool(
        definition={
            "name": "view_image",
            "description": (
                "Look at an image file stored on the Raspberry Pi this program is "
                "running on. This is how you see: the picture itself comes back to "
                "you, so you can describe it, read what is written in it or answer "
                "questions about it. Use it on a photo you have just taken with the "
                "camera, or on any other image file, whenever the person wants to "
                "know what a picture shows. Never describe an image you have not "
                "looked at with this tool. It takes JPEG, PNG, GIF and WebP files of "
                "up to 3.5 MB. Every image you look at stays in the conversation and "
                "costs a few thousand tokens, so look at the ones that are needed."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The path of the image file, for example "
                            "/home/user/robot-photos/photo.jpg. '~' and paths "
                            "relative to the home directory work too."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        run=view_image,
        is_available=lambda: True,
        parallel_safe=True,
    ),
]

# Web search is not listed here: it runs on Anthropic's servers, so there is
# nothing to implement. Its declaration depends on the model and comes from
# models.web_search_tool.


def available_tools() -> dict[str, Tool]:
    """Return the tools that work on this machine, keyed by name."""
    return {t.definition["name"]: t for t in ALL_TOOLS if t.is_available()}
