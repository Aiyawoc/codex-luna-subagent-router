#!/usr/bin/env python3
"""Safely configure verified-outcome calibration in an existing routing.json."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

MODES = ("off", "conservative")


class ConfigurationError(ValueError):
    pass


def _default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _routing_path(scope: str, codex_home: Path, project_root: str | None) -> Path:
    if scope == "user":
        return codex_home / "codex-luna-subagent-router" / "routing.json"
    if not project_root:
        raise ConfigurationError("--project-root is required for project scope")
    project = Path(project_root).expanduser().resolve()
    if not project.is_dir():
        raise ConfigurationError(f"project root is not an existing directory: {project}")
    return project / ".codex" / "codex-luna-subagent-router" / "routing.json"


def _read_routing(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ConfigurationError(f"refusing to modify a symbolic-link routing config: {path}")
    if not path.is_file():
        raise ConfigurationError(f"routing config does not exist: {path}; run guided routing setup first")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"routing config is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("routing config root must be an object")
    if value.get("schema_version") != "2.0":
        raise ConfigurationError("evidence calibration helper supports routing schema 2.0 only")
    if value.get("routing_mode") not in {"luna_only", "adaptive"}:
        raise ConfigurationError("routing config has an unsupported routing_mode")
    return value


def _write_atomic(path: Path, text: str) -> None:
    previous_mode = stat.S_IMODE(path.stat().st_mode)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, previous_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(path: Path, mode: str, *, dry_run: bool = False) -> dict[str, Any]:
    if mode not in MODES:
        raise ConfigurationError(f"mode must be one of: {', '.join(MODES)}")
    data = _read_routing(path)
    if mode == "conservative" and data["routing_mode"] != "adaptive":
        raise ConfigurationError("conservative evidence calibration is available only in adaptive mode")
    current = data.get("evidence_calibration", "off")
    if current not in MODES:
        raise ConfigurationError("existing evidence_calibration is unknown; review it manually")
    if current == mode and "evidence_calibration" in data:
        return {"action": "unchanged", "path": str(path), "mode": mode}
    data["evidence_calibration"] = mode
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not dry_run:
        _write_atomic(path, rendered)
    return {"action": "updated" if not dry_run else "would_update", "path": str(path), "mode": mode}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--codex-home", type=Path, default=_default_codex_home())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        path = _routing_path(args.scope, args.codex_home.expanduser().resolve(), args.project_root)
        result = configure(path, args.mode, dry_run=args.dry_run)
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"OK: {result['action']} evidence calibration -> {result['mode']} at {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
