"""The Memories window: look at what the robot remembers, and look after it.

A memory is made by using it (an instruction names it), so there is nothing
to create here. This window shows each memory there is, lets its text be
corrected, copies one, takes one back to an earlier state and deletes one.
The files are read again before every change: a run may have remembered
something since the window opened.
"""

import datetime

from robot import instructions, memory
from robot.tui.widgets import Button, Label, ListBox, TextArea, Window, flow

TITLE = "Memories"


def version_label(path) -> str:
    """An earlier state as a list shows it: when it was put aside, and its size."""
    stamp = path.stem[len("memory_"):]
    try:
        when = datetime.datetime.strptime(stamp[:15], "%Y%m%d_%H%M%S").strftime(
            "%Y-%m-%d %H:%M:%S")
    except ValueError:
        when = stamp
    try:
        words = len(path.read_text(encoding="utf-8", errors="replace").split())
    except OSError:
        words = 0
    return f"{when}{stamp[15:]}  ({words} words)"


class MemoriesWindow(Window):
    hint = "Esc: close"

    def __init__(self, app):
        super().__init__(app)
        self.names = []
        self.store = None
        self.list = self.add(ListBox("&Memories", on_move=self._on_move))
        self.used_label = self.add(Label())
        self.facts_label = self.add(Label("", "dim"))
        self.kept_label = self.add(Label("", "dim"))
        self.text = self.add(TextArea("What it &remembers", read_only=True))
        self.actions = [
            self.add(Button("&Edit", self.edit)),
            self.add(Button("Cop&y", self.copy)),
            self.add(Button("Roll &back", self.roll_back)),
            self.add(Button("&Delete", self.delete)),
        ]
        self.close_button = self.add(Button("Close", self.on_escape))
        self._reload(memory.SHARED)
        self.focus = self.list

    @property
    def title(self):
        return f"{TITLE}: {memory.label(self.store.name)}"

    # -- showing -------------------------------------------------------------------

    def _reload(self, select=memory.SHARED):
        """Read what there is and show the memory called `select`."""
        self.names = [memory.SHARED] + memory.names(self.app.datadir)
        index = self.names.index(select) if select in self.names else 0
        self.list.set_items([memory.label(name) for name in self.names], index)
        self._show(self.names[index])

    def _show(self, name):
        store = self.store = memory.Store(self.app.datadir, name)
        used = memory.users(self.app.datadir, name)
        self.used_label.text = "Used by: " + (", ".join(used) or "no instruction")
        awake = store.last_awake().replace("T", " ")[:16] or "never"
        self.facts_label.text = f"{store.words()} words. Last awake: {awake}."
        self.kept_label.text = (f"In the diary: {len(store.diary())} conversations. "
                                f"Earlier states: {len(store.versions())}.")
        remembered = store.memory() or "(nothing is remembered yet)"
        diary = "\n\n".join(store.diary())
        self.text.set_text(remembered + ("\n\n--- The diary ---\n\n" + diary if diary else ""))

    def _on_move(self, index):
        self._show(self.names[index])
        return True

    # -- what stands in the way of a change ------------------------------------------

    def _busy(self) -> bool:
        """True, with a message, while a run is using this memory: it will
        write the memory when it ends, over whatever was done here."""
        if not self.app.running:
            return False
        entry = instructions.load_instructions(self.app.datadir).get(self.app.instruction) or {}
        if not entry.get("memory") or str(entry.get("memory_name") or "") != self.store.name:
            return False
        self.app.message(TITLE, "The run in progress uses this memory and will write to it "
                                "when it ends. Change it when the run is over.")
        return True

    def _fail(self, error):
        self.app.message(TITLE, f"That could not be done: {error}")

    # -- the buttons -------------------------------------------------------------------

    def edit(self):
        """Correct the memory's text by hand. The diary is a record and is not edited."""
        if self._busy():
            return
        name = self.store.name
        before = self.store.memory()
        text = self.app.edit_text(
            f"What '{memory.label(name)}' remembers", before,
            hint="The robot is told this text as its own memory.")
        if text is None or text.strip() == before:
            return
        try:
            memory.Store(self.app.datadir, name).set_memory(text)
        except OSError as error:
            self._fail(error)
            return
        self._reload(name)
        self.app.status = f"Saved what '{memory.label(name)}' remembers."

    def copy(self):
        source = self.store
        if not source.exists():
            self.app.message(TITLE, "This memory is empty: there is nothing to copy.")
            return
        typed = self.app.edit_text(
            "Name of the copy", "",
            hint="Letters, digits, spaces, - and _. An instruction can then use it.")
        name = " ".join((typed or "").split())
        if not name:
            return
        problem = memory.name_problem(name)
        if problem:
            self.app.message(TITLE, problem)
            return
        target = memory.Store(self.app.datadir, name)
        if target.exists():
            self.app.message(TITLE, f"There is a memory named '{name}' already.")
            return
        try:
            source.copy_to(target)
        except OSError as error:
            self._fail(error)
            return
        self._reload(name)
        self.app.status = f"Copied '{memory.label(source.name)}' to '{name}'."

    def roll_back(self):
        if self._busy():
            return
        name = self.store.name
        versions = self.store.versions()
        if not versions:
            self.app.message(TITLE, "No earlier state of this memory has been kept.")
            return
        newest_first = versions[::-1]
        rows = [version_label(path) for path in newest_first]
        picked = self.app.pick("Go back to the memory as it was before", rows)
        if picked is None:
            return
        version = newest_first[rows.index(picked)]
        try:
            earlier = version.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self._fail(error)
            return
        self.app.show_text(f"The memory as it was: {picked}", earlier)
        if not self.app.confirm(TITLE, "Make this the memory again? The memory as it is now "
                                       "is kept among the earlier states."):
            return
        try:
            memory.Store(self.app.datadir, name).roll_back(version)
        except OSError as error:
            self._fail(error)
            return
        self._reload(name)
        self.app.status = f"'{memory.label(name)}' is as it was at {picked.split('  ')[0]}."

    def delete(self):
        if self._busy():
            return
        name = self.store.name
        if not self.store.exists():
            self.app.message(TITLE, "This memory is empty: there is nothing to delete.")
            return
        used = memory.users(self.app.datadir, name)
        after = (f" {', '.join(used)} will start again with no memories."
                 if used else "")
        if not self.app.confirm(
                TITLE, f"Delete everything '{memory.label(name)}' remembers, its diary and "
                       f"its earlier states?{after} This cannot be undone."):
            return
        try:
            memory.Store(self.app.datadir, name).delete()
        except OSError as error:
            self._fail(error)
            return
        self._reload(memory.SHARED)
        self.app.status = f"Deleted the memory '{memory.label(name)}'."

    def on_escape(self):
        self.close(None)

    # -- layout --------------------------------------------------------------------------

    def layout(self, rows, cols):
        self.y = self.x = 0
        self.h, self.w = rows, cols
        list_width = max(16, min(30, cols // 3 - 2))
        self.list.place(1, 1, list_width, rows - 2)
        x = list_width + 2
        width = cols - x - 2
        self.used_label.place(1, x, width)
        self.facts_label.place(2, x, width)
        self.kept_label.place(3, x, width)
        self.text.place(4, x, width, max(3, rows - 6))
        flow(self.actions, rows - 2, x, width)
        self.close_button.place(rows - 2, cols - 2 - self.close_button.w)
