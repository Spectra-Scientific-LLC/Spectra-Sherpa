"""Tests for HIGH severity bug fixes.

Bug #1: sample_partition drops embedded targets from X_cal/X_test
Bug #2: generate_python() in selection nodes incomplete
Bug #3: load_apply feature_mask deployment path broken
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Bug #1: sample_partition preserves embedded targets
# ---------------------------------------------------------------------------


class TestSamplePartitionTargetPreservation:
    """sample_partition must reattach y to X_cal_ds and X_test_ds."""

    @pytest.fixture
    def partition_node(self):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        return SamplePartitionNode(
            node_id="test_sp",
            parameters={"method": "random", "test_size": 0.3, "random_seed": 42},
        )

    @pytest.fixture
    def dataset_with_target(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.RandomState(1).randn(20, 50), target=np.arange(20, dtype=np.float64))
        return ds

    def test_xcal_has_target(self, partition_node, dataset_with_target):
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        X_cal = result.outputs["X_cal"]
        assert X_cal.target is not None, "X_cal must have target reattached"
        assert len(X_cal.target) == X_cal.data.shape[0]

    def test_xtest_has_target(self, partition_node, dataset_with_target):
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        X_test = result.outputs["X_test"]
        assert X_test.target is not None, "X_test must have target reattached"
        assert len(X_test.target) == X_test.data.shape[0]

    def test_target_values_match_indices(self, partition_node, dataset_with_target):
        """Targets on X_cal/X_test must be the correct slices, not shuffled."""
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        cal_idx = result.outputs["cal_indices"]
        test_idx = result.outputs["test_indices"]
        y_full = dataset_with_target.target

        np.testing.assert_array_equal(result.outputs["X_cal"].target, y_full[cal_idx])
        np.testing.assert_array_equal(result.outputs["X_test"].target, y_full[test_idx])

    def test_no_target_when_y_is_none(self, partition_node):
        """When no y is provided, X_cal/X_test should not have spurious targets."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.randn(20, 50))
        result = asyncio.run(partition_node.execute(X=ds))
        # Target may or may not be None depending on source, but y_cal/y_test should not be in outputs
        assert "y_cal" not in result.outputs
        assert "y_test" not in result.outputs


# ---------------------------------------------------------------------------
# Bug #2: generate_python() completeness
# ---------------------------------------------------------------------------


