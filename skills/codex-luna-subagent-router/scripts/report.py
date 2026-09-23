#!/usr/bin/env python3
"""Read-only Router statistics report: Markdown brief plus JSON and CSV exports."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import outcome_store as store
import route_advisor
import token_usage
import turn_usage
import decision_store
import planning_store

REPORT_VERSION = "1.0"
ROUTER_VERSION = store.ROUTER_VERSION
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
CSV_FIELDS = (
    "record_type", "scope_id", "session_id", "turn_id", "phase", "agent_id", "parent_id",
    "model", "effort", "status", "started_at", "updated_at", "total_tokens", "input_tokens",
    "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "reasons", "outcome", "count", "note",
)


def _timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scope(args):
    if args.all_scopes:
        return None, None, "all"
    sid, root = store.resolve_scope(args.project_root, args.global_scope)
    return sid, root, "global" if args.global_scope or (root is None and sid == "global") else "current"


def _default_output_root():
    return store.codex_home() / "state/codex-luna-subagent-router/reports"


def _new_report_dir(root: Path, generated_at: str, scope_label: str) -> Path:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_scope = SAFE_NAME.sub("-", scope_label).strip("-._") or "scope"
    stamp = generated_at.replace(":", "").replace("-", "").replace("Z", "Z")
    candidate = root / f"{stamp}-{safe_scope}"
    index = 2
    while candidate.exists():
        candidate = root / f"{stamp}-{safe_scope}-{index}"
        index += 1
    candidate.mkdir(mode=0o700)
    return candidate


def _counts(snapshot):
    counts = (snapshot or {}).get("counts") or {}
    return {key: counts.get(key) for key in token_usage.FIELDS}


def _snapshot_rows(turn_rows):
    snapshots = []
    for row in turn_rows:
        snapshots.append(row["main_snapshot"])
        snapshots.extend(row.get("child_snapshots", {}).values())
    return snapshots


def _turn_summary(turn_rows):
    main = [row["main_snapshot"] for row in turn_rows]
    all_snapshots = _snapshot_rows(turn_rows)
    phases = Counter(row.get("phase", "unknown") for row in turn_rows)
    reasons = Counter()
    for snapshot in all_snapshots:
        reasons.update(snapshot.get("reasons", []))
    return {
        "registered_turns": len(turn_rows),
        "phases": dict(phases),
        "excluded_children": sum(int(row.get("excluded_children", 0)) for row in turn_rows),
        "main_completeness": token_usage.aggregate_snapshots(main),
        "registered_thread_completeness": token_usage.aggregate_snapshots(all_snapshots),
        "reason_counts": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        "latest_snapshot_at": max((row.get("updated_at") for row in turn_rows if row.get("updated_at")), default=None),
    }


def collect(scope_id, project_root=None):
    registry = store.default_registry_path()
    usage_path = token_usage.default_usage_path(registry)
    outcomes = route_advisor.stats(registry, scope=scope_id)
    subagents = token_usage.statistics(usage_path, scope=scope_id)
    turns = turn_usage.statistics(usage_path, scope=scope_id)
    planning_paths = [planning_store.default_path(registry)]
    if project_root is not None:
        planning_paths.append(planning_store.project_path(project_root))
    planning = planning_store.statistics_many(planning_paths, scope=scope_id)
    decision_rows, invalid_decisions = decision_store.read()
    decision_rows = [row for row in decision_rows if scope_id is None or row["scope_id"] == scope_id]
    decision_status = Counter(row["status"] for row in decision_rows)
    decision_providers = Counter(row["provider"] for row in decision_rows)
    latencies = sorted(row["latency_ms"] for row in decision_rows if type(row.get("latency_ms")) is int)
    decisions = {
        "records": len(decision_rows),
        "statuses": dict(decision_status),
        "providers": dict(decision_providers),
        "available": decision_status.get("available", 0),
        "unavailable": decision_status.get("unavailable", 0),
        "with_confidence": sum(1 for row in decision_rows if row.get("confidence") is not None),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
        "invalid_decision_rows": invalid_decisions,
        "latest_recorded_at": max((row.get("recorded_at") for row in decision_rows), default=None),
    }
    return {
        "outcomes": outcomes,
        "subagents": subagents,
        "turns": {"summary": _turn_summary(turns), "records": turns},
        "planning": planning,
        "decisions": decisions,
    }


def _sanitized(data):
    """Remove local filesystem locations; keep IDs and accounting metadata for diagnostics."""
    data = json.loads(json.dumps(data, ensure_ascii=False))
    data.get("outcomes", {}).pop("registry", None)
    data.get("subagents", {}).pop("usage_file", None)
    return data


def _row(record_type, **values):
    row = {field: "" for field in CSV_FIELDS}
    row["record_type"] = record_type
    for key, value in values.items():
        if key in row:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            elif value is None:
                value = ""
            row[key] = value
    return row


def csv_rows(data):
    rows = []
    outcomes = data["outcomes"]
    for outcome, count in sorted(outcomes.get("outcomes", {}).items()):
        rows.append(_row("outcome_summary", scope_id=outcomes.get("scope"), outcome=outcome, count=count))
    for item in outcomes.get("by_model", []):
        rows.append(_row("outcome_route", scope_id=outcomes.get("scope"), model=item.get("model"),
                         effort=item.get("effort"), outcome=item.get("outcome"), count=item.get("count")))
    for item in outcomes.get("available_recommendations", []):
        rows.append(_row("recommendation", scope_id=item.get("scope_id"), model=item.get("model"),
                         effort=item.get("effort"), note=item.get("rule")))
    for worker in data["subagents"].get("workers", []):
        snapshot = worker.get("snapshot", {})
        rows.append(_row("subagent", scope_id=worker.get("scope_id"), agent_id=worker.get("agent_id"),
                         parent_id=worker.get("parent_id"), model=snapshot.get("model"), effort=snapshot.get("effort"),
                         status=snapshot.get("status"), started_at=worker.get("started_at"), updated_at=worker.get("updated_at"),
                         reasons=snapshot.get("reasons", []), **_counts(snapshot)))
    for turn in data["turns"].get("records", []):
        main = turn.get("main_snapshot", {})
        common = dict(scope_id=turn.get("scope_id"), session_id=turn.get("session_id"), turn_id=turn.get("turn_id"),
                      phase=turn.get("phase"), started_at=turn.get("started_at"), updated_at=turn.get("updated_at"))
        rows.append(_row("turn_main", model=main.get("model"), effort=main.get("effort"), status=main.get("status"),
                         reasons=main.get("reasons", []), **common, **_counts(main)))
        for agent_id, snapshot in sorted(turn.get("child_snapshots", {}).items()):
            rows.append(_row("turn_child", agent_id=agent_id, model=snapshot.get("model"), effort=snapshot.get("effort"),
                             status=snapshot.get("status"), reasons=snapshot.get("reasons", []), **common, **_counts(snapshot)))
    return rows


def _compact_counts(counts):
    return (f"总量 {token_usage.compact(counts.get('total_tokens'))} / "
            f"输入 {token_usage.compact(counts.get('input_tokens'))}（缓存 {token_usage.compact(counts.get('cached_input_tokens'))}）/ "
            f"输出 {token_usage.compact(counts.get('output_tokens'))}")


def _coverage_line(coverage):
    return (f"完整 {coverage.get('complete', 0)} / 待确认 {coverage.get('waiting', 0)} / "
            f"部分 {coverage.get('partial', 0)} / 不可用 {coverage.get('unavailable', 0)}")


def markdown(payload):
    """Fixed chat-first Markdown panel. brief.md and stdout intentionally share this exact layout."""
    data = payload["data"]
    outcomes, subagents, turns = data["outcomes"], data["subagents"], data["turns"]["summary"]
    planning, decisions = data.get("planning", {}), data.get("decisions", {})
    known = subagents.get("known_usage", {}).get("counts", {})
    subcov = subagents.get("completeness", {})
    maincov = turns.get("main_completeness", {})
    threadcov = turns.get("registered_thread_completeness", {})
    turn_known = threadcov.get("counts", {})
    outcome_counts = outcomes.get("outcomes", {})
    scope = payload["scope"]["scope_id"] or "all"
    mode = payload["scope"]["mode"]

    lines = [
        "# 📊 Codex Router · 数据简报",
        "",
        f"`Router v{payload['router_version']}` · `{scope}` · `{mode}` · `{payload['generated_at']}`",
        "",
        "## 核心指标",
        "",
        "| 指标 | 当前值 | 指标 | 当前值 |",
        "|---|---:|---|---:|",
        f"| ✅ Verified pass | **{outcome_counts.get('verified_pass', 0)}** | ❌ Verified fail | **{outcome_counts.get('verified_fail', 0)}** |",
        f"| ◐ Partial outcome | **{outcome_counts.get('partial', 0)}** | ⏳ Pending receipt | **{outcomes.get('pending_count', 0)}** |",
        f"| 🤖 SubAgent | **{subagents.get('observed_subagents', 0)}** | 🧵 主轮次 | **{turns.get('registered_turns', 0)}** |",
        f"| 🔢 SubAgent 已知 Token | **{token_usage.compact(known.get('total_tokens'))}** | 🔢 主/子轮次已知 Token | **{token_usage.compact(turn_known.get('total_tokens'))}** |",
        "",
        "## Token 完整度",
        "",
        "| 范围 | 完整 | 待确认 | 部分 | 不可用 |",
        "|---|---:|---:|---:|---:|",
        f"| SubAgent | {subcov.get('complete', 0)} | {subcov.get('waiting', 0)} | {subcov.get('partial', 0)} | {subcov.get('unavailable', 0)} |",
        f"| Main Agent | {maincov.get('complete', 0)} | {maincov.get('waiting', 0)} | {maincov.get('partial', 0)} | {maincov.get('unavailable', 0)} |",
        f"| 已登记主/子线程 | {threadcov.get('complete', 0)} | {threadcov.get('waiting', 0)} | {threadcov.get('partial', 0)} | {threadcov.get('unavailable', 0)} |",
        "",
        "## 已知用量",
        "",
        "| 范围 | 总量 | 输入 | 缓存输入 | 输出 |",
        "|---|---:|---:|---:|---:|",
        f"| SubAgent | {token_usage.compact(known.get('total_tokens'))} | {token_usage.compact(known.get('input_tokens'))} | {token_usage.compact(known.get('cached_input_tokens'))} | {token_usage.compact(known.get('output_tokens'))} |",
        f"| 已登记主/子轮次 | {token_usage.compact(turn_known.get('total_tokens'))} | {token_usage.compact(turn_known.get('input_tokens'))} | {token_usage.compact(turn_known.get('cached_input_tokens'))} | {token_usage.compact(turn_known.get('output_tokens'))} |",
        "",
        "## 模型使用",
        "",
        "| 模型 | 强度 | Worker | 总量 | 输入 | 缓存 | 输出 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in subagents.get("by_model", []):
        c = item.get("counts", {})
        lines.append(
            f"| {item.get('model') or '未核实'} | {item.get('effort') or '未知'} | {item.get('workers', 0)} | "
            f"{token_usage.compact(c.get('total_tokens'))} | {token_usage.compact(c.get('input_tokens'))} | "
            f"{token_usage.compact(c.get('cached_input_tokens'))} | {token_usage.compact(c.get('output_tokens'))} |"
        )
    if not subagents.get("by_model"):
        lines.append("| - | - | 0 | - | - | - | - |")

    lines.extend([
        "",
        "## 验收结果",
        "",
        "| 结果 | 数量 |",
        "|---|---:|",
        f"| ✅ verified_pass | {outcome_counts.get('verified_pass', 0)} |",
        f"| ❌ verified_fail | {outcome_counts.get('verified_fail', 0)} |",
        f"| ◐ partial | {outcome_counts.get('partial', 0)} |",
        f"| ⏳ pending receipt | {outcomes.get('pending_count', 0)} |",
        f"| 📐 可用校准建议 | {len(outcomes.get('available_recommendations', []))} |",
        "",
        "## 执行规划",
        "",
        "| 指标 | 当前值 |",
        "|---|---:|",
        f"| 规划次数 | {planning.get('plans', 0)} |",
        f"| local_serial | {planning.get('execution_shapes', {}).get('local_serial', 0)} |",
        f"| local_parallel_tools | {planning.get('execution_shapes', {}).get('local_parallel_tools', 0)} |",
        f"| subagent | {planning.get('execution_shapes', {}).get('subagent', 0)} |",
        f"| Planned Worker | {planning.get('planned_workers', 0)} |",
        f"| Health probe | {planning.get('health_probes', 0)} |",
        "",
        "## Decision Shadow",
        "",
        "| 指标 | 当前值 |",
        "|---|---:|",
        f"| Shadow records | {decisions.get('records', 0)} |",
        f"| Available | {decisions.get('available', 0)} |",
        f"| Unavailable | {decisions.get('unavailable', 0)} |",
        f"| 有 confidence | {decisions.get('with_confidence', 0)} |",
        f"| 中位延迟 | {decisions.get('median_latency_ms') if decisions.get('median_latency_ms') is not None else '-'} ms |",
        "",
        "## ⚠️ 需要关注",
        "",
    ])
    reasons = Counter()
    for worker in subagents.get("workers", []):
        reasons.update(worker.get("snapshot", {}).get("reasons", []))
    reasons.update(turns.get("reason_counts", {}))
    if turns.get("excluded_children", 0):
        lines.append(f"- `unassociated_children`：{turns['excluded_children']}")
    if reasons:
        for reason, count in reasons.most_common(10):
            lines.append(f"- `{reason}`：{count}")
    if not reasons and not turns.get("excluded_children", 0):
        lines.append("- ✅ 当前已保存统计没有诊断原因。")

    lines.extend([
        "",
        "> 当前面板只读已保存统计，不执行 `refresh`。`partial / unavailable` 代表未知或不完整，不按 0 计算。",
        "",
        "## 数据文件",
        "",
        "- `brief.md`：与聊天中显示相同的固定面板。",
        "- `data.json`：权威机器可读快照，保留嵌套结构和 token 原始整数。",
        "- `data.csv`：UTF-8 BOM 扁平表，适合 Excel、Numbers、脚本和数据分析工具。",
        "",
        "## 口径说明",
        "",
        "- token 是已知快照，不是账单、配额或实测节省；缓存命中属于输入子项。",
        "- Outcome 是 Lead 验收结果；token 完整度与任务质量是两个不同维度。",
        "- CSV/JSON 可能包含 session / turn / agent ID；不包含 prompt、回复正文、源码或原始 rollout 行。",
        "- `all` 范围可能混合多个项目；项目简报优先从目标项目目录运行，或显式传 `--project-root`。",
        "",
    ])
    return "\n".join(lines)

def write_report(data, scope_id, mode, output_root):
    generated_at = _timestamp()
    clean = _sanitized(data)
    payload = {
        "schema_version": REPORT_VERSION,
        "router_version": ROUTER_VERSION,
        "generated_at": generated_at,
        "scope": {"mode": mode, "scope_id": scope_id},
        "data": clean,
        "limitations": [
            "Read-only saved statistics; no refresh or rollout discovery is performed.",
            "Known token counts are not billing, quota, or measured savings.",
            "Missing values are unknown, not zero.",
        ],
    }
    report_dir = _new_report_dir(output_root, generated_at, scope_id or "all")
    json_path, csv_path, md_path = report_dir / "data.json", report_dir / "data.csv", report_dir / "brief.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_rows(clean))
    md_path.write_text(markdown(payload), encoding="utf-8")
    for path in (json_path, csv_path, md_path):
        try: os.chmod(path, 0o600)
        except OSError: pass
    return payload, md_path, json_path, csv_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all-scopes", action="store_true", help="汇总所有已保存 scope；默认只看当前项目/global scope")
    scope.add_argument("--global-scope", action="store_true", help="只看 global scope")
    scope.add_argument("--project-root", type=Path, help="明确指定项目根目录")
    parser.add_argument("--output-dir", type=Path, help="报告根目录；默认写入 CODEX_HOME/state/.../reports")
    parser.add_argument("--json", action="store_true", help="stdout 输出生成结果 JSON；文件内容不变")
    args = parser.parse_args(argv)
    try:
        sid, _, mode = _scope(args)
        data = collect(sid, root)
        payload, md_path, json_path, csv_path = write_report(data, sid, mode, args.output_dir or _default_output_root())
        result = {
            "status": "ok", "generated_at": payload["generated_at"], "scope": payload["scope"],
            "brief": str(md_path), "json": str(json_path), "csv": str(csv_path),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(markdown(payload))
            print("\n生成文件：")
            print(f"- Markdown: {md_path}")
            print(f"- JSON: {json_path}")
            print(f"- CSV: {csv_path}")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: report unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
