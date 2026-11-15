"""The agent loop: one run from its first message to its end.

A run sends the task as the first user message, then keeps calling the model
and running the tools it asks for until the model is done. In Convo mode the
person is asked for the next message after every reply instead of the run
ending. There is no limit on the number of steps.
"""

import concurrent.futures
import json
import os
import time

from robot import api, chats, costs, history, models, prompts
from robot.console import INTERRUPTED, convo_end_word
from robot.tools import Tool, available_tools

# Typed in answer to a user_prompt question, this word ends the whole run.
EXIT_WORD = "exit"

NUDGE_TEXT = ("[System: You ended your turn without calling user_prompt. "
              "You must call user_prompt now to get the user's next message.]")
NOT_RUN_TEXT = "[Not run: the user pressed STOP]"
BLOCKED_TEXT = ("Tool '{name}' is HARD-BLOCKED for this instruction (blocked_tools). This "
                "action is not permitted under any circumstances - do not attempt it again; "
                "continue the task without it.")
_CHAT_SAVE_SECONDS = 30

USER_PROMPT_TOOL = {
    "name": "user_prompt",
    "description": (
        "Pause and show a message to the person, then wait for their reply. Use this "
        "whenever you need the person to do something (approve something, make a choice, "
        "carry out an action) or need information only they can provide. In a single task "
        "run this is the ONLY way to get an answer: a question written as ordinary text "
        "ends your turn and cannot be replied to. An empty reply means the person wants "
        "the run to stop."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message or question to show the person",
            }
        },
        "required": ["message"],
    },
}


def get_skill_tool(skill_names) -> dict:
    """The get_skill tool, offering exactly the skills that are on demand."""
    return {
        "name": "get_skill",
        "description": ("Retrieve the full content of an on-demand skill by name. Each "
                        "skill's purpose is listed under '## On-Demand Skills' in the "
                        "system prompt."),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to retrieve.",
                    "enum": list(skill_names),
                }
            },
            "required": ["skill_name"],
        },
    }


def _block_field(block, name, default=None):
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


