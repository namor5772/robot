"""The Meta tools: the agent managing its own instructions and skills.

Runs of an instruction with Meta on are offered these. Their behaviour follows
MyAgent's, without the parts that belong to its windows.
"""

import json

from robot import instructions, models, skills, spawn
from robot.tools import Tool

_MODE_CHOICES = list(models.THINKING_MODES)
_SKILL_MODES = list(skills.MODES)

MANAGE_INSTRUCTIONS_TOOL = {
    "name": "manage_instructions",
    "description": (
        "Manage the saved instruction library on disk. An instruction is a saved task "
        "plus the settings to run it with; its text is sent as the first message of a "
        "run. You CAN read and update the instruction that is running now: changes are "
        "saved to disk and take effect the next time it is run (this run is not "
        "affected). The entry named 'Default' holds the settings of a chat started "
        "without naming an instruction. Actions: list (show all), read (full detail), "
        "create (new), update (modify), delete (remove)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "create", "update", "delete"],
                "description": "The operation to perform",
            },
            "name": {
                "type": "string",
                "description": "Instruction name (required for all except list)",
            },
            "text": {
                "type": "string",
                "description": "The task text (required for create, optional for update)",
            },
            "notes": {
                "type": "string",
                "description": (
                    "Free-text notes about the instruction (what it is for, caveats). "
                    "Stored with it and NEVER sent to the model. Optional; '' clears."
                ),
            },
            "meta": {
                "type": "boolean",
                "description": (
                    "Give runs of this instruction the Meta tools: manage_instructions, "
                    "manage_skills, run_instruction and upgrade_model (default false on "
                    "create)"
                ),
            },
            "conversational": {
                "type": "boolean",
                "description": (
                    "Convo mode: after every reply the person is asked for the next "
                    "message, so the run is a conversation instead of a single task "
                    "(default false on create)"
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Anthropic model id, for example claude-opus-5-5, claude-sonnet-5-5, "
                    "claude-haiku-5-5 or claude-fable-5-2 (optional; create uses this "
                    "run's model when it is left out)"
                ),
            },
            "thinking_mode": {
                "type": "string",
                "enum": _MODE_CHOICES,
                "description": (
                    "Thinking level (optional; create uses this run's level when it is "
                    "left out). Not every model has every level: one it lacks is replaced "
                    "by the nearest it has when a run starts. Models whose thinking is "
                    "always on (Opus 5.5, Fable) have no 'off'."
                ),
            },
            "thinking_budget": {
                "type": "integer",
                "description": (
                    "Thinking token budget. Only used by older models that take a budget "
                    "instead of a level."
                ),
            },
            "fast_mode": {
                "type": "boolean",
                "description": (
                    "Anthropic fast mode: faster output at a higher per-token price, on "
                    "the models that have it (Fable 5.2, Opus 5.5, Opus 5, Opus 4.8). "
                    "Ignored on other models."
                ),
            },
            "upgrade_target": {
                "type": "object",
                "description": (
                    "The model the upgrade_model tool moves a run of this instruction to: "
                    "{model, level, fast}. level is a thinking level such as 'Max'; fast "
                    "(optional, default false) runs the upgrade in fast mode where the "
                    "model has it. model '' means never upgrade. Left out, the default "
                    "applies: claude-fable-5-2 at Max, standard speed."
                ),
                "properties": {
                    "model": {"type": "string"},
                    "level": {"type": "string"},
                    "fast": {"type": "boolean"},
                },
            },
            "blocked_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Hard tool blocklist for runs of this instruction: these tool names "
                    "are not offered to the model and are refused if called anyway. On "
                    "update the whole list is replaced. An empty list clears it."
                ),
            },
            "skill_modes": {
                "type": "object",
                "description": (
                    "Skill modes for runs of this instruction, as a map of skill name to "
                    "'disabled', 'enabled' or 'on_demand'. When an instruction has such a "
                    "map, every skill NOT named in it is disabled for its runs. Leave it "
                    "out for the instruction to follow each skill's own mode. On update "
                    "the listed skills are merged into the existing map."
                ),
                "additionalProperties": {"type": "string", "enum": _SKILL_MODES},
            },
        },
        "required": ["action"],
    },
}

