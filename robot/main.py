"""Robot brain entry point: an interactive chat loop with the Anthropic API."""

import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from robot.tools import SERVER_TOOLS, Tool, available_tools

try:
    import readline  # noqa: F401  (line editing and history for input() on the Pi)
except ImportError:
    pass  # not available on Windows

MODEL = "claude-opus-5-5"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
EXIT_WORDS = {"exit", "quit", "bye"}
MAX_PAUSES = 5  # how many times one reply may resume a paused server-side tool

SYSTEM_PROMPT = """\
You are the brain of a small robot. You run as a program on a Raspberry Pi
Zero 2 W, which is your body's onboard computer. The person talking to you is
typing at a keyboard connected to the robot, or over SSH.

Speak as the robot, in the first person. When asked about yourself, your
temperature, or your hardware, answer about this Raspberry Pi, not about
servers or data centres.

Your only way to sense or act on the physical world is through the tools you
have been given. If you have no tool for something (moving, seeing, hearing,
speaking aloud), say plainly that you can't do it yet rather than pretending.
Never invent sensor readings: use a tool to get the real value.

Keep replies short and conversational, a sentence or two unless asked for more.
Use plain text only, with no Markdown formatting, because your replies are
shown in a plain terminal.
"""


def run_tool(tools: dict[str, Tool], block) -> dict:
    """Run one tool the model asked for and build the result to send back."""
    detail = f": {json.dumps(block.input, ensure_ascii=False)}" if block.input else ""
    print(f"\n[tool: {block.name}{detail}]", flush=True)
    result = {"type": "tool_result", "tool_use_id": block.id}
    try:
        result["content"] = tools[block.name].run(block.input)
    except Exception as err:  # report any failure to the model instead of crashing
        result["content"] = f"{type(err).__name__}: {err}"
        result["is_error"] = True
    return result


def reply(client: anthropic.Anthropic, messages: list, tools: dict[str, Tool]) -> None:
    """Stream the model's reply, running any tools it asks for along the way."""
    request = {
        "model": MODEL,
        "max_tokens": 64000,
        "system": SYSTEM_PROMPT,
        "output_config": {"effort": "low"},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "cache_control": {"type": "ephemeral"},
    }
    request["tools"] = [tool.definition for tool in tools.values()] + SERVER_TOOLS

    pauses = 0
    while True:
        with client.beta.messages.stream(messages=messages, **request) as stream:
            for event in stream:
                if event.type == "text":
                    print(event.text, end="", flush=True)
                elif event.type == "content_block_stop":
                    # Show each web search and its query. The search tool also
                    # runs internal code_execution steps; those stay hidden.
                    block = event.content_block
                    if block.type == "server_tool_use" and block.name == "web_search":
                        print(f"\n[tool: web_search: {block.input.get('query', '')}]", flush=True)
            response = stream.get_final_message()

        # Keep the whole content list, not just the text: thinking, tool-use and
        # search-result blocks must be passed back unchanged on later requests.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn" and pauses < MAX_PAUSES:
            # A server-side tool is still working: send the turn back to resume it.
            pauses += 1
            continue
        if response.stop_reason != "tool_use":
            break

        # Answer every tool call from this reply in a single user message.
        results = [
            run_tool(tools, block)
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})

    print()
    if response.stop_reason == "refusal":
        print("(the model declined to answer that)")
    elif response.stop_reason == "max_tokens":
        print("(reply cut off at the length limit)")


def main() -> None:
    load_dotenv(ENV_FILE)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    tools = available_tools()
    messages: list = []

    print("Robot chat. Type 'exit' or press Ctrl-D to quit.")
    tool_names = list(tools) + [tool["name"] for tool in SERVER_TOOLS]
    print(f"Tools: {', '.join(tool_names) or 'none'}")
    while True:
        try:
            user_text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in EXIT_WORDS:
            break

        turn_start = len(messages)
        messages.append({"role": "user", "content": user_text})
        print("robot> ", end="", flush=True)
        try:
            reply(client, messages, tools)
            continue
        except KeyboardInterrupt:
            print("\n(interrupted)")
        except anthropic.RateLimitError:
            print("\n(rate limited; wait a moment and try again)")
        except anthropic.APIStatusError as err:
            print(f"\n(API error {err.status_code}: {err.message})")
        except anthropic.APIConnectionError:
            print("\n(could not reach the API; check the Pi's network)")
        # The turn failed: drop everything it added so the history stays valid.
        del messages[turn_start:]


if __name__ == "__main__":
    main()
