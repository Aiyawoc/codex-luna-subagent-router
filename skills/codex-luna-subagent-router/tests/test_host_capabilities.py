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

import host_capabilities as caps  # noqa: E402
import runtime_support  # noqa: E402


class HostCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.path = self.base / "capabilities.jsonl"
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def record(self, capability, status, source, version="26.928.20755", backend="codex_desktop"):
        row = caps.observation(
            backend=backend, host_version=version, capability=capability,
            status=status, source=source,
        )
        caps.append(self.path, row)
        return row

    def test_unknown_is_default_and_not_inferred_from_version(self):
        result = caps.snapshot(self.path, backend="codex_desktop", host_version="26.928.20755")
        self.assertFalse(result["authoritative"])
        self.assertTrue(result["routing_unchanged"])
        self.assertEqual(result["matching_observations"], 0)
        self.assertTrue(all(v["status"] == "unknown" for v in result["capabilities"].values()))

    def test_supported_evidence_is_bound_to_exact_backend_and_version(self):
        self.record("sol_medium", "supported", "user_verified")
        current = caps.snapshot(self.path, backend="codex_desktop", host_version="26.928.20755")
        other_version = caps.snapshot(self.path, backend="codex_desktop", host_version="26.929.0")
        other_backend = caps.snapshot(self.path, backend="agents_api", host_version="26.928.20755")
        self.assertEqual(current["capabilities"]["sol_medium"]["status"], "supported")
        self.assertEqual(other_version["capabilities"]["sol_medium"]["status"], "unknown")
        self.assertEqual(other_backend["capabilities"]["sol_medium"]["status"], "unknown")

    def test_conflicting_sources_remain_unknown(self):
        self.record("native_usage", "supported", "host_runtime")
        self.record("native_usage", "unsupported", "user_verified")
        result = caps.snapshot(self.path, backend="codex_desktop", host_version="26.928.20755")
        value = result["capabilities"]["native_usage"]
        self.assertEqual(value["status"], "unknown")
        self.assertEqual(value["reason"], "conflicting_evidence")
        self.assertEqual(value["evidence_count"], 2)

    def test_newer_observation_from_same_source_supersedes_older_source_value(self):
        self.record("programmatic_tool_calling", "unsupported", "user_verified")
        self.record("programmatic_tool_calling", "supported", "user_verified")
        result = caps.snapshot(self.path, backend="codex_desktop", host_version="26.928.20755")
        value = result["capabilities"]["programmatic_tool_calling"]
        self.assertEqual(value["status"], "supported")
        self.assertEqual(value["evidence_count"], 1)

    def test_record_cli_requires_explicit_confirmation(self):
        cmd = [
            sys.executable, *runtime_support.FLAGS,
            str(ROOT / "scripts/runtime_dispatch.py"), "host_capabilities",
            "--evidence-file", str(self.path), "record",
            "--backend", "codex_desktop", "--host-version", "26.928.20755",
            "--capability", "sol_medium", "--status", "supported",
            "--source", "user_verified", "--json",
        ]
        result = subprocess.run(cmd, env={**os.environ, "CODEX_HOME": str(self.home)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.path.exists())
        result = subprocess.run([*cmd, "--confirm"], env={**os.environ, "CODEX_HOME": str(self.home)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "recorded")

    def test_snapshot_contains_no_local_paths_or_raw_execution_ids(self):
        self.record("subagent_identity", "supported", "host_runtime")
        raw = json.dumps(
            caps.snapshot(self.path, backend="codex_desktop", host_version="26.928.20755"),
            ensure_ascii=False,
        )
        self.assertNotIn(str(self.base), raw)
        self.assertNotIn("session", raw.lower())
        self.assertNotIn("turn_", raw.lower())


if __name__ == "__main__":
    unittest.main()
