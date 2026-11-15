"""Helpers for the conversation history that is sent with every request.

They estimate its size, drop the oldest rounds when it no longer fits, read
the two API errors that say so, remove blocks the API will not take back, and
repair a history that an interruption left half-finished.

A message's content is a string or a list of blocks. A block is a plain dict
when this program built it and an SDK object when the API returned it, so
every block is read through _get.
"""

import json
import re

# An image is billed by its pixels, not by the length of its base64 text.
_IMAGE_TOKENS = 1600
_THINKING_TYPES = ("thinking", "redacted_thinking")


def _get(block, name, default=None):
    """One field of a block or message, whether it is a dict or an object."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def estimate_content_tokens(content) -> int:
    """A rough token count for one message's content: four characters a token.

    It only sizes a history cut and is never used for billing, so it can be
    coarse. Counting an image by its base64 length would overstate it by a
    factor of hundreds, hence the flat figure.
    """
    if isinstance(content, str):
        return len(content) // 4
    if not isinstance(content, list):
        return len(str(content)) // 4
    total = 0
    for block in content:
        if _get(block, "type") == "image":
            total += _IMAGE_TOKENS
        elif isinstance(block, dict):
            try:
                total += len(json.dumps(block, default=str)) // 4
            except (TypeError, ValueError):
                total += len(str(block)) // 4
        else:
            # An SDK object: its repr grows with what it holds.
            total += len(str(block)) // 4
    return total


def strip_thinking_blocks(messages: list) -> int:
    """Remove the thinking blocks from every assistant turn, in place.

    This is the recovery when the API rejects replayed thinking because the
    history before it has changed since it was written. Text and tool calls
    stay. A turn made of nothing but thinking is left alone, because an empty
    content list would be rejected as well. Returns the number of blocks
    removed.
    """
    removed = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        kept = [block for block in content if _get(block, "type") not in _THINKING_TYPES]
        if kept and len(kept) != len(content):
            removed += len(content) - len(kept)
            message["content"] = kept
    return removed


def strip_pre_fallback_blocks(blocks: list) -> list:
    """The blocks to keep from a reply in which the API switched models.

    A "fallback" block marks each switch. Everything before the last marker
    came from a model that declined part-way through. The model that took
    over never saw that model's thinking or its tool calls, and those calls
    would have no results, so from that part only the text and the finished
    server-tool pairs (a server_tool_use with its result) are kept. Everything
    after the marker is the serving model's own turn and is kept whole. The
    markers themselves are dropped. A reply without a marker is returned
    unchanged, as the same list object.
    """
    last = -1
    for index, block in enumerate(blocks):
        if _get(block, "type") == "fallback":
            last = index
    if last < 0:
        return blocks
    before = blocks[:last]
    answered = {_get(block, "tool_use_id") for block in before
                if (_get(block, "type") or "").endswith("_tool_result")}
    kept, kept_ids = [], set()
    for block in before:
        kind = _get(block, "type") or ""
        if kind == "text":
            kept.append(block)
        elif kind == "server_tool_use":
            if _get(block, "id") in answered:
                kept.append(block)
                kept_ids.add(_get(block, "id"))
        elif kind.endswith("_tool_result"):
            if _get(block, "tool_use_id") in kept_ids:
                kept.append(block)
    kept.extend(blocks[last + 1:])  # no marker can follow the last one
    return kept


def parse_overflow_counts(message: str) -> tuple[int | None, int | None]:
    """(tokens sent, tokens allowed) from the API's "prompt is too long" error.

    The error reads like "prompt is too long: 1,597,842 tokens > 1,000,000
    maximum". Returns (None, None) when the counts are not there.
    """
    found = re.search(r"(\d[\d,]*)\s*tokens\s*>\s*(\d[\d,]*)", message or "")
    if not found:
        return None, None
    return int(found.group(1).replace(",", "")), int(found.group(2).replace(",", ""))


def parse_output_cap(message: str) -> int | None:
    """The model's output ceiling, from the error an over-large max_tokens draws.

    The error reads like "max_tokens: 200000 > 64000, which is the maximum
    allowed number of output tokens for <model>". The overflow error has the
    same "N > M" shape but never the max_tokens prefix, so the two cannot be
    mistaken for each other. Returns None for any other message.
    """
    found = re.search(r"max_tokens:\s*(\d[\d,]*)\s*>\s*(\d[\d,]*)", message or "")
    if not found:
        return None
    cap = int(found.group(2).replace(",", ""))
    return cap if cap > 0 else None


def _is_turn_start(message) -> bool:
    """True for a user message that opens a round, false for one carrying tool results."""
    if _get(message, "role") != "user":
        return False
    content = _get(message, "content")
    if isinstance(content, list):
        return not any(_get(block, "type") == "tool_result" for block in content)
    return True


def trim_history_for_context(messages: list, tokens: int | None = None,
                             maximum: int | None = None) -> int:
    """Drop the oldest rounds, in place, so the history fits the context window.

    The cut only ever lands on a user message that opens a round. A message
    of tool results never becomes the first one, so no result is left without
    the call it answers. When the API reported how many tokens were sent and
    how many are allowed, enough rounds go to reach three quarters of the
    limit, which leaves room for the system prompt, the tools and the reply.
    Otherwise the oldest half goes. The last two rounds always stay. Returns
    the number of messages removed; 0 means there was nothing safe to drop.
    """
    starts = [index for index, message in enumerate(messages) if _is_turn_start(message)]
    if len(starts) <= 2:
        return 0
    last_cut = starts[-2]
    if tokens and maximum and tokens > maximum:
        to_remove = tokens - int(maximum * 0.75)
        cut_at, removed = 0, 0
        for start in starts[1:]:
            if start > last_cut:
                break
            removed += sum(estimate_content_tokens(_get(messages[i], "content"))
                           for i in range(cut_at, start))
            cut_at = start
            if removed >= to_remove:
                break
    else:
        cut_at = min(starts[len(starts) // 2], last_cut)
    if cut_at <= 0:
        cut_at = min(starts[1], last_cut)  # always drop at least one round
    del messages[:cut_at]
    return cut_at


def final_assistant_text(messages: list) -> str:
    """The text of the last assistant message that has any: the run's report."""
    for message in reversed(messages):
        if _get(message, "role") != "assistant":
            continue
        content = _get(message, "content")
        if isinstance(content, str):
            if content.strip():
                return content
            continue
        if isinstance(content, list):
            parts = [_get(block, "text") for block in content if _get(block, "type") == "text"]
            parts = [text for text in parts if text]
            if parts:
                return "\n".join(parts)
    return ""


