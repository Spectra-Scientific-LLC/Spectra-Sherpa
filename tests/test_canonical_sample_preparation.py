"""Scientific identity and projection parity for canonical sample preparation."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import filter_samples_dataset
from tests.performance_contract import PerformanceCeiling


def test_attach_numeric_target_retains_explicit_authority_and_source_row_labels() -> None:
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
    from spectra_sherpa.core.target_authority import TargetAuthority

    source = SherpaDataset(np.arange(12.0).reshape(4, 3))
    authority = TargetAuthority(column="Moisture", target_type="continuous", units="wt %", source_digest="a" * 64)
    result = attach_target_dataset(
        source, np.arange(4.0), target_type="continuous", node_id="attach", target_authority=authority
    )
    assert result.target_context.selected_authority == authority
    assert result.target_context.target_names == ["Moisture"]
    assert result.sample_axis.labels == ["Source row 1", "Source row 2", "Source row 3", "Source row 4"]
    assert result.meta["sample_label_origin"] == "source_row_index"
    assert source.sample_axis is None or source.sample_axis.labels is None
    assert get_processing_history(result)[-1]["parameters"]["sample_identity_checked"] is False
    with pytest.raises(ValueError, match="multiple response columns"):
        attach_target_dataset(
            source, np.ones((4, 2)), target_type="continuous", node_id="attach", target_authority=authority
        )
    with pytest.raises(ValueError, match="type differs"):
        attach_target_dataset(
            source, np.arange(4.0), target_type="categorical", node_id="attach", target_authority=authority
        )


def _spectra() -> SherpaDataset:
    return SherpaDataset(
        dataset_id="canonical-sample-preparation/1",
        X=np.asarray(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [np.nan, np.nan, np.nan],
                [7.0, 8.0, 9.0],
            ]
        ),
        sample_axis=SampleAxis(
            labels=["A01", "A02", "A03", "A04"],
            sample_table={
                "plate_id": ["plate-1"] * 4,
                "well": ["A01", "A02", "A03", "A04"],
                "batch": ["control", "sample", "sample", "control"],
            },
        ),
        backend="numpy",
    )


def _generated(node: object, inputs: dict[str, str], namespace: dict[str, object]) -> SherpaDataset:
    namespace = {**namespace, "results": {}}
    source = "\n".join(node.generate_python(inputs, indent="", use_scp=False))
    exec(source, namespace)  # noqa: S102 - generated execution parity is the contract under test
    return namespace["results"][node.node_id]


@pytest.mark.asyncio
async def test_attach_target_live_and_export_preserve_categorical_identity_and_provenance() -> None:
    spectra = _spectra()
    target = np.asarray(["blank", "sample", "sample", "blank"], dtype=object)
    node = node_registry.create_node(
        "data.attach_target",
        "attach",
        {"target_type": "categorical"},
    )

    live = (await node.execute(X=spectra, y=target))["default"]
    generated = _generated(node, {"X": "spectra", "y": "target"}, {"spectra": spectra, "target": target})

    np.testing.assert_array_equal(live.target, generated.target)
    assert live.target.dtype == generated.target.dtype == object
    assert live.dataset_id == generated.dataset_id == spectra.dataset_id
    assert live.target_context == generated.target_context
    assert live.sample_axis.sample_table == generated.sample_axis.sample_table
    assert get_processing_history(live)[-1]["parameters"] == get_processing_history(generated)[-1]["parameters"]
    assert get_processing_history(live)[-1]["parameters"]["sample_identity_checked"] is False


@pytest.mark.asyncio
async def test_attach_target_rejects_same_length_rows_in_a_different_order() -> None:
    spectra = _spectra()
    target = SherpaDataset(
        X=np.asarray([[1.0], [2.0], [3.0], [4.0]]),
        sample_axis=SampleAxis(labels=["A02", "A01", "A03", "A04"]),
        backend="numpy",
    )
    node = node_registry.create_node("data.attach_target", "attach", {"target_type": "continuous"})

    with pytest.raises(ValueError, match="sample identities/order differ"):
        await node.execute(X=spectra, y=target)


@pytest.mark.asyncio
async def test_filter_samples_live_and_export_preserve_every_aligned_row_field() -> None:
    spectra = _spectra()
    spectra.target = np.asarray([10.0, 20.0, 30.0, 40.0])
    node = node_registry.create_node(
        "data.filter_samples",
        "filter",
        {
            "field": "sample_table",
            "sample_table_column": "batch",
            "pattern": "sample",
            "match_mode": "equals",
        },
    )

    live = (await node.execute(X=spectra))["default"]
    generated = _generated(node, {"X": "spectra"}, {"spectra": spectra})

    np.testing.assert_array_equal(live.X, generated.X)
    np.testing.assert_array_equal(live.target, generated.target)
    assert live.sample_axis.labels == generated.sample_axis.labels == ["A02", "A03"]
    assert (
        live.sample_axis.sample_table
        == generated.sample_axis.sample_table
        == {
            "plate_id": ["plate-1", "plate-1"],
            "well": ["A02", "A03"],
            "batch": ["sample", "sample"],
        }
    )
    assert get_processing_history(live)[-1]["parameters"] == get_processing_history(generated)[-1]["parameters"]


@pytest.mark.asyncio
async def test_intensity_filter_never_selects_missing_spectrum_even_when_inverted() -> None:
    node = node_registry.create_node(
        "data.filter_samples",
        "filter",
        {
            "field": "intensity",
            "intensity_metric": "max",
            "intensity_operator": "gte",
            "intensity_threshold": 7.0,
            "invert": True,
        },
    )

    result = (await node.execute(X=_spectra()))["default"]

    assert result.sample_axis.labels == ["A01", "A02"]
    parameters = get_processing_history(result)[-1]["parameters"]
    assert parameters["n_nonfinite_excluded"] == 1
    assert parameters["selected_indices"] == [0, 1]


def test_sample_preparation_contracts_bind_the_shared_authority() -> None:
    for node_type in ("data.attach_target", "data.filter_samples"):
        contract = node_registry.get_metadata(node_type).resolved_execution_contract()
        assert contract.payload["implementation_version"] == ("4.0.0" if node_type == "data.attach_target" else "2.0.0")
        assert any(
            component["component_id"].endswith(".data.sample_preparation")
            for component in contract.payload["implementation_components"]
        )


def test_filter_samples_has_a_representative_absolute_performance_ceiling() -> None:
    dataset = SherpaDataset(
        X=np.random.RandomState(17).normal(size=(200, 1600)),
        sample_axis=SampleAxis(labels=[f"sample-{index:03d}" for index in range(200)]),
        backend="numpy",
    )
    with PerformanceCeiling("data.filter_samples", "200x1600-intensity", 5.0).measure():
        filtered = filter_samples_dataset(
            dataset,
            field="intensity",
            pattern="",
            match_mode="contains",
            case_sensitive=False,
            invert=False,
            sample_table_column="",
            allow_empty=False,
            intensity_metric="max",
            intensity_operator="gte",
            intensity_threshold=2.0,
            intensity_upper_threshold=3.0,
            filter_values=None,
            node_id="filter",
        )
    assert filtered.shape[1] == 1600
