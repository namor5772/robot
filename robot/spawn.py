"""run_instruction: run a saved instruction as a child run of this program.

A child is a whole separate process running `python -m robot.main -l NAME`.
It reports back through a result file, and its questions travel through a
relay folder (see relay.py). On a small Pi a child costs many seconds to start
and a large share of the memory, so one is only started while there is memory
for it: how many can run at once depends on the computer, up to a ceiling that
is the same everywhere.

A child can start children of its own, so the runs form a tree. The ceiling
and the memory rule are for the whole tree: the first run's children and the
children those start, counted together.
"""

import contextlib
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

try:
    import fcntl
except ImportError:  # Windows, where only the tests run
    fcntl = None

# How many children run at once is decided by the memory that is free, so the
# same code suits a Pi Zero and a larger computer. Measured on the Pi Zero 2 W
# on 2026-11-19: a run starts at 5 MB, holds 77 MB eleven seconds later, when
# everything is loaded, and grows a little with use (93 MB was seen); the
# memory the kernel calls available falls by less, 57 MB, because the runs
# share what they load from the same files.
CHILD_MB = 80  # what a child run holds once it has loaded
SPARE_MB = 30  # what must still be free when it has
MIN_FREE_MB = CHILD_MB + SPARE_MB  # so a child is only started with this much available
# The most child runs alive at once in a whole tree of runs, however much
# memory is free: the first run's children and the children those start,
# counted together. Every child is a run that is paid for, and where there are
# gigabytes to spare memory alone would allow dozens. Set by the owner on
# 2026-11-19, who asked for it to cover the whole tree.
MAX_CHILDREN = 8
# Where the free memory cannot be read (anywhere but Linux), a fixed number of
# children at once has to do.
FALLBACK_MAX_CHILDREN = 2
MAX_DEPTH = 2  # a child may start children, but their children may not
DEPTH_ENV = "ROBOT_SPAWN_DEPTH"
# The name of the tree a run belongs to. The first run makes one up; every
# child is given it in this variable and hands it on to its own children.
FAMILY_ENV = "ROBOT_SPAWN_FAMILY"
DEFAULT_TIMEOUT = 600
REPORT_LIMIT = 20000
_POLL_SECONDS = 0.5
_STOP_GRACE_SECONDS = 15
_LOCK_WAIT_SECONDS = 10

# What starts a child. Tests point this at a stand-in program.
CHILD_COMMAND = [sys.executable, "-m", "robot.main"]
REPO_ROOT = Path(__file__).resolve().parent.parent
_PROC = Path("/proc")

_spawn_lock = threading.Lock()
_children = []  # the children this program started that may still be running
_children_lock = threading.Lock()
_family_name = ""  # made up on first use by a run that was given none


def family() -> str:
    """The name of the tree of runs this one belongs to."""
    global _family_name
    given = os.environ.get(FAMILY_ENV, "")
    if given:
        return given
    if not _family_name:
        _family_name = f"{os.getpid()}.{time.time_ns()}"
    return _family_name


def family_members():
    """The PIDs of the child runs alive in this run's tree, itself included if
    it is one. None where the list of processes cannot be read (anywhere but
    Linux).

    The kernel's list is asked, not a count kept by the runs: a run that is
    killed takes itself off that list, whatever it failed to tidy up. A child
    run is known by the command it was started with and by the tree's name in
    its environment. The shell commands a run starts inherit the name, but
    their command is another.
    """
    command = b"\0".join(os.fsencode(part) for part in CHILD_COMMAND) + b"\0"
    mark = f"{FAMILY_ENV}={family()}".encode()
    try:
        entries = os.listdir(_PROC)
    except OSError:
        return None
    members = []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            if not (_PROC / entry / "cmdline").read_bytes().startswith(command):
                continue
            environment = (_PROC / entry / "environ").read_bytes()
        except OSError:
            continue  # it ended meanwhile, or is not ours to look at
        if mark in environment.split(b"\0"):
            members.append(int(entry))
    return members


@contextlib.contextmanager
def _one_start_at_a_time(folder):
    """Hold everything that lets two starts be judged at the same moment.

    Inside this program that is a lock between threads: the model can ask for
    several children in one turn, and those calls run side by side. Between
    the programs of a tree it is an exclusive hold on `folder`, the data
    folder's tmp, which they all share: a child and its parent can both be
    starting a child. Each start then sees the ones before it. A hold that
    cannot be had in ten seconds is done without, sooner than never start.
    """
    with _spawn_lock:
        handle = None
        if fcntl is not None:
            try:
                os.makedirs(folder, exist_ok=True)
                handle = os.open(folder, os.O_RDONLY)
            except OSError:
                handle = None
            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while handle is not None:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        os.close(handle)
                        handle = None
                    else:
                        time.sleep(0.02)
        try:
            yield
        finally:
            if handle is not None:
                os.close(handle)  # which lets the hold go


