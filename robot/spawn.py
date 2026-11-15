"""run_instruction: run a saved instruction as a child run of this program.

A child is a whole separate process running `python -m robot.main -l NAME`.
It reports back through a result file, and its questions travel through a
relay folder (see relay.py). On the Pi a child costs many seconds to start
and a large share of the memory, so their number is capped.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from robot import instructions, relay

MAX_CHILDREN = 2  # alive at once, per parent run
MIN_FREE_MB = 110  # do not start a child with less memory than this available
MAX_DEPTH = 2  # a child may start children, but their children may not
DEPTH_ENV = "ROBOT_SPAWN_DEPTH"
DEFAULT_TIMEOUT = 600
REPORT_LIMIT = 20000
_POLL_SECONDS = 0.5
_STOP_GRACE_SECONDS = 15

# What starts a child. Tests point this at a stand-in program.
CHILD_COMMAND = [sys.executable, "-m", "robot.main"]
REPO_ROOT = Path(__file__).resolve().parent.parent

_spawn_lock = threading.Lock()
_slots = threading.BoundedSemaphore(MAX_CHILDREN)


def available_memory_mb():
    """Memory the kernel says can be used without swapping, or None if unknown."""
    try:
        with open("/proc/meminfo", encoding="ascii") as source:
            for line in source:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _temp_file(folder, prefix, suffix, text=None):
    handle, path = tempfile.mkstemp(dir=str(folder), prefix=prefix, suffix=suffix)
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as target:
        if text is not None:
            target.write(text)
    return path


def _remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _stop_child(process):
    """Ask a child to stop, and make sure it has.

    SIGTERM lets it wind down properly: log its cost, save its chat, write its
    result file. The whole process group goes, so its own shell commands and
    children stop too.
    """
    if os.name != "posix":
        # Only the tests run here. There is no gentle stop on Windows, and its
        # venv starts Python through a launcher, so take the whole tree.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, check=False)
        try:
            process.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        process.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _clip(text, limit=120):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def relay_serve(relay_dir, answers, served, ask=None):
    """Answer the child's open question, if it has one. True if it was answered.

    With `answers`, each question gets the next unused one; when they run out
    the reply is empty, which stops the child. Without `answers`, `ask` puts
    the question to the person at this run's terminal; no `ask`, or no answer
    from it, is also the empty reply. `served` is the record of what was asked.
    """
    request = relay.read_request(relay_dir)
    if request is None:
        return False
    sequence = int(request.get("seq", 0))
    if any(entry["seq"] == sequence for entry in served):
        return False  # answered already; the child has not picked it up yet
    question = str(request.get("text", ""))
    if answers is not None:
        used = sum(1 for entry in served if entry["outcome"] == "answered")
        if used < len(answers):
            answer, outcome = answers[used], "answered"
        else:
            answer, outcome = "", "stopped"
    else:
        reply = ask(question) if ask is not None else None
        if reply:
            answer, outcome = reply, "asked"
        else:
            answer, outcome = "", "unanswered"
    relay.write_reply(relay_dir, sequence, answer)
    served.append({"seq": sequence, "question": question, "answer": answer,
                   "outcome": outcome})
    return True


def relay_report(served, answers) -> str:
    """The part of a waited child's report about the questions it asked."""
    if not served:
        spare = f" ({len(answers)} answer(s) given, none needed)" if answers else ""
        return f"\nQuestions asked: none{spare}."
    lines = [f"\nQuestions asked: {len(served)}"]
    for entry in served:
        asked = f'  #{entry["seq"]} "{_clip(entry["question"])}"'
        if entry["outcome"] == "answered":
            lines.append(f'{asked} -> answered "{_clip(entry["answer"])}"')
        elif entry["outcome"] == "asked":
            lines.append(f'{asked} -> the person answered "{_clip(entry["answer"])}"')
        elif entry["outcome"] == "stopped":
            lines.append(f"{asked} -> no answer left: the empty reply stopped the run")
        else:
            lines.append(f"{asked} -> nobody answered: the empty reply stopped the run")
    return "\n".join(lines)


