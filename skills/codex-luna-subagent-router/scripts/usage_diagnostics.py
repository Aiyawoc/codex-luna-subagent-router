"""Local snapshot diagnostics. Age describes a saved snapshot, not live Host state."""
from __future__ import annotations
from datetime import datetime, timezone

from usage_cache import VERSION

ERRORS = {
    'no_active_turn': '当前 scope 没有进行中的轮次；历史记录请使用 stats 或显式 refresh。',
    'ambiguous_active_turn': '当前 scope 有多个进行中的轮次；请明确 --session-id 和 --turn-id。',
    'turn_not_registered': '未登记指定轮次；不会用会话累计代替本轮。',
    'turn_not_active': '指定轮次已停止或封存；请使用 stats 或显式 refresh。',
    'scope_mismatch': '指定记录不属于当前 scope；请核对 --project-root / --global-scope。',
    'token_accounting_disabled': '统计未启用；请先按安装第 6 项明确选择。',
    'main_accounting_not_enabled': '未明确启用主／子统一统计；请完成第 6 项升级确认。',
    'invalid_identity': 'session/turn 标识无效；请使用真实的结构化标识。',
    'transcript_locator_changed': '日志定位发生变化或超出允许目录；未自动改读其他日志。',
    'sealed_refresh_requires_opt_in': '该轮次已封存；请使用 refresh 或 collect --refresh-sealed。',
    'invalid_read_budget': '读取预算无效；整批复核最多 30 秒、100 条记录；每个文件每次读取最多 512 MiB。',
    'no_matching_records': '没有匹配此 session、turn 和 scope 的已登记记录。',
    'configuration_invalid': '配置无效；未更改配置、统计口径或信任状态。',
    'ledger_unavailable': '账本或已登记边界不可用；原有记录保持不变。',
}


def describe(row, snapshot=None):
    snap = snapshot or row.get('main_snapshot') or row.get('snapshot') or {}
    stamp = row.get('updated_at')
    try:
        age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()))
    except (TypeError, ValueError, AttributeError):
        age = None
    return dict(reader_version=row.get('reader_version'), current_reader_version=VERSION,
                legacy_snapshot=row.get('reader_version') != VERSION or 'stale_previous_snapshot' in snap.get('reasons', []),
                retained_previous_snapshot='stale_previous_snapshot' in snap.get('reasons', []),
                scope_id=row.get('scope_id'), phase=row.get('phase', 'snapshot'),
                started_at=row.get('started_at'), snapshot_updated_at=stamp,
                last_usage_at=snap.get('last_usage_at'), snapshot_age_seconds=age,
                bytes_scanned=snap.get('bytes_read'), boundary_reason=row.get('boundary_reason'),
                view='saved_snapshot_not_live_status', stats_reads_transcript=False)


def context_line(row):
    d = describe(row)
    identity = f"session={row['session_id']} turn={row['turn_id']}" if 'session_id' in row else f"parent={row['parent_id']} child={row['agent_id']}"
    return (f"{identity} | scope={d['scope_id']} | phase={d['phase']} | "
            f"开始={d['started_at']} | 快照更新={d['snapshot_updated_at']} | "
            f"reader={d['reader_version'] or 'legacy/unknown'} | "
            "已保存快照，stats 不刷新日志")


def error(code):
    return dict(error=dict(code=code, message=ERRORS.get(code, ERRORS['ledger_unavailable'])), reader_version=VERSION)


def budget(limit, seconds, max_bytes):
    import math
    return (type(limit) is int and 1 <= limit <= 100 and isinstance(seconds, (float,int))
            and math.isfinite(seconds) and 0 < seconds <= 30
            and type(max_bytes) is int and 1 <= max_bytes <= 512 * 1024 * 1024)
