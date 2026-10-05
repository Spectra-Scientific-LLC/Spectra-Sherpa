from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity


@pytest.mark.asyncio
async def test_project_dataset_parsing_and_assembly_leave_the_api_event_loop(monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import experiments, model_application

    event_loop_thread = threading.get_ident()
    observed = []
    (tmp_path / "source.csv").write_text("1,2\n", encoding="utf-8")
    monkeypatch.setattr(experiments, "experiment_dir", lambda _: tmp_path)
    monkeypatch.setattr(model_application, "read_collection_definition", lambda _: None)
    monkeypatch.setattr(
        model_application,
        "load_prepared_data_overrides",
        lambda **_: SimpleNamespace(to_sidecar_dict=lambda: {}),
    )

    def parse(*args, **kwargs):
        observed.append(("parse", threading.get_ident()))
        return object()

    def assemble(*args, **kwargs):
        observed.append(("assemble", threading.get_ident()))
        dataset = SherpaDataset(X=np.asarray([[1.0, 2.0]]))
        dataset.meta["source_collection"] = {"manifest_digest": "a" * 64}
        return dataset

    monkeypatch.setattr(model_application.ExperimentDatasetReader, "_load_file", parse)
    monkeypatch.setattr(model_application, "_loaded_files_to_sherpa", assemble)
    experiment = SimpleNamespace(name="Generic collection", project_id=3)
    file = SimpleNamespace(id=11, file_path="source.csv", file_size_bytes=4)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: experiment),
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [file])),
            ]
        )
    )
    loaded = await model_application.load_project_dataset(session, user_id=7, experiment_id=1)
    assert loaded.file_ids == [11]
    assert [phase for phase, _ in observed] == ["parse", "assemble"]
    assert all(thread != event_loop_thread for _, thread in observed)


def test_model_result_dataset_payload_preserves_exact_scientific_asset() -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.api.v1.routes.models import _dataset_payload

    loaded = SimpleNamespace(
        experiment_id=7,
        experiment_name="OPUS sample",
        project_id=3,
        file_ids=[11],
        stage="raw",
        asset_id="a",
        source_manifest_sha256="f" * 64,
    )

    assert _dataset_payload(loaded) == {
        "experiment_id": 7,
        "name": "OPUS sample",
        "project_id": 3,
        "file_ids": [11],
        "stage": "raw",
        "asset_id": "a",
        "source_manifest_sha256": "f" * 64,
    }


def test_model_apply_and_batch_requests_close_dataset_stage_vocabulary() -> None:
    from spectra_sherpa.app.api.v1.routes.models import MyDatasetModelApplyRef
    from spectra_sherpa.app.api.v1.routes.runs import RunDatasetRef

    for schema in (MyDatasetModelApplyRef, RunDatasetRef):
        assert schema(experiment_id=1, file_id=2, stage="preprocessed").stage == "preprocessed"
        with pytest.raises(ValidationError):
            schema(experiment_id=1, file_id=2, stage="bogus")


@pytest.mark.asyncio
async def test_explicit_project_file_must_match_claimed_stage(test_session, test_user) -> None:
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.services.model_application import load_project_dataset

    experiment = Experiment(
        user_id=test_user.id,
        name="Exact stage",
        description=None,
        metadata_path="metadata.json",
    )
    test_session.add(experiment)
    await test_session.flush()
    file_row = ExperimentFile(
        experiment_id=experiment.id,
        file_path="preprocessed/source.csv",
        file_type="csv",
        stage="preprocessed",
        file_size_bytes=1,
    )
    test_session.add(file_row)
    await test_session.commit()

    with pytest.raises(ValueError, match="no files for the requested scope"):
        await load_project_dataset(
            test_session,
            user_id=test_user.id,
            experiment_id=experiment.id,
            file_id=file_row.id,
            stage="raw",
        )

    with pytest.raises(ValueError, match="must be raw, preprocessed, or synthetic"):
        await load_project_dataset(
            test_session,
            user_id=test_user.id,
            experiment_id=experiment.id,
            file_id=file_row.id,
            stage="bogus",  # type: ignore[arg-type] - direct service boundary mutation
        )


