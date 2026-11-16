"""Phase 7 draft generation: the gate runs before any write (D-6, D-7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import FakeLLM

from src import compliance, config
from src.backlog import build_backlog
from src.cli import app
from src.drafts import MAX_DRAFTS, draft_slug, template_draft, write_drafts
from src.models import BacklogItem
from src.pipeline import load_profile, run_deterministic
from src.trace import read_trace

pytestmark = pytest.mark.fast

FIXTURE = config.FIXTURES_DIR / "own_site_audit.json"
runner = CliRunner()


@pytest.fixture
def profile():
    return load_profile(config.PROFILES_DIR / "site.json")


def make_item(item_id, kind, target, title="", priority=0.5, **evidence):
    return BacklogItem(
        item_id=item_id,
        kind=kind,
        target=target,
        priority=priority,
        effort=3,
        impact=3,
        confidence=0.65,
        title=title,
        evidence=evidence,
        gap_type="LOCAL_MISSING" if kind == "create_local_page" else "NO_PAGE",
    )


def draft_items():
    return [
        make_item("BL-0001", "create_local_page", "/mortgage-advice-manchester",
                  title="Create a local page for 'mortgage advice manchester'",
                  city="Manchester", service="mortgage advice manchester"),
        make_item("BL-0003", "create_page", "/bad-credit-mortgage",
                  title="Create a page targeting 'bad credit mortgage'"),
        make_item("BL-0004", "create_page", "/mortgage-broker-near-me",
                  title="Create a page targeting 'mortgage broker near me'"),
        make_item("BL-0005", "create_page", "/mortgage-fees-explained",
                  title="Create a page targeting 'mortgage fees explained'"),
    ]


# ---------------------------------------------------------------------------
# Template drafts
# ---------------------------------------------------------------------------


def test_template_drafts_pass_the_compliance_gate(profile):
    for item in draft_items():
        text = template_draft(item, profile)
        ok, violations = compliance.check_text(text, "draft", fca_firm_ref=profile.fca_firm_ref)
        assert ok, (item.item_id, [v.rule for v in violations])


def test_template_drafts_are_disclosure_complete(profile):
    text = template_draft(draft_items()[0], profile)
    assert "Your home may be repossessed if you do not keep up repayments on your mortgage." in text
    assert "We do not charge a fee for our initial consultation." in text
    assert profile.fca_firm_ref in text
    assert "FCA firm reference" in text


def test_template_drafts_contain_no_banned_social_proof_or_absolutes(profile):
    text = template_draft(draft_items()[0], profile).casefold()
    for banned in ("guarantee", "best rates", "award-winning", "five-star", "trusted by", "voted"):
        assert banned not in text


def test_write_drafts_caps_at_max_drafts(profile):
    items = draft_items()
    drafts, rejected = write_drafts(items, profile, llm=None)
    assert len(drafts) == MAX_DRAFTS
    assert rejected == []


def test_write_drafts_skips_non_draftable_kinds(profile):
    items = [
        make_item("BL-9001", "fix_issue", "/x", title="Fix the thing"),
        *draft_items()[:1],
    ]
    drafts, rejected = write_drafts(items, profile, llm=None)
    assert list(drafts) == [draft_slug("/mortgage-advice-manchester")]


def test_slug_normalises_the_target():
    assert draft_slug("/Bad Credit Mortgage!") == "bad-credit-mortgage.md"
    assert draft_slug("/") == "draft.md"


# ---------------------------------------------------------------------------
# The gate comes before the write
# ---------------------------------------------------------------------------


def test_violating_llm_draft_is_never_written(profile, tmp_path):
    items = draft_items()[:1]
    llm = FakeLLM([
        "Guaranteed approval for every applicant. We are the best.",
        "Guaranteed approval again. No disclosure at all.",
    ])
    drafts, rejected = write_drafts(items, profile, llm=llm)
    assert drafts == {}
    assert rejected == ["BL-0001"]


def test_violating_draft_is_retried_once_with_feedback(profile, tmp_path):
    items = draft_items()[:1]
    retry_ok = template_draft(items[0], profile)
    llm = FakeLLM([
        "Guaranteed approval for everyone.",  # attempt 1: fails C1
        retry_ok,                             # attempt 2, after feedback: passes
    ])
    drafts, rejected = write_drafts(items, profile, llm=llm)
    assert drafts == {draft_slug(items[0].target): retry_ok.strip()}
    assert rejected == []
    # the second call was made with the violation fed back
    second_call = llm.calls[1]
    assert "C1" in json.dumps(second_call["messages"])


def test_gate_regression_protects_the_template_path(profile, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.drafts.check_text",
        lambda *a, **k: (False, [compliance.Violation("C9", "synthetic failure")]),
    )
    drafts, rejected = write_drafts(draft_items()[:1], profile, llm=None)
    assert drafts == {}
    assert rejected == ["BL-0001"]


def test_written_drafts_always_pass_the_gate(profile):
    llm = FakeLLM([template_draft(item, profile) for item in draft_items()])
    drafts, _ = write_drafts(draft_items(), profile, llm=llm)
    for name, text in drafts.items():
        ok, violations = compliance.check_text(text, "draft", fca_firm_ref=profile.fca_firm_ref)
        assert ok, (name, [v.rule for v in violations])


# ---------------------------------------------------------------------------
# Deterministic run integration (byte-stable)
# ---------------------------------------------------------------------------


def test_no_llm_drafts_are_byte_identical_across_reruns(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")

    def run(tag):
        out = tmp_path / tag / "out"
        report = run_deterministic(
            profile,
            fixture_path=FIXTURE,
            run_id="run-drafts",
            db_path=tmp_path / tag / "seo.db",
            out_root=out,
            with_drafts=True,
        )
        drafts_dir = out / "run-drafts" / "drafts"
        return report, {
            path.name: path.read_bytes() for path in sorted(drafts_dir.glob("*.md"))
        }

    first_report, first = run("a")
    second_report, second = run("b")

    assert first == second  # byte-identical drafts
    assert first  # at least one draft was written
    assert first_report.budgets["drafts"] == len(first)
    assert "## Drafts" in first_report.report_markdown
    for name in first:
        assert name in first_report.report_markdown


def test_drafts_are_off_by_default(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    report = run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-nodrafts",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
    )
    assert not (tmp_path / "out" / "run-nodrafts" / "drafts").exists()
    assert report.budgets["drafts"] == 0
    assert "_No drafts written this run._" in report.report_markdown


def test_cli_no_llm_with_drafts_end_to_end(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            "--site", str(config.PROFILES_DIR / "site.json"),
            "--no-llm",
            "--with-drafts",
            "--fixture", str(FIXTURE),
            "--run-id", "cli-drafts",
            "--db", str(tmp_path / "seo.db"),
            "--out", str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    drafts = sorted((tmp_path / "out" / "cli-drafts" / "drafts").glob("*.md"))
    assert len(drafts) == MAX_DRAFTS


def test_agent_mode_drafts_use_the_llm(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")

    GOOD_SEQUENCE = [
        '{"tool": "audit_site", "args": {}}',
        '{"tool": "mine_keywords", "args": {}}',
        '{"tool": "build_clusters", "args": {}}',
        '{"tool": "analyze_gaps", "args": {}}',
        '{"tool": "build_backlog", "args": {}}',
        '{"tool": "write_outputs", "args": {}}',
        '{"finish": true, "summary": "done"}',
    ]
    draft_text = template_draft(
        make_item("BL-0001", "create_local_page", "/mortgage-advice-manchester",
                  city="Manchester", service="mortgage advice manchester"),
        profile,
    )
    # write_outputs consumes its draft calls during the loop, so the finish
    # proposal comes after the three draft responses — not before them.
    llm = FakeLLM(
        GOOD_SEQUENCE[:6] + [draft_text] * 3 + ['{"finish": true, "summary": "done"}']
    )

    from src.agent import AgentRunner

    runner_obj = AgentRunner(
        llm,
        run_id="agent-drafts",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
        trace_path=tmp_path / "logs" / "trace.jsonl",
        with_drafts=True,
    )
    report = runner_obj.run(profile, fixture_path=FIXTURE)

    assert report.status == "ok"
    drafts = sorted((tmp_path / "out" / "agent-drafts" / "drafts").glob("*.md"))
    assert len(drafts) == 3
    events = read_trace(tmp_path / "logs" / "trace.jsonl")
    assert sum(e.get("kind") == "compliance_pass" for e in events) == 3
