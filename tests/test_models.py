"""Tests for robot.models: the model tables and the capability rules.

Everything under test is a pure function of a model id, so there is no
network, no API key and no file written here.
"""

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

from robot import models

FULL = ["off", "adaptive", "low", "medium", "high", "xhigh", "max"]
ALWAYS_ON = ["adaptive", "low", "medium", "high", "xhigh", "max"]
NO_XHIGH = ["off", "adaptive", "low", "medium", "high", "max"]
PLAIN = ["off", "adaptive", "low", "medium", "high"]

# model: (thinking is always on, kind of thinking control, valid modes)
CAPABILITIES = {
    # Fable and Mythos are matched by prefix, so every release is always on.
    "claude-fable-5-2": (True, "adaptive", ALWAYS_ON),
    "claude-mythos-5-2": (True, "adaptive", ALWAYS_ON),
    "claude-fable-5-1": (True, "adaptive", ALWAYS_ON),
    "claude-mythos-5-1": (True, "adaptive", ALWAYS_ON),
    "claude-fable-5": (True, "adaptive", ALWAYS_ON),
    "claude-mythos-5": (True, "adaptive", ALWAYS_ON),
    "claude-opus-5": (False, "adaptive", FULL),
    # Opus joins the always-on models at 5.5. A dated 5.5 snapshot rides
    # along; a dated Opus 5 snapshot (its date in the minor slot) does not.
    "claude-opus-5-5": (True, "adaptive", ALWAYS_ON),
    "claude-opus-5-5-20260921": (True, "adaptive", ALWAYS_ON),
    "claude-opus-5-20260724": (False, "adaptive", FULL),
    "claude-opus-6": (True, "adaptive", ALWAYS_ON),
    "claude-opus-4-8": (False, "adaptive", FULL),
    "claude-opus-4-7": (False, "adaptive", FULL),
    "claude-opus-4-6": (False, "adaptive", NO_XHIGH),
    "claude-opus-4-5": (False, "manual", PLAIN),
    "claude-sonnet-5-5": (False, "adaptive", FULL),
    "claude-sonnet-5": (False, "adaptive", FULL),
    "claude-sonnet-5-20260601": (False, "adaptive", FULL),
    "claude-sonnet-4-6": (False, "adaptive", NO_XHIGH),
    "claude-sonnet-4-6-20260101": (False, "adaptive", NO_XHIGH),
    "claude-sonnet-4-5": (False, "manual", PLAIN),
    "claude-haiku-4-5": (False, "manual", PLAIN),
    "claude-haiku-4-5-20251001": (False, "manual", PLAIN),
    # Haiku 5.5 is the first adaptive Haiku. It keeps its off switch.
    "claude-haiku-5-5": (False, "adaptive", FULL),
    "claude-haiku-5-5-20261007": (False, "adaptive", FULL),
    "claude-haiku-6": (False, "adaptive", FULL),
    # No thinking control this program knows of: only "off" is valid.
    "claude-opus-3": (False, None, ["off"]),
    "totally-unknown-xyz": (False, None, ["off"]),
}

# model: does it think when a request says nothing about thinking?
THINKS_BY_DEFAULT = {
    "claude-fable-5-2": True,
    "claude-mythos-5-2": True,
    "claude-fable-5-1": True,
    "claude-mythos-5-1": True,
    "claude-fable-5": True,
    "claude-mythos-5": True,
    "claude-opus-5": True,
    "claude-opus-5-5": True,
    "claude-sonnet-5-5": True,
    "claude-sonnet-5": True,
    "claude-sonnet-5-20260601": True,
    "claude-sonnet-4-6": False,
    "claude-sonnet-4-5": False,
    "claude-opus-4-8": False,
    "claude-haiku-4-5": False,
    "claude-haiku-5-5": True,
    "claude-haiku-5-5-20261007": True,
}

FAST_CAPABLE = {
    "claude-opus-5-5": True,
    "claude-opus-5": True,
    "claude-opus-4-8": True,
    "claude-opus-5-20260724": True,   # a dated Opus 5: the date is not a minor
    "claude-fable-5-2": True,
    "claude-mythos-5-2": True,
    "claude-fable-5-3": True,
    "claude-fable-6": True,
    "claude-mythos-6-0": True,
    "claude-opus-4-7": False,
    "claude-opus-4-6": False,
    "claude-opus-4-20250514": False,  # the dated 4.0 id, not a "4.<date>"
    "claude-sonnet-5": False,
    "claude-sonnet-5-5": False,
    "claude-fable-5-1": False,
    "claude-fable-5": False,
    "claude-mythos-5-1": False,
    "claude-mythos-5": False,
    "claude-haiku-4-5": False,
    "claude-haiku-5-5": False,
    "totally-unknown-xyz": False,
}

BINDING = {"prefix_mismatch_behavior": "drop_block"}
NEW_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
BASIC_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def rates(input_, output, cache_write, cache_read):
    """Per-token rates from USD-per-million figures."""
    return {"input": input_ / 1_000_000, "output": output / 1_000_000,
            "cache_write": cache_write / 1_000_000, "cache_read": cache_read / 1_000_000}


class ParseVersionTests(unittest.TestCase):
    def test_major_and_minor(self):
        cases = {
            ("claude-opus-4-8", ("claude-opus-",)): (4, 8),
            ("claude-sonnet-5", ("claude-sonnet-",)): (5, 0),          # no minor: 0
            ("claude-sonnet-4-6-20260101", ("claude-sonnet-",)): (4, 6),
            ("claude-opus-5-5-20260921", ("claude-opus-",)): (5, 5),
            ("claude-haiku-4-5-20251001", ("claude-haiku-",)): (4, 5),
            # A dated id with no minor of its own carries the date there.
            ("claude-sonnet-5-20260601", ("claude-sonnet-",)): (5, 20260601),
            ("claude-opus-5-preview", ("claude-opus-",)): (5, 0),     # not a number: 0
            ("claude-sonnet-4-6", ("claude-opus-", "claude-sonnet-")): (4, 6),
        }
        for (model, prefixes), expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(models.parse_major_minor(model, prefixes), expected)

    def test_no_family_or_no_major_is_none(self):
        parse = models.parse_major_minor
        self.assertIsNone(parse("claude-haiku-5-5", ("claude-opus-", "claude-sonnet-")))
        self.assertIsNone(parse("claude-opus-latest", ("claude-opus-",)))
        self.assertIsNone(parse("claude-opus-", ("claude-opus-",)))
        self.assertIsNone(parse("claude-opus-4-8", ()))
        self.assertIsNone(parse("", ("claude-opus-",)))
        self.assertIsNone(parse(None, ("claude-opus-",)))

    def test_only_the_first_matching_prefix_is_tried(self):
        # "claude-" matches first and has no number after it, so the more
        # specific prefix behind it is never reached.
        self.assertIsNone(models.parse_major_minor("claude-opus-4-8", ("claude-", "claude-opus-")))

    def test_a_bare_string_prefix_is_one_prefix(self):
        self.assertEqual(models.parse_major_minor("claude-opus-4-8", "claude-opus-"), (4, 8))


