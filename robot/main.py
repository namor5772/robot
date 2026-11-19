"""Robot brain entry point: run the agent from the command line.

    python -m robot.main              chat: type the task at you>, then converse
    python -m robot.main -l "Name"    run a saved instruction
    python -m robot.main --list       show the saved instructions
    python -m robot.main --help       every option

Nothing here imports the Anthropic SDK directly. It takes many seconds to load
on the Pi, so it is loaded in the background while the person types, and the
listing commands never load it at all.
"""

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

from robot import costs, instructions, models
from robot.console import INTERRUPTED, Console, Interrupts, convo_end_word
from robot.datastore import DataDir, StoreUnreadableError
from robot.skills import SkillStore
from robot.tools import available_tools

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

EXIT_OK = 0
EXIT_RUN_ERROR = 1
EXIT_CANNOT_START = 2


class CannotStart(Exception):
    """The run asked for cannot be started; the message says why."""


class ClientLoader:
    """Loads the Anthropic SDK and makes the client on a background thread."""

    def __init__(self):
        self._ready = threading.Event()
        self._client = None
        self._error = None
        threading.Thread(target=self._load, name="sdk-loader", daemon=True).start()

    def _load(self):
        try:
            import anthropic

            import robot.agent  # noqa: F401  (everything else a run needs)
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        except BaseException as error:
            self._error = error
        finally:
            self._ready.set()

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def get(self):
        self._ready.wait()
        if self._error is not None:
            raise self._error
        return self._client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m robot.main",
        description="The robot's agent. With no options it asks for a task and then chats.")
    parser.add_argument("-l", "--load", metavar="NAME",
                        help="run the saved instruction with this name")
    parser.add_argument("--list", action="store_true",
                        help="list the saved instructions and exit")
    parser.add_argument("--skills", action="store_true", help="list the skills and exit")
    run = parser.add_argument_group("the run")
    run.add_argument("--model", metavar="ID", help="use this model for the run")
    run.add_argument("--mode", metavar="LEVEL", choices=models.THINKING_MODES,
                     help="thinking level for the run: " + ", ".join(models.THINKING_MODES))
    run.add_argument("--headless", action="store_true",
                     help="unattended: never read the terminal")
    run.add_argument("--result-file", metavar="PATH",
                     help="write the run's outcome here as JSON when it ends")
    run.add_argument("--extra-file", metavar="PATH",
                     help="text added after the task, for this run only")
    run.add_argument("--prepend-file", metavar="PATH",
                     help="text put in front of the task, for this run only")
    run.add_argument("--relay-dir", metavar="DIR",
                     help="folder through which another process answers the agent's questions")
    run.add_argument("--dry-run", action="store_true",
                     help="print the first request instead of sending it")
    show = parser.add_argument_group("what is shown")
    show.add_argument("--no-activity", action="store_true",
                      help="hide tool lines, retries and the cost of each call")
    show.add_argument("--thinking", action="store_true", help="show the model's thinking")
    show.add_argument("--tool-calls", action="store_true", help="show each tool call as JSON")
    show.add_argument("--debug", action="store_true", help="show every request sent")
    show.add_argument("--save-thinking", action="store_true",
                      help="keep thinking blocks in the saved chat")
    return parser


def _read_text_file(path, what, console):
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        console.warn(f"Could not read the {what} file {path}: {error}")
        return ""


def load_library(datadir, console) -> dict:
    """The instruction library, with Default in it. Empty if it cannot be read."""
    try:
        return instructions.ensure_default(datadir)
    except (StoreUnreadableError, OSError) as error:
        console.warn(f"{error} Running with built-in settings.")
        return {}


def resolve_settings(args, library, console) -> instructions.RunSettings:
    """The settings of this run: a named instruction's, or the Default ones."""
    if args.load:
        if args.load not in library:
            available = ", ".join(sorted(library)) or "(none)"
            raise CannotStart(
                f"No saved instruction named '{args.load}'. Available: {available}")
        name, entry = args.load, library[args.load]
    else:
        name = instructions.DEFAULT_NAME
        entry = library.get(name) or instructions.default_entry()
    try:
        settings, warnings = instructions.settings_from_entry(name, entry)
    except instructions.InstructionError as error:
        raise CannotStart(str(error)) from None
    for warning in warnings:
        console.warn(warning)
    if not args.load:
        # A chat started without a name is not a run of "Default": it borrows
        # that entry's settings, and its task is typed at the prompt.
        settings.name = ""
        settings.text = ""
    return settings


def apply_overrides(settings, args, console):
    """--model and --mode change the run, not anything saved."""
    if args.model:
        settings.model = args.model
    wanted = args.mode or settings.thinking_mode
    settings.thinking_mode = models.coerce_mode(settings.model, wanted)
    if settings.thinking_mode != wanted:
        console.warn(f"{settings.model} has no thinking level '{wanted}'; "
                     f"using '{settings.thinking_mode}'.")


def load_skills(datadir, settings, console) -> SkillStore:
    """The skills, with this run's modes applied."""
    store = SkillStore(datadir.skills_dir)
    try:
        store.load()
    except OSError as error:
        console.warn(f"Could not read the skills in {datadir.skills_dir}: {error}")
    for warning in store.apply_instruction_modes(settings.skill_modes):
        console.warn(warning)
    return store


