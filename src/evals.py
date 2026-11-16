"""Phase 4 eval harness (frozen v1.2 eight + opt-in extras).

Every scenario is a JSON file under ``evals/scenarios/`` (the frozen v1.2
eight) or ``evals/extra/`` (the extra scenarios, opt-in) with a ``kind`` from
a small, explicit vocabulary. Checkers run in-process and pin ``clock.now()``
so the deterministic checks stay byte-stable. A failing scenario is reported,
never raised; ``run_evals`` returns the summary and the CLI exits non-zero
when any scenario fails.

Usage::

    seo-agent evals            # run the frozen v1.2 eight
    seo-agent evals --extra    # run the extra eight from evals/extra/
    seo-agent evals --all      # run both sets
    seo-agent evals --list     # print scenario titles and exit
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import clock, config


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    kind: str
    params: dict[str, Any]


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    title: str
    ok: bool
    detail: str = ""


def load_scenarios(
    scenarios_dir: Path | None = None, *, include_extra: bool = False
) -> list[Scenario]:
    directories = [scenarios_dir or config.SCENARIOS_DIR]
    if include_extra and scenarios_dir is None:
        directories.append(config.EXTRA_SCENARIOS_DIR)
    scenarios: list[Scenario] = []
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            scenarios.append(
                Scenario(
                    id=str(data["id"]),
                    title=str(data.get("title", data["id"])),
                    kind=str(data["kind"]),
                    params=dict(data.get("params") or {}),
                )
            )
    return sorted(scenarios, key=lambda item: item.id)


class _MiniMonkeyPatch:
    """Just enough monkeypatch for the checkers, outside pytest."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def setattr(self, target: Any, name: str, value: Any) -> None:
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, value in reversed(self._undo):
            setattr(target, name, value)
        self._undo.clear()


@contextmanager
def _inject_clock(monkeypatch: _MiniMonkeyPatch, start: str = "2026-11-16T09:00:00+00:00") -> Iterator[None]:
    base = datetime.fromisoformat(start).astimezone(timezone.utc)
    monkeypatch.setattr(clock, "now", lambda: base)
    yield


def _run_pipeline(tmp_path: Path, monkeypatch: _MiniMonkeyPatch, profile, *, fixture=None,
                  run_id="eval"):
    from src import pipeline

    with _inject_clock(monkeypatch):
        return pipeline.run_deterministic(
            profile,
            fixture_path=fixture,
            run_id=run_id,
            db_path=tmp_path / f"{run_id}.db",
            out_root=tmp_path / f"{run_id}-out",
            trace_path=tmp_path / f"{run_id}-trace.jsonl",
        )


def _write_variant(path: Path, variant: dict[str, Any]) -> Path:
    data = json.loads((config.FIXTURES_DIR / "own_site_audit.json").read_text(encoding="utf-8"))
    for key, value in variant.items():
        data[key] = value
    if "issues" in variant:
        data["total_issues"] = len(data["issues"])
        data["critical_count"] = sum(i["severity"] == "CRITICAL" for i in data["issues"])
        data["warning_count"] = sum(i["severity"] == "WARNING" for i in data["issues"])
        data["info_count"] = sum(i["severity"] == "INFO" for i in data["issues"])
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Checker implementations. Each returns (ok, detail).
# ---------------------------------------------------------------------------


def check_golden_baseline(params, tmp_path, monkeypatch):
    """S01: the deterministic fixture run matches evals/baselines.json."""

    from src.pipeline import load_profile

    profile = load_profile(config.PROFILES_DIR / "site.json")
    report = _run_pipeline(
        tmp_path, monkeypatch, profile,
        fixture=config.FIXTURES_DIR / "own_site_audit.json", run_id="eval-s01",
    )
    baseline = json.loads(config.BASELINES_PATH.read_text(encoding="utf-8"))
    current = {
        "site_score": report.site_score,
        "grade": report.grade,
        "backlog_items": len(report.backlog),
        "top_backlog_id": report.backlog[0].item_id if report.backlog else None,
        "top_backlog_kind": report.backlog[0].kind if report.backlog else None,
        "top_backlog_target": report.backlog[0].target if report.backlog else None,
        "top_backlog_priority": report.backlog[0].priority if report.backlog else None,
    }
    mismatch = {
        key: (current.get(key), baseline[key])
        for key in baseline
        if current.get(key) != baseline[key]
    }
    if mismatch:
        return False, f"baseline mismatch: {json.dumps(mismatch, sort_keys=True)}"
    return True, "fixture run matches committed baseline"


