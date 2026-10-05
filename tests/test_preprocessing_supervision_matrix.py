"""Sample-table authority must survive every sample-preserving preprocessing path."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    attach_sample_table_supervision,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

CASES = [
    *[("time_series.trend_removal", {"method": m}) for m in ("linear", "polynomial", "difference", "moving_average")],
    ("preprocess.clip_range", {"minimum": 1200, "maximum": 1700}),
    ("preprocess.clip_floor", {"floor": 0.5}),
    ("preprocess.cosmic_ray", {}),
    *[("preprocess.wavenumber_align", {"method": m}) for m in ("pchip", "linear", "sinc")],
    ("baseline.rubberband", {}),
    *[("baseline.penalized_ls", {"method": m, "max_iter": 100, "tol": 1e-3}) for m in ("als", "arpls", "airpls")],
    *[("preprocess.scale", {"method": m}) for m in ("mean_center", "autoscale", "pareto")],
    ("preprocess.normalize", {"method": "snv"}),
    *[("preprocess.normalize", {"method": "scale", "scale_method": m}) for m in ("max", "area", "minmax")],
    *[("preprocess.smooth", {"method": m}) for m in ("savitzky_golay", "whittaker", "gaussian")],
    *[
        ("preprocess.derivative", {"method": m, "deriv": d})
        for m in ("savitzky_golay", "norris_williams")
        for d in ("1", "2")
    ],
    *[("preprocess.msc", {"reference_method": m}) for m in ("mean", "median", "first")],
    *[("preprocess.emsc", {"reference_method": m}) for m in ("mean", "median", "first")],
    ("preprocess.osc", {}),
]
CASE_IDS = [f"{kind}-{'-'.join(str(v) for v in params.values()) or 'default'}" for kind, params in CASES]
FITTED = ["preprocess.scale", "preprocess.msc", "preprocess.emsc", "preprocess.osc"]


@pytest.fixture(autouse=True)
def _types():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


def _dataset(continuous=False, grouped=True, seed=21):
    rng = np.random.default_rng(seed)
    axis = np.linspace(1800, 1000, 81)
    concentration = np.linspace(0.5, 2.0, 24)
    matrix = (
        0.2
        + concentration[:, None] * np.exp(-(((axis - 1450) / 75) ** 2))
        + rng.uniform(0.2, 0.6, (24, 1)) * np.exp(-(((axis - 1200) / 45) ** 2))
        + rng.normal(0, 0.002, (24, 81))
    )
    labels = [f"specimen-{seed}-{i}" for i in range(24)]
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "response": concentration.tolist() if continuous else ["A", "B"] * 12,
                "batch": [i // 4 for i in range(24)],
            },
        ),
        units="absorbance",
        data_role="X_spectra",
        extra={
            "source_collection": {
                "manifest_digest": "a" * 64,
                "collection_definition_sha256": "b" * 64,
                "scientific_collection_sha256": "c" * 64,
            }
        },
    )
    return attach_sample_table_supervision(
        dataset,
        target_column="response",
        target_type="continuous" if continuous else "categorical",
        group_column="batch" if grouped else None,
        node_id="attach",
    )


def _assert_binding(source, result):
    before = admit_attached_sample_table_supervision(source)
    after = admit_attached_sample_table_supervision(result)
    assert before is not None and after is not None
    for key in before.record:
        if key != "dataset_scientific_projection_sha256":
            assert before.record[key] == after.record[key], key
    np.testing.assert_array_equal(source.target, result.target)
    np.testing.assert_array_equal(before.groups, after.groups)
    assert source.sample_axis.model_dump() == result.sample_axis.model_dump()
    assert np.isfinite(result.X).all()


async def _execute(node, source, exported):
    inputs = {"default": "source"}
    kwargs = {"input_data": source}
    reference = source[:, 2:-2]
    if node.metadata.node_type == "preprocess.wavenumber_align":
        inputs = {"spectra": "source", "reference": "reference"}
        kwargs = {"spectra": source, "reference": reference}
    if exported:
        namespace = {"np": np, "source": source, "reference": reference, "results": {}}
        exec("\n".join(node.generate_python(inputs, indent="", use_scp=False)), namespace)  # noqa: S102
        return namespace["results"][node.node_id]
    return NodeResult.wrap(await node.execute(**kwargs)).outputs["default"]


@pytest.mark.parametrize("kind,params", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("grouped", [False, True], ids=["target", "target-and-groups"])
@pytest.mark.parametrize("exported", [False, True], ids=["live", "python-export"])
@pytest.mark.asyncio
async def test_preprocessing_preserves_exact_supervision(kind, params, grouped, exported):
    source = _dataset(continuous=kind == "preprocess.osc", grouped=grouped)
    node = node_registry.create_node(kind, "transform", params)
    original = source.meta["supervision_binding"].copy()
    result = await _execute(node, source, exported)
    _assert_binding(source, result)
    assert source.meta["supervision_binding"] == original


@pytest.mark.parametrize("kind,params", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("exported", [False, True], ids=["live", "python-export"])
@pytest.mark.asyncio
async def test_preprocessing_rejects_stale_input_binding(kind, params, exported):
    source = _dataset(continuous=kind == "preprocess.osc")
    source.X[0, 0] += 0.01
    node = node_registry.create_node(kind, "transform", params)
    with pytest.raises(ValueError, match="does not match"):
        await _execute(node, source, exported)


@pytest.mark.parametrize("kind,params", CASES, ids=CASE_IDS)
@pytest.mark.asyncio
async def test_export_has_the_same_scientific_result_and_binding(kind, params):
    source = _dataset(continuous=kind == "preprocess.osc")
    node = node_registry.create_node(kind, "transform", params)
    live = await _execute(node, source, False)
    exported = await _execute(node, source, True)
    np.testing.assert_array_equal(live.X, exported.X)
    assert live.scientific_projection(include_provenance=False) == exported.scientific_projection(
        include_provenance=False
    )
    assert live.meta["supervision_binding"] == exported.meta["supervision_binding"]


@pytest.mark.parametrize("exported", [False, True], ids=["live", "python-export"])
@pytest.mark.asyncio
async def test_serial_preprocessing_keeps_target_and_group_decisions(exported):
    source = _dataset()
    current = source
    for i, (kind, params) in enumerate(
        [
            ("preprocess.clip_range", {"minimum": 1100, "maximum": 1750}),
            ("preprocess.smooth", {}),
            ("preprocess.derivative", {}),
            ("preprocess.normalize", {}),
        ]
    ):
        node = node_registry.create_node(kind, f"step_{i}", params)
        current = await _execute(node, current, exported)
        _assert_binding(source, current)


@pytest.mark.parametrize("kind", FITTED)
def test_held_out_fitted_application_preserves_its_own_supervision(kind):
    train = _dataset(continuous=kind == "preprocess.osc")
    held_out = _dataset(continuous=kind == "preprocess.osc", seed=22)
    node = node_registry.create_node(kind, "transform", {})
    state = node.fit_fitted_state(train, train.target) if kind == "preprocess.osc" else node.fit_fitted_state(train)
    result = node.apply_fitted_state(held_out, state)
    _assert_binding(held_out, result)
    assert result.sample_axis.labels != train.sample_axis.labels


def test_matrix_covers_every_preprocessing_implementation():
    covered = {kind for kind, _ in CASES} | {
        "preprocess.apply_fitted_scale",
        "preprocess.apply_fitted_msc",
        "preprocess.apply_fitted_emsc",
        "preprocess.apply_fitted_osc",
        "time_series.moving_window",
        "transfer.ds",
        "transfer.pds",
        "transfer.sws",
        "transfer.apply_fitted",
    }
    # This is an implementation-coverage matrix, not a catalog-placement test.
    # Raw metadata keeps the shared execution family while the scientist-facing
    # catalog gives calibration transfer and time series their own families.
    registered = {meta.node_type for meta in node_registry.list_nodes() if meta.category == "preprocessing"}
    assert registered == covered


@pytest.mark.parametrize("aggregation", ["none", "mean", "median", "std"])
@pytest.mark.parametrize("exported", [False, True], ids=["live", "python-export"])
@pytest.mark.asyncio
async def test_generated_windows_retire_original_sample_supervision(aggregation, exported):
    source = _dataset()
    node = node_registry.create_node(
        "time_series.moving_window",
        "window",
        {
            "window_size": 4,
            "step_size": 2,
            "aggregation": aggregation,
        },
    )
    result = await _execute(node, source, exported)
    assert result.target is None
    assert result.target_context.target_type is None
    assert admit_attached_sample_table_supervision(result) is None
    assert result.sample_axis.sample_table is None
    assert result.meta["time_series_windows"]["source_supervision_binding_sha256"] == (
        source.meta["supervision_binding"]["supervision_binding_sha256"]
    )
    source.X[0, 0] += 0.01
    with pytest.raises(ValueError, match="does not match"):
        await _execute(node, source, exported)


def _attach_transfer_supervision(dataset):
    axis = dataset.sample_axis.model_copy(deep=True)
    axis.sample_table = {
        "sample_id": list(axis.labels),
        "class": ["A" if i % 2 else "B" for i in range(dataset.n_samples)],
        "batch": [i // 3 for i in range(dataset.n_samples)],
    }
    dataset.sample_axis = axis
    dataset.meta["source_collection"] = {
        "manifest_digest": "a" * 64,
        "collection_definition_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    return attach_sample_table_supervision(
        dataset,
        target_column="class",
        target_type="categorical",
        group_column="batch",
        node_id="attach",
    )


@pytest.mark.parametrize("kind", ["ds", "pds", "sws"])
@pytest.mark.parametrize("exported", [False, True], ids=["live", "python-export"])
@pytest.mark.asyncio
async def test_transfer_and_application_preserve_secondary_sample_supervision(kind, exported):
    from tests.test_transfer_nodes import _ds_case, _pds_case, _sws_case

    primary, secondary, held_out, *_ = {"ds": _ds_case, "pds": _pds_case, "sws": _sws_case}[kind]()
    secondary = _attach_transfer_supervision(secondary)
    held_out = _attach_transfer_supervision(held_out)
    node = node_registry.create_node(f"transfer.{kind}", "fit", {})
    if exported:
        namespace = {"primary": primary, "secondary": secondary, "results": {}}
        exec(
            "\n".join(
                node.generate_python(
                    {"X_primary": "primary", "X_secondary": "secondary"},
                    indent="",
                    use_scp=False,
                )
            ),
            namespace,
        )  # noqa: S102
        outputs = namespace["results"]["fit"]
    else:
        outputs = (await node.execute(X_primary=primary, X_secondary=secondary)).outputs
    _assert_binding(secondary, outputs["X_standardized"])
    application = node_registry.create_node("transfer.apply_fitted", "apply", {})
    state = outputs["fitted_state"]

    async def apply():
        if exported:
            namespace = {"source": held_out, "state": state, "results": {}}
            exec(
                "\n".join(
                    application.generate_python(
                        {"default": "source", "fitted_state": "state"},
                        indent="",
                        use_scp=False,
                    )
                ),
                namespace,
            )  # noqa: S102
            return namespace["results"]["apply"]["default"]
        return (await application.execute(input_data=held_out, fitted_state=state)).outputs["default"]

    _assert_binding(held_out, await apply())
    held_out.X[0, 0] += 0.01
    with pytest.raises(ValueError, match="does not match"):
        await apply()


@pytest.mark.parametrize("kind", FITTED)
@pytest.mark.parametrize("tampered", [False, True], ids=["valid", "stale"])
@pytest.mark.asyncio
async def test_artifact_application_uses_the_same_supervision_finalization(kind, tampered):
    train = _dataset(continuous=kind == "preprocess.osc")
    held_out = _dataset(continuous=kind == "preprocess.osc", seed=22)
    producer = node_registry.create_node(kind, "fit", {})
    state = (
        producer.fit_fitted_state(train, train.target) if kind == "preprocess.osc" else producer.fit_fitted_state(train)
    )
    contract = producer.metadata.resolved_execution_contract()
    binding = {
        "artifact_digest": "d" * 64,
        "state_node_id": "fit",
        "state_digest": "e" * 64,
        "state_content_digest": "f" * 64,
        "serializer": contract.payload["fitted_state_serializer"],
        "source_contract_digest": contract.digest,
    }
    reader = Mock()
    reader.load_bound_state.return_value = state
    application = node_registry.create_node(kind.replace("preprocess.", "preprocess.apply_fitted_"), "apply", binding)
    application.bind_execution_runtime(ExecutionRuntime(canonical_artifact_reader=reader))
    if tampered:
        held_out.X[0, 0] += 0.01
        with pytest.raises(ValueError, match="does not match"):
            await application.execute(input_data=held_out)
    else:
        result = (await application.execute(input_data=held_out)).outputs["default"]
        _assert_binding(held_out, result)
    reader.load_bound_state.assert_called_once_with(
        binding,
        expected_source_contract_digest=contract.digest,
        expected_serializer=contract.payload["fitted_state_serializer"],
    )
