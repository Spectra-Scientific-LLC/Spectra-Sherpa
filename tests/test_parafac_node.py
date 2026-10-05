from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import AxisInfo, FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.parafac_core import (
    PARAFAC_STATE_SERIALIZER,
    apply_parafac,
    validate_parafac_state,
)
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling import parafac_node
from spectra_sherpa.app.services.dag.nodes.modeling.parafac_node import PARAFACNode, _parafac_export_outputs
from spectra_sherpa.app.services.dag.nodes.output.plot_node import PlotNode
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import StatsSummaryNode
from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity
from spectra_sherpa.core.dimension_roles import DimensionRole
from spectra_sherpa.execution_contract_vocabulary import DatasetRankPolicy, WorkerCapability
from tests.performance_contract import PerformanceCeiling


def _tensor_dataset(*, seed: int = 7, n_samples: int = 9) -> SherpaDataset:
    rng = np.random.default_rng(seed)
    sample_factor = rng.normal(size=(n_samples, 2))
    time_factor = rng.normal(size=(5, 2))
    emission_factor = rng.normal(size=(7, 2))
    values = np.einsum("ir,jr,kr->ijk", sample_factor, time_factor, emission_factor)
    return SherpaDataset(
        values,
        sample_axis=SampleAxis(labels=[f"sample-{index + 1}" for index in range(n_samples)]),
        feature_axis=FeatureAxis(
            values=np.linspace(300.0, 600.0, 7),
            title="Emission wavelength",
            units="nm",
        ),
        axes={1: AxisInfo(values=np.linspace(0.0, 4.0, 5), title="Time", units="s")},
        target=np.linspace(1.0, 2.0, n_samples),
        layout=DatasetLayoutContext(
            kind="batch",
            source_type="synthetic-eem-kinetics",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SAMPLE,
                DimensionRole.TIME_POINT,
                DimensionRole.SPECTRAL_VARIABLE,
            ),
        ),
        title="Synthetic multiway response",
        units="intensity",
    )


def _node() -> PARAFACNode:
    return PARAFACNode(
        "parafac-test",
        {"n_components": 2, "max_iter": 200, "tol": 1e-8, "ridge": 1e-12},
    )


def test_parafac_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(20260904)
    factors = [rng.normal(size=(length, 3)) for length in (60, 20, 100)]
    values = np.einsum("ir,jr,kr->ijk", *factors)
    dataset = SherpaDataset(
        values,
        layout=DatasetLayoutContext(
            kind="batch",
            source_type="synthetic-eem-panel",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SAMPLE,
                DimensionRole.EXCITATION,
                DimensionRole.EMISSION,
            ),
        ),
    )
    node = PARAFACNode(
        "parafac-performance",
        {"n_components": 3, "max_iter": 100, "tol": 1e-7, "ridge": 1e-12},
    )

    with PerformanceCeiling("model.parafac", "60x20x100-three-component-fit", 5.0).measure():
        result = asyncio.run(node.run(dataset))

    assert result.outputs["sample_scores"].shape == (60, 3)
    assert np.isfinite(result.outputs["sample_scores"].X).all()


