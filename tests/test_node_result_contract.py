"""Node contract tests: ensure diagnostic-producing nodes return NodeResult.

Background: many nodes historically returned plain dicts from ``execute()``,
which caused the DAG executor to store an empty ``diagnostics`` dict for
them (see executor.py lines 958-964). The Sherpa advisor's context builder
reads from that diagnostics channel, so plain-dict returns silently hid
scientific metrics from the LLM.

This test locks in the contract for nodes that have been converted to
``NodeResult`` so future regressions fail loudly, and tracks the remaining
nodes via an explicit ``PENDING_NODE_RESULT`` list so progress is visible.

When a node is migrated to NodeResult, move its entry from PENDING to
REQUIRED_NODE_RESULT.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.services.dag import out_of_fold_evidence
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.sdk.validate import make_split_plan
from tests._optional_scp import HAS_SCP

# Many nodes wrap their inputs in spectrochempy.NDDataset internally and
# cannot execute without it (PCR, MCR, SIMPLISMA, EFA, and their
# application nodes). Skip the corresponding contract tests
# in environments without SCP installed — the SCP Compat CI job re-runs
# them with the full extras.
_requires_scp = pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")


def _bound_regression_evidence(observed: np.ndarray, predicted: np.ndarray, *, n_splits: int) -> dict[str, object]:
    plan = make_split_plan(observed.size, n_splits=n_splits)
    split_plan = {
        "schema_version": "spectra-split-plan/1",
        "method": plan.method,
        "n_samples": plan.n_samples,
        "grouped": plan.grouped,
        "folds": [{"train": fold.train.tolist(), "test": fold.test.tolist()} for fold in plan.folds],
    }
    return out_of_fold_evidence.build_out_of_fold_evidence(
        producer_node_id="nested",
        task_type="regression",
        observations=observed,
        predictions=predicted,
        split_plan=split_plan,
    )


# ---------------------------------------------------------------------------
# Nodes that MUST return NodeResult with non-empty diagnostics today.
# Each tuple: (node_type, constructor_params, execute_kwargs_builder, expected_diagnostic_keys)
# ---------------------------------------------------------------------------


def _make_classification_data(n_samples: int = 60, n_features: int = 10):
    """Build a small, well-separated 3-class classification dataset."""
    rng = np.random.default_rng(42)
    n_per_class = n_samples // 3
    X = np.vstack(
        [
            rng.normal(0, 0.5, (n_per_class, n_features)),
            rng.normal(3, 0.5, (n_per_class, n_features)),
            rng.normal(-3, 0.5, (n_per_class, n_features)),
        ]
    )
    y = np.array(
        ["a"] * n_per_class + ["b"] * n_per_class + ["c"] * n_per_class,
        dtype=object,
    )
    return X, y


def _make_regression_data(n_samples: int = 40, n_features: int = 8):
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (n_samples, n_features))
    coefs = rng.normal(0, 1, n_features)
    y = X @ coefs + rng.normal(0, 0.05, n_samples)
    return X, y


# ---------------------------------------------------------------------------
# Shared helper: run node.execute and assert NodeResult contract
# ---------------------------------------------------------------------------


async def _assert_node_result(
    node_type: str,
    parameters: dict,
    kwargs: dict,
    required_diagnostic_keys: set[str],
) -> NodeResult:
    node = node_registry.create_node(
        node_type=node_type,
        node_id=f"test_{node_type.replace('.', '_')}",
        parameters=parameters,
    )
    result = await node.execute(**kwargs)

    assert isinstance(result, NodeResult), (
        f"{node_type}.execute() must return NodeResult so its diagnostics reach "
        f"the Sherpa advisor. Got {type(result).__name__}. "
        f"See src/spectra_sherpa/app/services/dag/nodes/* for the pattern."
    )
    assert result.diagnostics, (
        f"{node_type} returned NodeResult but with empty diagnostics. "
        f"The Sherpa context builder will skip it. Populate diagnostics with "
        f"scientifically meaningful scalars."
    )
    missing = required_diagnostic_keys - set(result.diagnostics.keys())
    assert not missing, (
        f"{node_type} diagnostics is missing required keys: {missing}. "
        f"Emitted keys: {sorted(result.diagnostics.keys())}"
    )
    return result


def _assert_classification_metrics_contract(result: NodeResult, *, method: str) -> None:
    metrics = result.outputs.get("metrics")
    assert isinstance(metrics, dict)
    assert metrics["task_type"] == "classification"
    assert metrics["method"] == method
    assert metrics["primary_split"] == "train"
    assert metrics["primary_metric"] == "balanced_accuracy"
    assert set(metrics["splits"]) == {"train"}
    for split in ("train",):
        split_metrics = metrics["splits"][split]
        assert set(split_metrics) >= {
            "accuracy",
            "balanced_accuracy",
            "f1_macro",
            "precision_macro",
            "recall_macro",
            "sensitivity_macro",
            "specificity_macro",
        }
    assert set(metrics["confusion_matrices"]) == {"train"}
    assert result.diagnostics["metrics"] == metrics


# ---------------------------------------------------------------------------
# Fixed nodes — these must continue to emit NodeResult with diagnostics
# ---------------------------------------------------------------------------


class TestClassificationNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_plsda_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        result = await _assert_node_result(
            node_type="classification.plsda",
            parameters={"n_components": 2, "scale": False},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={
                "train_accuracy",
                "train_f1_macro",
                "requested_n_components",
                "effective_n_components",
                "n_classes",
            },
        )
        metrics = result.outputs["metrics"]
        assert metrics["method"] == "plsda"
        assert metrics["primary_split"] == "train"
        assert set(metrics["splits"]) == {"train"}
        assert set(metrics["confusion_matrices"]) == {"train"}
        assert result.diagnostics["evidence_scope"] == "calibration_fit_diagnostics_not_validation_evidence"

    @pytest.mark.asyncio
    async def test_plsda_components_are_not_capped_by_class_count(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(7)
        X = rng.normal(size=(60, 12))
        y = np.array(["a"] * 30 + ["b"] * 30, dtype=object)
        X[y == "b", :3] += 1.5

        node = node_registry.create_node(
            node_type="classification.plsda",
            node_id="test_plsda_component_count",
            parameters={"n_components": 5, "scale": False},
        )
        result = await node.execute(X=SherpaDataset(X=X), y=y)

        assert result.diagnostics["n_classes"] == 2
        assert result.diagnostics["requested_n_components"] == 5
        assert result.diagnostics["effective_n_components"] == 5
        assert result.outputs["default"].shape == (60, 5)
        assert result.outputs["loadings"].shape == (5, 12)
        assert result.outputs["explained_variance"].shape == (5, 2)
        assert result.outputs["class_coefficients"].shape == (12, 2)
        assert [trace["name"] for trace in result.outputs["plots"]["loadings_lines"]["data"]] == [
            "LV1",
            "LV2",
            "LV3",
            "LV4",
            "LV5",
        ]

    @_requires_scp
    @pytest.mark.asyncio
    async def test_knn_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        result = await _assert_node_result(
            node_type="classification.knn",
            parameters={"n_neighbors": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"train_accuracy", "n_classes"},
        )
        _assert_classification_metrics_contract(result, method="knn")

    @_requires_scp
    @pytest.mark.asyncio
    async def test_simca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        result = await _assert_node_result(
            node_type="classification.simca",
            parameters={"n_components": 2},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"train_accuracy", "n_classes"},
        )
        _assert_classification_metrics_contract(result, method="simca")


class TestRegressionNodesEmitDiagnostics:
    @_requires_scp
    @pytest.mark.asyncio
    async def test_pls_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        result = await _assert_node_result(
            node_type="model.fitted_pls",
            parameters={"n_components": 3},
            kwargs={"input_data": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"fitted_state_serializer", "vip_method"},
        )
        assert result.outputs["default"].shape == (len(y), 1)
        assert result.outputs["fitted_state"]["state"]["n_components"] == 3
        assert result.outputs["vip_scores"].shape == (X.shape[1],)

    @_requires_scp
    @pytest.mark.asyncio
    async def test_pcr_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        await _assert_node_result(
            node_type="model.pcr",
            parameters={"n_components": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"r2", "rmse"},
        )


class TestDiagnosticsNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_cross_validation_regression_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.cross_validation",
            node_id="cv_regression",
            parameters={},
        )
        y_true = np.linspace(0, 10, 30)
        y_pred = y_true + np.random.default_rng(0).normal(0, 0.3, 30)
        result = await node.execute(evidence=_bound_regression_evidence(y_true, y_pred, n_splits=5))

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        # Regression CV metrics
        for key in ("rmsecv", "q2"):
            assert key.lower() in {k.lower() for k in result.diagnostics.keys()}, (
                f"CrossValidationNode (regression) missing {key!r} in diagnostics: "
                f"{list(result.diagnostics.keys())}"
            )

    @pytest.mark.asyncio
    async def test_holdout_evaluation_classification_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.classification_evaluator",
            node_id="holdout_cls",
            parameters={},
        )
        y_true = np.array(["a", "a", "b", "b", "c", "c"])
        y_pred = np.array(["a", "b", "b", "b", "c", "c"])
        result = await node.execute(input_data=y_pred, y_true=y_true)

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        assert result.outputs["default"]["accuracy"] == pytest.approx(5 / 6)
        assert result.outputs["default"]["n_samples"] == 6
        assert result.diagnostics["accounted_samples"] == 6
        assert result.outputs["visualization"]["metadata"]["type"] == "ClassificationTest"

    @pytest.mark.asyncio
    async def test_holdout_evaluation_regression_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.regression_evaluator",
            node_id="holdout_reg",
            parameters={},
        )
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.1, 1.9, 3.2, 3.8, 5.1])
        result = await node.execute(input_data=y_pred, y_true=y_true)

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        assert result.diagnostics["metric_registry"] == "2"
        metrics = result.outputs["default"]
        assert metrics["rmse"] > 0.0
        assert metrics["r2"] > 0.9
        comparison = result.outputs["comparison"]
        assert comparison["schema_version"] == "spectrasherpa-regression-comparison/1"
        # Direct arrays carry no saved population/model lineage.
        assert comparison["metadata"]["role"] == "unqualified_evaluation"
        assert comparison["metadata"]["n_samples"] == 5
        assert len(comparison["data"]) == 5


class TestClusteringNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_kmeans_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.kmeans",
            parameters={"n_clusters": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_clusters"},
        )

    @pytest.mark.asyncio
    async def test_hca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.hca",
            parameters={"n_clusters": 3, "linkage": "ward", "metric": "euclidean"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_clusters", "linkage", "metric", "n_samples"},
        )

    @pytest.mark.asyncio
    async def test_dbscan_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.dbscan",
            parameters={"eps": 2.0, "min_samples": 3, "metric": "euclidean"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={
                "n_clusters",
                "eps",
                "min_samples",
                "noise_fraction",
                "metric",
            },
        )


class TestDecompositionNodesEmitDiagnostics:
    @_requires_scp
    @pytest.mark.asyncio
    async def test_mcr_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(0)
        X = np.abs(rng.normal(0, 1, (20, 50))) + 0.1
        await _assert_node_result(
            node_type="model.mcr_als",
            parameters={"n_components": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )

    @_requires_scp
    @pytest.mark.asyncio
    async def test_simplisma_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(1)
        X = np.abs(rng.normal(0, 1, (20, 50))) + 0.1
        await _assert_node_result(
            node_type="model.simplisma",
            parameters={"n_components": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components", "noise"},
        )

    @pytest.mark.asyncio
    async def test_nmf_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(2)
        X = np.abs(rng.normal(0, 1, (20, 30))) + 0.1
        await _assert_node_result(
            node_type="model.nmf",
            parameters={"n_components": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components", "reconstruction_error"},
        )

    @pytest.mark.asyncio
    async def test_ica_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(3)
        X = rng.normal(0, 1, (40, 20))
        await _assert_node_result(
            node_type="model.ica",
            parameters={"n_components": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )

    @_requires_scp
    @pytest.mark.asyncio
    async def test_efa_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(4)
        X = np.abs(rng.normal(0, 1, (20, 30))) + 0.1
        await _assert_node_result(
            node_type="model.efa",
            parameters={"n_components": 10},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )


class TestPredictionNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_classifier_predict_plsda_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset

        X, y = _make_classification_data()
        feature_axis = FeatureAxis(
            values=np.arange(X.shape[1]),
            labels=[f"feature-{index}" for index in range(X.shape[1])],
        )
        dataset = SherpaDataset(X=X, feature_axis=feature_axis)
        train_node = node_registry.create_node(
            node_type="classification.plsda",
            node_id="plsda_train",
            parameters={"n_components": 2, "scale": False},
        )
        train_result = await train_node.execute(X=dataset, y=y)
        fitted_state = train_result.outputs["fitted_state"]

        await _assert_node_result(
            node_type="classification.apply_plsda",
            parameters={},
            kwargs={"default": dataset, "fitted_state": fitted_state},
            required_diagnostic_keys={"method", "n_predicted", "n_classes"},
        )

    @pytest.mark.asyncio
    async def test_classifier_predict_knn_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        train_node = node_registry.create_node(
            node_type="classification.knn",
            node_id="knn_train",
            parameters={"n_neighbors": 3},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        fitted_state = train_result.outputs["fitted_state"]

        await _assert_node_result(
            node_type="classification.apply_knn",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "fitted_state": fitted_state},
            required_diagnostic_keys={"method", "n_predicted", "n_classes", "serializer"},
        )

    @pytest.mark.asyncio
    async def test_classifier_predict_simca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        train_node = node_registry.create_node(
            node_type="classification.simca",
            node_id="simca_train",
            parameters={"n_components": 2},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        fitted_state = train_result.outputs["fitted_state"]

        await _assert_node_result(
            node_type="classification.apply_simca",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "fitted_state": fitted_state},
            required_diagnostic_keys={"method", "n_predicted", "n_classes", "n_rejected"},
        )

    @pytest.mark.asyncio
    async def test_peak_finding_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(5)
        # Build synthetic spectra with clear gaussian peaks
        x = np.linspace(0, 100, 200)
        n_samples = 5
        spectra = np.zeros((n_samples, len(x)))
        for i in range(n_samples):
            for center in (25.0, 55.0, 80.0):
                spectra[i] += np.exp(-((x - center) ** 2) / 10.0)
            spectra[i] += rng.normal(0, 0.01, len(x))
        result = await _assert_node_result(
            node_type="analysis.peak_finding",
            parameters={"distance": 5},
            kwargs={"input_data": SherpaDataset(X=spectra)},
            required_diagnostic_keys={
                "n_consensus_peaks",
                "n_peaks",
                "n_samples",
                "method",
                "n_features",
                "detection_rate_min",
                "detection_rate_max",
            },
        )
        assert result.outputs["plots"]["metadata"] == {
            "n_samples": n_samples,
            "n_peaks": result.diagnostics["n_peaks"],
            "n_consensus_peaks": result.diagnostics["n_consensus_peaks"],
        }

    @pytest.mark.asyncio
    async def test_peak_finding_peak_table_includes_fwhm_and_area(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        x = np.linspace(0, 100, 401)
        spectra = np.vstack(
            [
                np.exp(-((x - 45.0) ** 2) / 20.0),
                0.8 * np.exp(-((x - 45.5) ** 2) / 24.0),
            ]
        )
        result = await _assert_node_result(
            node_type="analysis.peak_finding",
            parameters={"distance": 20, "prominence": 0.1},
            kwargs={"input_data": SherpaDataset(X=spectra)},
            required_diagnostic_keys={
                "n_consensus_peaks",
                "n_peaks",
                "method",
                "n_features",
                "detection_rate_min",
                "detection_rate_max",
            },
        )

        rows = result.outputs["peaks"]["data"]
        assert rows
        assert rows[0]["median_half_prominence_width"] > 0
        assert rows[0]["median_absolute_window_integral"] > 0
        assert rows[0]["consensus_peak_id"].startswith("peak-")
        assert len(rows[0]["constituent_detections"]) == rows[0]["detection_count"]
        assert len(rows[0]["member_sample_labels"]) == rows[0]["sample_count"]
        assert result.outputs["peaks"]["metadata"]["membership_complete"] is True

    def test_peak_finding_numeric_parameters_are_not_artificially_capped(self):
        metadata = node_registry.get_metadata("analysis.peak_finding")
        by_name = {param.name: param for param in metadata.parameters}

        for name in (
            "height",
            "threshold",
            "distance",
            "prominence",
            "width",
            "consensus_tolerance",
        ):
            assert by_name[name].max_value is None

        assert by_name["height"].min_value == 0.0
        assert by_name["threshold"].min_value == 0.0
        assert by_name["prominence"].min_value == 0.0
        assert by_name["distance"].min_value == 0
        assert by_name["width"].min_value == 0
        assert by_name["consensus_tolerance"].min_value == 0.0

    @pytest.mark.asyncio
    async def test_peak_finding_treats_zero_distance_and_width_as_disabled(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        x = np.linspace(0, 100, 200)
        spectrum = (
            np.exp(-((x - 25.0) ** 2) / 10.0) + np.exp(-((x - 55.0) ** 2) / 10.0) + np.exp(-((x - 80.0) ** 2) / 10.0)
        )

        await _assert_node_result(
            node_type="analysis.peak_finding",
            parameters={"distance": 0, "width": 0, "height": 1000.0, "prominence": 0.0},
            kwargs={"input_data": SherpaDataset(X=spectrum.reshape(1, -1))},
            required_diagnostic_keys={
                "n_consensus_peaks",
                "n_peaks",
                "method",
                "n_features",
                "detection_rate_min",
                "detection_rate_max",
            },
        )

    @_requires_scp
    @pytest.mark.asyncio
    async def test_pls_predict_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        train_node = node_registry.create_node(
            node_type="model.fitted_pls",
            node_id="pls_train",
            parameters={"n_components": 3},
        )
        dataset = SherpaDataset(X=X)
        train_result = await train_node.execute(input_data=dataset, y=y)
        state = train_result.outputs["fitted_state"]

        applied = await _assert_node_result(
            node_type="model.apply_fitted_pls",
            parameters={},
            kwargs={"input_data": dataset, "fitted_state": state},
            required_diagnostic_keys={"fitted_state_custody"},
        )
        np.testing.assert_allclose(applied.outputs["default"], train_result.outputs["default"])
        evaluator = node_registry.create_node("diagnostics.regression_evaluator", "pls_eval", {})
        evidence = await evaluator.execute(input_data=applied.outputs["default"], y_true=y)
        assert evidence.outputs["default"]["rmse"] >= 0.0


# ---------------------------------------------------------------------------
# Pending migration — documents nodes that still return plain dicts.
# When you migrate a node, move its entry into the "fixed" section above and
# delete from PENDING. The test below will catch accidental re-regressions.
# ---------------------------------------------------------------------------


class TestPreprocessingNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_baseline_penalized_ls_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(6)
        x = np.linspace(0, 100, 200)
        baseline = 0.02 * x + 0.5
        spectra = np.zeros((5, 200))
        for i in range(5):
            peak = np.exp(-((x - 50) ** 2) / 10.0)
            spectra[i] = baseline + peak + rng.normal(0, 0.01, 200)
        await _assert_node_result(
            node_type="baseline.penalized_ls",
            parameters={"method": "als", "lam": 1e5},
            kwargs={"input_data": SherpaDataset(X=spectra)},
            required_diagnostic_keys={
                "algorithm",
                "baseline_mean",
                "baseline_standard_deviation",
                "maximum_absolute_correction",
                "corrected_root_mean_square",
                "correction_magnitude_percent",
                "converged_spectra",
                "nonconverged_spectra",
                "maximum_iterations_used",
                "input_feature_count",
            },
        )

    @pytest.mark.asyncio
    async def test_smooth_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(7)
        X = rng.normal(0, 1, (5, 100))
        await _assert_node_result(
            node_type="preprocess.smooth",
            parameters={"method": "savitzky_golay", "size": 11, "order": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"snr_before", "snr_after", "snr_improvement_db"},
        )

    @pytest.mark.asyncio
    async def test_normalize_snv_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(8)
        X = rng.normal(0, 1, (5, 100))
        await _assert_node_result(
            node_type="preprocess.normalize",
            parameters={"method": "snv"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"method", "snr_before", "snr_after"},
        )

    @pytest.mark.asyncio
    async def test_normalize_scale_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(9)
        X = np.abs(rng.normal(0, 1, (5, 100))) + 0.1
        await _assert_node_result(
            node_type="preprocess.normalize",
            parameters={"method": "scale", "scale_method": "max"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"method"},
        )


PENDING_NODE_RESULT: set[str] = set()