class ThinkingRulesTests(unittest.TestCase):
    def test_capability_matrix(self):
        for model, (always_on, support, modes) in CAPABILITIES.items():
            with self.subTest(model=model):
                self.assertIs(models.is_always_on_thinking(model), always_on)
                self.assertEqual(models.thinking_support(model), support)
                self.assertEqual(models.mode_values(model), modes)

    def test_thinking_on_by_default(self):
        for model, expected in THINKS_BY_DEFAULT.items():
            with self.subTest(model=model):
                self.assertIs(models.thinking_on_by_default(model), expected)

    def test_every_always_on_model_thinks_by_default_and_has_no_off(self):
        for model, (always_on, _support, modes) in CAPABILITIES.items():
            if always_on:
                with self.subTest(model=model):
                    self.assertTrue(models.thinking_on_by_default(model))
                    self.assertNotIn("off", modes)

    def test_thinking_kind_per_haiku_generation(self):
        # Haiku 4.5 thinks against a budget; a budget request is an error on 5.5.
        self.assertEqual(models.thinking_support("claude-haiku-4-5"), "manual")
        self.assertEqual(models.thinking_support("claude-haiku-4-5-20251001"), "manual")
        self.assertEqual(models.thinking_support("claude-haiku-5-5"), "adaptive")
        self.assertEqual(models.thinking_support("claude-haiku-5-5-20261007"), "adaptive")

    def test_haiku_5_and_later(self):
        for model in ("claude-haiku-5-5", "claude-haiku-5-5-20261007", "claude-haiku-5",
                      "claude-haiku-6"):
            self.assertIs(models.is_haiku_5(model), True, model)
        for model in ("claude-haiku-4-5", "claude-haiku-4-5-20251001", "claude-sonnet-5-5",
                      "claude-opus-5-5", "", None):
            self.assertIs(models.is_haiku_5(model), False, model)

    def test_sonnet_5_5_and_later(self):
        for model in ("claude-sonnet-5-5", "claude-sonnet-5-5-20260928", "claude-sonnet-5-6",
                      "claude-sonnet-6", "claude-sonnet-6-0"):
            self.assertIs(models.is_sonnet_55(model), True, model)
        for model in ("claude-sonnet-5", "claude-sonnet-5-20260601",   # a date, not a minor
                      "claude-sonnet-4-6", "claude-sonnet-4-5-20250929",
                      "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1", "", None):
            self.assertIs(models.is_sonnet_55(model), False, model)

    def test_sonnet_5_5_keeps_off_and_the_whole_ladder(self):
        # It can stop extended thinking, only with a different request shape.
        self.assertEqual(models.mode_values("claude-sonnet-5-5"), FULL)
        self.assertTrue(models.thinking_on_by_default("claude-sonnet-5-5"))
        self.assertFalse(models.is_always_on_thinking("claude-sonnet-5-5"))

    def test_a_missing_model_has_no_capabilities(self):
        for model in ("", None):
            with self.subTest(model=model):
                self.assertIsNone(models.thinking_support(model))
                self.assertFalse(models.is_always_on_thinking(model))
                self.assertFalse(models.thinking_on_by_default(model))
                self.assertFalse(models.supports_fast_mode(model))
                self.assertEqual(models.mode_values(model), ["off"])


class FastModeTests(unittest.TestCase):
    def test_matrix(self):
        for model, expected in FAST_CAPABLE.items():
            with self.subTest(model=model):
                self.assertIs(models.supports_fast_mode(model), expected)

    def test_every_fast_capable_listed_model_has_a_fast_price(self):
        for model in models.FALLBACK_MODELS:
            if models.supports_fast_mode(model):
                with self.subTest(model=model):
                    self.assertIsNotNone(models.get_pricing(model, speed="fast"))


class ModeTests(unittest.TestCase):
    def test_modes_are_drawn_from_the_one_list_in_its_order(self):
        for model in CAPABILITIES:
            with self.subTest(model=model):
                values = models.mode_values(model)
                self.assertEqual(values, [m for m in models.THINKING_MODES if m in values])

    def test_each_call_returns_a_new_list(self):
        models.mode_values("claude-sonnet-5").clear()
        self.assertEqual(models.mode_values("claude-sonnet-5"), FULL)

    def test_coercion_rules(self):
        coerce = models.coerce_mode
        ladder = "claude-opus-4-6"        # off, adaptive, low, medium, high, max
        always_on = "claude-fable-5-1"    # no off
        self.assertEqual(coerce(ladder, "none"), "off")           # another provider's off
        self.assertEqual(coerce(always_on, "none"), "adaptive")
        self.assertEqual(coerce(always_on, "off"), "adaptive")
        self.assertEqual(coerce(ladder, "minimal"), "low")
        self.assertEqual(coerce(ladder, "xhigh"), "high")         # above this ladder
        self.assertEqual(coerce(ladder, "medium"), "medium")      # present: unchanged
        self.assertEqual(coerce(always_on, "minimal"), "low")
        self.assertEqual(coerce(ladder, "turbo"), "high")         # an unknown word

    def test_coercion_ignores_letter_case_and_padding(self):
        self.assertEqual(models.coerce_mode("claude-fable-5-2", "Max"), "max")
        self.assertEqual(models.coerce_mode("claude-sonnet-5", " OFF "), "off")
        self.assertEqual(models.coerce_mode("claude-opus-5-5", "None"), "adaptive")

    def test_no_mode_at_all_means_off(self):
        for missing in ("", "   ", None):
            with self.subTest(mode=missing):
                self.assertEqual(models.coerce_mode("claude-sonnet-5", missing), "off")
                self.assertEqual(models.coerce_mode("claude-opus-5-5", missing), "adaptive")

    def test_a_budget_model_keeps_on_and_off_apart(self):
        for model in ("claude-haiku-4-5-20251001", "claude-opus-4-5"):
            with self.subTest(model=model):
                self.assertEqual(models.coerce_mode(model, "off"), "off")
                self.assertEqual(models.coerce_mode(model, "low"), "low")
                self.assertEqual(models.coerce_mode(model, "max"), "high")
                self.assertEqual(models.coerce_mode(model, "xhigh"), "high")

    def test_a_model_without_thinking_control_is_always_off(self):
        for mode in models.THINKING_MODES + ("none", "minimal", "", "turbo"):
            with self.subTest(mode=mode):
                self.assertEqual(models.coerce_mode("claude-opus-3", mode), "off")

    def test_the_result_is_always_valid_and_valid_modes_are_kept(self):
        for model in CAPABILITIES:
            values = models.mode_values(model)
            for mode in values:
                with self.subTest(model=model, mode=mode):
                    self.assertEqual(models.coerce_mode(model, mode), mode)
            for mode in models.THINKING_MODES + ("none", "minimal", "", "turbo", None):
                with self.subTest(model=model, mode=mode):
                    self.assertIn(models.coerce_mode(model, mode), values)


