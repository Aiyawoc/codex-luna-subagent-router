"""Optional, budgeted Shadow checkpoint attached to a successful CLI plan.

The deterministic planner finishes first. This module returns observation
metadata only, never model choices or provider answers to the execution path.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import decision_checkpoint
import decision_events as events
import decision_policy
import decision_provider
import decision_shadow
import decision_state
import outcome_store as store


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _context(payload, context):
    if not isinstance(context, dict) or set(context) - {"task_id", "state", "checkpoint"}:
        raise store.StoreError("invalid planner decision context")
    task = next((t for t in payload["tasks"] if t["task_id"] == context.get("task_id")), None)
    if task is None:
        raise store.StoreError("decision context must name one plan task")
    state = decision_state.build(context.get("state"))
    if state["task_family"] != task["task_family"]:
        raise store.StoreError("decision state task family mismatch")
    checkpoint = context.get("checkpoint")
    if checkpoint is None:
        checkpoint = {
            "task_scope": task["axes"]["task_scope"],
            "candidate_hypotheses": state["hypothesis_count"],
            "module_count": len(state.get("modules", [])),
            "entering_verification": state["stage"] == "verification",
        }
    if not isinstance(checkpoint, dict) or checkpoint.get("task_scope") != task["axes"]["task_scope"]:
        raise store.StoreError("checkpoint and planner scope disagree")
    # No provider-suggested lease is trusted as a verified cache lease.
    if checkpoint.get("valid_lease") is True:
        raise store.StoreError("automatic lease reuse is not implemented")
    if checkpoint.get("candidate_hypotheses", 0) != state["hypothesis_count"]:
        raise store.StoreError("checkpoint hypothesis evidence mismatch")
    if checkpoint.get("module_count", 0) != len(state.get("modules", [])):
        raise store.StoreError("checkpoint module evidence mismatch")
    return task, state, decision_checkpoint.evaluate(checkpoint)


def _request_size(engine, state):
    if engine.get("provider") == "openai_decisions":
        body = {
            "model": decision_provider.OPENAI_DECISIONS_MODEL,
            "input": json.dumps(state, ensure_ascii=False, separators=(",", ":")),
            "questions": decision_provider._official_questions(decision_policy.QUESTIONS),
        }
    else:
        body = {"state": state, "questions": decision_policy.QUESTIONS,
                "model": engine.get("model", "jev-latest")}
    return len(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def _isolated_provider(engine, state, questions):
    """Bound native credential/API failures without risking the Lead's plan."""
    start = time.monotonic()
    result = {"available": False, "provider": engine.get("provider"),
              "reason": "provider_process_failed", "latency_ms": 0}
    provider_config = {key: engine[key] for key in (
        "enabled", "mode", "provider", "model", "endpoint", "timeout_ms",
        "credential_source", "credential_scope", "api_key_env", "setup_completed",
    ) if key in engine}
    raw = json.dumps({"engine": provider_config, "state": state, "questions": questions},
                     ensure_ascii=False).encode("utf-8")
    if len(raw) > 65536:
        return dict(result, reason="invalid_or_unavailable")
    timeout = engine.get("timeout_ms", 1200 if engine.get("provider") == "openai_decisions" else 800)
    if type(timeout) is not int or not 50 <= timeout <= 15000:
        return dict(result, reason="invalid_or_unavailable")
    command = [sys.executable, "-I", "-S", "-B", "-X", "utf8",
               str(Path(__file__).with_name("decision_worker.py"))]
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # The extra second covers startup/credential lookup. It is a whole
        # child-process deadline, unlike the transport's socket timeout.
        stdout, _ = process.communicate(raw, timeout=timeout / 1000 + 1)
        if process.returncode == 0 and len(stdout) <= decision_provider.MAX_RESPONSE_BYTES:
            candidate = json.loads(stdout)
            if isinstance(candidate, dict) and type(candidate.get("available")) is bool:
                result = candidate
    except subprocess.TimeoutExpired:
        result["reason"] = "provider_deadline"
    except (OSError, ValueError, TypeError):
        pass
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
    result.setdefault("provider", engine.get("provider"))
    result["latency_ms"] = max(0, int((time.monotonic() - start) * 1000))
    return result


