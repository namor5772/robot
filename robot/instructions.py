"""Saved instructions, and the settings a run takes from one.

An instruction is a saved task together with how to run it: its text is the
first message of the run, the rest are settings. The library is one JSON file
keyed by name, in the same shape MyAgent uses, so entries can be copied
between the two programs. Keys this program does not use are left alone.
"""

from dataclasses import dataclass, field

from robot import models
from robot.datastore import StoreUnreadableError, load_store, save_store, store_unreadable

PROVIDER = "Anthropic"

# A chat started without naming an instruction takes its settings from the
# entry with this name. It is created on first use and can be edited like any
# other, which is how the everyday chat's model or tools are changed.
DEFAULT_NAME = "Default"

EXTRA_TEXT_HEADING = ("--- ADDITIONAL TASK CONTEXT (for this run only, from the "
                      "launching process) ---")


class InstructionError(Exception):
    """An instruction that cannot be run as asked."""


@dataclass
class RunSettings:
    """The settings of one run."""

    name: str = ""  # the instruction's name; empty for an ad-hoc run
    text: str = ""  # the task, sent as the first user message
    model: str = models.DEFAULT_MODEL
    thinking_mode: str = "low"
    thinking_budget: int = models.DEFAULT_THINKING_BUDGET
    fast_mode: bool = False
    meta: bool = False
    conversational: bool = False
    blocked_tools: list = field(default_factory=list)
    skill_modes: dict = field(default_factory=dict)
    upgrade_target: dict | None = None
    memory: bool = False  # remember this run's conversation, and be told the earlier ones
    memory_name: str = ""  # which memory: '' is the shared one


def default_entry() -> dict:
    """The Default entry as first created. It deliberately has no skill_modes:
    a snapshot would switch off every skill added later."""
    return {
        "text": "",
        "notes": ("Settings for a chat started without naming an instruction. "
                  "Change this entry to change the everyday chat."),
        "provider": PROVIDER,
        "model": models.DEFAULT_MODEL,
        "thinking_mode": "low",
        "fast_mode": False,
        "meta": True,
        "conversational": True,
    }


def load_instructions(datadir) -> dict:
    """The library as name -> entry. A pure read: nothing is written."""
    library = {}
    for name, entry in load_store(datadir.instructions_file).items():
        if isinstance(entry, str):  # an old entry that is only its text
            entry = {"text": entry}
        if isinstance(entry, dict):
            library[str(name)] = entry
    return library


def save_instructions(datadir, library: dict) -> None:
    """Write the library. Refuses to replace a file it could not read."""
    path = datadir.instructions_file
    if store_unreadable(path):
        raise StoreUnreadableError(
            f"{path} exists but is not readable as an instruction library; it was left "
            "untouched. Fix or remove the file first.")
    save_store(path, library)


def ensure_default(datadir) -> dict:
    """The library, with the Default entry created if it is missing."""
    library = load_instructions(datadir)
    if DEFAULT_NAME not in library:
        library[DEFAULT_NAME] = default_entry()
        save_instructions(datadir, library)
    return library


def settings_from_entry(name: str, entry: dict) -> tuple[RunSettings, list]:
    """Turn a stored entry into run settings. Returns (settings, warnings).

    Values the chosen model cannot honour are corrected here, with a warning,
    so the run starts with settings that will be accepted.
    """
    warnings = []
    provider = str(entry.get("provider") or PROVIDER)
    if provider != PROVIDER:
        raise InstructionError(
            f"The instruction '{name}' is set up for {provider}. "
            "This program runs Anthropic models only.")

    model = str(entry.get("model") or models.DEFAULT_MODEL)

    mode = entry.get("thinking_mode")
    stated = bool(mode)  # the entry names a level itself
    if not mode:
        mode = models.mode_from_legacy(entry)
    mode = str(mode).strip().lower()
    # For models with a thinking budget, MyAgent's on/off switch is the truth
    # and the mode field may be stale.
    if models.thinking_support(model) == "manual" and entry.get("thinking_enabled") is False:
        mode = "off"
    coerced = models.coerce_mode(model, mode)
    # Only a level the entry asked for by name is worth a warning; an entry
    # that says nothing about thinking just gets what the model does.
    if stated and coerced != mode and mode != "none":
        warnings.append(f"{model} has no thinking level '{mode}'; using '{coerced}'.")

    budget = entry.get("thinking_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        budget = models.DEFAULT_THINKING_BUDGET

    fast = bool(entry.get("fast_mode"))
    if fast and not models.supports_fast_mode(model):
        warnings.append(f"{model} has no fast mode; this run is at standard speed.")

    blocked = entry.get("blocked_tools")
    blocked = sorted({str(tool) for tool in blocked}) if isinstance(blocked, (list, tuple)) else []

    skill_modes = entry.get("skill_modes")
    skill_modes = dict(skill_modes) if isinstance(skill_modes, dict) else {}

    target = entry.get("upgrade_target")
    if target is not None:
        target = models.sanitize_upgrade_target(target)

    uses_memory = bool(entry.get("memory"))
    memory_name = str(entry.get("memory_name") or "") if uses_memory else ""
    if memory_name:
        from robot import memory

        problem = memory.name_problem(memory_name)
        if problem:
            # Not the shared one instead: that would write into a memory
            # the instruction was never meant to touch.
            warnings.append(f"{problem} This run has no memory.")
            uses_memory, memory_name = False, ""

    settings = RunSettings(
        name=name, text=str(entry.get("text") or ""), model=model, thinking_mode=coerced,
        thinking_budget=budget, fast_mode=fast, meta=bool(entry.get("meta")),
        conversational=bool(entry.get("conversational")), blocked_tools=blocked,
        skill_modes=skill_modes, upgrade_target=target, memory=uses_memory,
        memory_name=memory_name)
    return settings, warnings


def memory_flag(settings) -> str:
    """How a listing says that an instruction has memory, and which."""
    return f"memory: {settings.memory_name}" if settings.memory_name else "memory"


def describe(name: str, entry: dict) -> str:
    """Two lines about an instruction, for a listing."""
    try:
        settings, _ = settings_from_entry(name, entry)
    except InstructionError:
        return f"- {name}  [{entry.get('provider')}: cannot be run here]"
    flags = [flag for flag, on in (("meta", settings.meta), ("convo", settings.conversational),
                                   ("fast", settings.fast_mode),
                                   (memory_flag(settings), settings.memory)) if on]
    mode = models.mode_label(settings.model, settings.thinking_mode,
                             thinking_budget=settings.thinking_budget)
    line = f"- {name}  [{settings.model}, {mode}]"
    if flags:
        line += f" [{', '.join(flags)}]"
    text = " ".join(settings.text.split())
    if not text:
        text = "(no task text: the task is typed when the run starts)"
    elif len(text) > 100:
        text = text[:100] + "..."
    return f"{line}\n  {text}"


def merge_prepend_text(instruction_text: str, prepend_text: str) -> str:
    """Put a per-run text in front of the task. The saved instruction is untouched."""
    if not prepend_text:
        return instruction_text
    return f"{prepend_text}\n\n{instruction_text}"


def merge_extra_text(instruction_text: str, extra_text: str) -> str:
    """Add a per-run addendum after the task, under a heading that says what it is."""
    if not extra_text:
        return instruction_text
    return f"{instruction_text}\n\n{EXTRA_TEXT_HEADING}\n{extra_text}"
