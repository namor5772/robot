"""The Instruction Editor: choose, change, create and delete saved instructions.

The form shows one instruction at a time. Nothing is written until Save, and
Save reads the library afresh first, so a change made meanwhile by a run (its
manage_instructions tool) to another instruction is kept.
"""

from robot import instructions, memory, models
from robot import skills as skill_library
from robot.datastore import StoreUnreadableError
from robot.tui.dialogs import ChecklistDialog, _place_buttons_right
from robot.tui.widgets import (
    Button, Checkbox, Choice, Label, ListBox, TextArea, TextField, Window, flow)

# In the Memory list, beside the memories themselves.
MEMORY_OFF = "off"
MEMORY_NEW = "new name..."

# The tools that the Meta switch offers together. Without it none of them is
# offered, whatever the instruction's own list of blocked tools says.
META_TOOL_NAMES = ("manage_instructions", "manage_skills", "manage_memories",
                   "run_instruction", "upgrade_model")

# Every tool a run can be offered, for the list of tools an instruction may use.
TOOL_NAMES = (
    "run_shell_command", "get_current_datetime", "view_image", "microphone_listen", "speak",
    "voice_settings", "user_prompt", "get_skill", "web_search",
) + META_TOOL_NAMES

SKILL_MARKS = {"enabled": "[ON]", "on_demand": "[OD]", "disabled": "[  ]"}


def next_mode(mode) -> str:
    """The skill mode that follows `mode` when cycling: off, on, on demand."""
    order = skill_library.MODES
    return order[(order.index(mode) + 1) % len(order)] if mode in order else order[0]


class SkillModesDialog(Window):
    """Which skills an instruction runs with. Its result is the instruction's
    skill_modes: empty for "each skill's own mode", else a mode for every skill."""

    title = "Skills for this instruction"
    hint = "Space: change a skill   Esc: cancel"

    def __init__(self, app, store, skill_modes):
        super().__init__(app)
        self.store = store
        self.names = sorted(store.skills, key=str.lower)
        self.own = self.add(Checkbox("&Use each skill's own mode", not skill_modes,
                                     self._own_changed))
        self.list = self.add(ListBox("&Skills", on_activate=self._cycle, on_space=self._cycle))
        self.list.search_from = 5
        self.notes = [
            self.add(Label("Space changes a skill: off, ON (its text is in the prompt),", "dim")),
            self.add(Label("OD (on demand). A skill added later starts off in this set.", "dim")),
        ]
        self.buttons = [self.add(Button("&OK", self._ok)), self.add(Button("&Cancel", self.close))]
        if skill_modes:
            # A saved set names the skills it wants; any other skill is off.
            self.modes = {name: skill_modes.get(name) if skill_modes.get(name)
                          in skill_library.MODES else "disabled" for name in self.names}
        else:
            self.modes = self._own_modes()
        self._refresh()
        self.focus = self.list if self.names else self.buttons[1]

    def _own_modes(self):
        return {name: self.store.global_mode(name) for name in self.names}

    def _refresh(self):
        self.list.set_items([f"{SKILL_MARKS[self.modes[name]]} {name}" for name in self.names])
        self.list.note = "as set in the Skills Manager" if self.own.value else "this set"

    def _own_changed(self, ticked):
        if ticked:
            self.modes = self._own_modes()
        self._refresh()

    def _cycle(self):
        if not self.names:
            return
        self.own.value = False  # changing one skill makes this the instruction's own set
        name = self.names[self.list.index]
        self.modes[name] = next_mode(self.modes[name])
        self._refresh()

    def _ok(self):
        self.close({} if self.own.value or not self.names else dict(self.modes))

    def layout(self, rows, cols):
        longest = max((len(name) for name in self.names), default=0)
        self.center(rows, cols, len(self.names) + 9, max(66, longest + 12))
        self.own.place(self.y + 1, self.x + 2)
        self.list.place(self.y + 2, self.x + 1, self.w - 2, self.h - 6)
        for offset, note in enumerate(self.notes):
            note.place(self.y + self.h - 4 + offset, self.x + 2, self.w - 4)
        _place_buttons_right(self, self.buttons)


