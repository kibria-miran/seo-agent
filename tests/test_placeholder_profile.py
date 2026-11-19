"""Live runs against the placeholder demo profile must be refused."""

from __future__ import annotations

from typer.testing import CliRunner

from src import config
from src.cli import app

runner = CliRunner()

# The demo profile is test data now; profiles/site.json is the real site.
DEMO_PROFILE = str(config.EVALS_DIR / "profile-demo.json")


def test_live_run_refuses_the_placeholder_demo_profile(monkeypatch):
    monkeypatch.delenv(config.ALLOW_DEMO_PROFILE_ENV, raising=False)
    result = runner.invoke(app, ["run", "--site", DEMO_PROFILE, "--no-llm"])
    assert result.exit_code == 2
    assert "placeholder demo profile" in result.output


def test_fixture_runs_still_work(monkeypatch, tmp_path):
    monkeypatch.delenv(config.ALLOW_DEMO_PROFILE_ENV, raising=False)
    result = runner.invoke(
        app,
        [
            "run",
            "--site",
            DEMO_PROFILE,
            "--no-llm",
            "--fixture",
            "tests/fixtures/own_site_audit.json",
            "--run-id",
            "test-placeholder-fixture",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output


def test_demo_profile_env_var_acknowledges_the_demo(monkeypatch):
    monkeypatch.setenv(config.ALLOW_DEMO_PROFILE_ENV, "0")
    result = runner.invoke(app, ["run", "--site", DEMO_PROFILE, "--no-llm"])
    assert result.exit_code == 2


def test_doctor_warns_on_placeholder_profile(monkeypatch):
    result = runner.invoke(app, ["doctor", "--site", DEMO_PROFILE])
    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "placeholder demo profile" in result.output