def check_clean_site_produces_gaps(params, tmp_path, monkeypatch):
    """S02: a zero-issue site still yields actionable gaps."""

    from src.pipeline import load_profile

    profile = load_profile(config.PROFILES_DIR / "site.json")
    variant_path = _write_variant(
        tmp_path / "clean.json", {"issues": [], "site_score": 100.0, "grade": "A"}
    )
    report = _run_pipeline(tmp_path, monkeypatch, profile, fixture=variant_path, run_id="eval-s02")
    ok = bool(report.backlog) and all(
        item.gap_type in {"NO_PAGE", "LOCAL_MISSING"} for item in report.backlog
    )
    types = sorted({item.gap_type for item in report.backlog})
    return ok, f"backlog={len(report.backlog)} gap_types={types}"


def check_compliance_text(params, tmp_path, monkeypatch):
    """S03–S06: the compliance gate blocks/allows as annotated."""

    from src import compliance

    ok, violations = compliance.check_text(
        params["text"], params.get("page_kind", "content"),
        fca_firm_ref=params.get("fca_firm_ref"),
    )
    expect_ok = bool(params.get("expect_ok", False))
    expected_rule = params.get("expect_rule")
    if ok != expect_ok:
        return False, f"expected ok={expect_ok}, got violations={[v.rule for v in violations]}"
    if expected_rule and not any(v.rule == expected_rule for v in violations):
        return False, f"expected rule {expected_rule}, got {[v.rule for v in violations]}"
    if expected_rule:
        return True, f"blocked with {expected_rule} as expected"
    return True, "passed the gate as expected" if expect_ok else "blocked as expected"


def check_injection_corpus(params, tmp_path, monkeypatch):
    """S07: the injection payload corpus is detected end-to-end."""

    from src.security import find_injection

    corpus = json.loads(config.INJECTION_PAYLOADS_PATH.read_text(encoding="utf-8"))["payloads"]
    variant = params.get("variant", "all")
    chosen = [item for item in corpus if variant == "all" or item["variant"] == variant]
    missing = [item["id"] for item in chosen if not find_injection(item["text"])]
    if missing:
        return False, f"payloads not detected: {missing}"
    return True, f"{len(chosen)} payload(s) detected"


def check_budget_constants(params, tmp_path, monkeypatch):
    """S08: frozen budgets are exactly the spec values."""

    expected = {
        "MAX_STEPS": 12,
        "MAX_LLM_CALLS": 20,
        "MAX_TOKENS_IN": 20_000,
        "MAX_TOKENS_OUT": 5_000,
        "MAX_LLM_SECONDS": 180,
        "MAX_FETCHES": 120,
        "MAX_RUN_SECONDS": 600,
        "MAX_BACKLOG": 30,
    }
    mismatch = {
        name: (getattr(config, name), value)
        for name, value in expected.items() if getattr(config, name) != value
    }
    if mismatch:
        return False, f"frozen budgets drifted: {mismatch}"
    return True, "frozen budgets intact"


