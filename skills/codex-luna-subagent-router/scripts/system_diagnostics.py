#!/usr/bin/env python3
"""Read-only unified Router diagnostics. Never refresh transcripts or mutate trust/state."""
from __future__ import annotations

import argparse
import json
import os
import tomllib
from collections import Counter
from pathlib import Path

import configure_subagent_limit as concurrency
import configure_token_accounting as tokens
import host_shadow_store
import host_capabilities
import outcome_store as store
import plugin_support
import runtime_support
import token_usage
import turn_usage


def _error(code):
    return {"status": "unavailable", "reason": code}


def _runtime(verify_package=False):
    try:
        result = runtime_support.validate_runtime()
        root = runtime_support.ROOT
        manifest = root / "PACKAGE-MANIFEST.json"
        if verify_package and manifest.is_file():
            result["package_integrity"] = "verified"
            result["verified_files"] = runtime_support.verify_package(root)
        elif manifest.is_file():
            result["package_integrity"] = "not_checked"
        else:
            result["package_integrity"] = "not_applicable_source_development"
        result.pop("executable", None)
        result["version"] = runtime_support.skill_version(root)
        result["distribution"] = (
            "native_plugin_core" if plugin_support.plugin_root(root)
            else "complete_package" if result["mode"] == "bundled"
            else "source_development"
        )
        result["status"] = "ok"
        return result
    except (OSError, ValueError, ImportError):
        return _error("runtime_or_package_invalid")


def _config(scope_root):
    home = store.codex_home().expanduser().resolve()
    global_routing = home / "codex-luna-subagent-router/routing.json"
    project_routing = (
        Path(scope_root) / ".codex/codex-luna-subagent-router/routing.json"
        if scope_root else None
    )
    selected = project_routing if project_routing and project_routing.is_file() else global_routing
    try:
        routing = tokens.read_json(selected)
        global_toml = home / "config.toml"
        project_toml = Path(scope_root) / ".codex/config.toml" if scope_root else None
        layers = []
        for label, path in (("user", global_toml), ("project", project_toml)):
            if path is None or not path.is_file():
                continue
            store.safe_path(path)
            value = tomllib.loads(path.read_text(encoding="utf-8"))
            info = concurrency.analyze_config(value)
            if info["effective_subagent_limit"] is not None:
                layers.append({
                    "layer": label,
                    "effective_subagent_limit": info["effective_subagent_limit"],
                    "backend_safe_without_host_probe": info["backend_safe_without_host_probe"],
                })
        safe = [row["effective_subagent_limit"] for row in layers if row["backend_safe_without_host_probe"]]
        decision = routing.get("decision_engine")
        if not isinstance(decision, dict):
            decision = {"enabled": False, "provider": "off", "source": "absent_default_off"}
        return {
            "status": "ok",
            "configured": bool(routing),
            "source": "project" if selected == project_routing else "user",
            "routing_mode": routing.get("routing_mode"),
            "evidence_calibration": routing.get("evidence_calibration"),
            "token_accounting": routing.get("token_accounting"),
            "token_accounting_scope": routing.get("token_accounting_scope"),
            "token_accounting_collection": routing.get("token_accounting_collection"),
            "max_subagents": min(safe) if safe else None,
            "max_subagent_layers": layers,
            "decision_engine": {
                "enabled": bool(decision.get("enabled")),
                "provider": decision.get("provider", "off"),
                "source": decision.get("source"),
            },
        }
    except (OSError, ValueError, TypeError, KeyError, tomllib.TOMLDecodeError):
        return _error("configuration_invalid")


def _hooks(scope_root, config):
    try:
        home = store.codex_home().expanduser().resolve()
        project = Path(scope_root).resolve() if scope_root else None
        routing_base = (
            project / ".codex" if config.get("source") == "project" and project else home
        )
        hooks = tokens.read_json(routing_base / "hooks.json").get("hooks", {})
        configured_events = []
        for event in tokens.EVENTS:
            owned = [
                handler
                for group in hooks.get(event, [])
                if isinstance(group, dict)
                for handler in group.get("hooks", [])
                if isinstance(handler, dict) and handler.get("statusMessage") == tokens.OWNER
            ]
            if len(owned) == 1:
                configured_events.append(event)

        owner, owner_project = plugin_support.effective_owner(project)
        plugin_owner = bool(owner and owner.get("active_source") == "plugin")
        plugin_owner_matches = False
        if plugin_owner:
            try:
                plugin_owner_matches = plugin_support.owner_matches(
                    Path(owner["plugin_root"]), owner_project
                )[0]
            except (OSError, ValueError, KeyError, TypeError):
                plugin_owner_matches = False
            if plugin_owner_matches:
                definitions = tokens.read_json(
                    Path(owner["plugin_root"]) / "hooks/hooks.json"
                ).get("hooks", {})
                configured_events = [
                    event for event in tokens.EVENTS if event in definitions
                ]

        conflicts = plugin_support.hook_sources(project)
        return {
            "status": "ok",
            "collection_mode": config.get("token_accounting_collection"),
            "configured_events": configured_events,
            "all_four_configured": set(configured_events) == set(tokens.EVENTS),
            "managed_source_count": len(conflicts) + (1 if plugin_owner_matches else 0),
            "managed_source_kinds": sorted({row["kind"] for row in conflicts} | (
                {"native_plugin"} if plugin_owner_matches else set()
            )),
            "plugin_owner_active": plugin_owner,
            "plugin_owner_matches": plugin_owner_matches,
            "host_hook_trust": "unverified",
            "host_event_execution": "unverified",
            "note": "Configured definitions are not proof that the Host trusted or executed them.",
        }
    except (OSError, ValueError, TypeError, KeyError):
        return _error("hook_inventory_invalid")


