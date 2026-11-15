"""Stand-ins for the Anthropic client and the terminal, so the loop runs with no network."""

import io
import itertools

import anthropic
import httpx2

from robot.console import INTERRUPTED, Console, Interrupts

_ids = itertools.count(1)


class Obj:
    """A plain object with attributes, like the SDK's response objects."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __repr__(self):
        return f"Obj({self.__dict__})"


def text_block(text):
    return Obj(type="text", text=text)


def thinking_block(text="thinking it over", signature="sig"):
    return Obj(type="thinking", thinking=text, signature=signature)


def tool_use(name, tool_input=None, tool_id=None):
    return Obj(type="tool_use", name=name, input=tool_input or {},
               id=tool_id or f"toolu_{next(_ids)}")


def server_search(query):
    return Obj(type="server_tool_use", name="web_search", input={"query": query},
               id=f"srvtoolu_{next(_ids)}")


def usage(input_tokens=100, output_tokens=20, cache_write=0, cache_read=0, searches=0,
          speed=None, iterations=None):
    return Obj(input_tokens=input_tokens, output_tokens=output_tokens,
               cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read,
               server_tool_use=Obj(web_search_requests=searches), speed=speed,
               iterations=iterations)


def reply(*blocks, stop_reason=None, model="claude-opus-5-5", usage_=None, **extra):
    """A model reply. The stop reason defaults to what the blocks imply."""
    if stop_reason is None:
        has_tool = any(getattr(block, "type", "") == "tool_use" for block in blocks)
        stop_reason = "tool_use" if has_tool else "end_turn"
    fields = dict(content=list(blocks), stop_reason=stop_reason, model=model,
                  usage=usage_ or usage(), stop_details=None, input_transformations=None)
    fields.update(extra)
    return Obj(**fields)


class InterruptDuring:
    """A reply that is cut short by Ctrl-C after `after_text` has streamed."""

    def __init__(self, message, interrupts, after_text=None):
        self.message = message
        self.interrupts = interrupts
        self.after_text = after_text


class FakeStream:
    def __init__(self, message, interrupt=None):
        self.message = message
        self._interrupt = interrupt
        self.current_message_snapshot = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self.message.content:
            yield Obj(type="content_block_start", content_block=block)
            if block.type == "text":
                yield Obj(type="content_block_delta",
                          delta=Obj(type="text_delta", text=block.text))
                if self._interrupt is not None:
                    # What the signal handler does inside a raisable region.
                    self._interrupt.interrupts.interrupt.set()
                    raise KeyboardInterrupt
            elif block.type == "thinking":
                yield Obj(type="content_block_delta",
                          delta=Obj(type="thinking_delta", thinking=block.thinking))
            yield Obj(type="content_block_stop", content_block=block)
        yield Obj(type="message_delta",
                  delta=Obj(stop_reason=self.message.stop_reason,
                            stop_details=self.message.stop_details))

    def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def stream(self, **kwargs):
        # Keep what was sent. The messages list is copied because the loop
        # keeps appending to the original.
        self.requests.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self.script:
            raise AssertionError("the fake client ran out of scripted replies")
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, (Obj, InterruptDuring)):
            item = item(kwargs)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, InterruptDuring):
            return FakeStream(item.message, interrupt=item)
        return FakeStream(item)


class FakeClient:
    """Replays a script: each entry is a reply, an exception to raise, or a
    function of the request that returns one of those."""

    def __init__(self, script):
        self.beta = Obj(messages=FakeMessages(script))

    @property
    def requests(self):
        return self.beta.messages.requests

    @property
    def remaining(self):
        return len(self.beta.messages.script)


def _response(status, message):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(
        status, request=request,
        json={"type": "error", "error": {"type": "error", "message": message}})


def bad_request(message):
    return anthropic.BadRequestError(message, response=_response(400, message), body=None)


def rate_limited(message="rate limited"):
    return anthropic.RateLimitError(message, response=_response(429, message), body=None)


def status_error(status, message="server error"):
    return anthropic.APIStatusError(message, response=_response(status, message), body=None)


def connection_error(message="Connection error."):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message=message, request=request)


class NoWaitInterrupts(Interrupts):
    """Interrupts whose backoff waits return at once, recording their length."""

    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.pending()


def piped_console(lines="", **flags):
    """A console fed from text, as when input is piped: not a terminal."""
    out = io.StringIO()
    console = Console(stdin=io.StringIO(lines), stdout=out,
                      interrupts=flags.pop("interrupts", None) or NoWaitInterrupts(), **flags)
    return console, out


class TerminalConsole(Console):
    """A console that behaves as if a person were at a terminal.

    `replies` are handed out in order: a string, "" for a bare Enter, None for
    Ctrl-D, INTERRUPTED for Ctrl-C at the prompt.
    """

    def __init__(self, replies, **flags):
        self.out = io.StringIO()
        super().__init__(stdin=io.StringIO(""), stdout=self.out,
                         interrupts=flags.pop("interrupts", None) or NoWaitInterrupts(), **flags)
        self.tty = True
        self.replies = list(replies)
        self.questions = []

    def ask(self, *, question="", preface="", prompt="you> "):
        self.end_line()
        self.questions.append(question)
        if question:
            self._line("robot asks> " + question)
        if not self.replies:
            return None
        reply = self.replies.pop(0)
        if isinstance(reply, str):
            self._line(prompt + reply)
        return reply


__all__ = [
    "INTERRUPTED", "FakeClient", "InterruptDuring", "NoWaitInterrupts", "Obj",
    "TerminalConsole", "bad_request", "connection_error", "piped_console", "rate_limited",
    "reply", "server_search", "status_error", "text_block", "thinking_block", "tool_use",
    "usage",
]
