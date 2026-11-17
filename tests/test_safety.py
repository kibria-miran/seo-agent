"""D-15 safety invariants: writes only under out/ and logs/, GET-only HTTP."""

from __future__ import annotations

import json

import pytest
import requests
from conftest import assert_write_paths_under, fake_http_get_only

from src import config
from src.pipeline import load_profile, run_deterministic
from src.trace import TraceWriter, read_trace

pytestmark = pytest.mark.fast

FIXTURE = config.FIXTURES_DIR / "own_site_audit.json"


@pytest.fixture
def profile():
    return load_profile(config.PROFILES_DIR / "site.json")


def test_pipeline_writes_only_under_out_and_logs(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    out_root = tmp_path / "out"
    with assert_write_paths_under(tmp_path, allowed=("out/", "logs/")) as written:
        run_deterministic(
            profile,
            fixture_path=FIXTURE,
            run_id="run-safe",
            db_path=tmp_path / "data" / "seo.db",
            out_root=out_root,
        )

    relative = sorted(
        str(path).split(str(tmp_path) + "/", 1)[-1] for path in written
    )
    assert "out/run-safe/report.md" in relative
    assert "out/run-safe/backlog.json" in relative
    assert "logs/trace.jsonl" in relative
    assert all(part in {"out", "logs"} for part in (item.split("/")[0] for item in relative))


def test_write_guard_rejects_a_write_outside_the_allowlist(tmp_path):
    with pytest.raises(pytest.fail.Exception), assert_write_paths_under(
        tmp_path, allowed=("out/", "logs/")
    ):
        (tmp_path / "secrets").mkdir()
        (tmp_path / "secrets" / "key.txt").write_text("no", encoding="utf-8")


def test_get_only_guard_allows_get_and_the_llm_post(monkeypatch):
    def fake_request(self, method, url, *args, **kwargs):
        return {"method": method, "url": url}

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    with fake_http_get_only() as calls:
        requests.get("https://example.co.uk/page", timeout=1)
        requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            json={"messages": []},
            timeout=1,
        )
    assert [method for method, _ in calls] == ["GET", "POST"]


@pytest.mark.parametrize("method", ["delete", "put", "patch", "head"])
def test_get_only_guard_rejects_other_methods(monkeypatch, method):
    def fake_request(self, request_method, url, *args, **kwargs):
        return {"method": request_method, "url": url}

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    with fake_http_get_only(), pytest.raises(AssertionError, match="not allowed"):
        getattr(requests, method)("https://example.co.uk/page", timeout=1)


def test_get_only_guard_rejects_post_to_a_non_llm_host(monkeypatch):
    def fake_request(self, request_method, url, *args, **kwargs):
        return {"method": request_method, "url": url}

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    with fake_http_get_only(), pytest.raises(AssertionError, match="not allowed"):
        requests.post("https://example.co.uk/collect", json={}, timeout=1)


def test_fixture_pipeline_issues_zero_http_calls(tmp_path, profile):
    with fake_http_get_only() as calls:
        run_deterministic(
            profile,
            fixture_path=FIXTURE,
            run_id="run-no-http",
            db_path=tmp_path / "data" / "seo.db",
            out_root=tmp_path / "out",
        )
    assert calls == []


def test_trace_contains_no_api_key(tmp_path, profile):
    run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-trace",
        db_path=tmp_path / "data" / "seo.db",
        out_root=tmp_path / "out",
    )
    trace_path = tmp_path / "logs" / "trace.jsonl"
    events = read_trace(trace_path)
    assert [event["tool"] for event in events][-1] == "run_end"
    text = trace_path.read_text(encoding="utf-8")
    assert "nvapi-" not in text
    assert "NVIDIA_API_KEY" not in text
    assert "authorization" not in text.casefold()
    for event in events:
        assert "args" not in event


def test_trace_redacts_a_planted_secret_under_a_benign_key(tmp_path):
    path = tmp_path / "logs" / "trace.jsonl"
    TraceWriter(path, "run-secret").emit(
        step=1,
        tool="llm",
        args={"query": "nvapi-abcdefghijklmnop"},
    )
    text = path.read_text(encoding="utf-8")
    assert "nvapi-abcdefghijklmnop" not in text
    assert "args_hash" in json.loads(text)  # the line is still valid JSON
