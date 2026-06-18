from __future__ import annotations

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


def test_sdk_package_exposes_planned_namespaces() -> None:
    for name in [
        "data",
        "preprocess",
        "explore",
        "regression",
        "classify",
        "unmix",
        "select",
        "validate",
        "plot",
        "pipeline",
        "model",
        "workflow",
        "node",
        "report",
        "templates",
    ]:
        assert hasattr(ss, name)


def test_unimplemented_namespace_functions_raise_clear_errors() -> None:
    with pytest.raises(NotImplementedError, match="ss.classify.simca"):
        ss.classify.simca(None)