MANAGE_SKILLS_TOOL = {
    "name": "manage_skills",
    "description": (
        "Manage the skills library on disk. A skill is a piece of know-how for the "
        "agent. 'enabled' skills are put into every system prompt, 'on_demand' skills "
        "are listed there and fetched with get_skill when needed, 'disabled' skills are "
        "inactive. Each skill may carry a short description (what it does and when to "
        "use it), which is what on_demand skills are listed by. Actions: list, read, "
        "create, update, delete (the skill and its SKILL.md), plus list_files, "
        "read_file, write_file and delete_file for the bundled files a skill's folder "
        "may hold beside SKILL.md (scripts/, references/ and so on), addressed by skill "
        "name and a RELATIVE file_path inside the folder. A new or changed skill takes "
        "effect from the next run: this run's system prompt and tool list are fixed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "create", "update", "delete",
                         "list_files", "read_file", "write_file", "delete_file"],
                "description": "The operation to perform",
            },
            "name": {
                "type": "string",
                "description": (
                    "Skill name (required for all except list). On create it MUST be "
                    "kebab-case: lowercase letters, digits and hyphens, at most 64 "
                    "characters, for example 'check-battery'."
                ),
            },
            "content": {
                "type": "string",
                "description": "Skill text (required for create, optional for update)",
            },
            "description": {
                "type": "string",
                "description": (
                    "One or two sentences: WHAT the skill does and WHEN to use it. Shown "
                    "in the system prompt for on_demand skills. Optional; on update an "
                    "empty string clears it. Keep it under 1024 characters."
                ),
            },
            "mode": {
                "type": "string",
                "enum": _SKILL_MODES,
                "description": "Skill mode (default: disabled on create)",
            },
            "file_path": {
                "type": "string",
                "description": (
                    "RELATIVE path of a bundled file inside the skill's folder (required "
                    "for read_file, write_file and delete_file), for example "
                    "'scripts/run.sh'. Absolute paths, '..' and SKILL.md itself are "
                    "refused. Sub-folders are created on write and removed when emptied."
                ),
            },
            "file_content": {
                "type": "string",
                "description": (
                    "The full text to write (required for write_file). Overwrites an "
                    "existing file."
                ),
            },
        },
        "required": ["action"],
    },
}

UPGRADE_MODEL_TOOL = {
    "name": "upgrade_model",
    "description": (
        "Move THIS run to the instruction's upgrade model, a stronger model, for the "
        "rest of the run, from your next call on. Call it when the person asks for the "
        "stronger or upgraded model. A run upgrades once. The result says which model "
        "it moved to, or why nothing changed (no upgrade model set, already on it, "
        "already upgraded). Nothing is written to the saved instruction."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

RUN_INSTRUCTION_TOOL = {
    "name": "run_instruction",
    "description": (
        "Run a saved instruction as a separate child run of this program. By default "
        "the child runs on its own and this returns at once. Set wait=true to BLOCK "
        "until it finishes and get its final report back as this tool's result; use "
        "that when you need the child's answer to continue. A child is a whole extra "
        "process: on this small computer it takes about 15 seconds to start, and at "
        "most two can run at the same time, so start one only when the task really "
        "calls for it. Several run_instruction calls made in the same turn run "
        "concurrently. Use manage_instructions(action='list') first to see the names. "
        "A child's questions (its user_prompt calls and Convo turns) are answered from "
        "`answers` when given. Without `answers`, a waited child's question is put to "
        "the person at this run's terminal, and a child that is not waited for gets no "
        "answer and stops at its first question. `extra_text` adds task context after "
        "the child's saved instruction and `prepend_text` puts text in front of it, for "
        "that run only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the saved instruction to run",
            },
            "wait": {
                "type": "boolean",
                "description": (
                    "Wait for the child to finish and return its final report (default "
                    "false: start it and return at once)."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Longest time to wait when wait=true (default 600). On timeout the "
                    "child is stopped and an error is returned. Allow for the child's "
                    "slow start."
                ),
            },
            "extra_text": {
                "type": "string",
                "description": (
                    "Optional text added after the child's saved instruction as an "
                    "ADDITIONAL TASK CONTEXT block, for this run only: the specific "
                    "question, target or data for THIS child. The saved instruction is "
                    "unchanged."
                ),
            },
            "prepend_text": {
                "type": "string",
                "description": (
                    "Optional text put IN FRONT of the child's saved instruction, plain, "
                    "for this run only. extra_text is the labelled block after the "
                    "instruction; both may be given."
                ),
            },
            "answers": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Replies to the child's questions, in order: each question gets the "
                    "next entry as soon as it is asked. When the list is used up the "
                    "next question gets the EMPTY reply, which stops the child's run "
                    "cleanly ([] stops it at its first question). A waited call's "
                    "report lists each question and what it got."
                ),
            },
        },
        "required": ["name"],
    },
}

