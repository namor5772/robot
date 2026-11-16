"""The agent loop, driven by a scripted fake client. No network, no API key."""

import json
import tempfile
import unittest
from pathlib import Path

from robot import agent as agent_module
from robot.agent import NOT_RUN_TEXT, NUDGE_TEXT, Agent
from robot.datastore import DataDir
from robot.instructions import RunSettings
from robot.skills import SkillStore, manage_skills
from robot.tools import Tool, available_tools
from tests.fakes import (INTERRUPTED, FakeClient, InterruptDuring, NoWaitInterrupts, Obj,
                         TerminalConsole, bad_request, piped_console, reply, server_search,
                         text_block, thinking_block, tool_use)


def _tool(name, run, parallel_safe=False):
    definition = {"name": name, "description": name,
                  "input_schema": {"type": "object", "properties": {}}}
    return Tool(definition=definition, run=run, is_available=lambda: True,
                parallel_safe=parallel_safe)


class ScriptedAgent(Agent):
    """An Agent whose machine tools are replaced by the test's own."""

    test_tools = {}

    def tool_registry(self):
        machine = set(available_tools())  # differ between the laptop and the Pi
        registry = {name: tool for name, tool in super().tool_registry().items()
                    if name not in machine}
        registry.update(self.test_tools)
        return registry


class LoopCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.datadir = DataDir(self._tmp.name)
        self.calls = []

    def make(self, script, *, console=None, lines="", tools=None, result_file=None,
             **settings):
        if console is None:
            console, self.out = piped_console(lines)
        elif hasattr(console, "out"):
            self.out = console.out
        self.console = console
        self.client = FakeClient(script)
        settings.setdefault("text", "do the task")
        made = ScriptedAgent(
            settings=RunSettings(**settings), console=console, datadir=self.datadir,
            get_client=lambda: self.client, result_file=result_file)
        made.test_tools = tools or {}
        return made

    def recorder(self, name, value="ok", parallel_safe=False):
        def run(tool_input):
            self.calls.append((name, tool_input))
            return value
        return _tool(name, run, parallel_safe)

    def roles(self, made):
        return [message["role"] for message in made.messages]

    def shown(self):
        return self.out.getvalue()