class TestGeneratePythonCompleteness:
    """generate_python() must assign results dict and not reference undefined vars."""

    def test_sample_partition_has_results_dict(self):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        node = SamplePartitionNode(
            node_id="sp1",
            parameters={"method": "kennard_stone", "test_size": 0.2},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        assert "results['sp1']" in code, "generate_python must assign results dict"

    def test_classification_exports_emit_canonical_metrics_and_confusion_matrices(self):
        from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
        from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCANode

        nodes = [
            KNNNode(node_id="knn_export", parameters={"n_neighbors": 3, "cv_folds": 3}),
            PLSDANode(node_id="plsda_export", parameters={"n_components": 2, "cv_folds": 3}),
            SIMCANode(node_id="simca_export", parameters={"n_components": 2, "cv_folds": 3}),
        ]
        rng = np.random.default_rng(42)
        data = np.vstack(
            [
                rng.normal(loc=0.0, scale=0.08, size=(6, 5)),
                rng.normal(loc=2.0, scale=0.08, size=(6, 5)),
                rng.normal(loc=4.0, scale=0.08, size=(6, 5)),
            ]
        )
        target = np.asarray(["class_0"] * 6 + ["class_1"] * 6 + ["class_2"] * 6, dtype=object)

        try:
            import spectrochempy as scp
        except Exception as exc:  # pragma: no cover - only hit in minimal optional-dependency envs
            scp = None
            scp_import_error = exc
        else:
            scp_import_error = None

        for node in nodes:
            code = "\n".join(node.generate_python({"X": "data", "y": "target"}, indent=""))
            compile(code, f"<{node.node_id}_export>", "exec")
            assert "classification_metrics_contract" in code
            assert "'classification_metrics': _classification_metrics" in code
            assert "'confusion_matrix_train': _cm_train" in code
            assert "'confusion_matrix_cv': _cm_cv" in code
            assert "'y_pred_cv'" in code
            if isinstance(node, PLSDANode) and scp is None:
                pytest.skip(f"SpectroChemPy unavailable for generated PLS-DA export execution: {scp_import_error}")

            namespace = {"np": np, "data": data, "target": target, "results": {}}
            if scp is not None:
                namespace["scp"] = scp
            exec(compile(code, f"<{node.node_id}_export>", "exec"), namespace)
            output = namespace["results"][node.node_id]
            canonical = output["metrics"]["classification_metrics"]
            assert canonical["task_type"] == "classification"
            assert canonical["primary_split"] == "cv"
            assert "train" in canonical["splits"]
            assert "cv" in canonical["splits"]
            assert canonical["confusion_matrices"]["train"]
            assert canonical["confusion_matrices"]["cv"]
            assert output["confusion_matrix_train"].shape == (3, 3)
            assert output["confusion_matrix_cv"].shape == (3, 3)
            assert len(output["metadata"]["y_pred_cv"]) == len(target)

    def test_static_validation_rejects_feature_tables_for_spectrum_only_nodes(self):
        from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

        executor = DAGExecutor()
        executor.add_node(
            WorkflowNode(
                node_id="src",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="smooth",
                node_type="preprocess.smooth",
                parameters={"method": "savgol", "window_size": 5, "poly_order": 2},
            )
        )
        executor.add_edge(WorkflowEdge(from_node="src", to_node="smooth"))

        result = executor.validate_full()
        messages = "\n".join(issue.message for issue in result.errors).lower()
        assert "requires x_spectra" in messages
        assert "received x_features" in messages

    def test_sample_partition_export_preserves_targets(self):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        node = SamplePartitionNode(
            node_id="sp_target",
            parameters={"method": "random", "test_size": 0.2},
        )
        code = "\n".join(node.generate_python({"X": "data"}))
        assert "_y_train" in code
        assert "'y_train'" in code
        assert "target=_y_train" in code
        # Backward-compatible aliases also emitted
        assert "'y_cal'" in code
        assert "'X_cal'" in code

    def test_sample_partition_spxy_export(self):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        node = SamplePartitionNode(
            node_id="sp2",
            parameters={"method": "spxy", "test_size": 0.2},
        )
        lines = node.generate_python({"X": "data", "y": "target"})
        code = "\n".join(lines)
        assert "spxy" in code
        assert "results['sp2']" in code

    def test_sample_partition_stratified_export(self):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        node = SamplePartitionNode(
            node_id="sp3",
            parameters={"method": "stratified", "test_size": 0.3, "random_seed": 0},
        )
        lines = node.generate_python({"X": "data", "y": "target"})
        code = "\n".join(lines)
        assert "train_test_split" in code
        assert "results['sp3']" in code

    def test_variable_select_vip_no_undefined_mask(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs1",
            parameters={"method": "vip", "threshold": 1.0},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        # _mask must be defined before use
        assert "_mask = " in code, "VIP branch must define _mask"
        assert "results['vs1']" in code
        assert "extract_vip_from_pls_model" in code
        assert "TODO" not in code

    def test_variable_select_interval_has_results(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs2",
            parameters={"method": "interval", "region_start": 1000, "region_end": 2000},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        assert "results['vs2']" in code

    def test_variable_select_peak_window_export(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs3",
            parameters={"method": "peak_window", "peak_prominence": 0.1, "peak_half_window": 5},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        assert "_mask" in code
        assert "signal.find_peaks" in code
        assert "results['vs3']" in code

    def test_variable_select_peak_window_negative_extrema_is_opt_in(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        default_node = VariableSelectNode(
            node_id="vs_peak_default",
            parameters={"method": "peak_window", "peak_prominence": 0.1, "peak_half_window": 5},
        )
        default_code = "\n".join(default_node.generate_python({"X": "data"}))
        assert "_neg_peaks" not in default_code

        opt_in_node = VariableSelectNode(
            node_id="vs_peak_neg",
            parameters={
                "method": "peak_window",
                "peak_prominence": 0.1,
                "peak_half_window": 5,
                "include_negative_extrema": True,
            },
        )
        opt_in_code = "\n".join(opt_in_node.generate_python({"X": "data"}))
        assert "_neg_peaks" in opt_in_code

    def test_variable_select_export_preserves_targets(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs_target",
            parameters={"method": "interval", "region_start": 1000, "region_end": 2000},
        )
        code = "\n".join(node.generate_python({"X": "data"}))
        assert "_selected_target = getattr(_X_input, 'target', None)" in code
        assert "'X_selected': _X_selected_ds" in code

    def test_variable_select_unknown_method_defines_mask(self):
        """Even for unknown/selectivity_ratio methods, _mask must be defined."""
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs4",
            parameters={"method": "selectivity_ratio", "threshold": 1.0},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        assert "_mask = " in code or "_mask =" in code


# ---------------------------------------------------------------------------
# Bug #3: run comparison must not silently collapse duplicate node metrics
# ---------------------------------------------------------------------------


def test_run_metric_collapse_preserves_duplicate_node_provenance():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "knn_1": {"metrics": {"task_type": "classification", "splits": {"cv": {"accuracy": 0.75}}}},
            "simca_1": {"metrics": {"task_type": "classification", "splits": {"cv": {"accuracy": 0.8}}}},
        }
    )

    assert "cv_accuracy" not in collapsed
    assert collapsed["knn_1.cv_accuracy"] == 0.75
    assert collapsed["simca_1.cv_accuracy"] == 0.8


def test_run_metric_collapse_suppresses_nested_classification_aliases():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "evaluate_1": {
                "metrics": {
                    "task_type": "classification",
                    "n_classes": 3,
                    "splits": {
                        "test": {
                            "accuracy": 0.9333,
                            "balanced_accuracy": 0.9352,
                            "f1_macro": 0.9314,
                        }
                    },
                },
                "accuracy": 0.9333,
                "metadata": {
                    "accuracy": 0.9333,
                    "n_classes": 3,
                },
                "quality_summary": {
                    "balanced_accuracy": 0.9352,
                    "f1": 0.9314,
                },
            }
        }
    )

    assert collapsed["test_accuracy"] == 0.9333
    assert collapsed["test_balanced_accuracy"] == 0.9352
    assert collapsed["test_f1_macro"] == 0.9314
    assert collapsed["n_classes"] == 3.0
    assert "accuracy" not in collapsed
    assert "balanced_accuracy" not in collapsed
    assert "f1" not in collapsed


def test_run_metric_collapse_merges_duplicate_identical_node_metrics():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "model_1": {"n_classes": 3},
            "evaluate_1": {"n_classes": 3},
        }
    )

    assert collapsed == {"n_classes": 3}


