"""Record a real API reply as a test fixture. Costs a little API credit.

Run on a machine with an API key, from the repo root, and save the output
into tests/fixtures/:

    python -m tests.record_fixtures text   > tests/fixtures/text.sse
    python -m tests.record_fixtures tool   > tests/fixtures/tool.sse
    python -m tests.record_fixtures search > tests/fixtures/search.sse

The output is the raw event stream the API sent, with signatures, encrypted
content and ids replaced by placeholders: the repo is public, and the tests
only need the shape. tests/test_wire.py replays these through the real SDK.
"""

import json
import sys

MODEL = "claude-haiku-5-5"
SYSTEM = "You are a test fixture. Follow the instruction exactly and be brief."
CLOCK_TOOL = {
    "name": "get_current_datetime",
    "description": "Get the current date and time.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
SCENARIOS = {
    "text": dict(prompt="Say hello in exactly five words.", tools=[], web_search=False),
    "tool": dict(prompt="What time is it? Call your clock tool; do not answer yet.",
                 tools=[CLOCK_TOOL], web_search=False),
    "search": dict(prompt="Search the web for the capital of Australia. Answer in one "
                          "short sentence.", tools=[], web_search=True),
}
_OPAQUE_KEYS = {"signature": "SIGNATURE_PLACEHOLDER",
                "encrypted_content": "ENCRYPTED_PLACEHOLDER",
                "encrypted_index": "ENCRYPTED_PLACEHOLDER",
                "encrypted_stdout": "ENCRYPTED_PLACEHOLDER"}


def scrub(value, parent_type=None):
    """Replace anything opaque or identifying with a placeholder."""
    if isinstance(value, dict):
        kind = value.get("type")
        cleaned = {}
        for key, item in value.items():
            if key in _OPAQUE_KEYS and isinstance(item, str):
                cleaned[key] = _OPAQUE_KEYS[key]
            elif key == "data" and kind == "redacted_thinking":
                cleaned[key] = "REDACTED_PLACEHOLDER"
            elif key == "id" and isinstance(item, str) and item.startswith("msg_"):
                cleaned[key] = "msg_fixture"
            elif key == "id" and isinstance(item, str) and item.startswith("container_"):
                cleaned[key] = "container_fixture"
            else:
                cleaned[key] = scrub(item, kind)
        return cleaned
    if isinstance(value, list):
        return [scrub(item, parent_type) for item in value]
    if isinstance(value, str) and len(value) > 600 and " " not in value:
        return "OPAQUE_PLACEHOLDER"  # a long unbroken string is not readable text
    return value


def scrub_line(line: str) -> str:
    if not line.startswith("data:"):
        return line
    try:
        payload = json.loads(line[len("data:"):])
    except ValueError:
        return line
    return "data: " + json.dumps(scrub(payload), ensure_ascii=False, separators=(",", ":"))


def record(name: str) -> str:
    import anthropic
    from dotenv import load_dotenv

    from robot import api
    from robot.main import ENV_FILE

    load_dotenv(ENV_FILE)
    scenario = SCENARIOS[name]
    kwargs, betas, _ = api.build_request(
        model=MODEL, system_prompt=SYSTEM,
        messages=[{"role": "user", "content": scenario["prompt"]}],
        client_tools=scenario["tools"], web_search=scenario["web_search"], thinking_mode="low")
    if not kwargs["tools"]:
        del kwargs["tools"]
    kwargs["max_tokens"] = 4000
    client = anthropic.Anthropic()
    extra = {"betas": betas} if betas else {}
    with client.beta.messages.with_streaming_response.create(
            stream=True, **kwargs, **extra) as response:
        lines = [scrub_line(line) for line in response.iter_lines()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        sys.exit("usage: python -m tests.record_fixtures " + "|".join(SCENARIOS))
    sys.stdout.write(record(sys.argv[1]))