def _bind_model_application_runtime(node, store) -> None:
    from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    node.bind_execution_runtime(
        ExecutionRuntime(
            model_artifact_reader=store,
            model_artifact_replay=ApplicationModelArtifactReplay(),
        )
    )


@pytest.mark.parametrize("indices", [[1.2], [True], [[0, 1]], [0, 0], [-1], [6]])
def test_application_partition_rejects_invalid_sample_indices(indices):
    from spectra_sherpa.app.services.model_application import _scope_indices_for_artifact

    manifest = {"preprocessing_chain": [{"op_id": "data.train_test_split", "parameters": {"test_indices": indices}}]}
    with pytest.raises(ValueError, match="partition"):
        _scope_indices_for_artifact(6, manifest, scope="test")


@pytest.mark.parametrize("change", ["features", "target", "legacy"])
def test_partition_positions_cannot_be_reused_for_a_different_population(change):
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import plan_train_test_split
    from spectra_sherpa.app.services.model_application import _validate_partition_population

    X = np.arange(12, dtype=float).reshape(6, 2)
    y = np.arange(6, dtype=float)
    plan = plan_train_test_split(
        X,
        y,
        method="sequential",
        test_size=1 / 3,
        random_seed=42,
    ).as_dict()
    manifest = {"preprocessing_chain": [{"op_id": "data.train_test_split", "parameters": plan}]}
    _validate_partition_population(SherpaDataset(X=X), y, manifest)
    if change == "features":
        X[0, 0] += 1
    elif change == "target":
        y[0] += 1
    else:
        del plan["x_content_digest"]
    with pytest.raises(ValueError, match="digest|input-bound"):
        _validate_partition_population(SherpaDataset(X=X), y, manifest)


