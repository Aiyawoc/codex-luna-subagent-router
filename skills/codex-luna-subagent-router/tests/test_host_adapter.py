from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_adapter  # noqa: E402


class HostAdapterTests(unittest.TestCase):
    def test_agents_api_maps_execution_shapes_to_native_primitives(self):
        self.assertEqual(
            host_adapter.execution_primitive("agents_api", "local_parallel_tools")["execution_primitive"],
            "programmatic_tool_calling",
        )
        self.assertEqual(
            host_adapter.execution_primitive("agents_api", "subagent")["execution_primitive"],
            "native_multi_agent",
        )

    def test_desktop_keeps_existing_parallel_tool_fallback(self):
        result = host_adapter.execution_primitive("codex_desktop", "local_parallel_tools")
        self.assertEqual(result["execution_primitive"], "native_parallel_tools")
        self.assertFalse(result["experimental_backend"])

    def test_native_usage_keeps_missing_values_unknown(self):
        result = host_adapter.normalize_native_usage({"input_tokens": 120})
        self.assertEqual(result["input_tokens"], 120)
        self.assertIsNone(result["output_tokens"])
        self.assertIsNone(result["total_tokens"])
        self.assertEqual(result["status"], "partial")

    def test_native_usage_can_derive_total_only_from_known_input_and_output(self):
        result = host_adapter.normalize_native_usage({
            "input_tokens": 120,
            "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens_details": {"reasoning_tokens": 12},
        })
        self.assertEqual(result["total_tokens"], 150)
        self.assertEqual(result["cached_input_tokens"], 80)
        self.assertEqual(result["reasoning_tokens"], 12)
        self.assertEqual(result["status"], "complete")

    def test_cancelled_native_turn_maps_to_interrupted(self):
        self.assertEqual(host_adapter.normalize_lifecycle("cancelled"), "interrupted")


if __name__ == "__main__":
    unittest.main()
