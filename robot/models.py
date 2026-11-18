"""Model tables and capability rules for the Anthropic models the robot can run.

Every function here is a pure function of a model id: nothing is read from the
network, the disk or the running program. Ids are matched by family prefix and
version number, not by exact name, so a dated snapshot
(claude-haiku-5-5-20261007) or a later minor release follows its family's rules
without a new entry.

When Anthropic releases a model, the places to check are FALLBACK_MODELS,
MAX_OUTPUT_TOKENS, the three price tables and the version floors in the
capability functions.
"""

DEFAULT_MODEL = "claude-opus-5-5"

# Offered when the live model listing cannot be fetched.
FALLBACK_MODELS: list[str] = [
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-opus-4-8",
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-5-5",
    "claude-haiku-4-5-20251001",
]

# Ids starting with one of these are retired or retiring; filter_listing()
# hides them. "-4-20" matches the dated 4.0 ids (claude-opus-4-20250514)
# without touching 4.5 and later.
DEPRECATED_MODEL_PREFIXES: tuple[str, ...] = (
    "claude-sonnet-4-5",
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-opus-4-20",
    "claude-sonnet-4-0",
    "claude-sonnet-4-20",
    "claude-3",
    "claude-2",
)

# The most output tokens each family accepts, which is what a request sends as
# max_tokens. Adaptive thinking has no budget of its own, so a lower cap can
# end a reply while the model is still reasoning. Longest matching prefix wins.
MAX_OUTPUT_TOKENS: list[tuple[str, int]] = [
    ("claude-fable-5", 128000),
    ("claude-mythos-5", 128000),
    ("claude-opus-5", 128000),
    ("claude-sonnet-5", 128000),
    ("claude-haiku-5", 128000),
    ("claude-opus-4-8", 128000),
    ("claude-opus-4-7", 128000),
    ("claude-opus-4-6", 128000),
    ("claude-sonnet-4-6", 128000),
    ("claude-opus-4-5", 64000),
    ("claude-sonnet-4-5", 64000),
    ("claude-haiku-4-5", 64000),
]
# For an id no row names. If the guess is too high, the API's error says what
# the real ceiling is.
MAX_OUTPUT_DEFAULT = 128000

# Beta header and request value that make the API drop thinking blocks which no
# longer match the history before them (after a trim, say) instead of
# rejecting the whole request.
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
THINKING_BLOCK_BINDING = {"prefix_mismatch_behavior": "drop_block"}

# Beta header and request value that let the API re-run a request the model
# declined on another model, inside the same call.
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
SERVER_FALLBACKS = "default"

# Sent with every speed="fast" request. Only some models still need it, and
# the rest accept it, so one request shape serves them all.
FAST_MODE_BETA = "fast-mode-2026-02-01"

THINKING_MODES: tuple[str, ...] = (
    "off", "adaptive", "low", "medium", "high", "xhigh", "max",
)

# Thinking budget for the older models that take a token budget, not an effort.
DEFAULT_THINKING_BUDGET = 8192

# Thinking cannot be switched off on these families, nor on Opus from 5.5.
_ALWAYS_ON_PREFIXES = ("claude-fable-", "claude-mythos-")
_ALWAYS_ON_OPUS_MIN = (5, 5)

# The generation that thinks against a token budget.
_MANUAL_THINKING_PREFIXES = ("claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-5")

# How the cost log names a thinking budget.
_BUDGET_LABELS = {"1K": 1024, "4K": 4096, "8K": 8192, "16K": 16384, "32K": 32768}

# On a budget model every mode but "off" means the same thing: thinking on.
# This is the one an upgrade to such a model stores.
_BUDGET_ON_MODE = "high"

# Spellings of "no thinking": this program's, another provider's, and none set.
_OFF_MODES = ("off", "none", "")

