"""Phase 4 eval harness tests.

The frozen v1.2 eight run in-process by default; a handful of tests check the
harness itself (unknown kinds, failing checkers, CLI exit codes). The extra
scenarios in evals/extra/ are opt-in via --extra/--all.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from src import config, evals
from src.cli import app
from src.evals import load_scenarios, run_evals, run_scenario

pytestmark = pytest.mark.fast

runner = CliRunner()


FROZEN_EIGHT = ["S01", "S03", "S04", "S05", "S06", "S07", "S12", "S14"]
EXTRA_EIGHT = ["S02", "S08", "S09", "S10", "S11", "S13", "S15", "S16"]


def test_frozen_eight_exist_and_load():
    scenarios = load_scenarios()
    assert [scenario.id for scenario in scenarios] == FROZEN_EIGHT


def test_extra_eight_exist_and_load():
    scenarios = load_scenarios(config.EXTRA_SCENARIOS_DIR)
    assert [scenario.id for scenario in scenarios] == EXTRA_EIGHT


def test_all_sixteen_load_with_include_extra():
    scenarios = load_scenarios(include_extra=True)
    assert [scenario.id for scenario in scenarios] == [f"S{index:02d}" for index in range(1, 17)]


def test_the_full_eval_suite_passes():
    summary = run_evals(write_results=False)
    assert summary["failed"] == 0, [
        result for result in summary["results"] if not result["ok"]
    ]
    assert summary["total"] == 8


def test_the_extra_eval_suite_passes():
    summary = run_evals(config.EXTRA_SCENARIOS_DIR, write_results=False)
    assert summary["failed"] == 0, [
        result for result in summary["results"] if not result["ok"]
    ]
    assert summary["total"] == 8


def test_all_sixteen_eval_suite_passes():
    summary = run_evals(include_extra=True, write_results=False)
    assert summary["failed"] == 0, [
        result for result in summary["results"] if not result["ok"]
    ]
    assert summary["total"] == 16


def test_an_unknown_kind_is_reported_not_raised(tmp_path):
    scenario = evals.Scenario(id="S99", title="broken", kind="does_not_exist", params={})
    result = run_scenario(scenario, tmp_path, evals._MiniMonkeyPatch())
    assert not result.ok
    assert "unknown kind" in result.detail


def test_a_failing_checker_is_reported_not_raised(tmp_path, monkeypatch):
    scenario_file = tmp_path / "s97_fails.json"
    scenario_file.write_text(
        json.dumps(
            {
                "id": "S97",
                "title": "deliberately broken",
                "kind": "budget_constants",
                "params": {},
            }
        ),
        encoding="utf-8",
    )
    # Break a frozen budget inside the process; the scenario must fail cleanly.
    monkeypatch.setattr(config, "MAX_STEPS", 999)
    summary = run_evals(scenarios_dir=tmp_path, write_results=False)
    assert summary["failed"] == 1
    assert summary["results"][0]["id"] == "S97"


def test_an_exception_in_a_checker_becomes_a_failed_result(tmp_path, monkeypatch):
    from src import compliance

    monkeypatch.setattr(
        compliance,
        "check_text",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    scenario = evals.Scenario(id="S98", title="explodes", kind="compliance_text", params={"text": "x"})
    result = run_scenario(scenario, tmp_path, evals._MiniMonkeyPatch())
    assert not result.ok
    assert "RuntimeError" in result.detail


def test_baselines_file_is_committed_and_matches_the_harness():
    baseline = json.loads(config.BASELINES_PATH.read_text(encoding="utf-8"))
    assert set(baseline) == {
        "site_score",
        "grade",
        "backlog_items",
        "top_backlog_id",
        "top_backlog_kind",
        "top_backlog_target",
        "top_backlog_priority",
    }
    assert baseline["site_score"] == 87.5
    assert baseline["top_backlog_id"] == "BL-0001"


def test_cli_evals_runs_and_exits_zero():
    result = runner.invoke(app, ["evals"])
    assert result.exit_code == 0, result.output
    assert "8/8" in result.output


def test_cli_evals_all_runs_sixteen():
    result = runner.invoke(app, ["evals", "--all"])
    assert result.exit_code == 0, result.output
    assert "16/16" in result.output


def test_cli_evals_extra_runs_eight():
    result = runner.invoke(app, ["evals", "--extra"])
    assert result.exit_code == 0, result.output
    assert "8/8" in result.output


def test_cli_evals_list_only():
    result = runner.invoke(app, ["evals", "--list"])
    assert result.exit_code == 0
    assert "S01" in result.output
    assert "S16" not in result.output
