from __future__ import annotations

import numpy as np


def test_apply_knn_artifact_replays_partition_and_scale_state():
    from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
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
    test_idx = np.array([4, 5], dtype=np.int64)
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
                    "op_id": "selection.sample_partition",
                    "parameters": {
                        "train_indices": train_idx.tolist(),
                        "test_indices": test_idx.tolist(),
                        "n_samples": int(X_raw.shape[0]),
                    },
                },
                {
                    "op_id": "preprocess.scale",
                    "parameters": {
                        "method": "mean_center",
                        "transform_state": {
                            "method": "mean_center",
                            "mean": mean.tolist(),
                        },
                    },
                },
            ],
        }
    )
    store = get_model_store()
    store.save("knn-apply-test", metadata, arrays)

    ds = SherpaDataset(
        X=X_raw,
        feature_axis=FeatureAxis(labels=["f1", "f2"]),
        target=y,
        target_context=TargetContext(target_type="categorical"),
    )

    result = apply_model_to_dataset("knn-apply-test", ds, scope="test")
    assert result["sample_indices"] == [4, 5]
    assert result["predictions"] == ["A", "B"]
    assert result["true_labels"] == ["A", "B"]
    assert result["metrics"]["accuracy"] == 1.0


def test_compare_models_reports_pairwise_disagreements():
    from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract
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
        X_train=np.array([[0.0], [10.0]], dtype=np.float64),
        y_train_encoded=np.array([1, 1], dtype=np.int64),
        classes=["A", "B"],
        k=1,
    ).to_artifact()
    right_meta["n_features"] = 1
    store.save("knn-right", right_meta, right_arrays)

    ds = SherpaDataset(X=X, target=y, target_context=TargetContext(target_type="categorical"))
    result = compare_models_on_dataset(["knn-left", "knn-right"], ds)

    assert len(result["models"]) == 2
    assert result["pairwise"][0]["n_disagreements"] == 2
    assert result["pairwise"][0]["disagreement_indices"] == [0, 1]


def test_apply_regression_artifact_reports_labeled_set_metrics():
    from spectra_sherpa.app.lib.adapters.scp_extractors import LinearRegressionExtract
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
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
        X=X,
        target=y_true,
        target_context=TargetContext(target_type="continuous"),
    )
    result = apply_model_to_dataset("linear-apply-metrics", ds)

    assert result["metrics"]["rmsep"] == np.sqrt(np.mean(residual**2))
    assert result["metrics"]["bias"] == np.mean(residual)
    assert result["metrics"]["sep"] == np.std(residual, ddof=1)
    assert result["metrics"]["r2"] is not None
    assert result["metrics"]["n_evaluated"] == 3


def test_apply_regression_artifact_slices_labeled_multitarget_to_saved_target(tmp_path):
    from spectra_sherpa.app.lib.adapters.scp_extractors import LinearRegressionExtract
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

        result = apply_model_to_dataset("linear-selected-target", ds)

        assert result["warnings"] == []
        assert result["metadata"]["selected_target"] == "cetane"
        assert result["metrics"]["n_evaluated"] == 3
        assert result["metrics"]["rmsep"] == np.sqrt(np.mean(residual**2))
        assert result["metrics"]["bias"] == np.mean(residual)
    finally:
        model_store._store = previous_store


def test_apply_pls_artifact_reports_applicability_domain(tmp_path):
    from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract
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
        result = apply_model_to_dataset("pls-apply-domain", ds)

        assert result["predictions"] == [[0.2], [4.0]]
        assert result["applicability"]["out_of_domain"] == [False, True]
        assert result["applicability"]["n_out_of_domain"] == 1
        assert result["warnings"] == ["1 sample outside saved model applicability domain"]
    finally:
        model_store._store = previous_store


def test_load_apply_node_supports_saved_regression_artifact_with_feature_mask(tmp_path):
    from spectra_sherpa.app.lib.adapters.scp_extractors import LinearRegressionExtract
    from spectra_sherpa.app.lib.axes import FeatureAxis
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

        import asyncio

        result = asyncio.run(node.execute(X_new=ds))
        np.testing.assert_allclose(result["y_pred"], np.array([[14.0], [24.0]], dtype=np.float64))
        np.testing.assert_allclose(result["predictions"], np.array([[14.0], [24.0]], dtype=np.float64))
    finally:
        model_store._store = previous_store


def test_load_apply_node_surfaces_pls_applicability_domain(tmp_path):
    from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract
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

        import asyncio

        result = asyncio.run(node.execute(X_new=SherpaDataset(X=np.array([[0.0, 0.0], [3.0, 0.0]]))))

        np.testing.assert_allclose(result["y_pred"], np.array([[0.0], [3.0]], dtype=np.float64))
        assert result["applicability"]["out_of_domain"] == [False, True]
        assert result["metadata"]["applicability_warning"] == "1 sample outside saved model applicability domain"
    finally:
        model_store._store = previous_store


def test_model_apply_replays_deterministic_preprocessing_steps():
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _normalize_dispatch
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_deriv_nodes import _smooth_dispatch
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X = np.array(
        [
            [1.0, 2.0, 4.0, 8.0, 16.0],
            [3.0, 4.0, 6.0, 9.0, 15.0],
        ],
        dtype=np.float64,
    )
    chain = [
        {"op_id": "preprocess.normalize", "parameters": {"method": "snv"}},
        {
            "op_id": "preprocess.smooth",
            "parameters": {"method": "savitzky_golay", "size": 3, "order": 1},
        },
    ]

    X_ready, _, indices, warnings = _prepare_X_for_artifact(X, None, {"preprocessing_chain": chain}, scope="all")
    expected = _smooth_dispatch(_normalize_dispatch(X, method="snv"), method="savitzky_golay", size=3, order=1)

    np.testing.assert_allclose(X_ready, expected)
    np.testing.assert_array_equal(indices, np.array([0, 1], dtype=np.int64))
    assert warnings == []


def test_model_apply_replays_msc_with_persisted_reference_state():
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    X_train = np.array([[1.0, 2.0, 4.0], [2.0, 4.2, 8.0]], dtype=np.float64)
    X_new = np.array([[1.5, 3.1, 5.9]], dtype=np.float64)
    reference = np.mean(X_train, axis=0)
    chain = [
        {
            "op_id": "preprocess.normalize",
            "parameters": {
                "method": "msc",
                "transform_state": {
                    "method": "msc",
                    "reference": "mean",
                    "reference_spectrum": reference.tolist(),
                },
            },
        }
    ]

    X_ready, _, _, warnings = _prepare_X_for_artifact(X_new, None, {"preprocessing_chain": chain}, scope="all")

    A = np.vstack([reference, np.ones(reference.shape[0])]).T
    m, c = np.linalg.lstsq(A, X_new[0], rcond=None)[0]
    expected = ((X_new[0] - c) / m).reshape(1, -1)
    np.testing.assert_allclose(X_ready, expected)
    assert warnings == []


def test_model_apply_rejects_unreplayable_osc_preprocessing():
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