# USD per million tokens: (input, output, 5-minute cache write, cache read).
# Longest matching prefix wins. A row therefore also prices any later id that
# starts with it (the claude-opus-5 row would price a claude-opus-5-7), so a
# new model whose rates differ needs a row of its own before it is run.
PRICING: dict[str, tuple] = {
    # Each Fable and Mythos release has its own row: 5.2 is cheaper than 5.1,
    # and 5.1 reads its cache for a quarter of what 5 does.
    "claude-fable-5-2": (8.00, 40.00, 10.00, 0.20),
    "claude-mythos-5-2": (8.00, 40.00, 10.00, 0.20),
    "claude-fable-5-1": (10.00, 50.00, 12.50, 0.25),
    "claude-mythos-5-1": (10.00, 50.00, 12.50, 0.25),
    "claude-fable-5": (10.00, 50.00, 12.50, 1.00),
    "claude-mythos-5": (10.00, 50.00, 12.50, 1.00),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    # Cheaper than Opus 5, so it must not fall through to the row above.
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-5": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    # Sonnet 5's rates, but cache reads cost half as much.
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    # For a prompt of up to 100,000 tokens; see LONG_CONTEXT_PRICING.
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    # Haiku 4.5, including its dated id.
    "claude-haiku-4": (1.00, 5.00, 1.25, 0.10),
}

# Rates for a call the API says it served at speed "fast": twice the standard
# row in every column. A model missing here is unpriced when served fast; it
# is never priced from the standard table at half the real rate.
FAST_PRICING: dict[str, tuple] = {
    "claude-fable-5-2": (16.00, 80.00, 20.00, 0.40),
    "claude-mythos-5-2": (16.00, 80.00, 20.00, 0.40),
    "claude-opus-5-5": (8.00, 40.00, 10.00, 0.40),
    "claude-opus-5": (10.00, 50.00, 12.50, 1.00),
    "claude-opus-4-8": (10.00, 50.00, 12.50, 1.00),
}

# A second rate card for long prompts: model -> (threshold in prompt tokens,
# rates). Once a request's whole prompt (input plus both cache buckets) is
# over the threshold, the whole request is billed on this card.
LONG_CONTEXT_PRICING: dict[str, tuple] = {
    "claude-haiku-5-5": (100_000, (0.50, 2.50, 0.625, 0.05)),
}

# Price rows marked as pricing a whole family rather than one model. A model
# priced by one gets a warning from generic_pricing_warning(). None are marked.
_GENERIC_PRICING_PREFIXES: tuple[str, ...] = ()

WEB_SEARCH_FEE = 10.00 / 1000  # USD per executed search, on top of the tokens

# Where upgrade_model moves a run when its instruction names no target.
UPGRADE_DEFAULT_TARGET = {"model": "claude-fable-5-2", "level": "Max", "fast": False}


def _model_id(model) -> str:
    """The id as a string; anything else (a missing model) reads as ""."""
    return model if isinstance(model, str) else ""


def _mode_name(mode) -> str:
    """A thinking mode in its stored form: lower case, no padding."""
    return mode.strip().lower() if isinstance(mode, str) else ""


def parse_major_minor(model: str, prefixes: tuple[str, ...]) -> tuple[int, int] | None:
    """Read (major, minor) from a claude-<family>-<major>[-<minor>] id.

    Only the first prefix the id starts with is tried. The result is None when
    no prefix matches or the major is not a number. A missing or non-numeric
    minor counts as 0. A dated snapshot with no minor of its own
    (claude-sonnet-5-20260601) has its date in the minor slot, which still
    compares as "at least 5.0"; rules that look at the minor itself read such
    a date as 0 (see _family_version).
    """
    model = _model_id(model)
    if isinstance(prefixes, str):
        prefixes = (prefixes,)  # a bare string would otherwise be read letter by letter
    for family in prefixes:
        if model.startswith(family):
            parts = model[len(family):].split("-")
            try:
                major = int(parts[0])
            except (ValueError, IndexError):
                return None
            try:
                minor = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                minor = 0
            return (major, minor)
    return None


def _family_version(model: str, prefixes: tuple[str, ...]) -> tuple[int, int] | None:
    """parse_major_minor, with a date in the minor slot read as minor 0."""
    version = parse_major_minor(model, prefixes)
    if version is None:
        return None
    major, minor = version
    return (major, 0 if minor >= 100 else minor)


