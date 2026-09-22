from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_work  # noqa: E402


TASK_KINDS = ("leaf", "scan", "implementation", "debug", "review", "architecture", "verification", "research", "other")
SCOPES = ("micro", "bounded", "workflow")
DEPTHS = ("shallow", "medium", "deep")
VERIFIABILITY = ("yes", "partial", "no")
FAILURES = ("low", "medium", "high")
VOLUMES = ("low", "medium", "high")
LEADS = (("gpt-5.6-luna", "max"), ("gpt-5.6-sol", "high"), ("gpt-6-astra", "high"))


class PlannerFuzzTests(unittest.TestCase):
    def test_five_thousand_deterministic_plans_preserve_invariants(self):
        rng = random.Random(2700)
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "outcomes.jsonl"
            for case_no in range(5000):
                count = rng.randint(1, 5)
                tasks = []
                for idx in range(count):
                    task_id = f"fuzz-{case_no:04d}-{idx}"
                    read_name = f"src/{rng.randint(0, max(1, count - 1))}.py"
                    writes = []
                    if rng.random() < 0.42:
                        writes = [f"src/{rng.randint(0, max(1, count - 1))}.py"]
                    axes = {
                        "task_kind": rng.choice(TASK_KINDS),
                        "task_scope": rng.choice(SCOPES),
                        "reasoning_depth": rng.choice(DEPTHS),
                        "verifiability": rng.choice(VERIFIABILITY),
                        "failure_cost": rng.choice(FAILURES),
                        "context_volume": rng.choice(VOLUMES),
                    }
                    tasks.append({
                        "task_id": task_id,
                        "task_family": "planner-fuzz",
                        "axes": axes,
                        "read_paths": [read_name],
                        "write_paths": writes,
                        "independent_review": bool(rng.random() < 0.08),
                    })
                health = rng.choice(("unknown", "healthy", "degraded"))
                routing_mode = rng.choice(("adaptive", "luna_only"))
                lead_model, lead_effort = rng.choice(LEADS)
                result = plan_work.plan_work(
                    {"version": 1, "tasks": tasks},
                    lead_model=lead_model,
                    lead_effort=lead_effort,
                    calibration="off",
                    registry=registry,
                    scope="planner-fuzz",
                    routing_mode=routing_mode,
                    max_workers=3,
                    open_workers=0,
                    runtime_health=health,
                )

                decisions = {row["task_id"]: row for row in result["decisions"]}
                workers = {row["worker_id"]: row for row in result["workers"]}
                worker_tasks = {tid for row in result["workers"] for tid in row["task_ids"]}

                self.assertEqual(len(decisions), len(tasks))
                self.assertEqual(len(result["ready_worker_ids"]), len(set(result["ready_worker_ids"])))
                self.assertTrue(set(result["ready_worker_ids"]).issubset(workers))
                self.assertFalse(set(result["local_parallel_task_ids"]) & worker_tasks)

                for task in tasks:
                    row = decisions[task["task_id"]]
                    if task["axes"]["task_scope"] == "micro":
                        self.assertNotEqual(row["execution_shape"], "subagent")
                    if row["execution_shape"] == "local_parallel_tools":
                        self.assertEqual(row["decision"], "lead_only")
                        self.assertFalse(task["write_paths"])
                        self.assertEqual(task["axes"]["verifiability"], "yes")
                        self.assertNotEqual(task["axes"]["reasoning_depth"], "deep")
                        self.assertNotEqual(task["axes"]["context_volume"], "high")
                        self.assertNotEqual(task["axes"]["failure_cost"], "high")
                        self.assertFalse(task["independent_review"])
                    if row["decision"] == "delegate":
                        self.assertEqual(row["execution_shape"], "subagent")
                        self.assertIn(task["task_id"], worker_tasks)
                        if routing_mode == "luna_only":
                            self.assertEqual(row["model"], "gpt-5.6-luna")
                    if task["independent_review"] and task["axes"]["task_scope"] != "micro" and routing_mode == "adaptive":
                        self.assertNotEqual(row["execution_shape"], "local_parallel_tools")

                for wave in result["planned_waves"]:
                    groups = [workers[wid] for wid in wave]
                    for left_index, left in enumerate(groups):
                        for right in groups[left_index + 1:]:
                            self.assertFalse(plan_work.conflict(left, right))

                if health == "unknown" and result["effective_runtime_health"] == "unknown":
                    self.assertLessEqual(len(result["ready_worker_ids"]), 1)
                if health == "degraded":
                    self.assertEqual(result["ready_worker_ids"], [])


if __name__ == "__main__":
    unittest.main()
