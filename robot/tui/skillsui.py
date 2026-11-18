"""The Skills Manager: read and change skills, and switch them on and off.

Every change goes through manage_skills, the same code the model's tool of
that name runs, so the rules and the messages are the same either way. The
skills are read from disk again before each change: a run may have changed
them since this window opened.
"""

from robot import skills as skill_library
from robot.tui.dialogs import PickDialog
from robot.tui.editor import SKILL_MARKS, next_mode
from robot.tui.widgets import Button, Label, ListBox, TextArea, TextField, Window, flow

MODE_WORDS = {
    "disabled": "off (no run uses it)",
    "enabled": "ON (its text is in every run's prompt)",
    "on_demand": "OD (on demand: a run fetches it when needed)",
}


class SkillsManager(Window):
    hint = "Space on the list: change mode   Esc: close"

    def __init__(self, app):
        super().__init__(app)
        self.store = skill_library.SkillStore(app.datadir.skills_dir)
        self.names = []
        self.loaded = None    # the saved skill on the form; None for a new one
        self.mode = "disabled"
        self.description = ""
        self.files = []
        self.snapshot = None

        self.list = self.add(ListBox("S&kills", on_move=self._on_move, on_space=self.cycle))
        self.list.search_from = 5
        self.name = self.add(TextField("&Name"))
        self.mode_label = self.add(Label())
        self.buttons = [
            self.add(Button("&Cycle mode", self.cycle)),
            self.add(Button("D&escription", self._edit_description)),
            self.add(Button("&Files", self._show_files)),
        ]
        self.description_label = self.add(Label("", "dim"))
        self.files_label = self.add(Label("", "dim"))
        self.text = self.add(TextArea("Skill te&xt"))
        self.actions = [
            self.add(Button("&Save", self.save)),
            self.add(Button("Ne&w", self.new)),
            self.add(Button("&Delete", self.delete)),
        ]
        self.close_button = self.add(Button("Close", self.on_escape))
        self._reload()
        self.focus = self.list

    @property
    def title(self):
        shown = "new skill" if self.loaded is None else self.loaded
        return f"Skills Manager: {shown}{' (changed)' if self.changed() else ''}"

    # -- the form ------------------------------------------------------------------

    def _form(self) -> dict:
        return {"name": self.name.text.strip(), "content": self.text.text(),
                "description": " ".join(self.description.split())}

    def changed(self) -> bool:
        return self.snapshot is not None and self._form() != self.snapshot

    def _read_store(self) -> bool:
        try:
            self.store.load()
        except OSError as error:
            self.app.message("Skills Manager", f"Could not read the skills: {error}")
            return False
        return True

    def _rows(self):
        return [f"{SKILL_MARKS[self.store.global_mode(name)]} {name}" for name in self.names]

    def _reload(self, select=None):
        """Read the skills from disk and show the one called `select`, or the first."""
        self._read_store()
        self.names = sorted(self.store.skills, key=str.lower)
        index = self.names.index(select) if select in self.names else 0
        self.list.set_items(self._rows(), index)
        if self.names:
            self._load(self.names[index])
        else:
            self._blank()

    def _load(self, name):
        entry = self.store.skills[name]
        self.loaded = name
        self.mode = self.store.global_mode(name)
        self.description = str(entry.get("description") or "")
        self.files = self.store.resources(name)
        self.name.set(name)
        self.text.set_text(str(entry.get("content") or ""))
        self._refresh_labels()
        self.snapshot = self._form()

    def _blank(self):
        self.loaded = None
        self.mode = "disabled"
        self.description = ""
        self.files = []
        self.name.set("")
        self.text.set_text("")
        self._refresh_labels()
        self.snapshot = self._form()

    def _refresh_labels(self):
        self.mode_label.text = "Mode: " + MODE_WORDS[self.mode]
        self.description_label.text = "Description: " + (
            " ".join(self.description.split()) or "(none)")
        if self.files:
            names = ", ".join(path for path, _size in self.files)
            self.files_label.text = f"Bundled files ({len(self.files)}): {names}"
        else:
            self.files_label.text = "Bundled files: none"

    def _keep_changes(self, leaving) -> bool:
        return self.changed() and not self.app.confirm(
            "Skills Manager", f"{leaving} without saving your changes?")

    def _on_move(self, index):
        if self._keep_changes("Leave this skill"):
            return False
        name = self.names[index]
        if not self._read_store() or name not in self.store.skills:
            self._reload()
            return False
        self._load(name)
        return True

    def _report(self, reply) -> bool:
        """Show what manage_skills answered. True when the change was made."""
        if reply.startswith("Error"):
            self.app.message("Skills Manager", reply)
            return False
        first, _, rest = reply.partition("\n")
        self.app.status = first
        if rest.strip():
            self.app.message("Skills Manager", rest.strip())
        return True

    # -- the buttons -------------------------------------------------------------------

    def cycle(self):
        """Switch the skill to its next mode. For a saved skill that is stored at once."""
        mode = next_mode(self.mode)
        if self.loaded is not None:
            if not self._read_store():
                return
            reply = skill_library.manage_skills(
                self.store, {"action": "update", "name": self.loaded, "mode": mode})
            if not self._report(reply):
                return
            self.list.set_items(self._rows())
            self.app.status = f"'{self.loaded}' is now {MODE_WORDS[mode].split(' (')[0]}."
        self.mode = mode
        self._refresh_labels()

    def _edit_description(self):
        text = self.app.edit_text(
            "Description", self.description,
            hint="What the skill is for, and when to use it.")
        if text is not None:
            self.description = " ".join(text.split())
            self._refresh_labels()

    def _show_files(self):
        if not self.files:
            self.app.message("Skills Manager", "This skill has no bundled files: it is its "
                                               "text alone.")
            return
        rows = [f"{path}  ({size:,} bytes)" for path, size in self.files]
        while True:
            picked = self.app.run_modal(PickDialog(self.app, "Bundled files", rows))
            if picked is None:
                return
            path = self.files[rows.index(picked)][0]
            self.app.show_text(path, skill_library.manage_skills(
                self.store, {"action": "read_file", "name": self.loaded, "file_path": path}))

    def save(self) -> bool:
        form = self._form()
        name = form["name"]
        if not name:
            self.app.message("Skills Manager", "Give the skill a name first.")
            self.focus = self.name
            return False
        if not self._read_store():
            return False
        params = {"name": name, "content": form["content"], "description": form["description"]}
        if name in self.store.skills:
            if name != self.loaded and not self.app.confirm(
                    "Skills Manager", f"A skill named '{name}' already exists. Replace its "
                                      "text and description?"):
                return False
            params["action"] = "update"
        else:
            params["action"] = "create"
            params["mode"] = self.mode
        if not self._report(skill_library.manage_skills(self.store, params)):
            return False
        status = self.app.status
        self._reload(name)
        self.app.status = status
        return True

    def new(self):
        if self._keep_changes("Start a new skill"):
            return
        self._blank()
        self.focus = self.name

    def delete(self):
        name = self.loaded
        if name is None:
            self.app.message("Skills Manager", "This skill has not been saved, so there is "
                                               "nothing to delete.")
            return
        extra = " Its bundled files go with it." if self.files else ""
        if not self.app.confirm("Skills Manager",
                                f"Delete the skill '{name}'?{extra} This cannot be undone."):
            return
        if not self._read_store():
            return
        reply = skill_library.manage_skills(self.store, {"action": "delete", "name": name})
        done = self._report(reply)
        status = self.app.status
        self._reload()
        if done:
            self.app.status = status

    def on_escape(self):
        if not self._keep_changes("Close the Skills Manager"):
            self.close(None)

    # -- layout --------------------------------------------------------------------------

    def layout(self, rows, cols):
        self.y = self.x = 0
        self.h, self.w = rows, cols
        list_width = max(16, min(34, cols // 3))
        self.list.place(1, 1, list_width, rows - 2)
        x = list_width + 2
        width = cols - x - 2
        self.name.place(1, x, width)
        self.mode_label.place(2, x, width)
        y = flow(self.buttons, 3, x, width)
        self.description_label.place(y, x, width)
        self.files_label.place(y + 1, x, width)
        y += 2
        self.text.place(y, x, width, max(3, rows - 2 - y))
        flow(self.actions, rows - 2, x, width)
        self.close_button.place(rows - 2, cols - 2 - self.close_button.w)
