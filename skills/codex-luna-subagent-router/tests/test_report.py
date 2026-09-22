from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import report
import runtime_support


def snap(status="complete", total=100, input_tokens=80, cached=60, output=20, model="gpt-6-luna", effort="high", reasons=None):
    return {
        "status": status,
        "source": "codex_rollout_v1",
        "counts": {
            "total_tokens": total,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached,
            "output_tokens": output,
            "reasoning_output_tokens": 5 if output is not None else None,
        },
        "reasons": list(reasons or []),
        "usage_events": 1,
        "last_usage_at": "2026-09-16T10:00:00+00:00",
        "model": model,
        "effort": effort,
        "terminal_observed": status == "complete",
        "bytes_read": 123,
    }


def sample_data():
    worker = {
        "schema_version": "1.0", "usage_id": "u", "agent_id": "agent-a", "parent_id": "parent-a",
        "agent_type": "luna_high", "scope_id": "project-demo", "started_at": "2026-09-16T09:00:00+00:00",
        "updated_at": "2026-09-16T10:00:00+00:00", "receipt_id": None, "snapshot": snap(),
        "reader_version": "2.6.1", "summary": "ok", "diagnostics": {}, "display": {},
    }
    turn = {
        "schema_version": "1.1", "session_id": "parent-a", "turn_id": "turn-a", "scope_id": "project-demo",
        "started_at": "2026-09-16T09:00:00+00:00", "updated_at": "2026-09-16T10:00:00+00:00",
        "phase": "sealed", "main_snapshot": snap(total=200, input_tokens=170, cached=100, output=30, model="gpt-6-astra"),
        "child_snapshots": {"agent-a": snap()}, "excluded_children": 0, "reader_version": "2.6.1",
        "boundary_reason": None, "summary": "turn", "registered_children": 1, "diagnostics": {},
    }
    return {
        "outcomes": {
            "registry": "/private/home/outcomes.jsonl", "scope": "project-demo", "total_outcomes": 2,
            "outcomes": {"verified_pass": 1, "partial": 1},
            "by_model": [{"model": "gpt-6-luna", "effort": "high", "outcome": "verified_pass", "count": 1}],
            "pending_count": 0, "available_recommendations": [], "sparse_buckets": 0,
        },
        "subagents": {
            "usage_file": "/private/home/usage.jsonl", "observed_subagents": 1, "statuses": {"complete": 1},
            "known_usage": {"counts": snap()["counts"], "display": {}, "field_coverage": {}},
            "completeness": {"status": "complete", "counts": snap()["counts"], "reasons": [], "field_coverage": {},
                             "observed": 1, "complete": 1, "waiting": 0, "partial": 0, "unavailable": 0},
            "by_model": [{"model": "gpt-6-luna", "effort": "high", "workers": 1, "counts": snap()["counts"],
                          "display": {}, "field_coverage": {}}],
            "workers": [worker],
        },
        "turns": {"summary": report._turn_summary([turn]), "records": [turn]},
    }


class ReportTests(unittest.TestCase):
    def test_collect_reuses_existing_stats_apis(self):
        with patch.object(report.store, "default_registry_path", return_value=Path("/tmp/outcomes.jsonl")), \
             patch.object(report.token_usage, "default_usage_path", return_value=Path("/tmp/usage.jsonl")), \
             patch.object(report.route_advisor, "stats", return_value={"route": True}) as route_stats, \
             patch.object(report.token_usage, "statistics", return_value={"workers": []}) as token_stats, \
             patch.object(report.turn_usage, "statistics", return_value=[]) as turn_stats:
            result = report.collect("project-test")
        route_stats.assert_called_once_with(Path("/tmp/outcomes.jsonl"), scope="project-test")
        token_stats.assert_called_once_with(Path("/tmp/usage.jsonl"), scope="project-test")
        turn_stats.assert_called_once_with(Path("/tmp/usage.jsonl"), scope="project-test")
        self.assertEqual(result["turns"]["summary"]["registered_turns"], 0)

    def test_report_writes_markdown_json_and_csv_without_local_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, md_path, json_path, csv_path = report.write_report(sample_data(), "project-demo", "current", Path(tmp))
            self.assertEqual(payload["router_version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())
            self.assertIn(f"`Router v{payload['router_version']}`", md_path.read_text(encoding="utf-8"))
            self.assertTrue(md_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())
            exported = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("registry", exported["data"]["outcomes"])
            self.assertNotIn("usage_file", exported["data"]["subagents"])
            brief = md_path.read_text(encoding="utf-8")
            self.assertIn("📊 Codex Router · 数据简报", brief)
            self.assertIn("## 核心指标", brief)
            self.assertIn("## Token 完整度", brief)
            self.assertIn("## 已知用量", brief)
            self.assertIn("## 模型使用", brief)
            self.assertIn("## 验收结果", brief)
            self.assertIn("## ⚠️ 需要关注", brief)
            self.assertIn("不执行 `refresh`", brief)
            self.assertIn("brief.md`：与聊天中显示相同的固定面板", brief)
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            types = {row["record_type"] for row in rows}
            self.assertTrue({"outcome_summary", "outcome_route", "subagent", "turn_main", "turn_child"} <= types)
            self.assertEqual(next(row for row in rows if row["record_type"] == "subagent")["total_tokens"], "100")

    def test_fixed_panel_section_order_is_stable(self):
        text = report.markdown({"generated_at": "2026-09-16T10:00:00Z", "router_version": "2.6.2",
                                "scope": {"scope_id": "project-demo", "mode": "current"}, "data": sample_data()})
        headings = ["## 核心指标", "## Token 完整度", "## 已知用量", "## 模型使用",
                    "## 验收结果", "## ⚠️ 需要关注", "## 数据文件", "## 口径说明"]
        positions = [text.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("| ✅ Verified pass | **1** | ❌ Verified fail | **0** |", text)
        self.assertIn("| SubAgent | 1 | 0 | 0 | 0 |", text)

    def test_dispatch_exposes_single_report_command(self):
        import subprocess
        process = subprocess.run(
            [sys.executable, *runtime_support.FLAGS, str(ROOT / "scripts/runtime_dispatch.py"), "report", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("--output-dir", process.stdout)
        self.assertIn("--all-scopes", process.stdout)

    def test_markdown_never_calls_refresh(self):
        data = sample_data()
        with patch.object(report.token_usage, "refresh", side_effect=AssertionError("must not refresh")), \
             patch.object(report.turn_usage, "refresh", side_effect=AssertionError("must not refresh")):
            text = report.markdown({"generated_at": "2026-09-16T10:00:00Z", "router_version": "2.6.2",
                                    "scope": {"scope_id": "project-demo", "mode": "current"}, "data": data})
        self.assertIn("只读", text)


if __name__ == "__main__":
    unittest.main()
