"""Canonical FastICA scientific, lifecycle, projection, and cost proofs."""

from __future__ import annotations

import copy
import warnings

import numpy as np
import pytest
from sklearn.exceptions import ConvergenceWarning

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import FastICAExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling import ica_node as ica_module
from spectra_sherpa.app.services.dag.nodes.modeling.ica_node import (
    ICA_FITTED_STATE_SERIALIZER,
    FastICANode,
    _canonical_ica_parameters,
    _ica_scientific_core,
    apply_ica_fitted_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _parameters(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "n_components": 3,
        "algorithm": "parallel",
        "fun": "logcosh",
        "whiten": "unit-variance",
        "max_iter": 800,
        "tol": 1e-5,
        "random_seed": 42,
    }
    parameters.update(overrides)
    return parameters


def _dataset(
    *,
    samples: int = 240,
    features: int = 36,
    title: str = "Synthetic ICA contract mixture",
) -> SherpaDataset:
    rng = np.random.default_rng(20260812)
    axis = np.linspace(850.0, 1850.0, features)
    latent = np.column_stack(
        [
            rng.laplace(size=samples),
            rng.uniform(-np.sqrt(3.0), np.sqrt(3.0), size=samples),
            rng.standard_t(df=3.0, size=samples),
        ]
    )
    profiles = np.vstack(
        [
            np.exp(-0.5 * ((axis - 1050.0) / 65.0) ** 2),
            0.8 * np.exp(-0.5 * ((axis - 1370.0) / 85.0) ** 2),
            0.65 * np.exp(-0.5 * ((axis - 1650.0) / 55.0) ** 2),
        ]
    )
    matrix = 2.5 + latent @ profiles + rng.normal(0.0, 1e-5, size=(samples, features))
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, units="cm-1"),
        sample_axis=SampleAxis(labels=[f"mixture-{index:03d}" for index in range(samples)]),
        title=title,
    )


def test_ica_has_one_exact_local_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("model.ica")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "model.ica"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] == ICA_FITTED_STATE_SERIALIZER
    assert any("Hyvarinen" in citation for citation in contract.payload["citations"])
    assert metadata.requires_scp is False
    sources_port = next(port for port in metadata.output_ports if port.name == "sources")
    assert sources_port.type_ref == "spectrasherpa://types/ScoreMatrix/1.0"


def test_ica_parameter_contract_is_closed_and_seeded() -> None:
    assert _canonical_ica_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_components=True),
        _parameters(n_components=1),
        _parameters(n_components=51),
        _parameters(algorithm="symmetric"),
        _parameters(fun="kurtosis"),
        _parameters(whiten=True),
        _parameters(max_iter=49),
        _parameters(tol=float("nan")),
        _parameters(tol=0.2),
        _parameters(random_seed=-1),
        {**_parameters(), "whiten_solver": "eigh"},
    ):
        with pytest.raises(ValueError):
            _canonical_ica_parameters(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "samples", "features"),
    [
        pytest.param("NIR Shootout 2002 calibration", 155, 650, id="shootout-calibration"),
        pytest.param("Eigenvector CGL NIR", 231, 117, id="second-continuous-source"),
    ],
)
async def test_ica_convergence_failure_preserves_declared_method_and_guides_recovery(
    monkeypatch: pytest.MonkeyPatch,
    title: str,
    samples: int,
    features: int,
) -> None:
    class NonConvergingFastICA:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
            warnings.warn("did not converge", ConvergenceWarning, stacklevel=2)
            return np.zeros((matrix.shape[0], 3), dtype=np.float64)

    monkeypatch.setattr(ica_module, "FastICA", NonConvergingFastICA)

    node = FastICANode("fit_fastica", _parameters(max_iter=400, tol=0.0001))
    with pytest.raises(RuntimeError) as caught:
        await node.execute(
            input_data=_dataset(samples=samples, features=features, title=title),
        )

    message = str(caught.value)
    assert "algorithm=parallel" in message
    assert "contrast=logcosh" in message
    assert "n_components=3" in message
    assert "whiten=unit-variance" in message
    assert "max_iter=400" in message
    assert "tol=0.0001" in message
    assert "random_seed=42" in message
    assert "No component scores were accepted" in message
    assert "Increase Maximum Iterations up to 2000 first" in message
    assert "reduce Number of Components" in message
    assert "deflation algorithm" in message


def test_ica_refuses_components_above_centered_rank_before_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solver_started = False

    class SolverMustNotStart:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal solver_started
            solver_started = True

    monkeypatch.setattr(ica_module, "FastICA", SolverMustNotStart)

    with pytest.raises(RuntimeError) as caught:
        _ica_scientific_core(
            load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6"),
            parameters=_parameters(n_components=50, max_iter=50, tol=1e-8),
        )

    message = str(caught.value)
    assert solver_started is False
    assert "after centering 50 samples" in message
    assert "maximum identifiable component count is 49" in message
    assert "n_components=50" in message
    assert "max_iter=50" in message
    assert "tol=1e-08" in message
    assert "No component scores were accepted" in message
    assert "Reduce Number of Components to 49 or fewer first" in message


def test_ica_atmospheric_recovery_produces_replayable_three_component_scores() -> None:
    recovered = _ica_scientific_core(
        load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6"),
        parameters=_parameters(n_components=3, max_iter=400, tol=0.0001),
    )

    assert recovered["sources"].shape == (50, 3)
    assert 1 <= recovered["n_iter"] <= 400
    np.testing.assert_allclose(
        recovered["extract"].transform(recovered["data"]),
        recovered["sources"],
        rtol=1e-10,
        atol=1e-10,
    )


