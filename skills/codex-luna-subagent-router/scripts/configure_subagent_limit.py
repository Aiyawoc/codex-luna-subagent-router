#!/usr/bin/env python3
"""Safely configure Codex spawned-agent concurrency without requiring codex-cli."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

KEY = "max_concurrent_threads_per_session"
LEGACY_KEY = "max_threads"
V2_TABLE = "features.multi_agent_v2"
SCHEMAS = ("auto", "canonical", "portable")
_TABLE_HEADER_RE = re.compile(r"^\s*(\[\[?)([^\]]+?)(\]\]?)(?:\s*#.*)?$")
_AGENT_DIRECT_RE = re.compile(
    r"^(\s*)(max_concurrent_threads_per_session|max_threads)(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_AGENT_DOTTED_RE = re.compile(
    r"^(\s*)agents\.(max_concurrent_threads_per_session|max_threads)(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_V2_DIRECT_RE = re.compile(
    r"^(\s*)max_concurrent_threads_per_session(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_V2_DOTTED_RE = re.compile(
    r"^(\s*)features\.multi_agent_v2\.max_concurrent_threads_per_session(\s*=\s*)([+-]?\d+)(\s*(?:#.*)?)(\r?\n?)$"
)
_ROOT_AGENTS_ASSIGNMENT_RE = re.compile(r"^\s*agents\s*=")
_ROOT_FEATURES_ASSIGNMENT_RE = re.compile(r"^\s*features\s*=")


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


def _positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(f"{label} must be an integer >= 1")
    return value


def analyze_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return effective SubAgent cap and schema diagnostics for one config layer.

    Public/new Codex uses agents.max_concurrent_threads_per_session = N where N
    excludes the primary. Older V2 builds use
    features.multi_agent_v2.max_concurrent_threads_per_session = N + 1 because
    that internal setting includes the primary. A portable config stores both
    legacy agents.max_threads = N and the older V2 value N + 1, which is
    accepted by the known 0.142.1 and 0.154.0 schemas.
    """
    if not isinstance(config, Mapping):
        raise ConfigurationError("config root must be a TOML table")
    agents = config.get("agents", {})
    if agents is None:
        agents = {}
    if not isinstance(agents, Mapping):
        raise ConfigurationError("agents must be a config table")
    features = config.get("features", {})
    if features is None:
        features = {}
    if not isinstance(features, Mapping):
        raise ConfigurationError("features must be a config table")
    multi = features.get("multi_agent_v2", {})
    if multi is None:
        multi = {}
    if not isinstance(multi, Mapping):
        raise ConfigurationError("features.multi_agent_v2 must be a config table")

    canonical = _positive_int(agents.get(KEY), f"agents.{KEY}")
    legacy = _positive_int(agents.get(LEGACY_KEY), f"agents.{LEGACY_KEY}")
    legacy_v2 = _positive_int(multi.get(KEY), f"{V2_TABLE}.{KEY}")
    if canonical is not None and legacy is not None:
        raise ConfigurationError(
            f"config contains both agents.{KEY} and alias agents.{LEGACY_KEY}; remove the ambiguity"
        )

    agent_value = canonical if canonical is not None else legacy
    if legacy_v2 is not None and legacy_v2 < 2:
        raise ConfigurationError(
            f"{V2_TABLE}.{KEY} must be >= 2 to allow at least one SubAgent when the primary is included"
        )
    v2_effective = legacy_v2 - 1 if legacy_v2 is not None else None
    if agent_value is not None and v2_effective is not None and agent_value != v2_effective:
        raise ConfigurationError(
            "conflicting SubAgent caps: agents value excludes the primary, while "
            f"{V2_TABLE}.{KEY} includes it"
        )

    if canonical is not None and legacy_v2 is None:
        schema = "canonical"
        effective = canonical
        portable = False
        backend_safe = True
    elif legacy is not None and legacy_v2 is not None:
        schema = "portable"
        effective = legacy
        portable = True
        backend_safe = True
    elif canonical is not None and legacy_v2 is not None:
        schema = "canonical_with_v2_override"
        effective = canonical
        portable = False
        backend_safe = True
    elif legacy_v2 is not None:
        schema = "legacy_v2_only"
        effective = v2_effective
        portable = False
        backend_safe = bool(multi.get("enabled") is True)
    elif legacy is not None:
        schema = "legacy_v1_or_alias_only"
        effective = legacy
        portable = False
        backend_safe = bool(multi.get("enabled") is False)
    else:
        schema = "unset"
        effective = None
        portable = False
        backend_safe = False

    return {
        "schema": schema,
        "effective_subagent_limit": effective,
        "canonical_value": canonical,
        "legacy_agent_value": legacy,
        "legacy_v2_value_including_primary": legacy_v2,
        "portable_across_known_0142_0154": portable,
        "backend_safe_without_host_probe": backend_safe,
    }