class LegacyModeTests(unittest.TestCase):
    def test_enabled_plus_effort_is_the_mode(self):
        legacy = models.mode_from_legacy
        self.assertEqual(legacy({"thinking_enabled": True, "thinking_effort": "low"}), "low")
        self.assertEqual(legacy({"thinking_enabled": True, "thinking_effort": "max"}), "max")
        self.assertEqual(legacy({"thinking_enabled": True}), "high")   # the default effort
        self.assertEqual(legacy({"thinking_enabled": False, "thinking_effort": "high"}), "off")

    def test_a_stored_mode_wins(self):
        legacy = models.mode_from_legacy
        self.assertEqual(legacy({"thinking_mode": "adaptive", "thinking_enabled": True,
                                 "thinking_effort": "high"}), "adaptive")
        self.assertEqual(legacy({"thinking_mode": "Xhigh", "thinking_enabled": False}), "xhigh")
        self.assertEqual(legacy({"thinking_mode": "off", "thinking_enabled": True,
                                 "thinking_effort": "high"}), "off")

    def test_an_empty_mode_is_no_mode(self):
        entry = {"thinking_mode": "", "thinking_enabled": True, "thinking_effort": "medium"}
        self.assertEqual(models.mode_from_legacy(entry), "medium")

    def test_nothing_about_thinking_means_off(self):
        for entry in ({}, {"text": "do it"}, None, "low", []):
            with self.subTest(entry=entry):
                self.assertEqual(models.mode_from_legacy(entry), "off")

    def test_another_providers_off_survives_until_it_is_coerced(self):
        mode = models.mode_from_legacy({"thinking_mode": "None"})
        self.assertEqual(mode, "none")
        self.assertEqual(models.coerce_mode("claude-sonnet-5", mode), "off")


class OutputCapTests(unittest.TestCase):
    def test_current_models_take_128k_and_the_4_5_generation_64k(self):
        for model in ("claude-fable-5-2", "claude-mythos-5-2", "claude-fable-5-1",
                      "claude-mythos-5-1", "claude-fable-5", "claude-mythos-5",
                      "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
                      "claude-sonnet-5", "claude-haiku-5-5", "claude-opus-4-8",
                      "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"):
            self.assertEqual(models.output_cap_for(model), 128000, model)
        for model in ("claude-haiku-4-5-20251001", "claude-opus-4-5-20251101",
                      "claude-sonnet-4-5-20250929"):
            self.assertEqual(models.output_cap_for(model), 64000, model)

    def test_a_dated_snapshot_rides_with_its_family(self):
        self.assertEqual(models.output_cap_for("claude-fable-5-1-20260828"), 128000)
        self.assertEqual(models.output_cap_for("claude-haiku-5-5-20261007"), 128000)

    def test_the_longest_prefix_wins_whatever_the_table_order(self):
        with mock.patch.object(models, "MAX_OUTPUT_TOKENS",
                               [("claude-x", 1000), ("claude-x-9", 2000)]):
            self.assertEqual(models.output_cap_for("claude-x-9-2027"), 2000)
            self.assertEqual(models.output_cap_for("claude-x-1"), 1000)
        with mock.patch.object(models, "MAX_OUTPUT_TOKENS",
                               [("claude-x-9", 2000), ("claude-x", 1000)]):
            self.assertEqual(models.output_cap_for("claude-x-9-2027"), 2000)

    def test_an_id_no_row_names_gets_the_default(self):
        for model in ("claude-zeta-9", "", None):
            self.assertEqual(models.output_cap_for(model), models.MAX_OUTPUT_DEFAULT, model)
        self.assertEqual(models.MAX_OUTPUT_DEFAULT, 128000)

    def test_every_row_is_a_claude_prefix_with_a_positive_ceiling(self):
        self.assertIsInstance(models.MAX_OUTPUT_TOKENS, list)
        for prefix, cap in models.MAX_OUTPUT_TOKENS:
            self.assertTrue(prefix.startswith("claude-"), prefix)
            self.assertIsInstance(cap, int)
            self.assertGreater(cap, 0)


class ListingTests(unittest.TestCase):
    def test_retired_and_retiring_ids_are_dropped_and_order_is_kept(self):
        listing = ["claude-fable-5-1", "claude-haiku-4-5-20251001",
                   "claude-3-opus-20240229", "claude-sonnet-5"]
        self.assertEqual(models.filter_listing(listing),
                         ["claude-fable-5-1", "claude-haiku-4-5-20251001", "claude-sonnet-5"])

    def test_sonnet_4_5_is_hidden_while_opus_and_haiku_4_5_stay(self):
        self.assertIn("claude-sonnet-4-5", models.DEPRECATED_MODEL_PREFIXES)
        listing = ["claude-sonnet-5-5", "claude-sonnet-4-5-20250929",
                   "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001"]
        self.assertEqual(models.filter_listing(listing),
                         ["claude-sonnet-5-5", "claude-opus-4-5-20251101",
                          "claude-haiku-4-5-20251001"])

    def test_each_kind_of_retired_id(self):
        for retired in ("claude-opus-4-1-20250805", "claude-opus-4-0", "claude-opus-4-20250514",
                        "claude-sonnet-4-0", "claude-sonnet-4-20250514",
                        "claude-3-5-haiku-20241022", "claude-3-7-sonnet-20250219",
                        "claude-2.1", "claude-sonnet-4-5"):
            with self.subTest(model=retired):
                self.assertEqual(models.filter_listing([retired]), [])

    def test_current_ids_pass_through(self):
        current = ["claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
                   "claude-opus-4-5", "claude-haiku-4-5"] + models.FALLBACK_MODELS
        self.assertEqual(models.filter_listing(current), current)

    def test_the_input_is_not_changed_and_nothing_in_gives_nothing_out(self):
        listing = ["claude-3-opus-20240229", "claude-sonnet-5"]
        models.filter_listing(listing)
        self.assertEqual(listing, ["claude-3-opus-20240229", "claude-sonnet-5"])
        self.assertEqual(models.filter_listing([]), [])
        self.assertEqual(models.filter_listing(None), [])


class WebSearchToolTests(unittest.TestCase):
    def test_current_models_get_the_current_tool_without_betas(self):
        for model in ("claude-sonnet-5", "claude-opus-5-5", "claude-opus-5",
                      "claude-fable-5-1", "claude-fable-5-2", "claude-opus-4-5",
                      "claude-haiku-5-5", "claude-haiku-5-5-20261007"):
            with self.subTest(model=model):
                self.assertEqual(models.web_search_tool(model), (NEW_SEARCH, []))

    def test_haiku_before_5_gets_the_basic_tool(self):
        for model in ("claude-haiku-4-5", "claude-haiku-4-5-20251001"):
            with self.subTest(model=model):
                self.assertEqual(models.web_search_tool(model), (BASIC_SEARCH, []))

    def test_a_session_that_learned_the_current_tool_off_falls_back(self):
        self.assertEqual(
            models.web_search_tool("claude-sonnet-5", {"server_tools_20260209"}),
            (BASIC_SEARCH, []))
        # Other learned-off surfaces have nothing to do with the search tool.
        self.assertEqual(models.web_search_tool("claude-sonnet-5", {"speed", "fallbacks"}),
                         (NEW_SEARCH, []))
        self.assertEqual(models.web_search_tool("claude-sonnet-5", None), (NEW_SEARCH, []))

    def test_only_web_search_is_declared(self):
        for model in ("claude-opus-5-5", "claude-haiku-4-5"):
            tool, betas = models.web_search_tool(model)
            self.assertEqual(set(tool), {"type", "name", "max_uses"})
            self.assertEqual((tool["name"], tool["max_uses"]), ("web_search", 5))
            self.assertEqual(betas, [])

    def test_each_call_returns_new_objects(self):
        tool, betas = models.web_search_tool("claude-opus-5-5")
        tool["max_uses"] = 99
        betas.append("x")
        self.assertEqual(models.web_search_tool("claude-opus-5-5"), (NEW_SEARCH, []))


