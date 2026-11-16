"""Opt-in live smoke test: one real NVIDIA NIM call.

Never runs in the default suite. Requires NVIDIA_API_KEY and network access:

    NVIDIA_API_KEY=nvapi-... .venv/bin/python -m pytest -m live -q
"""

from __future__ import annotations

import os

import pytest

from src import config
from src.llm import LLMClient, self_test

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not os.environ.get(config.NIM_API_KEY_ENV),
    reason=f"{config.NIM_API_KEY_ENV} not set",
)
def test_live_self_test_one_real_call():
    result = self_test()
    assert "ok" in result.casefold()


@pytest.mark.skipif(
    not os.environ.get(config.NIM_API_KEY_ENV),
    reason=f"{config.NIM_API_KEY_ENV} not set",
)
def test_live_client_budget_ledger_records_tokens():
    client = LLMClient.from_env()
    client.chat(
        [
            {"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Reply with: ok"},
        ],
        max_tokens=4,
    )
    assert client.budget.usage.calls == 1
    assert client.budget.usage.tokens_in > 0
    assert client.budget.usage.tokens_out > 0
