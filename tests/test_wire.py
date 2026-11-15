"""The real Anthropic SDK, driven over a mock network with recorded replies.

The fake client in tests/fakes.py cannot notice a mistake in how this program
uses the SDK itself. These tests can: they let the installed SDK build the
real HTTP request and parse real event streams (tests/fixtures/*.sse, recorded
with tests/record_fixtures.py). Nothing leaves the machine.
"""

import json
import tempfile
import unittest
from pathlib import Path

import anthropic
import httpx2

from robot import api
from robot.agent import Agent
from robot.datastore import DataDir
from robot.instructions import RunSettings
from tests.fakes import piped_console

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLOCK_TOOL = {
    "name": "get_current_datetime",
    "description": "Get the current date and time.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def stream(name):
    """A recorded reply as the API would send it."""
    return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                           content=(FIXTURES / f"{name}.sse").read_bytes())


def api_error(status, message, kind="invalid_request_error"):
    return httpx2.Response(status, json={"type": "error",
                                         "error": {"type": kind, "message": message}})


class WireCase(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.console, self.out = piped_console("")
        self.interrupts = self.console.interrupts
        self.learned = api.Learned()

    def client(self, *replies):
        waiting = list(replies)

        def handle(request):
            self.sent.append(request)
            reply = waiting.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return anthropic.Anthropic(
            api_key="test-key", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handle)))

    def call(self, client, messages=None, **overrides):
        args = dict(model="claude-opus-5-5", system_prompt="You are a robot.",
                    messages=messages if messages is not None
                    else [{"role": "user", "content": "hello"}],
                    client_tools=[CLOCK_TOOL], thinking_mode="low", learned=self.learned)
        args.update(overrides)
        return api.call_model(client, self.console, self.interrupts, **args)

    def body(self, index=-1):
        return json.loads(self.sent[index].content)