class FableFeaturesTests(unittest.TestCase):
    def test_full_surface_on_fable(self):
        for model in ("claude-fable-5-1", "claude-fable-5-2"):
            with self.subTest(model=model):
                features = models.fable_features(model)
                self.assertEqual(features["betas"], [models.THINKING_BINDING_BETA,
                                                     models.SERVER_FALLBACK_BETA])
                self.assertEqual(features["block_binding"], BINDING)
                self.assertEqual(features["fallbacks"], "default")
                self.assertEqual(set(features), {"betas", "block_binding", "fallbacks"})

    def test_the_whole_always_on_class(self):
        for model in ("claude-fable-5", "claude-mythos-5", "claude-mythos-5-1",
                      "claude-fable-5-2", "claude-mythos-5-2", "claude-opus-5-5",
                      "claude-opus-5-5-20260921", "claude-opus-6"):
            with self.subTest(model=model):
                features = models.fable_features(model)
                self.assertEqual(features["block_binding"], BINDING)
                self.assertEqual(features["fallbacks"], "default")

    def test_none_outside_the_class(self):
        for model in ("claude-opus-5", "claude-opus-5-20260724", "claude-sonnet-5",
                      "claude-haiku-4-5", "claude-opus-4-8", "totally-unknown-xyz", "", None):
            with self.subTest(model=model):
                self.assertIsNone(models.fable_features(model))

    def test_haiku_5_5_gets_the_binding_but_no_fallbacks(self):
        for model in ("claude-haiku-5-5", "claude-haiku-5-5-20261007"):
            with self.subTest(model=model):
                features = models.fable_features(model)
                self.assertEqual(features["betas"], [models.THINKING_BINDING_BETA])
                self.assertEqual(features["block_binding"], BINDING)
                self.assertIsNone(features["fallbacks"])
        self.assertEqual(models.fable_features("claude-haiku-5-5", {"block_binding"}),
                         {"betas": [], "block_binding": None, "fallbacks": None})

    def test_sonnet_5_5_takes_both(self):
        for model in ("claude-sonnet-5-5", "claude-sonnet-5-5-20260928"):
            with self.subTest(model=model):
                features = models.fable_features(model)
                self.assertEqual(features["betas"], [models.THINKING_BINDING_BETA,
                                                     models.SERVER_FALLBACK_BETA])
                self.assertEqual(features["block_binding"], BINDING)
                self.assertEqual(features["fallbacks"], models.SERVER_FALLBACKS)
        self.assertEqual(
            models.fable_features("claude-sonnet-5-5", {"block_binding", "fallbacks"}),
            {"betas": [], "block_binding": None, "fallbacks": None})

    def test_learned_off_surfaces_are_dropped(self):
        features = models.fable_features("claude-fable-5-1", {"fallbacks"})
        self.assertEqual(features["betas"], [models.THINKING_BINDING_BETA])
        self.assertIsNone(features["fallbacks"])
        self.assertEqual(features["block_binding"], BINDING)
        features = models.fable_features("claude-fable-5-1", {"block_binding"})
        self.assertEqual(features["betas"], [models.SERVER_FALLBACK_BETA])
        self.assertIsNone(features["block_binding"])
        self.assertEqual(features["fallbacks"], "default")
        self.assertEqual(
            models.fable_features("claude-fable-5-1", {"block_binding", "fallbacks"}),
            {"betas": [], "block_binding": None, "fallbacks": None})

    def test_unrelated_or_missing_learned_off_entries_change_nothing(self):
        full = models.fable_features("claude-opus-5-5")
        self.assertEqual(models.fable_features("claude-opus-5-5", {"speed"}), full)
        self.assertEqual(models.fable_features("claude-opus-5-5", None), full)
        self.assertEqual(models.fable_features("claude-opus-5-5", []), full)

    def test_each_call_returns_a_new_dict(self):
        # The caller edits what it gets back; the constant must not change.
        first = models.fable_features("claude-fable-5-1")
        first["block_binding"]["prefix_mismatch_behavior"] = "x"
        first["betas"].clear()
        features = models.fable_features("claude-fable-5-1")
        self.assertEqual(features["block_binding"], BINDING)
        self.assertEqual(len(features["betas"]), 2)
        self.assertEqual(models.THINKING_BLOCK_BINDING, BINDING)


class PricingTests(unittest.TestCase):
    CASES = {
        "claude-opus-4-8": rates(5.00, 25.00, 6.25, 0.50),
        "claude-opus-4-7": rates(5.00, 25.00, 6.25, 0.50),
        "claude-opus-4-6": rates(5.00, 25.00, 6.25, 0.50),
        "claude-opus-4-5": rates(5.00, 25.00, 6.25, 0.50),
        "claude-sonnet-4-6": rates(3.00, 15.00, 3.75, 0.30),
        "claude-haiku-4-5": rates(1.00, 5.00, 1.25, 0.10),
        "claude-haiku-4-5-20251001": rates(1.00, 5.00, 1.25, 0.10),
        "claude-fable-5": rates(10.00, 50.00, 12.50, 1.00),
        "claude-mythos-5": rates(10.00, 50.00, 12.50, 1.00),
        # 5.2 is cheaper than 5.1 and must out-rank the "claude-fable-5" prefix.
        "claude-fable-5-2": rates(8.00, 40.00, 10.00, 0.20),
        "claude-mythos-5-2": rates(8.00, 40.00, 10.00, 0.20),
        # 5.1 has Fable 5's rates except for its cache reads.
        "claude-fable-5-1": rates(10.00, 50.00, 12.50, 0.25),
        "claude-mythos-5-1": rates(10.00, 50.00, 12.50, 0.25),
        "claude-fable-5-1-20260828": rates(10.00, 50.00, 12.50, 0.25),
        "claude-sonnet-5": rates(2.00, 10.00, 2.50, 0.20),
        "claude-sonnet-5-20260601": rates(2.00, 10.00, 2.50, 0.20),
        "claude-sonnet-5-5": rates(2.00, 10.00, 2.50, 0.10),
        "claude-opus-5": rates(5.00, 25.00, 6.25, 0.50),
        "claude-opus-5-20260724": rates(5.00, 25.00, 6.25, 0.50),
        # Cheaper than Opus 5: it must not be priced by the "claude-opus-5" row.
        "claude-opus-5-5": rates(4.00, 20.00, 5.00, 0.20),
        "claude-opus-5-5-20260921": rates(4.00, 20.00, 5.00, 0.20),
        "claude-haiku-5-5": rates(0.10, 0.50, 0.125, 0.01),
        # A later Haiku 5 has no row: unpriced, not priced by a family prefix.
        "claude-haiku-5-6": None,
        # Retired and retiring generations have no row.
        "claude-3-haiku-20240307": None,
        "claude-opus-4-1": None,
        "claude-sonnet-4-5": None,
        "claude-sonnet-4-5-20250929": None,
        "claude-opus-6": None,
        "totally-unknown-xyz": None,
        "": None,
        None: None,
    }

    def test_pricing(self):
        for model, expected in self.CASES.items():
            with self.subTest(model=model):
                self.assertEqual(models.get_pricing(model), expected)

    def test_rates_are_per_token(self):
        priced = models.get_pricing("claude-opus-4-8")
        self.assertEqual(priced, {"input": 5e-06, "output": 2.5e-05,
                                  "cache_write": 6.25e-06, "cache_read": 5e-07})
        self.assertEqual(list(priced), ["input", "output", "cache_write", "cache_read"])

    def test_each_call_returns_a_new_dict(self):
        models.get_pricing("claude-opus-5-5")["input"] = 0
        self.assertEqual(models.get_pricing("claude-opus-5-5"), rates(4.00, 20.00, 5.00, 0.20))

    def test_a_row_also_prices_a_later_release_that_starts_with_it(self):
        # Longest-prefix matching cuts both ways: until a new release has a
        # row of its own, the row of the release it extends prices it.
        self.assertEqual(models.get_pricing("claude-opus-5-7"),
                         models.get_pricing("claude-opus-5"))
        self.assertEqual(models.get_pricing("claude-fable-5-3"),
                         models.get_pricing("claude-fable-5"))

    def test_every_listed_model_is_priced(self):
        for model in models.FALLBACK_MODELS + [models.DEFAULT_MODEL,
                                               models.UPGRADE_DEFAULT_TARGET["model"]]:
            with self.subTest(model=model):
                self.assertIsNotNone(models.get_pricing(model))
                self.assertIsNone(models.unpriced_model_warning(model))


