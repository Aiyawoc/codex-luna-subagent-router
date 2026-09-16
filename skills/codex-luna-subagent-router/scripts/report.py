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


def collect(scope_id):
    registry = store.default_registry_path()
    usage_path = token_usage.default_usage_path(registry)
    outcomes = route_advisor.stats(registry, scope=scope_id)
    subagents = token_usage.statistics(usage_path, scope=scope_id)
    turns = turn_usage.statistics(usage_path, scope=scope_id)
    return {
        "outcomes": outcomes,
        "subagents": subagents,
        "turns": {"summary": _turn_summary(turns), "records": turns},
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
    data = payload["data"]
    outcomes, subagents, turns = data["outcomes"], data["subagents"], data["turns"]["summary"]
    known = subagents.get("known_usage", {}).get("counts", {})
    subcov = subagents.get("completeness", {})
    maincov = turns.get("main_completeness", {})
    threadcov = turns.get("registered_thread_completeness", {})
    lines = [
        "# Codex Router 数据简报",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- Router：`v{payload['router_version']}`",
        f"- 数据范围：`{payload['scope']['scope_id'] or 'all'}`（{payload['scope']['mode']}）",
        "- 采集方式：只读现有 `route_advisor stats`、`token_usage stats`、`turn_usage stats` 数据；**不会执行 refresh，也不会修改账本**。",
        "",
        "## 概览",
        "",
        f"- 验收结果：{outcomes.get('total_outcomes', 0)} 条；verified_pass {outcomes.get('outcomes', {}).get('verified_pass', 0)} / verified_fail {outcomes.get('outcomes', {}).get('verified_fail', 0)} / partial {outcomes.get('outcomes', {}).get('partial', 0)}。",
        f"- 待结算回执：{outcomes.get('pending_count', 0)}；可用校准建议：{len(outcomes.get('available_recommendations', []))}。",
        f"- 已观察 SubAgent：{subagents.get('observed_subagents', 0)}；{_coverage_line(subcov)}。",
        f"- SubAgent 已知用量：{_compact_counts(known)}。",
        f"- 已登记主轮次：{turns.get('registered_turns', 0)}；阶段 {json.dumps(turns.get('phases', {}), ensure_ascii=False, sort_keys=True)}。",
        f"- 主 Agent 快照：{_coverage_line(maincov)}；已登记主/子线程快照：{_coverage_line(threadcov)}。",
        f"- 本轮账本已知合计：{_compact_counts(threadcov.get('counts', {}))}；未安全关联子线程 {turns.get('excluded_children', 0)} 个。",
        "",
        "## Outcome 分布",
        "",
        "| 模型 | 强度 | 结果 | 数量 |",
        "|---|---|---|---:|",
    ]
    for item in outcomes.get("by_model", []):
        lines.append(f"| {item.get('model') or '未知'} | {item.get('effort') or '未知'} | {item.get('outcome')} | {item.get('count', 0)} |")
    if not outcomes.get("by_model"):
        lines.append("| - | - | 暂无记录 | 0 |")
    lines.extend(["", "## SubAgent 路由与已知用量", "", "| 模型 | 强度 | Worker | 总量 | 输入 | 缓存 | 输出 |", "|---|---|---:|---:|---:|---:|---:|"])
    for item in subagents.get("by_model", []):
        c = item.get("counts", {})
        lines.append(f"| {item.get('model') or '未核实'} | {item.get('effort') or '未知'} | {item.get('workers', 0)} | {token_usage.compact(c.get('total_tokens'))} | {token_usage.compact(c.get('input_tokens'))} | {token_usage.compact(c.get('cached_input_tokens'))} | {token_usage.compact(c.get('output_tokens'))} |")
    if not subagents.get("by_model"):
        lines.append("| - | - | 0 | - | - | - | - |")
    reasons = Counter()
    for worker in subagents.get("workers", []):
        reasons.update(worker.get("snapshot", {}).get("reasons", []))
    reasons.update(turns.get("reason_counts", {}))
    lines.extend(["", "## 主要诊断", ""])
    if reasons:
        for reason, count in reasons.most_common(10):
            lines.append(f"- `{reason}`：{count}")
    else:
        lines.append("- 当前已保存统计没有诊断原因。")
    lines.extend([
        "", "## 数据文件", "",
        "- `data.json`：完整、嵌套、保留原始整数的机器可读快照；适合作为后续分析的权威导出。",
        "- `data.csv`：扁平化 outcome / SubAgent / 主轮次 / 子线程记录；适合 Excel、Numbers、脚本和数据分析工具。",
        "- CSV/JSON 可能包含 session / turn / agent ID；不包含 prompt、回复正文、源码或原始 rollout 行。",
        "", "## 口径说明", "",
        "- token 数为已知快照，不是账单、配额或实际节省；缓存命中属于输入子项。",
        "- `partial` / `unavailable` 不等于 0；本命令不会为了生成报告自动补读长日志。",
        "- Outcome 是 Lead 验收结果；token 完整度与任务质量是两个不同维度。",
        "- `all` 范围可能混合多个项目；需要项目简报时应从目标项目目录运行默认命令，或显式传 `--project-root`。",
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
        data = collect(sid)
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