def observe(payload, context, output, config, scope, *, event_path=None,
            ledger=None, provider_evaluate=None, now=None, caller_disabled=False):
    """Best-effort observation: failures do not alter a validated plan.

    Existing enabled providers need an additional explicit
    automatic_checkpoints=true opt-in. An absent context or absent facts is
    observable as a skip, not filled with a fabricated evidence summary.
    """
    checkpoint_id = uuid.uuid4().hex
    plan_id = output["plan_id"]
    path = event_path or events.default_path()
    base = dict(checkpoint_id=checkpoint_id, plan_id=plan_id, scope=scope, now=now)
    response = dict(plan_id=plan_id, checkpoint_id=checkpoint_id,
                    origin="planner", production_effect="none")

    def skipped(reason):
        events.append(path, events.event(**base, state="skipped", reason=reason))
        return dict(response, status="skipped", reason=reason)

    try:
        events.append(path, events.event(**base, state="considered", reason="planner_entry"))
        if output.get("planning_observation_error") or not output.get("planning_observation_storage"):
            return skipped("planning_unavailable")
        engine = config.get("decision_engine", {})
        if not isinstance(engine, dict) or engine.get("enabled") is not True:
            return skipped("disabled")
        if caller_disabled or engine.get("automatic_checkpoints") is not True:
            return skipped("automatic_disabled")
        if engine.get("setup_completed") is not True:
            return skipped("explicit_setup_required")
        if engine.get("mode", "shadow") != "shadow":
            return skipped("invalid_mode")
        if engine.get("provider") not in set(decision_provider.PROVIDERS) - {"off"}:
            return skipped("invalid_config")
        try:
            policy = events.limits(engine)
        except (ValueError, TypeError):
            return skipped("invalid_config")
        if context is None:
            return skipped("missing_context")
        try:
            task, state, checkpoint = _context(payload, context)
        except (ValueError, TypeError, KeyError):
            return skipped("invalid_context")
        base["task_key"] = _hash([scope, task["task_id"]])
        inactive = set(payload.get("completed_task_ids", [])) | set(payload.get("in_progress_task_ids", []))
        if task["task_id"] in inactive or task.get("retain_reason") == "already_completed":
            return skipped("task_not_active")
        if task["axes"]["task_scope"] == "micro":
            return skipped("micro_task")
        if not state.get("facts") and not state.get("verification_summary"):
            return skipped("missing_grounded_evidence")
        if checkpoint["decision"] != "checkpoint_required":
            return skipped(checkpoint["reason_codes"][0])
        if _request_size(engine, state) > policy["max_request_bytes"]:
            return skipped("payload_budget")
        # Paths and prompt/state text are fingerprinted, never journaled. IDs
        # themselves are also hashed so two distinct tasks are not conflated.
        base["context_hash"] = _hash({
            "scope": scope, "task_id": task["task_id"], "axes": task["axes"],
            "state": state, "questions": decision_policy.QUESTIONS,
            "provider": engine["provider"], "model": engine.get("model"),
            "endpoint": engine.get("endpoint"),
        })
        reservation = events.event(**base, state="attempted", reason="checkpoint_required")
        denied = events.reserve(path, reservation, policy, now=now)
        if denied:
            return dict(response, status="skipped", reason=denied)
        try:
            result = decision_shadow.execute(
                state, engine, scope, checkpoint, ledger=ledger,
                provider_evaluate=provider_evaluate or _isolated_provider, checkpoint_id=checkpoint_id,
                correlation={"plan_id": plan_id, "task_key": base["task_key"],
                             "baseline_axes": dict(task["axes"])},
            )
        except Exception:
            # Python/provider/schema failures must not suppress the original
            # plan. Native process failure leaves the attempted event for audit.
            events.append(path, events.event(**base, state="unavailable", reason="provider_error"))
            return dict(response, status="unavailable", reason="provider_error")
        status = result["status"]
        events.append(path, events.event(**base, state=status,
                                        reason="provider_available" if status == "available" else "provider_unavailable"))
        # Deliberately do not expose semantic answers to the Lead's execution
        # plan. They remain in the correlated, metadata-only decision ledger.
        return dict(response, status=status, reason=result.get("reason"),
                    latency_ms=result["latency_ms"])
    except Exception:
        return dict(response, status="unavailable", reason="decision_storage_unavailable")
