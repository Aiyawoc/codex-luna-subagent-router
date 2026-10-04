from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_store as bench  # noqa: E402
import runtime_support  # noqa: E402


class BenchmarkStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.path = self.base / "benchmark.jsonl"
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def row(self, **overrides):
        values = dict(
            workload_id="parallel-read-scan",
            variant="router_adaptive",
            backend="codex_desktop",
            host_version="26.928.20755",
            outcome="pass",
            execution_primitive="native_parallel_tools",
            total_tokens=1000,
            elapsed_ms=500,
            tool_calls=3,
            workers=0,
            retries=0,
            cost_usd=None,
            cost_source=None,
            evidence_coverage="full",
        )
        values.update(overrides)
        return bench.observation(**values)

    def test_unknown_metrics_remain_null_and_are_not_zero_filled(self):
        row = self.row(total_tokens=None, elapsed_ms=None, evidence_coverage="partial")
        bench.append(self.path, row)
        result = bench.statistics(self.path)
        group = result["groups"][0]
        self.assertIsNone(group["total_tokens"]["average"])
        self.assertEqual(group["total_tokens"]["unknown_passes"], 1)
        self.assertIsNone(group["elapsed_ms"]["average"])
        self.assertFalse(result["automatic_routing_change"])

    def test_stats_compare_variants_without_auto_ranking(self):
        for variant, tokens in (
            ("host_default", 1200),
            ("router_luna_only", 900),
            ("router_adaptive", 800),
        ):
            bench.append(self.path, self.row(variant=variant, total_tokens=tokens))
        result = bench.statistics(self.path)
        self.assertEqual(len(result["groups"]), 3)
        self.assertTrue(all(group["success_rate"] == 1.0 for group in result["groups"]))
        self.assertNotIn("winner", result)
        self.assertFalse(result["authoritative"])

    def test_failed_runs_count_against_success_rate_but_not_pass_metric_average(self):
        bench.append(self.path, self.row(total_tokens=1000))
        bench.append(self.path, self.row(outcome="fail", total_tokens=9000))
        result = bench.statistics(self.path)
        group = result["groups"][0]
        self.assertEqual(group["success_rate"], 0.5)
        self.assertEqual(group["total_tokens"]["average"], 1000)

    def test_cost_requires_explicit_source(self):
        with self.assertRaisesRegex(Exception, "cost_source"):
            self.row(cost_usd=0.5)
        row = self.row(cost_usd=0.5, cost_source="request_level_estimate")
        self.assertEqual(row["cost_usd"], 0.5)

    def test_filters_are_exact_backend_and_host_version(self):
        bench.append(self.path, self.row())
        bench.append(self.path, self.row(host_version="26.929.0"))
        result = bench.statistics(
            self.path, backend="codex_desktop", host_version="26.928.20755"
        )
        self.assertEqual(result["rows"], 1)

    def test_ledger_contains_no_prompt_paths_or_freeform_notes(self):
        bench.append(self.path, self.row())
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.home), raw)
        payload = json.loads(raw)
        self.assertEqual(set(payload), bench.ROW_FIELDS)
        self.assertFalse(any(key in payload for key in ("prompt", "message", "path", "notes")))

    def test_comparison_requires_full_evidence_and_does_not_pick_winner(self):
        bench.append(self.path, self.row(
            variant="host_default", total_tokens=1200, elapsed_ms=700,
        ))
        bench.append(self.path, self.row(
            variant="router_adaptive", total_tokens=800, elapsed_ms=500,
        ))
        result = bench.comparisons(
            self.path, backend="codex_desktop", host_version="26.928.20755"
        )
        self.assertEqual(result["eligible_for_review"], 1)
        row = result["comparisons"][0]
        self.assertEqual(row["status"], "eligible_for_review")
        self.assertEqual(row["metrics"]["total_tokens"]["ratio"], round(800 / 1200, 6))
        self.assertFalse(row["automatic_routing_change"])
        self.assertNotIn("winner", result)

    def test_lower_success_or_partial_evidence_blocks_review(self):
        bench.append(self.path, self.row(variant="host_default"))
        bench.append(self.path, self.row(
            variant="router_adaptive", outcome="fail", evidence_coverage="full"
        ))
        bench.append(self.path, self.row(
            variant="router_luna_only", evidence_coverage="partial"
        ))
        result = bench.comparisons(self.path)
        rows = {row["variant"]: row for row in result["comparisons"]}
        self.assertIn("success_rate_lower_than_baseline", rows["router_adaptive"]["reasons"])
        self.assertIn("full_evidence_required", rows["router_luna_only"]["reasons"])
        self.assertEqual(result["eligible_for_review"], 0)

    def test_runtime_dispatch_exposes_benchmark_store(self):
        result = subprocess.run(
            [
                sys.executable, *runtime_support.FLAGS,
                str(ROOT / "scripts/runtime_dispatch.py"),
                "benchmark_store", "--file", str(self.path), "stats", "--json",
            ],
            env={**os.environ, "CODEX_HOME": str(self.home)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["rows"], 0)
        self.assertFalse(payload["automatic_routing_change"])


if __name__ == "__main__":
    unittest.main()