def effective_subagent_limit(config: Mapping[str, Any], *, allow_backend_ambiguous: bool = True) -> int | None:
    info = analyze_config(config)
    if not allow_backend_ambiguous and not info["backend_safe_without_host_probe"]:
        return None
    return info["effective_subagent_limit"]


def _load_toml(existing: str) -> dict[str, Any]:
    if not existing or tomllib is None:
        return {}
    try:
        return tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"config.toml is not valid TOML: {exc}") from exc


def _parse(existing: str) -> dict[str, Any]:
    data = _load_toml(existing)
    analyze_config(data)
    return data


def _scan(existing: str) -> tuple[list[str], dict[str, int | None], list[tuple[str, int, re.Match[str]]]]:
    """Locate editable agent/V2 assignments while rejecting ambiguous table shapes."""
    lines = existing.splitlines(keepends=True)
    current_table: str | None = None
    headers: dict[str, int | None] = {"agents": None, V2_TABLE: None}
    first_nested: dict[str, int | None] = {"agents": None, "features": None}
    matches: list[tuple[str, int, re.Match[str]]] = []
    root_agents: list[int] = []
    root_features: list[int] = []

    for index, line in enumerate(lines):
        header = _table_header(line)
        if header is not None:
            kind, name = header
            if kind == "array" and (
                name == "agents"
                or name.startswith("agents.")
                or name == "features"
                or name.startswith("features.")
            ):
                raise ConfigurationError("config uses an array-of-tables where concurrency requires normal tables")
            if kind == "table":
                if name in headers:
                    if headers[name] is not None:
                        raise ConfigurationError(f"config.toml contains duplicate [{name}] tables")
                    headers[name] = index
                if name.startswith("agents.") and first_nested["agents"] is None:
                    first_nested["agents"] = index
                if name.startswith("features.") and first_nested["features"] is None:
                    first_nested["features"] = index
                current_table = name
            else:
                current_table = None
            continue

        if current_table == "agents":
            match = _AGENT_DIRECT_RE.match(line)
            if match:
                matches.append(("agents_direct", index, match))
        elif current_table == V2_TABLE:
            match = _V2_DIRECT_RE.match(line)
            if match:
                matches.append(("v2_direct", index, match))
        elif current_table is None:
            match = _AGENT_DOTTED_RE.match(line)
            if match:
                matches.append(("agents_dotted", index, match))
            match = _V2_DOTTED_RE.match(line)
            if match:
                matches.append(("v2_dotted", index, match))
            if _ROOT_AGENTS_ASSIGNMENT_RE.match(line):
                root_agents.append(index)
            if _ROOT_FEATURES_ASSIGNMENT_RE.match(line):
                root_features.append(index)

    if root_agents and headers["agents"] is None and not any(k.startswith("agents_") for k, _, _ in matches):
        raise ConfigurationError("config.toml defines agents as an inline/root value; review it manually")
    if root_features and headers[V2_TABLE] is None and not any(k.startswith("v2_") for k, _, _ in matches):
        # A normal inline [features] object can contain unrelated settings; only reject if it already
        # hides multi_agent_v2 from our text-safe editor.
        data = _load_toml(existing)
        if isinstance(data.get("features"), Mapping) and "multi_agent_v2" in data.get("features", {}):
            raise ConfigurationError("config.toml defines features.multi_agent_v2 in an inline value; review it manually")
    return lines, {**headers, **{f"first_{k}": v for k, v in first_nested.items()}}, matches


