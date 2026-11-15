"""Cost accounting for a run.

Three jobs: price each API call as it completes, append one line per run to
the cost log (in the format MyAgent's cost-log viewers read), and keep a small
record on disk while a run is in flight, so that a run killed from outside
still gets its line the next time the program starts.
"""

import importlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROVIDER = "Anthropic"

_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_RECORD_NAME = re.compile(r"agent_run_(\d+)\.json")
_CLAIM_OPEN_TRIES = 10
_PROC = Path("/proc")


def _models():
    # Imported on first use: formatting and folding in a line need no price
    # tables, and the tests can price calls without the real ones.
    return importlib.import_module("robot.models")


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


# -- one call ----------------------------------------------------------------


def cost_line(update: dict) -> str:
    """The line shown after a call: its cost, the running total and its tokens.

    A call that could not be priced still shows its tokens, behind "unpriced",
    so usage is never silent. An empty update (a call that reported no usage)
    gives an empty string.
    """
    if not update:
        return ""
    tokens_in = update.get("input_tokens") or 0
    tokens_out = update.get("output_tokens") or 0
    cache_write = update.get("cache_write_tokens") or 0
    cache_read = update.get("cache_read_tokens") or 0
    parts = [f"in:{tokens_in:,}  out:{tokens_out:,}"]
    if cache_write:
        parts.append(f"cache_write:{cache_write:,}")
    if cache_read:
        parts.append(f"cache_read:{cache_read:,}")
    tokens = "  ".join(parts)
    call_cost = update.get("call_cost")
    if call_cost is None:
        return f"  unpriced this call  |  no pricing row  ({tokens})\n"
    total = update.get("total_cost")
    if total is None:
        total = call_cost
    # Four decimals while the total is under a cent, two from then on.
    total_text = f"{total:.4f}" if total < 0.01 else f"{total:.2f}"
    return f"  ${call_cost:.4f} this call  |  ${total_text} total  ({tokens})\n"


