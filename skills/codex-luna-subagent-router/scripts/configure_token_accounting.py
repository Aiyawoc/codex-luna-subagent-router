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
from configure_evidence_calibration import _routing_path, ConfigurationError

OWNER = "codex-luna-subagent-router:token-accounting"
VERSION = "2.5.4"
EVENTS = ("UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop")


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


def hook_handler(script, python=None, project_root=None):
    python = str(python or sys.executable)
    script = str(Path(script).absolute())
    if any(c in python + script for c in "\r\n\x00"):
        raise ConfigurationError("invalid command path")
    root_args = ["--project-root", str(Path(project_root).resolve())] if project_root else []
    args = [python, script, *root_args, "--hook-version", VERSION, "hook"]
    if os.name == "nt":
        # cmd-style command line, for Codex's Windows command override.
        # Reject metacharacters instead of pretending to escape arbitrary shell code.
        if any(c in " ".join(args) for c in '&|<>^%!?`$"'):
            raise ConfigurationError("Windows command path contains shell metacharacters")
        command = subprocess.list2cmdline(args)
        return dict(type="command", command=command, commandWindows=command, timeout=5, statusMessage=OWNER)
    return dict(type="command", command=shlex.join(args), timeout=5, statusMessage=OWNER)


def merge_hooks(existing, handler=None):
    merged = copy.deepcopy(existing)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigurationError("hooks must be an object")
    for event in EVENTS:
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
        if handler:
            cleaned.append({**({"matcher": ".*"} if event.startswith("Subagent") else {}), "hooks": [copy.deepcopy(handler)]})
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


def configure(routing_path, mode, *, install_hooks=False, hooks_supported=False, script=None, dry_run=False, project_root=None):
    if mode not in ("on", "off"):
        raise ConfigurationError("token_accounting must be on or off")
    if install_hooks and (mode != "on" or not hooks_supported):
        raise ConfigurationError("confirm UserPromptSubmit/Stop/SubagentStart/SubagentStop support before --install-hooks")
    routing_path = Path(routing_path)
    hooks_path = routing_path.parent.parent / "hooks.json"
    # Hold one config transaction lock to serialize this helper; never alter trust storage.
    with store.locked(routing_path, timeout=0.4) if not dry_run else _noop():
        data = read_json(routing_path)
        if data.get("schema_version") != "2.0" or data.get("routing_mode") not in ("adaptive", "luna_only"):
            raise ConfigurationError("run guided routing setup first")
        if data.get("token_accounting", "off") not in ("on", "off"):
            raise ConfigurationError("unknown existing token_accounting")
        # mode=on is an explicit answer to the combined question 6. Old on alone
        # does not authorize main-thread collection in the runtime handler.
        proposed = {**data, "token_accounting": mode,
                    "token_accounting_scope": "main_and_subagents",
                    "token_accounting_collection": "hooks" if install_hooks else "manual"}
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
                    if not isinstance(features, dict) or features.get("hooks", features.get("codex_hooks", True)) is False or config.get("allow_managed_hooks_only") is True:
                        raise ConfigurationError("platform hooks are disabled or restricted")
        # Explicit manual/off also removes obsolete owned handlers, never user hooks.
        existing = read_json(hooks_path)
        handler = None
        if install_hooks:
            target = Path(script or Path(__file__).with_name("token_usage.py")).absolute()
            if not target.is_file():
                raise ConfigurationError("installed token_usage.py is missing")
            handler = hook_handler(target, project_root=project_root)
        merged = merge_hooks(existing, handler)
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
                    mode=mode, accounting_scope="main_and_subagents", events=list(EVENTS) if install_hooks else [], routing_config=str(routing_path), hooks_file=str(hooks_path),
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
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        path = _routing_path(args.scope, args.codex_home.expanduser().resolve(), args.project_root)
        result = configure(path, args.mode, install_hooks=args.install_hooks, hooks_supported=args.hooks_supported, dry_run=args.dry_run, project_root=args.project_root if args.scope == "project" else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, KeyError):
        print("ERROR: token accounting configuration failed; inspect existing routing/hooks config. Nothing is auto-trusted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
