"""Phase 1: baseline selection must stay on the current domain (N-1, N-2).

Fixture in, real ledger out. The landc profile is used as the second
domain; the fixture audit payload is clearpath-shaped either way, which is
irrelevant to baseline *selection* (it keys off the stored run url).
"""

from __future__ import annotations

import pytest
from conftest import make_audit, make_issue, make_page

from src import config
from src.pipeline import load_profile, previous_baseline, run_deterministic
from src.store import Store

pytestmark = pytest.mark.fast

FIXTURE = config.FIXTURES_DIR / "own_site_audit.json"


@pytest.fixture
def clearpath_profile():
    return load_profile(config.PROFILES_DIR / "site.json")


@pytest.fixture
def landc_profile():
    return load_profile(config.PROFILES_DIR / "landc.json")


def test_P1_mixed_db_baselines_same_domain_run(tmp_path, clearpath_profile, landc_profile, inject_clock):
    inject_clock("2026-11-17T10:00:00+00:00", step=3600)
    db = tmp_path / "seo.db"
    out = tmp_path / "out"

    run_deterministic(clearpath_profile, fixture_path=FIXTURE, run_id="run-cp-1", db_path=db, out_root=out)
    run_deterministic(landc_profile, fixture_path=FIXTURE, run_id="run-lc-1", db_path=db, out_root=out)
    run_deterministic(landc_profile, fixture_path=FIXTURE, run_id="run-lc-2", db_path=db, out_root=out)

    with Store(db) as store:
        previous_run_id, note = previous_baseline(store, "run-lc-2", landc_profile.domain)
    assert previous_run_id == "run-lc-1"
    assert note is None

    report = (out / "run-lc-2" / "report.md").read_text(encoding="utf-8")
    assert "Delta vs previous run: +" in report
    assert "no comparable previous run" not in report


def test_P1_only_other_domain_runs_yields_no_baseline(tmp_path, clearpath_profile, landc_profile, inject_clock):
    inject_clock("2026-11-17T12:00:00+00:00", step=3600)
    db = tmp_path / "seo.db"
    out = tmp_path / "out"

    run_deterministic(clearpath_profile, fixture_path=FIXTURE, run_id="run-cp-only", db_path=db, out_root=out)
    run_deterministic(landc_profile, fixture_path=FIXTURE, run_id="run-lc-first", db_path=db, out_root=out)

    with Store(db) as store:
        previous_run_id, note = previous_baseline(store, "run-lc-first", landc_profile.domain)
    assert previous_run_id is None
    assert note == "No comparable previous run for landc.co.uk."

    report = (out / "run-lc-first" / "report.md").read_text(encoding="utf-8")
    assert "Delta vs previous run: n/a (No comparable previous run for landc.co.uk.)" in report


# ---------------------------------------------------------------------------
# P1-R1..R6: table-driven rows for the baseline contract (N-1, N-2)
# ---------------------------------------------------------------------------



def _seed_ok(store, run_id, url, started_at, site_score=80.0):
    store.start_run(run_id, url=url, started_at=started_at)
    store.save_audit(run_id, make_audit(site_score=site_score, pages=[], issues=[]))
    store.finish_run(run_id, status="ok", site_score=site_score, grade="B",
                     finished_at=started_at)


def test_P1_R1_same_domain_one_prior_run(tmp_path, landc_profile):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-prior", "https://www.landc.co.uk", "2026-11-16T09:00:00+00:00")
        previous_run_id, note = previous_baseline(store, "run-current", landc_profile.domain)
    assert previous_run_id == "run-prior"
    assert note is None


def test_P1_R2_same_domain_several_prior_runs_picks_newest_completed(tmp_path, landc_profile):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-old", "https://www.landc.co.uk", "2026-11-15T09:00:00+00:00")
        _seed_ok(store, "run-new", "https://www.landc.co.uk", "2026-11-16T09:00:00+00:00")
        _seed_ok(store, "run-mid", "https://www.landc.co.uk", "2026-11-15T20:00:00+00:00")
        previous_run_id, note = previous_baseline(store, "run-current", landc_profile.domain)
    assert previous_run_id == "run-new"
    assert note is None


def test_P1_R3_only_other_domain_runs(tmp_path, landc_profile):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-cp", "https://clearpath-mortgage.co.uk", "2026-11-16T09:00:00+00:00")
        previous_run_id, note = previous_baseline(store, "run-current", landc_profile.domain)
    assert previous_run_id is None
    assert note == "No comparable previous run for landc.co.uk."


@pytest.mark.parametrize(
    "stored_url",
    [
        "https://www.landc.co.uk",
        "https://landc.co.uk",
        "http://landc.co.uk:8080",
        "https://LANDC.CO.UK/",
        "www.landc.co.uk",
    ],
    ids=["www-host", "bare-host", "port-ignored", "case-insensitive", "no-scheme"],
)
def test_P1_R4_www_and_port_and_scheme_are_one_domain(tmp_path, stored_url):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-prior", stored_url, "2026-11-16T09:00:00+00:00")
        previous_run_id, note = previous_baseline(store, "run-current", "https://www.landc.co.uk")
    assert previous_run_id == "run-prior"
    assert note is None


def test_P1_R5_incomplete_prior_run_is_never_a_baseline(tmp_path, landc_profile):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-ok", "https://www.landc.co.uk", "2026-11-10T09:00:00+00:00")
        store.start_run("run-stale", url="https://www.landc.co.uk", started_at="2026-11-16T09:00:00+00:00")
        previous_run_id, _note = previous_baseline(store, "run-current", "https://www.landc.co.uk")
    assert previous_run_id == "run-ok"
    assert _note is None

    with Store(tmp_path / "seo.db") as store:
        store.start_run("run-only-stale", url="https://other.co.uk", started_at="2026-11-16T10:00:00+00:00")
        previous_run_id, note = previous_baseline(store, "run-x", "https://other.co.uk")
    assert previous_run_id is None
    assert note == "No comparable previous run for other.co.uk."


def test_P1_R6_diff_runs_refuses_cross_domain(tmp_path, landc_profile):
    with Store(tmp_path / "seo.db") as store:
        _seed_ok(store, "run-cp", "https://clearpath-mortgage.co.uk", "2026-11-16T09:00:00+00:00", site_score=80.0)
        store.start_run("run-lc", url="https://www.landc.co.uk", started_at="2026-11-16T10:00:00+00:00")
        issue = make_issue(issue_type="Missing Meta Description")
        store.save_audit("run-lc", make_audit(
            site_score=90.0,
            pages=[make_page(url="https://www.landc.co.uk/remortgage", issues=[issue])],
            issues=[issue],
        ))
        store.finish_run("run-lc", status="ok", site_score=90.0, grade="A",
                         finished_at="2026-11-16T10:00:00+00:00")
        diff = store.diff_runs("run-cp", "run-lc")
    assert diff.closed_items == []
    assert any("Missing Meta Description" in item for item in diff.new_items)
    assert diff.score_delta is None
