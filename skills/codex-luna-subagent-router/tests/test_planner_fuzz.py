from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

import plan_work

SEED = 270_5000
CASES = 5000
KINDS = ("scan", "verification", "leaf", "implementation", "debug", "review")
DEPTHS = ("shallow", "medium", "deep")
VERIFY = ("yes", "partial", "no")
FAILURE = ("low", "medium", "high")
VOLUME = ("low", "medium", "high")


def task(task_id, rng):
    kind = rng.choice(KINDS)
    depth = rng.choice(DEPTHS)
    verifiability = rng.choice(VERIFY)
    failure = rng.choice(FAILURE)
    volume = rng.choice(VOLUME)
    write = rng.random() < 0.35
    review = rng.random() < 0.08
    return {
        "task_id": task_id,
        "task_family": "fuzz-route",
        "axes": {
            "task_kind": kind,
            "task_scope": rng.choice(("micro", "bounded", "workflow")),
            "reasoning_depth": depth,
            "verifiability": verifiability,
            "failure_cost": failure,
            "context_volume": volume,
        },
        "read_paths": [f"src/{task_id}.py"],
        "write_paths": [f"src/{task_id}.py"] if write else [],
        **({"independent_review": True} if review else {}),
    }


class PlannerFuzzTests(unittest.TestCase):
    def test_5000_deterministic_plans_preserve_core_invariants(self):
        rng = random.Random(SEED)
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "outcomes.jsonl"
            for index in range(CASES):
                count = 2 + (index % 2)
                tasks = [task(f"task-{index}-{slot}", rng) for slot in range(count)]
                health = ("unknown", "healthy", "degraded")[index % 3]
                result = plan_work.plan_work(
                    {"version": 1, "tasks": tasks},
                    lead_model="gpt-5.6-sol",
                    lead_effort="high",
                    calibration="off",
                    registry=registry,
                    scope="project-fuzz",
                    routing_mode="adaptive",
                    max_workers=3,
                    open_workers=0,
                    runtime_health=health,
                )

                workers = {w["worker_id"] for w in result["workers"]}
                ready = result["ready_worker_ids"]
                self.assertTrue(set(ready).issubset(workers))
                self.assertLessEqual(len(ready), result["effective_wave_limit"])

                if health == "unknown":
                    self.assertLessEqual(len(ready), 1)
                elif health == "degraded":
                    self.assertEqual(ready, [])

                local_parallel = set(result["local_parallel_task_ids"])
                self.assertTrue(local_parallel.isdisjoint(workers))
                for decision in result["decisions"]:
                    shape = decision["execution_shape"]
                    self.assertIn(shape, ("local_serial", "local_parallel_tools", "subagent"))
                    original = next(t for t in tasks if t["task_id"] == decision["task_id"])
                    axes = original["axes"]
                    if shape == "local_parallel_tools":
                        self.assertFalse(original["write_paths"])
                        self.assertFalse(original.get("independent_review", False))
                        self.assertNotEqual(axes["task_scope"], "micro")
                        self.assertIn(axes["task_kind"], ("scan", "verification", "leaf"))
                        self.assertIn(axes["reasoning_depth"], ("shallow", "medium"))
                        self.assertEqual(axes["verifiability"], "yes")
                        self.assertNotEqual(axes["failure_cost"], "high")
                        self.assertNotEqual(axes["context_volume"], "high")
                    if original.get("independent_review") and axes["task_scope"] != "micro":
                        self.assertEqual(shape, "subagent")
                    if axes["task_scope"] == "micro":
                        self.assertNotEqual(shape, "local_parallel_tools")


if __name__ == "__main__":
    unittest.main()