def test_parafac_is_deterministic_preserves_modes_and_records_no_unfolding() -> None:
    dataset = _tensor_dataset()
    first = asyncio.run(_node().run(dataset))
    second = asyncio.run(_node().run(dataset))

    assert first.diagnostics["converged"] is True
    # The norm-identity diagnostic subtracts nearly equal O(||X||^2)
    # values, so a perfect reconstruction has an O(sqrt(eps)) error floor
    # that varies with BLAS reduction order. Check fit accuracy directly,
    # independently of that diagnostic's cancellation floor.
    state = validate_parafac_state(first.outputs["model"])
    reconstructed = np.einsum(
        "ir,jr,kr->ijk",
        first.outputs["sample_scores"].X,
        state["arrays"]["mode_1_factor"],
        state["arrays"]["mode_2_factor"],
    )
    direct_error = np.linalg.norm(dataset.X - reconstructed) / np.linalg.norm(dataset.X)
    # tol bounds relative change between iterations, not the final residual.
    # The ALS stopping diagnostic itself has the cancellation floor above,
    # so different BLAS reductions can stop this exact-rank fit just above
    # tol (Windows: 1.23e-8 for tol=1e-8). Require sqrt(eps)-scale
    # reconstruction independently of that iteration-stopping threshold.
    cancellation_floor = np.sqrt(8 * np.finfo(np.float64).eps)
    assert direct_error < cancellation_floor
    assert abs(first.diagnostics["relative_reconstruction_error"] - direct_error) < cancellation_floor
    assert first.diagnostics["unfolding"] == "none"
    assert first.diagnostics["mode_roles"] == ["sample", "time_point", "spectral_variable"]
    np.testing.assert_allclose(first.outputs["sample_scores"].X, second.outputs["sample_scores"].X)
    np.testing.assert_allclose(first.outputs["component_weights"], second.outputs["component_weights"])

    scores = first.outputs["sample_scores"]
    assert scores.shape == (9, 2)
    assert scores.sample_axis is not None
    assert scores.sample_axis.labels == [f"sample-{index + 1}" for index in range(9)]
    np.testing.assert_allclose(scores.target, dataset.target)
    assert tuple(scores.layout.mode_roles) == (DimensionRole.SAMPLE, DimensionRole.COMPONENT)
    history = scores.provenance.to_list()
    assert history[-1]["op_id"] == "model.parafac.observation_scores"
    assert history[-1]["parameters"]["input_shape"] == [9, 5, 7]
    assert history[-1]["parameters"]["unfolding"] == "none"
    assert history[-1]["parameters"]["rank_policy"] == DatasetRankPolicy.PRESERVES_ND.value


def test_parafac_state_is_data_free_and_applies_to_new_sample_count() -> None:
    dataset = _tensor_dataset()
    result = asyncio.run(_node().run(dataset))
    state = validate_parafac_state(result.outputs["model"])

    assert state["serializer"] == PARAFAC_STATE_SERIALIZER
    assert set(state["arrays"]) == {"mode_1_factor", "mode_2_factor"}
    assert all(array.shape[0] != dataset.n_samples for array in state["arrays"].values())
    assert "sample_scores" not in state["arrays"]

    subset = dataset[:4]
    applied = _node().apply_fitted_state(subset, state)
    np.testing.assert_allclose(applied, result.outputs["sample_scores"].X[:4], rtol=1e-7, atol=1e-8)


def test_parafac_preserves_a_four_mode_problem_without_projection() -> None:
    rng = np.random.default_rng(19)
    factors = [rng.normal(size=(length, 1)) for length in (6, 3, 4, 5)]
    values = np.einsum("ir,jr,kr,lr->ijkl", *factors)
    dataset = SherpaDataset(
        values,
        layout=DatasetLayoutContext(
            kind="image",
            source_type="synthetic-hyperspectral-series",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SAMPLE,
                DimensionRole.SPATIAL_X,
                DimensionRole.SPATIAL_Y,
                DimensionRole.SPECTRAL_VARIABLE,
            ),
        ),
    )
    node = PARAFACNode(
        "parafac-four-mode",
        {"n_components": 1, "max_iter": 100, "tol": 1e-9, "ridge": 1e-12},
    )
    result = asyncio.run(node.run(dataset))

    assert result.diagnostics["input_shape"] == [6, 3, 4, 5]
    assert result.diagnostics["mode_roles"] == ["sample", "spatial_x", "spatial_y", "spectral_variable"]
    # LAPACK/BLAS implementations converge to the same rank-one solution with
    # slightly different final roundoff.  A 1e-7 relative reconstruction ceiling
    # remains negligible for this synthetic exact-rank fixture; the 1e-9 ALS
    # tolerance governs successive fit updates, not the final residual itself.
    assert result.diagnostics["relative_reconstruction_error"] < 1e-7
    assert set(result.outputs["model"]["arrays"]) == {
        "mode_1_factor",
        "mode_2_factor",
        "mode_3_factor",
    }


def test_parafac_accepts_a_spatial_first_hyperspectral_cube() -> None:
    rng = np.random.default_rng(29)
    factors = [rng.normal(size=(length, 2)) for length in (8, 7, 11)]
    values = np.einsum("ir,jr,kr->ijk", *factors)
    dataset = SherpaDataset(
        values,
        layout=DatasetLayoutContext(
            kind="image",
            source_type="hyperspectral-image-cube",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SPATIAL_Y,
                DimensionRole.SPATIAL_X,
                DimensionRole.SPECTRAL_FEATURE,
            ),
            image_size=values.shape[:2],
            image_mode=1,
            original_unfolded_shape=(values.shape[0] * values.shape[1], values.shape[2]),
        ),
        data_role="X_hsi",
    )

    result = asyncio.run(_node().run(dataset))

    assert result.diagnostics["mode_roles"] == ["spatial_y", "spatial_x", "spectral_feature"]
    assert result.diagnostics["relative_reconstruction_error"] < 1e-7
    assert result.outputs["sample_scores"].shape == (8, 2)
    assert result.outputs["sample_scores"].layout.mode_roles == (
        DimensionRole.SPATIAL_Y,
        DimensionRole.COMPONENT,
    )