@dataclass
class RunCost:
    """What one run has spent so far.

    The agent loop owns `calls` and adds one as it starts each call. add_call
    does the rest when a call reports its usage. The three input counts never
    overlap: input_tokens is what was not served from or written to the cache.
    """

    total_cost: float = 0.0
    had_usage: bool = False  # at least one call reported usage
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    # model -> [cost, in, out, cache_write, cache_read], in order of first use
    per_model: dict = field(default_factory=dict)
    _long_context_noted: bool = field(default=False, init=False, repr=False, compare=False)
    _progress_warned: bool = field(default=False, init=False, repr=False, compare=False)

    def tokens(self) -> tuple[int, int, int, int]:
        """(input, output, cache_write, cache_read), the order the log uses."""
        return (self.input_tokens, self.output_tokens,
                self.cache_write_tokens, self.cache_read_tokens)

    def add_call(self, usage: dict, configured_model: str,
                 pricing=None) -> tuple[dict, str | None]:
        """Account for one call. Returns (update for cost_line, warning or None).

        `usage` is the dict the API module builds from the response. `pricing`
        is called as pricing(model, speed=..., prompt_tokens=...) and returns
        per-token rates or None; it defaults to models.get_pricing.

        The update holds the call's own figures and the run's totals so far:
        call_cost and total_cost (both None when the call could not be
        priced), input_tokens, output_tokens, cache_write_tokens,
        cache_read_tokens, total_input_tokens and total_output_tokens.

        Tokens are counted whether or not the call can be priced. The warning
        is given once per run, the first time a prompt is long enough to move
        the model onto its second, dearer rate card. A call without usage
        changes nothing and returns ({}, None).
        """
        if not usage:
            return {}, None
        self.had_usage = True
        tokens_in = usage.get("input_tokens") or 0
        tokens_out = usage.get("output_tokens") or 0
        cache_write = usage.get("cache_creation_input_tokens") or 0
        cache_read = usage.get("cache_read_input_tokens") or 0
        self.input_tokens += tokens_in
        self.output_tokens += tokens_out
        self.cache_write_tokens += cache_write
        self.cache_read_tokens += cache_read

        # The model that produced the reply can differ from the one asked for:
        # a refusal fallback is served, and billed, by another model. A dated
        # snapshot of the configured model is the same model under its full
        # name, so it is kept under the name the log's MODEL field shows.
        reported = usage.get("model") or configured_model
        served = reported
        if configured_model and re.fullmatch(re.escape(configured_model) + r"-\d{8}", served):
            served = configured_model
        part = self.per_model.setdefault(served, [0.0, 0, 0, 0, 0])
        part[1] += tokens_in
        part[2] += tokens_out
        part[3] += cache_write
        part[4] += cache_read

        update = {
            "call_cost": None,
            "total_cost": None,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cache_write_tokens": cache_write,
            "cache_read_tokens": cache_read,
            "total_input_tokens": self.input_tokens,
            "total_output_tokens": self.output_tokens,
        }

        if pricing is None:
            pricing = _models().get_pricing
        speed = usage.get("speed")
        # The whole prompt the API counted picks the rate card where a model has two.
        prompt = tokens_in + cache_write + cache_read
        rates = (pricing(reported, speed=speed, prompt_tokens=prompt)
                 or pricing(configured_model, speed=speed, prompt_tokens=prompt))
        if not rates:
            return update, None

        call_cost = (tokens_in * rates["input"]
                     + tokens_out * rates["output"]
                     + cache_write * rates.get("cache_write", 0)
                     + cache_read * rates.get("cache_read", 0))
        searches = usage.get("web_search_requests") or 0
        if searches:
            # Each search the API ran is billed a flat fee on top of the tokens.
            call_cost += searches * _models().WEB_SEARCH_FEE
        self.total_cost += call_cost
        part[0] += call_cost
        update["call_cost"] = call_cost
        update["total_cost"] = self.total_cost

        warning = None
        if rates.get("long_context") and not self._long_context_noted:
            self._long_context_noted = True
            warning = (
                f"Prompt of {prompt:,} tokens (input plus cache) is over the "
                f"{rates['long_context']:,}-token line where {served} moves to its second "
                "rate card: this call, and the rest of the run while prompts stay this long, "
                f"are priced at ${rates['input'] * 1e6:.2f} / ${rates['output'] * 1e6:.2f} "
                "per MTok instead of the base rates.\n")
        return update, warning


# -- the cost log -------------------------------------------------------------


def split_field(per_model: dict, logged_model: str | None = None) -> str:
    """The log line's 13th field: each serving model's share of a run.

    "model,cost,in,out,cache_write,cache_read" per model, in order of first
    use, joined by "|". It is empty, and then left off the line, unless more
    than one model served the run, or the one that did is not `logged_model`
    (a run moved to a new model that never served a priced call is logged
    under the new model, so the line must say who really did the work). Costs
    have six decimals so the shares add up to the line's four-decimal total.
    """
    if not per_model:
        return ""
    if len(per_model) < 2 and (logged_model is None or logged_model in per_model):
        return ""
    parts = []
    for model, (cost, tokens_in, tokens_out, cache_write, cache_read) in per_model.items():
        # No model id contains a separator, but one that did must not split the field.
        name = str(model).replace(",", "_").replace("|", "_").replace(";", "_")
        parts.append(f"{name},{cost:.6f},{int(tokens_in)},{int(tokens_out)},"
                     f"{int(cache_write)},{int(cache_read)}")
    return "|".join(parts)


def _one_line(text) -> str:
    # A typed name may hold anything. A line break would end the record early
    # and a semicolon would start a new field.
    return " ".join(str(text or "").split()).replace(";", ",")


def _param_parts(params) -> list:
    # The parameter summary arrives as parts separated by spaces, or as a list
    # of them. Commas and semicolons count as separators too, so a summary
    # that was already joined comes out the same and cannot split the line.
    if isinstance(params, (list, tuple)):
        params = " ".join(str(part) for part in params)
    return [part for part in re.split(r"[\s,;]+", str(params or "")) if part]


