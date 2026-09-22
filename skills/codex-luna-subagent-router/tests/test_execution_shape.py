from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plan_work import plan_work


def axes(**overrides: str) -> dict[str, str]:
    value = {
        "task_kind": "scan",
        "task_scope": "bounded",
        "reasoning_depth": "shallow",
        "verifiability": "yes",
        "failure_cost": "low",
        "context_volume": "low",
    }
    value.update(overrides)
    return value


def task(task_id: str, *, read: str, write: str | None = None, axis_overrides=None, independent_review=False):
    return {
        "task_id": task_id,
        "task_family": "execution-shape",
        "axes": axes(**(axis_overrides or {})),
        "read_paths": [read],
        "write_paths": [write] if write else [],
        **({"independent_review": True} if independent_review else {}),
    }


class ExecutionShapeTests(unittest.TestCase):
    def run_plan(self, tasks, *, lead_model="gpt-5.6-sol", lead_effort="high"):
        with tempfile.TemporaryDirectory() as temp:
            return plan_work(
                {"version": 1, "tasks": tasks},
                lead_model=lead_model,
                lead_effort=lead_effort,
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-shape",
                routing_mode="adaptive",
                max_workers=3,
                open_workers=0,
            )

    def test_parallel_read_only_scans_stay_in_lead_tools(self):
        result = self.run_plan([
            task("scan-one", read="src/a.py"),
            task("scan-two", read="src/b.py"),
        ])
        self.assertEqual([d["execution_shape"] for d in result["decisions"]],
                         ["local_parallel_tools", "local_parallel_tools"])
        self.assertEqual([d["decision"] for d in result["decisions"]], ["lead_only", "lead_only"])
        self.assertEqual(result["local_parallel_task_ids"], ["scan-one", "scan-two"])
        self.assertEqual(result["workers"], [])
        self.assertEqual(result["ready_worker_ids"], [])

    def test_single_scan_can_still_delegate_for_cheaper_model(self):
        result = self.run_plan([task("scan-only", read="src/a.py")])
        self.assertEqual(result["decisions"][0]["execution_shape"], "subagent")
        self.assertEqual(result["decisions"][0]["decision"], "delegate")
        self.assertEqual(result["ready_worker_ids"], ["scan-only"])

    def test_high_context_scan_keeps_context_isolation_worker(self):
        result = self.run_plan([
            task("scan-large-a", read="src/a.py", axis_overrides={"context_volume": "high", "reasoning_depth": "medium"}),
            task("scan-large-b", read="src/b.py", axis_overrides={"context_volume": "high", "reasoning_depth": "medium"}),
        ])
        self.assertEqual([d["execution_shape"] for d in result["decisions"]], ["subagent", "subagent"])
        self.assertEqual(result["ready_worker_ids"], ["scan-large-a", "scan-large-b"])

    def test_write_work_is_not_relabelled_as_parallel_tools(self):
        result = self.run_plan([
            task("write-one", read="src/a.py", write="src/a.py"),
            task("write-two", read="src/b.py", write="src/b.py"),
        ])
        self.assertEqual([d["execution_shape"] for d in result["decisions"]], ["subagent", "subagent"])

    def test_deep_debug_siblings_remain_independent_subagents(self):
        deep = {
            "task_kind": "debug",
            "reasoning_depth": "deep",
            "verifiability": "partial",
            "failure_cost": "medium",
            "context_volume": "medium",
        }
        result = self.run_plan([
            task("debug-one", read="src/a.py", write="src/a_fix.py", axis_overrides=deep),
            task("debug-two", read="src/b.py", write="src/b_fix.py", axis_overrides=deep),
        ])
        self.assertEqual([d["execution_shape"] for d in result["decisions"]], ["subagent", "subagent"])
        self.assertEqual([d["delegation_trigger"] for d in result["decisions"]],
                         ["parallel_independent_sibling", "parallel_independent_sibling"])

    def test_independent_review_never_collapses_into_local_parallel_tools(self):
        result = self.run_plan([
            task("review-one", read="src/a.py", axis_overrides={"task_kind": "verification"}, independent_review=True),
            task("review-two", read="src/b.py", axis_overrides={"task_kind": "verification"}, independent_review=True),
        ])
        self.assertEqual([d["execution_shape"] for d in result["decisions"]], ["subagent", "subagent"])
        self.assertEqual([d["delegation_trigger"] for d in result["decisions"]],
                         ["independent_review", "independent_review"])

    def test_micro_work_is_local_serial(self):
        result = self.run_plan([
            task("micro-edit", read="src/a.py", write="src/a.py",
                 axis_overrides={"task_kind": "leaf", "task_scope": "micro"}),
        ])
        self.assertEqual(result["decisions"][0]["execution_shape"], "local_serial")
        self.assertEqual(result["local_serial_task_ids"], ["micro-edit"])
        self.assertEqual(result["ready_worker_ids"], [])


if __name__ == "__main__":
    unittest.main()