@pytest.mark.asyncio
async def test_apply_knn_artifact_replays_partition_and_scale_state(monkeypatch):
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.fitted_state import KNNExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import plan_train_test_split
    from spectra_sherpa.app.services.model_application import apply_model_to_dataset
    from spectra_sherpa.app.services.model_store import get_model_store

    X_raw = np.array(
        [
            [1.0, 2.0],
            [1.2, 1.8],
            [8.0, 9.0],
            [8.1, 8.8],
            [1.1, 2.1],
            [8.2, 9.1],
        ],
        dtype=np.float64,
    )
    y = np.array(["A", "A", "B", "B", "A", "B"], dtype=object)
    train_idx = np.array([0, 1, 2, 3], dtype=np.int64)
    mean = X_raw[train_idx].mean(axis=0)
    X_train_scaled = X_raw[train_idx] - mean

    extract = KNNExtract(
        X_train=X_train_scaled,
        y_train_encoded=np.array([0, 0, 1, 1], dtype=np.int64),
        classes=["A", "B"],
        k=1,
    )
    metadata, arrays = extract.to_artifact()
    metadata.update(
        {
            "n_features": 2,
            "preprocessing_chain": [
                {
                    "op_id": "data.train_test_split",
                    "parameters": plan_train_test_split(
                        X_raw,
                        y,
                        method="sequential",
                        test_size=1 / 3,
                        random_seed=42,
                    ).as_dict(),
                },
                {
                    "op_id": "preprocess.scale",
                    "parameters": {
                        "method": "mean_center",
                        "center": True,
                        "transform_state": {
                            "serializer": "spectra.scale-reference-json.v2",
                            "input_identity": fitted_input_identity(
                                SherpaDataset(X=X_raw, feature_axis=FeatureAxis(labels=["f1", "f2"])), features=2
                            ),
                            "method": "mean_center",
                            "center": True,
                            "mean": mean.tolist(),
                            "scale": None,
                        },
                    },
                },
            ],
        }
    )
    store = get_model_store()
    store.save("knn-apply-test", metadata, arrays)
    real_load = store.load
    load_calls = 0

    def count_loads(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(store, "load", count_loads)

    ds = SherpaDataset(
        X=X_raw,
        feature_axis=FeatureAxis(labels=["f1", "f2"]),
        target=y,
        target_context=TargetContext(target_type="categorical"),
    )

    result = await apply_model_to_dataset("knn-apply-test", ds, scope="test")
    assert result["sample_indices"] == [4, 5]
    assert result["predictions"] == ["A", "B"]
    assert result["true_labels"] == ["A", "B"]
    assert result["metrics"]["accuracy"] == 1.0
    assert load_calls == 1


@pytest.mark.asyncio
async def test_compare_models_reports_pairwise_disagreements():
    from spectra_sherpa.app.lib.fitted_state import KNNExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
    from spectra_sherpa.app.services.model_application import compare_models_on_dataset
    from spectra_sherpa.app.services.model_store import get_model_store

    X = np.array([[0.0], [1.0], [10.0], [11.0]], dtype=np.float64)
    y = np.array(["A", "A", "B", "B"], dtype=object)
    store = get_model_store()

    left_meta, left_arrays = KNNExtract(
        X_train=np.array([[0.0], [10.0]], dtype=np.float64),
        y_train_encoded=np.array([0, 1], dtype=np.int64),
        classes=["A", "B"],
        k=1,
    ).to_artifact()
    left_meta["n_features"] = 1
    store.save("knn-left", left_meta, left_arrays)

    right_meta, right_arrays = KNNExtract(
        X_train=np.array([[0.0], [5.0], [10.0]], dtype=np.float64),
        y_train_encoded=np.array([0, 1, 0], dtype=np.int64),
        classes=["A", "B"],
        k=1,
    ).to_artifact()
    right_meta["n_features"] = 1
    store.save("knn-right", right_meta, right_arrays)

    ds = SherpaDataset(X=X, target=y, target_context=TargetContext(target_type="categorical"))
    result = await compare_models_on_dataset(["knn-left", "knn-right"], ds)

    assert len(result["models"]) == 2
    assert result["pairwise"][0]["n_disagreements"] == 2
    assert result["pairwise"][0]["disagreement_indices"] == [2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("included", [None, [True, False, True]])
@pytest.mark.parametrize("excluded_feature", [False, True])
async def test_apply_regression_artifact_reports_labeled_set_metrics(included, excluded_feature):
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext
    from spectra_sherpa.app.services.model_application import apply_model_to_dataset
    from spectra_sherpa.app.services.model_store import get_model_store

    metadata, arrays = LinearRegressionExtract(
        coef=np.array([2.0, -1.0], dtype=np.float64),
        intercept=np.array([0.5], dtype=np.float64),
    ).to_artifact()
    metadata["n_features"] = 2
    get_model_store().save("linear-apply-metrics", metadata, arrays)

    X = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 1.5]], dtype=np.float64)
    y_true = np.array([2.6, 3.3, 5.0], dtype=np.float64)
    expected = X @ arrays["coef"].reshape(-1, 1) + arrays["intercept"]
    residual = y_true - expected.ravel()

    ds = SherpaDataset(
        X=np.column_stack((X, np.full(3, 9999.0))) if excluded_feature else X,
        feature_axis=FeatureAxis(include_mask=[True, True, False]) if excluded_feature else None,
        sample_axis=SampleAxis(include_mask=included),
        target=y_true,
        target_context=TargetContext(target_type="continuous"),
    )
    if included is not None:
        expected = expected[included]
        residual = residual[included]
    evidence = {}
    result = await apply_model_to_dataset("linear-apply-metrics", ds, execution_evidence=evidence)
    assert evidence["definition"]["nodes"][1]["node_type"] == "model.load_apply"
    assert evidence["definition"]["nodes"][1]["parameters"]["model_id"] == "linear-apply-metrics"
    np.testing.assert_allclose(evidence["outputs"]["application-model-artifact"]["result"], expected)
    assert "application-model-artifact" in evidence["diagnostics"]["_scientific_presentations"]

    assert result["metrics"]["registry_version"] == "2"
    assert result["metrics"]["rmse"] == pytest.approx(np.sqrt(np.mean(residual**2)), rel=1e-12)
    assert result["metrics"]["mae"] == np.mean(np.abs(residual))
    assert result["metrics"]["bias"] == -np.mean(residual)
    assert result["metrics"]["r2"] is not None
    assert result["metrics"]["n_samples"] == len(expected)
    assert result["sample_indices"] == ([0, 2] if included is not None else [0, 1, 2])
    assert result["feature_indices"] == [0, 1]