def check_money_impact(params, tmp_path, monkeypatch):
    """S09: money keywords get CRITICAL impact; others get WARNING."""

    from src.backlog import impact_for
    from src.models import Gap, GapType
    from src.pipeline import load_profile, money_keywords_for

    profile = load_profile(config.PROFILES_DIR / "site.json")
    money = money_keywords_for(profile)
    money_gap = Gap(keyword=money[0], gap_type=GapType.NO_PAGE, evidence={})
    plain_gap = Gap(keyword="remortgage rates comparison", gap_type=GapType.NO_PAGE, evidence={})
    money_impact = impact_for(money_gap, money)
    plain_impact = impact_for(plain_gap, money)
    ok = (
        money_impact == config.IMPACT_CRITICAL == 3
        and plain_impact == config.IMPACT_WARNING == 2
    )
    return ok, f"money={money_impact} plain={plain_impact} (money={money})"


def check_confidence(params, tmp_path, monkeypatch):
    """S10: dual/multi-source and audited-rule confidences per frozen weights."""

    from src.backlog import confidence_for
    from src.models import Gap, GapType

    dual = Gap(keyword="k", gap_type=GapType.NO_PAGE, evidence={}, sources=["keywords", "serp"])
    multi = Gap(keyword="k", gap_type=GapType.NO_PAGE, evidence={}, sources=["a", "b", "c"])
    single = Gap(keyword="k", gap_type=GapType.NO_PAGE, evidence={}, sources=["keywords"])
    audited = Gap(keyword="k", gap_type=GapType.SCHEMA_MISSING, evidence={}, sources=[])
    values = (confidence_for(dual), confidence_for(multi),
              confidence_for(single), confidence_for(audited))
    ok = values == (
        config.CONFIDENCE_DUAL_SOURCE, config.CONFIDENCE_MULTI_SOURCE,
        config.CONFIDENCE_SINGLE_SOURCE, config.CONFIDENCE_AUDIT,
    ) == (0.65, 0.8, 0.5, 1.0)
    return ok, f"dual={values[0]} multi={values[1]} single={values[2]} audit={values[3]}"


def check_aborted_run(params, tmp_path, monkeypatch):
    """S11: a stale 'running' row is marked aborted when a run starts."""

    from src.pipeline import load_profile
    from src.store import Store

    profile = load_profile(config.PROFILES_DIR / "site.json")
    db = tmp_path / "eval-s11.db"
    with Store(db) as store:
        store.start_run("stale", url="https://clearpath-mortgage.co.uk")
    _run_pipeline(
        tmp_path, monkeypatch, profile,
        fixture=config.FIXTURES_DIR / "own_site_audit.json", run_id="eval-s11",
    )
    with Store(db) as store:
        status = store.get_run("stale")["status"]
    return status == "aborted", f"stale run status={status}"


def check_byte_identical_rerun(params, tmp_path, monkeypatch):
    """S12: same run-id + fixture + clock reproduce byte-identical files."""

    from src import pipeline
    from src.pipeline import load_profile

    profile = load_profile(config.PROFILES_DIR / "site.json")
    out = tmp_path / "out"
    db = tmp_path / "eval-s12.db"
    with _inject_clock(monkeypatch):
        pipeline.run_deterministic(
            profile, fixture_path=config.FIXTURES_DIR / "own_site_audit.json",
            run_id="eval-s12", db_path=db, out_root=out,
            trace_path=tmp_path / "trace.jsonl",
        )
        first = {name: (out / "eval-s12" / name).read_bytes()
                 for name in ("report.md", "backlog.json")}
        pipeline.run_deterministic(
            profile, fixture_path=config.FIXTURES_DIR / "own_site_audit.json",
            run_id="eval-s12", db_path=db, out_root=out,
            trace_path=tmp_path / "trace.jsonl",
        )
        second = {name: (out / "eval-s12" / name).read_bytes()
                  for name in ("report.md", "backlog.json")}
    ok = first == second
    return ok, "byte-identical rerun" if ok else "rerun drifted"