def test_run_metric_collapse_normalizes_legacy_test_accuracy_alias():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run({"evaluate_1": {"accuracy_test": 0.91}})

    assert collapsed == {"test_accuracy": 0.91}


def test_run_metric_collapse_normalizes_regression_cv_aliases():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "cv_1": {
                "metadata": {"type": "RegressionCV"},
                "R2": 0.82,
                "RMSECV": 0.31,
                "Q2": 0.8,
                "SEP": 0.3,
                "RER": 11.0,
            }
        }
    )

    assert collapsed["r2_cv"] == 0.82
    assert collapsed["rmsecv"] == 0.31
    assert collapsed["q2"] == 0.8
    assert collapsed["sep"] == 0.3
    assert collapsed["rer"] == 11.0
    assert "R2" not in collapsed
    assert "RMSECV" not in collapsed


def test_run_metric_collapse_normalizes_nested_cv_r2_context():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "nested_cv_1": {
                "cv_metrics": {
                    "metadata": {"type": "RegressionCV"},
                    "r2": 0.78,
                    "rmsecv": 0.42,
                    "q2": 0.76,
                }
            }
        }
    )

    assert collapsed["r2_cv"] == 0.78
    assert collapsed["rmsecv"] == 0.42
    assert collapsed["q2"] == 0.76
    assert "r2" not in collapsed


def test_classification_macro_metrics_do_not_promote_rejects_to_classes():
    from spectra_sherpa.app.services.dag.nodes.classification.core_utils import classification_scalar_metrics

    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, -1, 1, -1])

    metrics = classification_scalar_metrics(y_true, y_pred, np.array([0, 1]), prefix="test_")

    assert metrics["test_accuracy"] == pytest.approx(0.5)
    assert metrics["test_balanced_accuracy"] == pytest.approx(0.5)
    assert metrics["test_sensitivity_macro"] == pytest.approx(0.5)


def test_run_metric_collapse_normalizes_regression_test_aliases():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    collapsed = comparable_results_for_run(
        {
            "holdout_1": {
                "metadata": {"type": "RegressionTest"},
                "R2": 0.91,
                "RMSEP": 0.22,
                "MAE": 0.14,
                "bias": -0.02,
                "SEP": 0.21,
                "RER": 18.0,
            }
        }
    )

    assert collapsed["r2_test"] == 0.91
    assert collapsed["rmse_test"] == 0.22
    assert collapsed["mae"] == 0.14
    assert collapsed["bias"] == -0.02
    assert collapsed["sep"] == 0.21
    assert collapsed["rer"] == 18.0
    assert "R2" not in collapsed
    assert "RMSEP" not in collapsed