@pytest.mark.parametrize("names", [None, ["density"]])
def test_application_never_substitutes_a_different_target(names):
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
    from spectra_sherpa.app.services.model_application import _target_for_artifact

    dataset = SherpaDataset(
        X=np.ones((3, 2)),
        target=np.arange(3.0),
        target_context=TargetContext(target_type="continuous", target_names=names),
    )
    with pytest.raises(ValueError, match="matching target"):
        _target_for_artifact(dataset, {"selected_target": "cetane", "available_target_names": ["cetane"]})


@pytest.mark.asyncio
async def test_apply_regression_artifact_slices_labeled_multitarget_to_saved_target(tmp_path):
    from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.model_application import apply_model_to_dataset

    previous_store = model_store._store
    try:
        store = model_store.init_model_store(tmp_path)
        metadata, arrays = LinearRegressionExtract(
            coef=np.array([2.0, -1.0], dtype=np.float64),
            intercept=np.array([0.5], dtype=np.float64),
        ).to_artifact()
        metadata.update(
            {
                "n_features": 2,
                "target_mode": "single",
                "selected_target": "cetane",
                "target_names": ["cetane"],
                "available_target_names": ["density", "cetane"],
                "target_type": "continuous",
            }
        )
        store.save("linear-selected-target", metadata, arrays)

        X = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 1.5]], dtype=np.float64)
        expected = X @ arrays["coef"].reshape(-1, 1) + arrays["intercept"]
        y_multi = np.column_stack(
            [
                np.array([900.0, 901.0, 902.0], dtype=np.float64),
                expected.ravel() + np.array([0.1, -0.2, 0.3], dtype=np.float64),
            ]
        )
        residual = y_multi[:, 1] - expected.ravel()
        ds = SherpaDataset(
            X=X,
            target=y_multi,
            target_context=TargetContext(
                target_type="continuous",
                target_names=["density", "cetane"],
            ),
        )

        result = await apply_model_to_dataset("linear-selected-target", ds)

        assert result["warnings"] == []
        assert result["metadata"]["selected_target"] == "cetane"
        assert result["metrics"]["n_samples"] == 3
        assert result["metrics"]["rmse"] == pytest.approx(np.sqrt(np.mean(residual**2)), rel=1e-12)
        assert result["metrics"]["bias"] == -np.mean(residual)
    finally:
        model_store._store = previous_store


@pytest.mark.asyncio
async def test_apply_pls_artifact_reports_applicability_domain(tmp_path):
    from spectra_sherpa.app.lib.fitted_state import PLSExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.model_application import apply_model_to_dataset

    previous_store = model_store._store
    try:
        store = model_store.init_model_store(tmp_path)
        metadata, arrays = PLSExtract(
            x_scores=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]),
            y_scores=None,
            x_loadings=np.eye(2),
            y_loadings=None,
            coef=np.ones((2, 1), dtype=np.float64),
            n_components=2,
            x_mean=np.zeros(2, dtype=np.float64),
            y_mean=np.zeros(1, dtype=np.float64),
            x_scale=np.ones(2, dtype=np.float64),
            t2_limit=2.0,
            q_limit=0.1,
            t2_q_method="pomerantsev_dd_moments",
        ).to_artifact()
        metadata["n_features"] = 2
        store.save("pls-apply-domain", metadata, arrays)

        ds = SherpaDataset(X=np.array([[0.1, 0.1], [4.0, 0.0]], dtype=np.float64))
        result = await apply_model_to_dataset("pls-apply-domain", ds)

        assert result["predictions"] == [[0.2], [4.0]]
        assert result["applicability"]["out_of_domain"] == [None, None]
        assert result["applicability"]["n_out_of_domain"] is None
        assert result["warnings"] == [
            "Applicability unavailable: refit to retain exact projection and screening authority"
        ]
    finally:
        model_store._store = previous_store