def offered_tool_names(settings, skills) -> list:
    """The tools this run will offer, in the order the agent declares them."""
    names = list(available_tools()) + ["user_prompt"]
    if skills is not None and skills.on_demand_names():
        names.append("get_skill")
    if settings.meta:
        names += ["manage_instructions", "manage_skills", "run_instruction", "upgrade_model"]
    names.append("web_search")
    blocked = set(settings.blocked_tools or ())
    return [name for name in names if name not in blocked]


def show_banner(console, settings, skills):
    mode = models.mode_label(settings.model, settings.thinking_mode,
                             thinking_budget=settings.thinking_budget)
    kind = "Conversation" if settings.conversational else "Single task"
    title = f"instruction '{settings.name}'" if settings.name else "chat"
    console.note(f"Robot agent: {title}. {kind} on {settings.model} ({mode}).")
    console.note("Tools: " + ", ".join(offered_tool_names(settings, skills)))
    # Skills put text into the system prompt, so always say which are in use.
    if skills is not None and skills.skills:
        enabled = [name for name, entry in skills.skills.items()
                   if entry.get("mode") == "enabled"]
        on_demand = skills.on_demand_names()
        parts = []
        if enabled:
            parts.append("enabled: " + ", ".join(enabled))
        if on_demand:
            parts.append("on demand: " + ", ".join(on_demand))
        if parts:
            console.note("Skills: " + "; ".join(parts))
    if settings.conversational and console.tty:
        console.note("Type quit, stop or exit to end. Ctrl-C stops a reply.")


def first_message(console) -> str:
    """Ask for the task. Empty when the person leaves instead."""
    while True:
        reply = console.ask()
        if reply is INTERRUPTED or reply is None:
            return ""
        if reply == "":
            if console.skips_empty:
                continue
            return ""
        if convo_end_word(reply):
            return ""
        return reply


def fold_in_unfinished_runs(datadir, console):
    """Log the cost of earlier runs that were killed before they could."""
    try:
        logged = costs.progress_fold_in(
            datadir.runs_dir, datadir.costlog_file, is_alive=costs.process_is_robot,
            boot_id=costs.current_boot_id(), my_pid=os.getpid())
    except OSError:
        return
    if logged:
        console.activity(f"Logged the cost of {logged} earlier run(s) that did not finish.")


def list_instructions(console, datadir) -> int:
    library = load_library(datadir, console)
    console.note(f"Saved instructions in {datadir.instructions_file}:")
    for name in sorted(library):
        console.note(instructions.describe(name, library[name]))
    console.note('Run one with: python -m robot.main -l "Name"')
    return EXIT_OK


def list_skills(console, datadir) -> int:
    store = SkillStore(datadir.skills_dir)
    store.load()
    console.note(f"Skills in {datadir.skills_dir}:")
    if not store.skills:
        console.note("(none yet: the agent can create them with its manage_skills tool)")
    for name in sorted(store.skills):
        entry = store.skills[name]
        console.note(f"- {name}  [{entry.get('mode', 'disabled')}]")
        description = " ".join(str(entry.get("description") or "").split())
        if description:
            console.note(f"  {description}")
    return EXIT_OK


def write_failed_result(result_file, name, message):
    """Tell a waiting parent run why this one never started."""
    if not result_file:
        return
    try:
        with open(result_file, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"instruction": name, "status": "error", "error": message,
                       "final_text": ""}, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never die on a character we cannot show
        except (AttributeError, ValueError):
            pass
    load_dotenv(ENV_FILE)

    interrupts = Interrupts()
    interrupts.install()
    console = Console(
        activity=not args.no_activity, show_thinking=args.thinking, tool_calls=args.tool_calls,
        debug=args.debug, headless=args.headless, relay_dir=args.relay_dir,
        interrupts=interrupts)
    datadir = DataDir()
    try:
        datadir.ensure()
    except OSError as error:
        console.error(f"Cannot use the data folder {datadir.root}: {error}")
        return EXIT_CANNOT_START

    if args.list:
        return list_instructions(console, datadir)
    if args.skills:
        return list_skills(console, datadir)

    try:
        settings = resolve_settings(args, load_library(datadir, console), console)
        apply_overrides(settings, args, console)
        if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
            raise CannotStart(f"No ANTHROPIC_API_KEY found. It belongs in {ENV_FILE}.")

        # Start the slow SDK import now; the person reads the banner and types
        # their first message while it loads.
        loader = ClientLoader()
        fold_in_unfinished_runs(datadir, console)
        skills = load_skills(datadir, settings, console)
        show_banner(console, settings, skills)

        if not settings.text.strip():
            # No saved task: the person types it. An unattended run cannot ask.
            unattended = args.headless or args.result_file
            if args.load and unattended:
                raise CannotStart(f"The saved instruction '{args.load}' has no text.")
            settings.text = first_message(console)
            if not settings.text:
                return EXIT_OK
        settings.text = instructions.merge_prepend_text(
            settings.text, _read_text_file(args.prepend_file, "prepend", console))
        settings.text = instructions.merge_extra_text(
            settings.text, _read_text_file(args.extra_file, "extra", console))
    except CannotStart as error:
        console.error(str(error))
        write_failed_result(args.result_file, args.load or "", str(error))
        return EXIT_CANNOT_START

    if not loader.is_ready():
        console.activity("Starting up...")
    from robot.agent import Agent  # waits here if the SDK is still loading

    agent = Agent(
        settings=settings, console=console, datadir=datadir, get_client=loader.get,
        skills=skills, save_thinking=args.save_thinking, result_file=args.result_file,
        dry_run=args.dry_run)
    status = agent.run()
    return EXIT_RUN_ERROR if status == "error" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
