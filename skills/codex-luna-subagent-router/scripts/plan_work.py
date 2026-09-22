"""Plan all bounded siblings together; never spawn Workers or fill slots for display."""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

import route_advisor as advisor
import outcome_store as store
import configure_subagent_limit as concurrency

RETAIN_REASONS = {"critical_path", "context_not_transferable", "permission_boundary", "external_side_effect", "already_completed"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def session_limit(requested, project_root=None):
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise advisor.AdvisorError("max-workers must be a positive integer")
    limit = min(3, requested)
    configs = [store.codex_home() / "config.toml"]
    if project_root:
        configs.append(Path(project_root) / ".codex/config.toml")
    for config in configs:
        if not config.exists():
            continue
        try:
            import tomllib
            data = tomllib.loads(config.read_text(encoding="utf-8"))
        except ImportError as exc:
            raise advisor.AdvisorError("Python tomllib is unavailable; use the bundled bin/router instead of system python3") from exc
        except ValueError as exc:
            raise advisor.AdvisorError("cannot safely read Codex concurrency config") from exc
        try:
            value = concurrency.effective_subagent_limit(data)
        except concurrency.ConfigurationError as exc:
            raise advisor.AdvisorError("invalid or conflicting Codex concurrency cap") from exc
        if value is not None:
            limit = min(limit, value)
    return limit


def normalized_paths(value):
    if not isinstance(value, list) or any(not isinstance(p, str) or not p.strip() for p in value):
        raise advisor.AdvisorError("read_paths/write_paths must be lists of exact repository-relative paths")
    clean = []
    for p in value:
        p = p.replace("\\", "/")
        if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/") or any(c in p for c in "*?[]"):
            raise advisor.AdvisorError("use normalized relative paths, no glob or parent traversal")
        clean.append(posixpath.normpath(p).rstrip("/"))
    return clean


def overlap(a, b):
    return a == "." or b == "." or a == b or a.startswith(b + "/") or b.startswith(a + "/")


def conflict(a, b):
    return any(overlap(x, y) for x in a["write_paths"] for y in b["write_paths"] + b["read_paths"]) or any(overlap(x, y) for x in b["write_paths"] for y in a["read_paths"])


def plan_work(payload, *, lead_model, lead_effort, calibration, registry, scope, routing_mode="adaptive", max_workers=3, open_workers=0, project_root=None):
    if not isinstance(payload, dict) or set(payload) - {"version", "tasks", "completed_task_ids", "in_progress_task_ids"} or payload.get("version") != 1:
        raise advisor.AdvisorError("plan requires version=1 and a task list")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 32:
        raise advisor.AdvisorError("plan accepts 1..32 bounded tasks, not 32 concurrent Workers")
    if routing_mode not in ("adaptive", "luna_only"):
        raise advisor.AdvisorError("invalid routing_mode")
    if not isinstance(open_workers, int) or isinstance(open_workers, bool) or open_workers < 0:
        raise advisor.AdvisorError("open-workers must be the current PendingInit/Running Worker count")
    limit = session_limit(max_workers, project_root)
    by_id, decisions, groups = {}, [], []
    allowed = {"task_id", "task_family", "axes", "depends_on", "write_paths", "read_paths", "batch_key", "retain_reason", "independent_review"}
    for t in tasks:
        if not isinstance(t, dict) or set(t) - allowed:
            raise advisor.AdvisorError("task contains unsupported fields; do not include prompt text")
        tid = t.get("task_id")
        if not isinstance(tid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{5,127}", tid) or tid in by_id:
            raise advisor.AdvisorError("task IDs must be unique machine identifiers")
        by_id[tid] = t
        for key in ("task_family", "axes"):
            if key not in t:
                raise advisor.AdvisorError(f"task missing {key}")
        normalized_paths(t.get("write_paths", []))
        normalized_paths(t.get("read_paths", []))
        if t.get("retain_reason") is not None and t["retain_reason"] not in RETAIN_REASONS:
            raise advisor.AdvisorError("invalid retain_reason; keeping the Lead busy is not a cost reason")
        if "independent_review" in t and not isinstance(t["independent_review"], bool):
            raise advisor.AdvisorError("independent_review must be boolean")
        if t.get("batch_key") is not None and (not isinstance(t["batch_key"], str) or not ID.fullmatch(t["batch_key"])):
            raise advisor.AdvisorError("batch_key must be a non-sensitive machine label")
    completed = payload.get("completed_task_ids", [])
    if not isinstance(completed, list) or any(not isinstance(i, str) or i not in by_id for i in completed):
        raise advisor.AdvisorError("unknown completed task ID")
    completed = set(completed) | {tid for tid, task in by_id.items() if task.get("retain_reason") == "already_completed"}
    in_progress = payload.get("in_progress_task_ids", [])
    if not isinstance(in_progress, list) or any(not isinstance(i, str) or i not in by_id for i in in_progress) or len(in_progress) != len(set(in_progress)):
        raise advisor.AdvisorError("invalid in-progress task IDs")
    if completed.intersection(in_progress):
        raise advisor.AdvisorError("task cannot be completed and in progress")
    if in_progress and open_workers == 0:
        raise advisor.AdvisorError("in-progress tasks require the actual open-worker count")
    graph = {}
    for tid, t in by_id.items():
        deps = t.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or d not in by_id or d == tid for d in deps):
            raise advisor.AdvisorError("unknown or self dependency")
        graph[tid] = set(deps)
    visiting, visited = set(), set()
    def visit(tid):
        if tid in visiting:
            raise advisor.AdvisorError("dependency cycle")
        if tid in visited:
            return
        visiting.add(tid)
        for d in graph[tid]:
            visit(d)
        visiting.remove(tid)
        visited.add(tid)
    for tid in by_id:
        visit(tid)
    ancestor_cache = {}
    def ancestors(tid):
        if tid in ancestor_cache:
            return ancestor_cache[tid]
        result = set(graph[tid])
        for dep in graph[tid]:
            result.update(ancestors(dep))
        ancestor_cache[tid] = result
        return result
    ancestry = {tid: ancestors(tid) for tid in by_id}
    ownership = {
        tid: {key: normalized_paths(task.get(key, [])) for key in ("write_paths", "read_paths")}
        for tid, task in by_id.items()
    }

    def local_tool_candidate(tid):
        """Cheap read-only evidence work can stay in the Lead without a new model context."""
        task = by_id[tid]
        axes = task["axes"]
        return (
            tid not in completed
            and tid not in in_progress
            and not task.get("retain_reason")
            and not task.get("independent_review")
            and not ownership[tid]["write_paths"]
            and bool(ownership[tid]["read_paths"])
            and graph[tid].issubset(completed)
            and axes["task_scope"] != "micro"
            and axes["task_kind"] in ("scan", "verification", "leaf")
            and axes["reasoning_depth"] in ("shallow", "medium")
            and axes["verifiability"] == "yes"
            and axes["failure_cost"] != "high"
            and axes["context_volume"] != "high"
        )

    def has_local_tool_peer(tid):
        if not local_tool_candidate(tid):
            return False
        for peer_id in by_id:
            if peer_id == tid or not local_tool_candidate(peer_id):
                continue
            if peer_id in ancestry[tid] or tid in ancestry[peer_id]:
                continue
            if not conflict(ownership[tid], ownership[peer_id]):
                return True
        return False

    def has_independent_peer(tid):
        task = by_id[tid]
        if task["axes"]["task_scope"] == "micro" or task.get("retain_reason") or tid in completed or tid in in_progress:
            return False
        for peer_id, peer in by_id.items():
            if peer_id == tid or peer["axes"]["task_scope"] == "micro" or peer.get("retain_reason") or peer_id in completed or peer_id in in_progress:
                continue
            if peer_id in ancestry[tid] or tid in ancestry[peer_id]:
                continue
            if not conflict(ownership[tid], ownership[peer_id]):
                return True
        return False

    for tid, t in by_id.items():
        rec = advisor.recommend(task_family=t["task_family"], axes=t["axes"], lead_model=lead_model, lead_effort=lead_effort,
                                calibration=calibration if routing_mode == "adaptive" else "off", registry=registry, scope=scope)
        retained = t.get("retain_reason")
        decision, reason = rec["decision"], rec["selection_reason"]
        trigger = rec.get("delegation_trigger")
        lead_only_reason = rec.get("lead_only_reason")
        execution_shape, execution_reason = ("subagent", reason) if decision == "delegate" else ("local_serial", reason)
        if routing_mode == "luna_only" and rec["model"] != "gpt-5.6-luna":
            decision, reason, trigger, lead_only_reason = "lead_only", "luna_only capability boundary", None, "luna_only capability boundary"
            execution_shape, execution_reason = "local_serial", reason
        elif t.get("independent_review") and t["axes"]["task_scope"] != "micro" and rec.get("history_rule") != "verified-failure-exhausted":
            decision, reason, trigger, lead_only_reason = "delegate", "explicit bounded independent review", "independent_review", None
            execution_shape, execution_reason = "subagent", reason
        elif (
            has_local_tool_peer(tid)
            and rec["route_direction"] != "up"
            and rec.get("history_rule") not in ("verified-failure-escalation", "verified-failure-exhausted")
        ):
            reason = "independent read-only evidence can run as Lead parallel tools; Worker startup/context cost is unnecessary"
            decision, trigger, lead_only_reason = "lead_only", None, reason
            execution_shape, execution_reason = "local_parallel_tools", reason
        elif (
            decision == "lead_only"
            and rec["route_direction"] == "same"
            and t["axes"]["task_scope"] != "micro"
            and rec.get("history_rule") != "verified-failure-exhausted"
            and has_independent_peer(tid)
        ):
            decision, reason, trigger, lead_only_reason = (
                "delegate",
                "independent sibling can run in parallel; ownership benefit exceeds startup cost",
                "parallel_independent_sibling",
                None,
            )
            execution_shape, execution_reason = "subagent", reason
        if tid in in_progress:
            decision, reason, trigger, lead_only_reason = "wait", "already_running", None, None
            execution_shape, execution_reason = "subagent", reason
        elif retained or tid in completed:
            reason = retained or "already_completed"
            decision, trigger, lead_only_reason = "lead_only", None, reason
            execution_shape, execution_reason = "local_serial", reason
        elif decision == "delegate":
            execution_shape, execution_reason = "subagent", reason
        item = dict(
            task_id=tid,
            decision=decision,
            reason=reason,
            delegation_trigger=trigger,
            lead_only_reason=lead_only_reason,
            execution_shape=execution_shape,
            execution_reason=execution_reason,
            model=rec["model"],
            effort=rec["effort"],
            agent_profile=rec["agent_profile"],
            minimum_capability=rec["minimum_capability"],
            route_direction=rec["route_direction"],
            history_rule=rec["history_rule"],
        )
        decisions.append(item)
        if decision != "delegate":
            continue
        # Only explicit common context, identical family/axes/route, and no internal dependencies may batch.
        group = None
        if t.get("batch_key") and not t.get("independent_review"):
            group = next((g for g in groups if g["batch_key"] == t["batch_key"] and g["task_family"] == t["task_family"] and g["axes"] == t["axes"]
                          and (g["model"], g["effort"]) == (rec["model"], rec["effort"])
                          and set(g["depends_on"]) == graph[tid]
                          and not any(i in ancestry[tid] or tid in ancestry[i] for i in g["task_ids"])), None)
        if group is None:
            group = dict(worker_id=tid, task_ids=[], batch_key=t.get("batch_key") if not t.get("independent_review") else None,
                         task_family=t["task_family"], axes=t["axes"], model=rec["model"], effort=rec["effort"], agent_profile=rec["agent_profile"],
                         route_direction=rec["route_direction"], read_paths=[], write_paths=[], depends_on=[])
            groups.append(group)
        group["task_ids"].append(tid)
        group["read_paths"] += normalized_paths(t.get("read_paths", []))
        group["write_paths"] += normalized_paths(t.get("write_paths", []))
        group["depends_on"] = sorted(set(group["depends_on"]) | graph[tid])
        item["worker_id"] = group["worker_id"]
    # Retained/active ownership matters just as much as Worker-vs-Worker ownership.
    retained_work = [d["task_id"] for d in decisions if d["decision"] != "delegate" and d["task_id"] not in completed]
    def retained_conflict(group):
        for tid in retained_work:
            # An explicit dependency can order a future Lead action after this Worker.
            follows_worker = tid not in in_progress and any(i in ancestry[tid] for i in group["task_ids"])
            if not follows_worker and conflict(group, ownership[tid]):
                return True
        return False
    planned, remaining, waves = set(completed), list(groups), []
    while remaining:
        ready = [g for g in remaining if set(g["depends_on"]).issubset(planned) and not retained_conflict(g)]
        wave = []
        for g in ready:
            if len(wave) >= limit:
                break
            if g["route_direction"] == "up" and any(w["route_direction"] == "up" for w in wave):
                continue  # The one-expert default is not a one-Luna-per-wave restriction.
            if not any(conflict(g, w) for w in wave):
                wave.append(g)
        if not wave:
            break  # Requires retained Lead work; do not pretend prerequisites are finished.
        waves.append([g["worker_id"] for g in wave])
        for g in wave:
            planned.update(g["task_ids"])
            remaining.remove(g)
    now_ids = waves[0][:max(0, limit - open_workers)] if waves else []
    local_parallel = [d["task_id"] for d in decisions if d["decision"] == "lead_only" and d["execution_shape"] == "local_parallel_tools"]
    local_serial = [
        d["task_id"] for d in decisions
        if d["decision"] == "lead_only" and d["execution_shape"] == "local_serial" and d["reason"] != "already_completed"
    ]
    return dict(version=1, routing_mode=routing_mode, lead_model=lead_model, lead_effort=lead_effort,
                effective_wave_limit=limit, open_workers=open_workers, open_workers_semantics="pending_or_running_only", decisions=decisions, workers=groups,
                local_parallel_task_ids=local_parallel, local_serial_task_ids=local_serial,
                planned_waves=waves, ready_worker_ids=now_ids,
                blocked_worker_ids=[g["worker_id"] for g in remaining],
                instruction="Run local_parallel_task_ids with independent Lead-native tool concurrency; do not spawn Workers for them. Run local_serial_task_ids in the Lead. Preflight exact routes, authority and runtime status before SubAgents. open_workers counts PendingInit/Running only, never historical Completed agents. Spawn all ready independent Workers before waiting. If runtime returns an agent thread limit, refresh statuses before fallback; do not relabel it model overload. No spawn is performed by this planner.")