@pytest.mark.asyncio
async def test_ica_replay_validation_failure_preserves_settings_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_transform = FastICAExtract.transform

    def incompatible_replay(self: FastICAExtract, matrix: np.ndarray) -> np.ndarray:
        return original_transform(self, matrix) + 1e-3

    monkeypatch.setattr(FastICAExtract, "transform", incompatible_replay)

    node = FastICANode("fit_fastica", _parameters())
    result = None
    with pytest.raises(RuntimeError) as caught:
        result = await node.execute(input_data=_dataset())

    assert result is None
    message = str(caught.value)
    assert message == (
        "FastICA fitted-state replay validation failed under the declared settings "
        "(n_components=3, algorithm=parallel, contrast=logcosh, whiten=unit-variance, max_iter=800, "
        "tol=1e-05, random_seed=42). No component scores were accepted and downstream nodes were not run. "
        "Reduce Number of Components first; then increase Maximum Iterations up to 2000. If validation still "
        "fails, review preprocessing and deliberately try the deflation algorithm or a looser tolerance."
    )
    assert message.index("Reduce Number of Components first") < message.index("increase Maximum Iterations up to 2000")


@pytest.mark.asyncio
async def test_ica_live_generated_and_fitted_state_share_one_scientific_core() -> None:
    dataset = _dataset()
    node = FastICANode("ica", _parameters())

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["ica"]
    replay = apply_ica_fitted_state(dataset, live.outputs["fitted_state"])

    np.testing.assert_allclose(generated["sources"], live.outputs["sources"].data, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(generated["components"], live.outputs["components"].data, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(generated["mixing_matrix"], live.outputs["mixing_matrix"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["unmixing_matrix"], live.outputs["unmixing_matrix"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["residuals"], live.outputs["residuals"].data, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(replay, live.outputs["sources"].data, rtol=1e-12, atol=1e-12)
    reconstructed = live.outputs["sources"].data @ live.outputs["mixing_matrix"].T + np.asarray(
        live.outputs["fitted_state"]["arrays"]["mean"]
    )
    np.testing.assert_allclose(
        live.outputs["residuals"].data,
        np.asarray(dataset.X) - reconstructed,
        rtol=0.0,
        atol=1e-12,
    )
    assert generated["fitted_state"] == live.outputs["fitted_state"]
    assert generated["model"] == live.outputs["model"] == live.outputs["fitted_state"]
    assert live.outputs["components"].shape == (3, dataset.shape[1])
    assert live.outputs["mixing_matrix"].shape == (dataset.shape[1], 3)
    assert live.outputs["unmixing_matrix"].shape == (3, dataset.shape[1])
    assert live.outputs["components"].feature_axis.units == "cm-1"
    assert live.outputs["sources"].data_role == "X_features"
    assert live.outputs["sources"].feature_axis.title == "Independent Component"
    assert live.outputs["sources"].sample_axis.labels[0] == "mixture-000"
    assert live.diagnostics["random_seed"] == 42
    assert live.diagnostics["converged"] is True


def test_ica_seed_sign_and_order_are_repeatable() -> None:
    dataset = _dataset()
    first = _ica_scientific_core(dataset, parameters=_parameters())
    second = _ica_scientific_core(dataset, parameters=_parameters())

    np.testing.assert_allclose(first["sources"], second["sources"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(first["mixing"], second["mixing"], rtol=0.0, atol=0.0)
    for profile in first["mixing"].T:
        assert profile[int(np.argmax(np.abs(profile)))] > 0.0
    assert np.all(np.diff(first["contribution"]) <= 0.0)


def test_ica_fitted_state_fails_closed_on_identity_shape_and_numeric_corruption() -> None:
    dataset = _dataset()
    state = _ica_scientific_core(dataset, parameters=_parameters())["fitted_state"]
    corruptions: list[dict[str, object]] = []

    extra = copy.deepcopy(state)
    extra["unexpected"] = True
    corruptions.append(extra)
    wrong_serializer = copy.deepcopy(state)
    wrong_serializer["serializer"] = "spectrasherpa.model-artifact.fastica/0"
    corruptions.append(wrong_serializer)
    wrong_sign = copy.deepcopy(state)
    wrong_sign["metadata"]["sign_rule"] = "arbitrary"
    corruptions.append(wrong_sign)
    wrong_shape = copy.deepcopy(state)
    wrong_shape["arrays"]["mixing"] = [[1.0, 2.0]]
    corruptions.append(wrong_shape)
    nonfinite = copy.deepcopy(state)
    nonfinite["arrays"]["components"][0][0] = float("nan")
    corruptions.append(nonfinite)

    for corrupted in corruptions:
        with pytest.raises(ValueError):
            apply_ica_fitted_state(dataset, corrupted)
    with pytest.raises(ValueError, match="feature count"):
        apply_ica_fitted_state(np.ones((4, dataset.shape[1] + 1)), state)


def test_ica_artifact_round_trip_preserves_the_exact_unmixing_state() -> None:
    dataset = _dataset()
    core = _ica_scientific_core(dataset, parameters=_parameters())
    extract = core["extract"]
    metadata, arrays = extract.to_artifact()
    replay = FastICAExtract.from_artifact(metadata, arrays)

    np.testing.assert_allclose(replay.transform(dataset.X), core["sources"], rtol=1e-12, atol=1e-12)
    assert metadata["serializer"] == ICA_FITTED_STATE_SERIALIZER
    assert metadata["random_seed"] == 42
    assert set(arrays) == {"components", "mean", "mixing"}


def test_ica_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples=180, features=60)
    _ica_scientific_core(dataset, parameters=_parameters())

    with PerformanceCeiling("model.ica", "180x60-three-components", 5.0).measure():
        _ica_scientific_core(dataset, parameters=_parameters())
