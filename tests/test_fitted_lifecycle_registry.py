"""Registry-wide proof that live fitted execution and frozen-state replay agree.

Every operation that declares ``fitted_transform`` or ``fitted_model`` must
have one scientifically admissible case here.  The inventory assertion makes
adding a fitted operation without this proof a registry-level failure rather
than a convention left to the node author.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.core.dimension_roles import DimensionRole
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind
from tests._optional_scp import HAS_SCP


@dataclass(frozen=True)
class LifecycleInputs:
    execute_kwargs: dict[str, Any]
    fit_args: tuple[Any, ...]
    apply_input: Any


@dataclass(frozen=True)
class LifecycleCase:
    parameters: dict[str, Any]
    inputs: Callable[[], LifecycleInputs]
    output_port: str | None
    state_port: str | None = None
    atol: float = 1e-10
    rtol: float = 1e-10


def _dataset(matrix: np.ndarray, *, prefix: str = "sample") -> SherpaDataset:
    values = np.asarray(matrix, dtype=np.float64)
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, values.shape[1]), title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=[f"{prefix}-{index:03d}" for index in range(values.shape[0])]),
        data_role="X_spectra",
    )


def _regression_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026081701)
    matrix = rng.normal(size=(36, 18))
    target = 1.4 * matrix[:, 2] - 0.7 * matrix[:, 11] + rng.normal(scale=0.02, size=matrix.shape[0])
    dataset = _dataset(matrix)
    return LifecycleInputs(execute_kwargs={"X": dataset, "y": target}, fit_args=(dataset, target), apply_input=dataset)


def _pls_inputs() -> LifecycleInputs:
    case = _regression_inputs()
    return LifecycleInputs(
        execute_kwargs={"input_data": case.apply_input, "y": case.fit_args[1]},
        fit_args=case.fit_args,
        apply_input=case.apply_input,
    )


def _classification_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026081702)
    labels = np.repeat(np.asarray(["class-a", "class-b", "class-c"], dtype=object), 15)
    matrix = rng.normal(scale=0.15, size=(labels.size, 12))
    matrix[labels == "class-a", :3] += np.asarray([1.2, 0.3, -0.2])
    matrix[labels == "class-b", :3] += np.asarray([-0.2, 1.1, 0.4])
    matrix[labels == "class-c", :3] += np.asarray([0.2, -0.4, 1.3])
    dataset = _dataset(matrix)
    return LifecycleInputs(execute_kwargs={"X": dataset, "y": labels}, fit_args=(dataset, labels), apply_input=dataset)


def _cluster_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026081703)
    matrix = np.vstack([rng.normal(loc=center, scale=0.06, size=(12, 10)) for center in (-3.0, 0.0, 3.0)])
    dataset = _dataset(matrix)
    return LifecycleInputs(execute_kwargs={"input_data": dataset}, fit_args=(dataset,), apply_input=dataset)


def _positive_mixture_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026081704)
    axis = np.linspace(900.0, 1800.0, 24)
    spectra = np.vstack(
        [
            np.exp(-0.5 * ((axis - 1050.0) / 55.0) ** 2),
            0.8 * np.exp(-0.5 * ((axis - 1380.0) / 70.0) ** 2),
            0.6 * np.exp(-0.5 * ((axis - 1640.0) / 45.0) ** 2),
        ]
    )
    matrix = rng.uniform(0.05, 1.2, size=(32, 3)) @ spectra + 1e-5
    dataset = _dataset(matrix)
    return LifecycleInputs(execute_kwargs={"input_data": dataset}, fit_args=(dataset,), apply_input=dataset)


def _ica_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026081705)
    latent = np.column_stack([rng.laplace(size=90), rng.uniform(-1.0, 1.0, size=90), rng.standard_t(df=4.0, size=90)])
    matrix = latent @ rng.normal(size=(3, 18))
    dataset = _dataset(matrix)
    return LifecycleInputs(execute_kwargs={"input_data": dataset}, fit_args=(dataset,), apply_input=dataset)


def _parafac_inputs() -> LifecycleInputs:
    rng = np.random.default_rng(2026090401)
    factors = [rng.normal(size=(length, 2)) for length in (9, 5, 7)]
    values = np.einsum("ir,jr,kr->ijk", *factors)
    dataset = SherpaDataset(
        values,
        layout=DatasetLayoutContext(
            kind="batch",
            source_type="synthetic-multiway-lifecycle",
            source_dtype=values.dtype.str,
            source_shape=values.shape,
            mode_roles=(
                DimensionRole.SAMPLE,
                DimensionRole.TIME_POINT,
                DimensionRole.SPECTRAL_VARIABLE,
            ),
        ),
    )
    return LifecycleInputs(execute_kwargs={"input_data": dataset}, fit_args=(dataset,), apply_input=dataset)


def _preprocess_inputs(*, supervised: bool = False) -> LifecycleInputs:
    rng = np.random.default_rng(2026081706)
    axis = np.linspace(-1.0, 1.0, 18)
    target = np.linspace(-1.0, 1.0, 30)
    matrix = np.vstack(
        [
            1.0 + 0.15 * target[index] * axis + 0.04 * axis**2 + rng.normal(scale=0.002, size=axis.size)
            for index in range(target.size)
        ]
    )
    dataset = _dataset(matrix)
    if supervised:
        return LifecycleInputs(
            execute_kwargs={"default": dataset, "y": target},
            fit_args=(dataset, target),
            apply_input=dataset,
        )
    return LifecycleInputs(execute_kwargs={"default": dataset}, fit_args=(dataset,), apply_input=dataset)


def _transfer_inputs(kind: str) -> LifecycleInputs:
    rng = np.random.default_rng(2026081707)
    if kind == "ds":
        secondary = rng.normal(size=(40, 8))
        primary = secondary @ rng.normal(size=(8, 6))
    else:
        latent = rng.normal(size=(40, 3))
        secondary = latent @ rng.normal(size=(3, 18))
        primary = secondary * np.linspace(0.85, 1.15, 18) + np.linspace(-0.04, 0.06, 18)
    primary_dataset = _dataset(primary, prefix="standard")
    secondary_dataset = _dataset(secondary, prefix="standard")
    return LifecycleInputs(
        execute_kwargs={"X_primary": primary_dataset, "X_secondary": secondary_dataset},
        fit_args=(primary_dataset, secondary_dataset),
        apply_input=secondary_dataset,
    )


_CASES: dict[str, LifecycleCase] = {
    "classification.knn": LifecycleCase(
        {"n_neighbors": 5, "weights": "uniform", "metric": "euclidean", "scale": True},
        _classification_inputs,
        None,
        "fitted_state",
    ),
    "classification.plsda": LifecycleCase(
        {"n_components": 2, "scale": False}, _classification_inputs, None, "fitted_state"
    ),
    "classification.simca": LifecycleCase(
        {"n_components": 2, "confidence_level": 0.95, "critical_limits_method": "ddmoments"},
        _classification_inputs,
        None,
        "fitted_state",
    ),
    "model.dbscan": LifecycleCase({"eps": 0.45, "min_samples": 4, "metric": "euclidean"}, _cluster_inputs, "labels"),
    "model.fitted_pls": LifecycleCase({"n_components": 3}, _pls_inputs, "default"),
    "model.fitted_pcr": LifecycleCase({"n_components": 3}, _pls_inputs, "default"),
    "model.fitted_svr": LifecycleCase({"kernel": "rbf"}, _pls_inputs, "default"),
    "model.fitted_linear_regression": LifecycleCase({"fit_intercept": True}, _pls_inputs, "default"),
    "model.hca": LifecycleCase({"n_clusters": 3, "linkage": "ward", "metric": "euclidean"}, _cluster_inputs, "labels"),
    "model.ica": LifecycleCase(
        {
            "n_components": 3,
            "algorithm": "parallel",
            "fun": "logcosh",
            "whiten": "unit-variance",
            "max_iter": 800,
            "tol": 1e-5,
            "random_seed": 42,
        },
        _ica_inputs,
        "sources",
    ),
    "model.kmeans": LifecycleCase(
        {"n_clusters": 3, "n_init": 10, "max_iter": 300, "random_state": 42}, _cluster_inputs, "labels"
    ),
    "model.linear_regression": LifecycleCase({"fit_intercept": True}, _regression_inputs, "predictions"),
    "model.mcr_als": LifecycleCase(
        {
            "n_components": 3,
            "non_negative_C": True,
            "non_negative_St": True,
            "max_iter": 80,
            "tol": 1e-5,
            "normSpec": "euclid",
            "validation_target_index": 1,
            "validation_component_index": 1,
        },
        _positive_mixture_inputs,
        None,
        "fitted_state",
    ),
    "model.nmf": LifecycleCase(
        {"n_components": 3, "solver": "mu", "max_iter": 1000, "tol": 1e-5, "random_state": 42},
        _positive_mixture_inputs,
        None,
        "model",
    ),
    "model.pca": LifecycleCase({"n_components": "3", "standardized": False, "scaled": False}, _ica_inputs, "scores"),
    "model.parafac": LifecycleCase(
        {"n_components": 2, "max_iter": 200, "tol": 1e-8, "ridge": 1e-12},
        _parafac_inputs,
        "sample_scores",
    ),
    "model.pcr": LifecycleCase({"n_components": 3, "scale": True}, _regression_inputs, "y_pred"),
    "model.svr": LifecycleCase(
        {
            "kernel": "rbf",
            "C": 3.0,
            "epsilon": 0.05,
            "gamma": "scale",
            "degree": 3,
            "coef0": 0.0,
            "target_index": 1,
            "scale": True,
        },
        _regression_inputs,
        "predictions",
    ),
    "preprocess.emsc": LifecycleCase({"reference_method": "mean", "poly_order": 1}, _preprocess_inputs, "default"),
    "preprocess.msc": LifecycleCase({"reference_method": "mean"}, _preprocess_inputs, "default"),
    "preprocess.osc": LifecycleCase({"n_components": 1}, lambda: _preprocess_inputs(supervised=True), "default"),
    "preprocess.scale": LifecycleCase({"method": "autoscale", "center": True}, _preprocess_inputs, "default"),
    "selection.cars": LifecycleCase(
        {"n_iterations": 10, "max_components": 2, "cv_folds": 3, "calibration_fraction": 0.75, "random_seed": 619},
        _regression_inputs,
        "X_selected",
    ),
    "selection.ipls": LifecycleCase(
        {"n_intervals": 6, "max_components": 3, "cv_folds": 4, "random_seed": 113},
        _regression_inputs,
        "X_selected",
    ),
    "selection.mcuve": LifecycleCase(
        {"n_components": 2, "n_resamples": 20, "calibration_fraction": 0.75, "n_variables": 6, "random_seed": 719},
        _regression_inputs,
        "X_selected",
    ),
    "selection.spa": LifecycleCase(
        {"max_variables": 5, "cv_folds": 3, "random_seed": 8}, _regression_inputs, "X_selected"
    ),
    "selection.stability": LifecycleCase(
        {
            "base_method": "coef_abs",
            "base_threshold": 0.1,
            "selection_probability_threshold": 0.6,
            "n_resamples": 20,
            "n_components": 2,
            "random_seed": 719,
        },
        _regression_inputs,
        "X_selected",
    ),
    "transfer.ds": LifecycleCase({}, lambda: _transfer_inputs("ds"), "X_standardized"),
    "transfer.pds": LifecycleCase(
        {"half_window": 3, "n_components": 2}, lambda: _transfer_inputs("pds"), "X_standardized"
    ),
    "transfer.sws": LifecycleCase({}, lambda: _transfer_inputs("sws"), "X_standardized"),
}


def _registered_fitted_operations() -> set[str]:
    fitted = {LifecycleKind.FITTED_MODEL.value, LifecycleKind.FITTED_TRANSFORM.value}
    return {
        metadata.node_type
        for metadata in node_registry.list_nodes()
        if metadata.resolved_execution_contract().payload["lifecycle_kind"] in fitted
    }


def _values(value: Any) -> np.ndarray:
    if isinstance(value, SherpaDataset):
        return np.asarray(value.X)
    if hasattr(value, "data") and not isinstance(value, (dict, str, bytes)):
        return np.asarray(value.data)
    return np.asarray(value)


def test_fitted_lifecycle_cases_exactly_cover_the_live_registry() -> None:
    assert set(_CASES) == _registered_fitted_operations()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_id", sorted(_CASES))
async def test_live_fitted_execution_equals_frozen_state_replay(operation_id: str) -> None:
    metadata = node_registry.get_metadata(operation_id)
    if metadata.requires_scp and not HAS_SCP:
        pytest.skip(f"{operation_id} requires the optional SpectroChemPy runtime")

    case = _CASES[operation_id]
    inputs = case.inputs()
    live_node = node_registry.create_node(operation_id, f"{operation_id}-live", case.parameters)
    replay_node = node_registry.create_node(operation_id, f"{operation_id}-replay", case.parameters)

    live = await live_node.execute(**inputs.execute_kwargs)
    outputs = live.outputs if isinstance(live, NodeResult) else live
    assert isinstance(outputs, dict)
    state = replay_node.fit_fitted_state(*inputs.fit_args)
    replayed = replay_node.apply_fitted_state(inputs.apply_input, state)

    # Classification producer outputs are deliberately out-of-fold validation
    # predictions, not full-fit application predictions. NMF/MCR training
    # concentrations come from joint fitting and need not equal a later frozen-
    # basis projection. For those nodes the identity under review is the live
    # fitted-state port versus the separately fitted state, both replayed on the
    # same application input. Other producers expose the corresponding live
    # full-fit application value directly.
    if case.output_port is not None:
        actual_value = outputs[case.output_port]
    else:
        assert case.state_port is not None
        actual_value = live_node.apply_fitted_state(inputs.apply_input, outputs[case.state_port])
    actual = _values(actual_value)
    expected = _values(replayed)
    assert actual.shape == expected.shape
    if np.issubdtype(actual.dtype, np.number) and np.issubdtype(expected.dtype, np.number):
        np.testing.assert_allclose(actual, expected, rtol=case.rtol, atol=case.atol)
    else:
        np.testing.assert_array_equal(actual, expected)
