#!/usr/bin/env python3
"""Exercise plugin packaging/migration with bundled Python in a synthetic Host home."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import build_plugin


def run(args, cwd, env, payload=None, expected=0):
    result = subprocess.run(args, cwd=cwd, env=env, input=payload, text=True,
                            encoding="utf-8", capture_output=True, timeout=180)
    if result.returncode != expected:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"plugin smoke command returned {result.returncode}, expected {expected}")
    return result.stdout


def smoke(target, dist, *, lifecycle_hooks=False):
    ext = ".zip" if target.startswith("windows-") else ".tar.gz"
    version = build_plugin.runtime.skill_version(build_plugin.CORE)
    variant = "plugin-lifecycle" if lifecycle_hooks else "plugin"
    archive = dist / f"router-{variant}-{version}-{target}{ext}"
    checksum = archive.with_name(archive.name + ".sha256").read_text().strip().split("  ", 1)
    assert checksum == [build_plugin.runtime.file_digest(archive), archive.name], "plugin checksum mismatch"
    with tempfile.TemporaryDirectory(prefix="router-plugin-smoke-") as tmp:
        base = Path(tmp).resolve() / "中文 空格"
        base.mkdir()
        build_plugin.extract(archive, base)
        market = base / "agent-router-marketplace"
        catalog = json.loads((market / ".agents/plugins/marketplace.json").read_text())
        source = market / catalog["plugins"][0]["source"]["path"]
        plugin = base / "native cache" / "agent-router" / "local"
        shutil.copytree(source, plugin, symlinks=True)
        core = plugin / "core/codex-luna-subagent-router"
        definitions = json.loads((plugin / "hooks/hooks.json").read_text())["hooks"]
        expected_events = build_plugin.ps.tokens.ALL_EVENTS if lifecycle_hooks else build_plugin.ps.tokens.EVENTS
        assert set(definitions) == set(expected_events)
        home = base / "home"; home.mkdir()
        project = base / "project"; project.mkdir()
        env = dict(os.environ, CODEX_HOME=str(home), CODEX_SKILLS_DIR=str(base / "installed skills"),
                   CODEX_AGENTS_DIR=str(home / "agents"), PLUGIN_ROOT=str(plugin),
                   PLUGIN_DATA=str(base / "plugin data"), PATH="", PYTHONHOME="/invalid", PYTHONPATH="/invalid")
        env.pop("CODEX_ROUTER_PYTHON", None)
        python = core / ("runtime/python/python.exe" if os.name == "nt" else "runtime/python/bin/python3")
        command = [str(python), *build_plugin.runtime.FLAGS, str(core / "scripts/runtime_dispatch.py")]
        proof = json.loads(run(command + ["doctor", "--verify"], project, env))
        assert proof["mode"] == "bundled" and proof["target"] == target
        proof = json.loads(run(command + ["plugin_control", "inspect", "--verify", "--json"], project, env))
        assert proof["integrity"]["status"] == "ok" and proof["host_loaded"] == "unverified"
        assert not proof["active"]
        # Install a real complete package as the disposable migration baseline.
        run(command + ["install", "--global", "--install-mode", "fresh"], project, env)
        legacy = base / "installed skills/codex-luna-subagent-router"
        legacy_python = legacy / ("runtime/python/python.exe" if os.name == "nt" else "runtime/python/bin/python3")
        legacy_command = [str(legacy_python), *build_plugin.runtime.FLAGS, str(legacy / "scripts/runtime_dispatch.py")]
        routing = home / "codex-luna-subagent-router/routing.json"
        build_plugin.write_json(routing, dict(schema_version="2.1", routing_mode="adaptive", evidence_calibration="off"))
        lifecycle_flags = ["--lifecycle-hooks", "on", "--lifecycle-hooks-supported"] if lifecycle_hooks else []
        run(legacy_command + ["configure_token_accounting", "--scope", "user", "--mode", "on", "--install-hooks", "--hooks-supported", *lifecycle_flags], project, env)
        saved_config = routing.read_bytes()
        saved_hooks = (home / "hooks.json").read_bytes()
        saved_profiles = {p.name: p.read_bytes() for p in (home / "agents").glob("*.toml")}
        ledger = home / "state/codex-luna-subagent-router/usage.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"")
        input_event = dict(hook_event_name="SubagentStart", cwd=str(project), session_id="plugin-smoke-parent",
                           agent_id="plugin-smoke-worker", agent_type="fixture-only")
        def event_command(event):
            definition = definitions[event][0]["hooks"][0]
            if os.name == "nt":
                # Simulate the documented Windows command environment expansion.
                return definition["commandWindows"].replace("%PLUGIN_ROOT%", str(plugin))
            return ["/bin/sh", "-c", definition["command"]]

        hook_command = event_command("SubagentStart")
        terminal_payloads = [
            dict(hook_event_name="Interrupt", cwd=str(project), session_id="plugin-smoke-parent", turn_id="plugin-smoke-turn"),
            dict(hook_event_name="SessionEnd", cwd=str(project), session_id="plugin-smoke-parent", reason="other"),
        ] if lifecycle_hooks else []
        sidecar = ledger.with_name(ledger.stem + ".hook-state")
        for payload in terminal_payloads:
            assert json.loads(run(event_command(payload["hook_event_name"]), project, env, json.dumps(payload))) == {}
        assert not sidecar.exists(), "plugin wrote state before explicit activation"
        run(hook_command, project, env, json.dumps(input_event))
        assert ledger.read_bytes() == b"", "plugin collected before explicit activation"
        flags = ["--confirm", "--quiescent", "--host-installed-reviewed", "--setup-reviewed"]
        activation = json.loads(run(command + ["plugin_control", "activate", "--install-mode", "upgrade", *flags], project, env))
        assert activation["status"] == "activated" and activation["hook_trust"] == "review_required"
        assert not legacy.exists()
        assert routing.read_bytes() == saved_config and ledger.read_bytes() == b""
        run(hook_command, project, env, json.dumps(input_event))
        first_usage = ledger.read_bytes()
        assert first_usage, "synthetic native event did not reach the existing Core handler"
        run(hook_command, project, env, json.dumps(input_event))
        assert ledger.read_bytes() == first_usage, "duplicate event created another usage entry"
        terminal_runs = []
        for payload in terminal_payloads:
            event = payload["hook_event_name"]
            handler = definitions[event][0]["hooks"][0]
            assert handler["timeout"] == 3 and not handler.get("async", False)
            started = time.monotonic()
            assert json.loads(run(event_command(event), project, env, json.dumps(payload))) == {}
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            before_repeat = {p.name: p.read_bytes() for p in (sidecar / "terminal").glob("*.json")}
            assert json.loads(run(event_command(event), project, env, json.dumps(payload))) == {}
            assert {p.name: p.read_bytes() for p in (sidecar / "terminal").glob("*.json")} == before_repeat
            assert ledger.read_bytes() == first_usage, "advisory event mutated token counts"
            terminal_runs.append(dict(event=event, elapsed_ms=elapsed_ms, duplicate_idempotent=True))
        if lifecycle_hooks:
            assert len(list((sidecar / "terminal").glob("*.json"))) == 2
            diagnostics = json.loads(run(command + ["diagnostics", "--json"], project, env))
            for event in ("Interrupt", "SessionEnd"):
                assert diagnostics["hooks"]["handler_receipts"]["events"][event]["phase"] == "handled"
            assert diagnostics["hooks"]["host_event_execution"] == "unverified"
        sidecar_before_disable = {p.relative_to(sidecar).as_posix(): p.read_bytes() for p in sidecar.rglob("*") if p.is_file()}
        state = json.loads(run(command + ["plugin_control", "inspect", "--verify", "--json"], project, env))
        assert state["active"] and state["conflicts"] == []
        run(command + ["install", "--global", "--install-mode", "fresh"], project, env, expected=2)
        run(command + ["plugin_control", "deactivate", "--confirm", "--quiescent"], project, env)
        input_event["agent_id"] = "must-not-be-recorded"
        run(hook_command, project, env, json.dumps(input_event))
        for payload in terminal_payloads:
            disabled_payload = {**payload, "session_id": "must-not-be-recorded"}
            assert json.loads(run(event_command(payload["hook_event_name"]), project, env, json.dumps(disabled_payload))) == {}
        assert {p.relative_to(sidecar).as_posix(): p.read_bytes() for p in sidecar.rglob("*") if p.is_file()} == sidecar_before_disable
        assert ledger.read_bytes() == first_usage
        run(command + ["plugin_control", "rollback", "--confirm", "--quiescent", "--host-disabled-reviewed"], project, env)
        assert legacy.exists() and routing.read_bytes() == saved_config
        assert (home / "hooks.json").read_bytes() == saved_hooks
        assert {p.name: p.read_bytes() for p in (home / "agents").glob("*.toml")} == saved_profiles
        assert ledger.read_bytes() == first_usage
        assert {p.relative_to(sidecar).as_posix(): p.read_bytes() for p in sidecar.rglob("*") if p.is_file()} == sidecar_before_disable
        run(legacy_command + ["doctor", "--verify"], project, env)
        run(command + ["plugin_control", "inspect", "--verify", "--json"], project, env)
        assert not (plugin / ".serena").exists()
        print(json.dumps(dict(target=target, status="passed", variant=variant, checksum_verified=True,
                              lifecycle_events=terminal_runs, sidecar_preserved=True, bundled_runtime=True,
                              same_core=True, unicode_space_path=True, preactivation_inert=True,
                              migration=True, duplicate_event_idempotent=True, deactivate=True,
                              rollback=True, ledgers_preserved=True, synthetic_events_only=True,
                              actual_host_loading="NOT VERIFIED", trust_database_changed=False), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=build_plugin.TARGETS, required=True)
    parser.add_argument("--dist", type=Path, default=Path("dist-plugin"))
    parser.add_argument("--lifecycle-hooks", action="store_true", help="Test the separately built six-event candidate instead of the default plugin.")
    args = parser.parse_args()
    smoke(args.target, args.dist, lifecycle_hooks=args.lifecycle_hooks)