def _section_end(lines: list[str], header_index: int) -> int:
    for index in range(header_index + 1, len(lines)):
        if _table_header(lines[index]) is not None:
            return index
    return len(lines)


def _ensure_newline_before(lines: list[str], index: int) -> None:
    if index and not lines[index - 1].endswith(("\n", "\r")):
        lines[index - 1] += "\n"


def _set_agent_assignment(existing: str, key: str, value: int) -> tuple[str, str]:
    """Set one editable [agents] assignment, replacing the alias if necessary."""
    _load_toml(existing)
    lines, locations, matches = _scan(existing)
    agent_matches = [(kind, index, match) for kind, index, match in matches if kind.startswith("agents_")]
    if len(agent_matches) > 1:
        raise ConfigurationError("duplicate/ambiguous agents concurrency assignments")
    if agent_matches:
        kind, index, match = agent_matches[0]
        current_key = match.group(2)
        current_value = int(match.group(4))
        if current_key == key and current_value == value:
            return existing, "unchanged"
        prefix, assignment, suffix, newline = match.group(1), match.group(3), match.group(5), match.group(6)
        rendered = f"{prefix}{key}{assignment}{value}{suffix}{newline}"
        if kind == "agents_dotted":
            rendered = f"{prefix}agents.{key}{assignment}{value}{suffix}{newline}"
        lines[index] = rendered
        return "".join(lines), "migrated" if current_key != key else "updated"

    parsed = _load_toml(existing)
    agents = parsed.get("agents", {})
    if isinstance(agents, Mapping) and (KEY in agents or LEGACY_KEY in agents):
        raise ConfigurationError("SubAgent concurrency exists in an unmanaged inline agents value")
    header = locations["agents"]
    if header is not None:
        insertion = _section_end(lines, header)
        _ensure_newline_before(lines, insertion)
        lines.insert(insertion, f"{key} = {value}\n")
        return "".join(lines), "updated"
    nested = locations["first_agents"]
    if nested is not None:
        lines[nested:nested] = ["[agents]\n", f"{key} = {value}\n", "\n"]
        return "".join(lines), "created"
    separator = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
    spacing = "" if not existing or existing.endswith(("\n\n", "\r\n\r\n")) else "\n"
    return existing + separator + spacing + f"[agents]\n{key} = {value}\n", "created"


def _set_v2_assignment(existing: str, value: int) -> tuple[str, str]:
    _load_toml(existing)
    lines, locations, matches = _scan(existing)
    v2_matches = [(kind, index, match) for kind, index, match in matches if kind.startswith("v2_")]
    if len(v2_matches) > 1:
        raise ConfigurationError("duplicate/ambiguous legacy V2 concurrency assignments")
    if v2_matches:
        kind, index, match = v2_matches[0]
        current_value = int(match.group(3))
        if current_value == value:
            return existing, "unchanged"
        prefix, assignment, suffix, newline = match.group(1), match.group(2), match.group(4), match.group(5)
        rendered = f"{prefix}{KEY}{assignment}{value}{suffix}{newline}"
        if kind == "v2_dotted":
            rendered = f"{prefix}{V2_TABLE}.{KEY}{assignment}{value}{suffix}{newline}"
        lines[index] = rendered
        return "".join(lines), "updated"

    parsed = _load_toml(existing)
    multi = parsed.get("features", {}).get("multi_agent_v2", {}) if isinstance(parsed.get("features", {}), Mapping) else {}
    if isinstance(multi, Mapping) and KEY in multi:
        raise ConfigurationError("legacy V2 concurrency exists in an unmanaged inline value")
    header = locations[V2_TABLE]
    if header is not None:
        insertion = _section_end(lines, header)
        _ensure_newline_before(lines, insertion)
        lines.insert(insertion, f"{KEY} = {value}\n")
        return "".join(lines), "updated"
    separator = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
    spacing = "" if not existing or existing.endswith(("\n\n", "\r\n\r\n")) else "\n"
    return existing + separator + spacing + f"[{V2_TABLE}]\n{KEY} = {value}\n", "created"


