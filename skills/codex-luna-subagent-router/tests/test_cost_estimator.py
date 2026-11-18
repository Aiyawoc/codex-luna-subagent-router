from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_estimator  # noqa: E402


class CostEstimatorTests(unittest.TestCase):
    def test_luna_short_context_estimate_splits_cached_subset(self):
        result = cost_estimator.estimate("gpt-6-luna", {
            "input_tokens": 200_000,
            "cached_input_tokens": 120_000,
            "output_tokens": 20_000,
        })
        # 0.08M*$0.10 + 0.12M*$0.01 + 0.02M*$0.50 = $0.0192
        self.assertEqual(result["estimated_usd"], 0.0192)
        self.assertEqual(result["context_class"], "short")

    def test_long_context_uses_published_long_context_rates(self):
        result = cost_estimator.estimate("gpt-6.1-sol", {
            "input_tokens": 300_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 20_000,
        })
        self.assertEqual(result["context_class"], "long")
        # 0.2M*$4 + 0.1M*$0.20 + 0.02M*$15 = $1.12
        self.assertEqual(result["estimated_usd"], 1.12)
        self.assertEqual(result["pricing_granularity"], "request")

    def test_receipt_interval_above_threshold_is_not_guessed_long(self):
        result = cost_estimator.estimate("gpt-6.1-sol", {
            "input_tokens": 400_000,
            "cached_input_tokens": 200_000,
            "output_tokens": 40_000,
        }, granularity="receipt_interval")
        self.assertEqual(result["status"], "incomplete_pricing_granularity")
        self.assertEqual(result["reason"], "request_level_context_class_unknown")
        self.assertEqual(result["pricing_granularity"], "receipt_interval")
        self.assertIsNone(result["estimated_usd"])
        self.assertNotIn("context_class", result)

    def test_receipt_interval_at_or_below_threshold_proves_short(self):
        result = cost_estimator.estimate("gpt-6.1-sol", {
            "input_tokens": 272_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 20_000,
        }, granularity="receipt_interval")
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["context_class"], "short")
        self.assertEqual(result["pricing_granularity"], "receipt_interval")

    def test_short_context_sol61_retains_historical_cached_rate(self):
        result = cost_estimator.estimate("gpt-6.1-sol", {
            "input_tokens": 200_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 20_000,
        })
        self.assertEqual(result["context_class"], "short")
        self.assertEqual(result["rates_per_million_usd"]["cached"], 0.10)
        self.assertEqual(result["estimated_usd"], 0.41)

    def test_gpt62_standard_rates_and_historical_rates_stay_separate(self):
        counts = {"input_tokens": 200_000, "cached_input_tokens": 100_000, "output_tokens": 20_000}
        expected = {
            "gpt-6.1-terra": (0.205, {"input": 1.0, "cached": 0.05, "output": 5.0}),
            "gpt-6.2-sol": (0.41, {"input": 2.0, "cached": 0.10, "output": 10.0}),
            "gpt-6.2-astra": (1.64, {"input": 8.0, "cached": 0.40, "output": 40.0}),
            "gpt-6.1-sol": (0.41, {"input": 2.0, "cached": 0.10, "output": 10.0}),
            "gpt-6-astra": (2.10, {"input": 10.0, "cached": 1.0, "output": 50.0}),
            "gpt-6-sol": (0.42, {"input": 2.0, "cached": 0.20, "output": 10.0}),
        }
        for model, (amount, rates) in expected.items():
            with self.subTest(model=model):
                result = cost_estimator.estimate(model, counts)
                self.assertEqual(result["model"], model)
                self.assertEqual(result["estimated_usd"], amount)
                self.assertEqual(result["rates_per_million_usd"], rates)
                self.assertIn("cache_writes", result["excluded_costs"])

    def test_gpt62_long_context_charges_whole_request_at_long_rates(self):
        counts = {"input_tokens": 300_000, "cached_input_tokens": 100_000, "output_tokens": 20_000}
        for model, amount in (("gpt-6.1-terra", 0.56), ("gpt-6.2-sol", 1.12), ("gpt-6.2-astra", 4.48)):
            with self.subTest(model=model):
                result = cost_estimator.estimate(model, counts)
                self.assertEqual(result["context_class"], "long")
                self.assertEqual(result["estimated_usd"], amount)

    def test_gpt62_long_context_boundary_is_strictly_above_272k(self):
        below = cost_estimator.estimate("gpt-6.2-astra", {
            "input_tokens": 272_000, "cached_input_tokens": 0, "output_tokens": 1_000,
        })
        above = cost_estimator.estimate("gpt-6.2-astra", {
            "input_tokens": 272_001, "cached_input_tokens": 0, "output_tokens": 1_000,
        })
        self.assertEqual((below["context_class"], below["estimated_usd"]), ("short", 2.216))
        self.assertEqual((above["context_class"], above["estimated_usd"]), ("long", 4.412016))

    def test_gpt62_aggregate_usage_does_not_invent_request_context_class(self):
        for model in ("gpt-6.2-sol", "gpt-6.2-astra"):
            with self.subTest(model=model):
                result = cost_estimator.estimate(model, {
                    "input_tokens": 400_000, "cached_input_tokens": 200_000, "output_tokens": 40_000,
                }, granularity="receipt_interval")
                self.assertEqual(result["status"], "incomplete_pricing_granularity")
                self.assertIsNone(result["estimated_usd"])

    def test_reasoning_tokens_are_not_required_or_double_counted(self):
        base = {"input_tokens": 100_000, "cached_input_tokens": 50_000, "output_tokens": 20_000}
        a = cost_estimator.estimate("gpt-6.1-sol", base)
        b = cost_estimator.estimate("gpt-6.1-sol", dict(base, reasoning_output_tokens=19_000))
        self.assertEqual(a["estimated_usd"], b["estimated_usd"])

    def test_missing_cache_detail_is_incomplete_not_assumed_zero(self):
        result = cost_estimator.estimate("gpt-6-astra", {
            "input_tokens": 1000, "cached_input_tokens": None, "output_tokens": 100,
        })
        self.assertEqual(result["status"], "incomplete_usage")
        self.assertIsNone(result["estimated_usd"])

    def test_unknown_model_is_unsupported(self):
        result = cost_estimator.estimate("unknown-model", {
            "input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1,
        })
        self.assertEqual(result["status"], "unsupported_model")
        self.assertIsNone(result["estimated_usd"])

    def test_cached_input_cannot_exceed_input(self):
        with self.assertRaisesRegex(cost_estimator.CostEstimateError, "cannot exceed"):
            cost_estimator.estimate("gpt-6-luna", {
                "input_tokens": 10, "cached_input_tokens": 11, "output_tokens": 1,
            })

    def test_unknown_pricing_granularity_is_rejected(self):
        with self.assertRaisesRegex(cost_estimator.CostEstimateError, "granularity"):
            cost_estimator.estimate("gpt-6-luna", {
                "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1,
            }, granularity="session")


if __name__ == "__main__":
    unittest.main()
