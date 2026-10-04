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

    def test_short_context_sol61_uses_current_cached_rate(self):
        result = cost_estimator.estimate("gpt-6.1-sol", {
            "input_tokens": 200_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 20_000,
        })
        self.assertEqual(result["context_class"], "short")
        self.assertEqual(result["rates_per_million_usd"]["cached"], 0.10)
        self.assertEqual(result["estimated_usd"], 0.41)

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