def test_load_apply_node_supports_saved_regression_artifact_with_feature_mask(tmp_path):
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode

    previous_store = model_store._store
    try:
        store = model_store.init_model_store(tmp_path)
        metadata, arrays = LinearRegressionExtract(
            coef=np.array([2.0, 3.0], dtype=np.float64),
            intercept=np.array([1.0], dtype=np.float64),
        ).to_artifact()
        metadata.update(
            {
                "n_features": 2,
                "feature_mask": [False, True, True],
                "selected_features": [200.0, 300.0],
            }
        )
        store.save("linear-mask-test", metadata, arrays)

        ds = SherpaDataset(
            X=np.array([[10.0, 2.0, 3.0], [20.0, 4.0, 5.0]], dtype=np.float64),
            feature_axis=FeatureAxis(values=np.array([100.0, 200.0, 300.0], dtype=np.float64)),
        )
        node = LoadApplyModelNode(node_id="load_apply_1", parameters={"model_id": "linear-mask-test"})
        _bind_model_application_runtime(node, store)

        import asyncio

        result = asyncio.run(node.execute(X_new=ds))
        np.testing.assert_allclose(result["y_pred"], np.array([[14.0], [24.0]], dtype=np.float64))
        np.testing.assert_allclose(result["predictions"], np.array([[14.0], [24.0]], dtype=np.float64))
    finally:
        model_store._store = previous_store


def test_load_apply_node_surfaces_pls_applicability_domain(tmp_path):
    from spectra_sherpa.app.lib.fitted_state import PLSExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode

    previous_store = model_store._store
    try:
        store = model_store.init_model_store(tmp_path)
        metadata, arrays = PLSExtract(
            x_scores=np.array([[0.0], [1.0], [-1.0]], dtype=np.float64),
            y_scores=None,
            x_loadings=np.array([[1.0, 0.0]], dtype=np.float64),
            y_loadings=None,
            coef=np.array([[1.0], [0.0]], dtype=np.float64),
            n_components=1,
            x_mean=np.zeros(2, dtype=np.float64),
            y_mean=np.zeros(1, dtype=np.float64),
            x_scale=np.ones(2, dtype=np.float64),
            t2_limit=2.0,
            q_limit=0.1,
        ).to_artifact()
        metadata["n_features"] = 2
        store.save("pls-load-apply-domain", metadata, arrays)

        node = LoadApplyModelNode(node_id="load_apply_pls", parameters={"model_id": "pls-load-apply-domain"})
        _bind_model_application_runtime(node, store)

        import asyncio

        result = asyncio.run(node.execute(X_new=SherpaDataset(X=np.array([[0.0, 0.0], [3.0, 0.0]]))))

        np.testing.assert_allclose(result["y_pred"], np.array([[0.0], [3.0]], dtype=np.float64))
        assert result["applicability"]["out_of_domain"] == [None, None]
        assert (
            result["metadata"]["applicability_warning"]
            == "Applicability unavailable: refit to retain exact projection and screening authority"
        )
    finally:
        model_store._store = previous_store