def check_backlog_cap_and_order(params, tmp_path, monkeypatch):
    """S13: the backlog is capped at MAX_BACKLOG, deterministically ordered."""

    from src.backlog import build_backlog
    from src.models import Gap, GapType

    gaps = [
        Gap(
            keyword=f"mortgage keyword {index:02d}",
            gap_type=GapType.NO_PAGE,
            evidence={},
            target=f"/mortgage-keyword-{index:02d}",
        )
        for index in range(int(params.get("gap_count", 40)))
    ]
    backlog = build_backlog(gaps, money_keywords=("mortgage keyword 39",))
    priorities = [item.priority for item in backlog]
    ok = (
        len(backlog) == config.MAX_BACKLOG
        and priorities == sorted(priorities, reverse=True)
        and backlog[0].target == "/mortgage-keyword-39"
    )
    return ok, f"items={len(backlog)} top={backlog[0].target if backlog else None}"


def check_profile_validation(params, tmp_path, monkeypatch):
    """S14: the profile rejects a malformed FCA reference."""

    from src.models import SiteProfile

    data = {
        "domain": "https://example.co.uk",
        "money_pages": ["/"],
        "target_keywords": ["remortgage"],
        "competitors": ["habito.com"],
        "cities": ["London"],
        "fca_firm_ref": params.get("fca_firm_ref", "12345"),
    }
    try:
        SiteProfile(**data)
        built = True
    except ValueError:
        built = False
    expect_ok = bool(params.get("expect_ok", False))
    return built == expect_ok, f"valid={built} expected={expect_ok}"


def check_two_run_diff(params, tmp_path, monkeypatch):
    """S15: two real runs diff one closed and one new issue."""

    from src import pipeline
    from src.pipeline import load_profile
    from src.store import Store

    profile = load_profile(config.PROFILES_DIR / "site.json")
    variant = {
        "issues": [
            issue
            for issue in json.loads((config.FIXTURES_DIR / "own_site_audit.json").read_text(encoding="utf-8"))["issues"]
            if not (issue["page_url"].endswith("/remortgage") and issue["issue_type"] == "Duplicate Title")
        ] + [{
            "page_url": "https://clearpath-mortgage.co.uk/free-mortgage-advice",
            "issue_type": "Missing Title",
            "severity": "CRITICAL",
            "current_value": "",
            "suggestion": "Add a unique title.",
        }],
        "site_score": 90.0,
        "grade": "A",
    }
    variant_path = _write_variant(tmp_path / "variant.json", variant)
    db = tmp_path / "eval-s15.db"
    out = tmp_path / "eval-s15-out"
    with _inject_clock(monkeypatch):
        pipeline.run_deterministic(
            profile, fixture_path=config.FIXTURES_DIR / "own_site_audit.json",
            run_id="eval-s15-a", db_path=db, out_root=out,
            trace_path=tmp_path / "trace-a.jsonl",
        )
        pipeline.run_deterministic(
            profile, fixture_path=variant_path,
            run_id="eval-s15-b", db_path=db, out_root=out,
            trace_path=tmp_path / "trace-b.jsonl",
        )
    with Store(db) as store:
        diff = store.diff_runs("eval-s15-a", "eval-s15-b")
    ok = len(diff.new_items) == 1 and len(diff.closed_items) == 1
    return ok, f"new={diff.new_items} closed={diff.closed_items} delta={diff.score_delta}"


