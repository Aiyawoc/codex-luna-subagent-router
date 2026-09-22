"""Optional System-1 provider adapters. Fail closed to 'unavailable', never into production routing."""
from __future__ import annotations

import json
import math
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import outcome_store as store
import decision_state

PROVIDERS = ("off", "jev", "http", "jev_ask")
QUESTION_TYPES = ("choice", "score", "noul")
MAX_RESPONSE_BYTES = 1024 * 1024
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def _bounded_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1


def validate_questions(questions):
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 40:
        raise store.StoreError("questions must contain 1..40 typed entries")
    for name, question in questions.items():
        if not isinstance(name, str) or not name or not isinstance(question, dict):
            raise store.StoreError("invalid decision question")
        qtype = question.get("type")
        if qtype not in QUESTION_TYPES or not isinstance(question.get("instructions"), str):
            raise store.StoreError("invalid question type or instructions")
        criteria = question.get("criteria")
        if qtype == "choice" and (not isinstance(criteria, dict) or not criteria or any(not isinstance(k, str) or not isinstance(v, str) for k, v in criteria.items())):
            raise store.StoreError("choice questions require string criteria")
        if qtype == "score" and not isinstance(criteria, list):
            raise store.StoreError("score questions require list criteria")
    return questions


def _endpoint(value, provider):
    endpoint = value or (JEV_ENDPOINT if provider == "jev" else None)
    if not isinstance(endpoint, str):
        return None
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme == "https" and parsed.netloc:
        return endpoint
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return endpoint
    raise store.StoreError("decision endpoint must use HTTPS or loopback HTTP")


def _normalize_answer(question, answer):
    if not isinstance(answer, dict):
        raise store.StoreError("provider answer must be an object")
    qtype = question["type"]
    if answer.get("type") not in (None, qtype):
        raise store.StoreError("provider answer type mismatch")
    confidence = answer.get("confidence")
    if confidence is not None and not _bounded_number(confidence):
        raise store.StoreError("invalid answer confidence")
    result = {"type": qtype}
    if qtype == "choice":
        choice = answer.get("choice")
        if choice not in question["criteria"]:
            raise store.StoreError("provider returned an unknown choice")
        result["choice"] = choice
        probabilities = answer.get("probabilities")
        if probabilities is not None:
            if not isinstance(probabilities, dict) or set(probabilities) != set(question["criteria"]):
                raise store.StoreError("invalid choice probabilities")
            if any(not _bounded_number(v) for v in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.02:
                raise store.StoreError("invalid choice probability distribution")
            result["probabilities"] = probabilities
    elif qtype == "noul":
        value = answer.get("noul")
        if not _bounded_number(value):
            raise store.StoreError("invalid noul probability")
        result["noul"] = value
    else:
        value = answer.get("score")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise store.StoreError("invalid score answer")
        result["score"] = value
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _normalize(payload, questions, provider, latency_ms):
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise store.StoreError("invalid provider response")
    answers = payload["answers"]
    if set(answers) != set(questions):
        raise store.StoreError("provider response must answer the complete question set")
    normalized = {name: _normalize_answer(questions[name], answers[name]) for name in questions}
    usage = payload.get("usage")
    clean_usage = {}
    if isinstance(usage, dict):
        clean_usage = {k: v for k, v in usage.items() if isinstance(k, str) and type(v) is int and v >= 0}
    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or len(model) > 128):
        model = None
    return {
        "available": True,
        "provider": provider,
        "provider_model": model,
        "latency_ms": latency_ms,
        "answers": normalized,
        "usage": clean_usage,
    }


def evaluate(config, state, questions, *, opener=None):
    if not isinstance(config, dict):
        raise store.StoreError("decision provider config must be an object")
    provider = config.get("provider", "off")
    enabled = config.get("enabled", False)
    if type(enabled) is not bool or provider not in PROVIDERS:
        raise store.StoreError("invalid decision provider configuration")
    if not enabled or provider == "off":
        return {"available": False, "provider": provider, "reason": "disabled", "latency_ms": 0}
    state = decision_state.build(state)
    questions = validate_questions(questions)
    endpoint = _endpoint(config.get("endpoint"), provider)
    if endpoint is None:
        return {"available": False, "provider": provider, "reason": "missing_endpoint", "latency_ms": 0}
    timeout_ms = config.get("timeout_ms", 800)
    if type(timeout_ms) is not int or not 50 <= timeout_ms <= 15000:
        raise store.StoreError("timeout_ms must be 50..15000")
    env_name = config.get("api_key_env")
    if env_name is None and provider == "jev":
        env_name = "TYPESAFE_API_KEY"
    if env_name is not None and (not isinstance(env_name, str) or not env_name or len(env_name) > 128):
        raise store.StoreError("invalid api_key_env")
    key = os.environ.get(env_name) if env_name else None
    if env_name and not key:
        return {"available": False, "provider": provider, "reason": "missing_credential", "latency_ms": 0}
    body = {"state": state, "questions": questions}
    if provider == "jev":
        body["model"] = config.get("model", "jev-latest")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen
    started = time.monotonic()
    try:
        with open_fn(req, timeout=timeout_ms / 1000.0) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise store.StoreError("decision provider response too large")
            payload = json.loads(raw.decode("utf-8"))
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        return _normalize(payload, questions, provider, latency_ms)
    except urllib.error.HTTPError as exc:
        reason = f"http_{exc.code}" if exc.code in (401, 402, 403, 408, 429, 500, 502, 503, 504) else "http_error"
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        reason = "unavailable"
    except (OSError, UnicodeError, json.JSONDecodeError, store.StoreError, TypeError, ValueError):
        reason = "invalid_or_unavailable"
    return {"available": False, "provider": provider, "reason": reason,
            "latency_ms": max(0, int((time.monotonic() - started) * 1000))}