class FastPricingTests(unittest.TestCase):
    def test_every_fast_row_is_exactly_double_its_standard_row(self):
        for model, fast_row in models.FAST_PRICING.items():
            with self.subTest(model=model):
                self.assertEqual(fast_row, tuple(2 * p for p in models.PRICING[model]))

    def test_fast_lookup(self):
        priced = models.get_pricing("claude-opus-5-5", speed="fast")
        expected = {"input": 8e-06, "output": 40e-06, "cache_write": 10e-06,
                    "cache_read": 0.40e-06}
        self.assertEqual(set(priced), set(expected))
        for key, value in expected.items():
            self.assertAlmostEqual(priced[key], value, places=12, msg=key)

    def test_fable_5_2_has_a_fast_row_and_5_1_has_none(self):
        self.assertEqual(models.FAST_PRICING["claude-fable-5-2"], (16.00, 80.00, 20.00, 0.40))
        self.assertEqual(models.FAST_PRICING["claude-mythos-5-2"], (16.00, 80.00, 20.00, 0.40))
        self.assertEqual(models.get_pricing("claude-fable-5-2", speed="fast"),
                         rates(16.00, 80.00, 20.00, 0.40))
        self.assertNotIn("claude-fable-5-1", models.FAST_PRICING)
        self.assertIsNone(models.get_pricing("claude-fable-5-1", speed="fast"))

    def test_the_other_fast_rows(self):
        self.assertEqual(models.get_pricing("claude-opus-5", speed="fast"),
                         rates(10.00, 50.00, 12.50, 1.00))
        self.assertEqual(models.get_pricing("claude-opus-5-20260724", speed="fast"),
                         rates(10.00, 50.00, 12.50, 1.00))
        self.assertEqual(models.get_pricing("claude-opus-4-8", speed="fast"),
                         rates(10.00, 50.00, 12.50, 1.00))

    def test_standard_speed_and_none_use_the_standard_table(self):
        standard = models.get_pricing("claude-opus-5-5")
        for speed in (None, "standard", ""):
            with self.subTest(speed=speed):
                self.assertEqual(models.get_pricing("claude-opus-5-5", speed=speed), standard)

    def test_a_fast_miss_is_unpriced_never_the_standard_row(self):
        # Pricing a fast call from the standard table would halve its cost.
        for model in ("claude-sonnet-5", "claude-opus-6", "claude-opus-4-7", "claude-haiku-5-5"):
            with self.subTest(model=model):
                self.assertIsNone(models.get_pricing(model, speed="fast"))


class LongContextTests(unittest.TestCase):
    """Haiku 5.5 bills the whole request on a second rate card once its prompt
    (input plus both cache buckets) is over 100,000 tokens."""
    BASE = rates(0.10, 0.50, 0.125, 0.01)
    LONG = dict(rates(0.50, 2.50, 0.625, 0.05), long_context=100_000)

    def test_base_card_without_a_prompt_size_or_at_the_line(self):
        self.assertEqual(models.get_pricing("claude-haiku-5-5"), self.BASE)
        for size in (None, 0, 99_999, 100_000):
            with self.subTest(prompt_tokens=size):
                self.assertEqual(
                    models.get_pricing("claude-haiku-5-5", prompt_tokens=size), self.BASE)

    def test_long_card_above_the_line(self):
        for model in ("claude-haiku-5-5", "claude-haiku-5-5-20261007"):
            for size in (100_001, 400_000):
                with self.subTest(model=model, prompt_tokens=size):
                    self.assertEqual(models.get_pricing(model, prompt_tokens=size), self.LONG)

    def test_models_without_a_second_card_ignore_the_prompt_size(self):
        for model in ("claude-opus-5-5", "claude-haiku-4-5", "claude-fable-5-2"):
            with self.subTest(model=model):
                big = models.get_pricing(model, prompt_tokens=900_000)
                self.assertEqual(big, models.get_pricing(model))
                self.assertNotIn("long_context", big)

    def test_the_fast_lookup_ignores_the_prompt_size(self):
        self.assertEqual(
            models.get_pricing("claude-opus-5-5", speed="fast", prompt_tokens=900_000),
            models.get_pricing("claude-opus-5-5", speed="fast"))

    def test_an_unpriced_model_stays_unpriced_at_any_size(self):
        self.assertIsNone(models.get_pricing("claude-haiku-5-6", prompt_tokens=900_000))

    def test_a_model_with_its_own_row_does_not_inherit_its_familys_card(self):
        own_row = {**models.PRICING, "claude-haiku-5-5-mini": (0.05, 0.25, 0.0625, 0.005)}
        with mock.patch.object(models, "PRICING", own_row):
            priced = models.get_pricing("claude-haiku-5-5-mini", prompt_tokens=900_000)
        self.assertEqual(priced, rates(0.05, 0.25, 0.0625, 0.005))

    def test_the_card_table(self):
        self.assertEqual(models.LONG_CONTEXT_PRICING,
                         {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.625, 0.05))})
        for prefix in models.LONG_CONTEXT_PRICING:
            self.assertIn(prefix, models.PRICING)   # a card needs its base row


