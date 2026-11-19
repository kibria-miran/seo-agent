"""Single source of truth for time (D-10).

Tests monkeypatch ``clock.now``; production code must call ``clock.now()``
rather than ``datetime.now()`` so the report and cache expiry are injectable
and deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """Current UTC time as an aware datetime."""

    return datetime.now(timezone.utc)


def utc_iso() -> str:
    """Current UTC time in a stable, sortable ISO-8601 form."""

    return now().isoformat(timespec="seconds")