def _reaches(model: str, *floors) -> bool:
    """True when the model is at or past one of the given versions.

    Each floor is (family prefixes, (major, minor)): the version at which a
    capability arrived in those families. The always-on models and Haiku from
    5 have every capability that is asked about this way.
    """
    if is_always_on_thinking(model) or is_haiku_5(model):
        return True
    for prefixes, floor in floors:
        version = parse_major_minor(model, prefixes)
        if version is not None and version >= floor:
            return True
    return False


def thinking_support(model: str) -> str | None:
    """How the model's thinking is controlled.

    "adaptive": by an effort level (Opus and Sonnet from 4.6, Haiku from 5,
    Fable, Mythos). "manual": by a token budget (the 4.5 generation). None:
    the model has no thinking control this program knows how to use.
    """
    model = _model_id(model)
    if _reaches(model, (("claude-opus-", "claude-sonnet-"), (4, 6))):
        return "adaptive"
    if model.startswith(_MANUAL_THINKING_PREFIXES):
        return "manual"
    return None


def is_always_on_thinking(model: str) -> bool:
    """True when the API refuses to switch the model's thinking off.

    These models have no "off" mode. A request must leave thinking adaptive,
    so a stored "off" is sent as "adaptive".
    """
    model = _model_id(model)
    if model.startswith(_ALWAYS_ON_PREFIXES):
        return True
    version = _family_version(model, ("claude-opus-",))
    return version is not None and version >= _ALWAYS_ON_OPUS_MIN


def thinking_on_by_default(model: str) -> bool:
    """True when the model thinks if a request says nothing about thinking.

    Opus, Sonnet and Haiku from 5, and the always-on models. For these "off"
    has to be sent explicitly: leaving the parameter out would let the model
    think, and bill for it, without anyone having asked.
    """
    return _reaches(_model_id(model), (("claude-opus-", "claude-sonnet-"), (5, 0)))


def is_sonnet_55(model: str) -> bool:
    """True for Sonnet 5.5 and later, which turn thinking off differently.

    They reject {"type": "disabled"}; their off switch is
    {"type": "between_tools"}.
    """
    version = _family_version(_model_id(model), ("claude-sonnet-",))
    return version is not None and version >= (5, 5)


def is_haiku_5(model: str) -> bool:
    """True for Haiku 5 and later, the first Haiku with adaptive thinking."""
    version = parse_major_minor(_model_id(model), ("claude-haiku-",))
    return version is not None and version >= (5, 0)


def supports_fast_mode(model: str) -> bool:
    """True when the model can be asked for speed="fast".

    Opus from 4.8, Fable and Mythos from 5.2. The API has the last word: a
    request it refuses is dealt with where the request is sent.
    """
    model = _model_id(model)
    for prefixes, floor in (
        (("claude-opus-",), (4, 8)),
        (("claude-fable-", "claude-mythos-"), (5, 2)),
    ):
        version = _family_version(model, prefixes)
        if version is not None:
            return version >= floor
    return False


def mode_values(model: str) -> list[str]:
    """The thinking modes that are valid for this model, weakest first.

    Always-on models have no "off"; "xhigh" and "max" are listed only where
    the API accepts them. A budget model gets the plain ladder, on which every
    mode but "off" means thinking on at DEFAULT_THINKING_BUDGET. A model with
    no thinking control has "off" alone.
    """
    model = _model_id(model)
    if thinking_support(model) is None:
        return ["off"]
    values = [] if is_always_on_thinking(model) else ["off"]
    values += ["adaptive", "low", "medium", "high"]
    if _reaches(model, (("claude-opus-",), (4, 7)), (("claude-sonnet-",), (5, 0))):
        values.append("xhigh")
    if _reaches(model, (("claude-opus-", "claude-sonnet-"), (4, 6))):
        values.append("max")
    return values


def _first_of(values: list[str], *wanted: str) -> str:
    """The first wanted mode the model has, else the model's strongest."""
    for mode in wanted:
        if mode in values:
            return mode
    return values[-1]


