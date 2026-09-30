"""Sanitized OTLP trace summaries for Agents API shadow observability."""
from __future__ import annotations

from collections import Counter


class HostTraceError(ValueError):
    pass


def _nanos(value, field):
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or value < 0:
        raise HostTraceError(f"{field} must be a non-negative nanosecond value")
    return value


def _category(name):
    text = str(name or "").lower()
    if "agent" in text or "subagent" in text:
        return "agent"
    if "generation" in text or "response" in text or "model" in text:
        return "generation"
    if "tool" in text or "mcp" in text or "command" in text:
        return "tool"
    return "other"


def _status(span):
    status = span.get("status") or {}
    if not isinstance(status, dict):
        raise HostTraceError("span status must be an object")
    code = status.get("code", "STATUS_CODE_UNSET")
    if not isinstance(code, str) or len(code) > 64:
        raise HostTraceError("invalid span status code")
    return code


def _spans(trace):
    otlp = trace.get("otlp") if isinstance(trace, dict) else None
    resources = otlp.get("resourceSpans") if isinstance(otlp, dict) else None
    if not isinstance(resources, list):
        raise HostTraceError("trace must contain OTLP resourceSpans")
    result = []
    for resource in resources:
        scopes = resource.get("scopeSpans") if isinstance(resource, dict) else None
        if not isinstance(scopes, list):
            raise HostTraceError("resource span must contain scopeSpans")
        for scope in scopes:
            spans = scope.get("spans") if isinstance(scope, dict) else None
            if not isinstance(spans, list):
                raise HostTraceError("scope span must contain spans")
            for span in spans:
                if not isinstance(span, dict):
                    raise HostTraceError("OTLP span must be an object")
                start = _nanos(span.get("startTimeUnixNano"), "startTimeUnixNano")
                end = _nanos(span.get("endTimeUnixNano"), "endTimeUnixNano")
                if end < start:
                    raise HostTraceError("span end precedes start")
                result.append((start, end, _category(span.get("name")), _status(span)))
    return result


def summarize_trace_page(payload):
    """Return only aggregate timing/status metadata; discard OTLP attributes and IDs."""
    if not isinstance(payload, dict) or payload.get("object") != "list" or not isinstance(payload.get("data"), list):
        raise HostTraceError("invalid Agents API trace list")
    all_spans = []
    for trace in payload["data"]:
        all_spans.extend(_spans(trace))
    categories = Counter(category for _, _, category, _ in all_spans)
    statuses = Counter(status for _, _, _, status in all_spans)
    durations = [(end - start) / 1_000_000 for start, end, _, _ in all_spans]
    events = []
    for start, end, _, _ in all_spans:
        if end > start:
            events.append((start, 1))
            events.append((end, -1))
    active = peak = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return {
        "source": "agents_api_trace_otlp",
        "authoritative": False,
        "trace_count": len(payload["data"]),
        "span_count": len(all_spans),
        "span_categories": {key: int(categories.get(key, 0)) for key in ("agent", "generation", "tool", "other")},
        "span_statuses": dict(sorted(statuses.items())),
        "total_span_ms": round(sum(durations), 3),
        "max_span_ms": round(max(durations, default=0.0), 3),
        "peak_overlapping_spans": peak,
        "has_more": payload.get("has_more") is True,
        "last_id": payload.get("last_id") if isinstance(payload.get("last_id"), str) else None,
    }


def merge_summaries(summaries):
    categories = Counter()
    statuses = Counter()
    result = {
        "source": "agents_api_trace_otlp",
        "authoritative": False,
        "pages_read": len(summaries),
        "trace_count": 0,
        "span_count": 0,
        "total_span_ms": 0.0,
        "max_span_ms": 0.0,
        "max_page_peak_overlapping_spans": 0,
    }
    for summary in summaries:
        result["trace_count"] += summary["trace_count"]
        result["span_count"] += summary["span_count"]
        result["total_span_ms"] += summary["total_span_ms"]
        result["max_span_ms"] = max(result["max_span_ms"], summary["max_span_ms"])
        result["max_page_peak_overlapping_spans"] = max(
            result["max_page_peak_overlapping_spans"], summary["peak_overlapping_spans"]
        )
        categories.update(summary["span_categories"])
        statuses.update(summary["span_statuses"])
    result["total_span_ms"] = round(result["total_span_ms"], 3)
    result["span_categories"] = {key: int(categories.get(key, 0)) for key in ("agent", "generation", "tool", "other")}
    result["span_statuses"] = dict(sorted(statuses.items()))
    return result
