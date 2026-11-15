"""Robot brain entry point: an interactive chat loop with the Anthropic API."""

from pathlib import Path

import anthropic
from dotenv import load_dotenv

try:
    import readline  # noqa: F401  (line editing and history for input() on the Pi)
except ImportError:
    pass  # not available on Windows

MODEL = "claude-opus-5-5"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
EXIT_WORDS = {"exit", "quit", "bye"}


def reply(client: anthropic.Anthropic, messages: list) -> None:
    """Stream the model's reply to the terminal and append it to the history."""
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        cache_control={"type": "ephemeral"},
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        response = stream.get_final_message()
    print()

    if response.stop_reason == "refusal":
        print("(the model declined to answer that)")
    elif response.stop_reason == "max_tokens":
        print("(reply cut off at the length limit)")

    # Keep the whole content list, not just the text: thinking blocks must be
    # passed back unchanged on later turns.
    messages.append({"role": "assistant", "content": response.content})


def main() -> None:
    load_dotenv(ENV_FILE)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    messages: list = []

    print("Robot chat. Type 'exit' or press Ctrl-D to quit.")
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

        messages.append({"role": "user", "content": user_text})
        print("robot> ", end="", flush=True)
        try:
            reply(client, messages)
        except KeyboardInterrupt:
            messages.pop()
            print("\n(interrupted)")
        except anthropic.RateLimitError:
            messages.pop()
            print("\n(rate limited; wait a moment and try again)")
        except anthropic.APIStatusError as err:
            messages.pop()
            print(f"\n(API error {err.status_code}: {err.message})")
        except anthropic.APIConnectionError:
            messages.pop()
            print("\n(could not reach the API; check the Pi's network)")


if __name__ == "__main__":
    main()