def coerce_mode(model: str, mode: str) -> str:
    """The nearest thinking mode this model accepts.

    A valid mode comes back unchanged. "off" (or another provider's "none", or
    no mode at all) stays off where the model has an off switch and becomes
    "adaptive" where it has none. "minimal" becomes "low". Anything else, such
    as "xhigh" on a model that stops at "high", becomes "high". A model with no
    thinking control has nothing but "off" to land on.
    """
    values = mode_values(model)
    current = _mode_name(mode)
    if current in values:
        return current
    if current in _OFF_MODES:
        return _first_of(values, "off", "adaptive")
    if current == "minimal":
        return _first_of(values, "low", "high")
    return _first_of(values, "high")


def mode_from_legacy(entry: dict) -> str:
    """The thinking mode a saved instruction entry asks for.

    Entries saved before thinking_mode existed only say whether thinking was
    on (thinking_enabled) and how hard (thinking_effort); the effort is then
    the mode. An entry that says nothing about thinking means off.
    """
    if not isinstance(entry, dict):
        return "off"
    mode = _mode_name(entry.get("thinking_mode"))
    if mode:
        return mode
    if entry.get("thinking_enabled"):
        return _mode_name(entry.get("thinking_effort")) or "high"
    return "off"


def output_cap_for(model: str) -> int:
    """The output ceiling to send as max_tokens for this model."""
    model = _model_id(model)
    best = None
    for prefix, cap in MAX_OUTPUT_TOKENS:
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, cap)
    return best[1] if best else MAX_OUTPUT_DEFAULT


def filter_listing(model_ids: list[str]) -> list[str]:
    """A live model listing without the retired and retiring ids.

    Hiding an id only keeps it from being offered. An instruction that names
    it can still run it for as long as the API serves it.
    """
    return [mid for mid in (model_ids or []) if not mid.startswith(DEPRECATED_MODEL_PREFIXES)]


def web_search_tool(model: str, unsupported=frozenset()) -> tuple[dict, list[str]]:
    """The web search declaration for this model, and the beta headers it needs.

    The current tool filters its results with code the model writes. Haiku
    before 5 cannot do that and takes the basic tool, as does a session that
    has seen the API reject the current one ("server_tools_20260209" in
    `unsupported`). Neither needs a beta header. max_uses caps the searches in
    one request, because each search is billed.
    """
    haiku = parse_major_minor(_model_id(model), ("claude-haiku-",))
    basic = (haiku is not None and haiku < (5, 0)) or (
        "server_tools_20260209" in (unsupported or ()))
    tool_type = "web_search_20250305" if basic else "web_search_20260209"
    return {"type": tool_type, "name": "web_search", "max_uses": 5}, []


def fable_features(model: str, unsupported=frozenset()) -> dict | None:
    """The two extra request surfaces of the newest models, or None.

    Returns {"betas", "block_binding", "fallbacks"}: the beta headers to add,
    the block_binding value to put inside an adaptive thinking parameter, and
    the fallbacks value to send. Always-on models and Sonnet from 5.5 take
    both; Haiku from 5 takes the binding only, as it has no fallback model.
    A surface named in `unsupported` ("block_binding", "fallbacks") was
    rejected by the API earlier in this session and is left out. The dict is
    new on every call, so the caller may change it.
    """
    model = _model_id(model)
    unsupported = unsupported or ()
    takes_both = is_always_on_thinking(model) or is_sonnet_55(model)
    if not (takes_both or is_haiku_5(model)):
        return None
    features = {"betas": [], "block_binding": None, "fallbacks": None}
    if "block_binding" not in unsupported:
        features["betas"].append(THINKING_BINDING_BETA)
        features["block_binding"] = dict(THINKING_BLOCK_BINDING)
    if takes_both and "fallbacks" not in unsupported:
        features["betas"].append(SERVER_FALLBACK_BETA)
        features["fallbacks"] = SERVER_FALLBACKS
    return features


