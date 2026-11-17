"""Packaging smoke test: verifies the wheel ships the read-only data it needs.

The checkout and the bundled copy under ``src/resources/`` must stay in sync.
This test guards against the bundled vendored engine, profile, fixture or evals
going stale relative to the checkout (the failure mode the previous `dist/`
wheel had: missing ``third_party/seoextract`` and ``profiles/``).

Run in-tree (checkout copy wins via ``config._locate``) AND asserts the
committed bundled copies under ``src/resources/`` exist and load.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src import config
from src.audit_adapter import probe_capabilities

pytestmark = pytest.mark.fast

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "resources"
BUNDLED_SEOEXTRACT = RESOURCES / "third_party" / "seoextract"
BUNDLED_PROFILE = RESOURCES / "profiles" / "site.json"
BUNDLED_FIXTURE = RESOURCES / "tests" / "fixtures" / "own_site_audit.json"
BUNDLED_BASELINES = RESOURCES / "evals" / "baselines.json"


def test_bundled_resources_exist():
    for path in (BUNDLED_SEOEXTRACT, BUNDLED_PROFILE, BUNDLED_FIXTURE, BUNDLED_BASELINES):
        assert path.exists(), f"missing bundled resource: {path}"


def test_bundled_seoextract_commit_matches_pin():
    assert config.SEOEXTRACT_COMMIT == "6544a74e340e6ac8b147b7f4ab0f09d55d142dd3"
    spec = importlib.util.spec_from_file_location(
        "seoextract", str(BUNDLED_SEOEXTRACT / "seoextract" / "__init__.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.__version__ == "0.3.0", mod.__version__


def test_bundled_seoextract_probe_passes():
    sys_path_backup = list(__import__("sys").path)
    try:
        __import__("sys").path.insert(0, str(BUNDLED_SEOEXTRACT))
        from seoextract import SEOExtract
        from seoextract import models as models_module
        probe_capabilities(models_module, SEOExtract)
    finally:
        __import__("sys").path[:] = sys_path_backup


def test_bundled_profile_loads():
    data = json.loads(BUNDLED_PROFILE.read_text(encoding="utf-8"))
    assert data["domain"] == "https://clearpath-mortgage.co.uk"
    assert data["fca_firm_ref"] == "123456"
    assert isinstance(data["money_pages"], list) and data["money_pages"]


def test_bundled_fixture_loads():
    data = json.loads(BUNDLED_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "pages" in data


def test_bundled_baselines_load():
    data = json.loads(BUNDLED_BASELINES.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_resolved_paths_point_at_existing_data():
    for path in (
        config.SEOEXTRACT_DIR,
        config.PROFILES_DIR / "site.json",
        config.FIXTURES_DIR / "own_site_audit.json",
        config.EVALS_DIR / "baselines.json",
    ):
        assert path.exists(), f"resolved path missing: {path}"
