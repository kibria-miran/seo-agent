"""Explicit report section for absent/empty sources (C2)."""

from __future__ import annotations

import pytest

from test_report_determinism import render

pytestmark = pytest.mark.fast


def test_sources_section_absent_without_source_counts():
    markdown = render(budgets={"steps": 5, "fetches": 0})
    assert "## Source data" not in markdown


def test_sources_section_lists_counts_and_absences():
    markdown = render(
        budgets={
            "steps": 5,
            "fetches": 3,
            "sources": {
                "suggest": 12,
                "serp": 0,
                "gsc_csv": "dep_unmet",
            },
        }
    )
    assert "## Source data" in markdown
    assert "- `suggest`: 12 item(s)" in markdown
    assert "- `serp`: no data from serp" in markdown
    assert "- `gsc_csv`: no data from gsc_csv (dep_unmet)" in markdown
    assert "- `gsc_pages`: no data from gsc_pages" in markdown
    assert "- `competitor_pages`: no data from competitor_pages" in markdown


def test_sources_section_reports_zero_as_no_data():
    markdown = render(
        budgets={
            "sources": {
                "suggest": 0,
                "serp": 0,
                "gsc_csv": 0,
                "gsc_pages": 0,
                "competitor_pages": 0,
            }
        }
    )
    for name in ("suggest", "serp", "gsc_csv", "gsc_pages", "competitor_pages"):
        assert f"- `{name}`: no data from {name}" in markdown
