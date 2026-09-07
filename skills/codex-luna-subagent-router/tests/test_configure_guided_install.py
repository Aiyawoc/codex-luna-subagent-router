from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from configure_guided_install import (  # noqa: E402
    ConfigurationError,
    END_MARKER,
    LEGACY_AUTHORIZATION_V1_0,
    REQUEST_USER_INPUT_FEATURE,
    START_MARKER,
    configure,
    merge_authorization,
    merge_request_user_input_feature,
)


class GuidedInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_configure(self, **overrides):
        values = {
            "delegation": "none",
            "routing_scope": "none",
            "routing_mode": "none",
            "project_root": None,
            "codex_home": self.codex_home,
            "dry_run": False,
        }
        values.update(overrides)
        return configure(**values)

    def test_global_authorization_preserves_existing_content(self) -> None:
        target = self.codex_home / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("# Existing guidance\n\nKeep this rule.\n", encoding="utf-8")
        result = self.run_configure(delegation="global")
        text = target.read_text(encoding="utf-8")
        self.assertEqual(result["delegation"]["action"], "appended")
        self.assertIn("Keep this rule.", text)
        self.assertEqual(text.count(START_MARKER), 1)
        self.assertEqual(text.count(END_MARKER), 1)

    def test_global_authorization_is_idempotent(self) -> None:
        first = self.run_configure(delegation="global")
        target = Path(first["delegation"]["path"])
        original = target.read_text(encoding="utf-8")
        second = self.run_configure(delegation="global")
        self.assertEqual(second["delegation"]["action"], "unchanged")
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_exact_v1_authorization_is_migrated(self) -> None:
        target = self.codex_home / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(f"# Existing\n\n{LEGACY_AUTHORIZATION_V1_0}\n", encoding="utf-8")
        result = self.run_configure(delegation="global")
        text = target.read_text(encoding="utf-8")
        self.assertEqual(result["delegation"]["action"], "migrated_v1.0")
        self.assertIn("预期总成本", text)

    def test_request_user_input_creates_user_config(self) -> None:
        result = self.run_configure(request_user_input="enable")
        target = self.codex_home / "config.toml"
        self.assertEqual(result["request_user_input"]["action"], "created")
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            f"[features]\n{REQUEST_USER_INPUT_FEATURE} = true\n",
        )

    def test_request_user_input_preserves_existing_content(self) -> None:
        target = self.codex_home / "config.toml"
        target.parent.mkdir(parents=True)
        target.write_text(
            "[agents]\nenabled = true\n\n[features]\n# keep\ncode_mode = { enabled = true }\n",
            encoding="utf-8",
        )
        self.run_configure(request_user_input="enable")
        text = target.read_text(encoding="utf-8")
        self.assertIn("# keep", text)
        self.assertIn(f"{REQUEST_USER_INPUT_FEATURE} = true", text)

    def test_request_user_input_promotes_false(self) -> None:
        merged, action = merge_request_user_input_feature(
            "[features]\ndefault_mode_request_user_input = false # user choice\n"
        )
        self.assertEqual(action, "updated")
        self.assertIn("default_mode_request_user_input = true # user choice", merged)

    def test_luna_only_user_config(self) -> None:
        result = self.run_configure(routing_scope="user", routing_mode="luna_only")
        target = Path(result["routing_config"]["path"])
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "2.0")
        self.assertEqual(data["routing_mode"], "luna_only")
        self.assertEqual(data["max_concurrent_workers"], 3)

    def test_adaptive_project_config(self) -> None:
        result = self.run_configure(
            routing_scope="project",
            routing_mode="adaptive",
            project_root=str(self.project),
        )
        target = Path(result["routing_config"]["path"])
        self.assertEqual(
            target,
            self.project / ".codex" / "codex-luna-subagent-router" / "routing.json",
        )
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["routing_mode"], "adaptive")

    def test_scope_and_mode_must_be_selected_together(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "must both be none"):
            self.run_configure(routing_scope="user", routing_mode="none")
        with self.assertRaisesRegex(ConfigurationError, "must both be none"):
            self.run_configure(routing_scope="none", routing_mode="adaptive")

    def test_v1_routing_migrates_with_backup(self) -> None:
        target = self.codex_home / "codex-luna-subagent-router" / "routing.json"
        target.parent.mkdir(parents=True)
        legacy = {
            "schema_version": "1.0",
            "mode": "additional_responsibilities",
            "merge_policy": "raise_only",
            "levels": {"medium": ["扫描"], "high": [], "xhigh": [], "max": []},
        }
        original = json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
        target.write_text(original, encoding="utf-8")
        result = self.run_configure(routing_scope="user", routing_mode="luna_only")
        self.assertEqual(result["routing_config"]["action"], "migrated_v1")
        backup = target.with_name("routing.v1.backup.json")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["routing_mode"], "luna_only")

    def test_unknown_existing_routing_requires_confirmation(self) -> None:
        target = self.codex_home / "codex-luna-subagent-router" / "routing.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"custom": true}\n', encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "--replace-routing"):
            self.run_configure(routing_scope="user", routing_mode="adaptive")
        preview = self.run_configure(
            routing_scope="user", routing_mode="adaptive", dry_run=True
        )
        self.assertEqual(
            preview["routing_config"]["action"], "replace_requires_confirmation"
        )
        self.run_configure(
            routing_scope="user",
            routing_mode="adaptive",
            replace_routing=True,
        )
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["routing_mode"], "adaptive")

    def test_dry_run_does_not_write(self) -> None:
        result = self.run_configure(
            delegation="global",
            routing_scope="user",
            routing_mode="luna_only",
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.codex_home.exists())

    def test_malformed_managed_markers_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "malformed"):
            merge_authorization(f"prefix\n{START_MARKER}\nbroken", "replacement")
        with self.assertRaisesRegex(ConfigurationError, "wrong order"):
            merge_authorization(f"{END_MARKER}\n{START_MARKER}", "replacement")

    def test_symbolic_link_target_is_rejected(self) -> None:
        actual = self.root / "real-agents.md"
        actual.write_text("keep", encoding="utf-8")
        target = self.codex_home / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.symlink_to(actual)
        with self.assertRaisesRegex(ConfigurationError, "symbolic-link"):
            self.run_configure(delegation="global")
        self.assertEqual(actual.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
