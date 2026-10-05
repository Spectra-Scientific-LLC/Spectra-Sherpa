"""Scientific and execution-contract tests for canonical fitted EMSC."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node import (
    EMSCNode,
    _apply_emsc_state,
    _emsc_dispatch,
    _fit_emsc_state,
    _validated_emsc_state,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import ensure_registered_execution_contract
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact, validate_feature_contract
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, RuntimeFamily, WorkerCapability
from tests.performance_contract import PerformanceCeiling


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


AXIS = np.array([910.0, 945.0, 990.0, 1040.0, 1110.0, 1195.0, 1300.0, 1430.0])
REFERENCE = np.array([1.0, 0.3, 1.8, -0.4, 2.2, 0.7, 1.4, -0.2])
CONSTITUENT = np.array([0.2, -0.8, 0.5, 1.1, -0.3, 0.9, -1.0, 0.4])


def _dataset(rows: np.ndarray | list[list[float]], *, axis: np.ndarray | None = AXIS) -> SherpaDataset:
    feature_axis = None if axis is None else FeatureAxis(values=np.asarray(axis), units="cm-1")
    return SherpaDataset(X=np.asarray(rows, dtype=np.float64), feature_axis=feature_axis, data_role="X_spectra")


def _mixtures() -> np.ndarray:
    normalized = (AXIS - AXIS.mean()) / AXIS.std()
    rows = []
    for multiplier, offset, slope, curvature, interferent in (
        (1.8, 0.4, -0.2, 0.08, 0.7),
        (0.65, -0.3, 0.15, -0.04, -0.25),
    ):
        rows.append(
            multiplier * REFERENCE + offset + slope * normalized + curvature * normalized**2 + interferent * CONSTITUENT
        )
    return np.asarray(rows, dtype=np.float64)


def _fitted_state() -> dict[str, object]:
    return _fit_emsc_state(
        REFERENCE.reshape(1, -1),
        reference_method="first",
        poly_order=2,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
        constituents=CONSTITUENT.reshape(1, -1),
    )


def _scalar_apply_emsc_reference(data: np.ndarray, state: dict[str, object]) -> np.ndarray:
    """Literal pre-optimization row solver used as a numerical oracle."""

    matrix = np.asarray(data, dtype=np.float64)
    design, _reference, _axis, reference_column = _validated_emsc_state(state)
    nuisance_columns = [index for index in range(design.shape[1]) if index != reference_column]
    corrected = np.empty_like(matrix)
    for row_index, spectrum in enumerate(matrix):
        coefficients, _, _, _ = np.linalg.lstsq(design, spectrum, rcond=None)
        nuisance = design[:, nuisance_columns] @ coefficients[nuisance_columns]
        corrected[row_index] = (spectrum - nuisance) / coefficients[reference_column]
    return corrected


def test_fitted_reference_and_constituents_recover_the_scientific_reference() -> None:
    corrected = _apply_emsc_state(
        _mixtures(),
        _fitted_state(),
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )

    np.testing.assert_allclose(corrected, np.vstack([REFERENCE, REFERENCE]), rtol=1e-12, atol=1e-12)


def test_emsc_batch_solver_matches_the_literal_per_row_solver_and_decomposes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node as emsc_module

    rng = np.random.default_rng(20260810)
    base_rows = _mixtures()
    matrix = np.vstack([base_rows[index % 2] + rng.normal(scale=1e-8, size=AXIS.size) for index in range(64)])
    state = _fitted_state()
    expected = _scalar_apply_emsc_reference(matrix, state)

    original_lstsq = np.linalg.lstsq
    calls = 0

    def counted_lstsq(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_lstsq(*args, **kwargs)

    monkeypatch.setattr(emsc_module.np.linalg, "lstsq", counted_lstsq)
    actual = _apply_emsc_state(
        matrix,
        state,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )

    assert calls == 1
    np.testing.assert_allclose(actual, expected, rtol=5e-15, atol=5e-15)


def test_emsc_apply_requires_explicit_axis_identity_even_when_axis_is_absent() -> None:
    state = _fit_emsc_state(
        REFERENCE.reshape(1, -1),
        reference_method="first",
        poly_order=2,
        feature_axis_values=None,
        feature_axis_units=None,
    )
    with pytest.raises(TypeError, match="feature_axis_values"):
        _apply_emsc_state(_mixtures(), state)  # type: ignore[call-arg]

    corrected = _apply_emsc_state(
        _mixtures(),
        state,
        feature_axis_values=None,
        feature_axis_units=None,
    )
    assert corrected.shape == _mixtures().shape


def test_first_reference_row_is_explicitly_order_sensitive_in_the_catalog_and_state() -> None:
    reference_rows = np.vstack([REFERENCE, REFERENCE + 0.1 * CONSTITUENT])
    forward = _fit_emsc_state(
        reference_rows,
        reference_method="first",
        poly_order=2,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )
    reversed_rows = _fit_emsc_state(
        reference_rows[::-1],
        reference_method="first",
        poly_order=2,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )

    assert forward["reference_spectrum"] == REFERENCE.tolist()
    assert reversed_rows["reference_spectrum"] != forward["reference_spectrum"]
    parameter = next(item for item in EMSCNode.metadata.parameters if item.name == "reference_method")
    assert parameter.description is not None
    assert "first row" in parameter.description.lower()
    assert {option["value"]: option["label"] for option in parameter.options or []}["first"] == (
        "First reference row (order-sensitive)"
    )


def test_held_out_application_uses_training_state_without_refitting() -> None:
    training = _dataset(np.vstack([REFERENCE, REFERENCE + 0.05 * CONSTITUENT]))
    held_out = _dataset(_mixtures()[1:])
    node = EMSCNode("emsc", {"reference_method": "mean", "poly_order": 1})

    training_state = node.fit_fitted_state(training)
    frozen = node.apply_fitted_state(held_out, training_state)
    refitted = node.apply_fitted_state(held_out, node.fit_fitted_state(held_out))

    assert training_state["reference_spectrum"] == np.mean(training.X, axis=0).tolist()
    assert not np.allclose(frozen.X, refitted.X)


def test_workbench_reference_and_constituent_ports_use_the_same_fitted_abi() -> None:
    node = EMSCNode("emsc", {"reference_method": "first", "poly_order": 2})
    execution = asyncio.run(
        node.execute(
            default=_dataset(_mixtures()),
            reference=_dataset(REFERENCE.reshape(1, -1)),
            constituents=_dataset(CONSTITUENT.reshape(1, -1)),
        )
    )

    output = execution.outputs["default"]
    np.testing.assert_allclose(output.X, np.vstack([REFERENCE, REFERENCE]), rtol=1e-12, atol=1e-12)
    assert execution.diagnostics == {
        "reference_method": "first",
        "poly_order": 2,
        "n_constituents": 1,
        "fitted_state_serializer": "spectra.emsc-reference-json.v1",
    }
    step = output.provenance[-1]
    assert step.op_id == "preprocess.emsc"
    assert step.parameters["state_serializer"] == "spectra.emsc-reference-json.v1"
    assert json.loads(json.dumps(dict(step.parameters["transform_state"]), allow_nan=False))["feature_count"] == 8


def test_array_dispatch_and_generated_python_delegate_to_the_only_math_authority() -> None:
    index_axis = np.arange(AXIS.size, dtype=np.float64)
    normalized = (index_axis - index_axis.mean()) / index_axis.std()
    array_mixtures = np.vstack(
        [
            1.8 * REFERENCE + 0.4 - 0.2 * normalized + 0.08 * normalized**2 + 0.7 * CONSTITUENT,
            0.65 * REFERENCE - 0.3 + 0.15 * normalized - 0.04 * normalized**2 - 0.25 * CONSTITUENT,
        ]
    )
    expected = _emsc_dispatch(
        array_mixtures,
        reference_method="first",
        poly_order=2,
        reference_data=REFERENCE.reshape(1, -1),
        constituents_data=CONSTITUENT.reshape(1, -1),
    )
    np.testing.assert_allclose(expected, np.vstack([REFERENCE, REFERENCE]), rtol=1e-12, atol=1e-12)

    source = "\n".join(
        EMSCNode("emsc", {"reference_method": "first", "poly_order": 2}).generate_python(
            {"default": "application_data", "reference": "training_data", "constituents": "interferents"},
            use_scp=False,
        )
    )
    exported_source = (
        "def exported(application_data, training_data, interferents):\n"
        "    results = {}\n"
        f"{source}\n"
        "    return results['emsc']\n"
    )
    namespace: dict[str, object] = {}
    exec(compile(exported_source, "<preprocess.emsc export>", "exec"), namespace)
    assert "emsc_node import EMSCNode" in source
    assert "fit_fitted_state(training_data, interferents)" in source
    assert "apply_fitted_state(application_data, _state)" in source
    assert "np.linalg.lstsq" not in source

    application = _dataset(array_mixtures, axis=None)
    training = _dataset(REFERENCE.reshape(1, -1), axis=None)
    interferents = _dataset(CONSTITUENT.reshape(1, -1), axis=None)
    generated = namespace["exported"](application, training, interferents)  # type: ignore[operator]
    live = asyncio.run(
        EMSCNode("emsc", {"reference_method": "first", "poly_order": 2}).execute(
            default=application,
            reference=training,
            constituents=interferents,
        )
    ).outputs["default"]
    np.testing.assert_allclose(generated.X, live.X, rtol=1e-12, atol=1e-12)
    assert generated.data_role == live.data_role == application.data_role
    assert generated.get_feature_axis() == live.get_feature_axis() == application.get_feature_axis()


def test_artifact_application_replays_the_exact_fitted_state_authority() -> None:
    state = _fitted_state()
    chain = [
        {
            "op_id": "preprocess.emsc",
            "parameters": {
                "reference_method": "first",
                "poly_order": 2,
                "state_serializer": "spectra.emsc-reference-json.v1",
                "transform_state": state,
            },
        }
    ]

    source = _dataset(_mixtures())
    replayed, _, _, warnings = _prepare_X_for_artifact(
        _mixtures(),
        None,
        {"preprocessing_chain": chain},
        scope="all",
        source_dataset=source,
    )

    np.testing.assert_allclose(
        replayed,
        _apply_emsc_state(
            _mixtures(),
            state,
            feature_axis_values=AXIS,
            feature_axis_units="cm-1",
        ),
        rtol=1e-12,
        atol=1e-12,
    )
    assert warnings == []


def test_artifact_replay_requires_the_exact_full_fitted_axis() -> None:
    state = _fitted_state()
    chain = [
        {
            "op_id": "preprocess.emsc",
            "parameters": {
                "reference_method": "first",
                "poly_order": 2,
                "state_serializer": "spectra.emsc-reference-json.v1",
                "transform_state": state,
            },
        }
    ]

    sub_tolerance_axis = AXIS.copy()
    sub_tolerance_axis[-1] += 5.0e-7
    sub_tolerance_source = _dataset(_mixtures(), axis=sub_tolerance_axis)
    tolerant_manifest = {
        "n_features": AXIS.size,
        "feature_axis": AXIS.tolist(),
        "feature_axis_units": "cm-1",
        "preprocessing_chain": chain,
    }
    validate_feature_contract(_mixtures(), sub_tolerance_source, tolerant_manifest)
    with pytest.raises(ValueError, match="feature axis differs"):
        _prepare_X_for_artifact(
            _mixtures(),
            None,
            tolerant_manifest,
            scope="all",
            source_dataset=sub_tolerance_source,
        )

    mask = np.array([True, True, True, True, True, True, True, False])
    outside_mask_axis = AXIS.copy()
    outside_mask_axis[-1] += 10.0
    outside_mask_source = _dataset(_mixtures(), axis=outside_mask_axis)
    masked_manifest = {
        "n_features": int(mask.sum()),
        "feature_mask": mask.tolist(),
        "feature_axis": AXIS[mask].tolist(),
        "feature_axis_units": "cm-1",
        "preprocessing_chain": chain,
    }
    validate_feature_contract(_mixtures(), outside_mask_source, masked_manifest)
    with pytest.raises(ValueError, match="feature axis differs"):
        _prepare_X_for_artifact(
            _mixtures(),
            None,
            masked_manifest,
            scope="all",
            source_dataset=outside_mask_source,
        )

    mismatched_state = _fitted_state()
    mismatched_state["feature_axis_values"] = (AXIS + 0.25).tolist()
    mismatched_manifest = dict(tolerant_manifest)
    mismatched_manifest["preprocessing_chain"] = [
        {
            **chain[0],
            "parameters": {**chain[0]["parameters"], "transform_state": mismatched_state},
        }
    ]
    exact_source = _dataset(_mixtures())
    validate_feature_contract(_mixtures(), exact_source, mismatched_manifest)
    with pytest.raises(ValueError, match="feature axis differs"):
        _prepare_X_for_artifact(
            _mixtures(),
            None,
            mismatched_manifest,
            scope="all",
            source_dataset=exact_source,
        )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda state: state.update({"extra": True}), "closed serializer"),
        (lambda state: state.update({"reference_spectrum": [float("nan")] * 8}), "reference spectrum"),
        (lambda state: state.update({"feature_axis_units": "nm"}), "feature-axis units"),
        (lambda state: state.update({"reference_spectrum": [1.0] * 8}), "rank-deficient"),
    ],
)
def test_forged_or_incompatible_fitted_state_fails_closed(mutate, message: str) -> None:
    state = _fitted_state()
    mutate(state)
    with pytest.raises(ValueError, match=message):
        _apply_emsc_state(_mixtures(), state, feature_axis_values=AXIS, feature_axis_units="cm-1")


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("poly_order", True, "polynomial order"),
        ("poly_order", 2.0, "polynomial order"),
        ("feature_count", True, "feature count"),
        ("feature_axis_values", tuple(AXIS.tolist()), "feature axis"),
        ("feature_axis_values", AXIS.tolist()[:-1] + [True], "feature axis"),
        ("reference_spectrum", REFERENCE.astype(str).tolist(), "reference spectrum"),
        ("reference_spectrum", tuple(REFERENCE.tolist()), "reference spectrum"),
        ("constituent_spectra", [[]], "constituent spectra"),
        ("constituent_spectra", tuple(), "constituent spectra"),
        ("constituent_spectra", [CONSTITUENT.astype(str).tolist()], "constituent spectra"),
    ],
)
def test_fitted_state_accepts_only_its_canonical_json_representation(
    field: str,
    value: object,
    message: str,
) -> None:
    state = _fitted_state()
    state[field] = value
    with pytest.raises(ValueError, match=message):
        _apply_emsc_state(
            _mixtures(),
            state,
            feature_axis_values=AXIS,
            feature_axis_units="cm-1",
        )


def test_fitted_state_has_one_lossless_json_round_trip() -> None:
    state = _fitted_state()
    round_tripped = json.loads(json.dumps(state, allow_nan=False))

    assert round_tripped == state
    np.testing.assert_allclose(
        _apply_emsc_state(
            _mixtures(),
            round_tripped,
            feature_axis_values=AXIS,
            feature_axis_units="cm-1",
        ),
        np.vstack([REFERENCE, REFERENCE]),
        rtol=1e-12,
        atol=1e-12,
    )


def test_apply_rejects_axis_drift_and_unresolved_reference_coefficient() -> None:
    state = _fitted_state()
    with pytest.raises(ValueError, match="feature axis differs"):
        _apply_emsc_state(
            _mixtures(),
            state,
            feature_axis_values=AXIS + np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1]),
            feature_axis_units="cm-1",
        )

    normalized = (AXIS - AXIS.mean()) / AXIS.std()
    pure_nuisance = (0.3 + 0.2 * normalized - 0.1 * normalized**2 + 0.5 * CONSTITUENT).reshape(1, -1)
    with pytest.raises(ValueError, match="reference coefficient is unresolved"):
        _apply_emsc_state(
            pure_nuisance,
            state,
            feature_axis_values=AXIS,
            feature_axis_units="cm-1",
        )


def test_emsc_rejects_degenerate_fit_and_nonfinite_input() -> None:
    node = EMSCNode("emsc", {"reference_method": "mean", "poly_order": 2})
    with pytest.raises(ValueError, match="rank-deficient"):
        node.fit_fitted_state(_dataset(np.ones((3, 8))))
    with pytest.raises(ValueError, match="finite values"):
        node.fit_fitted_state(_dataset(np.array([[1.0, *([2.0] * 6), float("inf")]])))


def test_old_parameter_name_and_fractional_order_fail_closed() -> None:
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node("preprocess.emsc", "emsc", {"reference": "mean", "poly_order": 2})
    with pytest.raises(ValueError, match="exact integer"):
        node_registry.create_node("preprocess.emsc", "emsc", {"reference_method": "mean", "poly_order": 1.5})


def test_emsc_declares_one_complete_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("preprocess.emsc")
    contract = ensure_registered_execution_contract(metadata)

    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["fitted_state_serializer"] == "spectra.emsc-reference-json.v1"
    assert [port["name"] for port in contract.payload["semantic_inputs"]] == [
        "default",
        "reference",
        "constituents",
    ]
    assert contract.payload["semantic_outputs"][0]["accepted_data_roles"] == ("X_spectra",)
    assert contract.payload["managed_optimization_eligibility"] == ("local", "development", "full_refit")
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    admit_validation_graph([WorkflowNode("emsc", "preprocess.emsc", {"reference_method": "mean", "poly_order": 2})], [])


def test_model_application_rejects_incomplete_or_mismatched_emsc_records() -> None:
    state = _fitted_state()
    incomplete = [{"op_id": "preprocess.emsc", "parameters": {"transform_state": state}}]
    with pytest.raises(ValueError, match="complete canonical"):
        _prepare_X_for_artifact(
            _mixtures(),
            None,
            {"preprocessing_chain": incomplete},
            scope="all",
            source_dataset=_dataset(_mixtures()),
        )

    mismatched = [
        {
            "op_id": "preprocess.emsc",
            "parameters": {
                "reference_method": "mean",
                "poly_order": 2,
                "state_serializer": "spectra.emsc-reference-json.v1",
                "transform_state": state,
            },
        }
    ]
    with pytest.raises(ValueError, match="do not match"):
        _prepare_X_for_artifact(
            _mixtures(),
            None,
            {"preprocessing_chain": mismatched},
            scope="all",
            source_dataset=_dataset(_mixtures()),
        )


def test_emsc_executes_in_a_real_spawned_worker() -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-emsc",
        runtime=ExecutionRuntime(),
        capabilities=(WorkerCapability.READ_DATASET.value,),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "preprocess.emsc",
            "emsc",
            {"reference_method": "mean", "poly_order": 2},
            (),
            {"default": _dataset(_mixtures())},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    assert result.outputs["default"].shape == _mixtures().shape
    worker = result.diagnostics["worker_execution"]
    assert worker["mode"] == "spawned_worker"
    assert worker["origin_pid"] == os.getpid()
    assert worker["worker_pid"] != os.getpid()


def test_emsc_requires_its_declared_dataset_capability() -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-emsc-denied", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )
    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            "preprocess.emsc",
            "emsc",
            {"reference_method": "mean", "poly_order": 2},
            (),
            {"default": _dataset(_mixtures())},
            context,
        )


def test_emsc_representative_fit_and_application_have_absolute_ceilings() -> None:
    rng = np.random.default_rng(20260904)
    samples = 200
    features = 1_600
    axis = np.linspace(400.0, 4_000.0, features)
    reference = 0.8 + np.sin(axis / 230.0)
    matrix = rng.uniform(0.8, 1.2, size=(samples, 1)) * reference + rng.normal(scale=0.004, size=(samples, features))

    with PerformanceCeiling("preprocess.emsc", "emsc-200x1600-fit-and-apply", 5.0).measure():
        state = _fit_emsc_state(
            matrix,
            reference_method="mean",
            poly_order=2,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )
        corrected = _apply_emsc_state(
            matrix,
            state,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )

    with PerformanceCeiling("preprocess.apply_fitted_emsc", "emsc-200x1600-state-replay", 5.0).measure():
        replayed = _apply_emsc_state(
            matrix,
            state,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )

    assert corrected.shape == matrix.shape
    np.testing.assert_array_equal(replayed, corrected)
