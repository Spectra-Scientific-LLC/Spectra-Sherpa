from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.sdk import ChemometricsNode, SherpaDataset, param_number


def test_sdk_package_preserves_compatibility_exports() -> None:
    assert SherpaDataset is ss.SherpaDataset
    assert ChemometricsNode is ss.ChemometricsNode
    assert param_number is ss.param_number


def test_sdk_package_preserves_all_legacy_exports() -> None:
    for name in ss._compat.__all__:
        assert hasattr(ss, name), f"Compatibility export missing: {name!r}"


def test_sdk_package_exposes_supported_namespaces() -> None:
    expected_scientific = {
        "data",
        "deployment",
        "preprocess",
        "explore",
        "regression",
        "selection",
        "validate",
        "workflow",
        "plot",
        "plot_spec",
        "project",
        "report",
        "runtime",
    }
    assert ss._SCIENTIFIC_SUBMODULES == expected_scientific
    for name in sorted(expected_scientific):
        assert hasattr(ss, name)


def test_default_discovery_is_scientific_while_evidence_remains_explicit() -> None:
    discovered = set(dir(ss))
    assert ss._SCIENTIFIC_SUBMODULES <= discovered
    assert {"SherpaDataset", "Node", "NodeParameter", "register_node"} <= discovered
    assert not ss._EVIDENCE_SUBMODULES & discovered

    imported = importlib.import_module("spectra_sherpa.sdk.canonical_project")
    assert imported is ss.canonical_project


def test_scientific_leaf_import_does_not_initialize_evidence_modules() -> None:
    package_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import spectra_sherpa.sdk.data; "
            "assert not any(name.startswith('spectra_sherpa.sdk.canonical_') for name in sys.modules); "
            "assert 'spectra_sherpa.sdk.campaign_review' not in sys.modules",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(package_root / "src")},
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


_RETIRED_SDK_MODULES = {
    "_errors",
    "capsule",
    "classify",
    "harness_profile",
    "model",
    "node",
    "pipeline",
    "select",
    "templates",
    "unmix",
}


def test_retired_sdk_modules_and_root_namespaces_fail_closed() -> None:
    assert _RETIRED_SDK_MODULES.isdisjoint(ss.__all__)
    for name in sorted(_RETIRED_SDK_MODULES):
        assert not hasattr(ss, name)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"spectra_sherpa.sdk.{name}")


def test_placeholder_exports_are_absent() -> None:
    assert not hasattr(ss.data, "read_spc")
    assert not hasattr(ss.data, "read_opus")
    assert not hasattr(ss.report, "validation_pack")
    # S4a deliberately reuses the descriptive ``sdk.plot`` namespace for
    # rendering closed canonical specifications.  The deleted placeholder
    # plotting functions remain absent; there is no compatibility bridge.
    assert not hasattr(ss.plot, "scores")
    assert not hasattr(ss.plot, "loadings")


def test_root_package_defers_numpy_until_a_scientific_export_is_requested() -> None:
    package_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import spectra_sherpa; assert 'numpy' not in sys.modules; "
            "from spectra_sherpa import SherpaDataset; assert 'numpy' in sys.modules; "
            "assert SherpaDataset.__name__ == 'SherpaDataset'",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(package_root / "src")},
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