class UpgradeDialog(Window):
    """Where upgrade_model moves a run of this instruction. Its result is a
    one-item tuple holding the instruction's upgrade_target (None: the default)."""

    title = "Model upgrade"
    hint = "Esc: cancel"
    NEVER = "never upgrade"

    def __init__(self, app, target):
        super().__init__(app)
        default = models.UPGRADE_DEFAULT_TARGET
        self.default_label = f"the default ({default['model']}, {default['level']})"
        options = [self.default_label, self.NEVER] + list(models.FALLBACK_MODELS)
        level, fast = "", False
        if target is None:
            value = self.default_label
        elif not target.get("model"):
            value = self.NEVER
        else:
            value, level, fast = target["model"], target.get("level") or "", bool(
                target.get("fast"))
            if value not in options:
                options.append(value)
        self.notes = [
            self.add(Label("A run with Meta on can move itself to a stronger model", "dim")),
            self.add(Label("with its upgrade_model tool. This is where it goes.", "dim")),
        ]
        self.to = self.add(Choice("Upgrade &to", options, value, self._to_changed))
        self.level = self.add(Choice("&Level", [], ""))
        self.fast = self.add(Checkbox("&Fast", fast))
        self.buttons = [self.add(Button("&OK", self._ok)), self.add(Button("&Cancel", self.close))]
        self._to_changed(value, level)
        self.focus = self.to

    def _is_model(self, value) -> bool:
        return value not in (self.default_label, self.NEVER)

    def _to_changed(self, value, level=None):
        levels = models.upgrade_levels(value) if self._is_model(value) else []
        wanted = self.level.value if level is None else level
        self.level.set_options(levels, models.upgrade_level_for(value, wanted) if levels else "")
        self.level.enabled = bool(levels)
        self.fast.enabled = self._is_model(value) and models.supports_fast_mode(value)
        if not self.fast.enabled:
            self.fast.value = False

    def _ok(self):
        value = self.to.value
        if value == self.default_label:
            self.close((None,))
        elif value == self.NEVER:
            self.close(({"model": "", "level": "", "fast": False},))
        else:
            self.close(({"model": value, "level": self.level.value,
                         "fast": bool(self.fast.value)},))

    def layout(self, rows, cols):
        self.center(rows, cols, 10, 64)
        for offset, note in enumerate(self.notes):
            note.place(self.y + 1 + offset, self.x + 2, self.w - 4)
        self.to.place(self.y + 4, self.x + 2, self.w - 4)
        self.level.place(self.y + 5, self.x + 2, 22)
        self.fast.place(self.y + 6, self.x + 2)
        _place_buttons_right(self, self.buttons)


