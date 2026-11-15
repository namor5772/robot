"""Robot brain entry point: send one short test message to the Anthropic API."""

from pathlib import Path

import anthropic
from dotenv import load_dotenv

MODEL = "claude-opus-5-5"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    load_dotenv(ENV_FILE)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": "Say hello from a Raspberry Pi Zero 2 W robot in one short sentence.",
            }
        ],
    )

    if response.stop_reason == "refusal":
        print("The model declined to answer.")
        return

    for block in response.content:
        if block.type == "text":
            print(block.text)


if __name__ == "__main__":
    main()
