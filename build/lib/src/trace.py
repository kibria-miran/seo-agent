"""Append-only JSONL trace (section 8.10, D-15).

One event per line. Arguments are hashed, never stored raw, so a query or a
secret cannot leak. Values that look like API keys or bearer tokens are
redacted as a second line of defence.

The trace is the source of truth for tests and metrics; it is not a debug log.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src import clock, config

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization|auth)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:nvapi-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})",
    re.IGNORECASE,
)


def redact(value: Any) -> Any:
    """Recursively redact sensitive keys and key-shaped string values."""

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                cleaned[str(key)] = REDACTED
            else:
                cleaned[str(key)] = redact(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub(REDACTED, value)
    return value


def args_hash(args: Any) -> str:
    """Stable 16-hex digest of redacted, sorted arguments."""

    canonical = json.dumps(redact(args or {}), sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class TraceWriter:
    def __init__(self, path: str | Path | None = None, run_id: str = "") -> None:
        self.path = Path(path) if path is not None else config.TRACE_PATH
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        step: int | str,
        tool: str,
        args: Mapping[str, Any] | None = None,
        source: str = "code",
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0,
        status: str = "ok",
        kind: str = "action",
        **extra: Any,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "ts": clock.now().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "step": step,
            "tool": tool,
            "args_hash": args_hash(args or {}),
            "source": source,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "latency_ms": round(float(latency_ms), 3),
            "status": status,
            "kind": kind,
        }
        event.update(extra)
        event = redact(event)
        line = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return event


def read_trace(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else config.TRACE_PATH
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            events.append(json.loads(line))
    return events


__all__ = ["REDACTED", "TraceWriter", "args_hash", "read_trace", "redact"]
