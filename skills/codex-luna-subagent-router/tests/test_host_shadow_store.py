from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_shadow_store  # noqa: E402


def result(usage_status="consistent", mismatched=None, interrupt="not_observed", truncated=False):
    reason = {
        "consistent": "core_fields_equal",
        "divergent": "known_fields_differ",
        "inconclusive": "native_usage_unknown",
    }[usage_status]
    return {
        "usage_comparison": {
            "status": usage_status,
            "reason": reason,
            "comparable_fields": ["total_tokens", "input_tokens", "output_tokens"] if usage_status != "inconclusive" else [],
            "mismatched_fields": list(mismatched or []),
        },
        "interruption": {"status": interrupt},
        "coordination_truncated": truncated,
    }


class HostShadowStoreTests(unittest.TestCase):
    def test_row_is_sanitized_and_contains_no_raw_ids_or_token_values(self):
        row = host_shadow_store.from_result(
            result(), "project-test",
            session_id="sess_secret", turn_id="turn_secret", subagent_id="subagent_secret",
        )
        text = json.dumps(row, sort_keys=True)
        self.assertNotIn("sess_secret", text)
        self.assertNotIn("turn_secret", text)
        self.assertNotIn("subagent_secret", text)
        self.assertNotIn("150", text)
        self.assertEqual(len(row["evidence_id"]), 24)

    def test_evidence_id_is_stable_for_same_identity_and_changes_for_turn(self):
        a = host_shadow_store.from_result(result(), "global", session_id="s", turn_id="t1", subagent_id="a")
        b = host_shadow_store.from_result(result(), "global", session_id="s", turn_id="t1", subagent_id="a")
        c = host_shadow_store.from_result(result(), "global", session_id="s", turn_id="t2", subagent_id="a")
        self.assertEqual(a["evidence_id"], b["evidence_id"])
        self.assertNotEqual(a["evidence_id"], c["evidence_id"])

    def test_statistics_use_latest_observation_per_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "host-shadow.jsonl"
            first = host_shadow_store.from_result(
                result("inconclusive"), "project-test", session_id="s", turn_id="t", subagent_id="a",
            )
            first["recorded_at"] = "2026-09-30T00:00:00+00:00"
            second = host_shadow_store.from_result(
                result("consistent", interrupt="confirmed_interrupted"), "project-test",
                session_id="s", turn_id="t", subagent_id="a",
            )
            second["recorded_at"] = "2026-09-30T00:01:00+00:00"
            host_shadow_store.append(path, first)
            host_shadow_store.append(path, second)
            stats = host_shadow_store.statistics(path, "project-test")
        self.assertEqual(stats["observations"], 2)
        self.assertEqual(stats["unique_evidence"], 1)
        self.assertEqual(stats["latest_usage_statuses"], {"consistent": 1})
        self.assertEqual(stats["latest_interruption_statuses"], {"confirmed_interrupted": 1})

    def test_unknown_usage_field_is_rejected(self):
        bad = result("divergent", mismatched=["private_token_field"])
        with self.assertRaisesRegex(ValueError, "unknown usage fields"):
            host_shadow_store.from_result(bad, "global", session_id="s", turn_id="t", subagent_id="a")


if __name__ == "__main__":
    unittest.main()