# The fields `update` can change, in the order its error message names them.
_UPDATABLE = ("text", "notes", "meta", "conversational", "model", "thinking_mode",
              "thinking_budget", "fast_mode", "upgrade_target", "blocked_tools", "skill_modes")
_PLAIN_FIELDS = ("text", "notes", "meta", "conversational", "model", "thinking_budget",
                 "fast_mode")


def _check_fields(params) -> str:
    """An error text for a field of the wrong kind, or ''."""
    for key in ("text", "notes", "model", "thinking_mode"):
        if params.get(key) is not None and not isinstance(params[key], str):
            return f"Error: '{key}' must be a string."
    for key in ("meta", "conversational", "fast_mode"):
        if params.get(key) is not None and not isinstance(params[key], bool):
            return f"Error: '{key}' must be true or false."
    budget = params.get("thinking_budget")
    if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool)
                               or budget <= 0):
        return "Error: 'thinking_budget' must be a positive whole number."
    mode = params.get("thinking_mode")
    if mode is not None and mode.strip().lower() not in models.THINKING_MODES:
        return ("Error: 'thinking_mode' must be one of "
                + ", ".join(models.THINKING_MODES) + ".")
    blocked = params.get("blocked_tools")
    if blocked is not None and (not isinstance(blocked, list)
                                or not all(isinstance(tool, str) for tool in blocked)):
        return "Error: 'blocked_tools' must be a list of tool names."
    modes = params.get("skill_modes")
    if modes is not None:
        if not isinstance(modes, dict):
            return "Error: 'skill_modes' must be a map of skill name to mode."
        for skill, mode_value in modes.items():
            if mode_value not in skills.MODES:
                return (f"Error: Invalid mode '{mode_value}' for skill '{skill}'. Valid "
                        "modes: disabled, enabled, on_demand.")
    target = params.get("upgrade_target")
    if target is not None and not isinstance(target, dict):
        return "Error: 'upgrade_target' must be an object with model, level and fast."
    return ""


def _level_note(entry) -> str:
    """A remark when the stored thinking level is one the model does not have."""
    model = entry.get("model") or models.DEFAULT_MODEL
    mode = str(entry.get("thinking_mode") or "")
    usable = models.coerce_mode(model, mode)
    if mode and usable != mode:
        return (f" Note: {model} has no thinking level '{mode}'; its runs will use "
                f"'{usable}'.")
    return ""


