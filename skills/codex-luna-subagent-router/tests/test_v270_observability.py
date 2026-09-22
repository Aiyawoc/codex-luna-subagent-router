from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decision_store  # noqa: E402
import planning_store  # noqa: E402
import report  # noqa: E402


class V270ObservabilityTests(unittest.TestCase):
    def test_planning_store_keeps_counts_not_task_content(self):
        plan = {
            "routing_mode": "adaptive",
            "lead_model": "gpt-5.6-sol",
            "lead_effort": "high",
            "decisions": [
                {"execution_shape": "local_parallel_tools"},
                {"execution_shape": "subagent"},
            ],
            "workers": [{"worker_id": "private-task-id"}],
            "ready_worker_ids": ["private-task-id"],
            "open_workers": 0,
            "effective_wave_limit": 3,
            "runtime_health": "healthy",
            "effective_runtime_health": "healthy",
            "runtime_health_action": "use_ready_wave",
            "health_probe_worker_id": None,
        }
        row = planning_store.from_plan(plan, "project-test")
        raw = json.dumps(row)
        self.assertNotIn("private-task-id", raw)
        self.assertEqual(row["execution_shapes"]["local_parallel_tools"], 1)
        self.assertEqual(row["execution_shapes"]["subagent"], 1)

    def test_planning_statistics_are_scope_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "planning.jsonl"
            base = {
                "routing_mode": "adaptive",
                "lead_model": "gpt-5.6-sol",
                "lead_effort": "high",
                "decisions": [{"execution_shape": "local_serial"}],
                "workers": [],
                "ready_worker_ids": [],
                "open_workers": 0,
                "effective_wave_limit": 3,
                "runtime_health": "healthy",
                "effective_runtime_health": "healthy",
                "runtime_health_action": "use_ready_wave",
                "health_probe_worker_id": None,
            }
            planning_store.append(path, planning_store.from_plan(base, "project-a"))
            planning_store.append(path, planning_store.from_plan(base, "project-b"))
            stats = planning_store.statistics(path, "project-a")
            self.assertEqual(stats["plans"], 1)
            self.assertEqual(stats["execution_shapes"]["local_serial"], 1)

    def test_report_collects_planning_and_shadow_without_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            registry = home / "state/codex-luna-subagent-router/outcomes.jsonl"
            registry.parent.mkdir(parents=True)
            planning_store.append(
                planning_store.default_path(registry),
                planning_store.from_plan(
                    {
                        "routing_mode": "adaptive",
                        "lead_model": "gpt-5.6-sol",
                        "lead_effort": "high",
                        "decisions": [{"execution_shape": "local_parallel_tools"}],
                        "workers": [],
                        "ready_worker_ids": [],
                        "open_workers": 0,
                        "effective_wave_limit": 3,
                        "runtime_health": "healthy",
                        "effective_runtime_health": "healthy",
                        "runtime_health_action": "use_ready_wave",
                        "health_probe_worker_id": None,
                    },
                    "project-a",
                ),
            )
            decision_path = home / "state/codex-luna-subagent-router/decisions.jsonl"
            decision_store.append(
                decision_path,
                {
                    "checkpoint_id": "a" * 32,
                    "scope_id": "project-a",
                    "task_family": "repo-scan",
                    "provider": "jev_ask",
                    "provider_model": "jev-test",
                    "status": "available",
                    "reason": None,
                    "latency_ms": 10,
                    "confidence": 0.9,
                    "lease": "checkpoint",
                    "answers": {"task_kind": "scan"},
                },
            )
            with (
                patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                patch.object(report.store, "default_registry_path", return_value=registry),
                patch.object(report.decision_store, "default_path", return_value=decision_path),
                patch.object(
                    report.route_advisor,
                    "stats",
                    return_value={
                        "scope": "project-a",
                        "outcomes": {},
                        "by_model": [],
                        "pending_count": 0,
                        "available_recommendations": [],
                    },
                ),
                patch.object(
                    report.token_usage,
                    "statistics",
                    return_value={
                        "workers": [],
                        "observed_subagents": 0,
                        "known_usage": {"counts": {}},
                        "completeness": {},
                        "by_model": [],
                    },
                ),
                patch.object(report.turn_usage, "statistics", return_value=[]),
            ):
                data = report.collect("project-a")
            self.assertEqual(data["planning"]["execution_shapes"]["local_parallel_tools"], 1)
            self.assertEqual(data["decisions"]["available"], 1)
            brief = report.markdown(
                {
                    "generated_at": "2026-09-22T00:00:00Z",
                    "router_version": "2.7.0",
                    "scope": {"scope_id": "project-a", "mode": "current"},
                    "data": data,
                }
            )
            self.assertIn("## 执行规划", brief)
            self.assertIn("## Decision Shadow", brief)


if __name__ == "__main__":
    unittest.main()
