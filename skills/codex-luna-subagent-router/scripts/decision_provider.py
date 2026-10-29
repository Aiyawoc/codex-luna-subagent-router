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
import decision_credentials
import decision_state

PROVIDERS = ("off", "jev", "http", "jev_ask", "openai_decisions")
QUESTION_TYPES = ("choice", "score", "noul")
MAX_RESPONSE_BYTES = 1024 * 1024
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
OPENAI_DECISIONS_ENDPOINT = "https://api.openai.com/v1/decisions"
OPENAI_DECISIONS_MODEL = "gpt-6-luna"


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


def _official_questions(questions):
    """Translate the Router's historical typed-policy schema into GA Decisions."""
    translated = []
    for name, question in questions.items():
        qtype = question["type"]
        item = dict(name=name, instructions=question["instructions"])
        if qtype == "choice":
            choices = question["criteria"]
            if not 2 <= len(choices) <= 255:
                raise store.StoreError("official choice needs 2..255 options")
            item.update(type="choice", choices=[
                dict(value=value, description=description)
                for value, description in choices.items()
            ])
        elif qtype == "noul":
            item["type"] = "predicate"
        else:
            criteria = question["criteria"]
            if not 2 <= len(criteria) <= 10:
                raise store.StoreError("official score needs 2..10 ordered levels")
            levels = []
            for level in criteria:
                if isinstance(level, str):
                    label, description = level, level
                elif isinstance(level, dict) and set(level) == {"label", "description"}:
                    label, description = level["label"], level["description"]
                else:
                    raise store.StoreError("invalid official score level")
                if not isinstance(label, str) or not label or not isinstance(description, str):
                    raise store.StoreError("invalid official score level")
                levels.append(dict(label=label, description=description))
            if len({level["label"] for level in levels}) != len(levels):
                raise store.StoreError("duplicate official score level")
            item.update(type="score", levels=levels)
        translated.append(item)
    return translated


def _official_answers(payload, questions):
    """Normalize exact request/response identity, not best-effort partial answers."""
    if not isinstance(payload, dict) or payload.get("model") != OPENAI_DECISIONS_MODEL:
        raise store.StoreError("official decision returned unexpected model")
    rows = payload.get("answers")
    if not isinstance(rows, list) or len(rows) != len(questions):
        raise store.StoreError("official decision answer count mismatch")
    answers = {}
    for row in rows:
        if not isinstance(row, dict):
            raise store.StoreError("invalid official decision answer")
        name = row.get("name")
        if not isinstance(name, str) or name not in questions or name in answers:
            raise store.StoreError("official decision answer identity mismatch")
        if row.get("type") == "refusal":
            raise store.StoreError("official decision refused an answer")
        expected = questions[name]["type"]
        answer = {}
        if expected == "noul" and row.get("type") == "predicate":
            answer = dict(type="noul", noul=row.get("probability"))
        elif expected == "choice" and row.get("type") == "choice":
            answer = dict(type="choice", choice=row.get("choice"),
                          confidence=row.get("confidence"))
            distribution = row.get("probabilities")
            if distribution is not None:
                if not isinstance(distribution, list) or len(distribution) != len(questions[name]["criteria"]):
                    raise store.StoreError("official choice probability set mismatch")
                probabilities = {}
                for item in distribution:
                    if not isinstance(item, dict) or not isinstance(item.get("value"), str):
                        raise store.StoreError("invalid official choice distribution")
                    value = item["value"]
                    if value in probabilities:
                        raise store.StoreError("duplicate official choice probability")
                    probabilities[value] = item.get("probability")
                answer["probabilities"] = probabilities
        elif expected == "score" and row.get("type") == "score":
            score = row.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= len(questions[name]["criteria"])-1:
                raise store.StoreError("official score out of range")
            answer = dict(type="score", score=score, confidence=row.get("confidence"))
            distribution = row.get("probabilities")
            if distribution is not None:
                expected_levels = _official_questions({name: questions[name]})[0]["levels"]
                if not isinstance(distribution, list) or len(distribution) != len(expected_levels):
                    raise store.StoreError("official score probability set mismatch")
                seen = set()
                total = 0
                for item in distribution:
                    if not isinstance(item, dict) or type(item.get("value")) is not int:
                        raise store.StoreError("invalid official score distribution")
                    index = item["value"]
                    if index < 0 or index >= len(expected_levels) or index in seen:
                        raise store.StoreError("invalid official score level")
                    if item.get("label") != expected_levels[index]["label"] or not _bounded_number(item.get("probability")):
                        raise store.StoreError("invalid official score probability")
                    total += item["probability"]
                    seen.add(index)
                if len(seen) != len(expected_levels) or abs(total-1) > 0.02:
                    raise store.StoreError("invalid official score distribution total")
        else:
            raise store.StoreError("official decision answer type mismatch")
        answers[name] = answer
    if set(answers) != set(questions):
        raise store.StoreError("official decision missing answers")
    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        raise store.StoreError("invalid official decision usage")
    clean = {key: value for key, value in usage.items()
             if key in ("input_tokens", "output_tokens", "total_tokens")
             and type(value) is int and value >= 0}
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        for key in ("cached_tokens", "cache_write_tokens"):
            value = details.get(key)
            if type(value) is int and value >= 0:
                clean[key] = value
    return dict(model=payload["model"], answers=answers, usage=clean)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send a provider credential to a redirected URL.
        return None


