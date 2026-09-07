#!/usr/bin/env python3
"""Apply the user choices collected by the Codex cost-aware guided-install flow."""

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

ROUTING_MODES = ("luna_only", "adaptive")
REQUEST_USER_INPUT_FEATURE = "default_mode_request_user_input"
START_MARKER = "<!-- codex-luna-subagent-router:delegation-authorization:start -->"
END_MARKER = "<!-- codex-luna-subagent-router:delegation-authorization:end -->"
LEGACY_HEADING = "## Luna SubAgent 自动路由授权"
LEGACY_AUTHORIZATION_V1_0 = """## Luna SubAgent 自动路由授权

- 用户长期授权主 Agent 在独立分工、并行执行或独立复核具有明确净收益时，自动调用 `$codex-luna-subagent-router`；简单任务不得为了形式创建 SubAgent。
- 主 Agent 保持当前用户选择的 Sol 或 Luna 及其思考强度，负责拆分、所有权、监督、集成、验证和最终交付。
- 未被用户逐个明确指定模型的 SubAgent 必须显式使用 `gpt-5.6-luna`；不得自动继承主模型，也不得静默回退到 Sol、Terra、Auto 或旧模型。
- 主 Agent 必须为每个 SubAgent 在 `medium/high/xhigh/max` 中显式选择思考强度，对应用户可见的中/高/极高/最高。
- 实际创建前先向用户说明每个 SubAgent 的任务简报、复杂度、模型、思考强度、task_id、fresh 上下文和创建理由；默认通知后直接执行，无需再次确认。
- 每个新任务和重试必须使用新线程、新 task_id 和自包含的本轮任务包；禁止把新目标发送到旧 Worker。Worker 必须回显 `TASK_ACK <task_id>`，不匹配的结果视为 `STALE_CONTEXT` 并拒绝采纳。
- Worker 不得继续创建任何 SubAgent、后台任务或线程。精确 Luna 路由不可用时，由主 Agent 接管，不得伪称已经按要求创建。"""

_TABLE_HEADER_RE = re.compile(r"^\s*(\[\[?)([^\]]+?)(\]\]?)(?:\s*#.*)?$")
_FEATURE_ASSIGNMENT_RE = re.compile(
    r"^(\s*(?:default_mode_request_user_input|\"default_mode_request_user_input\"|"
    r"'default_mode_request_user_input')\s*=\s*)(true|false)(\s*(?:#.*)?)(\r?\n?)$"
)
_DOTTED_FEATURE_ASSIGNMENT_RE = re.compile(
    r"^(\s*features\.default_mode_request_user_input\s*=\s*)(true|false)"
    r"(\s*(?:#.*)?)(\r?\n?)$"
)
_ROOT_FEATURES_ASSIGNMENT_RE = re.compile(r"^\s*features\s*=")


class ConfigurationError(ValueError):
    """Raised when guided-install input or a managed target is invalid."""


def _table_header(line: str) -> tuple[str, str] | None:
    content = line.rstrip("\r\n")
    match = _TABLE_HEADER_RE.match(content)
    if not match:
        return None
    opening, name, closing = match.groups()
    if opening == "[" and closing != "]":
        return None
    if opening == "[[" and closing != "]]":
        return None
    if opening == "[" and closing == "]":
        return "table", name.strip()
    if opening == "[[" and closing == "]]":
        return "array", name.strip()
    return None


def _existing_feature_value(text: str) -> bool | None:
    if tomllib is None:
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"config.toml is not valid TOML: {exc}") from exc
    features = data.get("features")
    if features is None:
        return None
    if not isinstance(features, dict):
        raise ConfigurationError(
            "config.toml has a non-table features value; review it manually before enabling "
            f"{REQUEST_USER_INPUT_FEATURE}"
        )
    value = features.get(REQUEST_USER_INPUT_FEATURE)
    if value is not None and not isinstance(value, bool):
        raise ConfigurationError(f"config.toml {REQUEST_USER_INPUT_FEATURE} must be a boolean")
    return value


