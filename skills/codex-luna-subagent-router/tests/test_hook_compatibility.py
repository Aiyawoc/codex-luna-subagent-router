"""Synthetic contracts only. These tests are not Desktop loading/trust evidence."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_token_accounting import Sandbox, AGENT, PARENT, counter, event, SCRIPTS
from test_turn_usage import TURN, TURN2, root_meta, ctx, terminal
import configure_token_accounting as config
import hook_observability as hooks
import inspect_guided_install as preflight
import outcome_store as store
import system_diagnostics as diagnostics
import token_usage as usage
import turn_usage as turns


class HookCompatibilityTests(Sandbox):
    def settings(self, **changes):
        value = json.loads(self.rpath.read_text())
        value.update(changes)
        self.rpath.write_text(json.dumps(value), encoding="utf-8")
        return value

    def terminal_payload(self, name="Interrupt", turn=TURN):
        payload = dict(hook_event_name=name, session_id=PARENT, cwd=str(self.project),
                       transcript_path="PRIVATE-TRANSCRIPT", prompt="PRIVATE-PROMPT",
                       last_assistant_message="PRIVATE-ANSWER")
        if name == "Interrupt":
            payload["turn_id"] = turn
        else:
            payload["reason"] = "other"
        return payload

    def enable_lifecycle(self):
        return self.settings(token_accounting_scope="main_and_subagents",
                             token_accounting_lifecycle_hooks="on")

    def make_turn(self):
        self.enable_lifecycle()
        parent = self.home / "sessions/parent.jsonl"
        parent.write_text(json.dumps(root_meta()) + "\n", encoding="utf-8")
        payload = dict(session_id=PARENT, turn_id=TURN, transcript_path=str(parent),
                       hook_event_name="UserPromptSubmit", cwd=str(self.project))
        turns.begin(payload, self.upath, "global", None)
        with parent.open("a", encoding="utf-8") as handle:
            for row in (ctx(), event()):
                handle.write(json.dumps(row) + "\n")
        turns.finish(payload, self.upath, "global", None, mark_stopped=False)
        return parent, payload

    def test_four_hooks_remain_default_and_legacy_display_is_preserved(self):
        result = config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True)
        self.assertEqual(set(result["events"]), set(config.EVENTS))
        self.assertEqual(result["summary"], "legacy")
        self.assertEqual(result["lifecycle_hooks"], "off")
        self.assertNotIn("token_accounting_summary", json.loads(self.rpath.read_text()))

    def test_newly_enabled_accounting_is_silent_and_explicit_choice_survives(self):
        self.settings(token_accounting="off")
        config.configure(self.rpath, "on")
        self.assertEqual(json.loads(self.rpath.read_text())["token_accounting_summary"], "silent")
        config.configure(self.rpath, "on", summary="detailed")
        config.configure(self.rpath, "off")
        self.assertEqual(json.loads(self.rpath.read_text())["token_accounting_summary"], "detailed")

    def test_advisory_events_require_separate_confirmation_without_partial_writes(self):
        original = self.rpath.read_bytes()
        with self.assertRaises(ValueError):
            config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True, lifecycle_hooks="on")
        self.assertEqual(original, self.rpath.read_bytes())
        self.assertFalse((self.home / "hooks.json").exists())

    def test_six_event_configuration_has_event_specific_timeouts(self):
        result = config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True,
                                  lifecycle_hooks="on", lifecycle_hooks_supported=True, summary="brief")
        self.assertEqual(set(result["events"]), set(config.ALL_EVENTS))
        definitions = json.loads((self.home / "hooks.json").read_text())["hooks"]
        for name, groups in definitions.items():
            handler = groups[0]["hooks"][0]
            self.assertEqual(handler["timeout"], 3 if name in hooks.TERMINAL_EVENTS else 5)
            self.assertNotIn("async", handler)
        self.assertFalse((self.home / "config.toml").exists())

    def test_disabling_removes_only_router_owned_six_handlers(self):
        user = {"type": "command", "command": "keep-user-hook", "timeout": 1}
        path = self.home / "hooks.json"
        path.write_text(json.dumps({"hooks": {"Interrupt": [{"hooks": [user]}]}}))
        config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True,
                         lifecycle_hooks="on", lifecycle_hooks_supported=True)
        config.configure(self.rpath, "off")
        self.assertEqual(json.loads(path.read_text()), {"hooks": {"Interrupt": [{"hooks": [user]}]}})

    def test_dry_run_does_not_write_configuration_or_health(self):
        before = {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True,
                         lifecycle_hooks="on", lifecycle_hooks_supported=True, dry_run=True)
        after = {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_preflight_checks_selected_events_not_always_six(self):
        config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True)
        q5 = next(item for item in preflight.inspect(self.home, install_mode="fresh")["questions"] if item["number"] == 5)
        self.assertEqual(set(q5["current"]["current_hook_events"]), set(config.EVENTS))
        config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True,
                         lifecycle_hooks="on", lifecycle_hooks_supported=True)
        q5 = next(item for item in preflight.inspect(self.home, install_mode="fresh")["questions"] if item["number"] == 5)
        self.assertEqual(set(q5["current"]["current_hook_events"]), set(config.ALL_EVENTS))

    def test_invalid_display_choice_is_rejected(self):
        with self.assertRaises(ValueError):
            config.configure(self.rpath, "on", summary="invented")

    def test_inline_owned_hook_is_diagnosed_but_not_duplicated(self):
        path = self.home / "config.toml"
        path.write_text('[[hooks.stop]]\n[[hooks.stop.hooks]]\ntype = "command"\ncommand = "fixture"\n'
                        'status_message = "codex-luna-subagent-router:token-accounting"\n')
        before = path.read_bytes()
        result = diagnostics.collect(global_scope=True)
        self.assertIn("Stop", result["hooks"]["configured_events"])
        self.assertIn("inline", result["hooks"]["managed_source_kinds"])
        with self.assertRaisesRegex(ValueError, "another Router hook source"):
            config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / "hooks.json").exists())

    def test_explicit_disabled_hook_alias_is_not_overridden(self):
        (self.home / "config.toml").write_text('[features]\nhooks = true\ncodex_hooks = false\n')
        with self.assertRaisesRegex(ValueError, "disabled or restricted"):
            config.configure(self.rpath, "on", install_hooks=True, hooks_supported=True)
        self.assertEqual(diagnostics.collect(global_scope=True)["hooks"]["local_policy"], "disabled")

    def test_plugin_build_keeps_four_default_and_six_explicit(self):
        tools = SCRIPTS.parents[2] / "tools"
        if not (tools / "build_plugin.py").is_file():
            self.skipTest("source-only package builder is not shipped in the Core")
        with patch.object(sys, "path", [str(tools), *sys.path]):
            import build_plugin
        self.assertEqual(set(build_plugin.hook_definitions()["hooks"]), set(hooks.BASE_EVENTS))
        definitions = build_plugin.hook_definitions(lifecycle_hooks=True)["hooks"]
        self.assertEqual(set(definitions), set(hooks.ALL_EVENTS))
        for event in hooks.TERMINAL_EVENTS:
            self.assertEqual(definitions[event][0]["hooks"][0]["timeout"], 3)

    def test_silent_subagent_stop_still_collects_usage(self):
        self.settings(token_accounting_summary="silent")
        self.transcript()
        output = usage.hook(self.hook_payload(), self.upath)
        self.assertEqual(output, {"continue": True})
        self.assertEqual(usage.load_latest(self.upath)[0][usage.usage_id(AGENT, PARENT)]["snapshot"]["counts"], counter())

    def test_preview_respects_silent_without_needing_an_active_turn(self):
        self.settings(token_accounting_summary="silent", token_accounting_scope="main_and_subagents")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "turn_usage.py"), "preview", "--respect-summary", "--json"],
                              cwd=self.project, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)["display"])
        self.assertFalse(turns.ledger_path(self.upath).exists())

    def test_lifecycle_is_opt_in_and_disabled_accounting_writes_nothing(self):
        payload = self.terminal_payload()
        self.assertEqual(usage.hook(payload, self.upath), {})
        self.assertFalse(hooks.state_dir(self.upath).exists())
        self.enable_lifecycle()
        self.settings(token_accounting="off")
        self.assertEqual(usage.hook(payload, self.upath), {})
        self.assertFalse(hooks.state_dir(self.upath).exists())

    def test_interrupt_never_reads_transcripts_or_usage_ledgers(self):
        self.enable_lifecycle()
        with patch.object(store, "load_lines", side_effect=AssertionError("ledger scan")), \
                patch.object(turns, "read_usage", side_effect=AssertionError("transcript scan")):
            self.assertEqual(usage.hook(self.terminal_payload(), self.upath), {})
        self.assertFalse(self.upath.exists())
        self.assertFalse(turns.ledger_path(self.upath).exists())
        self.assertEqual(hooks.terminal_evidence(self.upath, "global", PARENT, TURN)["state"], "interrupted")

    def test_terminal_receipt_is_idempotent_and_content_free(self):
        first = hooks.record_terminal(self.terminal_payload(), self.upath, "global")
        before = {str(p): p.read_bytes() for p in hooks.state_dir(self.upath).rglob("*") if p.is_file()}
        second = hooks.record_terminal(self.terminal_payload(), self.upath, "global")
        self.assertEqual(first, second)
        self.assertEqual(before, {str(p): p.read_bytes() for p in hooks.state_dir(self.upath).rglob("*") if p.is_file()})
        raw = b"".join(before.values()).decode()
        for secret in ("PRIVATE", str(self.project), str(self.home), PARENT, TURN):
            self.assertNotIn(secret, raw)

    def test_interrupt_freezes_known_counts_without_claiming_complete(self):
        parent, payload = self.make_turn()
        ledger = turns.ledger_path(self.upath)
        before = ledger.read_bytes()
        original = turns.load(ledger)[(PARENT, TURN)]
        self.assertEqual(original["main_snapshot"]["status"], "partial")
        usage.hook(self.terminal_payload(), self.upath)
        self.assertEqual(ledger.read_bytes(), before)
        with parent.open("a", encoding="utf-8") as handle:
            for row in (event(counter(100000, 50000, 10000, 5000)), terminal()):
                handle.write(json.dumps(row) + "\n")
        turns.finish(payload, self.upath, "global", None, refresh_sealed=True)
        usage.hook({**payload, "hook_event_name": "Stop"}, self.upath)
        self.assertEqual(ledger.read_bytes(), before)
        result = turns.statistics(self.upath)[0]
        self.assertEqual(result["execution"]["state"], "interrupted")
        self.assertEqual(result["main_snapshot"], original["main_snapshot"])
        with self.assertRaisesRegex(turns.TurnUsageError, "turn_interrupted"):
            turns.preview(self.upath, "global", None, session=PARENT, turn=TURN)
        turns.begin({**payload, "turn_id": TURN2}, self.upath, "global", None)
        self.assertEqual(turns.load(ledger)[(PARENT, TURN)]["main_snapshot"], original["main_snapshot"])

    def test_wrong_scope_or_turn_cannot_freeze_another_execution(self):
        _, payload = self.make_turn()
        hooks.record_terminal(self.terminal_payload(turn=TURN2), self.upath, "global")
        hooks.record_terminal(self.terminal_payload(), self.upath, "other-scope")
        row = turns.load(turns.ledger_path(self.upath))[(PARENT, TURN)]
        self.assertFalse(hooks.interrupted(self.upath, row))

    def test_late_child_registration_cannot_extend_interrupted_parent(self):
        _, _ = self.make_turn()
        usage.hook(self.terminal_payload(), self.upath)
        before = turns.ledger_path(self.upath).read_bytes()
        self.transcript()
        usage.hook(self.hook_payload("SubagentStart"), self.upath)
        usage.hook(self.hook_payload("SubagentStop"), self.upath)
        self.assertEqual(turns.ledger_path(self.upath).read_bytes(), before)
        self.assertTrue(self.upath.exists())  # Independent child lifetime accounting remains valid.

    def test_corrupt_terminal_metadata_does_not_hide_saved_counts(self):
        _, _ = self.make_turn()
        usage.hook(self.terminal_payload(), self.upath)
        path = next((hooks.state_dir(self.upath) / "terminal").glob("*.json"))
        path.write_text("invalid-json")
        result = turns.statistics(self.upath)[0]
        self.assertEqual(result["main_snapshot"]["counts"], counter())
        self.assertEqual(result["execution"]["source"], "terminal_receipt_unavailable")
        self.assertTrue(result["execution"]["accounting_refresh_frozen"])

    def test_stop_recovery_does_not_reuse_interrupted_preterminal_boundary(self):
        _, payload = self.make_turn()
        ledger = turns.ledger_path(self.upath)
        old = turns.load(ledger)[(PARENT, TURN)]
        candidate = copy.deepcopy(old)
        candidate["end_cursor"] = candidate["cursor"]
        turns.save(ledger, candidate, old)
        usage.hook(self.terminal_payload(), self.upath)
        recovered, can_measure = turns._stop_recovery_row(
            {**payload, "turn_id": TURN2}, self.upath, "global", None)
        self.assertFalse(can_measure)
        self.assertIsNone(recovered["cursor"])
        self.assertEqual(recovered["main_snapshot"]["status"], "unavailable")

    def test_session_end_without_turn_never_marks_a_turn_successful(self):
        _, _ = self.make_turn()
        ledger = turns.ledger_path(self.upath)
        before = ledger.read_bytes()
        usage.hook(self.terminal_payload("SessionEnd"), self.upath)
        self.assertEqual(before, ledger.read_bytes())
        execution = turns.statistics(self.upath)[0]["execution"]
        self.assertEqual(execution["state"], "unknown")
        self.assertTrue(execution["session_end_observed"])

    def test_unknown_terminal_identity_is_not_inferred(self):
        payload = self.terminal_payload()
        payload.pop("turn_id")
        with self.assertRaises(ValueError):
            hooks.record_terminal(payload, self.upath, "global")
        self.assertFalse(hooks.state_dir(self.upath).exists())

    def test_receipt_cannot_make_host_trust_or_build_verified(self):
        self.transcript()
        usage.hook(self.hook_payload(), self.upath)
        result = diagnostics.collect(global_scope=True)
        receipts = result["hooks"]["handler_receipts"]
        self.assertEqual(receipts["events"]["SubagentStop"]["phase"], "handled")
        self.assertFalse(receipts["host_verified"])
        self.assertEqual(result["hooks"]["host_hook_trust"], "unverified")
        self.assertEqual(result["hooks"]["host_event_execution"], "unverified")

    def test_health_failure_is_visible_and_does_not_persist_exception_text(self):
        with patch.object(usage, "collect", side_effect=ValueError("PRIVATE-ERROR")):
            with self.assertRaises(ValueError):
                usage.hook(self.hook_payload(), self.upath)
        self.assertEqual(hooks.health(self.upath, "global")["events"]["SubagentStop"]["phase"], "failed")
        result = diagnostics.collect(global_scope=True)
        self.assertIn("hook_handler_failure_observed", result["warnings"])
        for path in hooks.state_dir(self.upath).rglob("*.json"):
            self.assertNotIn("PRIVATE", path.read_text())

    def test_health_writer_failure_does_not_block_collection(self):
        self.transcript()
        with patch.object(hooks, "_write", side_effect=OSError("disk unavailable")):
            usage.hook(self.hook_payload(), self.upath)
        self.assertTrue(self.upath.exists())

    def test_late_health_completion_cannot_overwrite_newer_invocation(self):
        first = hooks.received(self.upath, "global", self.hook_payload())
        second = hooks.received(self.upath, "global", self.hook_payload())
        hooks.handled(second)
        hooks.handled(first, failed=True)
        self.assertEqual(hooks.health(self.upath, "global")["events"]["SubagentStop"]["phase"], "handled")

    def test_unfinished_receipt_is_not_reported_as_proven_timeout(self):
        hooks.received(self.upath, "global", self.hook_payload())
        row = hooks.health(self.upath, "global")["events"]["SubagentStop"]
        self.assertEqual(row["phase"], "received")
        self.assertIsNone(row["elapsed_ms"])

    def test_health_is_read_only_and_version_bound(self):
        hooks.received(self.upath, "global", self.hook_payload())
        before = {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        with patch.object(hooks.runtime_support, "skill_version", return_value="different-build"):
            self.assertEqual(hooks.health(self.upath, "global")["events"]["SubagentStop"]["phase"], "stale_runtime")
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_oversized_terminal_evidence_fails_closed_without_rewrite(self):
        hooks.record_terminal(self.terminal_payload(), self.upath, "global")
        path = next((hooks.state_dir(self.upath) / "terminal").glob("*.json"))
        raw = b"x" * (hooks.MAX_STATE_BYTES + 1)
        path.write_bytes(raw)
        with self.assertRaises(ValueError):
            hooks.record_terminal(self.terminal_payload(), self.upath, "global")
        self.assertEqual(path.read_bytes(), raw)

    def test_malformed_terminal_entrypoint_never_emits_control_fields(self):
        self.enable_lifecycle()
        payload = self.terminal_payload()
        payload.pop("turn_id")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "token_usage.py"), "hook"],
                              input=json.dumps(payload), cwd=self.project, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        output = json.loads(proc.stdout)
        self.assertEqual(set(output), {"systemMessage"})
        self.assertNotIn("PRIVATE", proc.stdout)


if __name__ == "__main__":
    unittest.main()
