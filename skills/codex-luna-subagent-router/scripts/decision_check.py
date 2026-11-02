#!/usr/bin/env python3
"""Read-only decision setup/context preflight; opt-in credential check, never API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import decision_credentials
import decision_diagnostics
import decision_events
import decision_plan
import decision_validation
import outcome_store as store


def inspect(engine, request=None, *, check_credential=False):
    errors = []
    if not isinstance(engine, dict):
        engine = {}
    expected = {"enabled": True, "setup_completed": True, "mode": "shadow"}
    for name, value in expected.items():
        if engine.get(name) != value or (type(value) is bool and type(engine.get(name)) is not bool):
            errors.append({"code": "configuration_incomplete", "path": "/decision_engine/" + name})
    provider = engine.get("provider")
    if provider not in ("openai_decisions", "jev", "jev_ask", "http"):
        errors.append({"code": "invalid_provider", "path": "/decision_engine/provider"})
    if provider == "openai_decisions":
        if engine.get("model", "gpt-6-luna") != "gpt-6-luna":
            errors.append({"code": "invalid_model", "path": "/decision_engine/model"})
        if engine.get("endpoint") not in (None, "https://api.openai.com/v1/decisions"):
            errors.append({"code": "invalid_endpoint", "path": "/decision_engine/endpoint"})
    source = engine.get("credential_source", "env")
    if source == "keychain" and (not decision_credentials.supported() or not isinstance(engine.get("credential_scope"), str) or not engine.get("credential_scope")):
        errors.append({"code": "invalid_credential_reference", "path": "/decision_engine/credential_scope"})
    elif source == "env":
        name = engine.get("api_key_env") or ("OPENAI_API_KEY" if provider == "openai_decisions" else "TYPESAFE_API_KEY" if provider == "jev" else "")
        if not isinstance(name, str) or not decision_credentials.ENV_NAME.fullmatch(name):
            errors.append({"code": "invalid_env_reference", "path": "/decision_engine/api_key_env"})
    elif source not in ("keychain", "none") or (source == "none" and provider in ("openai_decisions", "jev")):
        errors.append({"code": "invalid_credential_source", "path": "/decision_engine/credential_source"})
    policy = None
    try:
        policy = decision_diagnostics.budgets(engine)
        decision_events.limits(engine)
    except (ValueError, TypeError):
        errors.append({"code": "invalid_limits", "path": "/decision_engine"})
    result = {
        "configuration_status": "valid" if not errors else "invalid",
        "provider": provider if provider in ("openai_decisions", "jev", "jev_ask", "http") else "invalid",
        "model": "gpt-6-luna" if provider == "openai_decisions" and engine.get("model", "gpt-6-luna") == "gpt-6-luna" else "not_verified",
        "automatic_checkpoints": engine.get("automatic_checkpoints") is True,
        "credential_status": "not_checked", "api_status": "not_tested", "api_called": False,
        "credential_source": source if source in ("keychain", "env", "none") else "invalid",
        "timeout_budgets": policy, "configuration_errors": errors,
        "context_status": "not_supplied", "context_errors": [],
        "dynamic_admission": "not_checked", "production_effect": "none",
    }
    if request is not None:
        context = request.get("decision_context") if isinstance(request, dict) else None
        payload = {k: v for k, v in request.items() if k != "decision_context"} if isinstance(request, dict) else {}
        context_errors = decision_validation.validate_context(payload, context)
        result.update(context_status="invalid" if context_errors else "valid", context_errors=context_errors)
        if not context_errors:
            _, state, checkpoint = decision_plan._context(payload, context)
            result["checkpoint"] = checkpoint
            try:
                size = decision_plan._request_size(engine, state)
                result["serialized_request_bytes"] = size
                if size > decision_events.limits(engine)["max_request_bytes"]:
                    result["context_status"] = "invalid"
                    result["context_errors"] = [{"code": "payload_budget", "path": "/decision_context"}]
            except (ValueError, TypeError, KeyError):
                result["context_status"] = "invalid"
    if check_credential and not errors:
        checked = decision_plan._isolated_provider(engine, {}, {}, credential_only=True)
        result["credential_status"] = "readable" if checked.get("available") else checked.get("reason", "unavailable")
        result["credential_diagnostics"] = checked.get("diagnostics")
    result["status"] = "valid" if not errors and result["context_status"] != "invalid" and result["credential_status"] in ("not_checked", "readable") else "blocked"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, nargs="?")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--global-scope", action="store_true")
    group.add_argument("--project-root")
    parser.add_argument("--check-credential", action="store_true",
                        help="Read only configured credential in a bounded noninteractive child; no API")
    args = parser.parse_args(argv)
    try:
        scope, root = store.resolve_scope(args.project_root, args.global_scope)
        request = None
        if args.request:
            with args.request.open("rb") as handle:
                raw = handle.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("request too large")
            request = json.loads(raw.decode("utf-8"))
        result = inspect(store.effective_config(root).get("decision_engine", {}), request,
                         check_credential=args.check_credential)
        result["scope_id"] = scope
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "valid" else 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "blocked", "code": "configuration_or_request_unreadable",
                          "api_called": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