class PricingWarningTests(unittest.TestCase):
    def test_an_unpriced_model_warns(self):
        note = models.unpriced_model_warning("claude-future-99")
        self.assertIn("claude-future-99", note)
        self.assertIn("Anthropic pricing table", note)
        self.assertIn("NOT be written to the API cost log", note)
        self.assertIsNotNone(models.unpriced_model_warning("claude-unknown-tier"))
        self.assertIsNotNone(models.unpriced_model_warning("claude-sonnet-4-5"))

    def test_priced_models_are_silent(self):
        for model in ("claude-fable-5-1", "claude-fable-5-2", "claude-opus-5-5",
                      "claude-haiku-4-5-20251001"):
            with self.subTest(model=model):
                self.assertIsNone(models.unpriced_model_warning(model))

    def test_a_fast_run_needs_a_row_in_the_fast_table(self):
        self.assertIsNone(models.unpriced_model_warning("claude-opus-5-5", fast=True))
        self.assertIsNone(models.unpriced_model_warning("claude-fable-5-2", fast=True))
        note = models.unpriced_model_warning("claude-opus-6", fast=True)
        self.assertIn("claude-opus-6", note)
        self.assertIn("FAST mode", note)
        self.assertIn("FAST_PRICING", note)
        # An ordinary standard row does not help a call that is served fast.
        self.assertIsNone(models.unpriced_model_warning("claude-sonnet-5"))
        self.assertIn("FAST mode", models.unpriced_model_warning("claude-sonnet-5", fast=True))

    def test_no_model_is_priced_by_a_family_row_today(self):
        for model in models.FALLBACK_MODELS + ["claude-fable-5-1", "claude-haiku-4-5",
                                               "claude-future-99", "", None]:
            with self.subTest(model=model):
                self.assertIsNone(models.generic_pricing_warning(model))

    def test_a_model_priced_by_a_marked_family_row_warns(self):
        with mock.patch.object(models, "_GENERIC_PRICING_PREFIXES", ("claude-haiku-4",)):
            note = models.generic_pricing_warning("claude-haiku-4-5")
            self.assertIn("claude-haiku-4-5", note)
            self.assertIn("'claude-haiku-4'", note)
            self.assertTrue(note.isascii())
            # A model with a row of its own, and an unpriced one, stay silent.
            self.assertIsNone(models.generic_pricing_warning("claude-haiku-5-5"))
            self.assertIsNone(models.generic_pricing_warning("claude-future-99"))

    def test_warnings_are_plain_ascii(self):
        for note in (models.unpriced_model_warning("claude-future-99"),
                     models.unpriced_model_warning("claude-future-99", fast=True)):
            self.assertTrue(note.isascii(), note)
            self.assertNotIn("\n", note)


class LabelTests(unittest.TestCase):
    def test_an_effort_or_adaptive_reads_as_itself(self):
        for mode, label in (("low", "Low"), ("medium", "Medium"), ("high", "High"),
                            ("xhigh", "Xhigh"), ("max", "Max"), ("adaptive", "Adaptive"),
                            ("Max", "Max")):
            self.assertEqual(models.mode_label("claude-opus-5-5", mode), label)

    def test_off_reads_as_what_the_request_carries(self):
        for mode in ("off", "none", "", None):
            with self.subTest(mode=mode):
                self.assertEqual(models.mode_label("claude-sonnet-5", mode), "Off")
                # Always on: a stored "off" is sent as adaptive.
                self.assertEqual(models.mode_label("claude-fable-5-2", mode), "Adaptive")
                self.assertEqual(models.mode_label("claude-opus-5-5", mode), "Adaptive")

    def test_a_budget_model_reads_as_its_budget(self):
        haiku = "claude-haiku-4-5-20251001"
        self.assertEqual(models.mode_label(haiku, "high"), "8K")
        self.assertEqual(models.mode_label(haiku, "adaptive"), "8K")
        self.assertEqual(models.mode_label(haiku, "off"), "Off")
        with mock.patch.object(models, "DEFAULT_THINKING_BUDGET", 5000):
            self.assertEqual(models.mode_label("claude-opus-4-5", "high"), "5000tok")

    def test_a_run_with_its_own_budget_reads_as_that_budget(self):
        haiku = "claude-haiku-4-5-20251001"
        for budget, label in ((1024, "1K"), (4096, "4K"), (8192, "8K"), (16384, "16K"),
                              (32768, "32K"), (5000, "5000tok")):
            with self.subTest(budget=budget):
                self.assertEqual(models.mode_label(haiku, "high", thinking_budget=budget), label)
        self.assertEqual(models.mode_label(haiku, "high", thinking_budget=None), "8K")
        self.assertEqual(models.mode_label(haiku, "off", thinking_budget=16384), "Off")
        # Only a budget model has a budget to name.
        self.assertEqual(models.mode_label("claude-opus-5-5", "low", thinking_budget=16384),
                         "Low")

    def test_a_model_without_thinking_control_is_off(self):
        self.assertEqual(models.mode_label("claude-opus-3", "high"), "Off")

    def test_the_label_of_a_valid_mode_is_the_mode_capitalised(self):
        for model, (_always_on, support, modes) in CAPABILITIES.items():
            if support == "adaptive":
                for mode in modes:
                    with self.subTest(model=model, mode=mode):
                        self.assertEqual(models.mode_label(model, mode), mode.capitalize())


