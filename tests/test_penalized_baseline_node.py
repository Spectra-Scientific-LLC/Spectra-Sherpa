"""Canonical contract and numerical-path tests for penalized-LS baselines."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
import spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node as baseline_module
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node import (
    BaselinePenalizedLSNode,
    _penalized_baseline_dispatch,
)
from spectra_sherpa.app.services.model_application import _apply_penalized_baseline_step
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk.preprocess import baseline_als
from tests.performance_contract import PerformanceCeiling


def _spectra() -> SherpaDataset:
    axis = np.linspace(0.0, 1.0, 160)
    rows = np.vstack(
        [
            0.2 + 0.7 * axis + np.exp(-(((axis - 0.35) / 0.045) ** 2)),
            0.5 + 0.3 * axis + 0.8 * np.exp(-(((axis - 0.70) / 0.060) ** 2)),
        ]
    )
    return SherpaDataset(X=rows, units="absorbance", data_role="X_spectra")


def _parameters(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "method": "als",
        "lam": 100_000.0,
        "p": 0.001,
        "max_iter": 100,
        "tol": 1e-6,
    }
    payload.update(updates)
    return payload


def test_penalized_baseline_has_one_closed_managed_execution_contract() -> None:
    metadata = node_registry.get_metadata("baseline.penalized_ls")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "baseline.penalized_ls"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.baseline.penalized_ls"
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert metadata.input_types == ["SpectralDataset"]
    assert metadata.output_type == "SpectralDataset"
    assert metadata.input_ports[0].accepted_data_roles == ["X_spectra"]
    assert metadata.output_ports[0].accepted_data_roles == ["X_spectra"]


def test_admission_preserves_the_exact_explicit_parameter_record() -> None:
    node = node_registry.create_node(
        "baseline.penalized_ls",
        "baseline",
        _parameters(lam=12_345.0, p=0.017, max_iter=125, tol=2e-7),
    )

    assert node.parameters == {
        "method": "als",
        "lam": 12_345.0,
        "p": 0.017,
        "max_iter": 125,
        "tol": 2e-7,
    }


@pytest.mark.parametrize(
    "parameters",
    [
        _parameters(method="asls"),
        _parameters(lam=99.0),
        _parameters(lam=float("nan")),
        _parameters(p=0.0),
        _parameters(method="arpls", p=0.01),
        _parameters(max_iter=True),
        _parameters(max_iter=10.5),
        _parameters(max_iter=4),
        _parameters(tol=0.0),
        _parameters(tol=float("inf")),
        {**_parameters(), "automatic_technique": "nir"},
    ],
)
def test_admission_rejects_aliases_coercion_irrelevant_and_hidden_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("baseline.penalized_ls", "baseline", parameters)


@pytest.mark.parametrize("method", ["als", "arpls", "airpls"])
def test_each_algorithm_returns_finite_correction_and_convergence_evidence(method: str) -> None:
    source = _spectra()

    corrected, diagnostics = _penalized_baseline_dispatch(
        source.X,
        **_parameters(method=method),
    )

    assert corrected.shape == source.X.shape
    assert np.isfinite(corrected).all()
    assert diagnostics["algorithm"] == method
    assert diagnostics["converged_spectra"] == source.n_samples
    assert diagnostics["nonconverged_spectra"] == 0
    assert 0 <= diagnostics["maximum_iterations_used"] <= 100
    assert diagnostics["input_feature_count"] == source.n_features
    assert diagnostics["maximum_absolute_correction"] > 0.0


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        (
            "als",
            [
                0.03079251563072538,
                -0.0023392716788399603,
                2.464528633086438,
                0.031419291325474275,
                0.19833111915085344,
                0.3152622184822469,
                0.13220870792813377,
                -0.0008364465251928799,
            ],
        ),
        (
            "arpls",
            [
                0.009048662232520543,
                -0.021514835228779283,
                2.4478320778131986,
                0.01721494491746478,
                0.18675930964303022,
                0.30642479776836784,
                0.12617103507189076,
                -0.004042352667989135,
            ],
        ),
        (
            "airpls",
            [
                5.459237173432996e-08,
                -6.369110039372572e-08,
                2.486813056431406,
                0.06263720855889354,
                0.22967018629036562,
                0.3401097832248261,
                0.14615379296127928,
                9.09872865939576e-09,
            ],
        ),
    ],
)
def test_each_algorithm_matches_its_frozen_numerical_reference(
    method: str,
    expected: list[float],
) -> None:
    """Anchor the reviewed recurrences, not merely their shared call paths."""

    spectrum = np.array([1.2, 1.25, 3.8, 1.45, 1.7, 1.9, 1.8, 1.75])
    corrected, _diagnostics = _penalized_baseline_dispatch(
        spectrum,
        method=method,
        lam=100.0,
        p=0.001,
        max_iter=1000,
        tol=1e-8,
    )

    np.testing.assert_allclose(corrected, expected, rtol=2e-8, atol=2e-8)


@pytest.mark.parametrize(
    "data",
    [
        np.array([1.0, 2.0]),
        np.array([[1.0, float("nan"), 3.0]]),
        np.empty((0, 5)),
        np.empty((1, 2, 3)),
    ],
)
def test_dispatch_rejects_unusable_or_nonfinite_spectra(data: np.ndarray) -> None:
    with pytest.raises(ValueError):
        _penalized_baseline_dispatch(data, **_parameters())


def test_nonconvergence_is_an_error_not_a_silent_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def _never_converges(spectrum, **kwargs):
        del kwargs
        return np.zeros_like(spectrum), 5, False

    monkeypatch.setattr(baseline_module, "_fit_als", _never_converges)

    with pytest.raises(ValueError, match="did not converge"):
        _penalized_baseline_dispatch(_spectra().X, **_parameters(max_iter=5))


def test_node_sdk_generated_python_and_artifact_replay_share_one_dispatcher() -> None:
    source = _spectra()
    parameters = _parameters()
    expected, expected_diagnostics = _penalized_baseline_dispatch(source.X, **parameters)

    node = BaselinePenalizedLSNode("baseline", parameters)
    node_result = asyncio.run(node.execute(input_data=source))
    sdk_result = baseline_als(
        source,
        lam=float(parameters["lam"]),
        p=float(parameters["p"]),
        max_iter=int(parameters["max_iter"]),
        tol=float(parameters["tol"]),
    )
    replayed = _apply_penalized_baseline_step(source.X, parameters)

    generated_source = "\n".join(node.generate_python({"default": "source"}, indent="", use_scp=False))
    namespace = {"np": np, "results": {}, "source": source}
    exec(compile(generated_source, "<baseline.penalized_ls export>", "exec"), namespace)
    generated = namespace["results"]["baseline"]

    np.testing.assert_allclose(node_result.outputs["default"].X, expected)
    np.testing.assert_allclose(sdk_result.X, expected)
    np.testing.assert_allclose(replayed, expected)
    np.testing.assert_allclose(generated.X, expected)
    assert node_result.diagnostics == expected_diagnostics
    assert dict(node_result.outputs["default"].provenance[-1].parameters) == parameters
    assert dict(sdk_result.provenance[-1].parameters) == parameters
    assert dict(generated.provenance[-1].parameters) == parameters
    assert generated.provenance[-1].node_id == "baseline"
    assert sdk_result.meta["baseline_diagnostics"] == expected_diagnostics
    assert generated.meta["baseline_diagnostics"] == expected_diagnostics
    assert node_result.outputs["default"].feature_axis == source.feature_axis
    assert generated.data_role == "X_spectra"


def test_managed_penalized_baseline_workload_completes_within_shared_ceiling() -> None:
    axis = np.linspace(0.0, 1.0, 400)
    matrix = np.vstack(
        [0.15 + 0.6 * axis + np.exp(-(((axis - center) / 0.04) ** 2)) for center in np.linspace(0.2, 0.8, 20)]
    )

    with PerformanceCeiling("baseline.penalized_ls", "als-20x400", 5.0).measure():
        corrected, diagnostics = _penalized_baseline_dispatch(
            matrix,
            method="als",
            lam=100_000.0,
            p=0.001,
            max_iter=100,
            tol=1e-6,
        )

    assert corrected.shape == matrix.shape
    assert diagnostics["converged_spectra"] == 20
