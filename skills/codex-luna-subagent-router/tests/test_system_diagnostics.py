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

import system_diagnostics as diagnostics  # noqa: E402
import runtime_support  # noqa: E402


class SystemDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        routing = self.project / ".codex/codex-luna-subagent-router/routing.json"
        routing.parent.mkdir(parents=True)
        routing.write_text(json.dumps({
            "schema_version": "2.1",
            "routing_mode": "adaptive",
            "evidence_calibration": "conservative",
            "token_accounting": "off",
        }))
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def files(self):
        return {
            p.relative_to(self.base).as_posix(): p.read_bytes()
            for p in self.base.rglob("*") if p.is_file()
        }

    def test_collect_is_read_only_and_separates_config_from_host_proof(self):
        before = self.files()
        result = diagnostics.collect(project_root=self.project)
        after = self.files()
        self.assertEqual(before, after)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["refresh_performed"])
        self.assertFalse(result["trust_changed"])
        self.assertEqual(result["config"]["routing_mode"], "adaptive")
        self.assertEqual(result["config"]["source"], "project")
        self.assertEqual(result["hooks"]["host_hook_trust"], "unverified")
        self.assertEqual(result["hooks"]["host_event_execution"], "unverified")
        self.assertFalse(result["native_shadow"]["authoritative"])
        self.assertFalse(result["native_shadow"]["automatic_promotion"])

    def test_empty_ledgers_are_zero_observations_not_errors(self):
        result = diagnostics.collect(project_root=self.project)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["usage"]["status"], "ok")
        self.assertEqual(result["usage"]["observed_subagents"], 0)
        self.assertEqual(result["turns"]["registered_turns"], 0)
        self.assertEqual(result["native_shadow"]["unique_evidence"], 0)

    def test_invalid_saved_usage_row_is_visible_as_warning_not_hidden(self):
        usage = self.home / "state/codex-luna-subagent-router/usage.jsonl"
        usage.parent.mkdir(parents=True)
        usage.write_text("not-json\n", encoding="utf-8")
        result = diagnostics.collect(project_root=self.project)
        self.assertEqual(result["status"], "warning")
        self.assertIn("invalid_usage_rows", result["warnings"])
        self.assertEqual(result["usage"]["invalid_usage_rows"], 1)

    def test_runtime_dispatch_exposes_diagnostics(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, *runtime_support.FLAGS,
             str(ROOT / "scripts/runtime_dispatch.py"),
             "diagnostics", "--project-root", str(self.project), "--json"],
            env={**os.environ, "CODEX_HOME": str(self.home)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["scope_id"], diagnostics.store.scope_id(self.project))
        self.assertTrue(payload["read_only"])

    def test_output_does_not_expose_home_or_project_paths(self):
        result = diagnostics.collect(project_root=self.project)
        raw = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(self.home), raw)
        self.assertNotIn(str(self.project), raw)


if __name__ == "__main__":
    unittest.main()
