"""Robot brain entry point: run the agent from the command line.

    python -m robot.main              chat: type the task at you>, then converse
    python -m robot.main --help       every option

Nothing here imports the Anthropic SDK directly. It takes many seconds to load
on the Pi, so it is loaded in the background while the person types.
"""

import argparse
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

from robot import costs, instructions, models
from robot.console import INTERRUPTED, Console, Interrupts, convo_end_word
from robot.datastore import DataDir
from robot.tools import available_tools

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

EXIT_OK = 0
EXIT_RUN_ERROR = 1
EXIT_CANNOT_START = 2


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


def default_settings() -> instructions.RunSettings:
    """What a chat started without a saved instruction runs with."""
    return instructions.RunSettings(
        model=models.DEFAULT_MODEL, thinking_mode="low", conversational=True)


def apply_overrides(settings, args, console):
    """--model and --mode change the run, not anything saved."""
    if args.model:
        settings.model = args.model
    wanted = args.mode or settings.thinking_mode
    settings.thinking_mode = models.coerce_mode(settings.model, wanted)
    if settings.thinking_mode != wanted:
        console.warn(f"{settings.model} has no thinking level '{wanted}'; "
                     f"using '{settings.thinking_mode}'.")


def offered_tool_names(settings) -> list:
    blocked = set(settings.blocked_tools or ())
    names = list(available_tools()) + ["user_prompt", "web_search"]
    return [name for name in names if name not in blocked]


def show_banner(console, settings):
    mode = models.mode_label(settings.model, settings.thinking_mode,
                             thinking_budget=settings.thinking_budget)
    kind = "Conversation" if settings.conversational else "Single task"
    title = f"instruction '{settings.name}'" if settings.name else "chat"
    console.note(f"Robot agent: {title}. {kind} on {settings.model} ({mode}).")
    console.note("Tools: " + ", ".join(offered_tool_names(settings)))
    if settings.conversational and console.tty:
        console.note("Type quit, stop or exit to end. Ctrl-C stops a reply.")


def first_message(console) -> str:
    """Ask for the task of an ad-hoc chat. Empty when the person leaves instead."""
    while True:
        reply = console.ask()
        if reply is INTERRUPTED or reply is None:
            return ""
        if reply == "":
            if console.tty:
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

    settings = default_settings()
    apply_overrides(settings, args, console)

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        console.error(f"No ANTHROPIC_API_KEY found. It belongs in {ENV_FILE}.")
        return EXIT_CANNOT_START

    # Start the slow SDK import now; the person reads the banner and types
    # their first message while it loads.
    loader = ClientLoader()

    try:
        datadir.ensure()
    except OSError as error:
        console.error(f"Cannot use the data folder {datadir.root}: {error}")
        return EXIT_CANNOT_START
    fold_in_unfinished_runs(datadir, console)

    show_banner(console, settings)
    if not settings.text:
        settings.text = first_message(console)
        if not settings.text:
            return EXIT_OK
    settings.text = instructions.merge_prepend_text(
        settings.text, _read_text_file(args.prepend_file, "prepend", console))
    settings.text = instructions.merge_extra_text(
        settings.text, _read_text_file(args.extra_file, "extra", console))

    if not loader.is_ready():
        console.activity("Starting up...")
    from robot.agent import Agent  # waits here if the SDK is still loading

    agent = Agent(
        settings=settings, console=console, datadir=datadir, get_client=loader.get,
        save_thinking=args.save_thinking, result_file=args.result_file, dry_run=args.dry_run)
    status = agent.run()
    return EXIT_RUN_ERROR if status == "error" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