def test_parafac_honors_hyperspectral_spatial_exclusions() -> None:
    rng = np.random.default_rng(31)
    factors = [rng.normal(size=(length, 2)) for length in (8, 7, 11)]
    values = np.einsum("ir,jr,kr->ijk", *factors)
    mask = np.ones(values.shape[:2], dtype=bool)
    mask[0, :] = False
    mask[3:6, 2:5] = False
    altered = values.copy()
    altered[~mask] = 1_000_000.0

    def image_dataset(data: np.ndarray, *, include: np.ndarray) -> SherpaDataset:
        return SherpaDataset(
            data,
            layout=DatasetLayoutContext(
                kind="image",
                source_type="hyperspectral-image-cube",
                source_dtype=data.dtype.str,
                source_shape=data.shape,
                mode_roles=(
                    DimensionRole.SPATIAL_Y,
                    DimensionRole.SPATIAL_X,
                    DimensionRole.SPECTRAL_FEATURE,
                ),
                image_size=data.shape[:2],
                image_mode=1,
                image_include=tuple(bool(item) for item in include.reshape(-1, order="F")),
                original_unfolded_shape=(data.shape[0] * data.shape[1], data.shape[2]),
            ),
            data_role="X_hsi",
        )

    baseline = asyncio.run(_node().run(image_dataset(values, include=mask)))
    challenged = asyncio.run(_node().run(image_dataset(altered, include=mask)))

    assert challenged.diagnostics["spatial_mask_policy"] == "binary-spatial-modes-0-1"
    assert challenged.diagnostics["included_spatial_cells"] == int(np.count_nonzero(mask))
    assert challenged.diagnostics["excluded_spatial_cells"] == int(mask.size - np.count_nonzero(mask))
    assert (
        challenged.outputs["model"]["metadata"]["state_content_digest"]
        == baseline.outputs["model"]["metadata"]["state_content_digest"]
    )
    np.testing.assert_allclose(
        challenged.outputs["sample_scores"].X,
        baseline.outputs["sample_scores"].X,
        rtol=1e-10,
        atol=1e-10,
    )


def test_parafac_application_refuses_changed_non_observation_axis() -> None:
    dataset = _tensor_dataset()
    state = asyncio.run(_node().run(dataset)).outputs["model"]
    changed = _tensor_dataset()
    changed.feature_axis = FeatureAxis(
        values=np.linspace(301.0, 601.0, 7),
        title="Emission wavelength",
        units="nm",
    )
    with pytest.raises(ValueError, match="axes differ"):
        _node().apply_fitted_state(changed, state)


def test_parafac_application_refuses_state_from_changed_execution_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = _tensor_dataset()
    state = asyncio.run(_node().run(dataset)).outputs["model"]
    monkeypatch.setattr(parafac_node, "execution_contract_digest", lambda _metadata: "0" * 64)

    with pytest.raises(ValueError, match="source contract differs"):
        _node().apply_fitted_state(dataset, state)


