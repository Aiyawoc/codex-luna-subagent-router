"""Explicit plugin ownership migration. Never edit ledgers, trust or Host enablement."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import install_bundle
import plugin_support as ps
import runtime_support as runtime
import configure_token_accounting as tokens
import outcome_store as store


def _bytes(path):
    store.safe_path(path)
    return path.read_bytes() if path.exists() else None


def _hash(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _json(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write(path, data):
    if data is None:
        store.safe_path(path).unlink(missing_ok=True)
    else:
        tokens.atomic_bytes(path, data)


def _locations(project, core):
    destination, agents = install_bundle.destinations(project)
    state = ps.read_owner(project)
    if state:
        # Once the legacy directory is moved, auto-discovery would prefer the
        # modern default. Keep its original supported location for upgrades and
        # rollback, without allowing arbitrary journal-controlled destinations.
        path = _journal_path(project, state["transaction_id"])
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("migration journal exceeds budget")
        saved = tokens.read_json(path).get("legacy_destination")
        if not isinstance(saved, str):
            raise ValueError("migration destination is missing")
        if project:
            allowed = [Path(project).resolve() / ".agents/skills" / ps.CORE_NAME]
        elif os.environ.get("CODEX_SKILLS_DIR"):
            allowed = [Path(os.environ["CODEX_SKILLS_DIR"]).expanduser().resolve() / ps.CORE_NAME]
        else:
            allowed = [Path.home().resolve() / ".agents/skills" / ps.CORE_NAME,
                       ps.scope_home() / "skills" / ps.CORE_NAME]
        if Path(saved) not in allowed:
            raise ValueError("migration target no longer matches supported installation locations")
        destination = Path(saved)
    destination, agents = destination.resolve(), agents.resolve()
    store.safe_path(destination / "VERSION")
    store.safe_path(agents / "profile-safety-check")
    profiles = sorted((core / "assets/codex-agents").glob("*.toml"))
    if not profiles:
        raise ValueError("plugin Core has no profiles")
    files = {"hooks": ps.scope_home(project) / "hooks.json"}
    files.update({"profile/" + p.name: agents / p.name for p in profiles})
    return destination, agents, files, profiles


def _journal_path(project, txid):
    return ps.owner_path(project).parent / "plugin-backups" / txid / "transaction.json"


def _load_journal(project, state, destination, agents):
    path = _journal_path(project, state["transaction_id"])
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("migration journal exceeds budget")
    journal = tokens.read_json(path)
    if (journal.get("schema_version") != 1 or journal.get("legacy_destination") != str(destination)
            or journal.get("agents_dir") != str(agents) or not isinstance(journal.get("files"), dict)):
        raise ValueError("migration targets changed; do not guess rollback paths")
    return journal


def inspect(root=None, project=None, verify=False):
    root = Path(root).expanduser().resolve() if root else ps.plugin_root()
    state, owner_project = ps.effective_owner(project)
    destination, agents = install_bundle.destinations(project)
    matched = ps.owner_matches(root, project)[0] if root else False
    conflicts = ps.hook_sources(project)
    # A legacy Skill is a second instruction source even if its hooks are off.
    if destination.exists():
        conflicts.append({"path": str(destination), "kind": "legacy_skill", "owned": 1})
    if project:
        global_destination, _ = install_bundle.destinations()
        if global_destination.exists() and global_destination != destination:
            conflicts.append({"path": str(global_destination), "kind": "legacy_skill", "owned": 1})
    proof = ps.verify_plugin(root) if verify and root else None
    return dict(plugin_root=str(root) if root else None, registered_owner=state or None,
                owner_matches=matched, active=matched and not conflicts,
                legacy_install=str(destination) if destination.exists() else None,
                profiles_dir=str(agents), conflicts=conflicts, integrity=proof,
                project_root=str(owner_project) if owner_project else None,
                read_only=True, host_loaded="unverified", hook_trust="review_required",
                instruction="Activate only after native installation and setup review; restart the Host. Do not index the installed package.")


def activate(root, *, project=None, install_mode=None, confirm=False,
             host_installed_reviewed=False, setup_reviewed=False, quiescent=False):
    if not all(v is True for v in (confirm, host_installed_reviewed, setup_reviewed, quiescent)):
        raise ValueError("activation needs explicit confirmation, native-install/setup review and a quiescent Host")
    if install_mode not in ("upgrade", "fresh"):
        raise ValueError("choose --install-mode upgrade or fresh before migration")
    root = Path(root).expanduser().resolve()
    proof = ps.verify_plugin(root)
    core = root / "core" / ps.CORE_NAME
    destination, agents, files, profiles = _locations(project, core)
    owner_path = ps.owner_path(project)
    if (root.is_relative_to(destination) or destination.is_relative_to(root)
            or any(p.resolve().is_relative_to(root) for p in [owner_path, *files.values()])):
        raise ValueError("plugin, legacy installation and mutable state must not contain each other")
    with store.locked(owner_path):
        state = ps.read_owner(project)
        if install_mode == "upgrade" and not state and not destination.exists():
            raise ValueError("upgrade requires a previous plugin or complete-package installation")
        sources = ps.hook_sources(project)
        selected_hooks = str(files["hooks"])
        if any(s["kind"] == "inline" or s["path"] != selected_hooks for s in sources):
            raise ValueError("Router hooks exist in another/inline layer; review those sources before migration")
        if project:
            global_destination, _ = install_bundle.destinations()
            if global_destination.exists():
                raise ValueError("global legacy Skill conflicts with project plugin; migrate the global source explicitly first")
        if state and ps.owner_matches(root, project)[0] and not sources and not destination.exists():
            return dict(status="unchanged", version=proof["version"], hook_trust="review_required")

        state_before = _bytes(owner_path)
        txid = state["transaction_id"] if state else uuid.uuid4().hex
        journal_path = _journal_path(project, txid)
        journal = _load_journal(project, state, destination, agents) if state else {
            "schema_version": 1, "legacy_destination": str(destination), "agents_dir": str(agents),
            "legacy_moved": False, "files": {},
        }
        if any(key not in files for key in journal["files"]):
            raise ValueError("managed file set changed; review migration instead of dropping backup entries")
        before = {key: _bytes(path) for key, path in files.items()}
        if state and any(_hash(before[key]) != value["after_sha256"] for key, value in journal["files"].items()):
            raise ValueError("managed files changed since activation; review before upgrade")
        desired = {"hooks": _json(tokens.merge_hooks(tokens.read_json(files["hooks"]))) }
        if desired["hooks"] == _json(tokens.read_json(files["hooks"])):
            desired["hooks"] = before["hooks"]
        desired.update({"profile/" + p.name: p.read_bytes() for p in profiles})
        backup = destination.with_name("." + ps.CORE_NAME + ".plugin-backup-" + txid)
        moved = False
        if destination.exists():
            if state:
                raise ValueError("legacy install reappeared while plugin owns the scope; review conflict")
            runtime.verify_package(destination)
            if backup.exists() or backup.is_symlink():
                raise ValueError("legacy backup destination already exists")
        for key, data in desired.items():
            original = journal["files"].get(key, {}).get("before")
            if key not in journal["files"]:
                original = base64.b64encode(before[key]).decode("ascii") if before[key] is not None else None
            journal["files"][key] = {"before": original, "after_sha256": _hash(data)}
        journal["legacy_moved"] = journal["legacy_moved"] or destination.exists()
        old_journal = _bytes(journal_path)
        # The backup is durable before the first mutation. No ledger is part of this transaction.
        tokens.atomic_bytes(journal_path, _json(journal))
        applied = []
        try:
            if destination.exists():
                os.replace(destination, backup)
                moved = True
            for key, data in desired.items():
                if data != before[key]:
                    _write(files[key], data)
                    applied.append(key)
            state = dict(schema_version=1, active_source="plugin", plugin_root=str(root),
                         version=proof["version"], package_sha256=proof["package_sha256"],
                         transaction_id=txid, project_root=str(Path(project).resolve()) if project else None)
            tokens.atomic_bytes(owner_path, _json(state))
        except Exception:
            for key in reversed(applied):
                _write(files[key], before[key])
            if moved:
                os.replace(backup, destination)
            _write(owner_path, state_before)
            _write(journal_path, old_journal)
            raise
        return dict(status="activated", version=proof["version"], install_mode=install_mode,
                    migration_backup=str(journal_path.parent), hook_trust="review_required",
                    restart_required=True, user_choices_and_ledgers="unchanged",
                    note="Native enablement and trust must be reviewed in the Host; no trust database was changed.")


def deactivate(project=None, *, confirm=False, quiescent=False):
    if confirm is not True or quiescent is not True:
        raise ValueError("deactivation needs confirmation and quiescent Host")
    with store.locked(ps.owner_path(project)):
        state = ps.read_owner(project)
        if not state:
            return {"status": "unchanged"}
        state["active_source"] = "disabled"
        tokens.atomic_bytes(ps.owner_path(project), _json(state))
    return dict(status="disabled", ledgers="unchanged", next="Disable the native plugin in the Host; rollback can restore the old complete package.")


def rollback(project=None, *, confirm=False, quiescent=False, host_disabled_reviewed=False):
    if not all(v is True for v in (confirm, quiescent, host_disabled_reviewed)):
        raise ValueError("rollback needs confirmation, quiescence and native plugin disabled review")
    owner_path = ps.owner_path(project)
    with store.locked(owner_path):
        state = ps.read_owner(project)
        if not state:
            raise ValueError("no plugin migration to roll back")
        core = Path(state["plugin_root"]) / "core" / ps.CORE_NAME
        # Installed Core may have been removed by the Host; use this helper's same-source profiles.
        if not core.is_dir():
            core = runtime.ROOT
        destination, agents, files, _ = _locations(project, core)
        journal = _load_journal(project, state, destination, agents)
        if any(key not in files for key in journal["files"]):
            raise ValueError("unknown backup file; refusing rollback")
        before = {key: _bytes(files[key]) for key in journal["files"]}
        if any(_hash(before[key]) != value["after_sha256"] for key, value in journal["files"].items()):
            raise ValueError("managed files changed after migration; rollback would overwrite changes")
        backup = destination.with_name("." + ps.CORE_NAME + ".plugin-backup-" + state["transaction_id"])
        if journal["legacy_moved"]:
            if destination.exists() or destination.is_symlink():
                raise ValueError("legacy destination is occupied; refusing overwrite")
            store.safe_path(backup / "VERSION")
            runtime.verify_package(backup)
        originals = {key: base64.b64decode(value["before"], validate=True) if value["before"] is not None else None
                     for key, value in journal["files"].items()}
        state_before = _bytes(owner_path)
        inactive = dict(state, active_source="disabled")
        tokens.atomic_bytes(owner_path, _json(inactive))
        applied, restored_package = [], False
        try:
            for key, data in originals.items():
                if data != before[key]:
                    _write(files[key], data)
                    applied.append(key)
            if journal["legacy_moved"]:
                os.replace(backup, destination)
                restored_package = True
            owner_path.unlink()
        except Exception:
            if restored_package:
                os.replace(destination, backup)
            for key in reversed(applied):
                _write(files[key], before[key])
            _write(owner_path, state_before)
            raise
        return dict(status="rolled_back", restored_complete_package=journal["legacy_moved"],
                    backups="retained", ledgers="unchanged", restart_required=True,
                    hook_trust="review_restored_definitions_in_host")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "activate", "deactivate", "rollback"):
        p = sub.add_parser(name)
        scope = p.add_mutually_exclusive_group()
        scope.add_argument("--project-root", type=Path)
        scope.add_argument("--global-scope", action="store_true")
        if name == "inspect":
            scope.add_argument("--current-scope", action="store_true")
            p.add_argument("--verify", action="store_true")
        else:
            p.add_argument("--confirm", action="store_true")
            p.add_argument("--quiescent", action="store_true", help="Operator has ended active turns/Workers before switching sources.")
        if name in ("inspect", "activate"):
            p.add_argument("--plugin-root", type=Path)
        if name == "activate":
            p.add_argument("--install-mode", choices=("upgrade", "fresh"), required=True)
            p.add_argument("--host-installed-reviewed", action="store_true")
            p.add_argument("--setup-reviewed", action="store_true")
        if name == "rollback":
            p.add_argument("--host-disabled-reviewed", action="store_true")
        p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    project = args.project_root
    if getattr(args, "current_scope", False):
        project = ps.current_project()
    if args.command == "inspect":
        result = inspect(args.plugin_root, project, args.verify)
    elif args.command == "activate":
        root = args.plugin_root or ps.plugin_root()
        if root is None:
            raise ValueError("run the installed plugin helper or pass its exact --plugin-root")
        result = activate(root, project=project, install_mode=args.install_mode, confirm=args.confirm,
                          host_installed_reviewed=args.host_installed_reviewed,
                          setup_reviewed=args.setup_reviewed, quiescent=args.quiescent)
    elif args.command == "deactivate":
        result = deactivate(project, confirm=args.confirm, quiescent=args.quiescent)
    else:
        result = rollback(project, confirm=args.confirm, quiescent=args.quiescent,
                          host_disabled_reviewed=args.host_disabled_reviewed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("ERROR: plugin operation stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