def _tool_call_ids(content) -> list:
    """The ids of the client tool calls in an assistant message, in order."""
    if not isinstance(content, (list, tuple)):
        return []
    ids = []
    for block in content:
        if _get(block, "type") == "tool_use":
            call_id = _get(block, "id")
            if call_id and call_id not in ids:
                ids.append(call_id)
    return ids


def _as_blocks(content) -> list:
    """A user message's content as a list of blocks."""
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        # The API rejects an empty text block, so blank text is dropped.
        return [{"type": "text", "text": content}] if content.strip() else []
    if isinstance(content, tuple):
        return list(content)
    return [] if content is None else [content]


def repair_tool_pairs(messages: list, note: str = "[Not run: the run was interrupted]") -> int:
    """Give every client tool call its result, in place. Returns results added.

    The API rejects a history in which an assistant turn calls tools and the
    next message does not answer every call. An interruption can leave exactly
    that, so each unanswered call gets an error result saying it was not run.
    The results go at the front of the user message that follows, because the
    API wants results before any text; if no user message follows, one is
    inserted. Tools the API runs itself (server_tool_use) keep their results
    inside the assistant turn and are not touched.
    """
    added = 0
    index = 0
    while index < len(messages):
        message = messages[index]
        index += 1
        if _get(message, "role") != "assistant":
            continue
        call_ids = _tool_call_ids(_get(message, "content"))
        if not call_ids:
            continue
        following = messages[index] if index < len(messages) else None
        merge = isinstance(following, dict) and following.get("role") == "user"
        blocks = _as_blocks(following.get("content")) if merge else []
        answered = {_get(block, "tool_use_id") for block in blocks
                    if _get(block, "type") == "tool_result"}
        missing = [{"type": "tool_result", "tool_use_id": call_id, "content": note,
                    "is_error": True}
                   for call_id in call_ids if call_id not in answered]
        if not missing:
            continue
        if not merge:
            messages.insert(index, {"role": "user", "content": missing})
        elif isinstance(following.get("content"), list):
            blocks[:0] = missing
        else:
            following["content"] = missing + blocks
        added += len(missing)
    return added
