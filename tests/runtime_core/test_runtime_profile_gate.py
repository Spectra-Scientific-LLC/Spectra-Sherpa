"""Tests that run without the Workbench test fixtures or application stack."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PACKAGE_ROOT / "scripts" / "core_runtime_profile.py"


def _profile_module():
    spec = importlib.util.spec_from_file_location("spectra_core_runtime_profile_independent", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_forbidden_import_mutation_fails_the_profile() -> None:
    profile = _profile_module()
    passing_stages = [{"name": "representative", "status": "passed"}]

    assert profile._profile_status(forbidden_installed=[], forbidden_imported=[], stages=passing_stages) == "passed"
    assert (
        profile._profile_status(forbidden_installed=[], forbidden_imported=["fastapi"], stages=passing_stages)
        == "failed"
    )


def test_core_child_cannot_inherit_a_source_tree_or_application_environment(monkeypatch) -> None:
    profile = _profile_module()
    monkeypatch.setenv("PYTHONPATH", "/tmp/unsafe-source-tree")
    monkeypatch.setenv("PYTHONHOME", "/tmp/unsafe-home")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/unsafe-venv")
    monkeypatch.setenv("CONDA_PREFIX", "/tmp/unsafe-conda")

    environment = profile._clean_child_environment()

    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX"} & set(environment)
    assert environment["PYTHONNOUSERSITE"] == "1"