def _price_row(model: str, table: dict) -> tuple:
    """(prefix, row) of the longest table prefix the id starts with, else (None, None)."""
    best_prefix, best_row = None, None
    for prefix, row in table.items():
        if model.startswith(prefix) and len(prefix) > len(best_prefix or ""):
            best_prefix, best_row = prefix, row
    return best_prefix, best_row


def _per_token(row: tuple) -> dict:
    """A table row (USD per million tokens) as USD per token."""
    return {
        "input": row[0] / 1_000_000,
        "output": row[1] / 1_000_000,
        "cache_write": row[2] / 1_000_000,
        "cache_read": row[3] / 1_000_000,
    }


def get_pricing(model: str, speed: str | None = None, prompt_tokens: int = 0) -> dict | None:
    """Per-token rates for one call, or None when the model has no price row.

    The keys are "input", "output", "cache_write" and "cache_read", in USD per
    token. `speed` is the speed the API says it served the call at: "fast" is
    priced from FAST_PRICING and nothing else. `prompt_tokens` is the call's
    whole prompt (input plus both cache buckets); when it is over the model's
    long-context threshold the second rate card is returned, with
    "long_context" set to that threshold.
    """
    model = _model_id(model)
    if speed == "fast":
        _prefix, row = _price_row(model, FAST_PRICING)
        return None if row is None else _per_token(row)
    prefix, row = _price_row(model, PRICING)
    if row is None:
        return None
    priced = _per_token(row)
    if prompt_tokens:
        # The card must belong to the very row that priced the model. A model
        # with a row of its own never inherits a card from its family.
        card_prefix, card = _price_row(model, LONG_CONTEXT_PRICING)
        if card is not None and card_prefix == prefix and prompt_tokens > card[0]:
            priced = _per_token(card[1])
            priced["long_context"] = card[0]
    return priced


def unpriced_model_warning(model: str, fast: bool = False) -> str | None:
    """A warning for the start of a run whose model cannot be priced, else None.

    With `fast` (the run will ask for fast mode) it is FAST_PRICING that must
    hold the row, because a call served fast is never priced from the
    standard table.
    """
    model = _model_id(model)
    if fast:
        _prefix, row = _price_row(model, FAST_PRICING)
        if row is not None:
            return None
        return (f"{model} will run in FAST mode but has no row in FAST_PRICING "
                f"(robot/models.py), so its calls cannot be priced: no cost will be "
                f"shown for this run and the run will NOT be written to the API cost "
                f"log (a $0.0000 line would claim it was free, and the standard row "
                f"would bill it at half the fast rate). Token counts are still shown "
                f"per call. Add the model's fast row.")
    _prefix, row = _price_row(model, PRICING)
    if row is not None:
        return None
    return (f"{model} has no row in the Anthropic pricing table (PRICING in "
            f"robot/models.py), so its calls cannot be priced: no cost will be shown "
            f"for this run and the run will NOT be written to the API cost log (a "
            f"$0.0000 line would claim it was free). Token counts are still shown "
            f"per call. Add the model's row.")


def generic_pricing_warning(model: str) -> str | None:
    """A warning when the model is priced by a family row, not its own, else None."""
    model = _model_id(model)
    prefix, _row = _price_row(model, PRICING)
    if prefix is None or prefix not in _GENERIC_PRICING_PREFIXES:
        return None
    return (f"{model} has no pricing entry of its own: it is priced by the generic "
            f"'{prefix}' fallback row, so its cost lines and cost-log rows may be "
            f"wrong. Add a {model} entry to PRICING in robot/models.py.")


def _budget_label(budget: int) -> str:
    """A thinking budget as the cost log names it: "8K", or "5000tok"."""
    for label, tokens in _BUDGET_LABELS.items():
        if tokens == budget:
            return label
    return f"{budget}tok"


