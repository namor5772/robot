"""Run settings: what one run of the agent is configured with."""

from dataclasses import dataclass, field

from robot import models


@dataclass
class RunSettings:
    """The settings of one run. A saved instruction supplies them; so do the
    built-in defaults for a chat started without one."""

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


EXTRA_TEXT_HEADING = ("--- ADDITIONAL TASK CONTEXT (for this run only, from the "
                      "launching process) ---")


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
