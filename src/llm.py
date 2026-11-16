"""Phase 5 LLM client — NVIDIA NIM (OpenAI-compatible), budgeted, retrying.

Hard rules (D-2, D-13, D-15):

- the API key comes from the environment (``NVIDIA_API_KEY``) and never
  appears in a trace, a log line or an exception message;
- budgets are enforced in code, not by prompts: every attempt decrements
  ``MAX_LLM_CALLS``, and cumulative tokens/wall-clock are capped at
  ``MAX_TOKENS_IN`` / ``MAX_TOKENS_OUT`` / ``MAX_LLM_SECONDS``;
- transient failures (429, 5xx, timeouts, connection errors) are retried
  with exponential backoff; anything else fails permanently;
- the client never sees raw HTML (that is D-4's job upstream).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from src import config
from src.trace import TraceWriter

Message = dict[str, str]  # {"role": "system|user|assistant", "content": "..."}
Transport = Callable[[dict[str, Any]], Mapping[str, Any]]

RETRY_DELAYS = (1.0, 2.0)  # seconds; attempts = 1 + len(RETRY_DELAYS)


class LLMError(RuntimeError):
    """Base class for LLM failures."""


class LLMUnavailable(LLMError):
    """Missing configuration or a permanent API error (no retry)."""


class LLMTransient(LLMError):
    """A retryable failure: 429, 5xx, timeout or connection error."""


class BudgetExceeded(LLMError):
    """A frozen budget (calls/tokens/seconds) would be exceeded."""


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    model: str
    finish_reason: str = ""


@dataclass
class LLMUsage:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0


class LLMBudget:
    """Cumulative per-run ledger for the frozen D-13 LLM budgets."""

    def __init__(
        self,
        *,
        max_calls: int = config.MAX_LLM_CALLS,
        max_tokens_in: int = config.MAX_TOKENS_IN,
        max_tokens_out: int = config.MAX_TOKENS_OUT,
        max_seconds: float = config.MAX_LLM_SECONDS,
    ) -> None:
        self.max_calls = int(max_calls)
        self.max_tokens_in = int(max_tokens_in)
        self.max_tokens_out = int(max_tokens_out)
        self.max_seconds = float(max_seconds)
        self.usage = LLMUsage()

    def reserve_attempt(self) -> None:
        """Every API attempt — including retries — counts."""

        if self.usage.calls + 1 > self.max_calls:
            raise BudgetExceeded(
                f"MAX_LLM_CALLS={self.max_calls} would be exceeded by this request"
            )
        if self.usage.seconds > self.max_seconds:
            raise BudgetExceeded(
                f"MAX_LLM_SECONDS={self.max_seconds} already exhausted"
            )
        self.usage.calls += 1

    def reserve_tokens_in(self, estimated_in: int) -> None:
        """Reject an over-budget prompt before spending money on it."""

        if self.usage.tokens_in + estimated_in > self.max_tokens_in:
            raise BudgetExceeded(
                f"MAX_TOKENS_IN={self.max_tokens_in} would be exceeded "
                f"(already {self.usage.tokens_in}, this prompt ~{estimated_in})"
            )

    def record_success(self, *, tokens_in: int, tokens_out: int, seconds: float) -> None:
        self.usage.tokens_in += int(tokens_in)
        self.usage.tokens_out += int(tokens_out)
        self.usage.seconds += float(seconds)
        if self.usage.tokens_in > self.max_tokens_in:
            raise BudgetExceeded(
                f"MAX_TOKENS_IN={self.max_tokens_in} would be exceeded "
                f"(cumulative {self.usage.tokens_in})"
            )
        if self.usage.tokens_out > self.max_tokens_out:
            raise BudgetExceeded(
                f"MAX_TOKENS_OUT={self.max_tokens_out} would be exceeded "
                f"(cumulative {self.usage.tokens_out})"
            )
        if self.usage.seconds > self.max_seconds:
            raise BudgetExceeded(
                f"MAX_LLM_SECONDS={self.max_seconds} would be exceeded "
                f"(cumulative {self.usage.seconds:.1f}s)"
            )


class LLMClient:
    """Minimal chat client for the NVIDIA NIM OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = config.LLM_TEMPERATURE,
        timeout: float = config.LLM_TIMEOUT_SECONDS,
        max_retries: int = len(RETRY_DELAYS),
        budget: LLMBudget | None = None,
        transport: Transport | None = None,
        trace: TraceWriter | None = None,
        timer: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url or config.NIM_BASE_URL
        self.model = model or config.NIM_MODEL
        self.temperature = float(temperature)
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.budget = budget or LLMBudget()
        self.trace = trace
        self._timer = timer
        self._sleeper = sleeper
        self._transport = transport or self._default_transport()

    @classmethod
    def from_env(cls, **kwargs: Any) -> "LLMClient":
        api_key = os.environ.get(config.NIM_API_KEY_ENV)
        if not api_key:
            raise LLMUnavailable(
                f"{config.NIM_API_KEY_ENV} is not set; the LLM path is unavailable "
                f"(the --no-llm deterministic path works without it)"
            )
        return cls(api_key=api_key, **kwargs)

    # -- public API --------------------------------------------------------

    def chat(
        self,
        messages: Sequence[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "temperature": self.temperature if temperature is None else float(temperature),
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        # Client-side estimate: exact when the server reports usage, honest
        # (chars/4) otherwise — the budget can never be blindsided.
        message_blob = json.dumps(payload["messages"], ensure_ascii=False)
        estimate_in = _estimate_tokens(message_blob)
        self.budget.reserve_tokens_in(estimate_in)

        delay_iter = iter(RETRY_DELAYS)
        attempt = 0
        while True:
            attempt += 1
            self.budget.reserve_attempt()
            started = self._timer()
            try:
                raw = self._transport(payload)
            except LLMTransient as exc:
                self._emit("retry" if attempt <= self.max_retries else "error",
                           model=self.model, tokens_in=0, tokens_out=0,
                           latency_ms=(self._timer() - started) * 1000)
                if attempt <= self.max_retries:
                    self._sleeper(next(delay_iter, RETRY_DELAYS[-1]))
                    continue
                raise LLMUnavailable(
                    f"LLM call failed after {attempt} attempts: {_safe_detail(exc)}"
                ) from exc
            except LLMUnavailable:
                self._emit("error", model=self.model, tokens_in=0, tokens_out=0,
                           latency_ms=(self._timer() - started) * 1000)
                raise
            except Exception as exc:  # transport bug surface; treat as permanent
                self._emit("error", model=self.model, tokens_in=0, tokens_out=0,
                           latency_ms=(self._timer() - started) * 1000)
                raise LLMUnavailable(
                    f"LLM transport error: {_safe_detail(exc)}"
                ) from exc
            elapsed = max(0.0, self._timer() - started)
            response = _parse_response(
                raw, model=self.model, latency_ms=elapsed * 1000, estimate_in=estimate_in
            )
            self.budget.record_success(
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                seconds=elapsed,
            )
            self._emit("ok", model=self.model, tokens_in=response.tokens_in,
                       tokens_out=response.tokens_out, latency_ms=response.latency_ms)
            return response

    def __call__(self, messages: Sequence[Message], *args: Any, **kwargs: Any) -> str:
        return self.chat(messages, *args, **kwargs).content

    # -- internals ---------------------------------------------------------

    def _default_transport(self) -> Transport:
        if not self.api_key:
            raise LLMUnavailable(
                f"{config.NIM_API_KEY_ENV} is not set; cannot build the NIM transport"
            )
        api_key = self.api_key
        base_url = self.base_url
        timeout = self.timeout

        def transport(payload: dict[str, Any]) -> Mapping[str, Any]:
            from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError

            client = OpenAI(base_url=base_url, api_key=api_key,
                            timeout=timeout, max_retries=0)
            try:
                response = client.chat.completions.create(**payload)
            except (APIConnectionError, APITimeoutError) as exc:
                raise LLMTransient(_safe_detail(exc)) from exc
            except APIStatusError as exc:
                status = int(getattr(exc, "status_code", 0) or 0)
                if status == 429 or status >= 500:
                    raise LLMTransient(f"HTTP {status}") from exc
                raise LLMUnavailable(f"HTTP {status}") from exc
            return response.model_dump(mode="json")

        return transport

    def _emit(self, status: str, *, model: str, tokens_in: int, tokens_out: int,
              latency_ms: float) -> None:
        if self.trace is None:
            return
        self.trace.emit(
            step="llm",
            tool="llm_chat",
            args={"model": model},
            source="net",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round(latency_ms, 3),
            status=status,
            kind="action",
        )


def _parse_response(
    raw: Mapping[str, Any],
    *,
    model: str,
    latency_ms: float,
    estimate_in: int,
) -> LLMResponse:
    choices = raw.get("choices") or []
    if not choices:
        raise LLMUnavailable("LLM returned no choices")
    first = choices[0] or {}
    message = first.get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise LLMUnavailable("LLM returned an empty message")
    usage = raw.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    if not tokens_in:
        tokens_in = estimate_in
    if not tokens_out:
        tokens_out = _estimate_tokens(content)
    finish = str(first.get("finish_reason") or "")
    return LLMResponse(
        content=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        model=str(raw.get("model") or model),
        finish_reason=finish,
    )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _safe_detail(exc: BaseException) -> str:
    """Exception detail with anything key-shaped redacted (D-15)."""

    text = str(exc)
    return re.sub(
        r"(nvapi-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )


def self_test() -> str:
    """One real call; used by `-m live` smoke tests and ops checks."""

    client = LLMClient.from_env()
    response = client.chat(
        [
            {"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Reply with the single word: ok"},
        ],
        max_tokens=4,
    )
    return f"{response.model}: ok ({response.tokens_in}+{response.tokens_out} tokens)"


__all__ = [
    "BudgetExceeded",
    "LLMBudget",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "LLMTransient",
    "LLMUnavailable",
    "LLMUsage",
    "self_test",
]
