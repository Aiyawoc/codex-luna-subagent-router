from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARENA = ROOT / "benchmarks" / "router_arena.py"
if ARENA.is_file():
    spec = importlib.util.spec_from_file_location("router_arena", ARENA)
    arena = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(arena)
else:
    arena = None


class RouterArenaTests(unittest.TestCase):
    @unittest.skipUnless(arena is not None, "source-only Router Arena is outside the portable Skill package")
    def test_frozen_baseline_and_v270_targets_pass(self):
        result = arena.audit()
        self.assertTrue(result["passed"], result)
        rows = {row["id"]: row for row in result["cases"]}
        self.assertEqual(rows["parallel-read-scan"]["actual"]["execution_shapes"],
                         ["local_parallel_tools", "local_parallel_tools"])
        self.assertEqual(rows["parallel-read-scan"]["actual"]["ready_worker_ids"], [])
        self.assertEqual(rows["deep-debug-siblings"]["actual"]["execution_shapes"],
                         ["subagent", "subagent"])
        self.assertEqual(rows["deep-debug-siblings"]["actual"]["ready_worker_ids"],
                         ["debug-one", "debug-two"])
        self.assertEqual(rows["micro-known-edit"]["actual"]["execution_shapes"],
                         ["local_serial"])
        self.assertEqual(result["changed_cases"], ["parallel-read-scan"])


if __name__ == "__main__":
    unittest.main()
