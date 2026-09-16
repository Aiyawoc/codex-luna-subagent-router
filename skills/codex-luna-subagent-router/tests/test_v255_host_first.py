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

import inspect_guided_install as inventory  # noqa: E402
import outcome_store as store  # noqa: E402
from configure_subagent_limit import KEY, LEGACY_KEY, V2_TABLE  # noqa: E402
from plan_work import session_limit  # noqa: E402


class HostFirstConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        routing = self.home / "codex-luna-subagent-router/routing.json"
        routing.parent.mkdir()
        routing.write_text(json.dumps({"schema_version": "2.0", "routing_mode": "adaptive"}))

    def q4(self):
        result = inventory.inspect(self.home)
        return result, result["questions"][3]

    def test_canonical_0154_shape_satisfies_q4(self) -> None:
        (self.home / "config.toml").write_text(f"[agents]\n{KEY} = 3\n")
        result, q4 = self.q4()
        self.assertNotIn(4, result["pending_questions"])
        self.assertEqual(q4["current"]["safe_effective_subagent_limit"], 3)
        self.assertEqual(q4["current"]["layers"][0]["schema"], "canonical")
        self.assertFalse(q4["current"]["cli_required"])

    def test_portable_0142_0154_shape_satisfies_q4_without_cli(self) -> None:
        (self.home / "config.toml").write_text(
            f"[agents]\n{LEGACY_KEY} = 3\n\n[{V2_TABLE}]\n{KEY} = 4\n"
        )
        result, q4 = self.q4()
        self.assertNotIn(4, result["pending_questions"])
        self.assertEqual(q4["current"]["effective_subagent_limit"], 3)
        self.assertEqual(q4["current"]["layers"][0]["schema"], "portable")

    def test_legacy_v1_only_stays_pending_when_host_backend_is_unknown(self) -> None:
        (self.home / "config.toml").write_text(f"[agents]\n{LEGACY_KEY} = 3\n")
        result, q4 = self.q4()
        self.assertIn(4, result["pending_questions"])
        self.assertEqual(q4["current"]["effective_subagent_limit"], 3)
        self.assertIsNone(q4["current"]["safe_effective_subagent_limit"])

    def test_explicit_legacy_v2_is_recognized(self) -> None:
        (self.home / "config.toml").write_text(
            f"[{V2_TABLE}]\nenabled = true\n{KEY} = 4\n"
        )
        result, q4 = self.q4()
        self.assertNotIn(4, result["pending_questions"])
        self.assertEqual(q4["current"]["effective_subagent_limit"], 3)
        self.assertEqual(q4["current"]["layers"][0]["schema"], "legacy_v2_only")

    def test_planner_reads_portable_v2_effective_limit(self) -> None:
        project = self.root / "project"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex/config.toml").write_text(
            f"[agents]\n{LEGACY_KEY} = 2\n\n[{V2_TABLE}]\n{KEY} = 3\n"
        )
        self.assertEqual(session_limit(3, project), 2)

    def test_planner_rejects_conflicting_dual_schema(self) -> None:
        project = self.root / "project"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex/config.toml").write_text(
            f"[agents]\n{LEGACY_KEY} = 2\n\n[{V2_TABLE}]\n{KEY} = 9\n"
        )
        with self.assertRaisesRegex(store.StoreError, "invalid or conflicting"):
            session_limit(3, project)

    def test_helper_has_no_external_codex_cli_runtime_dependency(self) -> None:
        source = (ROOT / "scripts/configure_subagent_limit.py").read_text()
        self.assertNotIn("subprocess", source)
        self.assertIn('"cli_required": False', source)

    def test_guided_install_is_host_first_and_cli_optional(self) -> None:
        guide = (ROOT / "references/codex-guided-install.md").read_text()
        self.assertIn("Host/Core", guide)
        self.assertIn("CLI 0.154.0", guide)
        self.assertIn("--schema auto", guide)
        self.assertIn("CLI 只是可选诊断器", guide)


if __name__ == "__main__":
    unittest.main()
