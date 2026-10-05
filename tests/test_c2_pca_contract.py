"""Canonical PCA producer, application, state, artifact, and cost proofs."""

from __future__ import annotations

import asyncio
import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import FeatureAxis, TimeAxis
from spectra_sherpa.app.lib.pca import PCAExtract, fit_pca
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, DomainContext, SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
from spectra_sherpa.app.services.dag.nodes.diagnostics import _outlier_dispatch
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import (
    PCA_FITTED_STATE_SCHEMA,
    PCA_FITTED_STATE_SERIALIZER,
    PCANode,
    PCATransformNode,
    _canonical_pca_parameters,
    apply_pca_fitted_state,
    reconstruct_pca_fitted_state,
    validate_pca_fitted_state,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _parameters(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {"n_components": "3", "standardized": False, "scaled": False}
    parameters.update(overrides)
    return parameters


def _dataset(*, samples: int = 36, features: int = 18) -> SherpaDataset:
    rng = np.random.default_rng(20260812)
    latent = rng.normal(size=(samples, 4))
    loadings = rng.normal(size=(4, features))
    matrix = 2.5 + latent @ loadings + rng.normal(0.0, 0.015, size=(samples, features))
    return SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(labels=[f"sample-{index:03d}" for index in range(samples)]),
        feature_axis=FeatureAxis(
            values=np.linspace(900.0, 1800.0, features),
            labels=[f"band-{index:03d}" for index in range(features)],
            units="cm^-1",
        ),
        data_role="X_spectra",
    )


def test_pca_has_one_closed_producer_and_one_closed_application_contract() -> None:
    producer = node_registry.get_metadata("model.pca").resolved_execution_contract()
    application = node_registry.get_metadata("model.pca_transform").resolved_execution_contract()

    assert producer is not None and application is not None
    assert producer.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert producer.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert application.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert application.payload["lifecycle_kind"] == LifecycleKind.ARTIFACT_APPLICATION.value
    assert (
        producer.payload["managed_optimization_eligibility"]
        == application.payload["managed_optimization_eligibility"]
        == (ManagedOptimizationEligibility.LOCAL.value,)
    )
    assert producer.payload["fitted_state_serializer"] == PCA_FITTED_STATE_SERIALIZER
    assert application.payload["fitted_state_serializer"] == PCA_FITTED_STATE_SERIALIZER
    assert any("Jolliffe" in citation for citation in producer.payload["citations"])
    assert any("Minka" in citation for citation in producer.payload["citations"])


def test_pca_leader_path_filters_hsi_source_exclusions_and_preserves_pixel_labels() -> None:
    rng = np.random.default_rng(20260909)
    dataset = SherpaDataset(
        X=rng.normal(size=(6, 5)),
        sample_axis=SampleAxis(labels=[f"pixel-{index}" for index in range(1, 7)]),
        layout=DatasetLayoutContext(
            kind="image",
            source_type="image",
            source_dtype="float64",
            source_shape=(6, 5),
            mode_roles=("sample", "feature"),
            image_size=(2, 3),
            image_mode=1,
            image_include=(True, True, False, False, True, True),
            original_unfolded_shape=(6, 5),
        ),
        data_role="X_hsi",
    )

    included = asyncio.run(FilterSamplesNode("inclusions", {"field": "source_inclusion"}).execute(X=dataset))["default"]
    centered = asyncio.run(ScaleNode("center", {"method": "mean_center"}).execute(default=included)).outputs["default"]
    outputs = asyncio.run(PCANode("pca", _parameters()).execute(input_data=centered)).outputs

    assert included.sample_axis.labels == ["pixel-1", "pixel-2", "pixel-5", "pixel-6"]
    assert outputs["scores"].shape == (4, 3)
    assert outputs["scores"].sample_axis.labels == included.sample_axis.labels
    assert outputs["diagnostic_state"]["sample_labels"] == included.sample_axis.labels
    assert included.data_role == "X_spectra"
    assert PCANode.metadata.input_ports[0].accepted_data_roles == ["X_spectra", "X_features"]
    assert ScaleNode.metadata.input_ports[0].accepted_data_roles == ["X_spectra", "X_features"]


def test_pca_parameters_are_closed_and_preprocessing_modes_are_exclusive() -> None:
    assert _canonical_pca_parameters(_parameters()) == _parameters()
    assert _canonical_pca_parameters(_parameters(n_components="0.95"))["n_components"] == "0.95"
    assert _canonical_pca_parameters(_parameters(n_components="mle"))["n_components"] == "mle"
    for invalid in (
        {},
        {**_parameters(), "whiten": True},
        _parameters(n_components=True),
        _parameters(n_components=0),
        _parameters(n_components="0"),
        _parameters(standardized=1),
        _parameters(standardized=True, scaled=True),
    ):
        with pytest.raises(ValueError):
            _canonical_pca_parameters(invalid)


@pytest.mark.parametrize("mode", ["center", "standard", "minmax"])
def test_pca_matches_independently_computed_full_svd_invariants(mode: str) -> None:
    raw = np.asarray(_dataset().X, dtype=np.float64)
    if mode == "standard":
        reference = (raw - np.mean(raw, axis=0)) / np.where(np.std(raw, axis=0) == 0.0, 1.0, np.std(raw, axis=0))
    elif mode == "minmax":
        span = np.ptp(raw, axis=0)
        reference = (raw - np.min(raw, axis=0)) / np.where(span == 0.0, 1.0, span)
    else:
        reference = raw
    reference = reference - np.mean(reference, axis=0)
    u, singular_values, right_vectors = np.linalg.svd(reference, full_matrices=False)
    components = 3
    reference_scores = u[:, :components] * singular_values[:components]
    reference_projection = right_vectors[:components].T @ right_vectors[:components]
    reference_ratio = singular_values[:components] ** 2 / np.sum(singular_values**2)

    fitted = fit_pca(
        raw,
        n_components=components,
        standardized=mode == "standard",
        scaled=mode == "minmax",
    )

    np.testing.assert_allclose(fitted.loadings.T @ fitted.loadings, reference_projection, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(
        fitted.scores @ fitted.scores.T, reference_scores @ reference_scores.T, rtol=1e-12, atol=1e-12
    )
    np.testing.assert_allclose(fitted.explained_variance_ratio, reference_ratio, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("mode", ["center", "standard", "minmax"])
def test_pca_live_generated_application_and_artifact_paths_share_one_projection(mode: str) -> None:
    dataset = _dataset()
    parameters = _parameters(
        standardized=mode == "standard",
        scaled=mode == "minmax",
    )
    node = PCANode("pca", parameters)

    live = asyncio.run(node.execute(input_data=dataset))
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["pca"]
    state = live.outputs["fitted_state"]
    applied = asyncio.run(PCATransformNode("apply", {}).execute(X_new=dataset, model=state))
    direct = apply_pca_fitted_state(dataset, state)
    artifact = live.outputs["_model_artifact"]
    restored = PCAExtract.from_artifact(artifact["metadata"], artifact["arrays"])

    assert state["schema_version"] == PCA_FITTED_STATE_SCHEMA
    assert state == generated["fitted_state"]
    np.testing.assert_allclose(live.outputs["scores"].data, generated["scores"].data, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(live.outputs["scores"].data, applied.outputs["scores"].data, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(live.outputs["scores"].data, direct, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(live.outputs["scores"].data, restored.transform(dataset.X), rtol=0.0, atol=1e-12)
    reconstruction = reconstruct_pca_fitted_state(live.outputs["scores"], state)
    assert reconstruction.shape == dataset.shape
    assert np.mean((dataset.X - reconstruction) ** 2) < np.var(dataset.X)


def test_standardized_pca_preserves_separate_reference_frames_for_large_offset_data() -> None:
    rng = np.random.default_rng(20260820)
    matrix = 1.0e8 + rng.normal(0.0, 2.0, size=(80, 20))
    dataset = SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(labels=[f"sample-{index:03d}" for index in range(matrix.shape[0])]),
        feature_axis=FeatureAxis(values=np.arange(matrix.shape[1], dtype=np.float64), units="channel"),
        units="counts",
        data_role="X_features",
    )
    node = PCANode("large-offset-pca", _parameters(n_components="6", standardized=True))

    live = asyncio.run(node.execute(input_data=dataset))
    state = live.outputs["fitted_state"]
    arrays = state["arrays"]
    assert arrays["mean"] is not None and arrays["scale"] is not None and arrays["center"] is not None
    assert np.max(np.abs(np.asarray(arrays["mean"], dtype=np.float64))) > 1.0e7
    assert np.max(np.abs(np.asarray(arrays["center"], dtype=np.float64))) < 1.0e-6

    direct = apply_pca_fitted_state(dataset, state)
    artifact = live.outputs["_model_artifact"]
    restored = PCAExtract.from_artifact(artifact["metadata"], artifact["arrays"])
    applied = asyncio.run(PCATransformNode("apply", {}).execute(X_new=dataset, model=state))
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["large-offset-pca"]

    np.testing.assert_allclose(live.outputs["scores"].data, direct, rtol=1e-11, atol=1e-11)
    np.testing.assert_allclose(live.outputs["scores"].data, restored.transform(matrix), rtol=1e-11, atol=1e-11)
    np.testing.assert_allclose(live.outputs["scores"].data, applied.outputs["scores"].data, rtol=1e-11, atol=1e-11)
    np.testing.assert_allclose(live.outputs["scores"].data, generated["scores"].data, rtol=1e-11, atol=1e-11)


@pytest.mark.parametrize("standardized,scaled", [(True, False), (False, True)])
def test_pca_owns_component_axes_and_dimensionless_value_semantics_on_square_input(
    standardized: bool,
    scaled: bool,
) -> None:
    rng = np.random.default_rng(20260821)
    source_samples = [f"source-{index}" for index in range(5)]
    source_features = [f"band-{index}" for index in range(5)]
    dataset = SherpaDataset(
        X=rng.normal(size=(5, 5)),
        sample_axis=SampleAxis(labels=source_samples, title="Specimen"),
        feature_axis=FeatureAxis(
            values=np.linspace(450.0, 650.0, 5),
            labels=source_features,
            units="nm",
            title="Wavelength",
        ),
        domain=DomainContext(technique="UV-vis", expected_units="absorbance", data_quantity="Absorbance"),
        units="absorbance",
        data_role="X_spectra",
    )

    result = asyncio.run(
        PCANode("full-rank", _parameters(n_components="5", standardized=standardized, scaled=scaled)).execute(
            input_data=dataset
        )
    )
    scores = result.outputs["scores"]
    loadings = result.outputs["loadings"]
    applied = asyncio.run(
        PCATransformNode("apply", {}).execute(X_new=dataset, model=result.outputs["fitted_state"])
    ).outputs["scores"]

    assert scores.sample_axis.labels == source_samples
    assert scores.feature_axis.labels == [
        f"PC{index + 1} ({result.diagnostics['explained_variance_ratio'][index] * 100:.1f}%)" for index in range(5)
    ]
    assert scores.feature_axis.units == "dimensionless"
    assert loadings.sample_axis.labels == scores.feature_axis.labels
    assert loadings.feature_axis.labels == source_features
    assert loadings.feature_axis.units == "nm"
    for derived, quantity in ((scores, "PCA score"), (loadings, "PCA loading"), (applied, "PCA score")):
        assert derived.units == "dimensionless"
        assert derived.domain.expected_units == "dimensionless"
        assert derived.domain.data_quantity == quantity
        assert derived.meta["value_units"] == "dimensionless"


def test_pca_scores_preserve_time_observation_axis_without_relabeling_components() -> None:
    dataset = _dataset(samples=12, features=7)
    time_axis = TimeAxis(values=np.linspace(0.0, 11.0, 12), units="s", title="Elapsed time")
    dataset._axes[dataset._SAMPLE_DIM] = time_axis  # noqa: SLF001 - exercise the generic observation-axis contract
    dataset.is_time_series = True

    scores = asyncio.run(PCANode("time-pca", _parameters()).execute(input_data=dataset)).outputs["scores"]

    assert isinstance(scores.axis(0), TimeAxis)
    assert scores.axis(0).units == "s"
    assert scores.is_time_series is True
    assert scores.feature_axis.labels is not None
    assert all(label.startswith("PC") for label in scores.feature_axis.labels)
    assert scores.units == "dimensionless"


def test_pca_state_and_feature_identity_fail_closed() -> None:
    dataset = _dataset()
    result = asyncio.run(PCANode("pca", _parameters()).execute(input_data=dataset))
    state = result.outputs["fitted_state"]

    corruptions: list[dict[str, object]] = []
    extra = copy.deepcopy(state)
    extra["unexpected"] = True
    corruptions.append(extra)
    wrong_schema = copy.deepcopy(state)
    wrong_schema["schema_version"] = "spectrasherpa.model.pca-state/0"
    corruptions.append(wrong_schema)
    wrong_contract = copy.deepcopy(state)
    wrong_contract["source_contract_digest"] = "0" * 64
    corruptions.append(wrong_contract)
    wrong_digest = copy.deepcopy(state)
    wrong_digest["state_content_digest"] = "0" * 64
    corruptions.append(wrong_digest)
    nonorthogonal = copy.deepcopy(state)
    nonorthogonal["arrays"]["loadings"][0] = nonorthogonal["arrays"]["loadings"][1]
    corruptions.append(nonorthogonal)

    for corrupted in corruptions:
        with pytest.raises(ValueError):
            validate_pca_fitted_state(corrupted)

    wrong_axis = dataset.copy()
    wrong_axis.feature_axis = FeatureAxis(
        values=np.asarray(dataset.feature_axis.values) + 0.5,
        labels=list(dataset.feature_axis.labels),
        units=dataset.feature_axis.units,
    )
    with pytest.raises(ValueError, match="feature axis"):
        apply_pca_fitted_state(wrong_axis, state)
    with pytest.raises(ValueError, match="closed schema"):
        asyncio.run(PCATransformNode("apply", {}).execute(X_new=dataset, model=object()))


def test_pca_application_allows_new_observation_count_but_binds_feature_space() -> None:
    calibration = _dataset(samples=36, features=18)
    state = asyncio.run(PCANode("pca", _parameters()).execute(input_data=calibration)).outputs["fitted_state"]
    application = _dataset(samples=7, features=18)

    scores = apply_pca_fitted_state(application, state)

    assert scores.shape == (7, 3)

    wrong_feature_count = _dataset(samples=7, features=17)
    with pytest.raises(ValueError, match="non-sample shape"):
        apply_pca_fitted_state(wrong_feature_count, state)


def test_pca_artifact_requires_current_dimensions_statistics_and_preprocessing_state() -> None:
    dataset = _dataset()
    artifact = asyncio.run(PCANode("pca", _parameters()).execute(input_data=dataset)).outputs["_model_artifact"]

    missing_variance = copy.deepcopy(artifact)
    del missing_variance["arrays"]["explained_variance"]
    with pytest.raises(ValueError, match="missing required current fields"):
        PCAExtract.from_artifact(missing_variance["metadata"], missing_variance["arrays"])

    missing_mean = copy.deepcopy(artifact)
    del missing_mean["arrays"]["mean"]
    with pytest.raises(ValueError, match="missing fitted preprocessing state"):
        PCAExtract.from_artifact(missing_mean["metadata"], missing_mean["arrays"])

    wrong_shape = copy.deepcopy(artifact)
    wrong_shape["arrays"]["loadings"] = wrong_shape["arrays"]["loadings"][:, :-1]
    with pytest.raises(ValueError, match="dimensions"):
        PCAExtract.from_artifact(wrong_shape["metadata"], wrong_shape["arrays"])

    standardized = asyncio.run(
        PCANode("pca-standard", _parameters(standardized=True)).execute(input_data=dataset)
    ).outputs["_model_artifact"]
    del standardized["arrays"]["center"]
    with pytest.raises(ValueError, match="missing fitted preprocessing state"):
        PCAExtract.from_artifact(standardized["metadata"], standardized["arrays"])


def test_pca_application_uses_only_the_serialized_state_without_spectrochempy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    state = asyncio.run(PCANode("pca", _parameters()).execute(input_data=dataset)).outputs["fitted_state"]
    monkeypatch.setattr("spectra_sherpa.interoperability.spectrochempy_adapter.import_module", None)

    applied = asyncio.run(PCATransformNode("apply", {}).execute(X_new=dataset, model=state))

    np.testing.assert_allclose(applied.outputs["scores"].data, apply_pca_fitted_state(dataset, state))


def test_pca_contract_and_native_authority_do_not_bind_scp_adapter() -> None:
    producer = node_registry.get_metadata("model.pca").resolved_execution_contract()
    application = node_registry.get_metadata("model.pca_transform").resolved_execution_contract()
    assert producer is not None and application is not None
    for contract in (producer, application):
        components = tuple(component["component_id"] for component in contract.payload["implementation_components"])
        requirements = tuple(requirement["distribution"] for requirement in contract.payload["runtime_requirements"])
        assert any(component.endswith(".app.lib.pca") for component in components)
        assert all("fitted_state" not in component for component in components)
        assert "spectrochempy" not in requirements


def test_pca_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples=180, features=160)
    node = PCANode("pca", _parameters(n_components="8"))
    asyncio.run(node.execute(input_data=dataset))

    with PerformanceCeiling("model.pca", "180x160-eight-components", 10.0).measure():
        asyncio.run(node.execute(input_data=dataset))


def test_pca_outlier_screen_stays_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples=180, features=160)
    result = asyncio.run(PCANode("pca", _parameters(n_components="8")).execute(input_data=dataset))
    decomposition = result.outputs["diagnostic_state"]
    assert len(decomposition["T2"]) == 180
    assert len(decomposition["Q"]) == 180
    assert np.isfinite(decomposition["T2"]).all()
    assert np.isfinite(decomposition["Q"]).all()
    _outlier_dispatch(decomposition)

    with PerformanceCeiling("diagnostics.outliers", "180x160-eight-components", 5.0).measure():
        outputs, diagnostics = _outlier_dispatch(decomposition)

    assert len(outputs["flags"]) == 180
    assert diagnostics["method"] == "hotelling_t2_q"