def _error_tail(path, limit=600) -> str:
    """The end of what a child wrote to stderr: why it died, if it did."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[-limit:]


def run_instruction(agent, params) -> str:
    """The run_instruction tool. Runs on a pool thread, never the main one."""
    name = params.get("name", "")
    name = name.strip() if isinstance(name, str) else ""
    wait = bool(params.get("wait", False))
    extra_text = params.get("extra_text") or ""
    prepend_text = params.get("prepend_text") or ""
    answers = params.get("answers")
    if isinstance(answers, str):
        answers = [answers]  # a single reply given bare
    if answers is not None and (not isinstance(answers, list)
                                or not all(isinstance(item, str) for item in answers)):
        return ("Error: 'answers' must be a list of strings: the replies to the child's "
                "questions, in order ([] stops it at its first question).")
    try:
        timeout = int(params.get("timeout_seconds") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if not name:
        return "Error: 'name' is required."

    datadir = agent.datadir
    result_path = extra_path = prepend_path = error_path = relay_dir = None
    have_slot = False
    try:
        with _spawn_lock:
            library = instructions.load_instructions(datadir)
            if name not in library:
                available = ", ".join(sorted(library)) if library else "(none)"
                return f"Error: Instruction '{name}' not found. Available: {available}"
            try:
                depth = int(os.environ.get(DEPTH_ENV, "0"))
            except ValueError:
                depth = 0
            if depth >= MAX_DEPTH:
                return ("Error: this run is already a child of a child run and cannot "
                        "start further child runs. Do the work in this run instead.")
            free = available_memory_mb()
            if free is not None and free < MIN_FREE_MB:
                return (f"Error: not enough free memory to start a child run ({free} MB "
                        "available; a child needs about 80 MB). Wait for other work to "
                        "finish, or do the task in this run.")
            if not _slots.acquire(blocking=False):
                return (f"Error: {MAX_CHILDREN} child runs are already running, which is "
                        "all this small computer can run at once. Wait for one to finish "
                        "and try again, or do the task in this run.")
            have_slot = True

            datadir.tmp_dir.mkdir(parents=True, exist_ok=True)
            command = list(CHILD_COMMAND) + ["-l", name, "--headless"]
            if wait:
                result_path = _temp_file(datadir.tmp_dir, "result_", ".json")
                command += ["--result-file", result_path]
            if extra_text:
                extra_path = _temp_file(datadir.tmp_dir, "extra_", ".txt", extra_text)
                command += ["--extra-file", extra_path]
            if prepend_text:
                prepend_path = _temp_file(datadir.tmp_dir, "prepend_", ".txt", prepend_text)
                command += ["--prepend-file", prepend_path]
            # A waited child always gets a relay folder: with no prepared
            # answers its questions are put to the person at this terminal.
            if answers is not None or wait:
                relay_dir = tempfile.mkdtemp(dir=str(datadir.tmp_dir), prefix="relay_")
                command += ["--relay-dir", relay_dir]
            error_path = _temp_file(datadir.tmp_dir, "child_", ".err")

            environment = dict(os.environ)
            environment[DEPTH_ENV] = str(depth + 1)
            try:
                with open(error_path, "w", encoding="utf-8") as errors:
                    process = subprocess.Popen(
                        command, cwd=str(REPO_ROOT), env=environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                        start_new_session=(os.name == "posix"))
            except Exception as error:
                return f"Error launching instruction '{name}': {error}"

        if not wait:
            # The child carries on by itself. A helper thread answers its
            # questions, frees its place when it ends, and tidies up.
            threading.Thread(
                target=_attend, name=f"child-{process.pid}", daemon=True,
                args=(process, relay_dir, answers,
                      (extra_path, prepend_path, error_path), _slots)).start()
            have_slot = False  # _attend releases it
            extra_path = prepend_path = error_path = relay_dir = None
            noted = " with extra task context" if extra_text else ""
            if prepend_text:
                noted += " with a prompt in front of its instruction"
            if answers is not None:
                asking = (f"; its questions are answered from the {len(answers)} answer(s) "
                          "given, the next one with an empty reply, which stops it")
            else:
                asking = "; nobody answers its questions, so it stops at its first one"
            return f"Launched instruction '{name}'{noted} (PID {process.pid}){asking}."

        return _wait_for(agent, process, name, timeout, relay_dir, answers, result_path,
                         error_path)
    finally:
        for path in (result_path, extra_path, prepend_path, error_path):
            _remove(path)
        if relay_dir:
            shutil.rmtree(relay_dir, ignore_errors=True)
        if have_slot:
            _slots.release()


def _attend(process, relay_dir, answers, leftovers, slots):
    """Look after a child nobody is waiting for, until it ends. `slots` is the
    counter its place was taken from."""
    served = []
    try:
        while process.poll() is None:
            if relay_dir:
                try:
                    relay_serve(relay_dir, answers, served)
                except OSError:
                    pass
            time.sleep(_POLL_SECONDS)
    finally:
        for path in leftovers:
            _remove(path)
        if relay_dir:
            shutil.rmtree(relay_dir, ignore_errors=True)
        slots.release()


def _wait_for(agent, process, name, timeout, relay_dir, answers, result_path, error_path):
    """Wait for a child to finish and return its report."""
    interrupts = agent.console.interrupts
    started = time.monotonic()
    waiting_on_person = 0.0
    served = []

    def ask(question):
        # Time the person takes to answer does not count against the child.
        nonlocal waiting_on_person
        asked_at = time.monotonic()
        try:
            return agent.ask_from_pool(f"[child run '{name}'] {question}")
        finally:
            waiting_on_person += time.monotonic() - asked_at

    while process.poll() is None:
        if interrupts.pending() or agent.stop_requested():
            _stop_child(process)
            return (f"run_instruction '{name}' cancelled: this run was stopped while "
                    "waiting; the child run was stopped too.")
        if time.monotonic() - started - waiting_on_person > timeout:
            _stop_child(process)
            return (f"Error: instruction '{name}' did not finish within {timeout}s; the "
                    f"child run was stopped. Its partial transcript ({name}_<timestamp>.txt) "
                    f"is in {agent.datadir.chats_dir}.")
        if relay_dir:
            try:
                relay_serve(relay_dir, answers, served, ask=ask if answers is None else None)
            except OSError:
                pass
        time.sleep(_POLL_SECONDS)

    elapsed = int(time.monotonic() - started)
    try:
        with open(result_path, encoding="utf-8") as source:
            result = json.load(source)
        if not isinstance(result, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        report = (f"Error: instruction '{name}' exited (code {process.returncode}, "
                  f"{elapsed}s) but wrote no readable result. It may have failed before "
                  "its run started.")
        tail = _error_tail(error_path)
        if tail:
            report += f"\nIts error output ended with:\n{tail}"
        return report
    status = result.get("status", "unknown")
    final_text = (result.get("final_text") or "").strip()
    if len(final_text) > REPORT_LIMIT:
        final_text = (final_text[:REPORT_LIMIT]
                      + f"\n...[report truncated at {REPORT_LIMIT} chars]")
    report = f"Instruction '{name}' finished (status={status}, {elapsed}s)."
    if result.get("error"):
        report += f"\nChild error: {result['error']}"
    if relay_dir:
        report += relay_report(served, answers)
    report += f"\nFinal report:\n{final_text}" if final_text else "\n(No final text.)"
    return report
