from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_trace  # noqa: E402


def span(name, start, end, status="STATUS_CODE_OK", **extra):
    return {
        "name": name,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "status": {"code": status, "message": "private status details"},
        "attributes": [{"key": "private.prompt", "value": {"stringValue": "do not retain"}}],
        **extra,
    }


def page(spans, *, has_more=False, last_id=None):
    return {
        "object": "list",
        "data": [{
            "id": "trace_private_id",
            "otlp": {"resourceSpans": [{
                "resource": {"attributes": [{"key": "private", "value": {"stringValue": "discard"}}]},
                "scopeSpans": [{"scope": {"name": "private.scope"}, "spans": spans}],
            }]},
        }],
        "has_more": has_more,
        "last_id": last_id,
    }


class HostTraceTests(unittest.TestCase):
    def test_summary_keeps_only_aggregate_timing_and_status(self):
        payload = page([
            span("agent.run", 0, 10_000_000),
            span("tool.call", 2_000_000, 7_000_000),
            span("response.generation", 7_000_000, 15_000_000),
            span("misc", 15_000_000, 16_000_000, "STATUS_CODE_ERROR"),
        ])
        result = host_trace.summarize_trace_page(payload)
        self.assertEqual(result["trace_count"], 1)
        self.assertEqual(result["span_count"], 4)
        self.assertEqual(result["span_categories"], {"agent": 1, "generation": 1, "tool": 1, "other": 1})
        self.assertEqual(result["span_statuses"], {"STATUS_CODE_ERROR": 1, "STATUS_CODE_OK": 3})
        self.assertEqual(result["total_span_ms"], 24.0)
        self.assertEqual(result["max_span_ms"], 10.0)
        self.assertEqual(result["peak_overlapping_spans"], 2)
        text = repr(result)
        self.assertNotIn("private.prompt", text)
        self.assertNotIn("do not retain", text)
        self.assertNotIn("trace_private_id", text)

    def test_touching_spans_do_not_count_as_overlap(self):
        result = host_trace.summarize_trace_page(page([
            span("tool.a", 0, 10),
            span("tool.b", 10, 20),
        ]))
        self.assertEqual(result["peak_overlapping_spans"], 1)

    def test_invalid_span_boundary_is_rejected(self):
        with self.assertRaisesRegex(host_trace.HostTraceError, "end precedes start"):
            host_trace.summarize_trace_page(page([span("agent.run", 10, 5)]))

    def test_merge_pages_preserves_only_aggregates(self):
        first = host_trace.summarize_trace_page(page([span("agent.run", 0, 1_000_000)], has_more=True, last_id="tr_1"))
        second = host_trace.summarize_trace_page(page([span("tool.call", 0, 2_000_000)]))
        merged = host_trace.merge_summaries([first, second])
        self.assertEqual(merged["pages_read"], 2)
        self.assertEqual(merged["trace_count"], 2)
        self.assertEqual(merged["span_count"], 2)
        self.assertEqual(merged["total_span_ms"], 3.0)
        self.assertEqual(merged["max_span_ms"], 2.0)
        self.assertEqual(merged["span_categories"]["agent"], 1)
        self.assertEqual(merged["span_categories"]["tool"], 1)


if __name__ == "__main__":
    unittest.main()
