#!/usr/bin/env python3
"""Safely configure Codex's public spawned-agent concurrency cap."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

KEY = "max_concurrent_threads_per_session"
LEGACY_KEY = "max_threads"
_TABLE_HEADER_RE = re.compile(r"^\s*(\[\[?)([^\]]+?)(\]\]?)(?:\s*#.*)?$")
_DIRECT_ASSIGNMENT_RE = re.compile(
    r"^(\s*)(max_concurrent_threads_per_session|max_threads)(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_DOTTED_ASSIGNMENT_RE = re.compile(
    r"^(\s*)agents\.(max_concurrent_threads_per_session|max_threads)(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_ROOT_AGENTS_ASSIGNMENT_RE = re.compile(r"^\s*agents\s*=")


class ConfigurationError(ValueError):
    """Raised when config.toml cannot be updated safely."""


def _default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _table_header(line: str) -> tuple[str, str] | None:
    content = line.rstrip("\r\n")
    match = _TABLE_HEADER_RE.match(content)
    if not match:
        return None
    opening, name, closing = match.groups()
    if opening == "[" and closing == "]":
        return "table", name.strip()
    if opening == "[[" and closing == "]]":
        return "array", name.strip()
    return None


def _parse_agents(existing: str) -> dict[str, Any]:
    if not existing or tomllib is None:
        return {}
    try:
        data = tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"config.toml is not valid TOML: {exc}") from exc
    agents = data.get("agents")
    if agents is None:
        return {}
    if not isinstance(agents, dict):
        raise ConfigurationError(
            "config.toml has a non-table agents value; review it manually before setting "
            f"agents.{KEY}"
        )
    for name in (KEY, LEGACY_KEY):
        value = agents.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ConfigurationError(f"config.toml agents.{name} must be an integer >= 1")
    if KEY in agents and LEGACY_KEY in agents:
        raise ConfigurationError(
            f"config.toml contains both agents.{KEY} and legacy agents.{LEGACY_KEY}; "
            "remove the ambiguity before continuing"
        )
    return agents


def merge_subagent_limit(existing: str, max_subagents: int) -> tuple[str, str]:
    if isinstance(max_subagents, bool) or not isinstance(max_subagents, int) or max_subagents < 1:
        raise ConfigurationError("max_subagents must be an integer >= 1")
    if not existing:
        return f"[agents]\n{KEY} = {max_subagents}\n", "created"

    parsed_agents = _parse_agents(existing)
    lines = existing.splitlines(keepends=True)
    current_table: str | None = None
    agents_header: int | None = None
    first_nested_agents_header: int | None = None
    agents_section_end = len(lines)
    matches: list[tuple[str, int, re.Match[str]]] = []
    root_agents_assignments: list[int] = []

    for index, line in enumerate(lines):
        header = _table_header(line)
        if header is not None:
            kind, name = header
            if kind == "array" and (name == "agents" or name.startswith("agents.")):
                raise ConfigurationError(
                    "config.toml uses an array-of-tables for agents; review it manually before "
                    f"setting agents.{KEY}"
                )
            if kind == "table" and name == "agents":
                if agents_header is not None:
                    raise ConfigurationError("config.toml contains duplicate [agents] tables")
                agents_header = index
            elif kind == "table" and name.startswith("agents."):
                if first_nested_agents_header is None:
                    first_nested_agents_header = index
            if agents_header is not None and index > agents_header and agents_section_end == len(lines):
                agents_section_end = index
            current_table = name if kind == "table" else None
            continue

        if current_table == "agents":
            match = _DIRECT_ASSIGNMENT_RE.match(line)
            if match:
                matches.append(("direct", index, match))
        elif current_table is None:
            match = _DOTTED_ASSIGNMENT_RE.match(line)
            if match:
                matches.append(("dotted", index, match))
            if _ROOT_AGENTS_ASSIGNMENT_RE.match(line):
                root_agents_assignments.append(index)

    if len(matches) > 1:
        raise ConfigurationError(
            f"config.toml contains duplicate/ambiguous agents.{KEY} or agents.{LEGACY_KEY} assignments"
        )

    if matches:
        kind, index, match = matches[0]
        existing_key = match.group(2)
        current_value = int(match.group(4))
        if existing_key == KEY and current_value == max_subagents:
            return existing, "unchanged"
        prefix = match.group(1)
        assignment = match.group(3)
        suffix = match.group(5)
        newline = match.group(6)
        if kind == "direct":
            lines[index] = f"{prefix}{KEY}{assignment}{max_subagents}{suffix}{newline}"
        else:
            lines[index] = f"{prefix}agents.{KEY}{assignment}{max_subagents}{suffix}{newline}"
        action = "migrated_legacy" if existing_key == LEGACY_KEY else "updated"
        return "".join(lines), action

    if KEY in parsed_agents or LEGACY_KEY in parsed_agents:
        raise ConfigurationError(
            "the SubAgent concurrency setting exists in an inline or otherwise unmanaged agents value; "
            "review config.toml manually before changing it"
        )
    if root_agents_assignments:
        raise ConfigurationError(
            "config.toml defines agents as a root value without an editable [agents] table; "
            f"review it manually before setting agents.{KEY}"
        )

    if agents_header is not None:
        insertion = agents_section_end
        if insertion and not lines[insertion - 1].endswith(("\n", "\r")):
            lines[insertion - 1] += "\n"
        lines.insert(insertion, f"{KEY} = {max_subagents}\n")
        return "".join(lines), "updated"

    if first_nested_agents_header is not None:
        lines[first_nested_agents_header:first_nested_agents_header] = [
            "[agents]\n",
            f"{KEY} = {max_subagents}\n",
            "\n",
        ]
        return "".join(lines), "created"

    separator = "" if existing.endswith(("\n", "\r")) else "\n"
    spacing = "" if existing.endswith(("\n\n", "\r\n\r\n")) else "\n"
    return existing + separator + spacing + f"[agents]\n{KEY} = {max_subagents}\n", "created"


def _read_optional_regular_file(path: Path) -> str | None:
    if path.is_symlink():
        raise ConfigurationError(f"refusing to replace a symbolic-link target: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ConfigurationError(f"target exists but is not a regular file: {path}")
    return path.read_text(encoding="utf-8")


def _write_text_atomic(path: Path, text: str) -> None:
    _read_optional_regular_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
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
        if temporary.exists():
            temporary.unlink()


def configure_limit(*, codex_home: Path, max_subagents: int, dry_run: bool) -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    existing = _read_optional_regular_file(config_path) or ""
    merged, action = merge_subagent_limit(existing, max_subagents)
    if not dry_run and merged != existing:
        _write_text_atomic(config_path, merged)
    return {
        "dry_run": dry_run,
        "max_subagents": max_subagents,
        "action": action,
        "path": str(config_path),
        "config_key": f"agents.{KEY}",
        "primary_thread_excluded": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-subagents",
        type=int,
        required=True,
        help=(
            "Maximum concurrently open spawned-agent threads, excluding the primary. "
            "OpenAI's public schema requires an integer >= 1 and currently documents no absolute maximum."
        ),
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=_default_codex_home(),
        help="Override CODEX_HOME (primarily for testing).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without writing files.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = configure_limit(
            codex_home=args.codex_home.expanduser().resolve(),
            max_subagents=args.max_subagents,
            dry_run=args.dry_run,
        )
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        prefix = "DRY RUN" if args.dry_run else "OK"
        print(f"{prefix}: {result['config_key']} = {result['max_subagents']} -> {result['path']} ({result['action']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