class WhatIsSent(WireCase):
    def test_the_request_on_the_wire(self):
        self.call(self.client(stream("text")))
        request = self.sent[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url.path, "/v1/messages")
        self.assertEqual(request.headers["anthropic-version"], "2026-10-21")
        betas = request.headers["anthropic-beta"]
        self.assertIn("thinking-binding-controls-2026-08-01", betas)
        self.assertIn("server-side-fallback-2026-07-01", betas)
        self.assertEqual(request.headers["authorization"], "Bearer test-key")

        body = self.body()
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertIs(body["stream"], True)
        self.assertEqual(body["max_tokens"], 128000)
        for gone in ("temperature", "top_p", "top_k", "betas"):
            self.assertNotIn(gone, body)
        self.assertEqual(body["thinking"], {
            "type": "adaptive", "display": "summarized",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"}})
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["system"], [{"type": "text", "text": "You are a robot.",
                                           "cache_control": {"type": "ephemeral"}}])
        self.assertEqual([tool["name"] for tool in body["tools"]],
                         ["get_current_datetime", "web_search"])
        self.assertEqual(body["tools"][1]["type"], "web_search_20260209")
        self.assertEqual(body["messages"], [{"role": "user", "content": [
            {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]}])

    def test_fast_mode_adds_its_parameter_and_header(self):
        self.call(self.client(stream("text")), fast_mode=True)
        self.assertEqual(self.body()["speed"], "fast")
        self.assertIn("fast-mode-2026-02-01", self.sent[0].headers["anthropic-beta"])

    def test_a_model_with_no_extras_sends_no_beta_header(self):
        self.call(self.client(stream("text")), model="claude-haiku-4-5-20251001")
        self.assertNotIn("anthropic-beta", self.sent[0].headers)
        self.assertNotIn("fallbacks", self.body())


class RecordedReplies(WireCase):
    def test_a_text_reply(self):
        result = self.call(self.client(stream("text")))
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.text, "Hello there, how are you?")
        self.assertEqual([block.type for block in result.content], ["text"])
        self.assertEqual(result.usage["input_tokens"], 43)
        self.assertEqual(result.usage["output_tokens"], 11)
        self.assertEqual(result.usage["model"], "claude-haiku-5-5")
        self.assertEqual(result.usage["web_search_requests"], 0)
        self.assertIn("robot> Hello there, how are you?", self.out.getvalue())

    def test_a_tool_call_reply(self):
        result = self.call(self.client(stream("tool")))
        self.assertEqual(result.stop_reason, "tool_use")
        block = result.content[-1]
        self.assertEqual(block.type, "tool_use")
        self.assertEqual(block.name, "get_current_datetime")
        self.assertEqual(block.input, {})
        self.assertTrue(block.id.startswith("toolu_"))

    def test_a_web_search_reply(self):
        result = self.call(self.client(stream("search")))
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertIn("Canberra", result.text)
        self.assertEqual(result.usage["web_search_requests"], 2)
        self.assertEqual(result.usage["cache_read_input_tokens"], 18699)
        kinds = {block.type for block in result.content}
        self.assertLessEqual({"thinking", "server_tool_use", "web_search_tool_result", "text"},
                             kinds)
        self.assertIn("[tool: web_search: ", self.out.getvalue())

    def test_thinking_is_shown_when_asked_for(self):
        self.console, self.out = piped_console("", show_thinking=True)
        self.interrupts = self.console.interrupts
        self.call(self.client(stream("search")))
        self.assertIn("[thinking] ", self.out.getvalue())


class Replay(WireCase):
    """What was received goes back unchanged on the next request."""

    def test_a_tool_round_goes_back_with_its_call_and_result(self):
        messages = [{"role": "user", "content": "what time is it?"}]
        client = self.client(stream("tool"), stream("text"))
        first = self.call(client, messages)
        call = first.content[-1]
        messages.append({"role": "assistant", "content": first.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": "10:30"}]})
        self.call(client, messages)

        sent = self.body()["messages"]
        self.assertEqual([message["role"] for message in sent], ["user", "assistant", "user"])
        echoed = sent[1]["content"][-1]
        self.assertEqual(echoed["type"], "tool_use")
        self.assertEqual(echoed["id"], call.id)
        self.assertEqual(echoed["name"], "get_current_datetime")
        self.assertEqual(echoed["input"], {})
        self.assertEqual(sent[2]["content"], [
            {"type": "tool_result", "tool_use_id": call.id, "content": "10:30",
             "cache_control": {"type": "ephemeral"}}])

    def test_thinking_and_search_results_go_back_as_they_came(self):
        messages = [{"role": "user", "content": "capital of Australia?"}]
        client = self.client(stream("search"), stream("text"))
        first = self.call(client, messages)
        messages.append({"role": "assistant", "content": first.content})
        messages.append({"role": "user", "content": "and its population?"})
        self.call(client, messages)

        echoed = self.body()["messages"][1]["content"]
        self.assertEqual(len(echoed), len(first.content))
        thinking = [block for block in echoed if block["type"] == "thinking"]
        received = [block for block in first.content if block.type == "thinking"]
        self.assertTrue(thinking)
        for sent_block, got in zip(thinking, received):
            self.assertEqual(sent_block["thinking"], got.thinking)
            self.assertEqual(sent_block["signature"], "SIGNATURE_PLACEHOLDER")
        searches = [block for block in echoed if block["type"] == "web_search_tool_result"]
        self.assertEqual(len(searches), 2)
        self.assertEqual(searches[0]["content"][0]["encrypted_content"], "ENCRYPTED_PLACEHOLDER")
        self.assertTrue(searches[0]["content"][0]["url"].startswith("http"))


class RealErrors(WireCase):
    """The retry ladder against the SDK's own exception classes and wording."""

    def test_an_overflow_is_read_from_the_real_error_and_trimmed(self):
        messages = []
        for number in range(6):
            messages += [{"role": "user", "content": f"question {number}"},
                         {"role": "assistant", "content": f"answer {number}"}]
        messages.append({"role": "user", "content": "latest"})
        before = len(messages)
        client = self.client(
            api_error(400, "prompt is too long: 250000 tokens > 200000 maximum"),
            stream("text"))
        result = self.call(client, messages)
        self.assertEqual(result.text, "Hello there, how are you?")
        self.assertLess(len(messages), before)
        self.assertEqual(len(self.body()["messages"]), len(messages))
        self.assertIn("Context exceeded the model's limit", self.out.getvalue())

    def test_a_lower_output_ceiling_is_learned(self):
        client = self.client(
            api_error(400, "max_tokens: 128000 > 64000, which is the maximum allowed number "
                           "of output tokens for claude-opus-5-5"),
            stream("text"))
        self.call(client)
        self.assertEqual(self.learned.output_caps, {"claude-opus-5-5": 64000})
        self.assertEqual(self.body()["max_tokens"], 64000)

    def test_refused_fallbacks_are_dropped_and_the_call_retried(self):
        client = self.client(api_error(400, "fallbacks: Extra inputs are not permitted"),
                             stream("text"))
        self.call(client)
        self.assertIn("fallbacks", self.learned.unsupported)
        self.assertNotIn("fallbacks", self.body())
        self.assertNotIn("server-side-fallback", self.sent[1].headers["anthropic-beta"])

    def test_rate_limits_overload_and_connection_failures_are_retried(self):
        client = self.client(
            api_error(429, "rate limited", "rate_limit_error"),
            api_error(529, "Overloaded", "overloaded_error"),
            httpx2.ConnectError("could not connect"),
            stream("text"))
        result = self.call(client)
        self.assertEqual(result.text, "Hello there, how are you?")
        self.assertEqual(self.interrupts.waits, [5, 20, 20])
        self.assertEqual(len(self.sent), 4)

    def test_a_request_too_large_in_bytes_trims_and_retries(self):
        messages = []
        for number in range(6):
            messages += [{"role": "user", "content": f"q{number}"},
                         {"role": "assistant", "content": f"a{number}"}]
        messages.append({"role": "user", "content": "latest"})
        before = len(messages)
        self.call(self.client(api_error(413, "request too large", "request_too_large"),
                              stream("text")), messages)
        self.assertLess(len(messages), before)

    def test_an_error_nothing_can_be_done_about_is_raised(self):
        with self.assertRaises(anthropic.BadRequestError):
            self.call(self.client(api_error(400, "messages.0.content: field required")))
        with self.assertRaises(anthropic.AuthenticationError):
            self.call(self.client(api_error(401, "invalid x-api-key", "authentication_error")))
        with self.assertRaises(anthropic.NotFoundError):
            self.call(self.client(api_error(404, "model: no-such-model", "not_found_error")))


class WholeRun(unittest.TestCase):
    """An entire run through the real SDK: a tool call, then the answer."""

    def test_a_tool_round_and_a_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            sent = []
            waiting = [stream("tool"), stream("text")]

            def handle(request):
                sent.append(json.loads(request.content))
                return waiting.pop(0)
            client = anthropic.Anthropic(
                api_key="test-key", max_retries=0,
                http_client=anthropic.DefaultHttpxClient(
                    transport=httpx2.MockTransport(handle)))
            console, out = piped_console("")
            datadir = DataDir(folder)
            made = Agent(settings=RunSettings(text="What time is it?"), console=console,
                         datadir=datadir, get_client=lambda: client)
            self.assertEqual(made.run(), "completed")

            self.assertEqual(len(sent), 2)
            self.assertEqual(sent[0]["tools"], sent[1]["tools"])
            self.assertEqual(sent[0]["system"], sent[1]["system"])
            result = sent[1]["messages"][2]["content"][0]
            self.assertEqual(result["type"], "tool_result")
            self.assertRegex(result["content"], r"\d{2}:\d{2}:\d{2}")
            shown = out.getvalue()
            self.assertIn("[tool: get_current_datetime]", shown)
            self.assertIn("robot> Hello there, how are you?", shown)
            self.assertIn("call 2: ", shown)
            line = datadir.costlog_file.read_text(encoding="utf-8").strip().split(";")
            self.assertEqual(line[7], "2")          # two calls
            self.assertEqual(line[8], "445")        # 402 + 43 input tokens
            self.assertEqual(line[9], "41")         # 30 + 11 output tokens
            self.assertGreater(float(line[3]), 0)


if __name__ == "__main__":
    unittest.main()