def manage_instructions(datadir, run_settings, params) -> str:
    """The manage_instructions tool.

    `run_settings` are the settings of the run that is calling: a new
    instruction takes the model settings it does not name from them.
    """
    action = params.get("action", "")
    name = params.get("name", "")
    name = name.strip() if isinstance(name, str) else ""
    library = instructions.load_instructions(datadir)

    if action == "list":
        if not library:
            return "No saved instructions."
        return "\n".join(instructions.describe(key, library[key]) for key in sorted(library))

    if not name:
        return "Error: 'name' is required for this action."

    if action == "read":
        if name not in library:
            return f"Error: Instruction '{name}' not found."
        entry = library[name]
        return json.dumps({
            "name": name,
            "text": entry.get("text", ""),
            "notes": entry.get("notes", ""),
            "meta": bool(entry.get("meta", False)),
            "conversational": bool(entry.get("conversational", False)),
            "provider": entry.get("provider", instructions.PROVIDER),
            "model": entry.get("model", ""),
            "thinking_mode": entry.get("thinking_mode") or models.mode_from_legacy(entry),
            "thinking_budget": entry.get("thinking_budget", models.DEFAULT_THINKING_BUDGET),
            "fast_mode": bool(entry.get("fast_mode", False)),
            "upgrade_target": entry.get("upgrade_target"),
            "skill_modes": entry.get("skill_modes", {}),
            "blocked_tools": entry.get("blocked_tools", []),
        }, indent=2, ensure_ascii=False)

    if action == "create":
        if name in library:
            return f"Error: Instruction '{name}' already exists. Use 'update' to modify it."
        if not params.get("text"):
            return "Error: 'text' is required when creating an instruction."
        problem = _check_fields(params)
        if problem:
            return problem
        entry = {
            "text": params["text"],
            "notes": params.get("notes") or "",
            "provider": instructions.PROVIDER,
            # Model settings the call does not name come from the run that is
            # creating the instruction (its own, never an upgrade's).
            "model": params.get("model") or run_settings.model,
            "thinking_mode": (params.get("thinking_mode") or run_settings.thinking_mode
                              ).strip().lower(),
            "thinking_budget": params.get("thinking_budget") or run_settings.thinking_budget,
            "fast_mode": (params["fast_mode"] if params.get("fast_mode") is not None
                          else bool(run_settings.fast_mode)),
            "meta": bool(params.get("meta", False)),
            "conversational": bool(params.get("conversational", False)),
            "blocked_tools": sorted(params["blocked_tools"]
                                    if params.get("blocked_tools") is not None
                                    else run_settings.blocked_tools or []),
        }
        if params.get("upgrade_target") is not None:
            entry["upgrade_target"] = models.sanitize_upgrade_target(params["upgrade_target"])
        # No skill_modes unless asked for: a map would switch off every skill
        # it does not name, including ones created later.
        if params.get("skill_modes") is not None:
            entry["skill_modes"] = dict(params["skill_modes"])
        library[name] = entry
        instructions.save_instructions(datadir, library)
        return f"Instruction '{name}' created successfully." + _level_note(entry)

    if action == "update":
        if name not in library:
            return f"Error: Instruction '{name}' not found. Use 'create' to add it."
        if all(params.get(key) is None for key in _UPDATABLE):
            return ("Error: At least one of " + ", ".join(f"'{key}'" for key in _UPDATABLE)
                    + " must be provided for update.")
        problem = _check_fields(params)
        if problem:
            return problem
        entry = library[name]
        for key in _PLAIN_FIELDS:
            if params.get(key) is not None:
                entry[key] = params[key]
        if params.get("thinking_mode") is not None:
            entry["thinking_mode"] = params["thinking_mode"].strip().lower()
        if params.get("blocked_tools") is not None:
            entry["blocked_tools"] = sorted(params["blocked_tools"])
        if params.get("skill_modes") is not None:
            merged = dict(entry.get("skill_modes") or {})
            merged.update(params["skill_modes"])
            entry["skill_modes"] = merged
        if params.get("upgrade_target") is not None:
            entry["upgrade_target"] = models.sanitize_upgrade_target(params["upgrade_target"])
        instructions.save_instructions(datadir, library)
        # A chat started without a name is running on Default's settings.
        running = run_settings.name or instructions.DEFAULT_NAME
        if name == running:
            reply = (f"Instruction '{name}' updated on disk. Changes will take effect next "
                     "time it is loaded.")
        else:
            reply = f"Instruction '{name}' updated successfully."
        return reply + _level_note(entry)

    if action == "delete":
        if name not in library:
            return f"Error: Instruction '{name}' not found."
        del library[name]
        instructions.save_instructions(datadir, library)
        reply = f"Instruction '{name}' deleted."
        if name == instructions.DEFAULT_NAME:
            reply += " It is re-created with built-in settings at the next start."
        return reply

    return f"Error: Unknown action '{action}'."


def meta_tools(agent) -> dict:
    """The Meta tools bound to one run, keyed by name."""
    tools = {
        "manage_instructions": Tool(
            definition=MANAGE_INSTRUCTIONS_TOOL,
            run=lambda params: manage_instructions(agent.datadir, agent.settings, params),
            is_available=lambda: True),
    }
    if agent.skills is not None:
        tools["manage_skills"] = Tool(
            definition=MANAGE_SKILLS_TOOL,
            run=lambda params: skills.manage_skills(agent.skills, params),
            is_available=lambda: True)
    # Waiting on a child only watches a process, so several can be waited on
    # at once: it is safe to run alongside other calls.
    tools["run_instruction"] = Tool(
        definition=RUN_INSTRUCTION_TOOL,
        run=lambda params: spawn.run_instruction(agent, params),
        is_available=lambda: True, parallel_safe=True)
    tools["upgrade_model"] = Tool(
        definition=UPGRADE_MODEL_TOOL, run=agent.do_upgrade_model,
        is_available=lambda: True)
    return tools
