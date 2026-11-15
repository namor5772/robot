"""Robot brain entry point: an interactive chat loop with the Anthropic API."""

from pathlib import Path

import anthropic
from dotenv import load_dotenv

from robot.tools import Tool, available_tools

try:
    import readline  # noqa: F401  (line editing and history for input() on the Pi)
except ImportError:
    pass  # not available on Windows

MODEL = "claude-opus-5-5"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
EXIT_WORDS = {"exit", "quit", "bye"}


def run_tool(tools: dict[str, Tool], block) -> dict:
    """Run one tool the model asked for and build the result to send back."""
    print(f"\n[tool: {block.name}]", flush=True)
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
        "output_config": {"effort": "low"},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "cache_control": {"type": "ephemeral"},
    }
    if tools:
        request["tools"] = [tool.definition for tool in tools.values()]

    while True:
        with client.beta.messages.stream(messages=messages, **request) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            response = stream.get_final_message()

        # Keep the whole content list, not just the text: thinking and tool-use
        # blocks must be passed back unchanged on later requests.
        messages.append({"role": "assistant", "content": response.content})

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
    print(f"Tools: {', '.join(tools) or 'none'}")
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
