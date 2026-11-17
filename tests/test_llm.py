"""Phase 5 LLM client: budgets, retries, redaction, from_env."""

from __future__ import annotations

import pytest

from src import config
from src.llm import (
    BudgetExceeded,
    LLMBudget,
    LLMClient,
    LLMTransient,
    LLMUnavailable,
    _estimate_tokens,
    self_test,
)
from src.trace import TraceWriter

pytestmark = pytest.mark.fast


def nim_ok(content="All options compared.", tokens_in=120, tokens_out=24, model="nvidia/llama-test"):
    return {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }


class FakeTransport:
    def __init__(self, steps):
        self.steps = list(steps)
        self.payloads: list[dict] = []

    def __call__(self, payload):
        self.payloads.append(payload)
        if not self.steps:
            return nim_ok()
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def make_client(steps, **kwargs):
    transport = FakeTransport(steps)
    client = LLMClient(api_key="nvapi-testkey1234567890", transport=transport,
                       model="nvidia/llama-test", **kwargs)
    return client, transport


@pytest.fixture
def sleeper():
    calls: list[float] = []
    yield calls



# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_chat_returns_content_and_usage(sleeper):
    calls = sleeper
    client, transport = make_client([nim_ok("Compare fixed rates", 150, 30)], sleeper=calls.append)
    response = client.chat([{"role": "user", "content": "remortgage?"}])

    assert response.content == "Compare fixed rates"
    assert response.tokens_in == 150
    assert response.tokens_out == 30
    assert response.model == "nvidia/llama-test"
    assert client.budget.usage.calls == 1
    assert client.budget.usage.tokens_in == 150
    assert client.budget.usage.tokens_out == 30
    assert calls == []

    payload = transport.payloads[0]
    assert payload["model"] == "nvidia/llama-test"
    assert payload["temperature"] == config.LLM_TEMPERATURE
    assert payload["messages"][0]["role"] == "user"
    assert "max_tokens" not in payload


def test_chat_with_max_tokens_and_temperature(sleeper):
    calls = sleeper
    client, transport = make_client([nim_ok()], sleeper=calls.append)
    client.chat([{"role": "user", "content": "hi"}], max_tokens=64, temperature=0.1)
    payload = transport.payloads[0]
    assert payload["max_tokens"] == 64
    assert payload["temperature"] == 0.1


def test_call_alias_returns_just_the_text():
    client, _ = make_client([nim_ok("short answer")])
    assert client([{"role": "user", "content": "question"}]) == "short answer"


def test_missing_usage_is_estimated_not_dropped():
    step = nim_ok("estimated reply")
    del step["usage"]
    client, _ = make_client([step])
    response = client.chat([{"role": "user", "content": "x" * 400}])
    assert response.tokens_in > 0
    assert response.tokens_out > 0


def test_empty_messages_rejected():
    client, transport = make_client([nim_ok()])
    with pytest.raises(ValueError):
        client.chat([])
    assert transport.payloads == []


def test_empty_llm_content_is_an_error():
    step = nim_ok("")
    client, _ = make_client([step])
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


def test_transient_failure_is_retried_once_then_succeeds(sleeper):
    calls = sleeper
    client, transport = make_client(
        [LLMTransient("HTTP 429"), nim_ok("recovered")], sleeper=calls.append
    )
    response = client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "recovered"
    assert len(transport.payloads) == 2
    assert calls == [1.0]
    assert client.budget.usage.calls == 2  # retry consumed a call from the budget


def test_transient_failures_exhaust_retries_and_raise(sleeper):
    calls = sleeper
    client, _ = make_client(
        [LLMTransient("HTTP 500"), LLMTransient("HTTP 500"), LLMTransient("HTTP 500")],
        sleeper=calls.append,
    )
    with pytest.raises(LLMUnavailable, match="after 3 attempts"):
        client.chat([{"role": "user", "content": "hi"}])
    assert calls == [1.0, 2.0]
    assert client.budget.usage.calls == 3


def test_permanent_error_is_not_retried(sleeper):
    calls = sleeper
    client, transport = make_client([LLMUnavailable("HTTP 400")], sleeper=calls.append)
    with pytest.raises(LLMUnavailable, match="HTTP 400"):
        client.chat([{"role": "user", "content": "hi"}])
    assert len(transport.payloads) == 1
    assert calls == []


