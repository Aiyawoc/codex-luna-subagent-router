#!/usr/bin/env python3
"""Opt-in token accounting and managed SubAgent hooks; never change hook trust."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import outcome_store as store
import hook_observability as hook_state
from configure_evidence_calibration import _routing_path, ConfigurationError

OWNER = "codex-luna-subagent-router:token-accounting"
VERSION = "2.6.1"
EVENTS = hook_state.BASE_EVENTS  # Existing four-event installs stay valid.
TERMINAL_EVENTS = hook_state.TERMINAL_EVENTS
ALL_EVENTS = hook_state.ALL_EVENTS


def read_json(path):
    store.safe_path(path)
    if not path.exists():
        return {}
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ConfigurationError("duplicate JSON config keys")
            data[key] = value
        return data
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ConfigurationError("configuration must be an object")
    return value


def hook_handler(script, python=None, project_root=None, *, validate_bundled_runtime=True):
    script_path = Path(script).absolute()
    skill_root = script_path.parent.parent
    bundled = (skill_root / "runtime/runtime.json").exists()
    if bundled:
        from runtime_support import runtime_executable, validate_runtime
        if validate_bundled_runtime:
            validate_runtime(skill_root)
        python = str(runtime_executable(skill_root))
    else:
        python = str(python or sys.executable)
    script = str(script_path)
    if any(c in python + script for c in "\r\n\x00"):
        raise ConfigurationError("invalid command path")
    root_args = ["--project-root", str(Path(project_root).resolve())] if project_root else []
    if bundled:
        from runtime_support import FLAGS
        args = [python, *FLAGS, str(script_path.with_name("runtime_dispatch.py")), "token_usage",
                *root_args, "--hook-version", VERSION, "hook"]
    else:
        args = [python, script, *root_args, "--hook-version", VERSION, "hook"]
    if os.name == "nt":
        # cmd-style command line, for Codex's Windows command override.
        # Reject metacharacters instead of pretending to escape arbitrary shell code.
        if any(c in " ".join(args) for c in '&|<>^%!?`$"'):
            raise ConfigurationError("Windows command path contains shell metacharacters")
        command = subprocess.list2cmdline(args)
        return dict(type="command", command=command, commandWindows=command, timeout=5, statusMessage=OWNER)
    return dict(type="command", command=shlex.join(args), timeout=5, statusMessage=OWNER)


def merge_hooks(existing, handler=None, *, lifecycle_hooks=False):
    merged = copy.deepcopy(existing)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigurationError("hooks must be an object")
    for event in ALL_EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ConfigurationError("hook event must contain an array")
        cleaned = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ConfigurationError("invalid hook group")
            if any(not isinstance(h, dict) for h in group["hooks"]):
                raise ConfigurationError("invalid hook handler")
            kept = [h for h in group["hooks"] if h.get("statusMessage") != OWNER]
            if kept or not group["hooks"]:
                cleaned.append({**group, "hooks": kept})
        if handler and (event in EVENTS or lifecycle_hooks):
            selected = copy.deepcopy(handler)
            if event in TERMINAL_EVENTS:
                selected["timeout"] = 3
                selected.pop("async", None)
            cleaned.append({**({"matcher": ".*"} if event.startswith("Subagent") else {}), "hooks": [selected]})
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)
    if not hooks:
        merged.pop("hooks", None)
    return merged


def atomic_bytes(path, payload):
    store.safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=".token-accounting-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def configure(routing_path, mode, *, install_hooks=False, hooks_supported=False, script=None, dry_run=False,
              project_root=None, summary=None, lifecycle_hooks=None, lifecycle_hooks_supported=False):
    if mode not in ("on", "off"):
        raise ConfigurationError("token_accounting must be on or off")
    if install_hooks and (mode != "on" or not hooks_supported):
        raise ConfigurationError("confirm UserPromptSubmit/Stop/SubagentStart/SubagentStop support before --install-hooks")
    if summary is not None and summary not in hook_state.SUMMARY_MODES:
        raise ConfigurationError("invalid token summary mode")
    if lifecycle_hooks not in (None, "on", "off"):
        raise ConfigurationError("invalid lifecycle hook mode")
    if lifecycle_hooks == "on" and not (install_hooks and lifecycle_hooks_supported):
        raise ConfigurationError("confirm Interrupt/SessionEnd support before enabling lifecycle hooks")
    routing_path = Path(routing_path)
    hooks_path = routing_path.parent.parent / "hooks.json"
    import plugin_support
    native_plugin = plugin_support.plugin_root(Path(script).parent.parent if script else Path(__file__).resolve().parents[1])
    if install_hooks and native_plugin is None:
        other_sources = [source for source in plugin_support.hook_sources(project_root)
                         if source["kind"] != "json" or Path(source["path"]).absolute() != hooks_path.absolute()]
        if other_sources:
            raise ConfigurationError("another Router hook source is active; review scope/inline migration before installing duplicate handlers")
    if native_plugin and not dry_run:
        if not plugin_support.owner_matches(native_plugin, project_root)[0] or plugin_support.hook_sources(project_root):
            raise ConfigurationError("activate the reviewed plugin migration before applying native token settings; legacy hooks must be backed up first")
    # Hold one config transaction lock to serialize this helper; never alter trust storage.
    with store.locked(routing_path, timeout=0.4) if not dry_run else _noop():
        data = read_json(routing_path)
        if data.get("schema_version") not in ("2.0", "2.1") or data.get("routing_mode") not in ("adaptive", "luna_only"):
            raise ConfigurationError("run guided routing setup first")
        if data.get("token_accounting", "off") not in ("on", "off"):
            raise ConfigurationError("unknown existing token_accounting")
        # mode=on is an explicit answer to the combined question 5. Old on alone
        # does not authorize main-thread collection in the runtime handler.
        proposed = {**data, "token_accounting": mode,
                    "token_accounting_scope": "main_and_subagents",
                    "token_accounting_collection": "hooks" if install_hooks else "manual"}
        # Existing on-without-summary retains legacy display. Newly enabled
        # accounting defaults to silent; explicit existing choices always survive.
        if summary is not None:
            proposed["token_accounting_summary"] = summary
        elif "token_accounting_summary" not in data and data.get("token_accounting") != "on":
            proposed["token_accounting_summary"] = "silent"
        hook_state.summary_mode(proposed)
        if lifecycle_hooks is not None:
            proposed["token_accounting_lifecycle_hooks"] = lifecycle_hooks
        if not install_hooks:
            proposed["token_accounting_lifecycle_hooks"] = "off"
        terminal_on = hook_state.lifecycle_enabled(proposed)
        if terminal_on and not lifecycle_hooks_supported:
            raise ConfigurationError("reconfirm current Host Interrupt/SessionEnd support when configuring lifecycle hooks")
        if native_plugin and terminal_on:
            definitions = read_json(native_plugin / "hooks/hooks.json").get("hooks", {})
            if not set(TERMINAL_EVENTS) <= set(definitions):
                raise ConfigurationError("this plugin package does not declare lifecycle hooks; use a reviewed lifecycle-capable package")
        writes = []
        if proposed != data:
            writes.append((routing_path, proposed))
        if install_hooks:
            import tomllib
            # Detect explicit local disablement; never override it or edit trust DBs.
            for config_path in {store.codex_home() / "config.toml", routing_path.parent.parent / "config.toml"}:
                if config_path.is_file():
                    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
                    features = config.get("features", {})
                    if (not isinstance(features, dict) or features.get("hooks") is False
                            or features.get("codex_hooks") is False or config.get("allow_managed_hooks_only") is True):
                        raise ConfigurationError("platform hooks are disabled or restricted")
        # Explicit manual/off also removes obsolete owned handlers, never user hooks.
        existing = read_json(hooks_path)
        handler = None
        if install_hooks:
            target = Path(script or Path(__file__).with_name("token_usage.py")).absolute()
            if not target.is_file():
                raise ConfigurationError("installed token_usage.py is missing")
            if native_plugin is None:
                handler = hook_handler(target, project_root=project_root)
            # Native plugin definitions are packaged and reviewed by the Host.
            # Do not also install a second user/project handler for the same events.
        merged = existing if native_plugin else merge_hooks(existing, handler, lifecycle_hooks=terminal_on)
        if merged != existing:
            writes.append((hooks_path, merged))
        originals = {p: p.read_bytes() if p.exists() else None for p, _ in writes}
        if not dry_run:
            # A durable first backup prevents accidental loss; later backups are not overwritten.
            for path, original in originals.items():
                backup = path.with_name(path.name + ".token-accounting.backup")
                store.safe_path(backup)
                if original is not None and not backup.exists():
                    atomic_bytes(backup, original)
            applied = []
            try:
                for path, value in writes:
                    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
                    applied.append(path)
            except (OSError, ValueError):
                for path in reversed(applied):
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_bytes(path, originals[path])
                raise
        return dict(action="would_update" if dry_run and writes else "updated" if writes else "unchanged",
                    mode=mode, accounting_scope="main_and_subagents",
                    summary=hook_state.summary_mode(proposed), lifecycle_hooks="on" if terminal_on else "off",
                    events=list(hook_state.required_events(proposed)) if install_hooks else [], routing_config=str(routing_path), hooks_file=str(hooks_path),
                    hook_support="operator_confirmed" if hooks_supported else "not_checked",
                    trust="review_required" if install_hooks else "unchanged",
                    message="Review hook definitions in Codex; this helper never grants trust or enables disabled platform hooks.")


from contextlib import nullcontext as _noop


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope", choices=("user", "project"), required=True)
    p.add_argument("--mode", choices=("on", "off"), required=True)
    p.add_argument("--project-root")
    p.add_argument("--codex-home", type=Path, default=store.codex_home())
    p.add_argument("--install-hooks", action="store_true")
    p.add_argument("--hooks-supported", action="store_true", help="Operator confirms the active Codex build lists all four main/SubAgent hook events; not a trust bypass.")
    p.add_argument("--summary", choices=hook_state.SUMMARY_MODES, help="Display only; does not disable collection. Omit to preserve an existing choice.")
    p.add_argument("--lifecycle-hooks", choices=("on", "off"), help="Optional advisory Interrupt/SessionEnd receipts; default off.")
    p.add_argument("--lifecycle-hooks-supported", action="store_true", help="Operator confirms both advisory events on the active local Host; not automatic detection or trust.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        path = _routing_path(args.scope, args.codex_home.expanduser().resolve(), args.project_root)
        result = configure(path, args.mode, install_hooks=args.install_hooks, hooks_supported=args.hooks_supported,
                           dry_run=args.dry_run, project_root=args.project_root if args.scope == "project" else None,
                           summary=args.summary, lifecycle_hooks=args.lifecycle_hooks,
                           lifecycle_hooks_supported=args.lifecycle_hooks_supported)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, KeyError):
        print("ERROR: token accounting configuration failed; inspect existing routing/hooks config. Nothing is auto-trusted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
