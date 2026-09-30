from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route_economics  # noqa: E402
import runtime_support  # noqa: E402


def outcome(receipt_id, result="verified_pass", scope="project-x"):
    return {"receipt_id": receipt_id, "outcome": result, "scope_id": scope}


def usage(model, effort, input_tokens=200_000, cached=100_000, output=20_000):
    return {
        "snapshot": {
            "model": model,
            "effort": effort,
            "counts": {
                "total_tokens": input_tokens + output,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached,
                "output_tokens": output,
                "reasoning_output_tokens": 10_000,
            },
        }
    }


class RouteEconomicsTests(unittest.TestCase):
    def test_runtime_dispatch_exposes_route_economics(self):
        process = subprocess.run(
            [sys.executable, *runtime_support.FLAGS, str(ROOT / "scripts/runtime_dispatch.py"), "route_economics", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("--all-scopes", process.stdout)

    def test_collect_uses_exact_receipt_usage_and_groups_routes(self):
        records = [outcome("r1"), outcome("r2", "verified_fail"), outcome("r3")]
        receipts = {
            "r1": usage("gpt-6-luna", "high"),
            "r2": usage("gpt-6.1-sol", "high"),
            "r3": usage("gpt-6-luna", "high"),
        }
        with patch.object(route_economics.store, "read_records", return_value=(records, {"invalid_lines": 0})), \
             patch.object(route_economics.token_usage, "for_receipt", side_effect=lambda path, rid: receipts[rid]):
            result = route_economics.collect(Path("outcomes.jsonl"), Path("usage.jsonl"), scope="project-x")
        self.assertEqual(result["matched_receipts"], 3)
        self.assertEqual(result["estimated_attempts"], 3)
        self.assertFalse(result["authoritative"])
        self.assertTrue(result["routing_unchanged"])
        luna = next(item for item in result["routes"] if item["model"] == "gpt-6-luna")
        sol = next(item for item in result["routes"] if item["model"] == "gpt-6.1-sol")
        self.assertEqual(luna["attempts"], 2)
        self.assertEqual(luna["outcomes"], {"verified_pass": 2})
        self.assertEqual(sol["outcomes"], {"verified_fail": 1})

    def test_missing_receipt_and_missing_usage_are_coverage_gaps(self):
        records = [dict(outcome("r1")), {"scope_id": "project-x", "outcome": "partial"}]
        with patch.object(route_economics.store, "read_records", return_value=(records, {})), \
             patch.object(route_economics.token_usage, "for_receipt", return_value=None):
            result = route_economics.collect(Path("outcomes.jsonl"), Path("usage.jsonl"), scope="project-x")
        self.assertEqual(result["missing_receipt"], 1)
        self.assertEqual(result["missing_usage"], 1)
        self.assertEqual(result["estimated_attempts"], 0)
        self.assertEqual(result["estimated_usd"], 0.0)

    def test_incomplete_cached_detail_is_not_estimated(self):
        bad = usage("gpt-6.1-sol", "high")
        bad["snapshot"]["counts"]["cached_input_tokens"] = None
        with patch.object(route_economics.store, "read_records", return_value=([outcome("r1")], {})), \
             patch.object(route_economics.token_usage, "for_receipt", return_value=bad):
            result = route_economics.collect(Path("outcomes.jsonl"), Path("usage.jsonl"), scope="project-x")
        self.assertEqual(result["routes"][0]["incomplete_usage"], 1)
        self.assertEqual(result["routes"][0]["estimated_attempts"], 0)

    def test_scope_filter_prevents_cross_project_cost_mix(self):
        records = [outcome("r1", scope="project-x"), outcome("r2", scope="project-y")]
        with patch.object(route_economics.store, "read_records", return_value=(records, {})), \
             patch.object(route_economics.token_usage, "for_receipt", return_value=usage("gpt-6-luna", "high")) as lookup:
            result = route_economics.collect(Path("outcomes.jsonl"), Path("usage.jsonl"), scope="project-x")
        self.assertEqual(result["outcome_records"], 1)
        self.assertEqual(lookup.call_count, 1)


if __name__ == "__main__":
    unittest.main()
