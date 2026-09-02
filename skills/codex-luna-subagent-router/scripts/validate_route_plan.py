#!/usr/bin/env python3
"""Validate a codex-luna-subagent-router RoutePlan and optionally render its user notice."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_LEVELS = ("medium", "high", "xhigh", "max")
ALLOWED_SURFACES = ("native_subagent", "app_thread")
ALLOWED_USER_INPUT_STATES = ("not_needed", "resolved")
PROFILE_BY_LEVEL = {
    "medium": "luna_medium",
    "high": "luna_high",
    "xhigh": "luna_xhigh",
    "max": "luna_max",
}
CN_LEVEL = {
    "medium": "中",
    "high": "高",
    "xhigh": "极高",
    "max": "最高",
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_string(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> str | None:
    value = obj.get(key)
    if not _is_nonempty_string(value):
        errors.append(f"{path}.{key}: must be a non-empty string")
        return None
    return value.strip()


def _require_string_list(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        errors.append(f"{path}.{key}: must be a list of strings")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not _is_nonempty_string(item):
            errors.append(f"{path}.{key}[{index}]: must be a non-empty string")
        else:
            result.append(item.strip())
    return result


def _normalize_write_path(value: str) -> str:
    path = str(PurePosixPath(value.strip().replace("\\", "/")))
    return path.rstrip("/") or "/"


def _paths_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    if left == "/" or right == "/":
        return True
    return left.startswith(right + "/") or right.startswith(left + "/")


def _validate_clarifications(value: Any, path: str, errors: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be a list")
        return []
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: must be an object")
            continue
        question = _require_string(item, "question", item_path, errors)
        answer = _require_string(item, "answer", item_path, errors)
        if question and answer:
            result.append({"question": question, "answer": answer})
    return result


def _validate_dependencies(workers: list[dict[str, Any]], errors: list[str]) -> None:
    ids = {worker.get("task_id") for worker in workers if isinstance(worker.get("task_id"), str)}
    graph: dict[str, list[str]] = {}
    for index, worker in enumerate(workers):
        task_id = worker.get("task_id")
        if not isinstance(task_id, str):
            continue
        deps = worker.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(f"workers[{index}].depends_on: must be a list")
            continue
        clean: list[str] = []
        for dep_index, dep in enumerate(deps):
            if not isinstance(dep, str) or dep not in ids:
                errors.append(f"workers[{index}].depends_on[{dep_index}]: unknown task_id {dep!r}")
            elif dep == task_id:
                errors.append(f"workers[{index}].depends_on[{dep_index}]: task cannot depend on itself")
            else:
                clean.append(dep)
        graph[task_id] = clean

    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        marker = state.get(node, 0)
        if marker == 1:
            cycle = " -> ".join(stack + [node])
            errors.append(f"workers.depends_on: dependency cycle detected: {cycle}")
            return
        if marker == 2:
            return
        state[node] = 1
        for dep in graph.get(node, []):
            visit(dep, stack + [node])
        state[node] = 2

    for node in graph:
        visit(node, [])


def validate_plan(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root: plan must be a JSON object"]

    if data.get("schema_version") != "1.1":
        errors.append('schema_version: must equal "1.1"')

    root_request_id = _require_string(data, "root_request_id", "root", errors)
    if root_request_id and not ID_RE.fullmatch(root_request_id):
        errors.append("root.root_request_id: invalid identifier format")

    if data.get("approval_mode") not in {"notify_and_proceed", "require_user_confirmation"}:
        errors.append("root.approval_mode: must be notify_and_proceed or require_user_confirmation")
    if data.get("on_route_rejected") != "lead_only":
        errors.append('root.on_route_rejected: must equal "lead_only"; silent model fallback is forbidden')
    if data.get("stale_context_policy") != "reject_and_respawn_fresh":
        errors.append('root.stale_context_policy: must equal "reject_and_respawn_fresh"')

    user_input_state = data.get("user_input_state")
    if user_input_state not in ALLOWED_USER_INPUT_STATES:
        errors.append(
            "root.user_input_state: must be not_needed or resolved; pending user input cannot be dispatched"
        )
    clarifications = _validate_clarifications(data.get("clarifications"), "root.clarifications", errors)
    if user_input_state == "not_needed" and clarifications:
        errors.append("root.clarifications: must be empty when user_input_state=not_needed")
    if user_input_state == "resolved" and not clarifications:
        errors.append("root.clarifications: must contain at least one answered item when user_input_state=resolved")

    max_attempts = data.get("max_attempts_per_task")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not (1 <= max_attempts <= 2):
        errors.append("root.max_attempts_per_task: must be integer 1 or 2")
        max_attempts = 2

    workers = data.get("workers")
    if not isinstance(workers, list) or not workers:
        errors.append("root.workers: must contain at least one Worker")
        return errors
    if len(workers) > 6:
        errors.append("root.workers: may contain at most 6 Workers")

    seen_ids: set[str] = set()
    normalized_write_paths: list[tuple[int, int, str, str]] = []

    for index, raw_worker in enumerate(workers):
        path = f"workers[{index}]"
        if not isinstance(raw_worker, dict):
            errors.append(f"{path}: must be an object")
            continue
        worker = raw_worker

        task_id = _require_string(worker, "task_id", path, errors)
        if task_id:
            if not ID_RE.fullmatch(task_id):
                errors.append(f"{path}.task_id: invalid identifier format")
            if task_id in seen_ids:
                errors.append(f"{path}.task_id: duplicate task_id {task_id}")
            seen_ids.add(task_id)

        attempt = worker.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or not (1 <= attempt <= max_attempts):
            errors.append(f"{path}.attempt: must be an integer between 1 and {max_attempts}")

        wave = worker.get("wave")
        if not isinstance(wave, int) or isinstance(wave, bool) or wave < 1:
            errors.append(f"{path}.wave: must be a positive integer")
            wave = 1

        _require_string(worker, "brief", path, errors)
        _require_string(worker, "creation_reason", path, errors)

        complexity = worker.get("complexity")
        effort = worker.get("reasoning_effort")
        if complexity not in ALLOWED_LEVELS:
            errors.append(f"{path}.complexity: must be one of {', '.join(ALLOWED_LEVELS)}")
        if effort not in ALLOWED_LEVELS:
            errors.append(f"{path}.reasoning_effort: must be one of {', '.join(ALLOWED_LEVELS)}")

        model = worker.get("model")
        override = worker.get("user_model_override")
        if not isinstance(override, bool):
            errors.append(f"{path}.user_model_override: must be boolean")
            override = False
        if override:
            if worker.get("override_source") != "user":
                errors.append(f'{path}.override_source: must equal "user" when model override is enabled')
            _require_string(worker, "override_reason", path, errors)
        else:
            if model != "gpt-5.6-luna":
                errors.append(f'{path}.model: must equal "gpt-5.6-luna" unless the user explicitly overrides it')
            if worker.get("override_source") not in {None, ""}:
                errors.append(f"{path}.override_source: must be null without an override")

        profile = worker.get("agent_profile")
        if model == "gpt-5.6-luna" and effort in PROFILE_BY_LEVEL:
            expected_profile = PROFILE_BY_LEVEL[effort]
            if profile != expected_profile:
                errors.append(f'{path}.agent_profile: expected "{expected_profile}" for reasoning_effort={effort}')
        elif not _is_nonempty_string(profile):
            errors.append(f"{path}.agent_profile: must be a non-empty string")

        surface = worker.get("surface")
        if surface not in ALLOWED_SURFACES:
            errors.append(f"{path}.surface: must be one of {', '.join(ALLOWED_SURFACES)}")
        if worker.get("context_mode") != "fresh":
            errors.append(f'{path}.context_mode: must equal "fresh"')
        if worker.get("new_thread") is not True:
            errors.append(f"{path}.new_thread: must be true")

        fork_turns = worker.get("fork_turns")
        if surface == "native_subagent" and fork_turns not in {None, "none"}:
            errors.append(f'{path}.fork_turns: native fresh tasks may only use null or "none"')
        if surface == "app_thread" and fork_turns is not None:
            errors.append(f"{path}.fork_turns: app_thread must use null/omitted; create a new thread instead")

        write_paths = worker.get("write_paths", [])
        if not isinstance(write_paths, list):
            errors.append(f"{path}.write_paths: must be a list")
        else:
            for path_index, write_path in enumerate(write_paths):
                if not _is_nonempty_string(write_path):
                    errors.append(f"{path}.write_paths[{path_index}]: must be a non-empty string")
                    continue
                normalized = _normalize_write_path(write_path)
                normalized_write_paths.append((index, wave, task_id or path, normalized))

        packet = worker.get("task_packet")
        packet_path = f"{path}.task_packet"
        if not isinstance(packet, dict):
            errors.append(f"{packet_path}: must be an object")
            continue

        packet_root_id = _require_string(packet, "root_request_id", packet_path, errors)
        packet_task_id = _require_string(packet, "task_id", packet_path, errors)
        if root_request_id and packet_root_id and packet_root_id != root_request_id:
            errors.append(f"{packet_path}.root_request_id: must match root.root_request_id")
        if task_id and packet_task_id and packet_task_id != task_id:
            errors.append(f"{packet_path}.task_id: must match Worker task_id")

        for key in ("current_user_request", "normalized_goal", "subtask_goal", "output_contract"):
            _require_string(packet, key, packet_path, errors)
        packet_clarifications = _validate_clarifications(
            packet.get("clarifications"), f"{packet_path}.clarifications", errors
        )
        if packet_clarifications != clarifications:
            errors.append(
                f"{packet_path}.clarifications: must exactly match the resolved root clarifications"
            )
        for key in (
            "in_scope",
            "out_of_scope",
            "necessary_context",
            "resources",
            "constraints",
            "acceptance_criteria",
        ):
            _require_string_list(packet, key, packet_path, errors)

        if packet.get("no_subagents") is not True:
            errors.append(f"{packet_path}.no_subagents: must be true")
        if packet.get("sole_source_of_truth") is not True:
            errors.append(f"{packet_path}.sole_source_of_truth: must be true")
        if packet.get("start_response_with_task_ack") is not True:
            errors.append(f"{packet_path}.start_response_with_task_ack: must be true")

    _validate_dependencies([w for w in workers if isinstance(w, dict)], errors)

    for left_index in range(len(normalized_write_paths)):
        wi, wave_i, id_i, path_i = normalized_write_paths[left_index]
        for right_index in range(left_index + 1, len(normalized_write_paths)):
            wj, wave_j, id_j, path_j = normalized_write_paths[right_index]
            if wi == wj or wave_i != wave_j:
                continue
            if _paths_overlap(path_i, path_j):
                errors.append(
                    f"workers.write_paths: same-wave overlap between {id_i} ({path_i}) and {id_j} ({path_j})"
                )

    return errors


def render_notice(data: dict[str, Any]) -> str:
    workers = data.get("workers", [])
    approval_mode = data.get("approval_mode")
    suffix = "等待用户确认后执行。" if approval_mode == "require_user_confirmation" else "通知后直接执行。"
    state = data.get("user_input_state")
    clarification_count = len(data.get("clarifications", []))
    clarification_summary = (
        f"已合并 {clarification_count} 项用户澄清"
        if state == "resolved"
        else "无需额外用户澄清"
    )
    lines = [f"准备创建 {len(workers)} 个 SubAgent；{suffix}", f"用户输入：{clarification_summary}", ""]
    for index, worker in enumerate(workers, start=1):
        effort = worker.get("reasoning_effort", "unknown")
        complexity = worker.get("complexity", "unknown")
        lines.extend(
            [
                f"{index}. {worker.get('brief', '<missing brief>')}",
                f"   - task_id：{worker.get('task_id', '<missing>')}",
                f"   - 复杂度：{CN_LEVEL.get(complexity, complexity)} ({complexity})",
                f"   - 模型：{worker.get('model', '<missing>')}",
                f"   - 思考强度：{CN_LEVEL.get(effort, effort)} ({effort})",
                f"   - Agent：{worker.get('agent_profile', '<missing>')}",
                f"   - 上下文：fresh / 新线程",
                f"   - 创建理由：{worker.get('creation_reason', '<missing>')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _load(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="RoutePlan JSON path, or - for stdin")
    parser.add_argument("--notice", action="store_true", help="Print the exact pre-dispatch user notice")
    args = parser.parse_args(argv)

    try:
        data = _load(args.plan)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to read plan: {exc}", file=sys.stderr)
        return 2

    errors = validate_plan(data)
    if errors:
        print(f"INVALID: {len(errors)} error(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OK: valid RoutePlan with {len(data['workers'])} Worker(s)")
    if args.notice:
        print()
        print(render_notice(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