class SingleTaskRuns(LoopCase):
    def test_a_plain_reply_completes_the_run(self):
        made = self.make([reply(thinking_block(), text_block("All done."))])
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.roles(made), ["user", "assistant"])
        # A reply that ended normally is kept whole, thinking included.
        self.assertEqual(len(made.messages[1]["content"]), 2)
        self.assertEqual(len(self.client.requests), 1)
        self.assertIn("robot> All done.", self.shown())

    def test_the_first_request_has_the_expected_shape(self):
        made = self.make([reply(text_block("ok"))])
        made.run()
        request = self.client.requests[0]
        self.assertEqual(request["model"], "claude-opus-5-5")
        self.assertNotIn("temperature", request)
        self.assertEqual(request["thinking"]["type"], "adaptive")
        self.assertEqual(request["thinking"]["display"], "summarized")
        self.assertEqual(request["thinking"]["block_binding"],
                         {"prefix_mismatch_behavior": "drop_block"})
        self.assertEqual(request["output_config"], {"effort": "low"})
        self.assertEqual(request["fallbacks"], "default")
        self.assertIn("thinking-binding-controls-2026-08-01", request["betas"])
        self.assertIn("server-side-fallback-2026-07-01", request["betas"])
        self.assertEqual(request["system"][0]["cache_control"], {"type": "ephemeral"})
        names = [tool["name"] for tool in request["tools"]]
        self.assertEqual(names, ["user_prompt", "web_search"])
        # The task is the first user message, carrying the newest cache marker.
        first = request["messages"][0]
        self.assertEqual(first["role"], "user")
        self.assertEqual(first["content"][0]["text"], "do the task")
        self.assertIn("cache_control", first["content"][0])

    def test_a_single_task_prompt_tells_the_model_to_ask_through_user_prompt(self):
        made = self.make([reply(text_block("ok"))])
        made.run()
        system = self.client.requests[0]["system"][0]["text"]
        self.assertIn("single task run", system)
        self.assertNotIn("This is a conversation", system)

    def test_a_tool_round_feeds_the_result_back(self):
        script = [reply(text_block("Checking."), tool_use("echo", {"x": 1}, "t1")),
                  reply(text_block("It said ok."))]
        made = self.make(script, tools={"echo": self.recorder("echo")})
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.calls, [("echo", {"x": 1})])
        self.assertEqual(self.roles(made), ["user", "assistant", "user", "assistant"])
        self.assertEqual(made.messages[2]["content"],
                         [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}])
        self.assertIn('[tool: echo: {"x": 1}]', self.shown())

    def test_parallel_safe_tools_run_before_the_rest_and_results_keep_their_order(self):
        script = [reply(tool_use("slow_a", {}, "a"), tool_use("fast_b", {}, "b"),
                        tool_use("slow_c", {}, "c")),
                  reply(text_block("done"))]
        tools = {"slow_a": self.recorder("slow_a", "A"),
                 "fast_b": self.recorder("fast_b", "B", parallel_safe=True),
                 "slow_c": self.recorder("slow_c", "C")}
        made = self.make(script, tools=tools)
        made.run()
        self.assertEqual([name for name, _ in self.calls], ["fast_b", "slow_a", "slow_c"])
        results = made.messages[2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b", "c"])
        self.assertEqual([r["content"] for r in results], ["A", "B", "C"])

    def test_a_failing_tool_is_reported_to_the_model_as_an_error(self):
        def explode(_input):
            raise ValueError("no such motor")
        script = [reply(tool_use("move", {}, "m")), reply(text_block("I could not."))]
        made = self.make(script, tools={"move": _tool("move", explode)})
        self.assertEqual(made.run(), "completed")
        result = made.messages[2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("Error executing move: ValueError: no such motor", result["content"])

    def test_an_unknown_tool_gets_an_error_result(self):
        script = [reply(tool_use("teleport", {}, "x")), reply(text_block("ok"))]
        made = self.make(script)
        made.run()
        result = made.messages[2]["content"][0]
        self.assertEqual(result["content"], "Unknown tool: teleport")
        self.assertTrue(result["is_error"])

    def test_blocked_tools_are_not_offered_and_are_refused_if_called(self):
        script = [reply(tool_use("echo", {}, "e")), reply(text_block("ok"))]
        made = self.make(script, tools={"echo": self.recorder("echo")},
                         blocked_tools=["echo", "web_search"])
        made.run()
        names = [tool["name"] for tool in self.client.requests[0]["tools"]]
        self.assertEqual(names, ["user_prompt"])
        self.assertEqual(self.calls, [])
        self.assertIn("HARD-BLOCKED", made.messages[2]["content"][0]["content"])

    def test_the_tool_list_and_system_prompt_do_not_change_during_a_run(self):
        made = None

        def add_a_tool(_input):
            made.test_tools["late"] = self.recorder("late")
            return "added"
        script = [reply(tool_use("grow", {}, "g")), reply(text_block("ok"))]
        made = self.make(script, tools={"grow": _tool("grow", add_a_tool)})
        made.run()
        first, second = self.client.requests
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(first["system"], second["system"])

    def test_a_paused_turn_is_sent_back_and_resumed(self):
        script = [reply(server_search("pi os"), stop_reason="pause_turn"),
                  reply(text_block("Found it."))]
        made = self.make(script)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.roles(made), ["user", "assistant", "assistant"])
        self.assertIn("paused the turn", self.shown())

    def test_a_reply_cut_off_at_the_output_limit_ends_the_run_as_an_error(self):
        made = self.make([reply(text_block("and so"), stop_reason="max_tokens")])
        self.assertEqual(made.run(), "error")
        self.assertIn("cut off (stop_reason=max_tokens)", made.error)
        self.assertIn("warning: The model's reply was cut off", self.shown())
        # A reply that did not end normally is kept as text only.
        self.assertEqual(made.messages[1]["content"], "and so")

    def test_a_refusal_ends_the_run_with_a_warning(self):
        declined = reply(stop_reason="refusal",
                         stop_details=Obj(category="cyber", explanation="not allowed",
                                          recommended_model=None))
        made = self.make([declined])
        self.assertEqual(made.run(), "completed")
        self.assertIn("declined this request (stop_reason=refusal, category=cyber)",
                      self.shown())
        self.assertEqual(self.roles(made), ["user"])

    def test_an_api_error_ends_a_single_task_run(self):
        made = self.make([bad_request("something else is wrong")])
        self.assertEqual(made.run(), "error")
        self.assertIn("something else is wrong", made.error)
        self.assertIn("error: ", self.shown())

    def test_tool_use_stop_without_tool_blocks_does_not_send_an_empty_result(self):
        made = self.make([reply(text_block("odd"), stop_reason="tool_use")])
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.roles(made), ["user", "assistant"])


