from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from configure_subagent_limit import (  # noqa: E402
    ConfigurationError,
    KEY,
    LEGACY_KEY,
    V2_TABLE,
    analyze_config,
    configure_limit,
    merge_subagent_limit,
)


class SubagentLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_auto_new_install_uses_cli_independent_portable_schema(self) -> None:
        result = configure_limit(codex_home=self.codex_home, max_subagents=3, dry_run=False)
        text = (self.codex_home / "config.toml").read_text(encoding="utf-8")
        self.assertEqual(result["max_subagents"], 3)
        self.assertEqual(result["selected_schema"], "portable")
        self.assertFalse(result["cli_required"])
        self.assertIn(f"[agents]\n{LEGACY_KEY} = 3", text)
        self.assertIn(f"[{V2_TABLE}]\n{KEY} = 4", text)
        self.assertEqual(analyze_config(__import__("tomllib").loads(text))["effective_subagent_limit"], 3)

    def test_canonical_schema_matches_codex_0154_public_agents_key(self) -> None:
        merged, action = merge_subagent_limit("", 3, schema="canonical")
        self.assertEqual(action, "created")
        self.assertEqual(merged, f"[agents]\n{KEY} = 3\n")

    def test_auto_preserves_existing_canonical_schema(self) -> None:
        existing = f"[agents]\n{KEY} = 8 # user choice\n"
        merged, action = merge_subagent_limit(existing, 2, schema="auto")
        self.assertEqual(action, "updated")
        self.assertIn(f"{KEY} = 2 # user choice", merged)
        self.assertNotIn(LEGACY_KEY, merged)

    def test_portable_updates_both_old_v1_and_v2_semantics(self) -> None:
        existing = f"[agents]\n{LEGACY_KEY} = 6\n\n[{V2_TABLE}]\n{KEY} = 7\n"
        merged, action = merge_subagent_limit(existing, 3, schema="portable")
        self.assertEqual(action, "updated_portable")
        self.assertIn(f"{LEGACY_KEY} = 3", merged)
        self.assertIn(f"{KEY} = 4", merged)
        info = analyze_config(__import__("tomllib").loads(merged))
        self.assertEqual(info["schema"], "portable")
        self.assertEqual(info["effective_subagent_limit"], 3)
        self.assertTrue(info["backend_safe_without_host_probe"])

    def test_canonical_keeps_existing_old_v2_override_semantically_aligned(self) -> None:
        existing = f"[agents]\n{LEGACY_KEY} = 6\n\n[{V2_TABLE}]\n{KEY} = 7\n"
        merged, action = merge_subagent_limit(existing, 3, schema="canonical")
        self.assertEqual(action, "updated_with_v2_compat")
        self.assertIn(f"[agents]\n{KEY} = 3", merged)
        self.assertIn(f"[{V2_TABLE}]\n{KEY} = 4", merged)
        self.assertNotIn(f"{LEGACY_KEY} =", merged)
        self.assertEqual(analyze_config(__import__("tomllib").loads(merged))["effective_subagent_limit"], 3)

    def test_preserves_other_config(self) -> None:
        target = self.codex_home / "config.toml"
        target.parent.mkdir(parents=True)
        target.write_text("[features]\ndefault_mode_request_user_input = true\n", encoding="utf-8")
        configure_limit(codex_home=self.codex_home, max_subagents=4, dry_run=False)
        text = target.read_text(encoding="utf-8")
        self.assertIn("[features]", text)
        self.assertIn("default_mode_request_user_input = true", text)
        self.assertIn("[agents]", text)
        self.assertIn(f"{LEGACY_KEY} = 4", text)
        self.assertIn(f"[{V2_TABLE}]", text)
        self.assertIn(f"{KEY} = 5", text)

    def test_migrates_legacy_max_threads_to_canonical_when_host_proven(self) -> None:
        merged, action = merge_subagent_limit(f"[agents]\n{LEGACY_KEY} = 6\n", 3, schema="canonical")
        self.assertEqual(action, "migrated")
        self.assertIn(f"{KEY} = 3", merged)
        self.assertNotIn(f"{LEGACY_KEY} =", merged)

    def test_canonical_updates_dotted_assignment(self) -> None:
        merged, action = merge_subagent_limit(f"agents.{LEGACY_KEY} = 5\n", 4, schema="canonical")
        self.assertEqual(action, "migrated")
        self.assertEqual(merged, f"agents.{KEY} = 4\n")

    def test_rejects_conflicting_agent_and_v2_effective_caps(self) -> None:
        text = f"[agents]\n{LEGACY_KEY} = 3\n\n[{V2_TABLE}]\n{KEY} = 8\n"
        with self.assertRaisesRegex(ConfigurationError, "conflicting"):
            merge_subagent_limit(text, 3, schema="auto")

    def test_rejects_ambiguous_new_and_alias_keys(self) -> None:
        text = f"[agents]\n{KEY} = 3\n{LEGACY_KEY} = 4\n"
        with self.assertRaisesRegex(ConfigurationError, "both"):
            analyze_config(__import__("tomllib").loads(text))

    def test_legacy_v2_only_is_effective_but_backend_ambiguous_without_explicit_v2(self) -> None:
        info = analyze_config({"features": {"multi_agent_v2": {KEY: 4}}})
        self.assertEqual(info["effective_subagent_limit"], 3)
        self.assertFalse(info["backend_safe_without_host_probe"])
        info = analyze_config({"features": {"multi_agent_v2": {"enabled": True, KEY: 4}}})
        self.assertTrue(info["backend_safe_without_host_probe"])

    def test_rejects_non_positive_limit(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, ">= 1"):
            merge_subagent_limit("", 0)

    def test_dry_run_does_not_write(self) -> None:
        result = configure_limit(codex_home=self.codex_home, max_subagents=3, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.codex_home.exists())


if __name__ == "__main__":
    unittest.main()