class ParamSummaryTests(unittest.TestCase):
    def test_the_mode_alone(self):
        self.assertEqual(models.param_summary("claude-opus-5-5", "low"), ["mode=Low"])
        self.assertEqual(models.param_summary("claude-sonnet-5", "adaptive"), ["mode=Adaptive"])
        self.assertEqual(models.param_summary("claude-sonnet-5", "off"), ["mode=Off"])
        self.assertEqual(models.param_summary("claude-opus-4-6", "off"), ["mode=Off"])

    def test_a_stale_off_on_an_always_on_model_is_adaptive(self):
        self.assertEqual(models.param_summary("claude-fable-5-1", "off"), ["mode=Adaptive"])

    def test_speed_fast_is_reported(self):
        self.assertEqual(models.param_summary("claude-opus-5-5", "adaptive", fast_active=True),
                         ["mode=Adaptive", "speed=fast"])
        self.assertEqual(models.param_summary("claude-fable-5-2", "max", fast_active=True),
                         ["mode=Max", "speed=fast"])

    def test_no_speed_part_when_fast_is_off_or_the_model_has_no_fast_mode(self):
        self.assertEqual(models.param_summary("claude-opus-5-5", "adaptive"), ["mode=Adaptive"])
        self.assertEqual(models.param_summary("claude-opus-5-5", "adaptive", fast_active=False),
                         ["mode=Adaptive"])
        for model in ("claude-sonnet-5", "claude-fable-5-1", "claude-haiku-5-5"):
            with self.subTest(model=model):
                self.assertEqual(models.param_summary(model, "adaptive", fast_active=True),
                                 ["mode=Adaptive"])

    def test_an_upgraded_run_names_the_model_and_call_it_left(self):
        self.assertEqual(
            models.param_summary("claude-fable-5-1", "max", upgraded_from="claude-sonnet-5",
                                 upgraded_call=12),
            ["mode=Max", "upgraded-from=claude-sonnet-5@call12"])
        self.assertEqual(models.param_summary("claude-fable-5-1", "max"), ["mode=Max"])
        self.assertEqual(
            models.param_summary("claude-fable-5-1", "max", upgraded_from="claude-sonnet-5"),
            ["mode=Max", "upgraded-from=claude-sonnet-5@call0"])

    def test_all_three_parts_in_order(self):
        self.assertEqual(
            models.param_summary("claude-fable-5-2", "max", True, "claude-sonnet-5", 12),
            ["mode=Max", "speed=fast", "upgraded-from=claude-sonnet-5@call12"])

    def test_a_budget_model_logs_its_budget(self):
        self.assertEqual(models.param_summary("claude-haiku-4-5-20251001", "high"),
                         ["thinking=8K"])
        self.assertEqual(models.param_summary("claude-haiku-4-5-20251001", "off"),
                         ["thinking=off"])
        self.assertEqual(
            models.param_summary("claude-haiku-4-5-20251001", "high", fast_active=True),
            ["thinking=8K"])
        self.assertEqual(
            models.param_summary("claude-haiku-4-5-20251001", "high", thinking_budget=32768),
            ["thinking=32K"])
        self.assertEqual(
            models.param_summary("claude-haiku-4-5-20251001", "off", thinking_budget=32768),
            ["thinking=off"])
        self.assertEqual(
            models.param_summary("claude-opus-5-5", "low", thinking_budget=32768),
            ["mode=Low"])

    def test_a_model_without_thinking_control_logs_no_thinking_part(self):
        self.assertEqual(models.param_summary("claude-opus-3", "high"), [])
        self.assertEqual(
            models.param_summary("claude-opus-3", "high", upgraded_from="claude-sonnet-5",
                                 upgraded_call=3),
            ["upgraded-from=claude-sonnet-5@call3"])

    def test_no_part_can_split_the_log_field(self):
        for model in CAPABILITIES:
            for mode in models.THINKING_MODES + ("none", ""):
                parts = models.param_summary(model, mode, True, "claude-sonnet-5", 7)
                for part in parts:
                    with self.subTest(model=model, mode=mode, part=part):
                        self.assertTrue(part.isascii())
                        self.assertFalse(set(part) & set(" ,;\n"))


class UpgradeLevelTests(unittest.TestCase):
    def test_a_saved_level_lands_on_what_the_model_offers(self):
        level = models.upgrade_level_for
        self.assertEqual(level("claude-sonnet-5", "max"), "Max")
        self.assertEqual(level("claude-opus-5-5", "High"), "High")
        self.assertEqual(level("claude-opus-5-5", " high "), "High")
        self.assertEqual(level("claude-sonnet-5", "Off"), "Off")
        self.assertEqual(level("claude-sonnet-5", "adaptive"), "Adaptive")

    def test_the_levels_of_an_effort_model_are_its_thinking_modes(self):
        for model, (_always_on, support, modes) in CAPABILITIES.items():
            if support == "adaptive":
                for mode in modes:
                    with self.subTest(model=model, mode=mode):
                        self.assertEqual(models.upgrade_level_for(model, mode),
                                         mode.capitalize())
                        self.assertEqual(models.upgrade_params_for(model, mode),
                                         {"thinking_mode": mode})

    def test_a_level_the_model_lacks_becomes_its_strongest(self):
        level = models.upgrade_level_for
        self.assertEqual(level("claude-fable-5-1", "Off"), "Max")     # always on: no Off
        self.assertEqual(level("claude-fable-5-1", ""), "Max")
        self.assertEqual(level("claude-fable-5-1", None), "Max")
        self.assertEqual(level("claude-opus-4-6", "Xhigh"), "Max")    # no Xhigh on 4.6
        self.assertEqual(level("claude-sonnet-5", "turbo"), "Max")

    def test_a_model_without_thinking_control_has_no_level(self):
        self.assertEqual(models.upgrade_level_for("claude-opus-3", "Max"), "")
        self.assertEqual(models.upgrade_level_for("", "Max"), "")

    def test_a_budget_model_is_offered_off_and_on(self):
        # An upgrade sets the mode only, so it cannot choose a budget.
        level = models.upgrade_level_for
        self.assertEqual(level("claude-haiku-4-5-20251001", "Off"), "Off")
        self.assertEqual(level("claude-haiku-4-5-20251001", "on"), "On")
        self.assertEqual(level("claude-haiku-4-5-20251001", "16K"), "On")
        self.assertEqual(level("claude-haiku-4-5-20251001", "Max"), "On")
        self.assertEqual(level("claude-opus-4-5", ""), "On")

    def test_the_default_target_runs_at_its_own_level(self):
        target = models.UPGRADE_DEFAULT_TARGET
        self.assertEqual(target, {"model": "claude-fable-5-2", "level": "Max", "fast": False})
        self.assertEqual(models.upgrade_level_for(target["model"], target["level"]), "Max")
        self.assertEqual(models.upgrade_params_for(target["model"], target["level"]),
                         {"thinking_mode": "max"})


class UpgradeParamTests(unittest.TestCase):
    def test_a_rung_is_the_mode(self):
        self.assertEqual(models.upgrade_params_for("claude-fable-5-1", "Max"),
                         {"thinking_mode": "max"})
        self.assertEqual(models.upgrade_params_for("claude-opus-5-5", "xhigh"),
                         {"thinking_mode": "xhigh"})

    def test_adaptive_and_off(self):
        self.assertEqual(models.upgrade_params_for("claude-sonnet-5", "Adaptive"),
                         {"thinking_mode": "adaptive"})
        self.assertEqual(models.upgrade_params_for("claude-sonnet-5", "Off"),
                         {"thinking_mode": "off"})

    def test_a_level_the_model_lacks_runs_at_its_strongest(self):
        self.assertEqual(models.upgrade_params_for("claude-fable-5-2", "Off"),
                         {"thinking_mode": "max"})
        self.assertEqual(models.upgrade_params_for("claude-opus-4-6", "Xhigh"),
                         {"thinking_mode": "max"})

    def test_a_model_with_no_thinking_control_runs_with_thinking_off(self):
        self.assertEqual(models.upgrade_params_for("claude-opus-3", "Max"),
                         {"thinking_mode": "off"})

    def test_a_budget_model_is_on_or_off(self):
        haiku = "claude-haiku-4-5-20251001"
        for level in ("On", "16K", "Max", ""):
            with self.subTest(level=level):
                on = models.upgrade_params_for(haiku, level)
                self.assertEqual(set(on), {"thinking_mode"})
                self.assertNotEqual(on["thinking_mode"], "off")
                # Thinking on, at the budget the run already has.
                self.assertEqual(models.mode_label(haiku, on["thinking_mode"]), "8K")
        self.assertEqual(models.upgrade_params_for(haiku, "Off"), {"thinking_mode": "off"})

    def test_the_mode_is_always_valid_for_the_model(self):
        for model in CAPABILITIES:
            for level in ("Max", "Xhigh", "High", "Low", "Adaptive", "Off", "On", "8K", "", None):
                with self.subTest(model=model, level=level):
                    params = models.upgrade_params_for(model, level)
                    self.assertEqual(list(params), ["thinking_mode"])
                    self.assertIn(params["thinking_mode"], models.mode_values(model))


