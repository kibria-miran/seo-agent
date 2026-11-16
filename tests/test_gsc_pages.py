"""GSC query→page mapping source and gap evidence enrichment."""

from __future__ import annotations

import pytest
from conftest import make_audit, make_cluster, make_page

from src.gap import analyze
from src.sources.base import SourceError
from src.sources.gsc_pages import ENV_VAR, GscPagesSource
from src.store import Store
from src.trace import TraceWriter, read_trace

pytestmark = pytest.mark.fast


@pytest.fixture
def store():
    with Store(":memory:") as handle:
        yield handle


@pytest.fixture
def trace(tmp_path):
    return TraceWriter(tmp_path / "trace.jsonl", "gsc-pages-test")


def test_gsc_pages_unconfigured_is_dep_unmet(store, trace, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    result = GscPagesSource().collect(store=store, trace=trace)
    assert result.skipped is True
    assert "dep_unmet" in result.reason
    events = read_trace(trace.path)
    assert any(e.get("kind") == "dep_unmet" for e in events)


def test_gsc_pages_configured_but_missing_is_an_error(store, trace, tmp_path):
    with pytest.raises(SourceError):
        GscPagesSource(path=tmp_path / "gone.csv").collect(store=store, trace=trace)


def test_gsc_pages_parses_the_export(tmp_path, store, trace):
    csv_path = tmp_path / "Pages.csv"
    csv_path.write_text(
        "Top queries,Top pages,Impressions,Clicks\n"
        "Remortgage Calculator,/remortgage-calculator,300,12\n"
        "remortgage calculator,/remortgage-calculator,100,2\n"
        "bad credit mortgage,/bad-credit-mortgage,50,1\n"
        ",\n",
        encoding="utf-8",
    )
    result = GscPagesSource(path=csv_path).collect(store=store, trace=trace)
    pairs = {(item["query"], item["page"]) for item in result.items}
    assert ("remortgage calculator", "/remortgage-calculator") in pairs
    mapping = GscPagesSource.to_query_page_map(result.items)
    assert mapping == {
        "bad credit mortgage": ["/bad-credit-mortgage"],
        "remortgage calculator": ["/remortgage-calculator"],
    }


def test_gsc_pages_rejects_a_file_without_a_page_column(tmp_path, store, trace):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("Query,Impressions\nremortgage,100\n", encoding="utf-8")
    with pytest.raises(SourceError):
        GscPagesSource(path=csv_path).collect(store=store, trace=trace)


def test_gsc_pages_mapping_flows_into_gap_evidence():
    audit = make_audit(url="https://example.co.uk", pages=[
        make_page(url="https://example.co.uk/other", title="Other", h1_tags=[]),
    ])
    cluster = make_cluster(cluster_id="c1", keywords=["remortgage"], head_term="remortgage")
    gaps = analyze(
        audit,
        [cluster],
        query_page_map={"remortgage": ["/remortgage"]},
        cities=["London"],
    )
    missing = [g for g in gaps if g.gap_type.value == "NO_PAGE"]
    assert missing, [g.gap_type for g in gaps]
    assert missing[0].evidence.get("gsc_pages") == ["/remortgage"]


def test_gsc_pages_no_map_leaves_evidence_unchanged():
    audit = make_audit(url="https://example.co.uk", pages=[])
    cluster = make_cluster(cluster_id="c1", keywords=["brand query"], head_term="brand query")
    gaps = analyze(audit, [cluster], cities=["London"])
    assert gaps
    assert "gsc_pages" not in gaps[0].evidence
