"""Trace events: valid JSONL, hashed arguments, secrets redacted (D-15)."""

from __future__ import annotations

import json

import pytest

from src.trace import REDACTED, TraceWriter, args_hash, read_trace, redact

pytestmark = pytest.mark.fast


def test_redact_masks_sensitive_keys_recursively():
    value = {
        "api_key": "anything",
        "nested": {"authorization": "Bearer abcdefghijkl", "query": "remortgage"},
        "items": [{"password": "hunter2"}],
    }
    cleaned = redact(value)
    assert cleaned["api_key"] == REDACTED
    assert cleaned["nested"]["authorization"] == REDACTED
    assert cleaned["nested"]["query"] == "remortgage"
    assert cleaned["items"][0]["password"] == REDACTED


def test_redact_masks_key_shaped_values_even_under_innocent_keys():
    assert "nvapi-" not in redact({"note": "nvapi-abcdefghijklmnop"})
    assert "sk-" not in redact({"note": "sk-abcdefghijklmnop"})
    assert "Bearer" not in redact({"note": "Bearer abcdefghijklmnop"})


def test_args_hash_is_stable_and_redacted():
    first = args_hash({"query": "remortgage", "api_key": "nvapi-abcdefghijkl"})
    second = args_hash({"query": "remortgage", "api_key": "nvapi-abcdefghijkl"})
    changed = args_hash({"query": "remortgage", "api_key": "nvapi-zzzzzzzzzzzz"})
    assert first == second == changed  # the secret contributes nothing
    assert len(first) == 16


def test_emit_writes_one_sorted_json_line(tmp_path, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    path = tmp_path / "logs" / "trace.jsonl"
    trace = TraceWriter(path, "run-a")
    event = trace.emit(
        step=1,
        tool="audit_site",
        args={"url": "https://example.co.uk", "api_key": "nvapi-abcdefghijkl"},
        source="net",
        latency_ms=12.3456,
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed == event
    assert parsed["ts"] == "2026-11-16T09:00:00.000+00:00"
    assert parsed["run_id"] == "run-a"
    assert parsed["tool"] == "audit_site"
    assert parsed["latency_ms"] == 12.346
    assert parsed["args_hash"] == args_hash({"url": "https://example.co.uk", "api_key": "nvapi-abcdefghijkl"})
    assert "nvapi" not in lines[0]
    assert "https://example.co.uk" not in lines[0]  # args are hashed, not raw


def test_append_mode_preserves_previous_events(tmp_path, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    path = tmp_path / "trace.jsonl"
    trace = TraceWriter(path, "run-a")
    trace.emit(step=1, tool="one")
    trace.emit(step=2, tool="two")
    events = read_trace(path)
    assert [event["tool"] for event in events] == ["one", "two"]


def test_read_trace_missing_file_returns_empty(tmp_path):
    assert read_trace(tmp_path / "nope.jsonl") == []


def test_extra_fields_are_redacted_too(tmp_path):
    path = tmp_path / "trace.jsonl"
    TraceWriter(path, "run-a").emit(
        step=1,
        tool="llm",
        note="Bearer abcdefghijklmnop",
        api_key="nvapi-abcdefghijkl",
    )
    text = path.read_text(encoding="utf-8")
    assert "abcdefghijklmnop" not in text
    assert "nvapi" not in text
    assert REDACTED in text


def test_kind_and_status_are_recorded(tmp_path):
    path = tmp_path / "trace.jsonl"
    TraceWriter(path, "run-a").emit(
        step=2, tool="fetch_competitor", kind="robots_blocked", status="skipped"
    )
    event = read_trace(path)[0]
    assert event["kind"] == "robots_blocked"
    assert event["status"] == "skipped"
    assert event["source"] == "code"
    assert event["tokens_in"] == 0