class UpgradeTargetTests(unittest.TestCase):
    def test_what_is_not_a_target(self):
        sanitize = models.sanitize_upgrade_target
        self.assertIsNone(sanitize(None))
        self.assertIsNone(sanitize("claude-fable-5-1"))
        self.assertIsNone(sanitize(["claude-fable-5-1"]))
        self.assertIsNone(sanitize({"provider": "Bedrock", "model": "x"}))   # unknown provider

    def test_a_target_saved_for_another_provider_does_not_apply(self):
        self.assertIsNone(models.sanitize_upgrade_target(
            {"provider": "OpenAI", "model": "gpt-6-astra", "level": "Max"}))

    def test_model_and_level_are_trimmed(self):
        self.assertEqual(
            models.sanitize_upgrade_target({"model": " claude-opus-5-5 ", "level": " High "}),
            {"model": "claude-opus-5-5", "level": "High", "fast": False})
        self.assertEqual(
            models.sanitize_upgrade_target({"provider": "Anthropic", "model": "claude-opus-5-5",
                                            "level": "High", "fast": False}),
            {"model": "claude-opus-5-5", "level": "High", "fast": False})

    def test_an_empty_model_is_an_explicit_no_upgrade(self):
        nothing = {"model": "", "level": "", "fast": False}
        sanitize = models.sanitize_upgrade_target
        self.assertEqual(sanitize({"provider": "Anthropic", "model": "", "level": "Max",
                                   "fast": True}), nothing)
        self.assertEqual(sanitize({"model": "   "}), nothing)
        self.assertEqual(sanitize({"model": 5, "level": "Max"}), nothing)
        self.assertEqual(sanitize({}), nothing)

    def test_fast_is_a_bool_and_needs_a_model(self):
        sanitize = models.sanitize_upgrade_target
        fable = "claude-fable-5-2"
        self.assertIs(sanitize({"model": fable, "level": "Max", "fast": True})["fast"], True)
        self.assertIs(sanitize({"model": fable, "level": "Max", "fast": 1})["fast"], True)
        self.assertIs(sanitize({"model": fable, "fast": "yes"})["fast"], True)
        self.assertIs(sanitize({"model": fable, "level": "Max"})["fast"], False)   # no field
        self.assertIs(sanitize({"model": fable, "fast": 0})["fast"], False)
        self.assertIs(sanitize({"model": "", "fast": True})["fast"], False)

    def test_a_level_that_is_not_text_is_dropped(self):
        self.assertEqual(models.sanitize_upgrade_target({"model": "claude-opus-5-5", "level": 3}),
                         {"model": "claude-opus-5-5", "level": "", "fast": False})

    def test_the_result_is_a_new_dict_with_three_keys(self):
        raw = {"provider": "Anthropic", "model": "claude-opus-5-5", "level": "High",
               "fast": True, "extra": 1}
        clean = models.sanitize_upgrade_target(raw)
        self.assertEqual(clean, {"model": "claude-opus-5-5", "level": "High", "fast": True})
        self.assertIsNot(clean, raw)
        self.assertEqual(raw["extra"], 1)


class TableTests(unittest.TestCase):
    def test_the_fallback_list_in_order(self):
        self.assertEqual(models.FALLBACK_MODELS, [
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
        ])

    def test_the_default_model(self):
        self.assertEqual(models.DEFAULT_MODEL, "claude-opus-5-5")
        self.assertIn(models.DEFAULT_MODEL, models.FALLBACK_MODELS)

    def test_every_listed_model_can_run(self):
        for model in models.FALLBACK_MODELS:
            with self.subTest(model=model):
                self.assertFalse(model.startswith(models.DEPRECATED_MODEL_PREFIXES))
                self.assertIsNotNone(models.thinking_support(model))
                self.assertTrue(any(model.startswith(p) for p, _cap in models.MAX_OUTPUT_TOKENS))

    def test_the_deprecated_prefixes(self):
        self.assertEqual(models.DEPRECATED_MODEL_PREFIXES, (
            "claude-sonnet-4-5", "claude-opus-4-1", "claude-opus-4-0", "claude-opus-4-20",
            "claude-sonnet-4-0", "claude-sonnet-4-20", "claude-3", "claude-2"))

    def test_the_output_table(self):
        self.assertEqual(models.MAX_OUTPUT_TOKENS, [
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
        ])

    def test_request_values(self):
        self.assertEqual(models.THINKING_BINDING_BETA, "thinking-binding-controls-2026-08-01")
        self.assertEqual(models.THINKING_BLOCK_BINDING, BINDING)
        self.assertEqual(models.SERVER_FALLBACK_BETA, "server-side-fallback-2026-07-01")
        self.assertEqual(models.SERVER_FALLBACKS, "default")
        self.assertEqual(models.FAST_MODE_BETA, "fast-mode-2026-02-01")
        self.assertEqual(models.THINKING_MODES,
                         ("off", "adaptive", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual(models.DEFAULT_THINKING_BUDGET, 8192)

    def test_the_web_search_fee_is_ten_dollars_per_thousand(self):
        self.assertAlmostEqual(models.WEB_SEARCH_FEE, 0.01)

    def test_the_price_table_rows(self):
        self.assertEqual(set(models.PRICING), {
            "claude-fable-5-2", "claude-mythos-5-2", "claude-fable-5-1", "claude-mythos-5-1",
            "claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-opus-5-5",
            "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-opus-4-5",
            "claude-sonnet-5", "claude-sonnet-5-5", "claude-sonnet-4-6", "claude-haiku-5-5",
            "claude-haiku-4"})
        self.assertEqual(set(models.FAST_PRICING), {
            "claude-fable-5-2", "claude-mythos-5-2", "claude-opus-5-5", "claude-opus-5",
            "claude-opus-4-8"})

    def test_every_price_row_has_four_sane_rates(self):
        cards = (list(models.PRICING.items()) + list(models.FAST_PRICING.items())
                 + [(p, card) for p, (_line, card) in models.LONG_CONTEXT_PRICING.items()])
        for prefix, row in cards:
            with self.subTest(prefix=prefix, row=row):
                self.assertIsInstance(row, tuple)
                self.assertEqual(len(row), 4)
                input_, output, cache_write, cache_read = row
                self.assertGreater(output, input_)
                self.assertGreater(input_, cache_read)
                self.assertGreater(cache_read, 0)
                # A 5-minute cache write costs 1.25 times the input rate.
                self.assertAlmostEqual(cache_write, 1.25 * input_)

    def test_fable_5_2_comes_before_5_1_in_the_fallback_list(self):
        listed = models.FALLBACK_MODELS
        self.assertLess(listed.index("claude-fable-5-2"), listed.index("claude-fable-5-1"))


class ModuleTests(unittest.TestCase):
    TREE = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))

    def test_every_text_in_the_module_is_plain_ascii(self):
        # The robot's console cannot show other characters, and the texts
        # this module returns are printed there.
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertTrue(node.value.isascii(), node.value)

    def test_it_imports_nothing_outside_the_standard_library(self):
        imported = set()
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertFalse(imported & {"anthropic", "tkinter", "myagent"})
        self.assertLessEqual(imported, set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
