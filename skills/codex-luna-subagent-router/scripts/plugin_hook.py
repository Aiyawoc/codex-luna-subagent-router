"""Native hook gate. Default inactive, never blocks Stop and never creates another ledger."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import plugin_support as ps
import outcome_store as store
import token_usage


def dispatch(payload):
    root = ps.plugin_root()
    if root is None or payload.get("hook_event_name") not in ps.tokens.EVENTS:
        return {}
    supplied = os.environ.get("PLUGIN_ROOT")
    if not supplied or Path(supplied).resolve() != root:
        return {"continue": True, "systemMessage": "Router plugin root mismatch; no collection performed."}
    cwd = Path(payload.get("cwd", ""))
    if not cwd.is_absolute() or not cwd.is_dir():
        return {}
    with __import__("contextlib").chdir(cwd):
        project = ps.current_project()
        matched, state, owner_project = ps.owner_matches(root, project)
        if not matched:
            return {}
        if ps.hook_sources(project):
            return {"continue": True, "systemMessage": "Router plugin detected another accounting hook source; plugin collection skipped. Review migration."}
        # A revived legacy installation is also a conflict, even with hooks disabled.
        import install_bundle
        for scope in (None, project) if project else (None,):
            legacy, _ = install_bundle.destinations(scope)
            if legacy.exists():
                return {"continue": True, "systemMessage": "Router plugin detected a legacy Skill installation; plugin collection skipped."}
        config = store.effective_config(project)
        if (config.get("token_accounting") != "on" or config.get("token_accounting_collection") != "hooks"
                or config.get("token_accounting_scope") != "main_and_subagents"):
            return {}
        return token_usage.hook(payload, project_root=owner_project)


def main():
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("hook input exceeds budget")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        result = dispatch(payload)
    except (ValueError, OSError, KeyError, TypeError):
        result = {"continue": True, "systemMessage": "Router plugin accounting unavailable; no inferred usage and no blocked Stop."}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
