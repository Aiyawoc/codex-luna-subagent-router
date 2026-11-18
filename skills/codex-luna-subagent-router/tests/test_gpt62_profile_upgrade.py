"""Upgrade model profiles without rewriting user choices or historical records."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_bundle as installer


class ModelProfileUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "new package"
        shutil.copytree(ROOT / "assets/codex-agents", self.source / "assets/codex-agents")
        (self.source / "VERSION").write_text("2.9.5-rc.2\n", encoding="utf-8")
        self.destination = self.base / "skills" / installer.NAME
        self.previous_assets = self.destination / "assets/codex-agents"
        self.previous_assets.mkdir(parents=True)
        self.agents = self.base / "home/agents"
        self.agents.mkdir(parents=True)
        for profile in (self.source / "assets/codex-agents").glob("*.toml"):
            if profile.name == "terra-max.toml":
                continue
            previous = profile.read_text(encoding="utf-8").replace("gpt-6.2-sol", "gpt-6.1-sol").replace(
                "gpt-6.2-astra", "gpt-6-astra")
            (self.previous_assets / profile.name).write_text(previous, encoding="utf-8")
            (self.agents / profile.name).write_text(previous, encoding="utf-8")
        (self.destination / "VERSION").write_text("2.9.5-rc.1\n", encoding="utf-8")
        (self.agents / "user-review.toml").write_text('model = "custom-user-model"\n', encoding="utf-8")
        self.before_profiles = {p.name: p.read_bytes() for p in self.agents.glob("*.toml")}
        self.routing = self.base / "home" / installer.NAME / "routing.json"
        self.routing.parent.mkdir()
        self.routing.write_text('{"routing_mode":"adaptive","evidence_calibration":"off"}\n', encoding="utf-8")
        self.ledger = self.base / "home/state" / installer.NAME / "outcomes.jsonl"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text('{"model":"gpt-6.1-sol","effort":"high"}\n', encoding="utf-8")
        self.saved_routing, self.saved_ledger = self.routing.read_bytes(), self.ledger.read_bytes()

    def install(self):
        # Only the platform/runtime preflight is mocked. Package/profile file
        # replacement and its rollback run in a real, isolated filesystem.
        with patch.dict(os.environ, {"CODEX_ROUTER_PYTHON": sys.executable}), \
                patch.object(installer, "validate_runtime"), patch.object(installer, "run_helper"):
            return installer.install(self.source, self.destination, self.agents, install_mode="upgrade")

    def assert_user_data_unchanged(self):
        self.assertEqual(self.routing.read_bytes(), self.saved_routing)
        self.assertEqual(self.ledger.read_bytes(), self.saved_ledger)
        self.assertEqual((self.agents / "user-review.toml").read_bytes(), self.before_profiles["user-review.toml"])

    def test_upgrade_replaces_old_models_and_adds_only_terra_max(self):
        result = self.install()
        expected = {
            **{f"luna-{effort}.toml": ("gpt-6-luna", effort) for effort in ("low", "medium", "high", "xhigh", "max")},
            **{f"sol-{effort}.toml": ("gpt-6.2-sol", effort) for effort in ("medium", "high", "xhigh", "max")},
            **{f"astra-{effort}.toml": ("gpt-6.2-astra", effort) for effort in ("high", "xhigh", "max")},
            "terra-max.toml": ("gpt-6.1-terra", "max"),
        }
        managed = {p.name for p in self.agents.glob("*.toml")} - {"user-review.toml"}
        self.assertEqual(managed, set(expected))
        for name, identity in expected.items():
            with self.subTest(profile=name):
                profile = tomllib.loads((self.agents / name).read_text(encoding="utf-8"))
                self.assertEqual((profile["model"], profile["model_reasoning_effort"]), identity)
        previous = Path(result["previous_package"])
        self.assertEqual((previous / "VERSION").read_text(encoding="utf-8"), "2.9.5-rc.1\n")
        self.assertEqual((previous / "assets/codex-agents/sol-high.toml").read_bytes(),
                         self.before_profiles["sol-high.toml"])
        self.assert_user_data_unchanged()

    def test_late_profile_failure_restores_every_old_profile_and_package(self):
        replace = installer.os.replace

        def fail_terra(source, target):
            if Path(target) == self.agents / "terra-max.toml":
                raise OSError("synthetic Terra profile write failure")
            return replace(source, target)

        with patch.object(installer.os, "replace", side_effect=fail_terra):
            with self.assertRaisesRegex(OSError, "Terra profile"):
                self.install()
        self.assertEqual({p.name: p.read_bytes() for p in self.agents.glob("*.toml")}, self.before_profiles)
        self.assertEqual((self.destination / "VERSION").read_text(encoding="utf-8"), "2.9.5-rc.1\n")
        self.assertFalse(self.destination.with_name("." + installer.NAME + ".install-lock").exists())
        self.assert_user_data_unchanged()


if __name__ == "__main__":
    unittest.main()
