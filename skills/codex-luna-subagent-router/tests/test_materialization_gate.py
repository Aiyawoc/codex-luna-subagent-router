from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import plan_work


def axes() -> dict[str, str]:
    return {
        "task_kind": "debug",
        "task_scope": "bounded",
        "reasoning_depth": "deep",
        "verifiability": "partial",
        "failure_cost": "medium",
        "context_volume": "medium",
    }


def payload():
    return {
        "version": 1,
        "tasks": [
            {
                "task_id": "debug-one",
                "task_family": "runtime-gate",
                "axes": axes(),
                "read_paths": ["src/a.py"],
                "write_paths": ["src/a_fix.py"],
            },
            {
                "task_id": "debug-two",
                "task_family": "runtime-gate",
                "axes": axes(),
                "read_paths": ["src/b.py"],
                "write_paths": ["src/b_fix.py"],
            },
        ],
    }


class MaterializationGateTests(unittest.TestCase):
    def run_plan(self, runtime_health, open_workers=0):
        with tempfile.TemporaryDirectory() as temp:
            return plan_work.plan_work(
                payload(),
                lead_model="gpt-6-sol",
                lead_effort="high",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-runtime",
                routing_mode="adaptive",
                max_workers=3,
                open_workers=open_workers,
                runtime_health=runtime_health,
            )

    def test_unknown_runtime_releases_only_first_real_worker(self):
        result = self.run_plan("unknown")
        self.assertEqual(result["planned_waves"][0], ["debug-one", "debug-two"])
        self.assertEqual(result["ready_worker_ids"], ["debug-one"])
        self.assertEqual(result["health_probe_worker_id"], "debug-one")
        self.assertEqual(result["runtime_blocked_worker_ids"], ["debug-two"])
        self.assertEqual(result["runtime_health_action"], "probe_first_real_worker")
        self.assertEqual(result["open_workers_semantics"], "materialized_pendinginit_or_running_only")

    def test_healthy_runtime_releases_full_ready_wave(self):
        result = self.run_plan("healthy")
        self.assertEqual(result["ready_worker_ids"], ["debug-one", "debug-two"])
        self.assertIsNone(result["health_probe_worker_id"])
        self.assertEqual(result["runtime_blocked_worker_ids"], [])
        self.assertEqual(result["runtime_health_action"], "use_ready_wave")

    def test_existing_materialized_worker_is_health_evidence(self):
        result = self.run_plan("unknown", open_workers=1)
        self.assertEqual(result["effective_runtime_health"], "healthy")
        self.assertEqual(result["ready_worker_ids"], ["debug-one", "debug-two"])
        self.assertIsNone(result["health_probe_worker_id"])

    def test_degraded_runtime_holds_new_spawns(self):
        result = self.run_plan("degraded")
        self.assertEqual(result["ready_worker_ids"], [])
        self.assertEqual(result["runtime_blocked_worker_ids"], ["debug-one", "debug-two"])
        self.assertEqual(result["runtime_health_action"], "hold_new_spawns")

    def test_invalid_runtime_health_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(Exception, "runtime-health"):
                plan_work.plan_work(
                    payload(),
                    lead_model="gpt-6-sol",
                    lead_effort="high",
                    calibration="off",
                    registry=Path(temp) / "outcomes.jsonl",
                    scope="project-runtime",
                    runtime_health="maybe",
                )


if __name__ == "__main__":
    unittest.main()