def _stamp(now=None) -> str:
    """A log timestamp from a datetime, or from text that already is one."""
    if callable(now):
        now = now()
    if isinstance(now, str) and now.strip():
        return now.strip()
    if not isinstance(now, datetime):
        now = datetime.now()
    return now.strftime(_STAMP_FORMAT)


def format_log_line(*, timestamp: str, model: str, total_cost: float, params: str,
                    seconds: float, instruction: str, calls: int, tokens: tuple,
                    split: str = "", chat: str = "") -> str:
    """One cost-log line, newline included, in MyAgent's format:

        timestamp;provider;model;cost;params;seconds;instruction;calls;
        in;out;cache_write;cache_read[;split[;chat]]

    Twelve fields always. The split is added only when there is one. A chat
    name is the 14th field and forces the 13th to be present, blank or not,
    so a reader always finds each in its own place. `seconds`, `calls` or
    `tokens` given as None are written blank ("not recorded"), which is not
    the same as zero.
    """
    timestamp = _stamp(timestamp)
    params_text = ", ".join(_param_parts(params))
    seconds_text = "" if seconds is None else f"{seconds:.0f}"
    calls_text = "" if calls is None else f"{int(calls)}"
    tokens_text = ";".join(f"{int(count)}" for count in tokens) if tokens else ";;;"
    if isinstance(split, dict):
        split = split_field(split, model)
    split = split or ""
    chat_text = _one_line(chat)
    if chat_text:
        tail = f";{split};{chat_text}"
    elif split:
        tail = f";{split}"
    else:
        tail = ""
    return (f"{timestamp};{PROVIDER};{model};{total_cost:.4f};{params_text};"
            f"{seconds_text};{_one_line(instruction)};{calls_text};{tokens_text}{tail}\n")


def _append_line(costlog_path, line: str) -> None:
    # The log is a ledger that is summed over its whole life: lines are only
    # ever appended, and the file is never rotated or rewritten.
    with open(costlog_path, "a", encoding="utf-8", newline="\n") as log:
        log.write(line)


def log_run(costlog_path, run: RunCost, *, model: str, params: str, seconds: float,
            instruction: str = "", chat: str = "", now=None) -> tuple[bool, str | None]:
    """Append the run's line to the cost log. Returns (written, note).

    `model` is the model the run ended on and `seconds` the time it spent
    working. A run that cost nothing is not logged: either no call completed,
    or its calls could not be priced, and a zero line would claim the run was
    free when the truth is that the price is unknown. `note` is the text to
    show the person, or None when there is nothing to say. Never raises: a
    failed write is reported in the note.
    """
    if not run.total_cost or run.total_cost <= 0:
        if not run.had_usage:
            return False, None
        return False, (
            f"Run NOT written to the API cost log: {model} has no row in the {PROVIDER} "
            "pricing table, so its cost is unknown (a $0.0000 line would claim it was "
            "free). Add the row in robot/models.py.\n")
    try:
        line = format_log_line(
            timestamp=_stamp(now), model=model, total_cost=run.total_cost, params=params,
            seconds=seconds, instruction=instruction, calls=run.calls, tokens=run.tokens(),
            split=split_field(run.per_model, model), chat=chat)
        _append_line(costlog_path, line)
    except Exception as error:
        return False, f"Could not write the API cost log ({costlog_path}): {error}\n"
    return True, f"Logged API cost to {costlog_path}: {line}"


# -- the in-progress record ---------------------------------------------------
#
# A run's totals live in memory until its line is written at the end, so a run
# killed from outside (a reboot, a kill, a power cut) would leave no line.
# Each running process therefore keeps one small file holding the line it
# would write if it ended now, and removes it when the real line is written.
# A file found at start-up whose process is gone is a run that never got there.


def progress_path(runs_dir, pid: int) -> Path:
    """Where the process with this PID keeps its in-progress record."""
    return Path(runs_dir) / f"agent_run_{int(pid)}.json"