def check_competitor_gap(params, tmp_path, monkeypatch):
    """S16: two competitor domains covering a term yield COMP_COVERS."""

    from src.audit_adapter import run_audit
    from src.backlog import build_backlog
    from src.gap import analyze
    from src.models import CompetitorPage
    from src.pipeline import build_clusters, build_keywords, load_profile, money_keywords_for

    profile = load_profile(config.PROFILES_DIR / "site.json")
    audit = run_audit(profile.base_url, fixture_path=config.FIXTURES_DIR / "own_site_audit.json")
    keywords = build_keywords(profile)
    clusters = build_clusters(keywords)
    pages = [
        CompetitorPage(domain="habito.com", url="https://www.habito.com/bad-credit-mortgages",
                       title="Bad credit mortgages", h_tags={"h1": ["Bad credit mortgages"]},
                       word_count=1200, schema_types=["FAQPage"]),
        CompetitorPage(domain="moneysavingexpert.com",
                       url="https://www.moneysavingexpert.com/mortgages/bad-credit/",
                       title="Bad credit mortgages explained",
                       h_tags={"h1": ["Bad credit mortgages"]},
                       word_count=1500, schema_types=["FAQPage"]),
    ]
    gaps = analyze(audit, clusters, competitor_pages=pages, serp=[], cities=profile.cities)
    comp = [gap for gap in gaps if gap.gap_type.value == "COMP_COVERS"]
    backlog = build_backlog(gaps, money_keywords=money_keywords_for(profile))
    items = [item for item in backlog if item.gap_type == "COMP_COVERS"]
    ok = bool(comp) and bool(items) and items[0].confidence == config.CONFIDENCE_MULTI_SOURCE
    confidence = items[0].confidence if items else None
    return ok, f"COMP_COVERS gaps={len(comp)} confidence={confidence}"


CHECKERS = {
    "golden_baseline": check_golden_baseline,
    "clean_site_produces_gaps": check_clean_site_produces_gaps,
    "compliance_text": check_compliance_text,
    "injection_corpus": check_injection_corpus,
    "budget_constants": check_budget_constants,
    "money_impact": check_money_impact,
    "confidence": check_confidence,
    "aborted_run": check_aborted_run,
    "byte_identical_rerun": check_byte_identical_rerun,
    "backlog_cap_and_order": check_backlog_cap_and_order,
    "profile_validation": check_profile_validation,
    "two_run_diff": check_two_run_diff,
    "competitor_gap": check_competitor_gap,
}


def run_scenario(scenario: Scenario, tmp_path: Path, monkeypatch: _MiniMonkeyPatch) -> ScenarioResult:
    tmp_path.mkdir(parents=True, exist_ok=True)
    checker = CHECKERS.get(scenario.kind)
    if checker is None:
        return ScenarioResult(scenario.id, scenario.title, False, f"unknown kind {scenario.kind!r}")
    try:
        ok, detail = checker(scenario.params, tmp_path, monkeypatch)
    except Exception as exc:  # a broken checker is a failed scenario, never a crash
        return ScenarioResult(scenario.id, scenario.title, False, f"error: {type(exc).__name__}: {exc}")
    return ScenarioResult(scenario.id, scenario.title, bool(ok), str(detail))


def run_evals(
    scenarios_dir: Path | None = None,
    *,
    include_extra: bool = False,
    write_results: bool = True,
) -> dict[str, Any]:
    """Run the frozen v1.2 eight (plus ``evals/extra/`` when ``include_extra``)
    and return the summary.

    Results are persisted to ``evals/results/evals-<ts>.json`` when
    ``write_results`` is true (the default for the CLI).
    """

    scenarios = load_scenarios(scenarios_dir, include_extra=include_extra)
    results: list[ScenarioResult] = []
    with tempfile.TemporaryDirectory(prefix="seo-evals-") as raw_tmp:
        for scenario in scenarios:
            mp = _MiniMonkeyPatch()
            try:
                results.append(run_scenario(scenario, Path(raw_tmp) / scenario.id, mp))
            finally:
                mp.undo()

    summary = {
        "generated_at": clock.now().isoformat(timespec="milliseconds"),
        "total": len(results),
        "passed": sum(1 for item in results if item.ok),
        "failed": sum(1 for item in results if not item.ok),
        "results": [
            {"id": item.id, "title": item.title, "ok": item.ok, "detail": item.detail}
            for item in results
        ],
    }
    if write_results:
        target_dir = config.RESULTS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = clock.now().strftime("%Y%m%dT%H%M%S")
        (target_dir / f"evals-{stamp}.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return summary


__all__ = [
    "CHECKERS",
    "Scenario",
    "ScenarioResult",
    "load_scenarios",
    "run_evals",
    "run_scenario",
]
