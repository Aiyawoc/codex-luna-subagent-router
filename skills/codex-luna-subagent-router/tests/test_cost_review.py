from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_review  # noqa: E402
import runtime_support  # noqa: E402


def axes(**overrides):
    value = {
        "task_kind": "implementation",
        "task_scope": "bounded",
        "reasoning_depth": "medium",
        "verifiability": "yes",
        "failure_cost": "medium",
        "context_volume": "medium",
    }
    value.update(overrides)
    return value


def record(receipt_id, model, effort, *, family="same-family", outcome="verified_pass", axis=None):
    return {
        "receipt_id": receipt_id,
        "scope_id": "project-x",
        "task_family": family,
        "axes": dict(axis or axes()),
        "model": model,
        "effort": effort,
        "outcome": outcome,
    }


def usage(model, effort, *, input_tokens, cached_tokens, output_tokens):
    return {
        "snapshot": {
            "model": model,
            "effort": effort,
            "counts": {
                "total_tokens": input_tokens + output_tokens,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": output_tokens,
                "reasoning_output_tokens": 0,
            },
        }
    }


class CostReviewTests(unittest.TestCase):
    def test_runtime_dispatch_exposes_cost_review(self):
        process = subprocess.run(
            [sys.executable, *runtime_support.FLAGS, str(ROOT / "scripts/runtime_dispatch.py"), "cost_review", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("--min-candidate-passes", process.stdout)

    def test_clean_lower_capability_route_becomes_review_candidate(self):
        rows = [
            record(f"luna{i}", "gpt-6-luna", "high") for i in range(3)
        ] + [
            record(f"sol{i}", "gpt-6.1-sol", "high") for i in range(2)
        ]
        receipts = {
            **{f"luna{i}": usage("gpt-6-luna", "high", input_tokens=100_000, cached_tokens=50_000, output_tokens=10_000) for i in range(3)},
            **{f"sol{i}": usage("gpt-6.1-sol", "high", input_tokens=100_000, cached_tokens=50_000, output_tokens=10_000) for i in range(2)},
        }
        with patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
             patch.object(cost_review.token_usage, "for_receipt", side_effect=lambda path, rid: receipts[rid]):
            result = cost_review.collect(Path("outcomes.jsonl"), Path("usage.jsonl"), scope="project-x")
        self.assertEqual(result["review_candidate_count"], 1)
        candidate = result["review_candidates"][0]
        self.assertEqual(candidate["candidate_route"], {"model": "gpt-6-luna", "effort": "high"})
        self.assertEqual(candidate["comparison_route"], {"model": "gpt-6.1-sol", "effort": "high"})
        self.assertLess(candidate["observed_cost_ratio"], 0.75)
        self.assertFalse(candidate["automatic_override"])
        self.assertFalse(result["authoritative"])

    def test_any_candidate_failure_or_partial_blocks_review(self):
        rows = [
            record("l1", "gpt-6-luna", "high"),
            record("l2", "gpt-6-luna", "high"),
            record("l3", "gpt-6-luna", "high"),
            record("lf", "gpt-6-luna", "high", outcome="verified_fail"),
            record("s1", "gpt-6.1-sol", "high"),
            record("s2", "gpt-6.1-sol", "high"),
        ]
        receipts = {
            rid: usage("gpt-6-luna" if rid.startswith("l") else "gpt-6.1-sol", "high",
                       input_tokens=100_000, cached_tokens=50_000, output_tokens=10_000)
            for rid in ("l1", "l2", "l3", "lf", "s1", "s2")
        }
        with patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
             patch.object(cost_review.token_usage, "for_receipt", side_effect=lambda path, rid: receipts[rid]):
            result = cost_review.collect(Path("o"), Path("u"), scope="project-x")
        self.assertEqual(result["review_candidate_count"], 0)

        rows[3] = record("lp", "gpt-6-luna", "high", outcome="partial")
        with patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
             patch.object(cost_review.token_usage, "for_receipt", side_effect=lambda path, rid: receipts.get(rid)):
            result = cost_review.collect(Path("o"), Path("u"), scope="project-x")
        self.assertEqual(result["review_candidate_count"], 0)

    def test_unsafe_axes_never_enter_review(self):
        for unsafe in (
            axes(task_kind="architecture"),
            axes(reasoning_depth="deep"),
            axes(failure_cost="high"),
            axes(context_volume="high"),
            axes(verifiability="partial"),
            axes(task_scope="workflow"),
        ):
            rows = [
                *[record(f"l{i}", "gpt-6-luna", "high", axis=unsafe) for i in range(3)],
                *[record(f"s{i}", "gpt-6.1-sol", "high", axis=unsafe) for i in range(2)],
            ]
            with self.subTest(unsafe=unsafe), \
                 patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
                 patch.object(cost_review.token_usage, "for_receipt", return_value=usage(
                     "gpt-6-luna", "high", input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000)):
                result = cost_review.collect(Path("o"), Path("u"), scope="project-x")
                self.assertEqual(result["review_candidate_count"], 0)
                self.assertEqual(result["safe_groups"], 0)

    def test_family_or_axes_mismatch_prevents_comparison(self):
        rows = [
            *[record(f"l{i}", "gpt-6-luna", "high", family="family-a") for i in range(3)],
            *[record(f"s{i}", "gpt-6.1-sol", "high", family="family-b") for i in range(2)],
        ]
        with patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
             patch.object(cost_review.token_usage, "for_receipt", side_effect=lambda path, rid: usage(
                 "gpt-6-luna" if rid.startswith("l") else "gpt-6.1-sol", "high",
                 input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000)):
            result = cost_review.collect(Path("o"), Path("u"), scope="project-x")
        self.assertEqual(result["comparable_groups"], 0)
        self.assertEqual(result["review_candidate_count"], 0)

    def test_missing_exact_usage_does_not_satisfy_pass_threshold(self):
        rows = [
            *[record(f"l{i}", "gpt-6-luna", "high") for i in range(3)],
            *[record(f"s{i}", "gpt-6.1-sol", "high") for i in range(2)],
        ]
        receipts = {
            "l0": usage("gpt-6-luna", "high", input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000),
            "l1": usage("gpt-6-luna", "high", input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000),
            "s0": usage("gpt-6.1-sol", "high", input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000),
            "s1": usage("gpt-6.1-sol", "high", input_tokens=10_000, cached_tokens=5_000, output_tokens=1_000),
        }
        with patch.object(cost_review.store, "read_records", return_value=(rows, {})), \
             patch.object(cost_review.token_usage, "for_receipt", side_effect=lambda path, rid: receipts.get(rid)):
            result = cost_review.collect(Path("o"), Path("u"), scope="project-x")
        self.assertEqual(result["review_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
