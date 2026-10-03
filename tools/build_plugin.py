#!/usr/bin/env python3
"""Build a local-marketplace plugin from the exact verified complete package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "skills/codex-luna-subagent-router"
sys.path.insert(0, str(CORE / "scripts"))
import plugin_support as ps
import runtime_support as runtime

TARGETS = ("windows-x64", "windows-arm64", "macos-x64", "macos-arm64")


def extract(archive, destination):
    """Bound archive expansion and reject path traversal/special ZIP entries."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > 10000 or sum(m.file_size for m in members) > 1024**3:
                raise ValueError("archive exceeds extraction budget")
            for m in members:
                p = PurePosixPath(m.filename)
                mode = m.external_attr >> 16
                if p.is_absolute() or ".." in p.parts or "\\" in m.filename or ":" in m.filename or stat.S_ISLNK(mode):
                    raise ValueError("unsafe ZIP entry")
            z.extractall(destination)
    else:
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if len(members) > 10000 or sum(m.size for m in members) > 1024**3:
                raise ValueError("archive exceeds extraction budget")
            t.extractall(destination, filter="data")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def hook_definitions():
    unix = '"${PLUGIN_ROOT}/core/codex-luna-subagent-router/runtime/python/bin/python3" -I -S -B -X utf8 "${PLUGIN_ROOT}/core/codex-luna-subagent-router/scripts/runtime_dispatch.py" plugin_hook'
    windows = '"%PLUGIN_ROOT%/core/codex-luna-subagent-router/runtime/python/python.exe" -I -S -B -X utf8 "%PLUGIN_ROOT%/core/codex-luna-subagent-router/scripts/runtime_dispatch.py" plugin_hook'
    handler = dict(type="command", command=unix, commandWindows=windows,
                   timeout=5, statusMessage="agent-router:plugin-accounting")
    return {"hooks": {event: [{"hooks": [dict(handler)]}] for event in ps.tokens.EVENTS}}


def assemble(core, destination, template=REPO / "plugin"):
    runtime.verify_package(core)
    version = runtime.skill_version(core)
    plugin = destination / "plugins" / ps.PLUGIN_NAME
    shutil.copytree(core, plugin / "core" / ps.CORE_NAME, symlinks=True)
    shutil.copytree(template / "skills", plugin / "skills")
    manifest = json.loads((template / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    write_json(plugin / ".codex-plugin/plugin.json", manifest)
    write_json(plugin / "hooks/hooks.json", hook_definitions())
    write_json(plugin / ps.PLUGIN_MANIFEST, {"schema_version": 1, "version": version, "files": ps.inventory(plugin)})
    write_json(destination / ".agents/plugins/marketplace.json", {
        "name": "agent-router-local", "interface": {"displayName": "Agent Router Local"},
        "plugins": [{"name": ps.PLUGIN_NAME, "source": {"source": "local", "path": "./plugins/agent-router"},
                     "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}],
    })
    (destination / "README.md").write_text(
        "# Agent Router local marketplace\n\n"
        "Verify the Release SHA256 before extracting. Register this extracted marketplace root with the native Host, "
        "for example `codex plugin marketplace add /absolute/path/to/agent-router-marketplace` where supported. "
        "Install Agent Router from the Host Plugins Directory and locate its actual installed/cache root. "
        "Do not mistake this source folder for a confirmed active Host install.\n\n"
        "Then follow `plugins/agent-router/core/codex-luna-subagent-router/references/plugin-install.md`. "
        "The plugin defaults to inactive ownership. Installing it grants neither routing permission nor hook trust. "
        "Keep all turns/Workers stopped during migration, review setup and trust normally, and reopen a session. "
        "Canonical config/ledgers stay at existing CODEX_HOME locations. No scripts download Python at runtime.\n",
        encoding="utf-8",
    )
    ps.verify_plugin(plugin)
    return plugin


def build(target, portable_dist=Path("dist"), output=Path("dist-plugin")):
    if target not in TARGETS:
        raise ValueError("unsupported plugin platform")
    version = runtime.skill_version(CORE)
    ext = ".zip" if target.startswith("windows-") else ".tar.gz"
    archive = portable_dist / f"router-{version}-{target}{ext}"
    check = archive.with_name(archive.name + ".sha256").read_text().strip().split("  ", 1)
    if check != [runtime.file_digest(archive), archive.name]:
        raise ValueError("complete package checksum mismatch")
    output.mkdir(parents=True, exist_ok=True)
    result = output / f"router-plugin-{version}-{target}{ext}"
    with tempfile.TemporaryDirectory(prefix="router-plugin-build-") as tmp:
        base = Path(tmp)
        extract(archive, base / "portable")
        core = base / "portable" / ps.CORE_NAME
        meta = json.loads((core / "runtime/runtime.json").read_text())
        if meta.get("target") != target or runtime.skill_version(core) != version:
            raise ValueError("complete package target/version mismatch")
        market = base / "agent-router-marketplace"
        assemble(core, market)
        if ext == ".zip":
            with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for path in sorted(market.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("Windows plugin archive cannot contain symlinks")
                    if path.is_file():
                        z.write(path, path.relative_to(base))
        else:
            with tarfile.open(result, "w:gz", compresslevel=9) as t:
                t.add(market, arcname=market.name)
    digest = runtime.file_digest(result)
    result.with_name(result.name + ".sha256").write_text(digest + "  " + result.name + "\n")
    print(json.dumps(dict(target=target, archive=str(result), sha256=digest,
                          distribution="local-marketplace", host_activation="unverified"), indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=TARGETS, required=True)
    p.add_argument("--portable-dist", type=Path, default=Path("dist"))
    p.add_argument("--output", type=Path, default=Path("dist-plugin"))
    a = p.parse_args()
    build(a.target, a.portable_dist, a.output)
