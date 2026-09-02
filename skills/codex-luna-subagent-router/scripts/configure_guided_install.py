#!/usr/bin/env python3
"""Apply the user choices collected by the Codex guided-install flow."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

LEVELS = ("medium", "high", "xhigh", "max")
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


class ConfigurationError(ValueError):
    """Raised when guided-install input or a managed target is invalid."""


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
    """Return (new_text, action) while preserving all unmanaged content."""

    starts = existing.count(START_MARKER)
    ends = existing.count(END_MARKER)
    if starts != ends or starts > 1:
        raise ConfigurationError(
            "AGENTS.md contains malformed or duplicate codex-luna-subagent-router markers"
        )
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


def build_routing_table(responsibilities: dict[str, list[str]]) -> dict[str, Any]:
    levels: dict[str, list[str]] = {}
    for level in LEVELS:
        cleaned: list[str] = []
        for raw in responsibilities.get(level, []):
            value = raw.strip()
            if not value:
                raise ConfigurationError(f"{level} responsibility must not be empty")
            if len(value) > 500:
                raise ConfigurationError(f"{level} responsibility exceeds 500 characters")
            if value not in cleaned:
                cleaned.append(value)
        if len(cleaned) > 20:
            raise ConfigurationError(f"{level} may contain at most 20 responsibilities")
        levels[level] = cleaned

    if not any(levels.values()):
        raise ConfigurationError(
            "custom routing was requested, but no additional responsibility was provided"
        )

    return {
        "schema_version": "1.0",
        "mode": "additional_responsibilities",
        "merge_policy": "raise_only",
        "levels": levels,
    }


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
    project_root: str | None,
    codex_home: Path,
    responsibilities: dict[str, list[str]],
    dry_run: bool,
    replace_routing: bool = False,
) -> dict[str, Any]:
    needs_project = delegation == "project" or routing_scope == "project"
    project = _resolve_existing_directory(project_root, "--project-root") if needs_project else None

    skill_root = Path(__file__).resolve().parents[1]
    snippet = (skill_root / "references" / "AGENTS-snippet.md").read_text(encoding="utf-8")
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "delegation": {"scope": delegation, "action": "skipped", "path": None},
        "routing_table": {"scope": routing_scope, "action": "skipped", "path": None},
    }

    pending_writes: list[tuple[Path, str]] = []

    if delegation != "none":
        agents_path = codex_home / "AGENTS.md" if delegation == "global" else project / "AGENTS.md"
        existing = _read_optional_regular_file(agents_path) or ""
        merged, action = merge_authorization(existing, _authorization_block(snippet))
        result["delegation"] = {
            "scope": delegation,
            "action": action,
            "path": str(agents_path),
        }
        if merged != existing:
            pending_writes.append((agents_path, merged))
        else:
            result["delegation"]["action"] = "unchanged"

    if routing_scope != "none":
        table = build_routing_table(responsibilities)
        routing_path = (
            codex_home / "codex-luna-subagent-router" / "routing.json"
            if routing_scope == "user"
            else project / ".codex" / "codex-luna-subagent-router" / "routing.json"
        )
        rendered = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        existing = _read_optional_regular_file(routing_path)
        needs_replace = existing is not None and existing != rendered
        if needs_replace and not replace_routing and not dry_run:
            raise ConfigurationError(
                f"routing table already exists with different content: {routing_path}; "
                "review it and pass --replace-routing only after user confirmation"
            )
        if needs_replace and not replace_routing:
            action = "replace_requires_confirmation"
        else:
            action = "unchanged" if existing == rendered else ("updated" if existing is not None else "created")
        result["routing_table"] = {
            "scope": routing_scope,
            "action": action,
            "path": str(routing_path),
        }
        if existing != rendered and not (needs_replace and not replace_routing):
            pending_writes.append((routing_path, rendered))

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
        help="Where to install the standing automatic-delegation authorization.",
    )
    parser.add_argument(
        "--routing-scope",
        choices=("user", "project", "none"),
        default="none",
        help="Where to write the optional additional-responsibility routing table.",
    )
    parser.add_argument("--project-root", help="Required by any project-scoped choice.")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=_default_codex_home(),
        help="Override CODEX_HOME (primarily for testing).",
    )
    for level in LEVELS:
        parser.add_argument(
            f"--{level}-responsibility",
            action="append",
            default=[],
            metavar="TEXT",
            help=f"Additional work assigned to Luna {level}; repeat as needed.",
        )
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without writing files.")
    parser.add_argument(
        "--replace-routing",
        action="store_true",
        help="Replace a different existing managed routing table after explicit user confirmation.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    responsibilities = {
        level: getattr(args, f"{level}_responsibility") for level in LEVELS
    }
    try:
        result = configure(
            delegation=args.delegation,
            routing_scope=args.routing_scope,
            project_root=args.project_root,
            codex_home=args.codex_home.expanduser().resolve(),
            responsibilities=responsibilities,
            dry_run=args.dry_run,
            replace_routing=args.replace_routing,
        )
    except (ConfigurationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        prefix = "DRY RUN" if args.dry_run else "OK"
        print(f"{prefix}: guided configuration completed")
        for key in ("delegation", "routing_table"):
            item = result[key]
            target = f" -> {item['path']}" if item["path"] else ""
            print(f"- {key}: {item['scope']} / {item['action']}{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