def test_model_apply_replays_deterministic_preprocessing_steps():
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import _normalize_dispatch
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import SmoothNode, _smooth_dispatch
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X = np.array(
        [
            [1.0, 2.0, 4.0, 8.0, 16.0],
            [3.0, 4.0, 6.0, 9.0, 15.0],
        ],
        dtype=np.float64,
    )
    chain = [
        {
            "op_id": "preprocess.normalize",
            "parameters": {
                "method": "snv",
                "std_ddof": 0,
                "scale_method": "max",
                "transform_state": {"method": "snv", "std_ddof": 0, "replay": "sample_local"},
            },
        },
        {
            "op_id": "preprocess.smooth",
            "parameters": SmoothNode.metadata.canonicalize_parameters(
                {"method": "savitzky_golay", "size": 3, "order": 1}
            ),
        },
    ]

    X_ready, _, indices, warnings = _prepare_X_for_artifact(X, None, {"preprocessing_chain": chain}, scope="all")
    expected = _smooth_dispatch(
        _normalize_dispatch(X, method="snv", std_ddof=0, scale_method="max"),
        method="savitzky_golay",
        size=3,
        order=1,
    )

    np.testing.assert_allclose(X_ready, expected)
    np.testing.assert_array_equal(indices, np.array([0, 1], dtype=np.int64))
    assert warnings == []


def test_model_apply_replays_msc_with_persisted_reference_state():
    from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import _fit_msc_state
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X_train = np.array([[1.0, 2.0, 4.0], [2.0, 4.2, 8.0]], dtype=np.float64)
    X_new = np.array([[1.5, 3.1, 5.9]], dtype=np.float64)
    reference = np.mean(X_train, axis=0)
    chain = [
        {
            "op_id": "preprocess.msc",
            "parameters": {
                "reference_method": "mean",
                "state_serializer": "spectra.msc-reference-json.v2",
                "transform_state": _fit_msc_state(
                    X_train, reference_method="mean", feature_axis_values=None, feature_axis_units=None
                ),
            },
        }
    ]

    X_ready, _, _, warnings = _prepare_X_for_artifact(X_new, None, {"preprocessing_chain": chain}, scope="all")

    A = np.vstack([reference, np.ones(reference.shape[0])]).T
    m, c = np.linalg.lstsq(A, X_new[0], rcond=None)[0]
    expected = ((X_new[0] - c) / m).reshape(1, -1)
    np.testing.assert_allclose(X_ready, expected)
    assert warnings == []


def test_model_apply_rejects_incomplete_or_inconsistent_normalize_records():
    import pytest

    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X = np.arange(12, dtype=np.float64).reshape(3, 4)
    incomplete = [{"op_id": "preprocess.normalize", "parameters": {"method": "snv"}}]
    with pytest.raises(ValueError, match="complete canonical transform_state"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": incomplete}, scope="all")

    inconsistent = [
        {
            "op_id": "preprocess.normalize",
            "parameters": {
                "method": "snv",
                "std_ddof": 0,
                "scale_method": "max",
                "transform_state": {"method": "scale", "scale_method": "max", "replay": "sample_local"},
            },
        }
    ]
    with pytest.raises(ValueError, match="does not match"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": inconsistent}, scope="all")


def test_model_apply_rejects_noncanonical_derivative_records():
    import pytest

    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X = np.arange(42, dtype=np.float64).reshape(2, 21)
    incomplete = [
        {
            "op_id": "preprocess.derivative",
            "parameters": {"method": "savitzky_golay", "deriv": "1", "size": 11, "order": 2},
        }
    ]
    with pytest.raises(ValueError, match="complete canonical parameter and axis record"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": incomplete}, scope="all")

    coercive = [
        {
            "op_id": "preprocess.derivative",
            "parameters": {
                "method": "savitzky_golay",
                "deriv": "1",
                "size": 11.0,
                "order": 2,
                "gap": 5,
                "segment": 5,
                "delta": 1.0,
            },
        }
    ]
    with pytest.raises(ValueError, match="exact integers"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": coercive}, scope="all")


def test_model_apply_rejects_incomplete_or_noncanonical_smooth_records():
    import pytest

    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X = np.arange(42, dtype=np.float64).reshape(2, 21)
    incomplete = [
        {
            "op_id": "preprocess.smooth",
            "parameters": {"method": "savitzky_golay", "size": 11, "order": 2},
        }
    ]
    with pytest.raises(ValueError, match="complete canonical parameter record"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": incomplete}, scope="all")

    irrelevant = [
        {
            "op_id": "preprocess.smooth",
            "parameters": {
                "method": "gaussian",
                "size": 11,
                "order": 2,
                "lam": 200.0,
                "d": "2",
                "sigma": 1.0,
            },
        }
    ]
    with pytest.raises(ValueError, match="may not carry"):
        _prepare_X_for_artifact(X, None, {"preprocessing_chain": irrelevant}, scope="all")


def test_model_apply_rejects_incomplete_osc_preprocessing():
    import pytest

    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    chain = [{"op_id": "preprocess.osc", "parameters": {"n_components": 1}}]
    with pytest.raises(ValueError, match="preprocess.osc"):
        _prepare_X_for_artifact(np.ones((3, 4)), None, {"preprocessing_chain": chain}, scope="all")


def test_validate_feature_contract_rejects_feature_count_mismatch():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 3), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
    )

    import pytest

    with pytest.raises(ValueError, match="Feature count mismatch"):
        validate_feature_contract(np.asarray(ds.X), ds, {"n_features": 2})


def test_validate_feature_contract_rejects_manifest_axis_length_mismatch():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 2), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.array([100.0, 200.0]), units="cm-1"),
    )

    import pytest

    with pytest.raises(ValueError, match="artifact manifest has 3 feature-axis points"):
        validate_feature_contract(
            np.asarray(ds.X),
            ds,
            {"n_features": 2, "feature_axis": [100.0, 200.0, 300.0]},
        )