class UserPromptTool(LoopCase):
    def test_the_reply_goes_back_to_the_model(self):
        script = [reply(text_block("One thing."), tool_use("user_prompt", {"message": "Which?"})),
                  reply(text_block("Blue it is."))]
        made = self.make(script, lines="blue\n")
        self.assertEqual(made.run(), "completed")
        self.assertEqual(made.messages[2]["content"][0]["content"], "blue")
        self.assertIn("robot asks> Which?", self.shown())
        self.assertIn("you> blue", self.shown())

    def test_no_reply_stops_the_run_and_later_tools_are_not_run(self):
        script = [reply(tool_use("user_prompt", {"message": "Sure?"}, "q"),
                        tool_use("echo", {}, "e"))]
        made = self.make(script, lines="", tools={"echo": self.recorder("echo")})
        self.assertEqual(made.run(), "stopped")
        results = made.messages[2]["content"]
        self.assertIn("stopping agent", results[0]["content"])
        self.assertEqual(results[1]["content"], NOT_RUN_TEXT)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.client.requests), 1)

    def test_exit_stops_the_run_but_quit_is_an_ordinary_reply(self):
        made = self.make([reply(tool_use("user_prompt", {"message": "Go on?"}))], lines="Exit!\n")
        self.assertEqual(made.run(), "stopped")

        script = [reply(tool_use("user_prompt", {"message": "Go on?"})),
                  reply(text_block("Stopping then."))]
        made = self.make(script, lines="quit\n")
        self.assertEqual(made.run(), "completed")
        self.assertEqual(made.messages[2]["content"][0]["content"], "quit")

    def test_at_a_terminal_a_stray_enter_is_not_an_answer(self):
        console = TerminalConsole(["", "red"])
        script = [reply(tool_use("user_prompt", {"message": "Colour?"})),
                  reply(text_block("Red."))]
        made = self.make(script, console=console)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(made.messages[2]["content"][0]["content"], "red")

    def test_the_preface_is_what_the_model_said_before_asking(self):
        console = TerminalConsole(["yes"])
        seen = {}
        original = console.ask

        def ask(*, question="", preface="", prompt="you> "):
            seen["preface"] = preface
            return original(question=question, preface=preface, prompt=prompt)
        console.ask = ask
        script = [reply(text_block("I found two files."),
                        tool_use("user_prompt", {"message": "Delete both?"})),
                  reply(text_block("Deleted."))]
        self.make(script, console=console).run()
        self.assertEqual(seen["preface"], "I found two files.")

    def test_a_model_that_stops_asking_is_nudged_up_to_three_times(self):
        ask = lambda text: reply(tool_use("user_prompt", {"message": text}))  # noqa: E731
        script = [ask("first?"), ask("second?"), reply(text_block("forgot")),
                  reply(text_block("forgot again")), reply(text_block("and again")),
                  reply(text_block("the end"))]
        made = self.make(script, lines="a\nb\n")
        self.assertEqual(made.run(), "completed")
        nudges = [m for m in made.messages if m.get("content") == NUDGE_TEXT]
        self.assertEqual(len(nudges), 3)
        self.assertEqual(self.client.remaining, 0)

    def test_one_question_does_not_set_up_a_nudge(self):
        script = [reply(tool_use("user_prompt", {"message": "only one"})),
                  reply(text_block("done"))]
        made = self.make(script, lines="fine\n")
        made.run()
        self.assertFalse([m for m in made.messages if m.get("content") == NUDGE_TEXT])


