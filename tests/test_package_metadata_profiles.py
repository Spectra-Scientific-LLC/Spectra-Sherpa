"""Public installation metadata is one Workbench plus named capabilities."""

from __future__ import annotations

import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from spectra_sherpa.app.services import synthesis

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_REPORT = PACKAGE_ROOT.parents[1] / "docs/evidence/public-install-profiles-v060-1214-final.json"


def _metadata() -> dict[str, Any]:
    with (PACKAGE_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["poetry"]


def test_default_install_is_the_complete_native_workbench() -> None:
    """The obvious install command includes the UI host and local store."""

    dependencies = _metadata()["dependencies"]
    required_workbench = {
        "fastapi",
        "starlette",
        "uvicorn",
        "sqlalchemy",
        "aiosqlite",
        "alembic",
        "python-multipart",
        "greenlet",
    }
    assert required_workbench <= set(dependencies)
    for dependency in required_workbench:
        declaration = dependencies[dependency]
        assert not isinstance(declaration, dict) or declaration.get("optional") is not True

    scripts = _metadata()["scripts"]
    assert scripts == {"spectra-sherpa": "spectra_sherpa.cli:main"}


def test_public_extras_are_closed_and_independent() -> None:
    """No compatibility aggregate or second product topology is advertised."""

    metadata = _metadata()
    dependencies = metadata["dependencies"]
    extras = metadata["extras"]
    assert extras == {
        "scp": ["spectrochempy"],
        "hitran": ["hitran-api", "hitran-api2"],
        "nist": ["beautifulsoup4"],
        "postgres": ["asyncpg", "gunicorn"],
    }
    assert "cloud" not in extras
    assert "app" not in extras
    assert "core" not in extras
    assert "workbench" not in extras
    assert "production" not in extras
    for names in extras.values():
        for name in names:
            declaration = dependencies[name]
            assert isinstance(declaration, dict)
            assert declaration.get("optional") is True


def test_default_synthesis_import_does_not_require_nist_html_parser(monkeypatch) -> None:
    """Stored-reference use and app startup do not imply acquisition authority."""

    monkeypatch.setitem(sys.modules, "bs4", None)
    with pytest.raises(synthesis.SynthesisError, match=r"spectra-sherpa\[nist\]"):
        synthesis._extract_nist_jcamp_download_url("<html></html>")


def test_retained_public_profile_qualification_is_commit_and_lock_bound() -> None:
    report = json.loads(QUALIFICATION_REPORT.read_text(encoding="utf-8"))

    assert report["schema_version"] == "spectra-public-install-qualification/1"
    assert report["source_revision"] == "0cf33a13effd1f259f6fbc1f18b368e15f1601e4"
    lock_bytes = (PACKAGE_ROOT / "poetry.lock").read_bytes()
    lock_hash = hashlib.sha256(lock_bytes).hexdigest()
    assert report["poetry_lock_sha256"] == lock_hash
    assert set(report["profiles"]) == {
        "default",
        "scp",
        "hitran",
        "nist",
        "postgres",
        "hitran,nist",
        "scp,hitran,nist",
    }
    assert report["profiles"]["default"]["present_optional_distributions"] == []
    for profile in report["profiles"].values():
        assert set(profile["expected_optional_distributions"]) <= set(profile["present_optional_distributions"])
        assert profile["renderer"]["distribution"] == "plotly"
        assert isinstance(profile["renderer"]["version"], str) and profile["renderer"]["version"]