def _usage(scope_id):
    try:
        stats = token_usage.statistics(scope=scope_id)
        counts = stats.get("known_usage", {}).get("counts", {})
        return {
            "status": "ok",
            "observed_subagents": stats.get("observed_subagents", 0),
            "snapshot_statuses": stats.get("statuses", {}),
            "known_total_tokens": counts.get("total_tokens"),
            "known_input_tokens": counts.get("input_tokens"),
            "known_output_tokens": counts.get("output_tokens"),
            "invalid_usage_rows": stats.get("invalid_usage_rows", 0),
            "invalid_binding_rows": stats.get("invalid_binding_rows", 0),
            "superseded_snapshots": stats.get("superseded_snapshots", 0),
            "source": "saved_ledger_only",
        }
    except (OSError, ValueError, TypeError, KeyError):
        return _error("usage_ledger_invalid")


def _turns(scope_id):
    try:
        rows = turn_usage.statistics(token_usage.default_usage_path(), scope=scope_id)
        phases = Counter(row.get("phase") for row in rows)
        main_statuses = Counter(
            (row.get("main_snapshot") or {}).get("status") for row in rows
        )
        child_statuses = Counter(
            snap.get("status")
            for row in rows
            for snap in (row.get("child_snapshots") or {}).values()
            if isinstance(snap, dict)
        )
        return {
            "status": "ok",
            "registered_turns": len(rows),
            "phases": dict(phases),
            "main_snapshot_statuses": dict(main_statuses),
            "child_snapshot_statuses": dict(child_statuses),
            "registered_children": sum(row.get("registered_children", 0) for row in rows),
            "source": "saved_ledger_only",
        }
    except (OSError, ValueError, TypeError, KeyError):
        return _error("turn_ledger_invalid")


def _plugin(scope_root):
    try:
        project = Path(scope_root).resolve() if scope_root else None
        owner, owner_project = plugin_support.effective_owner(project)
        if not owner:
            return {
                "status": "ok",
                "registered": False,
                "active_source": None,
                "owner_scope": None,
                "integrity": "not_applicable",
                "host_loaded": "unverified",
                "hook_trust": "unverified",
            }
        active = owner.get("active_source")
        integrity = "not_checked"
        owner_matches = False
        if active == "plugin":
            try:
                root = Path(owner["plugin_root"])
                owner_matches = plugin_support.owner_matches(root, owner_project)[0]
                if owner_matches:
                    plugin_support.verify_plugin(root)
                    integrity = "verified"
                else:
                    integrity = "owner_mismatch"
            except (OSError, ValueError, TypeError, KeyError):
                integrity = "invalid"
        return {
            "status": "ok",
            "registered": True,
            "active_source": active,
            "owner_scope": "project" if owner_project else "global",
            "owner_matches": owner_matches,
            "integrity": integrity,
            "host_loaded": "unverified",
            "hook_trust": "unverified",
        }
    except (OSError, ValueError, TypeError, KeyError):
        return _error("plugin_owner_invalid")


def _native_shadow(scope_id):
    try:
        stats = host_shadow_store.statistics(scope=scope_id)
        readiness = host_shadow_store.review_readiness(scope=scope_id)
        return {
            "status": "ok",
            "observations": stats.get("observations", 0),
            "unique_evidence": stats.get("unique_evidence", 0),
            "usage_statuses": stats.get("latest_usage_statuses", {}),
            "lifecycle_statuses": stats.get("latest_interruption_statuses", {}),
            "invalid_rows": stats.get("invalid_rows", 0),
            "usage_review": readiness.get("usage", {}).get("status", "not_ready"),
            "lifecycle_review": readiness.get("lifecycle", {}).get("status", "not_ready"),
            "authoritative": False,
            "automatic_promotion": False,
        }
    except (OSError, ValueError, TypeError, KeyError):
        return _error("native_shadow_invalid")