class Conversations(LoopCase):
    def test_the_harness_asks_for_the_next_message_after_each_reply(self):
        script = [reply(text_block("Hello.")), reply(text_block("Forty-two."))]
        made = self.make(script, lines="what number?\nquit\n", conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.roles(made), ["user", "assistant", "user", "assistant"])
        self.assertEqual(made.messages[2]["content"], "what number?")
        self.assertIn("This is a conversation", self.client.requests[0]["system"][0]["text"])
        self.assertIn("Conversation ended.", self.shown())

    def test_end_words_ignore_case_and_punctuation(self):
        for word in ("quit", "Stop.", "EXIT!", "bye"):
            made = self.make([reply(text_block("Hi."))], lines=word + "\n", conversational=True)
            self.assertEqual(made.run(), "completed", word)
            self.assertEqual(len(self.client.requests), 1, word)

    def test_a_sentence_starting_with_an_end_word_is_an_ordinary_reply(self):
        script = [reply(text_block("Hi.")), reply(text_block("Stopped it."))]
        made = self.make(script, lines="stop the motor\n", conversational=True)
        made.run()
        self.assertEqual(made.messages[2]["content"], "stop the motor")

    def test_piped_input_ends_on_an_empty_line_or_end_of_input(self):
        made = self.make([reply(text_block("Hi."))], lines="\nmore\n", conversational=True)
        made.run()
        self.assertEqual(len(self.client.requests), 1)
        made = self.make([reply(text_block("Hi."))], lines="", conversational=True)
        self.assertEqual(made.run(), "completed")

    def test_at_a_terminal_an_empty_line_is_ignored(self):
        console = TerminalConsole(["", "", "again", None])
        script = [reply(text_block("Hi.")), reply(text_block("Hi again."))]
        made = self.make(script, console=console, conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(made.messages[2]["content"], "again")

    def test_at_a_terminal_a_reply_with_no_text_still_prompts(self):
        console = TerminalConsole(["are you there?", None])
        script = [reply(), reply(text_block("Yes."))]
        made = self.make(script, console=console, conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(len(self.client.requests), 2)
        self.assertIn("(the reply had no text)", self.shown())

    def test_without_a_terminal_a_reply_with_no_text_ends_the_run(self):
        made = self.make([reply()], lines="more\n", conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(len(self.client.requests), 1)

    def test_at_a_terminal_an_api_error_returns_to_the_prompt(self):
        console = TerminalConsole(["try again", None])
        script = [bad_request("something else is wrong"), reply(text_block("Better."))]
        made = self.make(script, console=console, conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertIn("error: something else is wrong", self.shown())
        # The history is intact: the task, then the follow-up, then the reply.
        self.assertEqual(self.roles(made), ["user", "user", "assistant"])

    def test_ctrl_c_twice_at_the_prompt_ends_the_conversation(self):
        console = TerminalConsole([INTERRUPTED, INTERRUPTED])
        made = self.make([reply(text_block("Hi."))], console=console, conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertIn("Ctrl-C again", self.shown())

    def test_ctrl_c_once_at_the_prompt_only_warns(self):
        console = TerminalConsole([INTERRUPTED, "still here", None])
        script = [reply(text_block("Hi.")), reply(text_block("Good."))]
        made = self.make(script, console=console, conversational=True)
        made.run()
        self.assertEqual(made.messages[2]["content"], "still here")


class Interruptions(LoopCase):
    def test_at_a_terminal_ctrl_c_mid_reply_returns_to_the_prompt(self):
        interrupts = NoWaitInterrupts()
        console = TerminalConsole(["carry on", None], interrupts=interrupts)
        script = [InterruptDuring(reply(text_block("The answer is")), interrupts),
                  reply(text_block("forty-two."))]
        made = self.make(script, console=console, conversational=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(self.roles(made), ["user", "assistant", "user", "assistant"])
        self.assertEqual(made.messages[1]["content"], "The answer is")
        self.assertIn("(stopped)", self.shown())
        self.assertFalse(interrupts.interrupt.is_set())

    def test_in_a_single_task_run_ctrl_c_stops_the_run(self):
        interrupts = NoWaitInterrupts()
        console, self.out = piped_console("", interrupts=interrupts)
        made = self.make([InterruptDuring(reply(text_block("Working")), interrupts)],
                         console=console)
        self.assertEqual(made.run(), "stopped")
        self.assertEqual(made.messages[1]["content"], "Working")

    def test_ctrl_c_during_a_tool_leaves_every_call_with_a_result(self):
        interrupts = NoWaitInterrupts()
        console = TerminalConsole(["what happened?", None], interrupts=interrupts)

        def hang(_input):
            interrupts.interrupt.set()
            raise KeyboardInterrupt
        script = [reply(tool_use("hang", {}, "h"), tool_use("echo", {}, "e")),
                  reply(text_block("You stopped me."))]
        tools = {"hang": _tool("hang", hang), "echo": self.recorder("echo")}
        made = self.make(script, console=console, tools=tools, conversational=True)
        self.assertEqual(made.run(), "completed")
        results = made.messages[2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["h", "e"])
        self.assertIn("Interrupted", results[0]["content"])
        self.assertEqual(results[1]["content"], NOT_RUN_TEXT)
        self.assertEqual(self.calls, [])
        # Tool results, then the person's next message: two user turns in a row.
        self.assertEqual(self.roles(made), ["user", "assistant", "user", "user", "assistant"])

    def test_a_stop_request_ends_even_an_interactive_conversation(self):
        interrupts = NoWaitInterrupts()
        console = TerminalConsole(["more"], interrupts=interrupts)

        def shutdown(_input):
            interrupts.stop.set()
            interrupts.interrupt.set()
            return "ok"
        script = [reply(tool_use("shutdown", {}, "s"))]
        made = self.make(script, console=console, tools={"shutdown": _tool("shutdown", shutdown)},
                         conversational=True)
        self.assertEqual(made.run(), "stopped")
        self.assertEqual(len(self.client.requests), 1)


class RunRecords(LoopCase):
    def test_the_run_leaves_a_cost_line_a_chat_and_no_progress_record(self):
        made = self.make([reply(text_block("Done."))], name="Morning check")
        made.run()
        log = self.datadir.costlog_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(log), 1)
        fields = log[0].split(";")
        self.assertEqual(fields[1], "Anthropic")
        self.assertEqual(fields[2], "claude-opus-5-5")
        self.assertEqual(fields[4], "mode=Low")
        self.assertEqual(fields[6], "Morning check")
        self.assertEqual(fields[7], "1")
        self.assertEqual(list(self.datadir.runs_dir.glob("*.json")), [])
        self.assertTrue(made.chat_stem.startswith("Morning check_"))
        saved = json.loads((self.datadir.chats_dir / f"{made.chat_stem}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(len(saved["messages"]), 2)
        transcript = (self.datadir.chats_dir / f"{made.chat_stem}.txt").read_text(encoding="utf-8")
        self.assertIn("you> do the task", transcript)
        self.assertIn("robot> Done.", transcript)

    def test_each_call_prints_its_cost_with_activity_on(self):
        made = self.make([reply(tool_use("echo", {}, "e")), reply(text_block("ok"))],
                         tools={"echo": self.recorder("echo")})
        made.run()
        self.assertIn("  call 1: ", self.shown())
        self.assertIn("  call 2: ", self.shown())

    def test_activity_off_hides_tool_and_cost_lines(self):
        console, self.out = piped_console("", activity=False)
        made = self.make([reply(tool_use("echo", {}, "e")), reply(text_block("ok"))],
                         console=console, tools={"echo": self.recorder("echo")})
        made.run()
        self.assertNotIn("[tool:", self.shown())
        self.assertNotIn("call 1:", self.shown())
        self.assertIn("robot> ok", self.shown())

    def test_the_result_file_reports_status_and_final_text(self):
        path = Path(self._tmp.name) / "result.json"
        made = self.make([reply(text_block("Report: all good."))], result_file=str(path),
                         name="Check")
        made.run()
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result, {"instruction": "Check", "status": "completed", "error": "",
                                  "final_text": "Report: all good."})

    def test_the_result_file_is_written_for_an_error_too(self):
        path = Path(self._tmp.name) / "result.json"
        made = self.make([bad_request("broken request")], result_file=str(path))
        made.run()
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "error")
        self.assertIn("broken request", result["error"])

    def test_dropped_thinking_is_mentioned_once_per_shape(self):
        dropped = [Obj(type="thinking_dropped", reason="prefix_binding_mismatch")]
        script = [reply(tool_use("echo", {}, "1"), input_transformations=dropped),
                  reply(tool_use("echo", {}, "2"), input_transformations=dropped),
                  reply(text_block("ok"), input_transformations=dropped)]
        made = self.make(script, tools={"echo": self.recorder("echo")})
        made.run()
        self.assertEqual(self.shown().count("API dropped 1 replayed thinking block"), 1)

    def test_a_dry_run_prints_the_request_and_sends_nothing(self):
        console, self.out = piped_console("")
        client = FakeClient([])
        made = ScriptedAgent(settings=RunSettings(text="look"), console=console,
                             datadir=self.datadir, get_client=lambda: client, dry_run=True)
        self.assertEqual(made.run(), "completed")
        self.assertEqual(client.requests, [])
        self.assertIn('"model": "claude-opus-5-5"', self.shown())
        self.assertFalse(self.datadir.chats_dir.exists())


class SkillsInARun(LoopCase):
    def skill_store(self):
        store = SkillStore(self.datadir.skills_dir)
        store.load()
        manage_skills(store, {"action": "create", "name": "check-battery",
                              "content": "Read the voltage and report it.", "mode": "enabled",
                              "description": "Reads the battery."})
        manage_skills(store, {"action": "create", "name": "tidy-logs",
                              "content": "Delete logs older than a week.",
                              "mode": "on_demand", "description": "Clears old log files."})
        manage_skills(store, {"action": "create", "name": "asleep", "content": "Not in use."})
        return store

    def make_with_skills(self, script, **settings):
        made = self.make(script, **settings)
        made.skills = self.skill_store()
        return made

    def test_enabled_skills_and_the_on_demand_list_are_in_the_system_prompt(self):
        made = self.make_with_skills([reply(text_block("ok"))])
        made.run()
        system = self.client.requests[0]["system"][0]["text"]
        self.assertIn("## Skill: check-battery\nRead the voltage and report it.", system)
        self.assertIn("## On-Demand Skills", system)
        self.assertIn("tidy-logs", system)
        self.assertIn("Clears old log files.", system)
        self.assertNotIn("Delete logs older than a week.", system)
        self.assertNotIn("asleep", system)
        self.assertTrue(system.startswith("You are the brain of a small robot."))

    def test_get_skill_is_offered_for_exactly_the_on_demand_skills(self):
        made = self.make_with_skills([reply(text_block("ok"))])
        made.run()
        tools = {tool["name"]: tool for tool in self.client.requests[0]["tools"]}
        self.assertEqual(
            tools["get_skill"]["input_schema"]["properties"]["skill_name"]["enum"],
            ["tidy-logs"])

    def test_get_skill_is_not_offered_without_on_demand_skills(self):
        made = self.make([reply(text_block("ok"))])
        made.skills = SkillStore(self.datadir.skills_dir)
        made.skills.load()
        made.run()
        names = [tool["name"] for tool in self.client.requests[0]["tools"]]
        self.assertNotIn("get_skill", names)

    def test_get_skill_returns_the_skills_text(self):
        script = [reply(tool_use("get_skill", {"skill_name": "tidy-logs"}, "s")),
                  reply(text_block("Tidied."))]
        made = self.make_with_skills(script)
        made.run()
        self.assertEqual(made.messages[2]["content"][0]["content"],
                         "Delete logs older than a week.")

    def test_a_skill_that_is_not_on_demand_cannot_be_fetched(self):
        script = [reply(tool_use("get_skill", {"skill_name": "check-battery"}, "s")),
                  reply(text_block("ok"))]
        made = self.make_with_skills(script)
        made.run()
        self.assertEqual(made.messages[2]["content"][0]["content"],
                         "Skill not found or not on-demand: check-battery")

    def test_a_skill_with_bundled_files_says_where_they_are(self):
        store = self.skill_store()
        manage_skills(store, {"action": "write_file", "name": "tidy-logs",
                              "file_path": "scripts/tidy.sh", "file_content": "echo tidy\n"})
        script = [reply(tool_use("get_skill", {"skill_name": "tidy-logs"}, "s")),
                  reply(text_block("ok"))]
        made = self.make(script)
        made.skills = store
        made.run()
        result = made.messages[2]["content"][0]["content"]
        self.assertTrue(result.startswith("Delete logs older than a week."))
        self.assertIn(f"bundled files are in: {store.folder('tidy-logs')}", result)

    def test_a_skill_created_during_a_run_does_not_change_that_runs_prompt_or_tools(self):
        made = None

        def create_skill(_input):
            manage_skills(made.skills, {"action": "create", "name": "late-skill",
                                        "content": "New.", "mode": "on_demand"})
            return "created"
        script = [reply(tool_use("author", {}, "a")), reply(text_block("ok"))]
        made = self.make(script, tools={"author": _tool("author", create_skill)})
        made.skills = self.skill_store()
        made.run()
        first, second = self.client.requests
        self.assertEqual(first["system"], second["system"])
        self.assertEqual(first["tools"], second["tools"])

    def test_get_skill_can_be_blocked(self):
        made = self.make_with_skills([reply(text_block("ok"))], blocked_tools=["get_skill"])
        made.run()
        names = [tool["name"] for tool in self.client.requests[0]["tools"]]
        self.assertNotIn("get_skill", names)


class WhatTheModelKnowsAboutItsRun(LoopCase):
    def facts(self, request):
        return " ".join(request["system"][1]["text"].split())

    def test_a_saved_instruction_is_told_its_name_and_model(self):
        made = self.make([reply(text_block("ok"))], name="Morning check",
                         model="claude-haiku-5-5")
        made.run()
        system = self.client.requests[0]["system"]
        self.assertEqual(len(system), 2)
        self.assertEqual(self.facts(self.client.requests[0]),
                         'About this run: you are running as the saved instruction named '
                         '"Morning check", on the model claude-haiku-5-5.')
        # Only the shared part in front carries the cache marker.
        self.assertIn("cache_control", system[0])
        self.assertNotIn("cache_control", system[1])

    def test_a_plain_chat_is_told_it_runs_on_the_default_settings(self):
        made = self.make([reply(text_block("ok"))], lines="", conversational=True)
        made.run()
        self.assertEqual(self.facts(self.client.requests[0]),
                         "About this run: this is a chat started without a saved "
                         'instruction. Its settings come from the instruction named '
                         '"Default". You are running on the model claude-opus-5-5.')

    def test_different_instructions_share_everything_but_that_paragraph(self):
        first = self.make([reply(text_block("ok"))], name="One")
        first.run()
        one = self.client.requests[0]
        second = self.make([reply(text_block("ok"))], name="Two")
        second.run()
        two = self.client.requests[0]
        self.assertEqual(one["system"][0], two["system"][0])
        self.assertEqual(one["tools"], two["tools"])
        self.assertNotEqual(one["system"][1], two["system"][1])

    def test_the_paragraph_does_not_change_during_a_run(self):
        script = [reply(tool_use("echo", {}, "e")), reply(text_block("ok"))]
        made = self.make(script, name="Check", tools={"echo": self.recorder("echo")})
        made.run()
        first, second = self.client.requests
        self.assertEqual(first["system"], second["system"])

    def test_the_saved_chat_records_the_whole_prompt(self):
        made = self.make([reply(text_block("ok"))], name="Check")
        made.run()
        saved = json.loads((self.datadir.chats_dir / f"{made.chat_stem}.json")
                           .read_text(encoding="utf-8"))
        self.assertIn("You are the brain of a small robot.", saved["system_prompt"])
        self.assertIn('the saved instruction named "Check"',
                      " ".join(saved["system_prompt"].split()))


class ModuleSurface(unittest.TestCase):
    def test_the_user_prompt_tool_requires_a_message(self):
        self.assertEqual(agent_module.USER_PROMPT_TOOL["input_schema"]["required"], ["message"])


if __name__ == "__main__":
    unittest.main()