def merge_request_user_input_feature(existing: str) -> tuple[str, str]:
    if not existing:
        return f"[features]\n{REQUEST_USER_INPUT_FEATURE} = true\n", "created"

    parsed_value = _existing_feature_value(existing)
    lines = existing.splitlines(keepends=True)
    current_table: str | None = None
    feature_header: int | None = None
    first_nested_feature_header: int | None = None
    feature_section_end = len(lines)
    direct_matches: list[tuple[int, re.Match[str]]] = []
    dotted_matches: list[tuple[int, re.Match[str]]] = []
    root_features_assignments: list[int] = []

    for index, line in enumerate(lines):
        header = _table_header(line)
        if header is not None:
            kind, name = header
            if kind == "array" and (name == "features" or name.startswith("features.")):
                raise ConfigurationError(
                    "config.toml uses an array-of-tables for features; review it manually before "
                    f"enabling {REQUEST_USER_INPUT_FEATURE}"
                )
            if kind == "table" and name == "features":
                if feature_header is not None:
                    raise ConfigurationError("config.toml contains duplicate [features] tables")
                feature_header = index
            elif kind == "table" and name.startswith("features."):
                if first_nested_feature_header is None:
                    first_nested_feature_header = index
            if feature_header is not None and index > feature_header and feature_section_end == len(lines):
                feature_section_end = index
            current_table = name if kind == "table" else None
            continue

        if current_table == "features":
            match = _FEATURE_ASSIGNMENT_RE.match(line)
            if match:
                direct_matches.append((index, match))
        elif current_table is None:
            dotted_match = _DOTTED_FEATURE_ASSIGNMENT_RE.match(line)
            if dotted_match:
                dotted_matches.append((index, dotted_match))
            if _ROOT_FEATURES_ASSIGNMENT_RE.match(line):
                root_features_assignments.append(index)

    if len(direct_matches) + len(dotted_matches) > 1:
        raise ConfigurationError(f"config.toml contains duplicate {REQUEST_USER_INPUT_FEATURE} assignments")

    if direct_matches:
        index, match = direct_matches[0]
        current_value = parsed_value
        if current_value is None and tomllib is None:
            current_value = match.group(2) == "true"
        if current_value is True:
            return existing, "unchanged"
        if current_value is not False:
            raise ConfigurationError(f"unable to verify the boolean value of {REQUEST_USER_INPUT_FEATURE}")
        lines[index] = f"{match.group(1)}true{match.group(3)}{match.group(4)}"
        return "".join(lines), "updated"

    if dotted_matches:
        index, match = dotted_matches[0]
        current_value = parsed_value
        if current_value is None and tomllib is None:
            current_value = match.group(2) == "true"
        if current_value is True:
            return existing, "unchanged"
        if current_value is not False:
            raise ConfigurationError(f"unable to verify the boolean value of {REQUEST_USER_INPUT_FEATURE}")
        lines[index] = f"{match.group(1)}true{match.group(3)}{match.group(4)}"
        return "".join(lines), "updated"

    if parsed_value is True:
        return existing, "unchanged"
    if parsed_value is False:
        raise ConfigurationError(
            f"{REQUEST_USER_INPUT_FEATURE} is defined in an inline or otherwise unmanaged "
            "features value; review it manually before enabling"
        )
    if root_features_assignments:
        raise ConfigurationError(
            "config.toml defines features as a root value without an editable [features] table; "
            f"review it manually before enabling {REQUEST_USER_INPUT_FEATURE}"
        )

    if feature_header is not None:
        insertion = feature_section_end
        if insertion and not lines[insertion - 1].endswith(("\n", "\r")):
            lines[insertion - 1] += "\n"
        lines.insert(insertion, f"{REQUEST_USER_INPUT_FEATURE} = true\n")
        return "".join(lines), "updated"

    if first_nested_feature_header is not None:
        lines[first_nested_feature_header:first_nested_feature_header] = [
            "[features]\n",
            f"{REQUEST_USER_INPUT_FEATURE} = true\n",
            "\n",
        ]
        return "".join(lines), "created"

    separator = "" if existing.endswith(("\n", "\r")) else "\n"
    spacing = "" if existing.endswith(("\n\n", "\r\n\r\n")) else "\n"
    return existing + separator + spacing + f"[features]\n{REQUEST_USER_INPUT_FEATURE} = true\n", "created"


def _default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _resolve_existing_directory(value: str | None, label: str) -> Path:
    if not value:
        raise ConfigurationError(f"{label} is required for project-scoped configuration")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ConfigurationError(f"{label} is not an existing directory: {path}")
    return path