def test_classifier_training_nodes_emit_split_qualified_metrics_only():
    import inspect

    from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
    from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCANode

    forbidden_aliases = (
        '"accuracy":',
        '"balanced_accuracy":',
        '"f1":',
        '"f1_macro":',
        '"f1_score":',
    )

    for node_cls in (KNNNode, PLSDANode, SIMCANode):
        source = inspect.getsource(node_cls.execute)
        for alias in forbidden_aliases:
            assert alias not in source, f"{node_cls.__name__}.execute emits ambiguous {alias}"


def test_holdout_classification_export_uses_test_accuracy():
    import inspect

    from spectra_sherpa.app.services.dag.nodes.diagnostics import CrossValidationNode, HoldoutEvaluationNode

    cv_source = inspect.getsource(CrossValidationNode.execute)
    assert '"accuracy":' not in cv_source
    assert '"f1_score":' not in cv_source

    node = HoldoutEvaluationNode(node_id="holdout_1", parameters={"task_type": "classification"})
    code = "\n".join(node.generate_python({"y_true": "y_true", "y_pred": "y_pred"}, indent=""))

    assert "'test_accuracy': _acc" in code
    assert "'accuracy': _acc" not in code


def test_regression_diagnostic_exports_use_split_qualified_metrics():
    from spectra_sherpa.app.services.dag.nodes.diagnostics import CrossValidationNode, HoldoutEvaluationNode

    cv_node = CrossValidationNode(node_id="cv_1", parameters={"task_type": "regression"})
    cv_code = "\n".join(cv_node.generate_python({"y_true": "y_true", "y_pred": "y_pred"}, indent=""))

    assert "'r2_cv': _r2" in cv_code
    assert "'rmsecv': _rmse" in cv_code
    assert "'q2': _r2" in cv_code
    assert "'r2': _r2" not in cv_code
    assert "'rmse': _rmse" not in cv_code

    holdout_node = HoldoutEvaluationNode(node_id="holdout_1", parameters={"task_type": "regression"})
    holdout_code = "\n".join(holdout_node.generate_python({"y_true": "y_true", "y_pred": "y_pred"}, indent=""))

    assert "'r2_test': _r2" in holdout_code
    assert "'rmse_test': _rmsep" in holdout_code
    assert "'mae': _mae" in holdout_code
    assert "'R2': _r2" not in holdout_code
    assert "'RMSEP': _rmsep" not in holdout_code


# ---------------------------------------------------------------------------
# Bug #4: load_apply feature_mask ordering
# ---------------------------------------------------------------------------


class TestLoadApplyFeatureMask:
    """Feature mask must be applied BEFORE n_features validation,
    and wavelength comparison must use masked values."""

    def test_feature_mask_applied_before_nfeatures_check(self):
        """Reading the source to verify structural fix."""
        import inspect

        from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode

        source = inspect.getsource(LoadApplyModelNode.execute)

        # feature_mask application should appear before n_features validation
        mask_pos = source.find("Applied saved feature mask")
        nfeat_pos = source.find("Feature count mismatch")
        assert mask_pos < nfeat_pos, "Feature mask application must come before n_features validation"

    def test_variable_select_stores_feature_mask_in_meta(self):
        """variable_select must store the boolean mask in output dataset meta
        so the artifact builder can propagate it to load_apply."""
        from spectra_sherpa.app.lib.axes import FeatureAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        X = np.random.RandomState(1).randn(20, 50)
        fa = FeatureAxis(values=np.linspace(4000, 400, 50))
        ds = SherpaDataset(X=X, feature_axis=fa)

        node = VariableSelectNode(
            node_id="vs_mask",
            parameters={"method": "interval", "region_start": 2000, "region_end": 3000},
        )
        result = asyncio.run(node.execute(X=ds))
        X_selected = result.outputs["X_selected"]

        # Must have feature_mask in meta
        assert "feature_mask" in X_selected.meta, "variable_select must store feature_mask in output dataset meta"
        mask = np.asarray(X_selected.meta["feature_mask"], dtype=bool)
        assert len(mask) == 50, "feature_mask must be over the original feature count"
        assert np.sum(mask) == X_selected.data.shape[1]

    def test_wavelength_comparison_uses_masked_values(self):
        """The axis comparison must use actual_wn[mask], not actual_wn[:len]."""
        import inspect

        from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode

        source = inspect.getsource(LoadApplyModelNode.execute)

        # Should compare masked axis values
        assert (
            "actual_wn[mask]" in source
        ), "Wavelength comparison must use actual_wn[mask] for non-contiguous selections"
