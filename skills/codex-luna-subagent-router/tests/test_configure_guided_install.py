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
    START_MARKER,
    configure,
    merge_authorization,
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

    @staticmethod
    def responsibilities(**overrides: list[str]) -> dict[str, list[str]]:
        result = {"medium": [], "high": [], "xhigh": [], "max": []}
        result.update(overrides)
        return result

    def run_configure(self, **overrides):
        values = {
            "delegation": "none",
            "routing_scope": "none",
            "project_root": None,
            "codex_home": self.codex_home,
            "responsibilities": self.responsibilities(),
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
        self.assertEqual(original.count(START_MARKER), 1)

    def test_project_authorization_uses_project_root(self) -> None:
        result = self.run_configure(
            delegation="project",
            project_root=str(self.project),
        )

        self.assertEqual(Path(result["delegation"]["path"]), self.project / "AGENTS.md")
        self.assertTrue((self.project / "AGENTS.md").is_file())

    def test_exact_v1_authorization_is_migrated_to_managed_block(self) -> None:
        target = self.codex_home / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            f"# Existing\n\n{LEGACY_AUTHORIZATION_V1_0}\n",
            encoding="utf-8",
        )

        result = self.run_configure(delegation="global")
        text = target.read_text(encoding="utf-8")

        self.assertEqual(result["delegation"]["action"], "migrated_v1.0")
        self.assertEqual(text.count(START_MARKER), 1)
        self.assertIn("routing.json", text)

    def test_modified_unmarked_legacy_section_requires_manual_review(self) -> None:
        target = self.codex_home / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "## Luna SubAgent 自动路由授权\n\n- 用户自行修改过。\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ConfigurationError, "review it manually"):
            self.run_configure(delegation="global")

    def test_project_scope_requires_existing_root(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "--project-root"):
            self.run_configure(delegation="project")

    def test_none_does_not_create_authorization(self) -> None:
        result = self.run_configure(delegation="none")

        self.assertEqual(result["delegation"]["action"], "skipped")
        self.assertFalse((self.codex_home / "AGENTS.md").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_user_routing_table_records_additional_responsibilities(self) -> None:
        result = self.run_configure(
            routing_scope="user",
            responsibilities=self.responsibilities(
                medium=["仓库结构扫描"],
                max=["发布前的对抗式安全复核"],
            ),
        )
        target = Path(result["routing_table"]["path"])
        data = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(data["mode"], "additional_responsibilities")
        self.assertEqual(data["merge_policy"], "raise_only")
        self.assertEqual(data["levels"]["medium"], ["仓库结构扫描"])
        self.assertEqual(data["levels"]["max"], ["发布前的对抗式安全复核"])

    def test_project_routing_table_uses_project_codex_directory(self) -> None:
        result = self.run_configure(
            routing_scope="project",
            project_root=str(self.project),
            responsibilities=self.responsibilities(high=["本项目的跨包兼容性检查"]),
        )

        self.assertEqual(
            Path(result["routing_table"]["path"]),
            self.project / ".codex" / "codex-luna-subagent-router" / "routing.json",
        )

    def test_different_existing_routing_table_requires_replace_confirmation(self) -> None:
        self.run_configure(
            routing_scope="user",
            responsibilities=self.responsibilities(medium=["初始职责"]),
        )
        target = self.codex_home / "codex-luna-subagent-router" / "routing.json"
        original = target.read_text(encoding="utf-8")

        with self.assertRaisesRegex(ConfigurationError, "--replace-routing"):
            self.run_configure(
                routing_scope="user",
                responsibilities=self.responsibilities(high=["替换职责"]),
            )
        self.assertEqual(target.read_text(encoding="utf-8"), original)

        preview = self.run_configure(
            routing_scope="user",
            responsibilities=self.responsibilities(high=["替换职责"]),
            dry_run=True,
        )
        self.assertEqual(
            preview["routing_table"]["action"],
            "replace_requires_confirmation",
        )

        self.run_configure(
            routing_scope="user",
            responsibilities=self.responsibilities(high=["替换职责"]),
            replace_routing=True,
        )
        self.assertIn("替换职责", target.read_text(encoding="utf-8"))

    def test_custom_routing_requires_at_least_one_responsibility(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "no additional responsibility"):
            self.run_configure(routing_scope="user")

    def test_dry_run_validates_without_writing(self) -> None:
        result = self.run_configure(
            delegation="global",
            routing_scope="user",
            responsibilities=self.responsibilities(high=["复杂回归分析"]),
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
