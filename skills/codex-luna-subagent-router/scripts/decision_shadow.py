#!/usr/bin/env python3
"""Run the optional grounded Decision Engine in Shadow mode; never mutate the production plan."""
from __future__ import annotations

import argparse
import json
import math
import uuid
from pathlib import Path

import decision_checkpoint
import decision_policy
import decision_provider
import decision_state
import decision_store
import outcome_store as store


def _answer_summary(answers):
    result = {}
    confidences = []
    for name, answer in answers.items():
        if "choice" in answer:
            result[name] = answer["choice"]
        elif "noul" in answer:
            result[name] = answer["noul"]
        elif "score" in answer:
            result[name] = answer["score"]
        confidence = answer.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence):
            confidences.append(confidence)
    return result, min(confidences) if confidences else None


def run(request, *, root=None, global_scope=False, ledger=None, provider_evaluate=None):
    if not isinstance(request, dict) or set(request) - {"state", "checkpoint"}:
        raise store.StoreError("shadow request must contain only state and optional checkpoint")
    state = decision_state.build(request.get("state"))
    checkpoint = request.get("checkpoint")
    checkpoint_result = decision_checkpoint.evaluate(checkpoint) if checkpoint is not None else {
        "decision": "checkpoint_required", "reason_codes": ["explicit_shadow_request"]
    }
    if checkpoint_result["decision"] != "checkpoint_required":
        return {"status": "skipped", "checkpoint": checkpoint_result, "production_effect": "none"}
    scope, resolved_root = store.resolve_scope(root, global_scope)
    config = store.effective_config(resolved_root)
    engine = config.get("decision_engine", {})
    if not isinstance(engine, dict) or engine.get("enabled") is not True:
        return {"status": "disabled", "checkpoint": checkpoint_result, "production_effect": "none"}
    if engine.get("mode", "shadow") != "shadow":
        raise store.StoreError("v2.7.0 supports decision_engine mode=shadow only")
    evaluate = provider_evaluate or decision_provider.evaluate
    result = evaluate(engine, state, decision_policy.QUESTIONS)
    checkpoint_id = uuid.uuid4().hex
    answers, confidence, lease = {}, None, None
    status = "available" if result.get("available") is True else "unavailable"
    if status == "available":
        answers, confidence = _answer_summary(result["answers"])
        lease = answers.get("decision_lease")
    row = decision_store.append(ledger or decision_store.default_path(), {
        "checkpoint_id": checkpoint_id,
        "scope_id": scope,
        "task_family": state["task_family"],
        "provider": result.get("provider", engine.get("provider", "off")),
        "provider_model": result.get("provider_model"),
        "status": status,
        "reason": result.get("reason"),
        "latency_ms": int(result.get("latency_ms", 0)),
        "confidence": confidence,
        "lease": lease,
        "answers": answers,
    })
    return {
        "status": status,
        "checkpoint": checkpoint_result,
        "checkpoint_id": checkpoint_id,
        "provider": row["provider"],
        "provider_model": row["provider_model"],
        "latency_ms": row["latency_ms"],
        "confidence": row["confidence"],
        "lease": row["lease"],
        "answers": answers,
        "production_effect": "none",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--ledger", type=Path)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--project-root")
    scope.add_argument("--global-scope", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = args.request.read_bytes()
        if len(raw) > 64 * 1024:
            raise store.StoreError("shadow request exceeds read budget")
        request = json.loads(raw.decode("utf-8"))
        output = run(request, root=args.project_root, global_scope=args.global_scope, ledger=args.ledger)
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: decision shadow unavailable: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
