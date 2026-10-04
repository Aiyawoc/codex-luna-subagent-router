from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_capabilities  # noqa: E402
import native_execution as native  # noqa: E402


def stage(**overrides):
    value = {
        "version": 1,
        "stage_id": "bounded-read-reduce",
        "execution_shape": "local_parallel_tools",
        "tool_count": 3,
        "read_only": True,
        "predictable_control_flow": True,
        "structured_outputs": True,
        "requires_semantic_judgment": False,
        "approval_sensitive": False,
        "preserve_citations": False,
        "preserve_native_artifacts": False,
    }
    value.update(overrides)
    return value


class NativeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.path = self.base / "caps.jsonl"
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def record_ptc(self, status):
        row = host_capabilities.observation(
            backend="codex_desktop",
            host_version="26.928.20755",
            capability="programmatic_tool_calling",
            status=status,
            source="user_verified",
        )
        host_capabilities.append(self.path, row)

    def test_unknown_capability_falls_back_without_guessing_from_version(self):
        result = native.primitive(
            backend="codex_desktop",
            host_version="26.928.20755",
            execution_shape="local_parallel_tools",
            evidence_file=self.path,
        )
        self.assertEqual(result["capability_status"], "unknown")
        self.assertEqual(result["execution_primitive"], "native_parallel_tools")
        self.assertTrue(result["fallback"])

    def test_supported_capability_enables_programmatic_primitive(self):
        self.record_ptc("supported")
        result = native.primitive(
            backend="codex_desktop",
            host_version="26.928.20755",
            execution_shape="local_parallel_tools",
            evidence_file=self.path,
        )
        self.assertEqual(result["execution_primitive"], "programmatic_tool_calling")
        self.assertFalse(result["fallback"])

    def test_agents_api_unknown_capability_uses_direct_tool_fallback(self):
        result = native.primitive(
            backend="agents_api",
            host_version="agents-v1",
            execution_shape="local_parallel_tools",
            evidence_file=self.path,
        )
        self.assertEqual(result["execution_primitive"], "direct_tool_calling")
        self.assertEqual(result["capability_status"], "unknown")

    def test_safe_bounded_stage_is_ptc_eligible_only_when_supported(self):
        unknown = native.stage_eligibility(
            stage(),
            backend="codex_desktop",
            host_version="26.928.20755",
            evidence_file=self.path,
        )
        self.assertFalse(unknown["eligible"])
        self.assertIn("ptc_capability_not_supported", unknown["reasons"])
        self.record_ptc("supported")
        supported = native.stage_eligibility(
            stage(),
            backend="codex_desktop",
            host_version="26.928.20755",
            evidence_file=self.path,
        )
        self.assertTrue(supported["eligible"])
        self.assertEqual(supported["recommended_primitive"], "programmatic_tool_calling")

    def test_semantic_approval_write_and_evidence_sensitive_stages_remain_direct(self):
        self.record_ptc("supported")
        cases = [
            ({"read_only": False}, "write_or_side_effect_use_direct"),
            ({"predictable_control_flow": False}, "adaptive_control_flow_use_direct"),
            ({"structured_outputs": False}, "unstructured_tool_output_use_direct"),
            ({"requires_semantic_judgment": True}, "semantic_judgment_use_direct"),
            ({"approval_sensitive": True}, "approval_sensitive_use_direct"),
            ({"preserve_citations": True}, "citation_preservation_use_direct"),
            ({"preserve_native_artifacts": True}, "native_artifact_validation_use_direct"),
            ({"tool_count": 1}, "single_tool_call_use_direct"),
        ]
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                result = native.stage_eligibility(
                    stage(**overrides),
                    backend="codex_desktop",
                    host_version="26.928.20755",
                    evidence_file=self.path,
                )
                self.assertFalse(result["eligible"])
                self.assertIn(reason, result["reasons"])
                self.assertEqual(result["recommended_primitive"], "native_parallel_tools")

    def test_non_parallel_shape_is_not_reclassified_as_ptc(self):
        with self.assertRaisesRegex(Exception, "local_parallel_tools"):
            native.stage_eligibility(
                stage(execution_shape="subagent"),
                backend="codex_desktop",
                host_version="26.928.20755",
                evidence_file=self.path,
            )
        serial = native.primitive(
            backend="codex_desktop",
            host_version="26.928.20755",
            execution_shape="local_serial",
            evidence_file=self.path,
        )
        self.assertEqual(serial["execution_primitive"], "lead_tooling")


if __name__ == "__main__":
    unittest.main()