def merge_subagent_limit(existing: str, max_subagents: int, *, schema: str = "canonical") -> tuple[str, str]:
    """Merge the limit using a selected schema.

    `canonical` writes the modern public [agents] key.
    `portable` writes fields accepted by known Codex 0.142.1 and 0.154.0:
    legacy agents.max_threads=N plus old V2 internal concurrency=N+1.
    `auto` preserves an existing canonical config; otherwise it upgrades to the
    portable representation so Desktop operation does not depend on an external CLI.
    """
    if isinstance(max_subagents, bool) or not isinstance(max_subagents, int) or max_subagents < 1:
        raise ConfigurationError("max_subagents must be an integer >= 1")
    if schema not in SCHEMAS:
        raise ConfigurationError(f"schema must be one of: {', '.join(SCHEMAS)}")
    parsed = _parse(existing)
    current = analyze_config(parsed)
    selected = schema
    if schema == "auto":
        selected = "canonical" if current["canonical_value"] is not None else "portable"

    if selected == "canonical":
        merged, action = _set_agent_assignment(existing, KEY, max_subagents)
        # Existing old-V2 overrides take precedence on V2. Keep them semantically aligned instead
        # of silently leaving a conflicting effective limit.
        raw_after_agent = _load_toml(merged)
        multi_after_agent = raw_after_agent.get("features", {}).get("multi_agent_v2", {})
        if isinstance(multi_after_agent, Mapping) and multi_after_agent.get(KEY) is not None:
            merged, v2_action = _set_v2_assignment(merged, max_subagents + 1)
            if v2_action != "unchanged":
                action = "updated_with_v2_compat"
        analyze_config(_parse(merged))
        return merged, action

    # Portable fallback: legacy V1/alias plus old V2 internal value. It does not require codex-cli
    # and keeps the same effective N across known 0.142.1 V1/V2 and 0.154.0 V1/V2 behavior.
    merged, agent_action = _set_agent_assignment(existing, LEGACY_KEY, max_subagents)
    merged, v2_action = _set_v2_assignment(merged, max_subagents + 1)
    analyze_config(_parse(merged))
    if agent_action == "unchanged" and v2_action == "unchanged":
        return merged, "unchanged"
    if "created" in (agent_action, v2_action):
        return merged, "created_portable"
    return merged, "updated_portable"


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


def configure_limit(*, codex_home: Path, max_subagents: int, dry_run: bool, schema: str = "auto") -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    existing = _read_optional_regular_file(config_path) or ""
    before = analyze_config(_parse(existing))
    merged, action = merge_subagent_limit(existing, max_subagents, schema=schema)
    after = analyze_config(_parse(merged))
    if after["effective_subagent_limit"] != max_subagents:
        raise ConfigurationError("merged config does not preserve the requested effective SubAgent limit")
    if not dry_run and merged != existing:
        _write_text_atomic(config_path, merged)
    return {
        "dry_run": dry_run,
        "max_subagents": max_subagents,
        "action": action,
        "path": str(config_path),
        "requested_schema": schema,
        "selected_schema": after["schema"],
        "before": before,
        "after": after,
        "primary_thread_excluded": True,
        "cli_required": False,
        "validation": "toml_and_effective_semantics",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-subagents",
        type=int,
        required=True,
        help="Maximum concurrently open spawned-agent threads, excluding the primary.",
    )
    parser.add_argument(
        "--schema",
        choices=SCHEMAS,
        default="auto",
        help=(
            "auto preserves canonical configs and otherwise uses a CLI-independent portable fallback; "
            "canonical should be selected only when the active Codex Host/Core is known to support it."
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
            schema=args.schema,
        )
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        prefix = "DRY RUN" if args.dry_run else "OK"
        print(
            f"{prefix}: effective SubAgent limit = {result['max_subagents']} -> {result['path']} "
            f"({result['selected_schema']}, {result['action']}; codex-cli not required)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
