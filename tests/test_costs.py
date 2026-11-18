"""Tests for robot/costs.py: the cost of each call, the per-run cost-log line
and its exact format, and the in-progress record that lets a killed run still
be logged.

Prices come from a small stand-in for models.get_pricing, so these tests do
not need robot/models.py. Everything is written inside temporary folders.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import robot
from robot import costs
from robot.costs import (RunCost, cost_line, current_boot_id, format_log_line, log_run,
                         process_is_robot, progress_clear, progress_fold_in, progress_path,
                         progress_write, split_field)

REPO_ROOT = Path(__file__).resolve().parents[1]
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
WARNING_SIGN = "\u26a0"
WHEN = datetime(2026, 3, 4, 5, 6, 7)

# USD per million tokens: (input, output, cache write, cache read).
_RATES = {
    "claude-fable-5-1": (10.00, 50.00, 12.50, 0.25),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}
_FAST_RATES = {"claude-opus-5-5": (8.00, 40.00, 10.00, 0.40)}
_LONG_PROMPT_RATES = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.625, 0.05))}
SEARCH_FEE = 0.01


def fake_pricing(model, speed=None, prompt_tokens=0):
    """Stands in for models.get_pricing: longest prefix wins, rates per token."""
    def longest(table):
        hits = [prefix for prefix in table if model.startswith(prefix)]
        return max(hits, key=len) if hits else None

    def per_token(row):
        names = ("input", "output", "cache_write", "cache_read")
        return {name: rate / 1_000_000 for name, rate in zip(names, row)}

    if speed == "fast":
        prefix = longest(_FAST_RATES)
        return per_token(_FAST_RATES[prefix]) if prefix else None
    prefix = longest(_RATES)
    if prefix is None:
        return None
    rates = per_token(_RATES[prefix])
    card = _LONG_PROMPT_RATES.get(prefix)
    if card and prompt_tokens > card[0]:
        rates = per_token(card[1])
        rates["long_context"] = card[0]
    return rates


def fake_models(pricing=fake_pricing, fee=SEARCH_FEE):
    """Put a stand-in robot.models in place for the lazy import to find."""
    module = types.ModuleType("robot.models")
    module.get_pricing = pricing
    module.WEB_SEARCH_FEE = fee
    return _ModulePatch(module)


class _ModulePatch:
    """Context manager: robot.models is `module`, however it gets imported."""

    def __init__(self, module):
        self._patches = [mock.patch.dict(sys.modules, {"robot.models": module}),
                         mock.patch.object(robot, "models", module, create=True)]

    def __enter__(self):
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc_info):
        for patch in reversed(self._patches):
            patch.stop()
        return False


def no_models():
    """Fail the test if the code under test reaches for robot.models."""
    return mock.patch.object(costs, "_models",
                             side_effect=AssertionError("robot.models was not needed here"))


def usage(tokens_in=1000, tokens_out=100, **more):
    """A usage dict as the API module builds it."""
    built = {"input_tokens": tokens_in, "output_tokens": tokens_out}
    built.update(more)
    return built


def run_calls(model, *usages, pricing=fake_pricing, run=None):
    """What the agent loop does for each call: count it, then account for it."""
    run = run or RunCost()
    updates = []
    for one in usages:
        run.calls += 1
        updates.append(run.add_call(one, model, pricing))
    return run, updates


class TempDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.log = self.dir / "APICostLog_test.txt"
        self.runs = self.dir / "runs"
        self.runs.mkdir()

    def lines(self, log=None):
        log = log or self.log
        if not log.exists():
            return []
        return log.read_text(encoding="utf-8").splitlines()

    def fields(self, log=None):
        lines = self.lines(log)
        self.assertEqual(len(lines), 1, lines)
        return lines[0].split(";")

    def record_names(self):
        return sorted(os.listdir(self.runs))


# -- the line shown after each call ------------------------------------------


class CostLineTests(unittest.TestCase):
    @staticmethod
    def _update(call_cost, total_cost, cache_write=0, cache_read=0):
        return {"call_cost": call_cost, "total_cost": total_cost, "input_tokens": 12345,
                "output_tokens": 678, "cache_write_tokens": cache_write,
                "cache_read_tokens": cache_read}

    def test_priced_lines(self):
        self.assertEqual(cost_line(self._update(0.0012, 0.0034)),
                         "  $0.0012 this call  |  $0.0034 total  (in:12,345  out:678)\n")
        self.assertEqual(
            cost_line(self._update(0.0012, 1.2345, cache_write=40, cache_read=7)),
            "  $0.0012 this call  |  $1.23 total  "
            "(in:12,345  out:678  cache_write:40  cache_read:7)\n")

    def test_unpriced_line_shows_the_tokens(self):
        self.assertEqual(
            cost_line(self._update(None, None, cache_read=7)),
            "  unpriced this call  |  no pricing row  (in:12,345  out:678  cache_read:7)\n")

    def test_total_moves_to_two_decimals_at_one_cent(self):
        self.assertIn("$0.0099 total", cost_line(self._update(0.001, 0.0099)))
        self.assertIn("$0.01 total", cost_line(self._update(0.001, 0.01)))
        self.assertIn("$12.35 total", cost_line(self._update(0.001, 12.345678)))

    def test_only_the_cache_buckets_in_use_are_shown(self):
        self.assertIn("(in:12,345  out:678  cache_write:40)",
                      cost_line(self._update(0.1, 0.1, cache_write=40)))
        self.assertIn("(in:12,345  out:678  cache_read:7)",
                      cost_line(self._update(0.1, 0.1, cache_read=7)))

    def test_a_call_without_usage_gives_no_line(self):
        self.assertEqual(cost_line({}), "")
        self.assertEqual(cost_line(None), "")

    def test_lines_are_plain_ascii(self):
        for update in (self._update(0.5, 2.0, 1, 1), self._update(None, None)):
            self.assertTrue(cost_line(update).isascii())

    def test_the_update_from_add_call_is_what_cost_line_takes(self):
        run, [(update, _)] = run_calls("claude-sonnet-5", usage(1000, 100))
        self.assertEqual(cost_line(update),
                         "  $0.0030 this call  |  $0.0030 total  (in:1,000  out:100)\n")


# -- accounting for one call --------------------------------------------------


class AddCallTests(unittest.TestCase):
    def test_a_new_run_has_spent_nothing(self):
        run = RunCost()
        self.assertEqual(run.total_cost, 0.0)
        self.assertFalse(run.had_usage)
        self.assertEqual(run.calls, 0)
        self.assertEqual(run.tokens(), (0, 0, 0, 0))
        self.assertEqual(run.per_model, {})
        self.assertIsNot(RunCost().per_model, run.per_model)   # each run has its own

    def test_tokens_add_up_in_their_four_buckets(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        run, _ = run_calls("claude-sonnet-5", cached, dict(cached))
        self.assertEqual(run.tokens(), (2000, 200, 80, 14))
        self.assertEqual((run.input_tokens, run.output_tokens,
                          run.cache_write_tokens, run.cache_read_tokens), (2000, 200, 80, 14))
        self.assertTrue(run.had_usage)

    def test_add_call_does_not_count_calls(self):
        run = RunCost()
        run.add_call(usage(), "claude-sonnet-5", fake_pricing)
        self.assertEqual(run.calls, 0)   # the loop counts a call when it starts it

    def test_cost_at_the_models_rates(self):
        run, updates = run_calls("claude-sonnet-5", usage(1000, 100), usage(1000, 100))
        # 1000 in / 100 out at $2 / $10 per million.
        for update, warning in updates:
            self.assertAlmostEqual(update["call_cost"], 0.003)
            self.assertIsNone(warning)
        self.assertAlmostEqual(run.total_cost, 0.006)
        self.assertAlmostEqual(updates[0][0]["total_cost"], 0.003)
        self.assertAlmostEqual(updates[1][0]["total_cost"], 0.006)

    def test_cache_tokens_are_priced_at_their_own_rates(self):
        run, [(update, _)] = run_calls("claude-opus-5-5", usage(
            1000, 100, cache_creation_input_tokens=2000, cache_read_input_tokens=30000))
        expected = 1000 * 4e-6 + 100 * 20e-6 + 2000 * 5e-6 + 30000 * 0.2e-6
        self.assertAlmostEqual(update["call_cost"], expected)
        self.assertAlmostEqual(run.total_cost, expected)

    def test_the_update_carries_the_call_and_the_running_totals(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        _, updates = run_calls("claude-sonnet-5", cached, dict(cached))
        update = updates[1][0]
        self.assertEqual(update["input_tokens"], 1000)
        self.assertEqual(update["output_tokens"], 100)
        self.assertEqual(update["cache_write_tokens"], 40)
        self.assertEqual(update["cache_read_tokens"], 7)
        self.assertEqual(update["total_input_tokens"], 2000)
        self.assertEqual(update["total_output_tokens"], 200)
        self.assertGreater(update["total_cost"], update["call_cost"])

    def test_a_call_is_priced_by_the_model_that_served_it(self):
        # A refusal fallback: the first call was served by another model.
        run, updates = run_calls(
            "claude-fable-5-1",
            usage(1000, 100, model="claude-opus-5"),
            usage(1000, 100, model="claude-fable-5-1"))
        self.assertAlmostEqual(updates[0][0]["call_cost"], 1000 * 5e-6 + 100 * 25e-6)
        self.assertAlmostEqual(updates[1][0]["call_cost"], 1000 * 10e-6 + 100 * 50e-6)
        self.assertEqual(list(run.per_model), ["claude-opus-5", "claude-fable-5-1"])
        self.assertAlmostEqual(run.per_model["claude-opus-5"][0], 0.0075)
        self.assertEqual(run.per_model["claude-opus-5"][1:], [1000, 100, 0, 0])

    def test_an_unpriced_serving_model_falls_back_to_the_configured_models_rates(self):
        run, updates = run_calls(
            "claude-fable-5-1",
            usage(1000, 100, model="claude-unknown-tier"),
            usage(1000, 100, model="claude-unknown-tier"))
        for update, _ in updates:
            self.assertAlmostEqual(update["call_cost"], 1000 * 10e-6 + 100 * 50e-6)
        self.assertEqual(list(run.per_model), ["claude-unknown-tier"])

    def test_a_dated_snapshot_of_the_configured_model_is_the_same_model(self):
        run, _ = run_calls("claude-sonnet-5",
                           usage(model="claude-sonnet-5-20260801"),
                           usage(model="claude-sonnet-5-20260801"))
        self.assertEqual(list(run.per_model), ["claude-sonnet-5"])
        self.assertAlmostEqual(run.total_cost, 0.006)

    def test_only_an_eight_digit_date_makes_it_the_same_model(self):
        for served in ("claude-sonnet-5-5", "claude-sonnet-5-2026080", "claude-sonnet-5-latest",
                       "claude-opus-5-20260801"):
            with self.subTest(served=served):
                run, _ = run_calls("claude-sonnet-5", usage(model=served))
                self.assertEqual(list(run.per_model), [served])

    def test_no_reported_model_means_the_configured_one(self):
        for reported in (None, ""):
            run, _ = run_calls("claude-sonnet-5", usage(model=reported))
            self.assertEqual(list(run.per_model), ["claude-sonnet-5"])
        run, _ = run_calls("claude-sonnet-5", usage())
        self.assertEqual(list(run.per_model), ["claude-sonnet-5"])

    def test_a_run_moved_to_another_model_is_split_at_each_models_rates(self):
        run = RunCost()
        run.add_call(usage(1000, 100), "claude-sonnet-5", fake_pricing)
        run.add_call(usage(1000, 100), "claude-fable-5-1", fake_pricing)   # after an upgrade
        self.assertEqual(list(run.per_model), ["claude-sonnet-5", "claude-fable-5-1"])
        self.assertAlmostEqual(run.per_model["claude-sonnet-5"][0], 0.003)
        self.assertAlmostEqual(run.per_model["claude-fable-5-1"][0], 0.015)
        self.assertAlmostEqual(run.total_cost, 0.018)
        self.assertAlmostEqual(sum(part[0] for part in run.per_model.values()), run.total_cost)

    def test_an_unpriced_model_still_counts_its_tokens(self):
        run, updates = run_calls("claude-unknown-99", usage(1000, 100), usage(1000, 100))
        self.assertEqual([update["call_cost"] for update, _ in updates], [None, None])
        self.assertEqual([update["total_cost"] for update, _ in updates], [None, None])
        self.assertEqual(updates[1][0]["input_tokens"], 1000)
        self.assertEqual(updates[1][0]["total_input_tokens"], 2000)
        self.assertEqual(run.total_cost, 0.0)
        self.assertTrue(run.had_usage)
        self.assertEqual(run.tokens(), (2000, 200, 0, 0))
        self.assertEqual(run.per_model, {"claude-unknown-99": [0.0, 2000, 200, 0, 0]})
        self.assertTrue(cost_line(updates[0][0]).startswith("  unpriced this call"))

    def test_a_call_served_fast_bills_at_the_fast_rates(self):
        run, updates = run_calls(
            "claude-opus-5-5",
            usage(1000, 100, model="claude-opus-5-5", speed="fast"),
            usage(1000, 100, model="claude-opus-5-5", speed="fast"))
        for update, _ in updates:
            self.assertAlmostEqual(update["call_cost"], 1000 * 8e-6 + 100 * 40e-6)

    def test_standard_speed_bills_at_the_standard_rates(self):
        _, [(update, _)] = run_calls("claude-opus-5-5", usage(1000, 100, speed="standard"))
        self.assertAlmostEqual(update["call_cost"], 1000 * 4e-6 + 100 * 20e-6)

    def test_a_fast_call_on_a_model_with_no_fast_rates_is_unpriced(self):
        # Billing it from the standard table would record half the real cost.
        run, [(update, _)] = run_calls("claude-sonnet-5", usage(1000, 100, speed="fast"))
        self.assertIsNone(update["call_cost"])
        self.assertEqual(run.total_cost, 0.0)

    def test_the_lookup_gets_the_speed_and_the_whole_prompt_size(self):
        asked = []

        def recording(model, speed=None, prompt_tokens=0):
            asked.append((model, speed, prompt_tokens))
            return fake_pricing(model, speed=speed, prompt_tokens=prompt_tokens)

        RunCost().add_call(
            usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7,
                  model="claude-opus-5-5-20260921", speed="fast"),
            "claude-opus-5-5", recording)
        # The prompt is the uncached input plus both cache buckets, and the
        # model asked about first is the one the API reported.
        self.assertEqual(asked, [("claude-opus-5-5-20260921", "fast", 1047)])

    def test_the_long_prompt_rate_card_and_its_one_warning(self):
        # Call 1: a 121,000-token prompt (over the line). Call 2: 51,000 (under).
        run, updates = run_calls(
            "claude-haiku-5-5",
            usage(1000, 100, cache_read_input_tokens=120_000),
            usage(1000, 100, cache_read_input_tokens=50_000))
        call_1 = 1000 * 0.50e-6 + 100 * 2.50e-6 + 120_000 * 0.05e-6
        call_2 = 1000 * 0.10e-6 + 100 * 0.50e-6 + 50_000 * 0.01e-6
        self.assertAlmostEqual(updates[0][0]["call_cost"], call_1)
        self.assertAlmostEqual(updates[1][0]["call_cost"], call_2)
        self.assertEqual(f"{run.total_cost:.4f}", "0.0074")
        self.assertEqual(run.tokens(), (2000, 200, 0, 170000))
        warning = updates[0][1]
        self.assertIn("second rate card", warning)
        self.assertIn("121,000", warning)
        self.assertIn("100,000", warning)
        self.assertIn("$0.50 / $2.50", warning)
        self.assertIn("claude-haiku-5-5", warning)
        self.assertIsNone(updates[1][1])

    def test_the_long_prompt_warning_comes_once_per_run(self):
        long_call = usage(1000, 100, cache_read_input_tokens=120_000)
        run, updates = run_calls("claude-haiku-5-5", long_call, dict(long_call), dict(long_call))
        self.assertEqual([warning is not None for _, warning in updates], [True, False, False])
        _, again = run_calls("claude-haiku-5-5", dict(long_call))   # a new run says it again
        self.assertIsNotNone(again[0][1])

    def test_a_run_under_the_line_gets_no_warning(self):
        run, updates = run_calls("claude-haiku-5-5", usage(1000, 100), usage(1000, 100))
        self.assertEqual([warning for _, warning in updates], [None, None])
        self.assertEqual(f"{run.total_cost:.4f}", f"{2 * (1000 * 0.10e-6 + 100 * 0.50e-6):.4f}")

    def test_the_warning_is_plain_text_for_the_caller_to_mark(self):
        _, [(_, warning)] = run_calls("claude-haiku-5-5",
                                      usage(1000, 100, cache_read_input_tokens=120_000))
        self.assertTrue(warning.isascii())
        self.assertTrue(warning.startswith("Prompt of 121,000 tokens"))
        self.assertNotIn(WARNING_SIGN, warning)

    def test_no_usage_changes_nothing(self):
        run = RunCost()
        for nothing in (None, {}):
            self.assertEqual(run.add_call(nothing, "claude-sonnet-5", fake_pricing), ({}, None))
        self.assertFalse(run.had_usage)
        self.assertEqual(run.total_cost, 0.0)
        self.assertEqual(run.tokens(), (0, 0, 0, 0))
        self.assertEqual(run.per_model, {})

    def test_missing_or_empty_counts_read_as_zero(self):
        run = RunCost()
        update, _ = run.add_call(
            {"input_tokens": 5, "output_tokens": None, "cache_creation_input_tokens": None,
             "web_search_requests": None, "speed": None}, "claude-sonnet-5", fake_pricing)
        self.assertEqual(run.tokens(), (5, 0, 0, 0))
        self.assertAlmostEqual(update["call_cost"], 5 * 2e-6)

    def test_injected_pricing_needs_no_models_module(self):
        with no_models():
            run, updates = run_calls("claude-sonnet-5", usage(1000, 100),
                                     usage(1000, 100, web_search_requests=0))
        self.assertAlmostEqual(run.total_cost, 0.006)


class WebSearchFeeTests(unittest.TestCase):
    def test_the_fee_is_added_to_each_priced_call(self):
        with fake_models():
            run, updates = run_calls("claude-sonnet-5",
                                     usage(1000, 100, web_search_requests=2),
                                     usage(1000, 100, web_search_requests=2))
        expected = 1000 * 2e-6 + 100 * 10e-6 + 2 * SEARCH_FEE
        for update, _ in updates:
            self.assertAlmostEqual(update["call_cost"], expected)
        self.assertAlmostEqual(run.total_cost, 2 * expected)
        self.assertAlmostEqual(run.per_model["claude-sonnet-5"][0], 2 * expected)

    def test_the_fee_comes_from_the_models_module(self):
        with fake_models(fee=0.25):
            _, [(update, _)] = run_calls("claude-sonnet-5",
                                         usage(1000, 100, web_search_requests=3))
        self.assertAlmostEqual(update["call_cost"], 0.003 + 0.75)

    def test_an_unpriced_call_gets_no_fee(self):
        with no_models():
            run, [(update, _)] = run_calls("claude-unknown-99",
                                           usage(1000, 100, web_search_requests=4))
        self.assertIsNone(update["call_cost"])
        self.assertEqual(run.total_cost, 0.0)


class DefaultPricingTests(unittest.TestCase):
    def test_pricing_defaults_to_the_models_module(self):
        asked = []

        def recording(model, speed=None, prompt_tokens=0):
            asked.append((model, speed, prompt_tokens))
            return fake_pricing(model, speed=speed, prompt_tokens=prompt_tokens)

        with fake_models(pricing=recording):
            run = RunCost()
            update, _ = run.add_call(usage(1000, 100, web_search_requests=1), "claude-sonnet-5")
        self.assertEqual(asked, [("claude-sonnet-5", None, 1000)])
        self.assertAlmostEqual(update["call_cost"], 0.003 + SEARCH_FEE)

    def test_loading_costs_does_not_load_the_models_module(self):
        # The price tables are only needed once a call has to be priced. Load
        # a second copy of the module while robot.models cannot be imported.
        spec = importlib.util.spec_from_file_location("robot_costs_second_copy", costs.__file__)
        second = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"robot.models": None, spec.name: second}):
            spec.loader.exec_module(second)
            run = second.RunCost()
            update, _ = run.add_call(usage(1000, 100), "claude-sonnet-5", fake_pricing)
            self.assertAlmostEqual(update["call_cost"], 0.003)
            with self.assertRaises(ImportError):
                run.add_call(usage(1000, 100), "claude-sonnet-5")   # only now is it needed

    def test_the_real_models_module_if_it_is_there(self):
        try:
            import robot.models as models
            model = models.DEFAULT_MODEL
            rates = models.get_pricing(model, speed=None, prompt_tokens=1047)
            fee = models.WEB_SEARCH_FEE
        except Exception as error:   # not written yet, or not finished
            self.skipTest(f"robot/models.py is not usable yet: {error!r}")
        if not rates:
            self.skipTest(f"{model} has no price in robot/models.py")
        run = RunCost()
        update, _ = run.add_call(
            usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7,
                  web_search_requests=2), model)
        expected = (1000 * rates["input"] + 100 * rates["output"] + 40 * rates["cache_write"]
                    + 7 * rates["cache_read"] + 2 * fee)
        self.assertAlmostEqual(update["call_cost"], expected)
        self.assertAlmostEqual(run.total_cost, expected)


# -- the per-model split ------------------------------------------------------


class SplitFieldTests(unittest.TestCase):
    SONNET = {"claude-sonnet-5": [0.0264, 1000, 100, 0, 0]}

    def test_nothing_to_split_writes_nothing(self):
        self.assertEqual(split_field(None), "")
        self.assertEqual(split_field({}), "")
        self.assertEqual(split_field({"claude-sonnet-5": [0.5, 1, 2, 3, 4]}), "")

    def test_each_model_with_its_cost_and_four_buckets_in_order_of_first_use(self):
        split = {"claude-sonnet-5": [0.0264, 2, 60, 10324, 0],
                 "claude-fable-5-1": [0.14097, 2, 226, 10372, 0]}
        self.assertEqual(split_field(split),
                         "claude-sonnet-5,0.026400,2,60,10324,0"
                         "|claude-fable-5-1,0.140970,2,226,10372,0")

    def test_a_separator_in_a_model_id_cannot_split_the_field(self):
        split = {"odd,id|x;y": [0.1, 1, 1, 1, 1], "b": [0.2, 1, 1, 1, 1]}
        self.assertTrue(split_field(split).startswith("odd_id_x_y,0.100000,"))
        self.assertEqual(split_field(split).count("|"), 1)
        self.assertNotIn(";", split_field(split))

    def test_one_serving_model_other_than_the_logged_one_is_written(self):
        self.assertEqual(split_field(self.SONNET, "claude-fable-5-1"),
                         "claude-sonnet-5,0.026400,1000,100,0,0")

    def test_one_serving_model_that_is_the_logged_one_is_not(self):
        self.assertEqual(split_field(self.SONNET, "claude-sonnet-5"), "")
        self.assertEqual(split_field(self.SONNET), "")

    def test_two_models_are_written_whatever_the_logged_model(self):
        split = {"a": [0.1, 1, 1, 1, 1], "b": [0.2, 1, 1, 1, 1]}
        for logged in (None, "a", "b", "c"):
            self.assertEqual(split_field(split, logged), "a,0.100000,1,1,1,1|b,0.200000,1,1,1,1")

    def test_counts_are_written_as_whole_numbers(self):
        split = {"a": [0.1, 1000.0, 100.0, 0, 0], "b": [0, 1, 1, 1, 1]}
        self.assertEqual(split_field(split), "a,0.100000,1000,100,0,0|b,0.000000,1,1,1,1")


# -- the cost-log line --------------------------------------------------------


def _line(**over):
    values = dict(timestamp="2026-03-04 05:06:07", model="claude-opus-5-5", total_cost=0.3742,
                  params="mode=Low", seconds=137.4, instruction="", calls=7,
                  tokens=(10000, 5000, 20000, 900000))
    values.update(over)
    return format_log_line(**values)


def _fields(**over):
    return _line(**over).rstrip("\n").split(";")


class FormatLogLineTests(unittest.TestCase):
    def test_the_whole_line_byte_for_byte(self):
        self.assertEqual(
            _line(instruction="Tidy the workshop", chat="Tidy the workshop_2026-03-04_050000"),
            "2026-03-04 05:06:07;Anthropic;claude-opus-5-5;0.3742;mode=Low;137;"
            "Tidy the workshop;7;10000;5000;20000;900000;;Tidy the workshop_2026-03-04_050000\n")
        self.assertEqual(
            _line(),
            "2026-03-04 05:06:07;Anthropic;claude-opus-5-5;0.3742;mode=Low;137;;7;"
            "10000;5000;20000;900000\n")

    def test_twelve_fields_and_one_newline(self):
        line = _line()
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)
        self.assertNotIn("\r", line)
        self.assertEqual(len(line.rstrip("\n").split(";")), 12)

    def test_provider_model_and_cost(self):
        fields = _fields()
        self.assertEqual(fields[0], "2026-03-04 05:06:07")
        self.assertEqual(fields[1], "Anthropic")
        self.assertEqual(fields[2], "claude-opus-5-5")
        self.assertEqual(fields[3], "0.3742")

    def test_a_timestamp_given_as_a_datetime_is_written_in_the_logs_format(self):
        self.assertEqual(_fields(timestamp=datetime(2026, 3, 4, 5, 6, 7, 891011))[0],
                         "2026-03-04 05:06:07")

    def test_cost_has_four_decimals(self):
        self.assertEqual(_fields(total_cost=7.7744525)[3], "7.7745")
        self.assertEqual(_fields(total_cost=0.01)[3], "0.0100")
        self.assertEqual(_fields(total_cost=12)[3], "12.0000")
        self.assertEqual(_fields(total_cost=0.00004)[3], "0.0000")

    def test_params_are_the_fifth_field_joined_with_commas(self):
        self.assertEqual(_fields(params="mode=Max speed=fast")[4], "mode=Max, speed=fast")
        self.assertEqual(
            _fields(params="mode=Max upgraded-from=claude-sonnet-5@call1")[4],
            "mode=Max, upgraded-from=claude-sonnet-5@call1")

    def test_params_given_as_parts_or_already_joined_come_out_the_same(self):
        for given in (["mode=Max", "speed=fast"], ("mode=Max", "speed=fast"),
                      "mode=Max, speed=fast", "mode=Max,speed=fast", "  mode=Max \n speed=fast "):
            with self.subTest(given=given):
                fields = _fields(params=given)
                self.assertEqual(len(fields), 12)
                self.assertEqual(fields[4], "mode=Max, speed=fast")

    def test_params_cannot_split_the_line(self):
        fields = _fields(params="mode=Max;speed=fast")
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[4], "mode=Max, speed=fast")

    def test_empty_params_leave_the_field_blank(self):
        for empty in ("", None, [], "   "):
            fields = _fields(params=empty)
            self.assertEqual(len(fields), 12)
            self.assertEqual(fields[4], "")

    def test_seconds_are_whole_and_sixth(self):
        self.assertEqual(_fields(seconds=137.4)[5], "137")
        self.assertEqual(_fields(seconds=42.0)[5], "42")
        self.assertEqual(_fields(seconds=268.7)[5], "269")
        self.assertEqual(_fields(seconds=1234.6)[5], "1235")
        self.assertEqual(_fields(seconds=0)[5], "0")

    def test_instruction_is_seventh_and_calls_eighth(self):
        fields = _fields(seconds=42.0, instruction="Check the battery level", calls=7)
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[5], "42")
        self.assertEqual(fields[6], "Check the battery level")   # spaces are fine
        self.assertEqual(fields[7], "7")

    def test_an_instruction_name_cannot_split_the_line(self):
        # A semicolon would add a field and a line break would end the record.
        fields = _fields(instruction="  odd; name\nwith   breaks ", calls=3)
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[6], "odd, name with breaks")
        self.assertEqual(fields[7], "3")
        self.assertEqual(_line(instruction="a\r\nb\tc").count("\n"), 1)

    def test_values_that_were_not_recorded_are_blank_not_none(self):
        fields = _fields(instruction=None, calls=None, seconds=None)
        self.assertEqual(len(fields), 12)
        self.assertEqual((fields[5], fields[6], fields[7]), ("", "", ""))

    def test_tokens_are_the_last_four_fields(self):
        self.assertEqual(_fields()[8:], ["10000", "5000", "20000", "900000"])

    def test_absent_tokens_are_four_blanks_not_zeros(self):
        for absent in (None, ()):
            fields = _fields(tokens=absent)
            self.assertEqual(len(fields), 12)
            self.assertEqual(fields[8:], ["", "", "", ""])

    def test_zero_tokens_are_zeros(self):
        self.assertEqual(_fields(tokens=(0, 0, 0, 0))[8:], ["0", "0", "0", "0"])

    def test_tokens_and_calls_are_written_as_whole_numbers(self):
        fields = _fields(tokens=(1000.0, 100.0, 0, 0), calls=3.0)
        self.assertEqual(fields[8:], ["1000", "100", "0", "0"])
        self.assertEqual(fields[7], "3")

    def test_the_chat_is_the_14th_field_and_forces_a_blank_13th(self):
        fields = _fields(instruction="Check_the_sensors", calls=9,
                         tokens=(612, 8138, 48113, 276910),
                         chat="Check_the_sensors_2026-03-04_071620")
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[6:8], ["Check_the_sensors", "9"])
        self.assertEqual(fields[8:12], ["612", "8138", "48113", "276910"])
        self.assertEqual(fields[12], "")
        self.assertEqual(fields[13], "Check_the_sensors_2026-03-04_071620")

    def test_with_a_split_both_sit_in_their_own_places(self):
        split = split_field({"claude-sonnet-5": [0.0264, 2, 60, 10324, 0],
                             "claude-fable-5-1": [0.141, 2, 226, 10372, 0]})
        fields = _fields(model="claude-fable-5-1", split=split, chat="ZZ_2026-03-04_091500")
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[12], "claude-sonnet-5,0.026400,2,60,10324,0"
                                     "|claude-fable-5-1,0.141000,2,226,10372,0")
        self.assertEqual(fields[13], "ZZ_2026-03-04_091500")

    def test_the_chat_name_is_made_safe_like_the_instruction(self):
        fields = _fields(chat="  odd; name\nwith   breaks ")
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[13], "odd, name with breaks")

    def test_no_chat_keeps_the_12_field_shape(self):
        for chat in (None, "", "   "):
            with self.subTest(chat=chat):
                self.assertEqual(len(_fields(chat=chat)), 12)

    def test_a_split_without_a_chat_makes_13_fields(self):
        split = split_field({"claude-sonnet-5": [0.1, 1, 1, 1, 1],
                             "claude-fable-5-1": [0.4, 0, 1, 2, 3]})
        self.assertEqual(len(_fields(model="claude-fable-5-1", split=split)), 13)

    def test_a_split_given_as_the_per_model_totals_is_formatted(self):
        totals = {"claude-sonnet-5": [0.1, 1, 1, 1, 1], "claude-fable-5-1": [0.4, 0, 1, 2, 3]}
        self.assertEqual(_fields(model="claude-fable-5-1", split=totals)[12],
                         split_field(totals, "claude-fable-5-1"))
        one = {"claude-fable-5-1": [0.4, 0, 1, 2, 3]}
        self.assertEqual(len(_fields(model="claude-fable-5-1", split=one)), 12)

    def test_names_keep_their_letters(self):
        line = _line(instruction="Caf\u00e9 run", chat="Caf\u00e9 run_2026-03-04_050000")
        self.assertIn(";Caf\u00e9 run;", line)
        self.assertTrue(line.endswith(";Caf\u00e9 run_2026-03-04_050000\n"))


class LogRunTests(TempDir):
    def _run(self, total_cost=0.5, had_usage=True, calls=3, tokens=(1, 2, 3, 4), per_model=None):
        return RunCost(total_cost=total_cost, had_usage=had_usage, calls=calls,
                       input_tokens=tokens[0], output_tokens=tokens[1],
                       cache_write_tokens=tokens[2], cache_read_tokens=tokens[3],
                       per_model=per_model if per_model is not None else {})

    def _log(self, run, **over):
        values = dict(model="claude-opus-5-5", params="mode=Low", seconds=12.0)
        values.update(over)
        return log_run(self.log, run, **values)

    def test_writes_the_line_and_says_so(self):
        written, note = self._log(self._run(), instruction="X", chat="X_2026-03-04_101010",
                                  now=WHEN)
        self.assertIs(written, True)
        line = ("2026-03-04 05:06:07;Anthropic;claude-opus-5-5;0.5000;mode=Low;12;X;3;"
                "1;2;3;4;;X_2026-03-04_101010\n")
        self.assertEqual(self.log.read_text(encoding="utf-8"), line)
        self.assertEqual(note, f"Logged API cost to {self.log}: {line}")

    def test_the_file_is_utf8_with_bare_line_feeds(self):
        self._log(self._run(), instruction="Caf\u00e9", now=WHEN)
        self._log(self._run(), instruction="Caf\u00e9", now=WHEN)
        data = self.log.read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertEqual(data.count(b"\n"), 2)
        self.assertIn("Caf\u00e9".encode("utf-8"), data)

    def test_the_timestamp_is_now_unless_given(self):
        self._log(self._run())
        self.assertRegex(self.fields()[0], STAMP)

    def test_a_given_time_is_used(self):
        for given in (WHEN, "2026-03-04 05:06:07", lambda: WHEN):
            with self.subTest(given=given):
                self._log(self._run(), now=given)
                self.assertEqual(self.fields()[0], "2026-03-04 05:06:07")
                self.log.unlink()

    def test_the_runs_own_counts_fill_the_line(self):
        self._log(self._run(total_cost=0.1234, calls=7, tokens=(10000, 5000, 20000, 900000)),
                  seconds=42.0, instruction="Check the battery level")
        fields = self.fields()
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[3], "0.1234")
        self.assertEqual(fields[5], "42")
        self.assertEqual(fields[6], "Check the battery level")
        self.assertEqual(fields[7], "7")
        self.assertEqual(fields[8:], ["10000", "5000", "20000", "900000"])

    def test_a_run_that_made_no_call_is_not_logged_and_says_nothing(self):
        self.assertEqual(self._log(self._run(total_cost=0.0, had_usage=False, calls=0)),
                         (False, None))
        self.assertFalse(self.log.exists())

    def test_an_unpriced_run_is_not_logged_and_says_why(self):
        # A zero line would claim the run was free; the truth is that its
        # price is unknown.
        written, note = self._log(self._run(total_cost=0.0, had_usage=True),
                                  model="claude-future-99")
        self.assertIs(written, False)
        self.assertFalse(self.log.exists())
        self.assertTrue(note.startswith("Run NOT written to the API cost log"))
        self.assertIn("claude-future-99", note)
        self.assertIn("Anthropic pricing table", note)
        self.assertIn("robot/models.py", note)
        self.assertNotIn(WARNING_SIGN, note)
        self.assertTrue(note.isascii())

    def test_a_cost_that_is_not_above_zero_is_never_logged(self):
        for cost in (0, 0.0, -0.5, None):
            with self.subTest(cost=cost):
                written, _ = self._log(self._run(total_cost=cost))
                self.assertIs(written, False)
                self.assertFalse(self.log.exists())

    def test_a_two_model_run_gets_the_13th_field(self):
        split = {"claude-sonnet-5": [0.0264, 2, 60, 10324, 0],
                 "claude-fable-5-1": [0.141, 2, 226, 10372, 0]}
        self._log(self._run(total_cost=0.1674, calls=2, tokens=(4, 286, 20696, 0),
                            per_model=split),
                  model="claude-fable-5-1", params="mode=Max upgraded-from=claude-sonnet-5@call1",
                  seconds=7, instruction="ZZ")
        fields = self.fields()
        self.assertEqual(len(fields), 13)
        self.assertEqual(fields[2:4], ["claude-fable-5-1", "0.1674"])
        self.assertEqual(fields[4], "mode=Max, upgraded-from=claude-sonnet-5@call1")
        self.assertEqual(fields[8:12], ["4", "286", "20696", "0"])
        self.assertEqual(fields[12], "claude-sonnet-5,0.026400,2,60,10324,0"
                                     "|claude-fable-5-1,0.141000,2,226,10372,0")

    def test_a_one_model_run_keeps_its_12_fields(self):
        self._log(self._run(per_model={"claude-fable-5-1": [0.5, 1, 2, 3, 4]}),
                  model="claude-fable-5-1")
        self.assertEqual(len(self.fields()), 12)

    def test_a_run_logged_under_a_model_that_served_nothing_carries_the_split(self):
        # Moved to a new model on its last reply: the line names the new
        # model, so the split must credit the cost to the old one.
        self._log(self._run(total_cost=0.0264, tokens=(1000, 100, 0, 0),
                            per_model={"claude-sonnet-5": [0.0264, 1000, 100, 0, 0]}),
                  model="claude-fable-5-1", instruction="Balance")
        fields = self.fields()
        self.assertEqual(len(fields), 13)
        self.assertEqual(fields[2], "claude-fable-5-1")
        self.assertEqual(fields[12], "claude-sonnet-5,0.026400,1000,100,0,0")

    def test_a_chat_name_makes_14_fields_with_or_without_a_split(self):
        self._log(self._run(per_model={"claude-opus-5-5": [0.5, 1, 2, 3, 4]}), chat="A_chat")
        fields = self.fields()
        self.assertEqual((len(fields), fields[12], fields[13]), (14, "", "A_chat"))

    def test_lines_are_appended_and_the_log_is_never_rotated(self):
        history = "2026-01-09 08:11:17;Anthropic;claude-sonnet-4-6;0.3392\n" * 2000
        self.log.write_bytes(history.encode("utf-8"))
        self.assertGreater(self.log.stat().st_size, 100_000)
        written, _ = self._log(self._run(total_cost=0.0219), model="claude-haiku-5-5")
        self.assertTrue(written)
        text = self.log.read_bytes().decode("utf-8")
        self.assertTrue(text.startswith(history))        # every earlier byte kept
        added = text[len(history):].splitlines()
        self.assertEqual(len(added), 1)
        self.assertIn(";Anthropic;claude-haiku-5-5;0.0219;", added[0])
        self.assertEqual(sorted(os.listdir(self.dir)), ["APICostLog_test.txt", "runs"])

    def test_a_failed_write_is_reported_and_never_raised(self):
        missing = self.dir / "no" / "such" / "folder" / "log.txt"
        written, note = log_run(missing, self._run(), model="claude-opus-5-5",
                                params="mode=Low", seconds=1.0)
        self.assertIs(written, False)
        self.assertTrue(note.startswith("Could not write the API cost log"))
        self.assertIn(str(missing), note)
        self.assertNotIn(WARNING_SIGN, note)
        self.assertFalse(missing.parent.exists())      # nothing was created on the way

    def test_the_log_path_may_be_text(self):
        written, _ = log_run(str(self.log), self._run(), model="claude-opus-5-5",
                             params="mode=Low", seconds=1.0)
        self.assertTrue(written)
        self.assertEqual(len(self.lines()), 1)


class WholeRunTests(TempDir):
    """A run as the agent loop drives it: two calls of 1000 in / 100 out, the
    first a tool round, then the line."""

    def _finish(self, run, model="claude-sonnet-5", **over):
        values = dict(model=model, params="mode=Adaptive", seconds=3.0,
                      instruction="Check the battery level")
        values.update(over)
        return log_run(self.log, run, **values)

    def test_a_completed_run_logs_its_instruction_and_call_count(self):
        run, _ = run_calls("claude-sonnet-5", usage(), usage())
        self._finish(run)
        fields = self.fields()
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[1:4], ["Anthropic", "claude-sonnet-5", "0.0060"])
        self.assertEqual(fields[4], "mode=Adaptive")
        self.assertEqual(fields[6], "Check the battery level")
        self.assertEqual(fields[7], "2")
        self.assertEqual(fields[8:], ["2000", "200", "0", "0"])

    def test_a_run_that_failed_on_its_second_call_logs_what_it_got_through(self):
        run, _ = run_calls("claude-sonnet-5", usage())
        run.calls += 1           # the second call started, then raised
        self._finish(run)
        fields = self.fields()
        self.assertEqual(fields[7], "2")
        self.assertEqual(fields[8:], ["1000", "100", "0", "0"])

    def test_a_run_with_no_instruction_logs_a_blank_name(self):
        run, _ = run_calls("claude-sonnet-5", usage(), usage())
        self._finish(run, instruction="")
        fields = self.fields()
        self.assertEqual((fields[6], fields[7]), ("", "2"))

    def test_cache_buckets_get_their_own_fields(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        run, _ = run_calls("claude-sonnet-5", cached, dict(cached))
        self._finish(run)
        self.assertEqual(self.fields()[8:], ["2000", "200", "80", "14"])

    def test_a_run_that_failed_before_any_call_logs_nothing(self):
        self.assertEqual(self._finish(RunCost()), (False, None))
        self.assertFalse(self.log.exists())

    def test_an_unpriced_model_shows_its_tokens_and_logs_nothing(self):
        run, updates = run_calls("claude-unknown-99", usage(), usage())
        written, note = self._finish(run, model="claude-unknown-99")
        self.assertFalse(written)
        self.assertFalse(self.log.exists())
        self.assertTrue(note.startswith("Run NOT written to the API cost log"))
        self.assertIn("claude-unknown-99 has no row in the Anthropic pricing table", note)
        self.assertEqual([update["call_cost"] for update, _ in updates], [None, None])

    def test_a_priced_run_says_only_that_it_was_logged(self):
        run, updates = run_calls("claude-sonnet-5", usage(), usage())
        self.assertTrue(all(update["call_cost"] > 0 for update, _ in updates))
        self.assertEqual([warning for _, warning in updates], [None, None])
        written, note = self._finish(run)
        self.assertTrue(written)
        self.assertTrue(note.startswith("Logged API cost to "))

    def test_a_run_moved_to_another_model_is_split_at_each_models_rates(self):
        run = RunCost()
        for model in ("claude-sonnet-5", "claude-fable-5-1"):   # moved between the calls
            run.calls += 1
            run.add_call(usage(), model, fake_pricing)
        self._finish(run, model="claude-fable-5-1")
        fields = self.fields()
        # $2 / $10 per million, then $10 / $50: 0.003 + 0.015.
        self.assertEqual(fields[2:4], ["claude-fable-5-1", "0.0180"])
        self.assertEqual(fields[8:12], ["2000", "200", "0", "0"])
        self.assertEqual(fields[12], "claude-sonnet-5,0.003000,1000,100,0,0"
                                     "|claude-fable-5-1,0.015000,1000,100,0,0")

    def test_a_refusal_fallback_served_by_another_model_is_split_too(self):
        run, _ = run_calls("claude-sonnet-5", usage(model="claude-sonnet-5"),
                           usage(model="claude-opus-5"))
        self._finish(run)
        fields = self.fields()
        self.assertEqual(fields[3], "0.0105")
        self.assertEqual(fields[12], "claude-sonnet-5,0.003000,1000,100,0,0"
                                     "|claude-opus-5,0.007500,1000,100,0,0")

    def test_a_dated_snapshot_of_the_configured_model_makes_no_split(self):
        run, _ = run_calls("claude-sonnet-5", usage(model="claude-sonnet-5-20260801"),
                           usage(model="claude-sonnet-5-20260801"))
        self._finish(run)
        fields = self.fields()
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[3], "0.0060")

    def test_a_long_prompt_run_is_priced_call_by_call(self):
        run, _ = run_calls("claude-haiku-5-5",
                           usage(cache_read_input_tokens=120_000),
                           usage(cache_read_input_tokens=50_000))
        self._finish(run, model="claude-haiku-5-5", instruction="Long run")
        fields = self.fields()
        self.assertEqual(fields[1:4], ["Anthropic", "claude-haiku-5-5", "0.0074"])
        self.assertEqual(fields[8:12], ["2000", "200", "0", "170000"])

    def test_the_chat_name_is_logged_on_both_ways_out(self):
        for calls_made in (1, 2):
            with self.subTest(calls_made=calls_made):
                run, _ = run_calls("claude-sonnet-5", *[usage()] * calls_made)
                self._finish(run, chat="Check the battery level_2026-03-04_091500")
                fields = self.fields()
                self.assertEqual(len(fields), 14)
                self.assertEqual(fields[6], "Check the battery level")
                self.assertEqual(fields[12], "")
                self.assertEqual(fields[13], "Check the battery level_2026-03-04_091500")
                self.log.unlink()


# -- the in-progress record ---------------------------------------------------


def _dead(pid):
    return False


def _alive(pid):
    return True


class ProgressRecordTests(TempDir):
    def _write(self, run, pid=4242, **over):
        values = dict(model="claude-sonnet-5", params="mode=Adaptive", seconds=1.5,
                      instruction="Check the battery level",
                      chat="Check the battery level_2026-03-04_092704", boot_id="boot-a")
        values.update(over)
        return progress_write(self.runs, pid, run, **values)

    def _record(self, pid=4242):
        return json.loads(progress_path(self.runs, pid).read_text(encoding="utf-8"))

    def test_the_path_is_named_by_the_pid(self):
        self.assertEqual(progress_path(self.runs, 4242), self.runs / "agent_run_4242.json")
        self.assertEqual(progress_path(str(self.runs), 7), self.runs / "agent_run_7.json")
        self.assertIsInstance(progress_path(str(self.runs), 7), Path)

    def test_the_record_holds_what_the_line_would_say(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        run, _ = run_calls("claude-sonnet-5", cached)
        self.assertIsNone(self._write(run))
        record = self._record()
        self.assertEqual(record["version"], 1)
        self.assertRegex(record["written"], STAMP)
        self.assertEqual(record["provider"], "Anthropic")
        self.assertEqual(record["model"], "claude-sonnet-5")
        self.assertEqual(record["params"], "mode=Adaptive")
        self.assertIs(record["had_usage"], True)
        self.assertGreater(record["total_cost"], 0)
        self.assertEqual(record["duration_secs"], 1.5)
        self.assertEqual(record["instruction"], "Check the battery level")
        self.assertEqual(record["calls"], 1)
        self.assertEqual(record["tokens"], [1000, 100, 40, 7])
        self.assertEqual(list(record["split"]), ["claude-sonnet-5"])
        self.assertEqual(record["split"]["claude-sonnet-5"][1:], [1000, 100, 40, 7])
        self.assertAlmostEqual(record["split"]["claude-sonnet-5"][0], record["total_cost"])
        self.assertEqual(record["chat"], "Check the battery level_2026-03-04_092704")
        self.assertEqual(record["pid"], 4242)
        self.assertEqual(record["boot_id"], "boot-a")

    def test_each_write_replaces_the_one_before(self):
        run = RunCost()
        for call in (1, 2, 3):
            run.calls += 1
            run.add_call(usage(), "claude-sonnet-5", fake_pricing)
            self._write(run)
            record = self._record()
            self.assertEqual(record["calls"], call)
            self.assertEqual(record["tokens"], [1000 * call, 100 * call, 0, 0])
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])   # no temporary files

    def test_params_may_be_given_as_parts(self):
        self._write(RunCost(), params=["mode=Max", "speed=fast"])
        self.assertEqual(self._record()["params"], "mode=Max speed=fast")

    def test_names_keep_their_letters_and_the_file_has_bare_line_feeds(self):
        self._write(RunCost(), instruction="Caf\u00e9 run")
        data = progress_path(self.runs, 4242).read_bytes()
        self.assertIn("Caf\u00e9 run".encode("utf-8"), data)
        self.assertNotIn(b"\r", data)

    def test_the_folder_is_made_if_it_is_missing(self):
        runs = self.dir / "not" / "there" / "yet"
        self.assertIsNone(progress_write(runs, 5, RunCost(), model="m", params="", seconds=0))
        self.assertTrue((runs / "agent_run_5.json").exists())

    def test_each_process_has_its_own_record(self):
        self._write(RunCost(calls=1), pid=11)
        self._write(RunCost(calls=2), pid=22)
        self.assertEqual(self.record_names(), ["agent_run_11.json", "agent_run_22.json"])
        self.assertEqual(self._record(11)["calls"], 1)
        self.assertEqual(self._record(22)["calls"], 2)

    def test_clear_removes_only_this_processes_record(self):
        self._write(RunCost(), pid=11)
        self._write(RunCost(), pid=22)
        self.assertIsNone(progress_clear(self.runs, 11))
        self.assertEqual(self.record_names(), ["agent_run_22.json"])

    def test_clearing_a_record_that_is_not_there_is_quiet(self):
        self.assertIsNone(progress_clear(self.runs, 4242))
        self.assertIsNone(progress_clear(self.dir / "no" / "folder", 4242))

    def test_a_failed_clear_is_reported_not_raised(self):
        self._write(RunCost())
        with mock.patch.object(costs.os, "remove", side_effect=PermissionError("in use")):
            note = progress_clear(self.runs, 4242)
        self.assertIn("Could not remove the in-progress cost record", note)
        self.assertIn("in use", note)
        self.assertNotIn(WARNING_SIGN, note)

    def test_a_failed_write_warns_once_per_run_and_never_raises(self):
        run = RunCost()
        with mock.patch.object(costs.tempfile, "mkstemp", side_effect=OSError("disk full")):
            first = self._write(run)
            second = self._write(run)
            other_run = self._write(RunCost())
        self.assertIn("Could not write the in-progress cost record", first)
        self.assertIn("agent_run_4242.json", first)
        self.assertIn("disk full", first)
        self.assertNotIn(WARNING_SIGN, first)
        self.assertIsNone(second)                # two calls, one warning
        self.assertIsNotNone(other_run)          # the next run says it again
        self.assertEqual(self.record_names(), [])

    def test_a_write_that_fails_half_way_leaves_the_previous_record_whole(self):
        run, _ = run_calls("claude-sonnet-5", usage())
        self._write(run)
        before = progress_path(self.runs, 4242).read_bytes()
        run.calls += 1
        run.add_call(usage(), "claude-sonnet-5", fake_pricing)
        with mock.patch.object(costs.os, "replace", side_effect=OSError("no rename")):
            note = self._write(run)
        self.assertIn("no rename", note)
        self.assertEqual(progress_path(self.runs, 4242).read_bytes(), before)
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])   # the temp file is gone

    def test_bad_arguments_are_reported_not_raised(self):
        self.assertIn("Could not write", progress_write(self.runs, "not-a-pid", RunCost(),
                                                        model="m", params="", seconds=0))
        self.assertIn("Could not remove", progress_clear(self.runs, "not-a-pid"))

    def test_a_run_that_ends_normally_leaves_no_record_and_the_same_line(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        chat = "Check the battery level_2026-03-04_092704"

        def whole_run(keep_record):
            run = RunCost()
            for _ in range(2):
                run.calls += 1
                run.add_call(dict(cached), "claude-sonnet-5", fake_pricing)
                if keep_record:
                    self._write(run)
            log_run(self.log, run, model="claude-sonnet-5", params="mode=Adaptive",
                    seconds=3.0, instruction="Check the battery level", chat=chat, now=WHEN)
            if keep_record:
                progress_clear(self.runs, 4242)
            line = self.log.read_text(encoding="utf-8")
            self.log.unlink()
            return line

        with_record = whole_run(True)
        self.assertEqual(self.record_names(), [])
        self.assertEqual(with_record, whole_run(False))
        fields = with_record.rstrip("\n").split(";")
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[7], "2")
        self.assertEqual(fields[8:12], ["2000", "200", "80", "14"])
        self.assertEqual(fields[13], chat)
        self.assertNotIn("unfinished", fields[4])

    def test_a_killed_run_leaves_its_last_record_behind(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        run = RunCost()
        for _ in range(2):
            run.calls += 1
            run.add_call(dict(cached), "claude-sonnet-5", fake_pricing)
            self._write(run)
        # ... and the process dies here, before its line and before the clear.
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])
        record = self._record()
        self.assertEqual(record["calls"], 2)
        self.assertEqual(record["tokens"], [2000, 200, 80, 14])


class FoldInTests(TempDir):
    PID = 4242

    def _leftover(self, pid=None, **over):
        """A record as a dead process leaves it, with changes."""
        record = {
            "version": 1, "written": "2026-03-04 10:08:04", "provider": "Anthropic",
            "model": "claude-fable-5-1", "params": "mode=Max speed=fast",
            "total_cost": 7.7744525, "had_usage": True, "duration_secs": 1234.6,
            "instruction": "Sort_the_parts_bin", "calls": 53,
            "tokens": [18103, 48399, 108567, 3816385],
            "split": {"claude-fable-5-1": [7.7744525, 18103, 48399, 108567, 3816385]},
            "chat": "Sort_the_parts_bin_2026-03-04_092704",
            "pid": pid or self.PID, "boot_id": "boot-a",
        }
        record.update(over)
        progress_path(self.runs, pid or self.PID).write_text(json.dumps(record),
                                                             encoding="utf-8")
        return record

    def _fold(self, is_alive=_dead, **over):
        return progress_fold_in(self.runs, self.log, is_alive=is_alive, **over)

    def test_a_dead_runs_line_is_written_from_its_record(self):
        self._leftover()
        self.assertEqual(self._fold(), 1)
        self.assertEqual(
            self.log.read_text(encoding="utf-8"),
            "2026-03-04 10:08:04;Anthropic;claude-fable-5-1;7.7745;"
            "mode=Max, speed=fast, unfinished@call53;1235;Sort_the_parts_bin;53;"
            "18103;48399;108567;3816385;;Sort_the_parts_bin_2026-03-04_092704\n")
        fields = self.fields()
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[0], "2026-03-04 10:08:04")   # the record's time, not now
        self.assertEqual(fields[12], "")                     # one model, logged under it
        self.assertEqual(self.record_names(), [])            # the record is gone

    def test_no_records_means_nothing_happens(self):
        self.assertEqual(self._fold(), 0)
        self.assertEqual(self.lines(), [])

    def test_a_missing_folder_means_nothing_happens(self):
        self.assertEqual(progress_fold_in(self.dir / "nowhere", self.log, is_alive=_dead), 0)
        self.assertEqual(self.lines(), [])

    def test_a_live_processes_record_is_left_alone(self):
        self._leftover()
        before = progress_path(self.runs, self.PID).read_bytes()
        asked = []

        def alive(pid):
            asked.append(pid)
            return True

        self.assertEqual(self._fold(is_alive=alive), 0)
        self.assertEqual(asked, [self.PID])
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])
        self.assertEqual(progress_path(self.runs, self.PID).read_bytes(), before)

    def test_only_the_dead_are_folded_in(self):
        self._leftover(pid=11, chat="dead_one")
        self._leftover(pid=22, chat="alive")
        self._leftover(pid=33, chat="dead_two")
        self.assertEqual(self._fold(is_alive=lambda pid: pid == 22), 2)
        self.assertEqual(sorted(line.split(";")[13] for line in self.lines()),
                         ["dead_one", "dead_two"])
        self.assertEqual(self.record_names(), ["agent_run_22.json"])

    def test_this_processes_own_record_is_skipped_without_asking(self):
        self._leftover()
        asked = []

        def dead(pid):
            asked.append(pid)
            return False        # with this answer any other record is folded in

        self.assertEqual(self._fold(is_alive=dead, my_pid=self.PID), 0)
        self.assertEqual(self._fold(is_alive=dead, my_pid=self.PID, boot_id="boot-a"), 0)
        self.assertEqual(asked, [])
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])
        self.assertEqual(self._fold(is_alive=dead, my_pid=self.PID + 1), 1)   # not its own

    def test_a_record_from_an_earlier_boot_is_dead_whoever_has_its_pid_now(self):
        self._leftover(boot_id="boot-a")
        self.assertEqual(self._fold(is_alive=_alive, boot_id="boot-b"), 1)
        self.assertEqual(self.fields()[13], "Sort_the_parts_bin_2026-03-04_092704")
        self.assertEqual(self.record_names(), [])

    def test_an_earlier_boots_record_under_this_processes_own_pid_is_folded_in(self):
        # The program got the PID a dead run had before the reboot. Its own
        # first record would overwrite the dead run's, so that one is logged.
        self._leftover(boot_id="boot-a")
        self.assertEqual(self._fold(is_alive=_alive, boot_id="boot-b", my_pid=self.PID), 1)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.record_names(), [])

    def test_the_same_boot_and_a_live_pid_is_left_alone(self):
        self._leftover(boot_id="boot-a")
        self.assertEqual(self._fold(is_alive=_alive, boot_id="boot-a"), 0)
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])

    def test_an_unknown_boot_id_on_either_side_proves_nothing(self):
        self._leftover(boot_id="")
        self.assertEqual(self._fold(is_alive=_alive, boot_id="boot-b"), 0)
        self._leftover(boot_id="boot-a")
        self.assertEqual(self._fold(is_alive=_alive, boot_id=""), 0)
        self.assertEqual(self._fold(is_alive=_alive), 0)
        record = self._leftover()
        del record["boot_id"]
        progress_path(self.runs, self.PID).write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self._fold(is_alive=_alive, boot_id="boot-b"), 0)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])

    def test_a_dead_process_is_folded_in_whatever_the_boot_ids(self):
        for record_boot, now_boot in (("boot-a", "boot-a"), ("", "boot-a"), ("boot-a", "")):
            with self.subTest(record_boot=record_boot, now_boot=now_boot):
                self._leftover(boot_id=record_boot)
                self.assertEqual(self._fold(boot_id=now_boot), 1)
                self.log.unlink()

    def test_a_check_that_fails_leaves_the_record_alone(self):
        self._leftover()

        def broken(pid):
            raise OSError("cannot tell")

        self.assertEqual(self._fold(is_alive=broken), 0)
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])

    def test_an_unreadable_record_is_removed_and_logs_nothing(self):
        for text in ("{not json", "[1, 2, 3]", "", '"just text"'):
            with self.subTest(text=text):
                progress_path(self.runs, self.PID).write_text(text, encoding="utf-8")
                self.assertEqual(self._fold(), 0)
                self.assertEqual(self.lines(), [])
                self.assertEqual(self.record_names(), [])

    def test_a_record_with_values_that_cannot_be_used_is_removed(self):
        self._leftover(total_cost="a lot")
        self.assertEqual(self._fold(), 0)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), [])

    def test_an_unpriced_record_is_not_logged_like_a_run_that_ended(self):
        self._leftover(total_cost=0.0, split={})
        self.assertEqual(self._fold(), 0)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), [])

    def test_a_split_record_gets_its_13th_field(self):
        self._leftover(params="mode=Max upgraded-from=claude-haiku-5-5@call71",
                       split={"claude-haiku-5-5": [0.077055, 4828, 53699, 96311, 3768425],
                              "claude-fable-5-1": [7.635504, 1564, 44544, 177423, 3174876]})
        self.assertEqual(self._fold(), 1)
        fields = self.fields()
        self.assertEqual(fields[12], "claude-haiku-5-5,0.077055,4828,53699,96311,3768425"
                                     "|claude-fable-5-1,7.635504,1564,44544,177423,3174876")
        self.assertEqual(fields[4], "mode=Max, upgraded-from=claude-haiku-5-5@call71, "
                                    "unfinished@call53")

    def test_a_record_served_by_another_model_than_it_names_is_split(self):
        self._leftover(split={"claude-opus-5": [7.774452, 18103, 48399, 108567, 3816385]})
        self.assertEqual(self._fold(), 1)
        self.assertEqual(self.fields()[12], "claude-opus-5,7.774452,18103,48399,108567,3816385")

    def test_a_record_without_calls_or_tokens_still_folds(self):
        self._leftover(calls=None, tokens=None, split={}, duration_secs=None)
        self.assertEqual(self._fold(), 1)
        fields = self.fields()
        self.assertEqual(fields[4], "mode=Max, speed=fast, unfinished")
        self.assertEqual(fields[5], "")
        self.assertEqual(fields[7], "")
        self.assertEqual(fields[8:12], ["", "", "", ""])

    def test_a_record_without_params_carries_just_the_marker(self):
        self._leftover(params="", calls=2)
        self.assertEqual(self._fold(), 1)
        self.assertEqual(self.fields()[4], "unfinished@call2")

    def test_a_record_without_a_time_is_stamped_now(self):
        record = self._leftover()
        del record["written"]
        progress_path(self.runs, self.PID).write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self._fold(), 1)
        self.assertRegex(self.fields()[0], STAMP)

    def test_names_in_a_record_cannot_split_the_line(self):
        self._leftover(instruction="odd; name\nhere", chat="chat;name\nhere")
        self.assertEqual(self._fold(), 1)
        fields = self.fields()
        self.assertEqual(len(fields), 14)
        self.assertEqual(fields[6], "odd, name here")
        self.assertEqual(fields[13], "chat,name here")

    def test_other_files_in_the_folder_are_ignored(self):
        others = ["notes.txt", "agent_run_abc.json", "agent_run_12.json.x1y2.tmp",
                  "agent_run_12.json.99.abcdef.claim", "agent_run_.json", "xagent_run_5.json",
                  "agent_run_5.jsonx"]
        for name in others:
            (self.runs / name).write_text(json.dumps(self._leftover()), encoding="utf-8")
        os.remove(progress_path(self.runs, self.PID))
        self.assertEqual(self._fold(), 0)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), sorted(others))

    def test_what_progress_write_saves_is_what_fold_in_logs(self):
        cached = usage(1000, 100, cache_creation_input_tokens=40, cache_read_input_tokens=7)
        run, _ = run_calls("claude-sonnet-5", cached, dict(cached))
        settings = dict(model="claude-sonnet-5", params="mode=Adaptive speed=fast", seconds=41.6,
                        instruction="Check the battery level", chat="Check_2026-03-04_092704")
        log_run(self.log, run, now=WHEN, **settings)
        finished = self.fields()
        self.log.unlink()

        self.assertIsNone(progress_write(self.runs, self.PID, run, boot_id="boot-a", **settings))
        self.assertEqual(self._fold(boot_id="boot-a"), 1)
        unfinished = self.fields()
        # The same line the run would have written at its end, but for the
        # time (the last completed call's) and the marker.
        self.assertRegex(unfinished[0], STAMP)
        self.assertEqual(unfinished[4], finished[4] + ", unfinished@call2")
        self.assertEqual(unfinished[1:4] + unfinished[5:], finished[1:4] + finished[5:])

    def test_a_log_that_cannot_be_written_keeps_the_record_for_next_time(self):
        self._leftover()
        before = progress_path(self.runs, self.PID).read_bytes()
        missing = self.dir / "no" / "such" / "folder" / "log.txt"
        self.assertEqual(progress_fold_in(self.runs, missing, is_alive=_dead), 0)
        self.assertEqual(self.record_names(), ["agent_run_4242.json"])
        self.assertEqual(progress_path(self.runs, self.PID).read_bytes(), before)
        self.assertEqual(self._fold(), 1)             # the next start, with a working log
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.record_names(), [])

    def test_the_line_is_added_to_a_log_that_already_has_lines(self):
        self.log.write_text("earlier line\n", encoding="utf-8", newline="\n")
        self._leftover()
        self.assertEqual(self._fold(), 1)
        lines = self.lines()
        self.assertEqual(lines[0], "earlier line")
        self.assertEqual(len(lines), 2)
        self.assertNotIn(b"\r", self.log.read_bytes())

    def test_several_dead_runs_are_each_logged_once(self):
        for pid in range(100, 110):
            self._leftover(pid=pid, chat=f"chat_{pid}")
        self.assertEqual(self._fold(), 10)
        self.assertEqual(sorted(line.split(";")[13] for line in self.lines()),
                         [f"chat_{pid}" for pid in range(100, 110)])
        self.assertEqual(self._fold(), 0)             # nothing is logged twice
        self.assertEqual(len(self.lines()), 10)


class ClaimRaceTests(TempDir):
    """Two processes that start together must not both log the same record."""

    def _leftovers(self, count):
        for pid in range(1000, 1000 + count):
            record = {"version": 1, "written": "2026-03-04 10:08:04", "provider": "Anthropic",
                      "model": "claude-opus-5-5", "params": "mode=Low", "total_cost": 0.25,
                      "had_usage": True, "duration_secs": 9.0, "instruction": "Race",
                      "calls": 3, "tokens": [1, 2, 3, 4], "split": {}, "chat": f"chat_{pid}",
                      "pid": pid, "boot_id": ""}
            progress_path(self.runs, pid).write_text(json.dumps(record), encoding="utf-8")
        return [f"chat_{pid}" for pid in range(1000, 1000 + count)]

    def _logged_chats(self, logs):
        return sorted(line.split(";")[13] for log in logs for line in self.lines(log))

    def test_the_loser_of_the_claim_logs_nothing(self):
        self._leftovers(1)
        real_rename = os.rename
        rival = []

        def rename_after_a_rival_got_there(source, target):
            if not rival:
                # Between this start's look at the folder and its claim,
                # another start claims and logs the same record.
                rival.append(None)
                rival[0] = progress_fold_in(self.runs, self.log, is_alive=_dead)
            return real_rename(source, target)

        with mock.patch.object(costs.os, "rename", rename_after_a_rival_got_there):
            mine = progress_fold_in(self.runs, self.log, is_alive=_dead)
        self.assertEqual(rival, [1])
        self.assertEqual(mine, 0)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.record_names(), [])

    # On Windows two racing renames of one file can both report success: the
    # file ends up under the later name. The next tests act that out, so the
    # handling is covered on every system.

    def test_a_claim_that_a_rival_then_moved_is_left_to_the_rival(self):
        self._leftovers(1)
        real_rename = os.rename
        rivals = []

        def rename_then_a_rival_moves_it_again(source, target):
            real_rename(source, target)                  # this start's rename "succeeds"
            rivals.append(Path(str(target) + ".rival"))
            real_rename(target, rivals[-1])              # the rival's lands after it

        with mock.patch.object(costs.os, "rename", rename_then_a_rival_moves_it_again):
            mine = progress_fold_in(self.runs, self.log, is_alive=_dead)
        self.assertEqual(mine, 0)
        self.assertEqual(self.lines(), [])
        self.assertTrue(rivals[0].exists())              # still there for the rival to log

    def _lock_claims(self, failures, then=None):
        """Make opening a claimed record fail `failures` times, then call `then`."""
        real_open = open
        left = [failures]

        def locked_open(path, *args, **kwargs):
            if str(path).endswith(".claim"):
                if left[0] > 0:
                    left[0] -= 1
                    raise PermissionError(13, "in use by another process")
                if then is not None:
                    then(Path(path))
            return real_open(path, *args, **kwargs)

        return mock.patch("builtins.open", locked_open)

    def test_a_claim_that_is_locked_for_a_moment_is_logged_when_it_opens(self):
        self._leftovers(1)
        with self._lock_claims(3), mock.patch.object(costs.time, "sleep") as sleep:
            self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=_dead), 1)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.record_names(), [])

    def test_a_claim_that_goes_while_it_is_locked_is_left_to_the_rival(self):
        self._leftovers(1)
        taken = []

        def rival_takes_it(claimed):
            taken.append(claimed.with_name(claimed.name + ".rival"))
            os.rename(claimed, taken[-1])

        with self._lock_claims(2, then=rival_takes_it), mock.patch.object(costs.time, "sleep"):
            self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=_dead), 0)
        self.assertEqual(self.lines(), [])
        self.assertTrue(taken[0].exists())

    def test_a_claim_that_stays_locked_is_put_back_for_the_next_start(self):
        self._leftovers(1)
        before = progress_path(self.runs, 1000).read_bytes()
        with self._lock_claims(10_000), mock.patch.object(costs.time, "sleep") as sleep:
            self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=_dead), 0)
        self.assertEqual(sleep.call_count, costs._CLAIM_OPEN_TRIES)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.record_names(), ["agent_run_1000.json"])
        self.assertEqual(progress_path(self.runs, 1000).read_bytes(), before)
        self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=_dead), 1)
        self.assertEqual(self.record_names(), [])

    def test_threads_racing_over_the_same_records_log_each_once(self):
        chats = self._leftovers(40)
        workers = 8
        logs = [self.dir / f"log_{n}.txt" for n in range(workers)]
        counts = [None] * workers
        gate = threading.Barrier(workers)

        def start(n):
            gate.wait(timeout=30)
            counts[n] = progress_fold_in(self.runs, logs[n], is_alive=_dead)

        threads = [threading.Thread(target=start, args=(n,)) for n in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        # A later start picks up anything a transient error made them all skip.
        late = progress_fold_in(self.runs, self.log, is_alive=_dead)
        self.assertEqual(sum(counts) + late, len(chats))
        self.assertEqual(self._logged_chats(logs + [self.log]), sorted(chats))
        self.assertEqual(self.record_names(), [])

    def test_processes_racing_over_the_same_records_log_each_once(self):
        chats = self._leftovers(40)
        workers = 2
        child = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "from robot import costs\n"
            "runs, log, ready, go = (Path(arg) for arg in sys.argv[1:5])\n"
            "ready.write_text('ready', encoding='utf-8')\n"
            "deadline = time.monotonic() + 60\n"
            "while not go.exists() and time.monotonic() < deadline:\n"
            "    time.sleep(0.001)\n"
            "print(costs.progress_fold_in(runs, log, is_alive=lambda pid: False))\n")
        logs = [self.dir / f"log_{n}.txt" for n in range(workers)]
        ready = [self.dir / f"ready_{n}" for n in range(workers)]
        go = self.dir / "go"
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        processes = [
            subprocess.Popen([sys.executable, "-c", child, str(self.runs), str(logs[n]),
                              str(ready[n]), str(go)],
                             cwd=REPO_ROOT, env=environment, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for n in range(workers)]
        try:
            for _ in range(6000):                 # up to a minute for them all to be ready
                if all(path.exists() for path in ready):
                    break
                time.sleep(0.01)
            go.write_text("go", encoding="utf-8")
            counts = []
            for process in processes:
                out, err = process.communicate(timeout=120)
                self.assertEqual(process.returncode, 0, err)
                counts.append(int(out.strip()))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        late = progress_fold_in(self.runs, self.log, is_alive=_dead)
        self.assertEqual(sum(counts) + late, len(chats))
        self.assertEqual(self._logged_chats(logs + [self.log]), sorted(chats))
        self.assertEqual(self.record_names(), [])


# -- telling whether a record's owner is still running ------------------------


class FakeProc(TempDir):
    """A stand-in /proc inside the temporary folder."""

    def setUp(self):
        super().setUp()
        self.proc = self.dir / "proc"
        self.proc.mkdir()
        patch = mock.patch.object(costs, "_PROC", self.proc)
        patch.start()
        self.addCleanup(patch.stop)

    def on_linux(self, yes=True):
        patch = mock.patch.object(costs, "_is_linux", return_value=yes)
        patch.start()
        self.addCleanup(patch.stop)

    def process(self, pid, *argv):
        folder = self.proc / str(pid)
        folder.mkdir()
        (folder / "cmdline").write_bytes(b"".join(arg.encode() + b"\0" for arg in argv))


class BootIdTests(FakeProc):
    def test_reads_the_kernels_boot_id(self):
        folder = self.proc / "sys" / "kernel" / "random"
        folder.mkdir(parents=True)
        (folder / "boot_id").write_text("0f1e2d3c-aaaa-bbbb-cccc-0123456789ab\n", encoding="ascii")
        self.assertEqual(current_boot_id(), "0f1e2d3c-aaaa-bbbb-cccc-0123456789ab")

    def test_empty_where_there_is_none(self):
        self.assertEqual(current_boot_id(), "")

    def test_on_this_machine(self):
        with mock.patch.object(costs, "_PROC", Path("/proc")):
            boot_id = current_boot_id()
        self.assertIsInstance(boot_id, str)
        if sys.platform.startswith("linux"):
            self.assertRegex(boot_id, r"^[0-9a-f-]{36}$")
            with mock.patch.object(costs, "_PROC", Path("/proc")):
                self.assertEqual(current_boot_id(), boot_id)
        elif not Path("/proc/sys/kernel/random/boot_id").exists():
            self.assertEqual(boot_id, "")


class ProcessIsRobotTests(FakeProc):
    def test_a_running_copy_of_the_program(self):
        self.on_linux()
        self.process(4242, "/home/robot/.venv/bin/python", "-m", "robot.main", "-l", "Name")
        self.assertIs(process_is_robot(4242), True)

    def test_the_windowed_interface_is_the_program_too(self):
        # Its runs keep the same in-progress records, so a chat started beside
        # it must not take one of them for a run that died.
        self.on_linux()
        self.process(4242, "/home/robot/.venv/bin/python", "-m", "robot.tui")
        self.assertIs(process_is_robot(4242), True)

    def test_another_program_with_the_same_pid(self):
        self.on_linux()
        self.process(4242, "/usr/bin/vim", "notes.txt")
        self.assertIs(process_is_robot(4242), False)

    def test_another_python_program_with_the_same_pid(self):
        self.on_linux()
        self.process(4242, "/home/robot/.venv/bin/python", "-m", "http.server")
        self.assertIs(process_is_robot(4242), False)

    def test_no_such_process(self):
        self.on_linux()
        self.assertIs(process_is_robot(4242), False)

    def test_a_process_with_an_empty_command_line(self):
        self.on_linux()
        self.process(4242)            # what a zombie shows
        self.assertIs(process_is_robot(4242), False)

    def test_a_pid_that_cannot_be_checked_counts_as_running(self):
        self.on_linux()
        self.assertIs(process_is_robot("not a pid"), True)
        self.assertIs(process_is_robot(None), True)
        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            self.assertIs(process_is_robot(4242), True)

    def test_anywhere_but_linux_every_process_counts_as_running(self):
        self.on_linux(False)
        self.assertIs(process_is_robot(4242), True)        # even with nothing to look at
        self.process(4243, "/usr/bin/vim")
        self.assertIs(process_is_robot(4243), True)

    def test_fold_in_with_this_check(self):
        self.on_linux()
        self.process(11, "python", "-m", "robot.main")          # still running
        self.process(22, "bash")                                # the PID was reused
        for pid in (11, 22, 33):                                # 33: no such process
            record = {"written": "2026-03-04 10:08:04", "model": "claude-opus-5-5",
                      "params": "mode=Low", "total_cost": 0.25, "had_usage": True,
                      "duration_secs": 9.0, "calls": 3, "tokens": [1, 2, 3, 4],
                      "chat": f"chat_{pid}", "pid": pid}
            progress_path(self.runs, pid).write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=process_is_robot), 2)
        self.assertEqual(sorted(line.split(";")[13] for line in self.lines()),
                         ["chat_22", "chat_33"])
        self.assertEqual(self.record_names(), ["agent_run_11.json"])

    def test_fold_in_off_linux_never_touches_a_record(self):
        self.on_linux(False)
        record = {"written": "2026-03-04 10:08:04", "model": "claude-opus-5-5",
                  "total_cost": 0.25, "had_usage": True, "calls": 3, "chat": "c"}
        progress_path(self.runs, 33).write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(progress_fold_in(self.runs, self.log, is_alive=process_is_robot,
                                          boot_id=current_boot_id()), 0)
        self.assertEqual(self.record_names(), ["agent_run_33.json"])

    def test_no_signal_is_ever_sent(self):
        # os.kill(pid, 0) tests for a process on Linux but ends it on Windows.
        self.on_linux()
        self.process(11, "python", "-m", "robot.main")
        record = {"written": "2026-03-04 10:08:04", "model": "m", "total_cost": 0.25,
                  "had_usage": True, "calls": 1, "pid": 22}
        progress_path(self.runs, 22).write_text(json.dumps(record), encoding="utf-8")
        with mock.patch.object(os, "kill", side_effect=AssertionError("a signal was sent")) as kill:
            process_is_robot(11)
            process_is_robot(22)
            process_is_robot(os.getpid())
            progress_fold_in(self.runs, self.log, is_alive=process_is_robot,
                             my_pid=os.getpid())
        kill.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs a real /proc")
    def test_against_a_real_process(self):
        with mock.patch.object(costs, "_PROC", Path("/proc")), \
                mock.patch.object(costs, "_is_linux", return_value=True):
            named = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                      "robot.main"])
            other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                # A process's command line is not always readable in the very
                # instant after it starts, so give it a moment to appear.
                deadline = time.monotonic() + 5
                while not process_is_robot(named.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertIs(process_is_robot(named.pid), True)
                self.assertIs(process_is_robot(other.pid), False)
            finally:
                for process in (named, other):
                    process.kill()
                    process.wait()
            self.assertIs(process_is_robot(named.pid), False)         # gone


class ModuleRules(unittest.TestCase):
    SOURCE = Path(costs.__file__).read_text(encoding="utf-8")
    TREE = ast.parse(SOURCE)

    def test_only_the_standard_library_is_imported(self):
        imported = set()
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"importlib", "json", "os", "re", "sys", "tempfile", "time",
                                    "uuid", "dataclasses", "datetime", "pathlib"})

    def test_the_source_is_plain_ascii(self):
        self.assertTrue(self.SOURCE.isascii())

    def test_nothing_in_the_module_can_send_a_signal(self):
        attributes = {node.attr for node in ast.walk(self.TREE) if isinstance(node, ast.Attribute)}
        names = {node.id for node in ast.walk(self.TREE) if isinstance(node, ast.Name)}
        for forbidden in ("kill", "killpg", "terminate", "send_signal"):
            self.assertNotIn(forbidden, attributes)
            self.assertNotIn(forbidden, names)

    def test_public_names(self):
        for name in ("cost_line", "RunCost", "split_field", "format_log_line", "log_run",
                     "progress_path", "progress_write", "progress_clear", "progress_fold_in",
                     "current_boot_id", "process_is_robot"):
            self.assertTrue(callable(getattr(costs, name)), name)


if __name__ == "__main__":
    unittest.main()
