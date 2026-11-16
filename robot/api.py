"""One model call: build the request, stream the reply, retry what can be retried.

This is the only module that imports the Anthropic SDK, which takes many
seconds to load on the Pi. Import it lazily.
"""

import json
from dataclasses import dataclass, field

import anthropic

from robot import history, models

MAX_RETRIES = 10
_CACHE_CONTROL = {"type": "ephemeral"}


@dataclass
class Learned:
    """Request features the API has refused during this process.

    When the API rejects something this key or model cannot use, the feature
    is recorded here and no longer sent, so only the first call pays for it.
    """

    unsupported: set = field(default_factory=set)
    output_caps: dict = field(default_factory=dict)  # model -> ceiling the API named


@dataclass
class CallResult:
    stop_reason: str
    content: list  # the reply's content blocks, as returned by the SDK
    text: str  # the reply's text as it was streamed
    usage: dict | None = None
    interrupted: bool = False  # cut short by Ctrl-C or a stop request
    dropped_thinking: tuple | None = None  # (count, reasons) the API dropped from history


class _Interrupted(Exception):
    def __init__(self, text, usage):
        super().__init__("interrupted")
        self.text = text
        self.usage = usage


def rate_limit_backoff(attempt: int) -> int:
    return min(2 ** attempt * 5, 60)


def server_error_backoff(attempt: int) -> int:
    return min(2 ** attempt * 10, 90)


def connection_error_backoff(attempt: int) -> int:
    return min(2 ** attempt * 5, 60)


def cache_system(system_text, run_facts=""):
    """The system prompt as a cached block, plus the run's own facts after it.

    The cache prefix is built tools, then system, then messages, and a marker
    caches everything before it, so the one marker covers the tool list too.
    `run_facts` (which instruction, which model) differs between runs, so it
    goes in a second block with no marker: runs of different instructions can
    then still share the cached part in front of it.
    """
    if not system_text:
        return run_facts or system_text
    blocks = [{"type": "text", "text": system_text, "cache_control": dict(_CACHE_CONTROL)}]
    if run_facts:
        blocks.append({"type": "text", "text": run_facts})
    return blocks


def cache_messages(messages, max_breakpoints=2):
    """A copy of `messages` with cache markers on the newest user turns.

    Two rolling markers: the newest one is written this call and read on the
    next; the older one still matches if the newest write has not landed or
    has expired. The history itself is never changed. Assistant turns hold
    SDK objects and are skipped; user turns are the natural boundaries.
    """
    wire = list(messages)
    placed = 0
    for i in range(len(wire) - 1, -1, -1):
        if placed >= max_breakpoints:
            break
        message = wire[i]
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            if not content:
                continue
            blocks = [{"type": "text", "text": content, "cache_control": dict(_CACHE_CONTROL)}]
        elif isinstance(content, list) and content and isinstance(content[-1], dict):
            blocks = list(content)
            blocks[-1] = {**blocks[-1], "cache_control": dict(_CACHE_CONTROL)}
        else:
            continue
        wire[i] = {**message, "content": blocks}
        placed += 1
    return wire


def build_request(*, model, system_prompt, messages, client_tools, web_search=True,
                  thinking_mode="adaptive", thinking_budget=models.DEFAULT_THINKING_BUDGET,
                  fast_mode=False, learned=None, standard_speed=False, run_facts=""):
    """Everything one call sends: (kwargs, betas, info).

    The live call, --debug and --dry-run all use this one function, so what
    is displayed cannot differ from what is sent.
    """
    learned = learned or Learned()
    tools = list(client_tools)
    betas = []
    if web_search:
        search_tool, search_betas = models.web_search_tool(model, learned.unsupported)
        tools.append(search_tool)
        betas.extend(search_betas)

    kwargs = {
        "model": model,
        "system": cache_system(system_prompt, run_facts),
        "messages": cache_messages(messages),
        "tools": tools,
        # The model's own ceiling: nothing else bounds adaptive thinking, and a
        # smaller figure can cut off a long reasoning phase that is then lost.
        "max_tokens": learned.output_caps.get(model) or models.output_cap_for(model),
    }

    features = models.fable_features(model, learned.unsupported)
    binding = features["block_binding"] if features else None
    fallbacks = features["fallbacks"] if features else None
    feature_betas = list(features["betas"]) if features else []

    always_on = models.is_always_on_thinking(model)
    thinking_off = thinking_mode in ("off", "none")
    if not thinking_off or always_on:
        support = models.thinking_support(model)
        if support == "adaptive":
            # "summarized" returns readable thinking text; the default on
            # current models is an empty thinking block.
            thinking = {"type": "adaptive", "display": "summarized"}
            if binding:
                thinking["block_binding"] = dict(binding)
            kwargs["thinking"] = thinking
            if thinking_mode not in ("off", "none", "adaptive"):
                kwargs["output_config"] = {"effort": thinking_mode}
        elif support == "manual":
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    else:
        # Current models think when the parameter is left out, so "off" has to
        # be said explicitly. Sonnet 5.5 has its own spelling of off.
        if models.thinking_on_by_default(model):
            kwargs["thinking"] = ({"type": "between_tools"} if models.is_sonnet_55(model)
                                  else {"type": "disabled"})
        # The binding is only accepted beside adaptive thinking.
        if binding:
            binding = None
            feature_betas = [b for b in feature_betas if b != models.THINKING_BINDING_BETA]

    if fallbacks:
        kwargs["fallbacks"] = fallbacks

    fast = (fast_mode and not standard_speed and models.supports_fast_mode(model)
            and "speed" not in learned.unsupported)
    if fast:
        kwargs["speed"] = "fast"
        feature_betas.append(models.FAST_MODE_BETA)

    betas.extend(feature_betas)
    info = {"fast": fast, "fallbacks": bool(fallbacks), "block_binding": bool(binding)}
    return kwargs, betas, info