class Agent:
    """One run. Create it, call run(), read status afterwards."""

    def __init__(self, *, settings, console, datadir, get_client, skills=None, learned=None,
                 save_thinking=False, result_file=None, dry_run=False):
        self.settings = settings
        self.console = console
        self.datadir = datadir
        self.get_client = get_client
        self.skills = skills  # a SkillStore with this run's modes applied, or None
        self.learned = learned if learned is not None else api.Learned()
        self.save_thinking = save_thinking
        self.result_file = result_file
        self.dry_run = dry_run

        # The live model settings. An upgrade changes them for the rest of the
        # run; the instruction's own values stay in self.settings.
        self.model = settings.model
        self.thinking_mode = settings.thinking_mode
        self.fast_mode = settings.fast_mode
        self.upgraded_from = None
        self.upgraded_call = None

        self.status = "completed"
        self.error = ""
        self.messages = []
        self.system_prompt = ""
        self.tools = {}
        self.client_tool_defs = []
        self.web_search = True
        self.run_cost = costs.RunCost()
        self.chat_stem = ""
        self._transcript = None
        self._stop_run = False  # set when a reply to user_prompt ends the run
        self._turn_text = ""
        self._truncated_note = ""
        self._drops_noted = None
        self._last_chat_save = 0.0
        self._started = time.monotonic()
        self._client = None

    # -- set-up ------------------------------------------------------------

    def compose_system_prompt(self) -> str:
        """The base prompt, then every enabled skill, then the list of skills
        the model can fetch on demand."""
        base = prompts.base_system_prompt(self.settings.conversational)
        if self.skills is None:
            return base
        return self.skills.compose_system_prompt(base)

    def tool_registry(self) -> dict:
        """Every tool this run could offer, before the blocklist is applied."""
        registry = dict(available_tools())
        registry["user_prompt"] = Tool(
            definition=USER_PROMPT_TOOL, run=self._do_user_prompt, is_available=lambda: True)
        on_demand = self.skills.on_demand_names() if self.skills is not None else []
        if on_demand:
            registry["get_skill"] = Tool(
                definition=get_skill_tool(on_demand), run=self._do_get_skill,
                is_available=lambda: True, parallel_safe=True)
        return registry

    def _do_get_skill(self, tool_input) -> str:
        """The get_skill tool: the full text of an on-demand skill."""
        name = str(tool_input.get("skill_name", ""))
        body = self.skills.get_on_demand(name) if self.skills is not None else None
        if body is None:
            return f"Skill not found or not on-demand: {name}"
        # A skill may come with scripts or reference files. The model can only
        # use them through the shell, so say where they are.
        if self.skills.resources(name):
            body = f"{body.rstrip()}\n\n(This skill's bundled files are in: {self.skills.folder(name)})"
        return body

    def _freeze_run(self):
        """Fix the system prompt and tool list for the whole run.

        Both are part of what the prompt cache and the model's saved reasoning
        are tied to, so neither may change between calls of one run.
        """
        blocked = set(self.settings.blocked_tools or ())
        self.system_prompt = self.compose_system_prompt()
        self.tools = {name: tool for name, tool in self.tool_registry().items()
                      if name not in blocked}
        self.client_tool_defs = [tool.definition for tool in self.tools.values()]
        self.web_search = "web_search" not in blocked

    def _mode_label(self) -> str:
        return models.mode_label(self.model, self.thinking_mode,
                                 thinking_budget=self.settings.thinking_budget)

    def fast_active(self) -> bool:
        return bool(self.fast_mode and models.supports_fast_mode(self.model)
                    and "speed" not in self.learned.unsupported)

    def _request_args(self) -> dict:
        return dict(
            model=self.model, system_prompt=self.system_prompt, messages=self.messages,
            client_tools=self.client_tool_defs, web_search=self.web_search,
            thinking_mode=self.thinking_mode, thinking_budget=self.settings.thinking_budget,
            fast_mode=self.fast_mode, learned=self.learned)

    def describe_request(self) -> str:
        kwargs, betas, _ = api.build_request(**self._request_args())
        return api.describe_request(kwargs, betas)

    def _start_chat_files(self):
        self.datadir.ensure()
        stem = chats.new_chat_name(self.settings.name)
        self.chat_stem = chats.unique_chat_stem(self.datadir.chats_dir, stem, os.getpid())
        self._transcript = chats.Transcript(self.datadir.chats_dir / f"{self.chat_stem}.txt")
        self._transcript.write(
            f"=== {self.chat_stem} | {self.model} | {self._mode_label()} ===\n"
            f"you> {self.settings.text}\n")
        self.console.set_transcript(self._transcript)

    def _startup_warnings(self):
        for warning in (models.generic_pricing_warning(self.model),
                        models.unpriced_model_warning(self.model, fast=self.fast_active())):
            if warning:
                self.console.warn(warning)

    # -- the run -----------------------------------------------------------

    def run(self) -> str:
        """Run to the end. Returns "completed", "stopped" or "error"."""
        console = self.console
        console.input_wait_secs = 0.0
        self._started = time.monotonic()
        self.messages = [{"role": "user", "content": self.settings.text}]
        try:
            self._freeze_run()
            if self.dry_run:
                console.note(self.describe_request())
                return self.status
            self._start_chat_files()
            self._startup_warnings()
            self._client = self.get_client()
            self._loop()
        except KeyboardInterrupt:
            self.status = "stopped"
        except Exception as error:
            self.status = "error"
            self.error = str(error) or type(error).__name__
            console.error(self.error)
        finally:
            if not self.dry_run:
                self._end_run()
        return self.status

    def _interactive_convo(self) -> bool:
        """A conversation with a person at the keyboard.

        There the chat forgives: Ctrl-C and API errors return to the prompt
        instead of ending the run, and an empty line is ignored.
        """
        return self.settings.conversational and self.console.tty

    def _loop(self):
        console = self.console
        interrupts = console.interrupts
        messages = self.messages
        user_prompt_count = 0
        nudges = 0

        while True:
            if interrupts.stop.is_set() or self._stop_run:
                console.activity("Agent stopped.")
                self.status = "stopped"
                break

            # Never send a tool call without its result.
            history.repair_tool_pairs(messages)
            self.run_cost.calls += 1
            call_num = self.run_cost.calls
            console.call_header(call_num)
            if console.debug_on:
                console.debug_payload(self.describe_request())

            try:
                result = api.call_model(self._client, console, interrupts, **self._request_args())
            except Exception as error:
                if not self._interactive_convo():
                    raise
                console.error(str(error) or type(error).__name__)
                if not self._next_convo_message():
                    break
                continue

            self._account(result, call_num)
            self._note_dropped_thinking(result.dropped_thinking)

            if result.interrupted:
                console.end_line()
                if result.text:
                    messages.append({"role": "assistant", "content": result.text})
                if not self._after_interrupt():
                    break
                continue

            if result.stop_reason == "pause_turn":
                # A long server-side tool turn was paused: send it back as it
                # is and the API carries on from there.
                messages.append({"role": "assistant", "content": result.content})
                console.activity("Server-side tools paused the turn - resuming...")
                continue

            self._truncated_note = ""
            if result.stop_reason in ("max_tokens", "model_context_window_exceeded"):
                self._warn_truncated(result)

            tool_blocks = [block for block in result.content
                           if _block_field(block, "type") == "tool_use"]
            if result.stop_reason == "tool_use" and tool_blocks:
                messages.append({"role": "assistant", "content": result.content})
                results, asked_user, interrupted = self._run_tools(tool_blocks, result.text)
                messages.append({"role": "user", "content": results})
                if asked_user:
                    user_prompt_count += 1
                    nudges = 0
                if interrupted and not self._after_interrupt():
                    break
                continue

            # The model ended its turn.
            console.end_line()
            clean_end = result.stop_reason == "end_turn"
            if self.settings.conversational and (result.text or console.tty):
                self._append_reply(result, clean_end)
                if not result.text:
                    console.note("(the reply had no text)")
                if not self._next_convo_message():
                    break
                continue

            # A model that has been asking through user_prompt and then just
            # stops has most likely forgotten to ask again: remind it.
            if user_prompt_count >= 2 and result.text and nudges < 3:
                nudges += 1
                messages.append({"role": "assistant", "content": result.text})
                messages.append({"role": "user", "content": NUDGE_TEXT})
                console.activity("Model forgot user_prompt - nudging...")
                continue

            self._append_reply(result, clean_end)
            break

    def _append_reply(self, result, clean_end):
        """Add the finished reply to the history.

        A reply that ended normally is kept whole, with its reasoning and any
        search results, so follow-up questions can use them. A reply that was
        cut off or refused is kept as text only.
        """
        if clean_end and result.content:
            self.messages.append({"role": "assistant", "content": result.content})
        elif result.text:
            self.messages.append({"role": "assistant", "content": result.text})

    def _after_interrupt(self) -> bool:
        """After Ctrl-C. True to carry on (with the person's next message)."""
        console = self.console
        if self._interactive_convo() and not console.interrupts.stop.is_set():
            console.interrupts.clear()
            console.note("(stopped)")
            return self._next_convo_message()
        console.activity("Agent stopped by user.")
        self.status = "stopped"
        return False

    def _next_convo_message(self) -> bool:
        """Ask the person for the next message. False when the conversation ends."""
        console = self.console
        self._save_chat()
        pressed_ctrl_c = False
        while True:
            reply = console.ask()
            if reply is INTERRUPTED:
                if pressed_ctrl_c:
                    break
                pressed_ctrl_c = True
                console.note("(press Ctrl-C again, or type exit, to end the conversation)")
                continue
            pressed_ctrl_c = False
            if reply is None:
                break  # nobody is there to answer
            if reply == "":
                if console.tty:
                    continue  # a stray Enter at a terminal is not an answer
                break
            if convo_end_word(reply):
                break
            self.messages.append({"role": "user", "content": reply})
            return True
        console.activity("Conversation ended.")
        return False

    # -- tools -------------------------------------------------------------

    def _result(self, block, content, is_error=False) -> dict:
        result = {"type": "tool_result", "tool_use_id": _block_field(block, "id"),
                  "content": content}
        if is_error:
            result["is_error"] = True
        return result

    def _run_tool(self, block) -> dict:
        """Run one tool call and build the result that goes back to the model."""
        name = _block_field(block, "name", "")
        tool_input = _block_field(block, "input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        if name in (self.settings.blocked_tools or ()):
            return self._result(block, BLOCKED_TEXT.format(name=name))
        tool = self.tools.get(name)
        if tool is None:
            return self._result(block, f"Unknown tool: {name}", is_error=True)
        if name != "user_prompt":
            self.console.tool_line(
                name, json.dumps(tool_input, ensure_ascii=False) if tool_input else "")
        try:
            output = tool.run(tool_input)
        except Exception as error:
            # Tell the model what went wrong instead of ending the run.
            return self._result(
                block, f"Error executing {name}: {type(error).__name__}: {error}", is_error=True)
        if not isinstance(output, (str, list)):
            output = str(output)
        return self._result(block, output)

    def _run_tools(self, tool_blocks, turn_text):
        """Run a turn's tool calls. Returns (results, asked_user, interrupted).

        Tools marked parallel_safe run together first; the rest run one at a
        time in the order the model gave. Every call gets a result, run or not.
        """
        console = self.console
        interrupts = console.interrupts
        self._turn_text = turn_text or ""
        for block in tool_blocks:
            console.tool_call_json(json.dumps(
                {"tool": _block_field(block, "name"), "id": _block_field(block, "id"),
                 "input": _block_field(block, "input")}, indent=2, ensure_ascii=False,
                default=str))

        results = [None] * len(tool_blocks)
        parallel, sequential = [], []
        for index, block in enumerate(tool_blocks):
            tool = self.tools.get(_block_field(block, "name", ""))
            (parallel if tool is not None and tool.parallel_safe else sequential).append(
                (index, block))

        interrupted = False
        if parallel:
            if len(parallel) > 1:
                console.activity(f"Running {len(parallel)} tools in parallel...")
            interrupted = self._run_parallel(parallel, results)

        asked_user = False
        for index, block in sequential:
            if interrupted or interrupts.pending() or self._stop_run:
                interrupted = interrupted or interrupts.pending()
                results[index] = self._result(block, NOT_RUN_TEXT)
                continue
            try:
                with interrupts.raisable():
                    results[index] = self._run_tool(block)
            except KeyboardInterrupt:
                interrupted = True
                results[index] = self._result(block, "[Interrupted by the user]", is_error=True)
            if _block_field(block, "name") == "user_prompt":
                asked_user = True
        return results, asked_user, interrupted

    def _run_parallel(self, items, results) -> bool:
        """Run parallel-safe tools on a thread pool. True if interrupted."""
        interrupts = self.console.interrupts
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(items))
        futures = {executor.submit(self._run_tool, block): (index, block)
                   for index, block in items}
        pending = set(futures)
        interrupted = False
        try:
            # A timed wait, so Ctrl-C is noticed while tools are still running.
            while pending:
                done, pending = concurrent.futures.wait(pending, timeout=0.2)
                for future in done:
                    index, block = futures[future]
                    try:
                        results[index] = future.result()
                    except BaseException as error:  # never lose a result slot
                        results[index] = self._result(
                            block, f"Error: {type(error).__name__}: {error}", is_error=True)
                if interrupts.pending():
                    interrupted = True
                self._serve_pool_requests()
        finally:
            executor.shutdown(wait=False)
        return interrupted

    def _serve_pool_requests(self):
        """Hook for tools on pool threads that need the person (child runs)."""

    def _do_user_prompt(self, tool_input) -> str:
        """The user_prompt tool: ask the person and return their reply."""
        console = self.console
        message = str(tool_input.get("message", ""))
        while True:
            reply = console.ask(question=message, preface=self._turn_text)
            if reply is INTERRUPTED:
                reply = None
            if reply == "" and console.tty:
                continue  # a stray Enter at a terminal is not an answer
            break
        if not reply:
            self._stop_run = True
            return "[User submitted empty response - stopping agent]"
        if convo_end_word(reply) == EXIT_WORD:
            self._stop_run = True
            return "[User typed 'exit' - stopping the agent]"
        return reply

    # -- accounting and wind-down -------------------------------------------

    def _params(self) -> str:
        return ", ".join(models.param_summary(
            self.model, self.thinking_mode, fast_active=self.fast_active(),
            upgraded_from=self.upgraded_from, upgraded_call=self.upgraded_call,
            thinking_budget=self.settings.thinking_budget))

    def _working_seconds(self) -> float:
        """Run time, not counting time spent waiting on the person."""
        return max(0.0, time.monotonic() - self._started - self.console.input_wait_secs)

    def _account(self, result, call_num):
        if result.usage:
            update, long_context_warning = self.run_cost.add_call(result.usage, self.model)
            self.console.cost(call_num, costs.cost_line(update))
            if long_context_warning:
                self.console.warn(long_context_warning)
            # Rewritten after every call, so a run that is killed still gets
            # its cost-log line at the next start.
            warning = costs.progress_write(
                self.datadir.runs_dir, os.getpid(), self.run_cost, model=self.model,
                params=self._params(), seconds=self._working_seconds(),
                instruction=self.settings.name, chat=self.chat_stem,
                boot_id=costs.current_boot_id())
            if warning:
                self.console.warn(warning)
        if time.monotonic() - self._last_chat_save >= _CHAT_SAVE_SECONDS:
            self._save_chat()

    def _note_dropped_thinking(self, dropped):
        # Said once per run for each distinct shape, not on every call.
        if dropped and dropped != self._drops_noted:
            self._drops_noted = dropped
            count, reasons = dropped
            self.console.activity(
                f"API dropped {count} replayed thinking block(s): "
                f"{api.thinking_drop_reason(reasons)}. The model continues without that "
                "reasoning (not billed; the text and tool history is intact).")

    def _warn_truncated(self, result):
        unfinished_tool = any(_block_field(block, "type") == "tool_use"
                              for block in result.content or ())
        self._truncated_note = (
            f"the model's reply was cut off (stop_reason={result.stop_reason})"
            + ("; its unfinished tool call was not run" if unfinished_tool else ""))
        if result.stop_reason == "max_tokens":
            cap = self.learned.output_caps.get(self.model) or models.output_cap_for(self.model)
            why = (f"it filled the whole {cap:,}-token output window {self.model} allows "
                   "per call (thinking included)")
        else:
            why = "it filled the whole output window the call allows"
        note = self._truncated_note
        self.console.warn(f"{note[0].upper()}{note[1:]}: {why}. The turn ends here - "
                          "ask for smaller steps.")

    def _save_chat(self):
        if not self.chat_stem:
            return
        self._last_chat_save = time.monotonic()
        try:
            tools = list(self.client_tool_defs)
            if self.web_search:
                tools.append(models.web_search_tool(self.model, self.learned.unsupported)[0])
            payload = chats.chat_payload(
                name=self.chat_stem, messages=self.messages, tools=tools,
                system_prompt=self.system_prompt, instruction=self.settings.name,
                model=self.model, thinking_mode=self.thinking_mode,
                save_thinking=self.save_thinking)
            chats.save_chat_json(self.datadir.chats_dir / f"{self.chat_stem}.json", payload)
        except Exception as error:
            self.console.activity(f"Could not save the chat: {error}")

    def _write_result_file(self):
        """The run's outcome, for a parent run that is waiting on this one."""
        if not self.result_file:
            return
        try:
            with open(self.result_file, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({
                    "instruction": self.settings.name,
                    "status": self.status,
                    "error": self.error,
                    "final_text": history.final_assistant_text(self.messages),
                }, handle, ensure_ascii=False, indent=1)
        except OSError as error:
            self.console.warn(f"Could not write result file: {error}")

    def _restore_upgrade(self):
        """Hook: an upgraded run goes back to the instruction's own model."""

    def _end_run(self):
        """Wind the run down. Every step is best-effort: none may stop the rest."""
        console = self.console
        console.end_line()
        if self.status == "completed" and self._truncated_note:
            self.status = "error"
            self.error = self._truncated_note
        steps = (self._log_cost, self._clear_progress, self._restore_upgrade,
                 self._write_result_file, self._save_chat)
        for step in steps:
            try:
                step()
            except Exception as error:
                try:
                    console.activity(f"{step.__name__} failed: {error}")
                except Exception:
                    pass
        if self._transcript is not None:
            console.set_transcript(None)
            self._transcript.close()

    def _log_cost(self):
        written, note = costs.log_run(
            self.datadir.costlog_file, self.run_cost, model=self.model, params=self._params(),
            seconds=self._working_seconds(), instruction=self.settings.name,
            chat=self.chat_stem)
        if note:
            # A run that spent money but could not be logged must not be hidden
            # by --no-activity.
            (self.console.activity if written else self.console.warn)(note)

    def _clear_progress(self):
        warning = costs.progress_clear(self.datadir.runs_dir, os.getpid())
        if warning:
            self.console.warn(warning)