def test_validate_feature_contract_rejects_unit_mismatch():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 2), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.array([100.0, 200.0]), units="nm"),
    )

    import pytest

    with pytest.raises(ValueError, match="units"):
        validate_feature_contract(
            np.asarray(ds.X),
            ds,
            {
                "n_features": 2,
                "feature_axis": [100.0, 200.0],
                "feature_axis_units": "cm-1",
            },
        )


def test_validate_feature_contract_rejects_same_unit_different_axis_quantity():
    from spectra_sherpa.app.lib.axes import SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 2), dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.array([100.0, 200.0]),
            title="Raman shift",
            units="cm-1",
        ),
    )

    with pytest.raises(ValueError, match="quantity"):
        validate_feature_contract(
            np.asarray(ds.X),
            ds,
            {
                "n_features": 2,
                "feature_axis": [100.0, 200.0],
                "feature_axis_units": "cm-1",
                "feature_axis_quantity": "wavenumber",
            },
        )


def test_validate_feature_contract_accepts_canonical_unit_alias_for_same_quantity():
    from spectra_sherpa.app.lib.axes import SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 2), dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.array([100.0, 200.0]),
            title="Wavenumber",
            units="cm⁻¹",
        ),
    )

    validate_feature_contract(
        np.asarray(ds.X),
        ds,
        {
            "n_features": 2,
            "feature_axis": [100.0, 200.0],
            "feature_axis_units": "1/cm",
            "feature_axis_quantity": "wavenumber",
        },
    )


def test_validate_feature_contract_rejects_missing_axis_values():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 2), dtype=np.float64),
        feature_axis=FeatureAxis(labels=["a", "b"], units="cm-1"),
    )

    import pytest

    with pytest.raises(ValueError, match="no feature-axis values"):
        validate_feature_contract(
            np.asarray(ds.X),
            ds,
            {"n_features": 2, "feature_axis": [100.0, 200.0], "feature_axis_units": "cm-1"},
        )


def test_validate_feature_contract_uses_non_contiguous_feature_mask_for_axis_values():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.model_application import validate_feature_contract

    ds = SherpaDataset(
        X=np.ones((2, 4), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.array([100.0, 200.0, 300.0, 400.0]), units="cm-1"),
    )

    validate_feature_contract(
        np.asarray(ds.X),
        ds,
        {
            "n_features": 2,
            "feature_mask": [False, True, False, True],
            "feature_axis": [200.0, 400.0],
            "feature_axis_units": "cm^-1",
        },
    )