def _plain(value):
    """An SDK object as plain data, for showing a request as JSON."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json", exclude_none=True)
        except Exception:
            pass
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, dict):
        return {name: item for name, item in fields.items() if not name.startswith("_")}
    return str(value)


def describe_request(kwargs, betas) -> str:
    """The request exactly as it is sent, as readable JSON (--debug, --dry-run)."""
    shown = dict(kwargs)
    if betas:
        shown["betas"] = list(betas)
    return json.dumps(shown, indent=2, ensure_ascii=False, default=_plain)


def refusal_note(stop_details, fallbacks_requested=False) -> str:
    """What to tell the person when the model declined (stop_reason "refusal")."""
    def detail(name):
        if isinstance(stop_details, dict):
            return stop_details.get(name)
        return getattr(stop_details, name, None) if stop_details is not None else None

    note = "The model declined this request (stop_reason=refusal"
    if detail("category"):
        note += f", category={detail('category')}"
    note += ")"
    if detail("explanation"):
        note += f": {detail('explanation')}"
    note += "\n  Any partial output above is incomplete."
    if fallbacks_requested:
        note += " A server-side fallback was requested but no fallback model served it"
        if detail("recommended_model"):
            note += f"; the API suggests retrying directly on {detail('recommended_model')}"
        note += "."
    note += " Rephrase the task or use a different model."
    return note


def thinking_drop_reason(reasons) -> str:
    """Why the API dropped replayed thinking blocks, in plain words."""
    words = {
        "model_binding_mismatch": ("they were written by another model (the one this run "
                                   "started on before an upgrade, or a refusal fallback's), "
                                   "which this model cannot read"),
        "prefix_binding_mismatch": "earlier history changed since they were written",
    }
    return "; ".join(words.get(reason, f"reason: {reason}") for reason in reasons)


def _field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _error_text(error) -> str:
    return (getattr(error, "message", "") or str(error)).lower()


def _usage_dict(usage, served_model, fast_requested):
    if not usage:
        return None
    server_tools = _field(usage, "server_tool_use")
    return {
        "input_tokens": _field(usage, "input_tokens", 0) or 0,
        "output_tokens": _field(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": _field(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": _field(usage, "cache_read_input_tokens", 0) or 0,
        # The model and speed that really served the call: a refusal fallback
        # or a speed downgrade bills at different rates than the ones asked for.
        "model": served_model,
        "speed": _field(usage, "speed") or ("fast" if fast_requested else None),
        "web_search_requests": _field(server_tools, "web_search_requests", 0) or 0,
    }


def _stream_once(client, console, interrupts, kwargs, betas):
    """Send one request and show the reply as it streams.

    Returns (final_message, text, stop_details). Raises _Interrupted when the
    person pressed Ctrl-C or the run was told to stop.
    """
    text = ""
    stop_details = None
    stream = None
    extra = {"betas": betas} if betas else {}
    try:
        with interrupts.raisable():
            with client.beta.messages.stream(**kwargs, **extra) as stream:
                for event in stream:
                    kind = getattr(event, "type", "")
                    if kind == "content_block_start":
                        if _field(event.content_block, "type") == "thinking":
                            console.thinking_start()
                    elif kind == "content_block_delta":
                        delta_kind = _field(event.delta, "type")
                        if delta_kind == "thinking_delta":
                            console.thinking_delta(_field(event.delta, "thinking", ""))
                        elif delta_kind == "text_delta":
                            piece = _field(event.delta, "text", "")
                            text += piece
                            console.text(piece)
                    elif kind == "content_block_stop":
                        console.thinking_end()
                        block = getattr(event, "content_block", None)
                        if (_field(block, "type") == "server_tool_use"
                                and _field(block, "name") == "web_search"):
                            query = (_field(block, "input") or {}).get("query", "")
                            console.tool_line("web_search", query)
                    elif kind == "message_delta":
                        stop_details = _field(event.delta, "stop_details") or stop_details
                final = stream.get_final_message()
    except KeyboardInterrupt:
        console.thinking_end()
        snapshot = None
        try:
            snapshot = getattr(stream, "current_message_snapshot", None)
        except Exception:
            snapshot = None
        raise _Interrupted(text, _field(snapshot, "usage")) from None
    stop_details = _field(final, "stop_details") or stop_details
    return final, text, stop_details


def call_model(client, console, interrupts, *, model, system_prompt, messages, client_tools,
               web_search=True, thinking_mode="adaptive",
               thinking_budget=models.DEFAULT_THINKING_BUDGET, fast_mode=False,
               learned=None, max_retries=MAX_RETRIES, run_facts="") -> CallResult:
    """One call to the model, with the retry ladder.

    `messages` is trimmed in place if the context overflows. Raises when the
    call cannot be made to succeed.
    """
    learned = learned if learned is not None else Learned()
    stripped_thinking = False
    standard_speed = False

    def request():
        return build_request(
            model=model, system_prompt=system_prompt, messages=messages,
            client_tools=client_tools, web_search=web_search, thinking_mode=thinking_mode,
            thinking_budget=thinking_budget, fast_mode=fast_mode, learned=learned,
            standard_speed=standard_speed, run_facts=run_facts)

    def interrupted_result(text="", usage=None, fast=False):
        content = [{"type": "text", "text": text}] if text else []
        counted = _usage_dict(usage, model, fast)
        if counted and text:
            # The stream was cut before its final count arrived. What had
            # streamed was still generated and billed, so estimate it.
            counted["output_tokens"] = max(counted["output_tokens"],
                                           history.estimate_content_tokens(text))
        return CallResult("end_turn", content, text, counted, interrupted=True)

    def pause(seconds, what, attempt):
        console.activity(f"{what} - retrying in {seconds}s (attempt {attempt + 1}/{max_retries})...")
        return interrupts.wait(seconds)

    for attempt in range(max_retries):
        # Rebuilt for every attempt: the rungs below change what is sent
        # (a learned-off feature, a trimmed history).
        kwargs, betas, info = request()
        last_attempt = attempt >= max_retries - 1
        try:
            final, text, stop_details = _stream_once(client, console, interrupts, kwargs, betas)
            break
        except _Interrupted as stop:
            return interrupted_result(stop.text, stop.usage, info["fast"])

        except anthropic.RateLimitError as error:
            message = _error_text(error)
            # Fast mode has its own rate limit. A limit of zero means this key
            # has no fast mode at all; anything else is a busy moment.
            if "fast mode" in message and info["fast"]:
                if "limit of 0" in message:
                    learned.unsupported.add("speed")
                    console.warn("Fast mode is not enabled for this API key on this model "
                                 "(its fast-mode rate limit is 0). Running at standard speed "
                                 "and standard rates from here on.")
                else:
                    standard_speed = True
                    console.warn("Fast mode is rate-limited right now. This call runs at "
                                 "standard speed and bills standard rates.")
                continue
            if last_attempt:
                raise
            if pause(rate_limit_backoff(attempt), "Rate limited", attempt):
                return interrupted_result()

        except anthropic.BadRequestError as error:
            message = _error_text(error)
            if ("speed" in message or "fast-mode" in message) and info["fast"]:
                learned.unsupported.add("speed")
                console.warn("Fast mode is not available here (this model has none, or this "
                             "API key has no access to it). Retrying at standard speed; this "
                             "run bills at standard rates.")
                continue
            # A replayed thinking block whose earlier history has changed. The
            # drop_block setting normally has the API drop such blocks; this is
            # the fallback when that setting is not available. It must come
            # before the block_binding rung, because this error names that
            # setting as its remedy.
            if "signature" in message and "thinking" in message and not stripped_thinking:
                stripped_thinking = True
                removed = history.strip_thinking_blocks(messages)
                if removed:
                    console.warn(f"The API rejected {removed} replayed thinking block(s): "
                                 "earlier history changed since they were produced. Retrying "
                                 "without them; the model continues without that reasoning.")
                    continue
            if info["fallbacks"] and "fallback" in message:
                learned.unsupported.add("fallbacks")
                console.activity("Server-side refusal fallbacks are not available on this "
                                 "API key - retrying without them...")
                continue
            if info["block_binding"] and ("block_binding" in message
                                          or "thinking-binding" in message):
                learned.unsupported.add("block_binding")
                console.activity("Thinking-binding controls are not available on this API "
                                 "key - retrying without them...")
                continue
            if (web_search and "server_tools_20260209" not in learned.unsupported
                    and ("programmatic tool calling" in message
                         or "web_search_20260209" in message)):
                learned.unsupported.add("server_tools_20260209")
                console.activity(f"{model} does not take the current web search tool - "
                                 "retrying with the older variant...")
                continue
            real_cap = history.parse_output_cap(message)
            if real_cap and real_cap < kwargs.get("max_tokens", 0):
                learned.output_caps[model] = real_cap
                console.activity(f"{model} takes at most {real_cap:,} output tokens per "
                                 "call - retrying at that ceiling...")
                continue
            # The history no longer fits the context window. Resending it
            # cannot work, so drop the oldest rounds and try again.
            if "prompt is too long" in message or ("too long" in message and "maximum" in message):
                reported, maximum = history.parse_overflow_counts(message)
                removed = history.trim_history_for_context(messages, reported, maximum)
                if removed > 0:
                    console.warn(f"Context exceeded the model's limit: dropped the {removed} "
                                 "oldest message(s) and retried. Earlier history is no longer "
                                 "in context.")
                    continue
                console.warn(f"Context window exceeded on {model}: even the most recent "
                             "exchanges alone are larger than this model can hold. Use a "
                             "1M-context model or split the task into smaller parts.")
                raise RuntimeError(
                    f"Context window exceeded on {model} - nothing left to trim") from None
            raise

        except anthropic.APIStatusError as error:
            status = getattr(error, "status_code", None)
            if status == 413:
                # The request body is too large in bytes, not tokens.
                removed = history.trim_history_for_context(messages)
                if removed > 0:
                    console.warn("The request grew past the API's size limit (HTTP 413): "
                                 f"dropped the {removed} oldest message(s) and retried. "
                                 "Earlier history is no longer in context.")
                    continue
                raise RuntimeError(
                    f"Request too large on {model} (HTTP 413) - nothing left to remove") from None
            if status == 529 and not last_attempt:
                if pause(server_error_backoff(attempt), "API overloaded", attempt):
                    return interrupted_result()
            else:
                raise

        except anthropic.APIConnectionError as error:
            # The request never reached the API, or the stream broke. The SDK
            # has already retried quickly; wait longer and send it again.
            if last_attempt:
                raise
            detail = (getattr(error, "message", "") or str(error) or "Connection error").strip()
            if pause(connection_error_backoff(attempt), detail, attempt):
                return interrupted_result()
    else:
        raise RuntimeError(f"The API call did not succeed after {max_retries} attempts")

    # With the binding beta on, the response lists the replayed thinking
    # blocks the API dropped before the model saw them.
    dropped = None
    transformations = _field(final, "input_transformations") or []
    if transformations:
        reasons = sorted({str(_field(entry, "reason") or "unknown") for entry in transformations})
        dropped = (len(transformations), tuple(reasons))

    # A refusal fallback: another model produced this message.
    served_model = _field(final, "model") or model
    usage = _field(final, "usage")
    iterations = _field(usage, "iterations") or []
    fallback_ran = any(_field(entry, "type") == "fallback_message" for entry in iterations)
    content = history.strip_pre_fallback_blocks(list(_field(final, "content") or []))
    stop_reason = _field(final, "stop_reason")
    if fallback_ran and stop_reason != "refusal":
        console.warn(f"{model} declined this request (safety classifier). It was served by "
                     f"{served_model} through a server-side fallback; this call bills at "
                     f"{served_model} rates.")
    if stop_reason == "refusal":
        console.warn(refusal_note(stop_details, fallbacks_requested=info["fallbacks"]))

    return CallResult(stop_reason, content, text, _usage_dict(usage, served_model, info["fast"]),
                      dropped_thinking=dropped)