def _write_json_atomic(path: Path, data: dict) -> None:
    # Written beside the target and renamed over it, so a kill in the middle
    # of a write leaves the previous record, never half of a new one.
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp:
            json.dump(data, temp, ensure_ascii=False)
            temp.flush()
            try:
                os.fsync(temp.fileno())  # the record exists for a power cut
            except OSError:
                pass
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.remove(temp_name)
        except OSError:
            pass
        raise


def progress_write(runs_dir, pid: int, run: RunCost, *, model: str, params: str,
                   seconds: float, instruction: str = "", chat: str = "",
                   boot_id: str = "") -> str | None:
    """Save what the run's cost-log line would say if the run ended now.

    Call it after each call's accounting. It must never interrupt a run, so
    it does not raise: the first failure in a run returns a warning to show,
    and everything else returns None.
    """
    path = None
    try:
        path = progress_path(runs_dir, pid)
        record = {
            "version": 1,
            "written": _stamp(),
            "provider": PROVIDER,
            "model": model,
            "params": " ".join(_param_parts(params)),
            "total_cost": run.total_cost,
            "had_usage": bool(run.had_usage),
            "duration_secs": seconds,
            "instruction": instruction or "",
            "calls": run.calls,
            "tokens": list(run.tokens()),
            "split": run.per_model or {},
            "chat": chat or "",
            "pid": int(pid),
            "boot_id": boot_id or "",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(path, record)
    except Exception as error:
        if getattr(run, "_progress_warned", False):
            return None
        try:
            run._progress_warned = True
        except Exception:
            pass
        where = path if path is not None else f"{runs_dir}, PID {pid}"
        return f"Could not write the in-progress cost record ({where}): {error}\n"
    return None


def progress_clear(runs_dir, pid: int) -> str | None:
    """Remove this process's record: its run ended and the real line is written.

    Does not raise. Returns None, or a warning to show if the file is there
    but could not be removed.
    """
    path = None
    try:
        path = progress_path(runs_dir, pid)
        os.remove(path)
    except FileNotFoundError:
        return None
    except Exception as error:
        where = path if path is not None else f"{runs_dir}, PID {pid}"
        return f"Could not remove the in-progress cost record ({where}): {error}\n"
    return None


def _read_record(path) -> dict:
    with open(path, encoding="utf-8") as source:
        record = json.load(source)
    if not isinstance(record, dict):
        raise ValueError("not a JSON object")
    return record


def _owner_is_gone(path: Path, pid: int, is_alive, boot_id: str, my_pid: int) -> bool:
    if pid != my_pid:
        try:
            if not is_alive(pid):
                return True
        except Exception:
            return False  # cannot tell, so leave the record alone
    # The PID is in use, perhaps by this very process. The record is still
    # stale if it was written before the last reboot: PIDs start again at
    # boot, and a program started the same way each time tends to get the
    # same one. Without this, the new owner of the PID would overwrite the
    # dead run's record with its own.
    if not boot_id:
        return False
    try:
        record_boot = _read_record(path).get("boot_id")
    except (OSError, ValueError):
        return False
    return bool(record_boot) and record_boot != boot_id


def _claim(path: Path) -> Path | None:
    """Move a record to a name only this process knows, or None if it has gone.

    Of several processes that start together and find the same record, only
    one may log it. On Linux a rename settles that: it either happens or
    fails, and the losers find nothing left to rename. _log_claimed confirms
    the claim before logging, because not every system is that strict.
    """
    claimed = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.claim")
    try:
        os.rename(path, claimed)
    except OSError:
        return None
    return claimed


def _put_back(claimed: Path, original: Path) -> None:
    # Hand a claimed record back for a later start to try again, unless a new
    # record has appeared under its name in the meantime.
    try:
        if not original.exists():
            os.rename(claimed, original)
    except OSError:
        pass


def _unfinished_line(record: dict) -> str | None:
    """The log line for a dead run's record, or None if the run cost nothing."""
    total_cost = float(record.get("total_cost") or 0.0)
    if total_cost <= 0:
        return None  # the same rule a run that ended normally goes through
    calls = record.get("calls")
    marker = f"unfinished@call{int(calls)}" if calls else "unfinished"
    tokens = record.get("tokens")
    model = str(record.get("model") or "")
    return format_log_line(
        # The time of the run's last completed call, not the time of this start.
        timestamp=_stamp(record.get("written")),
        model=model,
        total_cost=total_cost,
        params=_param_parts(record.get("params")) + [marker],
        seconds=record.get("duration_secs"),
        instruction=record.get("instruction") or "",
        calls=calls,
        tokens=tuple(tokens) if tokens else None,
        split=split_field(record.get("split") or None, model),
        chat=record.get("chat") or "")


def _log_claimed(claimed: Path, original: Path, costlog_path) -> int:
    """Write the line for a claimed record and remove it. Returns lines written."""
    # On Windows a rename acts on an open handle, so two racing renames of one
    # file can both report success, and the file ends up under the later name.
    # Opening the claimed file settles who holds it: the open fails for
    # everyone but the last, and while it is open nobody else can move it.
    source = None
    for _ in range(_CLAIM_OPEN_TRIES):
        try:
            source = open(claimed, encoding="utf-8")
            break
        except FileNotFoundError:
            return 0  # another process took it after all: it is theirs to log
        except OSError:
            time.sleep(0.02)  # a rival is in the middle of its rename: look again
    if source is None:
        _put_back(claimed, original)
        return 0
    log_failed = False
    with source:
        try:
            record = json.load(source)
            if not isinstance(record, dict):
                raise ValueError("not a JSON object")
            line = _unfinished_line(record)
        except Exception:
            line = None  # unreadable: it can never be logged, so it is not kept
        if line is not None:
            try:
                _append_line(costlog_path, line)
            except OSError:
                log_failed = True
    if log_failed:
        # Nobody is told about this failure, so the cost must not be lost.
        _put_back(claimed, original)
        return 0
    try:
        os.remove(claimed)
    except OSError:
        pass
    return 0 if line is None else 1


def progress_fold_in(runs_dir, costlog_path, *, is_alive, boot_id: str = "",
                     my_pid: int = 0) -> int:
    """Log the runs that died without their cost line. Returns lines written.

    Call it at start-up. A record is a dead run's when `is_alive(pid)` is
    false, or when it was written during an earlier boot (its boot id and
    `boot_id` are both known and differ). Each such record is claimed, logged
    with "unfinished@call<N>" added to its parameters, and removed. A record
    under `my_pid` is this process's own and is left alone, unless its boot
    id shows it was left by an earlier process that had the same PID.
    """
    runs_dir = Path(runs_dir)
    try:
        names = sorted(os.listdir(runs_dir))
    except OSError:
        return 0
    written = 0
    for name in names:
        match = _RECORD_NAME.fullmatch(name)
        if not match:
            continue
        path = runs_dir / name
        if not _owner_is_gone(path, int(match.group(1)), is_alive, boot_id, my_pid):
            continue
        claimed = _claim(path)
        if claimed is not None:
            written += _log_claimed(claimed, path, costlog_path)
    return written


def current_boot_id() -> str:
    """An id that changes at every boot, or "" where the system has none."""
    try:
        with open(_PROC / "sys" / "kernel" / "random" / "boot_id", encoding="ascii",
                  errors="replace") as source:
            return source.read().strip()
    except (OSError, ValueError):
        return ""


def process_is_robot(pid: int) -> bool:
    """Whether the process with this PID is a running copy of this program.

    A PID alone proves little, because PIDs are reused: the command line must
    name this program too. Where that cannot be checked the answer is True,
    so a record is never folded in while its owner might be running. The
    check only reads /proc. It must never send a signal: on Windows
    os.kill(pid, 0) does not test for a process, it terminates it.
    """
    if not _is_linux():
        return True
    try:
        with open(_PROC / str(int(pid)) / "cmdline", "rb") as source:
            return b"robot.main" in source.read()
    except (FileNotFoundError, ProcessLookupError):
        return False  # no such process
    except (OSError, ValueError, TypeError):
        return True
