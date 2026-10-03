"""Native plugin layout and single-owner checks; importing this module is read-only."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

import outcome_store as store
import runtime_support as runtime
import configure_token_accounting as tokens

PLUGIN_NAME = "agent-router"
CORE_NAME = "codex-luna-subagent-router"
OWNER_FILE = "distribution.json"
PLUGIN_MANIFEST = "PLUGIN-MANIFEST.json"


def plugin_root(core=runtime.ROOT):
    core = Path(core).resolve()
    candidate = core.parent.parent
    if core.parent.name == "core" and (candidate / ".codex-plugin/plugin.json").is_file():
        return candidate
    return None


def scope_home(project=None):
    if project is not None:
        project = Path(project).expanduser().resolve()
        if not project.is_dir():
            raise ValueError("project root must exist")
        return project / ".codex"
    return store.codex_home().expanduser().resolve()


def owner_path(project=None):
    return scope_home(project) / CORE_NAME / OWNER_FILE


def read_owner(project=None):
    path = owner_path(project)
    if path.exists() and path.stat().st_size > 32 * 1024:
        raise ValueError("distribution metadata exceeds budget")
    value = tokens.read_json(path)
    if value:
        if value.get("schema_version") != 1 or value.get("active_source") not in ("plugin", "disabled"):
            raise ValueError("invalid distribution owner")
        if not re.fullmatch(r"[0-9a-f]{32}", str(value.get("transaction_id", ""))):
            raise ValueError("invalid distribution transaction")
        if not isinstance(value.get("plugin_root"), str) or not Path(value["plugin_root"]).is_absolute():
            raise ValueError("invalid plugin owner path")
        expected = str(Path(project).expanduser().resolve()) if project else None
        if value.get("project_root") != expected:
            raise ValueError("distribution scope mismatch")
    return value


def effective_owner(project=None):
    if project:
        value = read_owner(project)
        if value:
            return value, Path(project).expanduser().resolve()
    return read_owner(), None


def current_project():
    # Explicit non-Git projects retain their own distribution owner.
    for candidate in (Path.cwd(), *Path.cwd().parents):
        path = candidate / ".codex" / CORE_NAME / OWNER_FILE
        if path.exists():
            read_owner(candidate)
            return candidate.resolve()
    return store.resolve_scope()[1]


def inventory(root):
    """Hash every plugin file, including the Core manifest; reject escaping links."""
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel == PLUGIN_MANIFEST or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            if not path.exists() or not path.resolve().is_relative_to(root):
                raise ValueError("unsafe plugin link")
            result[rel] = {"link": os.readlink(path)}
        elif path.is_file():
            result[rel] = {"sha256": runtime.file_digest(path)}
        elif not path.is_dir():
            raise ValueError("plugin special file is not allowed")
    return result


def verify_plugin(root):
    root = Path(root).expanduser().resolve()
    core = root / "core" / CORE_NAME
    meta = tokens.read_json(root / ".codex-plugin/plugin.json")
    if meta.get("name") != PLUGIN_NAME or meta.get("skills") != "./skills/" or meta.get("hooks") != "./hooks/hooks.json":
        raise ValueError("unexpected plugin identity or component paths")
    if meta.get("version") != runtime.skill_version(core):
        raise ValueError("plugin/Core version mismatch")
    if not (root / "skills" / CORE_NAME / "SKILL.md").is_file():
        raise ValueError("plugin wrapper Skill is missing")
    manifest = tokens.read_json(root / PLUGIN_MANIFEST)
    if manifest.get("schema_version") != 1 or manifest.get("version") != meta["version"] or not isinstance(manifest.get("files"), dict):
        raise ValueError("invalid plugin integrity manifest")
    for rel in manifest["files"]:
        p = PurePosixPath(rel)
        if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel or ":" in rel:
            raise ValueError("unsafe plugin manifest path")
    if inventory(root) != manifest["files"]:
        raise ValueError("plugin integrity mismatch; do not index the installed plugin directory")
    files = runtime.verify_package(core)
    definitions = tokens.read_json(root / "hooks/hooks.json").get("hooks")
    if not isinstance(definitions, dict) or set(definitions) != set(tokens.EVENTS):
        raise ValueError("plugin must declare exactly the four Router lifecycle events")
    return {"status": "ok", "version": meta["version"], "plugin": PLUGIN_NAME,
            "plugin_files": len(manifest["files"]), "core_files": files,
            "package_sha256": runtime.file_digest(root / PLUGIN_MANIFEST),
            "host_loaded": "unverified", "hook_trust": "review_required"}


def owned_hook_count(value):
    """Inspect nested inline/JSON hook definitions without retaining command bodies."""
    if isinstance(value, dict):
        return int(value.get("statusMessage", value.get("status_message")) == tokens.OWNER) + sum(
            owned_hook_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(owned_hook_count(v) for v in value)
    return 0


def hook_sources(project=None):
    result = []
    bases = [scope_home()]
    if project and scope_home(project) not in bases:
        bases.append(scope_home(project))
    for base in bases:
        json_path = base / "hooks.json"
        data = tokens.read_json(json_path)
        count = owned_hook_count(data)
        if count:
            result.append({"path": str(json_path), "kind": "json", "owned": count})
        config = base / "config.toml"
        store.safe_path(config)
        data = tomllib.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        count = owned_hook_count(data.get("hooks", {}))
        if count:
            result.append({"path": str(config), "kind": "inline", "owned": count})
    return result


def owner_matches(root, project=None):
    owner, selected_project = effective_owner(project)
    if not owner or owner.get("active_source") != "plugin" or Path(owner["plugin_root"]).resolve() != Path(root).resolve():
        return False, owner, selected_project
    path = Path(root) / PLUGIN_MANIFEST
    return path.is_file() and runtime.file_digest(path) == owner.get("package_sha256"), owner, selected_project