@pytest.mark.parametrize(
    ("dataset", "message"),
    [
        (SherpaDataset(np.ones((4, 5))), "at least three dimensions"),
        (SherpaDataset(np.ones((4, 3, 5))), "explicit canonical dimension roles"),
    ],
)
def test_parafac_refuses_ambiguous_rank_or_roles(dataset: SherpaDataset, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        asyncio.run(_node().run(dataset))


def test_parafac_refuses_nonfinite_values_and_open_state() -> None:
    dataset = _tensor_dataset()
    dataset.X[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite input"):
        asyncio.run(_node().run(dataset))

    valid = asyncio.run(_node().run(_tensor_dataset())).outputs["model"]
    invalid = {**valid, "unexpected": True}
    with pytest.raises(ValueError, match="exact serializer"):
        validate_parafac_state(invalid)

    tampered = copy.deepcopy(valid)
    factor = tampered["arrays"]["mode_1_factor"]
    factor[[0, 1], 0] = factor[[1, 0], 0]
    with pytest.raises(ValueError, match="content digest does not match"):
        validate_parafac_state(tampered)


def test_parafac_refuses_tensor_above_execution_bound_before_factorization() -> None:
    # Prove the cell guard runs before float64 conversion would allocate a
    # 128 MB working copy.
    values = np.zeros((2, 4001, 2000), dtype=np.uint8)
    dataset = SherpaDataset(
        values,
        layout=DatasetLayoutContext(
            kind="batch",
            source_type="synthetic-oversized-panel",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SAMPLE,
                DimensionRole.EXCITATION,
                DimensionRole.EMISSION,
            ),
        ),
    )

    with pytest.raises(ValueError, match="16,000,000-cell execution bound"):
        asyncio.run(_node().run(dataset))


def test_parafac_generated_numeric_path_matches_live_authority() -> None:
    dataset = _tensor_dataset()
    parameters = {"n_components": 2, "max_iter": 200, "tol": 1e-8, "ridge": 1e-12}
    exported = _parafac_export_outputs(dataset, parameters=parameters)
    live = asyncio.run(PARAFACNode("parafac-test", parameters).run(dataset))

    np.testing.assert_allclose(exported["sample_scores"], live.outputs["sample_scores"].X)
    np.testing.assert_allclose(exported["component_weights"], live.outputs["component_weights"])
    assert exported["relative_reconstruction_error"] == live.outputs["relative_reconstruction_error"]
    generated = _node().generate_python({"default": "tensor"}, indent="")
    assert any("_parafac_export_outputs" in line for line in generated)


def test_parafac_contract_is_explicitly_multiway_and_state_bound() -> None:
    contract = PARAFACNode.get_metadata().resolved_execution_contract()
    assert contract is not None
    assert contract.payload["input_rank_policy"] == DatasetRankPolicy.PRESERVES_ND.value
    assert contract.payload["fitted_state_serializer"] == PARAFAC_STATE_SERIALIZER
    assert contract.payload["target_access"] == "none"
    assert contract.payload["deterministic"] is True
    assert contract.payload["implementation_id"] == "spectrasherpa.model.parafac"
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    state = asyncio.run(_node().run(_tensor_dataset())).outputs["model"]
    assert state["metadata"]["source_contract_digest"] == contract.digest
    assert any(
        component["component_id"] == "distribution.numpy" for component in contract.payload["implementation_components"]
    )
    assert input_axis_identity(_tensor_dataset()) == input_axis_identity(_tensor_dataset())


def test_parafac_has_one_hsi_only_analysis_starter_template() -> None:
    template_directory = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"
    references = [
        path.name for path in template_directory.glob("*.yaml") if "model.parafac" in path.read_text(encoding="utf-8")
    ]

    assert references == ["parafac_multiway.yaml"]


def test_parafac_starter_outputs_are_directly_inspectable() -> None:
    dataset = _tensor_dataset()
    fit = asyncio.run(_node().run(dataset))

    scores = asyncio.run(PlotNode("scores-plot", {"plot_type": "scores"}).execute(fit.outputs["sample_scores"]))[
        "visualization"
    ]
    weights = asyncio.run(PlotNode("weights-plot", {"plot_type": "spectra"}).execute(fit.outputs["component_weights"]))[
        "visualization"
    ]
    summary = asyncio.run(StatsSummaryNode("scores-summary", {}).execute(fit.outputs["sample_scores"]))["statistics"]

    assert scores["plot_type"] == "scores"
    assert scores["layout"]["xaxis"]["title"] == "Component 1"
    assert scores["layout"]["yaxis"]["title"] == "Component 2"
    assert weights["plot_type"] == "line"
    assert weights["data"][0]["y"] == pytest.approx(fit.outputs["component_weights"].tolist())
    assert summary["summary"]["n_samples"] == dataset.shape[0]
    assert summary["summary"]["n_features"] == 2


def test_parafac_direct_application_authority_refuses_wrong_shape() -> None:
    dataset = _tensor_dataset()
    state = asyncio.run(_node().run(dataset)).outputs["model"]
    wrong = np.ones((3, 5, 6), dtype=np.float64)
    with pytest.raises(ValueError, match="fitted non-observation shape"):
        apply_parafac(wrong, state, input_axis_identity_sha256=state["metadata"]["input_axis_identity_sha256"])