def _official_evaluate(config, state, questions, *, opener=None):
    started = time.monotonic()
    if config.get("setup_completed") is not True:
        # Older Router builds advertised this name as a network-inert
        # placeholder. Never silently convert such a config into paid calls.
        return dict(available=False, provider="openai_decisions",
                    reason="explicit_setup_required", latency_ms=0)
    if config.get("model", OPENAI_DECISIONS_MODEL) != OPENAI_DECISIONS_MODEL:
        return dict(available=False, provider="openai_decisions", reason="unsupported_model", latency_ms=0)
    if config.get("endpoint") not in (None, OPENAI_DECISIONS_ENDPOINT):
        return dict(available=False, provider="openai_decisions", reason="invalid_endpoint", latency_ms=0)
    timeout_ms = config.get("timeout_ms", 1200)
    if type(timeout_ms) is not int or not 50 <= timeout_ms <= 15000:
        raise store.StoreError("timeout_ms must be 50..15000")
    try:
        state = decision_state.build(state)
        questions = validate_questions(questions)
        wire = _official_questions(questions)
        key = decision_credentials.resolve(config, "openai_decisions")
        if not key:
            return dict(available=False, provider="openai_decisions",
                        reason="missing_credential", latency_ms=0)
        body = dict(model=OPENAI_DECISIONS_MODEL,
                    input=json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                    questions=wire)
        req = urllib.request.Request(
            OPENAI_DECISIONS_ENDPOINT,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        # The real path rejects redirects; tests may inject their own transport.
        open_fn = opener or urllib.request.build_opener(_NoRedirect).open
        with open_fn(req, timeout=timeout_ms/1000) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise store.StoreError("official decision response too large")
            payload = json.loads(raw.decode("utf-8"))
        normalized = _official_answers(payload, questions)
        return _normalize(normalized, questions, "openai_decisions",
                          max(0, int((time.monotonic()-started)*1000)))
    except urllib.error.HTTPError as exc:
        reason = f"http_{exc.code}" if exc.code in (401, 402, 403, 408, 429, 500, 502, 503, 504) else "http_error"
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        reason = "unavailable"
    except (OSError, UnicodeError, json.JSONDecodeError, store.StoreError,
            decision_credentials.CredentialError, TypeError, ValueError):
        reason = "invalid_or_unavailable"
    return dict(available=False, provider="openai_decisions", reason=reason,
                latency_ms=max(0, int((time.monotonic()-started)*1000)))


def evaluate(config, state, questions, *, opener=None):
    if not isinstance(config, dict):
        raise store.StoreError("decision provider config must be an object")
    provider = config.get("provider", "off")
    enabled = config.get("enabled", False)
    if type(enabled) is not bool or provider not in PROVIDERS:
        raise store.StoreError("invalid decision provider configuration")
    if not enabled or provider == "off":
        return {"available": False, "provider": provider, "reason": "disabled", "latency_ms": 0}
    if provider == "openai_decisions":
        return _official_evaluate(config, state, questions, opener=opener)
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
    if env_name is not None and (
            not isinstance(env_name, str) or
            not decision_credentials.ENV_NAME.fullmatch(env_name)):
        raise store.StoreError("invalid api_key_env")
    key = decision_credentials.resolve(config, provider)
    requires_credential = (
        config.get("credential_source") == "keychain" or
        (config.get("credential_source") != "none" and env_name is not None)
    )
    if requires_credential and not key:
        return {"available": False, "provider": provider, "reason": "missing_credential", "latency_ms": 0}
    body = {"state": state, "questions": questions}
    if provider == "jev":
        body["model"] = config.get("model", "jev-latest")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    open_fn = opener or urllib.request.build_opener(_NoRedirect).open
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