def mode_label(model: str, thinking_mode: str, *, thinking_budget: int | None = None) -> str:
    """The thinking setting as the cost log names it: "Low", "Adaptive", "Off".

    The label says what the request carries, so "off" on an always-on model
    reads "Adaptive", and a budget model with thinking on reads as its budget
    ("8K"): `thinking_budget` when the run has one of its own, else
    DEFAULT_THINKING_BUDGET.
    """
    model = _model_id(model)
    mode = _mode_name(thinking_mode)
    off = mode in _OFF_MODES
    support = thinking_support(model)
    if support is None:
        return "Off"
    if support == "manual":
        return "Off" if off else _budget_label(thinking_budget or DEFAULT_THINKING_BUDGET)
    if off:
        return "Adaptive" if is_always_on_thinking(model) else "Off"
    return mode.capitalize()


def param_summary(model: str, thinking_mode: str, fast_active: bool = False,
                  upgraded_from: str | None = None, upgraded_call: int | None = None,
                  *, thinking_budget: int | None = None) -> list[str]:
    """The parts of the cost log's parameters field, in order.

    "mode=<label>", then "speed=fast" when the run asks for fast mode on a
    model that has it, then "upgraded-from=<model>@call<N>" when the run began
    on another model and left it after call N. A budget model logs
    "thinking=8K" or "thinking=off" in place of the mode (see mode_label for
    `thinking_budget`), and a model with no thinking control logs no thinking
    part. No part contains a space, a comma or a semicolon, so the joined
    field cannot be split in the wrong place.
    """
    model = _model_id(model)
    parts = []
    support = thinking_support(model)
    if support == "adaptive":
        parts.append(f"mode={mode_label(model, thinking_mode)}")
        # Fast mode doubles every rate, so the log has to say when it was on.
        if fast_active and supports_fast_mode(model):
            parts.append("speed=fast")
    elif support == "manual":
        label = mode_label(model, thinking_mode, thinking_budget=thinking_budget)
        parts.append("thinking=off" if label == "Off" else f"thinking={label}")
    if upgraded_from:
        parts.append(f"upgraded-from={upgraded_from}@call{upgraded_call or 0}")
    return parts


def _upgrade_levels(model: str) -> list[str]:
    """The thinking levels an upgrade can run this model at, weakest first."""
    support = thinking_support(model)
    if support == "adaptive":
        return [mode.capitalize() for mode in mode_values(model)]
    if support == "manual":
        # An upgrade sets the mode and nothing else, so it cannot pick a
        # budget: thinking is on, at whatever budget the run has, or off.
        return ["Off", "On"]
    return []


def upgrade_levels(model: str) -> list[str]:
    """The levels an upgrade to this model can be given, weakest first ("Low" ... "Max")."""
    return _upgrade_levels(_model_id(model))


def upgrade_level_for(model: str, level: str) -> str:
    """The level an upgrade to this model really runs at, as a label ("Max").

    That is the level asked for when the model offers it (in any letter
    case), else the model's strongest level. It is "" for a model with no
    thinking control.
    """
    values = _upgrade_levels(_model_id(model))
    if not values:
        return ""
    wanted = _mode_name(level)
    for value in values:
        if value.lower() == wanted:
            return value
    return values[-1]


def upgrade_params_for(model: str, level: str) -> dict:
    """The thinking setting a run takes on when it is upgraded to this model."""
    mode = upgrade_level_for(model, level).lower()
    if mode in _OFF_MODES:
        return {"thinking_mode": "off"}
    if mode not in THINKING_MODES:
        return {"thinking_mode": _BUDGET_ON_MODE}  # "on", a budget model's only other level
    return {"thinking_mode": mode}


def sanitize_upgrade_target(target) -> dict | None:
    """An instruction's upgrade_target as {"model", "level", "fast"}, or None.

    None means the instruction names no usable target (it is missing,
    malformed or was saved for another provider), so UPGRADE_DEFAULT_TARGET
    applies. A model of "" is a different answer: an explicit "never upgrade",
    which has no level and no speed.
    """
    if not isinstance(target, dict):
        return None
    if (target.get("provider") or "Anthropic") != "Anthropic":
        return None
    model = target.get("model")
    model = model.strip() if isinstance(model, str) else ""
    level = target.get("level")
    level = level.strip() if isinstance(level, str) and model else ""
    fast = bool(target.get("fast")) and bool(model)
    return {"model": model, "level": level, "fast": fast}