class InstructionEditor(Window):
    hint = "Tab: next   Alt+letter   Esc: close"

    def __init__(self, app):
        super().__init__(app)
        self.names = []
        self.loaded = None   # the saved instruction on the form; None for a new one
        self.foreign = ""    # who an instruction made for another program belongs to
        self.snapshot = None  # the form as it was loaded or last saved
        self.notes = ""
        self.blocked = []
        self.skill_modes = {}
        self.upgrade = None

        self.list = self.add(ListBox("&Instructions", on_move=self._on_move))
        self.name = self.add(TextField("&Name"))
        self.model = self.add(Choice("M&odel", on_change=self._model_changed))
        self.thinking = self.add(Choice("T&hinking"))
        self.fast = self.add(Checkbox("&Fast"))
        self.meta = self.add(Checkbox("M&eta"))
        self.convo = self.add(Checkbox("&Convo"))
        self.memory = self.add(Choice("&Memory", on_change=self._memory_changed))
        self._memory_was = MEMORY_OFF
        self.extras = [
            self.add(Button("No&tes", self._edit_notes)),
            self.add(Button("Too&ls", self._edit_tools)),
            self.add(Button("S&kills", self._edit_skills)),
            self.add(Button("Up&grade", self._edit_upgrade)),
        ]
        self.summary = [self.add(Label("", "dim")), self.add(Label("", "dim"))]
        self.text = self.add(TextArea("Instruction te&xt"))
        self.actions = [
            self.add(Button("&Save", self.save)),
            self.add(Button("&Use", self.use)),
            self.add(Button("Ne&w", self.new)),
            self.add(Button("&Delete", self.delete)),
        ]
        self.close_button = self.add(Button("Close", self.on_escape))
        self._reload(app.instruction)
        self.focus = self.list

    @property
    def title(self):
        shown = "new instruction" if self.loaded is None else self.loaded
        return f"Instruction Editor: {shown}{' (changed)' if self.changed() else ''}"

    # -- the form ----------------------------------------------------------------

    def _form(self) -> dict:
        return {
            "name": self.name.text.strip(), "text": self.text.text(),
            "model": self.model.value, "thinking": self.thinking.value,
            "fast": self.fast.value, "meta": self.meta.value, "convo": self.convo.value,
            "memory": self.memory.value,
            "notes": self.notes, "blocked": list(self.blocked),
            "skill_modes": dict(self.skill_modes),
            "upgrade": dict(self.upgrade) if self.upgrade is not None else None,
        }

    def changed(self) -> bool:
        return self.snapshot is not None and self._form() != self.snapshot

    def _set_model(self, model, mode):
        """Show a model, and the thinking levels and speed that model has."""
        options = list(models.FALLBACK_MODELS)
        if model not in options:
            options.append(model)
        self.model.set_options(options, model)
        self.thinking.set_options(models.mode_values(model), models.coerce_mode(model, mode))
        self.fast.enabled = models.supports_fast_mode(model)
        if not self.fast.enabled:
            self.fast.value = False

    def _model_changed(self, model):
        self._set_model(model, self.thinking.value)

    def _reload(self, select=None):
        """Read the library and show the instruction called `select`, or the first."""
        library = instructions.load_instructions(self.app.datadir)
        self.names = sorted(library, key=str.lower)
        in_use = self.app.instruction
        index = self.names.index(select) if select in self.names else 0
        self.list.set_items(
            [name + ("  (in use)" if name == in_use else "") for name in self.names], index)
        if self.names:
            self._load(self.names[index], library[self.names[index]])
        else:
            self._blank()

    def _load(self, name, entry):
        self.loaded = name
        provider = str(entry.get("provider") or instructions.PROVIDER)
        self.foreign = "" if provider == instructions.PROVIDER else provider
        model = str(entry.get("model") or models.DEFAULT_MODEL)
        mode = str(entry.get("thinking_mode") or models.mode_from_legacy(entry)).strip().lower()
        if models.thinking_support(model) == "manual" and entry.get("thinking_enabled") is False:
            mode = "off"
        self.name.set(name)
        self._set_model(model, mode)
        self.fast.value = bool(entry.get("fast_mode")) and self.fast.enabled
        self.meta.value = bool(entry.get("meta"))
        self.convo.value = bool(entry.get("conversational"))
        self._set_memory(bool(entry.get("memory")), str(entry.get("memory_name") or ""))
        self.notes = str(entry.get("notes") or "")
        blocked = entry.get("blocked_tools")
        self.blocked = (sorted({str(tool) for tool in blocked})
                        if isinstance(blocked, (list, tuple)) else [])
        modes = entry.get("skill_modes")
        self.skill_modes = dict(modes) if isinstance(modes, dict) else {}
        target = entry.get("upgrade_target")
        self.upgrade = models.sanitize_upgrade_target(target) if target is not None else None
        self.text.set_text(str(entry.get("text") or ""))
        self._refresh_summary()
        self.snapshot = self._form()

    def _blank(self):
        """An empty form for a new instruction. The settings shown stay as they are."""
        self.loaded = None
        self.foreign = ""
        if not self.model.options:
            self._set_model(models.DEFAULT_MODEL, "low")
        if not self.memory.options:
            self._set_memory(False)
        self.name.set("")
        self.text.set_text("")
        self.notes = ""
        self.blocked = []
        self.skill_modes = {}
        self.upgrade = None
        self._refresh_summary()
        self.snapshot = self._form()

    # -- which memory ----------------------------------------------------------

    def _memory_options(self, current="") -> list:
        """Off, the shared memory, every named one there is or that an
        instruction asks for, and the way to name a new one."""
        datadir = self.app.datadir
        found = set(memory.names(datadir))
        for entry in instructions.load_instructions(datadir).values():
            name = str(entry.get("memory_name") or "")
            if entry.get("memory") and name:
                found.add(name)
        if current:
            found.add(current)
        return ([MEMORY_OFF, memory.SHARED_LABEL] + sorted(found, key=str.lower)
                + [MEMORY_NEW])

    def _set_memory(self, on, name=""):
        value = memory.label(name) if on else MEMORY_OFF
        self.memory.set_options(self._memory_options(name if on else ""), value)
        self._memory_was = value

    def _memory_changed(self, picked):
        if picked != MEMORY_NEW:
            self._memory_was = picked
            return
        self.memory.value = self._memory_was  # until a name has been given
        typed = self.app.edit_text(
            "Name of the new memory", "",
            hint="Letters, digits, spaces, - and _. It starts empty.")
        name = " ".join((typed or "").split())
        if not name:
            return
        problem = memory.name_problem(name)
        if problem:
            self.app.message("Instruction Editor", problem)
            return
        self.memory.set_options(self._memory_options(name), name)
        self._memory_was = name

    def _refresh_summary(self):
        if self.foreign:
            self.summary[0].text = f"Set up for {self.foreign} by another program."
            self.summary[1].text = "It can be read here, but not changed or run."
            return
        tools = f"{len(self.blocked)} blocked" if self.blocked else "all allowed"
        if self.skill_modes:
            switched_on = sum(1 for mode in self.skill_modes.values() if mode != "disabled")
            skills = f"its own set ({switched_on} on)"
        else:
            skills = "each skill's own mode"
        if self.upgrade is None:
            upgrade = "the default"
        elif not self.upgrade.get("model"):
            upgrade = "never"
        else:
            upgrade = self.upgrade["model"]
        notes = "yes" if self.notes.strip() else "none"
        self.summary[0].text = f"Tools: {tools}. Skills: {skills}."
        self.summary[1].text = f"Upgrade: {upgrade}. Notes: {notes}."

    def _keep_changes(self, leaving) -> bool:
        """True when unsaved changes must not be thrown away after all."""
        return self.changed() and not self.app.confirm(
            "Instruction Editor", f"{leaving} without saving your changes?")

    def _on_move(self, index):
        if self._keep_changes("Leave this instruction"):
            return False
        library = instructions.load_instructions(self.app.datadir)
        name = self.names[index]
        if name not in library:  # deleted meanwhile, by a run
            self._reload()
            return False
        self._load(name, library[name])
        return True

    # -- the small windows behind the buttons ---------------------------------------

    def _edit_notes(self):
        text = self.app.edit_text(
            "Notes", self.notes, hint="For you: notes are never sent to the model.")
        if text is not None:
            self.notes = text
            self._refresh_summary()

    def _edit_tools(self):
        names = list(TOOL_NAMES) + [name for name in self.blocked if name not in TOOL_NAMES]
        # A tick only says "not blocked". With the Meta box clear its five
        # tools are not offered at all, so a tick there would promise what a
        # run does not get: those rows are shown switched off instead, and
        # whether each is blocked is kept as it is for when Meta is ticked.
        without_meta = [index for index, name in enumerate(names)
                        if name in META_TOOL_NAMES and not self.meta.value]
        labels = [f"{name}  (needs Meta)" if index in without_meta else name
                  for index, name in enumerate(names)]
        hint = ("Space ticks or clears. [-] needs the Meta box ticked." if without_meta
                else "Space ticks or clears. A cleared tool is blocked.")
        ticks = self.app.run_modal(ChecklistDialog(
            self.app, "Tools this instruction may use", labels,
            [name not in self.blocked for name in names], hint=hint, locked=without_meta))
        if ticks is not None:
            self.blocked = sorted(name for name, allowed in zip(names, ticks) if not allowed)
            self._refresh_summary()

    def _edit_skills(self):
        store = skill_library.SkillStore(self.app.datadir.skills_dir)
        try:
            store.load()
        except OSError as error:
            self.app.message("Skills", f"Could not read the skills: {error}")
            return
        modes = self.app.run_modal(SkillModesDialog(self.app, store, self.skill_modes))
        if modes is not None:
            self.skill_modes = modes
            self._refresh_summary()

    def _edit_upgrade(self):
        result = self.app.run_modal(UpgradeDialog(self.app, self.upgrade))
        if result is not None:
            self.upgrade = result[0]
            self._refresh_summary()

    # -- the buttons -----------------------------------------------------------------

    def _refuse_foreign(self) -> bool:
        if self.foreign:
            self.app.message("Instruction Editor",
                             f"This instruction is set up for {self.foreign} by another "
                             "program. It can be read here, but not changed or run.")
        return bool(self.foreign)

    def save(self) -> bool:
        """Store the form under the name in the Name box. True when it was saved."""
        if self._refuse_foreign():
            return False
        form = self._form()
        name = form["name"]
        if not name:
            self.app.message("Instruction Editor", "Give the instruction a name first.")
            self.focus = self.name
            return False
        library = instructions.load_instructions(self.app.datadir)
        if name in library and name != self.loaded and not self.app.confirm(
                "Instruction Editor", f"An instruction named '{name}' already exists. "
                                      "Replace it?"):
            return False
        entry = dict(library.get(name) or {})  # keys other programs keep there stay
        entry.update({
            "text": form["text"], "notes": form["notes"], "provider": instructions.PROVIDER,
            "model": form["model"], "thinking_mode": form["thinking"],
            "fast_mode": form["fast"], "meta": form["meta"], "conversational": form["convo"],
            "memory": form["memory"] != MEMORY_OFF,
            "memory_name": ("" if form["memory"] in (MEMORY_OFF, memory.SHARED_LABEL)
                            else form["memory"]),
            "blocked_tools": form["blocked"],
        })
        if "thinking_enabled" in entry:
            entry["thinking_enabled"] = form["thinking"] != "off"
        if form["skill_modes"]:
            entry["skill_modes"] = form["skill_modes"]
        else:
            entry.pop("skill_modes", None)
        if form["upgrade"] is None:
            entry.pop("upgrade_target", None)
        else:
            entry["upgrade_target"] = form["upgrade"]
        library[name] = entry
        if not self._write(library):
            return False
        self._reload(name)
        self.app.refresh_instruction()
        self.app.status = f"Saved '{name}'."
        return True

    def _write(self, library) -> bool:
        try:
            instructions.save_instructions(self.app.datadir, library)
        except (StoreUnreadableError, OSError, ValueError) as error:
            self.app.message("Instruction Editor", f"Could not save: {error}")
            return False
        return True

    def use(self):
        """Make this instruction the one START runs, and close the editor."""
        if self._refuse_foreign():
            return
        if self.loaded is None or self.changed():
            if self.app.choose("Instruction Editor", "Save this instruction first?",
                               ("&Save and use", "&Cancel")) != 0:
                return
            if not self.save():
                return
        self.app.set_instruction(self.loaded)
        self.close(self.loaded)

    def new(self):
        if self._keep_changes("Start a new instruction"):
            return
        self._blank()
        self.focus = self.name

    def delete(self):
        name = self.loaded
        if name is None:
            self.app.message("Instruction Editor", "This instruction has not been saved, "
                                                   "so there is nothing to delete.")
            return
        if not self.app.confirm("Instruction Editor",
                                f"Delete the instruction '{name}'? This cannot be undone."):
            return
        library = instructions.load_instructions(self.app.datadir)
        library.pop(name, None)
        if not self._write(library):
            return
        self.app.refresh_instruction()  # creates Default again if that was the one
        self._reload()
        if name == instructions.DEFAULT_NAME:
            self.app.status = "Default is back at its built-in settings."
        else:
            self.app.status = f"Deleted '{name}'."

    def on_escape(self):
        if not self._keep_changes("Close the editor"):
            self.close(None)

    # -- layout ------------------------------------------------------------------------

    def layout(self, rows, cols):
        self.y = self.x = 0
        self.h, self.w = rows, cols
        list_width = max(16, min(30, cols // 3 - 2))
        self.list.place(1, 1, list_width, rows - 2)
        x = list_width + 2
        width = cols - x - 2
        self.name.place(1, x, width)
        self.model.w = min(width, 41)
        self.thinking.w = 22
        self.memory.w = 34
        y = flow([self.model], 2, x, width)
        y = flow([self.thinking, self.fast, self.meta, self.convo, self.memory], y, x, width)
        y = flow(self.extras, y, x, width)
        for label in self.summary:
            label.place(y, x, width)
            y += 1
        self.text.place(y, x, width, max(3, rows - 2 - y))
        flow(self.actions, rows - 2, x, width)
        self.close_button.place(rows - 2, cols - 2 - self.close_button.w)