def _host_capabilities(backend=None, host_version=None):
    if backend is None and host_version is None:
        return {
            "status": "not_selected",
            "backend": None,
            "host_version": None,
            "authoritative": False,
        }
    if backend is None or host_version is None:
        return _error("host_capability_identity_incomplete")
    try:
        result = host_capabilities.snapshot(
            backend=backend,
            host_version=host_version,
        )
        return {"status": "ok", **result}
    except (OSError, ValueError, TypeError, KeyError):
        return _error("host_capability_evidence_invalid")


def _report_output():
    root = store.codex_home().expanduser().resolve() / "state/codex-luna-subagent-router/reports"
    try:
        store.safe_path(root)
        probe = root
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return {
            "status": "ok",
            "directory_exists": root.is_dir(),
            "writable_hint": bool(probe.exists() and os.access(probe, os.W_OK)),
            "write_tested": False,
        }
    except (OSError, ValueError):
        return _error("report_output_path_invalid")


def collect(*, project_root=None, global_scope=False, verify_package=False,
            host_backend=None, host_version=None):
    scope_id, root = store.resolve_scope(project_root, global_scope)
    config = _config(root)
    sections = {
        "runtime": _runtime(verify_package),
        "config": config,
        "hooks": _hooks(root, config),
        "usage": _usage(scope_id),
        "turns": _turns(scope_id),
        "plugin": _plugin(root),
        "native_shadow": _native_shadow(scope_id),
        "host_capabilities": _host_capabilities(host_backend, host_version),
        "report_output": _report_output(),
    }
    unavailable = sorted(
        name for name, value in sections.items()
        if value.get("status") == "unavailable"
    )
    warnings = []
    if sections["usage"].get("invalid_usage_rows", 0):
        warnings.append("invalid_usage_rows")
    if sections["usage"].get("invalid_binding_rows", 0):
        warnings.append("invalid_usage_binding_rows")
    if sections["native_shadow"].get("invalid_rows", 0):
        warnings.append("invalid_native_shadow_rows")
    if sections["hooks"].get("managed_source_count", 0) > 1:
        warnings.append("multiple_managed_hook_sources")
    if (
        config.get("token_accounting") == "on"
        and config.get("token_accounting_collection") == "hooks"
        and not sections["hooks"].get("all_four_configured", False)
    ):
        warnings.append("configured_hook_collection_incomplete")
    if sections["plugin"].get("registered") and sections["plugin"].get("active_source") == "plugin":
        if sections["plugin"].get("integrity") != "verified":
            warnings.append("active_plugin_integrity_not_verified")
    if sections["report_output"].get("status") == "ok" and not sections["report_output"].get("writable_hint"):
        warnings.append("report_output_not_writable_hint")
    return {
        "schema_version": 1,
        "status": "ok" if not unavailable and not warnings else "warning",
        "scope_id": scope_id,
        "read_only": True,
        "refresh_performed": False,
        "trust_changed": False,
        "unavailable_sections": unavailable,
        "warnings": warnings,
        **sections,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--project-root")
    scope.add_argument("--global-scope", action="store_true")
    parser.add_argument("--verify-package", action="store_true")
    parser.add_argument("--host-backend", choices=tuple(host_capabilities.host_adapter.BACKENDS))
    parser.add_argument("--host-version")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = collect(
        project_root=args.project_root,
        global_scope=args.global_scope,
        verify_package=args.verify_package,
        host_backend=args.host_backend,
        host_version=args.host_version,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Router diagnostics: {result['status']} · scope={result['scope_id']}")
        print(f"Runtime: {result['runtime'].get('status')} · version={result['runtime'].get('version', '-')}")
        print(f"Routing: {result['config'].get('routing_mode') or '-'} · token={result['config'].get('token_accounting') or '-'}")
        print(f"Hooks configured: {len(result['hooks'].get('configured_events', []))}/4 · trust={result['hooks'].get('host_hook_trust', 'unverified')}")
        print(f"Usage workers: {result['usage'].get('observed_subagents', 0)} · turns={result['turns'].get('registered_turns', 0)}")
        print(f"Plugin: {result['plugin'].get('active_source') or 'none'} · host_loaded={result['plugin'].get('host_loaded', 'unverified')}")
        caps = result["host_capabilities"]
        print(f"Host capabilities: {caps.get('status')} · backend={caps.get('backend') or '-'} · version={caps.get('host_version') or '-'}")
        print(f"Native shadow evidence: {result['native_shadow'].get('unique_evidence', 0)} · authority=false")
        if result["unavailable_sections"]:
            print("Unavailable: " + ", ".join(result["unavailable_sections"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