def _authorization_block(snippet: str) -> str:
    body = snippet.strip()
    if not body:
        raise ConfigurationError("AGENTS authorization snippet is empty")
    if START_MARKER in body or END_MARKER in body:
        raise ConfigurationError("AGENTS authorization snippet must not contain managed markers")
    return f"{START_MARKER}\n{body}\n{END_MARKER}"


def _read_optional_regular_file(path: Path) -> str | None:
    if path.is_symlink():
        raise ConfigurationError(f"refusing to replace a symbolic-link target: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ConfigurationError(f"target exists but is not a regular file: {path}")
    return path.read_text(encoding="utf-8")


def merge_authorization(existing: str, managed_block: str) -> tuple[str, str]:
    starts = existing.count(START_MARKER)
    ends = existing.count(END_MARKER)
    if starts != ends or starts > 1:
        raise ConfigurationError("AGENTS.md contains malformed or duplicate codex-luna-subagent-router markers")
    if starts == 1 and existing.index(END_MARKER) < existing.index(START_MARKER):
        raise ConfigurationError("AGENTS.md contains managed markers in the wrong order")

    if starts == 0:
        legacy = LEGACY_AUTHORIZATION_V1_0.strip()
        legacy_count = existing.count(legacy)
        if legacy_count > 1:
            raise ConfigurationError("AGENTS.md contains duplicate legacy authorization blocks")
        if legacy_count == 1:
            merged = existing.replace(legacy, managed_block, 1)
            return merged.rstrip() + "\n", "migrated_v1.0"
        if LEGACY_HEADING in existing:
            raise ConfigurationError(
                "AGENTS.md contains an unmarked authorization section that differs from v1.0; "
                "review it manually before installing the managed block"
            )
        prefix = existing.rstrip()
        merged = f"{prefix}\n\n{managed_block}\n" if prefix else f"{managed_block}\n"
        return merged, "created" if not existing else "appended"

    start = existing.index(START_MARKER)
    end = existing.index(END_MARKER, start) + len(END_MARKER)
    before = existing[:start].rstrip()
    after = existing[end:].lstrip()
    pieces = [part for part in (before, managed_block, after.rstrip()) if part]
    return "\n\n".join(pieces) + "\n", "updated"


def build_routing_config(routing_mode: str) -> dict[str, Any]:
    if routing_mode not in ROUTING_MODES:
        raise ConfigurationError(f"routing_mode must be one of: {', '.join(ROUTING_MODES)}")
    return {
        "schema_version": "2.0",
        "routing_mode": routing_mode,
        "cost_objective": "minimize_expected_total_cost",
        "context_budget_policy": "minimal_sufficient",
        "result_budget_policy": "concise_sufficient",
        "max_concurrent_workers": 3,
    }


def _parse_routing_json(text: str, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"routing config is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"routing config root must be an object: {path}")
    return value


def _is_legacy_v1_routing(data: dict[str, Any]) -> bool:
    return (
        data.get("schema_version") == "1.0"
        and data.get("mode") == "additional_responsibilities"
        and isinstance(data.get("levels"), dict)
    )


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


def configure(
    *,
    delegation: str,
    routing_scope: str,
    routing_mode: str,
    project_root: str | None,
    codex_home: Path,
    dry_run: bool,
    replace_routing: bool = False,
    request_user_input: str = "none",
) -> dict[str, Any]:
    if request_user_input not in {"enable", "none"}:
        raise ConfigurationError("request_user_input must be either 'enable' or 'none'")
    if routing_scope not in {"user", "project", "none"}:
        raise ConfigurationError("routing_scope must be user, project, or none")
    if routing_mode not in {*ROUTING_MODES, "none"}:
        raise ConfigurationError("routing_mode must be luna_only, adaptive, or none")
    if (routing_scope == "none") != (routing_mode == "none"):
        raise ConfigurationError("routing_scope and routing_mode must both be none, or both select a managed routing config")

    needs_project = delegation == "project" or routing_scope == "project"
    project = _resolve_existing_directory(project_root, "--project-root") if needs_project else None

    skill_root = Path(__file__).resolve().parents[1]
    snippet = (skill_root / "references" / "AGENTS-snippet.md").read_text(encoding="utf-8")
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "request_user_input": {"scope": "user", "action": "skipped", "path": None},
        "delegation": {"scope": delegation, "action": "skipped", "path": None},
        "routing_config": {"scope": routing_scope, "mode": routing_mode, "action": "skipped", "path": None},
    }
    pending_writes: list[tuple[Path, str]] = []

    if request_user_input == "enable":
        config_path = codex_home / "config.toml"
        existing_config = _read_optional_regular_file(config_path)
        merged_config, action = merge_request_user_input_feature(existing_config or "")
        result["request_user_input"] = {"scope": "user", "action": action, "path": str(config_path)}
        if existing_config != merged_config:
            pending_writes.append((config_path, merged_config))

    if delegation != "none":
        agents_path = codex_home / "AGENTS.md" if delegation == "global" else project / "AGENTS.md"
        existing = _read_optional_regular_file(agents_path) or ""
        merged, action = merge_authorization(existing, _authorization_block(snippet))
        result["delegation"] = {"scope": delegation, "action": action, "path": str(agents_path)}
        if merged != existing:
            pending_writes.append((agents_path, merged))
        else:
            result["delegation"]["action"] = "unchanged"

    if routing_scope != "none":
        table = build_routing_config(routing_mode)
        routing_path = (
            codex_home / "codex-luna-subagent-router" / "routing.json"
            if routing_scope == "user"
            else project / ".codex" / "codex-luna-subagent-router" / "routing.json"
        )
        rendered = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        existing = _read_optional_regular_file(routing_path)

        if existing == rendered:
            action = "unchanged"
        elif existing is None:
            action = "created"
            pending_writes.append((routing_path, rendered))
        else:
            existing_data = _parse_routing_json(existing, routing_path)
            if _is_legacy_v1_routing(existing_data):
                backup_path = routing_path.with_name("routing.v1.backup.json")
                backup_existing = _read_optional_regular_file(backup_path)
                if backup_existing is not None and backup_existing != existing:
                    raise ConfigurationError(f"legacy routing backup already exists with different content: {backup_path}")
                result["routing_config"]["legacy_backup_path"] = str(backup_path)
                if backup_existing is None:
                    pending_writes.append((backup_path, existing))
                pending_writes.append((routing_path, rendered))
                action = "migrated_v1"
            elif replace_routing:
                action = "updated"
                pending_writes.append((routing_path, rendered))
            elif dry_run:
                action = "replace_requires_confirmation"
            else:
                raise ConfigurationError(
                    f"routing config already exists with different content: {routing_path}; "
                    "review it and pass --replace-routing only after user confirmation"
                )

        result["routing_config"].update({"action": action, "path": str(routing_path)})

    if not dry_run:
        for path, text in pending_writes:
            _write_text_atomic(path, text)

    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delegation",
        choices=("global", "project", "none"),
        required=True,
        help="Where to install standing automatic-delegation authorization.",
    )
    parser.add_argument(
        "--routing-scope",
        choices=("user", "project", "none"),
        default="none",
        help="Where to write the two-mode cost-aware routing config.",
    )
    parser.add_argument(
        "--routing-mode",
        choices=("luna_only", "adaptive", "none"),
        default="none",
        help="luna_only for maximum economy, adaptive for cheapest-sufficient automatic routing.",
    )
    parser.add_argument("--project-root", help="Required by any project-scoped choice.")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=_default_codex_home(),
        help="Override CODEX_HOME (primarily for testing).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without writing files.")
    parser.add_argument(
        "--replace-routing",
        action="store_true",
        help="Replace an unknown different routing config after explicit user confirmation.",
    )
    parser.add_argument(
        "--request-user-input",
        choices=("enable", "none"),
        default="none",
        help=(
            "Enable the experimental Default-mode request_user_input feature in the user "
            "config; 'none' preserves the current setting."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = configure(
            delegation=args.delegation,
            routing_scope=args.routing_scope,
            routing_mode=args.routing_mode,
            project_root=args.project_root,
            codex_home=args.codex_home.expanduser().resolve(),
            dry_run=args.dry_run,
            replace_routing=args.replace_routing,
            request_user_input=args.request_user_input,
        )
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        prefix = "DRY RUN" if args.dry_run else "OK"
        print(f"{prefix}: guided configuration completed")
        for key in ("request_user_input", "delegation", "routing_config"):
            item = result[key]
            target = f" -> {item['path']}" if item.get("path") else ""
            mode = f" / {item['mode']}" if item.get("mode") not in {None, "none"} else ""
            print(f"- {key}: {item['scope']}{mode} / {item['action']}{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
