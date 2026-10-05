"""Scientific and execution-contract proof for native rubberband correction."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.rubberband import rubberband_correct
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    Provenance,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.execution_contract_vocabulary import RuntimeFamily
from tests._optional_scp import HAS_SCP
from tests.performance_contract import PerformanceCeiling


def _dataset(*, descending: bool = False) -> SherpaDataset:
    axis = np.array([0.0, 1.0, 3.0, 4.0, 8.0])
    data = np.array(
        [
            [3.0, 2.0, 4.0, 1.0, 3.0],
            [2.0, 4.0, 3.0, 5.0, 2.0],
        ]
    )
    if descending:
        axis = axis[::-1]
        data = data[:, ::-1]
    source = SherpaDataset(
        X=data,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="wavenumber"),
        sample_axis=SampleAxis(
            values=np.array([10.0, 20.0]),
            include_mask=np.array([True, False]),
            sample_table={"batch": ["A", "B"]},
        ),
        target=np.array([0.25, 0.75]),
        domain=DomainContext(technique="FTIR", sample_type="fixture"),
        provenance=Provenance(),
        title="native-rubberband-fixture",
        units="absorbance",
    )
    source.provenance.append("data.fixture", {"source": "native-rubberband"}, node_id="source")
    return source


def test_hand_computed_nonuniform_axis_fixture() -> None:
    source = _dataset()
    result = rubberband_correct(source.data, source.feature_axis.values)

    expected_baseline = np.array(
        [
            [3.0, 2.0, 4.0 / 3.0, 1.0, 3.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ]
    )
    np.testing.assert_allclose(result.baseline, expected_baseline, rtol=0.0, atol=1e-15)
    np.testing.assert_allclose(result.corrected, source.data - expected_baseline, rtol=0.0, atol=1e-15)
    assert result.anchor_indices == ((0, 1, 3, 4), (0, 4))


def test_descending_axis_is_order_equivalent() -> None:
    ascending = _dataset()
    descending = _dataset(descending=True)
    expected = rubberband_correct(ascending.data, ascending.feature_axis.values)
    actual = rubberband_correct(descending.data, descending.feature_axis.values)

    np.testing.assert_allclose(actual.corrected[:, ::-1], expected.corrected, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(actual.baseline[:, ::-1], expected.baseline, rtol=0.0, atol=0.0)
    assert actual.anchor_indices == tuple(
        tuple(4 - index for index in reversed(row)) for row in expected.anchor_indices
    )


def test_large_axis_and_intensity_offsets_preserve_the_same_hull() -> None:
    source = _dataset()
    expected = rubberband_correct(source.data, source.feature_axis.values)
    actual = rubberband_correct(source.data + 1.0e8, source.feature_axis.values + 1.0e12)

    assert actual.anchor_indices == expected.anchor_indices
    np.testing.assert_allclose(actual.corrected, expected.corrected, rtol=0.0, atol=2e-8)


@pytest.mark.parametrize(
    ("offset", "peaks"),
    [
        (1.0e12, (1.0e-3, 2.0e-3)),
        (1.0e14, (1.0, 2.0)),
        (1.0e15, (2.0, 4.0)),
    ],
)
def test_large_representable_offsets_never_erase_positive_residuals(offset, peaks) -> None:
    spectrum = offset + np.array([0.0, peaks[0], 0.0, peaks[1], 0.0])
    expected = spectrum - offset
    result = rubberband_correct(spectrum[None, :], np.arange(5.0))

    np.testing.assert_array_equal(result.corrected[0], expected)
    assert result.anchor_indices == ((0, 4),)


def test_baseline_invariants_hold_for_seeded_spectra() -> None:
    rng = np.random.default_rng(20260821)
    axis = np.linspace(400.0, 4000.0, 700)
    data = rng.normal(size=(40, 700)) + np.linspace(-2.0, 3.0, 700)
    result = rubberband_correct(data, axis)

    assert np.all(result.baseline <= data + 1e-12)
    assert np.all(result.corrected >= -1e-12)
    for row, anchors in enumerate(result.anchor_indices):
        np.testing.assert_allclose(result.corrected[row, list(anchors)], 0.0, rtol=0.0, atol=0.0)
        assert anchors[0] == 0
        assert anchors[-1] == data.shape[1] - 1


@pytest.mark.parametrize(
    ("data", "axis", "message"),
    [
        (np.ones((1, 1)), np.array([1.0]), "at least two spectral features"),
        (np.ones((1, 3)), np.array([1.0, 1.0, 2.0]), "strictly monotonic"),
        (np.ones((1, 3)), np.array([1.0, 3.0, 2.0]), "strictly monotonic"),
        (np.array([[1.0, np.nan, 2.0]]), np.arange(3.0), "finite intensities"),
        (np.ones((1, 3)), np.array([1.0, np.inf, 3.0]), "finite coordinates"),
    ],
)
def test_invalid_or_ambiguous_scientific_inputs_fail_closed(data, axis, message) -> None:
    with pytest.raises(ValueError, match=message):
        rubberband_correct(data, axis)


def test_constant_and_collinear_spectra_reduce_to_endpoint_line() -> None:
    axis = np.array([1.0, 2.0, 4.0, 8.0])
    data = np.vstack([np.full(4, 7.5), 2.0 * axis + 3.0])
    result = rubberband_correct(data, axis)
    np.testing.assert_array_equal(result.corrected, np.zeros_like(data))
    assert result.anchor_indices == ((0, 3), (0, 3))


@pytest.mark.asyncio
async def test_live_and_generated_execution_share_one_native_authority() -> None:
    source = _dataset()
    node = node_registry.create_node("baseline.rubberband", "rubberband", {})
    live = await node.run(source)

    namespace = {"input_data": source, "results": {}}
    generated = "\n".join(node.generate_python({"default": "input_data"}, indent="", use_scp=False))
    exec(generated, namespace)
    generated_result = namespace["results"]["rubberband"]

    np.testing.assert_allclose(generated_result.data, live.outputs["default"].data, rtol=0.0, atol=0.0)
    generated_steps = generated_result.provenance.to_list()
    live_steps = live.outputs["default"].provenance.to_list()
    for steps in (generated_steps, live_steps):
        for step in steps:
            step.pop("timestamp", None)
    assert generated_steps == live_steps
    assert live.diagnostics["method"] == "lower_convex_envelope"
    assert live.diagnostics["anchor_count_min"] == 2
    assert live.diagnostics["anchor_count_max"] == 4


@pytest.mark.asyncio
async def test_rubberband_node_refuses_missing_values_at_its_input_boundary() -> None:
    source = _dataset()
    source.X[0, 2] = np.nan

    with pytest.raises(ValueError, match="baseline.rubberband requires finite input values"):
        await node_registry.create_node("baseline.rubberband", "rubberband", {}).run(source)


@pytest.mark.asyncio
async def test_node_preserves_typed_scientific_context() -> None:
    source = _dataset()
    output = (await node_registry.create_node("baseline.rubberband", "rubberband", {}).run(source)).outputs["default"]

    np.testing.assert_array_equal(output.target, source.target)
    np.testing.assert_array_equal(output.feature_axis.values, source.feature_axis.values)
    assert output.feature_axis.units == "cm-1"
    assert output.feature_axis.title == "wavenumber"
    np.testing.assert_array_equal(output.sample_axis.include_mask, [True, False])
    assert output.sample_axis.sample_table == {"batch": ["A", "B"]}
    assert output.domain == source.domain
    assert output.units == "absorbance"
    assert output.title == source.title
    assert output.provenance.operations == ["data.fixture", "baseline.rubberband"]
    assert output.provenance[-1].node_id == "rubberband"


@pytest.mark.asyncio
async def test_node_accepts_unitless_ordered_spectral_coordinates() -> None:
    source = SherpaDataset(
        X=np.array([[3.0, 2.0, 4.0, 1.0, 3.0]]),
        feature_axis=SpectralAxis(values=np.arange(5.0), units=None),
    )
    output = (await node_registry.create_node("baseline.rubberband", "rubberband", {}).run(source)).outputs["default"]
    assert output.shape == source.shape
    assert output.feature_axis.units is None


def test_contract_is_native_cited_and_range_control_is_removed() -> None:
    metadata = node_registry.get_metadata("baseline.rubberband")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["implementation_id"] == "spectrasherpa.baseline.rubberband"
    assert contract.payload["implementation_version"] == "2.0.1"
    component_ids = {component["component_id"] for component in contract.payload["implementation_components"]}
    assert "distribution.numpy" in component_ids
    assert "distribution.spectrochempy" not in component_ids
    assert any("10.1039/C8AN01384E" in citation for citation in contract.payload["citations"])
    assert any("10.1016/0020-0190(79)90072-3" in citation for citation in contract.payload["citations"])
    assert metadata.parameters == []
    with pytest.raises(ValueError, match="undeclared fields"):
        metadata.canonicalize_parameters({"ranges": "400:800"})


@pytest.mark.skipif(not HAS_SCP, reason="temporary cutover observation requires SpectroChemPy")
def test_temporary_uniform_axis_observation_matches_retired_scp_path() -> None:
    from tests._optional_scp import Coord, NDDataset

    data = _dataset().data
    native = rubberband_correct(data, np.arange(data.shape[1], dtype=np.float64)).corrected
    retired_input = NDDataset(data)
    retired_input.set_coordset(
        x=Coord(np.arange(data.shape[1], dtype=np.float64), title="features"),
        y=Coord(np.arange(data.shape[0], dtype=np.float64), title="samples"),
    )
    retired = retired_input.basc(model="rubberband")
    np.testing.assert_allclose(native, np.asarray(retired.data), rtol=0.0, atol=1e-12)


def test_representative_performance_ceiling() -> None:
    rng = np.random.default_rng(7)
    axis = np.linspace(400.0, 4000.0, 1600)
    data = rng.normal(size=(200, 1600)) + np.linspace(-1.0, 2.0, 1600)
    with PerformanceCeiling("baseline.rubberband", "200x1600-lower-hull", 5.0).measure():
        result = rubberband_correct(data, axis)
    assert result.corrected.shape == (200, 1600)


def test_clean_base_execution_never_imports_spectrochempy() -> None:
    script = r"""
import asyncio
import builtins
import os
import sys
import numpy as np

os.environ["SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION"] = "1"
real_import = builtins.__import__
def block_scp(name, *args, **kwargs):
    if name == "spectrochempy" or name.startswith("spectrochempy."):
        raise ImportError("SpectroChemPy deliberately blocked by native rubberband proof")
    return real_import(name, *args, **kwargs)
builtins.__import__ = block_scp

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry

metadata = node_registry.get_metadata("baseline.rubberband")
assert metadata.requires_scp is False
source = SherpaDataset(
    X=np.array([[3.0, 2.0, 4.0, 1.0, 3.0]]),
    feature_axis=SpectralAxis(values=np.arange(5.0), units="cm-1"),
)
result = asyncio.run(node_registry.create_node("baseline.rubberband", "rubberband", {}).run(source))
assert result.outputs["default"].shape == (1, 5)
assert not any(name == "spectrochempy" or name.startswith("spectrochempy.") for name in sys.modules)
assert "spectra_sherpa.app.lib.scp_compat" not in sys.modules
assert "spectra_sherpa.app.lib.adapters.scp_adapter" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "spectrochempy" not in (completed.stdout + completed.stderr).lower()
