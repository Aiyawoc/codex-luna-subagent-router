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

    def test_creates_agents_table(self) -> None:
        result = configure_limit(codex_home=self.codex_home, max_subagents=3, dry_run=False)
        target = self.codex_home / "config.toml"
        self.assertEqual(result["action"], "created")
        self.assertEqual(target.read_text(encoding="utf-8"), f"[agents]\n{KEY} = 3\n")

    def test_preserves_other_config(self) -> None:
        target = self.codex_home / "config.toml"
        target.parent.mkdir(parents=True)
        target.write_text("[features]\ndefault_mode_request_user_input = true\n", encoding="utf-8")
        configure_limit(codex_home=self.codex_home, max_subagents=4, dry_run=False)
        text = target.read_text(encoding="utf-8")
        self.assertIn("[features]", text)
        self.assertIn("default_mode_request_user_input = true", text)
        self.assertIn("[agents]", text)
        self.assertIn(f"{KEY} = 4", text)

    def test_updates_existing_value_and_preserves_comment(self) -> None:
        merged, action = merge_subagent_limit(
            f"[agents]\n{KEY} = 8 # user choice\n",
            2,
        )
        self.assertEqual(action, "updated")
        self.assertIn(f"{KEY} = 2 # user choice", merged)

    def test_migrates_legacy_max_threads(self) -> None:
        merged, action = merge_subagent_limit("[agents]\nmax_threads = 6\n", 3)
        self.assertEqual(action, "migrated_legacy")
        self.assertIn(f"{KEY} = 3", merged)
        self.assertNotIn("max_threads =", merged)

    def test_updates_dotted_assignment(self) -> None:
        merged, action = merge_subagent_limit("agents.max_threads = 5\n", 4)
        self.assertEqual(action, "migrated_legacy")
        self.assertEqual(merged, f"agents.{KEY} = 4\n")

    def test_rejects_non_positive_limit(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, ">= 1"):
            merge_subagent_limit("", 0)

    def test_rejects_ambiguous_new_and_legacy_keys(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "both"):
            merge_subagent_limit(
                f"[agents]\n{KEY} = 3\nmax_threads = 4\n",
                3,
            )

    def test_dry_run_does_not_write(self) -> None:
        result = configure_limit(codex_home=self.codex_home, max_subagents=3, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.codex_home.exists())


if __name__ == "__main__":
    unittest.main()
