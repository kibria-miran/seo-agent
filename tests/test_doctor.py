"""Phase 8/9 operational surface: doctor self-check, weekly runner script."""

from __future__ import annotations

import stat
import subprocess

import pytest
from typer.testing import CliRunner

from src import config
from src.cli import app

pytestmark = pytest.mark.fast

runner = CliRunner()
SCRIPT = config.ROOT / "scripts" / "weekly.sh"


def test_doctor_passes_with_the_repo_profile():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "all checks passed" in result.output
    assert "money keywords" in result.output
    assert "seoextract" in result.output.lower()


def test_doctor_fails_on_a_missing_profile(tmp_path):
    result = runner.invoke(app, ["doctor", "--site", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "FAIL" in result.output


def test_doctor_fails_on_a_broken_profile(tmp_path):
    broken = tmp_path / "site.json"
    broken.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--site", str(broken)])
    assert result.exit_code == 2
    assert "FAIL" in result.output


def test_doctor_fails_on_a_five_digit_fca_ref(tmp_path):
    profile = tmp_path / "site.json"
    profile.write_text(
        """{
          "domain": "https://example.co.uk",
          "money_pages": ["/"],
          "target_keywords": ["remortgage"],
          "competitors": ["habito.com"],
          "cities": ["London"],
          "fca_firm_ref": "12345"
        }""",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["doctor", "--site", str(profile)])
    assert result.exit_code == 2


def test_weekly_script_exists_and_is_executable():
    assert SCRIPT.exists()
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "weekly.sh must be executable"


def test_weekly_script_parses_without_executing():
    # sh -n parses only; it never runs the network-bearing command.
    result = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_weekly_script_defaults_to_the_demo_profile_safely():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -eu" in text
    assert "NVIDIA_API_KEY" not in text  # weekly path needs no key
    assert "weekly.log" in text  # log path present (via $LOG_DIR)