def available_memory_mb():
    """Memory the kernel says can be used without swapping, or None if unknown."""
    try:
        with open(_PROC / "meminfo", encoding="ascii") as source:
            for line in source:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _page_size() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return 4096


def _resident_mb(pid):
    """The memory a process holds right now, or None where that cannot be read."""
    try:
        with open(_PROC / str(int(pid)) / "statm", encoding="ascii") as source:
            pages = int(source.read().split()[1])
    except (OSError, ValueError, IndexError, TypeError):
        return None
    return pages * _page_size() // (1024 * 1024)


def alive_children() -> list:
    """The child runs this program started that are still running."""
    with _children_lock:
        _children[:] = [child for child in _children if child.poll() is None]
        return list(_children)


def _still_to_take(pid) -> int:
    """The memory, in MB, that a child which is still starting has yet to take.

    A child that holds nine tenths of CHILD_MB has loaded, and what it took is
    in the kernel's figure already. One whose memory cannot be read counts as
    not having taken any.
    """
    held = _resident_mb(pid) or 0
    return CHILD_MB - held if held < CHILD_MB * 9 // 10 else 0


def _why_not_another() -> str:
    """Why another child must not be started now, as an error text; "" if it may.

    Two things can stand in the way: the ceiling on how many run at once, and
    too little free memory. Both look at the whole tree this run belongs to.
    The caller holds _one_start_at_a_time, so that starts asked for at the
    same moment, here or elsewhere in the tree, are judged one after the
    other: each sees the children started before it.
    """
    own = alive_children()
    members = family_members()
    # Where the tree cannot be seen, this program's own children have to do.
    running = members if members is not None else [child.pid for child in own]
    if len(running) >= MAX_CHILDREN:
        return (f"Error: {MAX_CHILDREN} child runs are already running in this tree of runs "
                "(the first run's children and the children those started), which is the "
                "most at once. Wait for one to finish and try again, or do the task in this "
                "run.")
    free = available_memory_mb()
    if free is None:
        if len(own) >= FALLBACK_MAX_CHILDREN:
            return (f"Error: {FALLBACK_MAX_CHILDREN} child runs are already running. How "
                    "much memory is free cannot be read on this computer, so that is the "
                    "most that are started at once. Wait for one to finish and try again, "
                    "or do the task in this run.")
        return ""
    # A child that has only just been started holds next to nothing yet, and
    # the kernel's figure does not know what it is about to take. Without this
    # allowance several children asked for at once would each look affordable.
    shortfalls = [_still_to_take(pid) for pid in running]
    to_come = sum(shortfalls)
    if free - to_come >= MIN_FREE_MB:
        return ""
    starting = sum(1 for shortfall in shortfalls if shortfall)
    promised = ""
    if starting:
        promised = (f", but about {to_come} MB of that will go to the {starting} child "
                    f"run{'s' if starting != 1 else ''} still starting")
    return (f"Error: not enough free memory to start a child run ({free} MB available"
            f"{promised}; a child run takes about {CHILD_MB} MB and {SPARE_MB} MB must stay "
            "free). Wait for a child run or other work to finish and try again, or do the "
            "task in this run.")


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
    try:
        with _one_start_at_a_time(datadir.tmp_dir):
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
            refusal = _why_not_another()
            if refusal:
                return refusal

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
            environment[FAMILY_ENV] = family()  # the tree it belongs to, and counts in
            try:
                with open(error_path, "w", encoding="utf-8") as errors:
                    process = subprocess.Popen(
                        command, cwd=str(REPO_ROOT), env=environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                        start_new_session=(os.name == "posix"))
            except Exception as error:
                return f"Error launching instruction '{name}': {error}"
            # Noted before the lock is let go: the next start must count it.
            with _children_lock:
                _children.append(process)

        if not wait:
            # The child carries on by itself. A helper thread answers its
            # questions and tidies up when it ends.
            threading.Thread(
                target=_attend, name=f"child-{process.pid}", daemon=True,
                args=(process, relay_dir, answers,
                      (extra_path, prepend_path, error_path))).start()
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


def _attend(process, relay_dir, answers, leftovers):
    """Look after a child nobody is waiting for, until it ends."""
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