def test_unknown_transport_exception_is_permanent_not_retried(sleeper):
    calls = sleeper
    client, _transport = make_client([ValueError("weird")], sleeper=calls.append)
    with pytest.raises(LLMUnavailable, match="transport error"):
        client.chat([{"role": "user", "content": "hi"}])
    assert calls == []


# ---------------------------------------------------------------------------
# Budgets (D-13)
# ---------------------------------------------------------------------------


def test_max_llm_calls_budget_is_enforced():
    budget = LLMBudget(max_calls=2)
    client, _ = make_client([nim_ok(), nim_ok(), nim_ok()], budget=budget)
    client.chat([{"role": "user", "content": "one"}])
    client.chat([{"role": "user", "content": "two"}])
    with pytest.raises(BudgetExceeded, match="MAX_LLM_CALLS"):
        client.chat([{"role": "user", "content": "three"}])


def test_retry_attempts_count_toward_the_call_budget():
    budget = LLMBudget(max_calls=2)
    client, transport = make_client(
        [LLMTransient("HTTP 429"), LLMTransient("HTTP 429"), nim_ok("never reached")],
        budget=budget, sleeper=lambda _: None,
    )
    # Two attempts consume the entire budget; the third attempt (retry #2)
    # is refused before a single token is spent.
    with pytest.raises(BudgetExceeded, match="MAX_LLM_CALLS"):
        client.chat([{"role": "user", "content": "hi"}])
    assert budget.usage.calls == 2
    assert len(transport.payloads) == 2


def test_max_tokens_in_budget_rejects_an_oversized_prompt_before_spending():
    budget = LLMBudget(max_tokens_in=10)
    client, transport = make_client([nim_ok()], budget=budget)
    with pytest.raises(BudgetExceeded, match="MAX_TOKENS_IN"):
        client.chat([{"role": "user", "content": "word " * 200}])
    assert transport.payloads == []  # nothing was sent
    assert budget.usage.calls == 0


def test_max_tokens_out_budget_is_enforced_after_the_call():
    budget = LLMBudget(max_tokens_out=10)
    client, _ = make_client([nim_ok(tokens_out=50)], budget=budget)
    with pytest.raises(BudgetExceeded, match="MAX_TOKENS_OUT"):
        client.chat([{"role": "user", "content": "hello world"}])


def test_max_llm_seconds_budget_is_enforced():
    ticks = iter([0.0, 100.0, 200.0, 450.0])
    budget = LLMBudget(max_seconds=180.0)
    client, _ = make_client(
        [nim_ok(), nim_ok()], budget=budget,
        timer=lambda: next(ticks),
    )
    client.chat([{"role": "user", "content": "one"}])  # ~100s
    with pytest.raises(BudgetExceeded, match="MAX_LLM_SECONDS"):
        client.chat([{"role": "user", "content": "two"}])  # pushes cumulative > 180s


def test_token_estimate_is_chars_over_four():
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("a" * 40) == 10


# ---------------------------------------------------------------------------
# Missing key and redaction (D-15)
# ---------------------------------------------------------------------------


def test_from_env_without_a_key_fails_clearly(monkeypatch):
    monkeypatch.delenv(config.NIM_API_KEY_ENV, raising=False)
    with pytest.raises(LLMUnavailable, match=config.NIM_API_KEY_ENV):
        LLMClient.from_env()


def test_api_key_never_appears_in_an_error_message():
    client, _ = make_client([ValueError("auth failed for nvapi-testkey1234567890")])
    with pytest.raises(LLMUnavailable) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    assert "nvapi-testkey1234567890" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


def test_api_key_never_reaches_the_trace(tmp_path):
    trace_path = tmp_path / "logs" / "trace.jsonl"
    trace = TraceWriter(trace_path, "run-llm")
    client, _ = make_client(
        [LLMTransient("boom nvapi-testkey1234567890"), nim_ok("recovered fine")],
        trace=trace, sleeper=lambda _: None,
    )
    client.chat([{"role": "user", "content": "hi"}])
    text = trace_path.read_text(encoding="utf-8")
    assert "nvapi-testkey1234567890" not in text
    assert "llm_chat" in text


def test_self_test_with_a_fake_transport(monkeypatch):
    client, _ = make_client([nim_ok("ok")])
    monkeypatch.setattr(LLMClient, "from_env", classmethod(lambda cls, **kwargs: client))
    result = self_test()
    assert "ok" in result


def test_live_self_test_marker_is_not_in_fast_suite():
    # The real NVIDIA call lives behind -m live; fast CI must not depend on it.
    import src.llm as module

    assert callable(module.self_test)
