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


class TestTrainTestSplitTargetPreservation:
    """The canonical partition must reattach y to both split datasets."""

    @pytest.fixture
    def partition_node(self):
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        return TrainTestSplitNode(
            node_id="test_sp",
            parameters={"split_method": "random", "test_size": 0.3, "random_seed": 42},
        )

    @pytest.fixture
    def dataset_with_target(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.RandomState(1).randn(20, 50), target=np.arange(20, dtype=np.float64))
        return ds

    def test_xcal_has_target(self, partition_node, dataset_with_target):
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        X_train = result["X_train"]
        assert X_train.target is not None, "X_train must have target reattached"
        assert len(X_train.target) == X_train.data.shape[0]

    def test_xtest_has_target(self, partition_node, dataset_with_target):
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        X_test = result["X_test"]
        assert X_test.target is not None, "X_test must have target reattached"
        assert len(X_test.target) == X_test.data.shape[0]

    def test_target_values_match_indices(self, partition_node, dataset_with_target):
        """Targets on X_cal/X_test must be the correct slices, not shuffled."""
        result = asyncio.run(partition_node.execute(X=dataset_with_target, y=dataset_with_target.target))
        cal_idx = result["train_indices"]
        test_idx = result["test_indices"]
        y_full = dataset_with_target.target

        np.testing.assert_array_equal(result["X_train"].target, y_full[cal_idx])
        np.testing.assert_array_equal(result["X_test"].target, y_full[test_idx])

    def test_no_target_when_y_is_none(self, partition_node):
        """When no y is provided, X_cal/X_test should not have spurious targets."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.randn(20, 50))
        result = asyncio.run(partition_node.execute(X=ds))
        # Target may or may not be None depending on source, but no target
        # outputs may be fabricated when the canonical input has none.
        assert "y_train" not in result
        assert "y_test" not in result


# ---------------------------------------------------------------------------
# Bug #2: generate_python() completeness
# ---------------------------------------------------------------------------


class TestGeneratePythonCompleteness:
    """generate_python() must assign results dict and not reference undefined vars."""

    def test_sample_partition_has_results_dict(self):
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        node = TrainTestSplitNode(
            node_id="sp1",
            parameters={"split_method": "kennard_stone", "test_size": 0.2},
        )
        lines = node.generate_python({"X": "data", "y": "target"})
        code = "\n".join(lines)
        assert "results['sp1']" in code, "generate_python must assign results dict"

    def test_classification_exports_emit_canonical_metrics_and_confusion_matrices(self):
        from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
        from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCANode

        nodes = [
            KNNNode(node_id="knn_export", parameters={"n_neighbors": 3}),
            PLSDANode(node_id="plsda_export", parameters={"n_components": 2, "scale": False}),
            SIMCANode(node_id="simca_export", parameters={"n_components": 2}),
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
            if isinstance(node, (KNNNode, PLSDANode, SIMCANode)):
                # Canonical repaired classifiers delegate generated execution to
                # the same source-closed operation as live execution. Validate
                # returned contracts below instead of requiring duplicated
                # implementation details in generated source text.
                helper = {
                    KNNNode: "_knn_export_outputs",
                    PLSDANode: "_plsda_export_outputs",
                    SIMCANode: "_simca_export_outputs",
                }[type(node)]
                assert helper in code
            else:
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
            canonical = (
                output["metrics"]
                if isinstance(node, (KNNNode, PLSDANode, SIMCANode))
                else output["metrics"]["classification_metrics"]
            )
            assert canonical["task_type"] == "classification"
            assert canonical["primary_split"] == "train"
            assert set(canonical["splits"]) == {"train"}
            assert canonical["confusion_matrices"]["train"]
            assert set(canonical["confusion_matrices"]) == {"train"}
            assert output["confusion_matrix_train"].shape == (3, 3)
            assert "confusion_matrix_cv" not in output
            assert "y_pred_cv" not in output["metadata"]

    def test_static_validation_accepts_canonical_spectral_file_for_spectrum_nodes(self):
        from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

        executor = DAGExecutor()
        executor.add_node(
            WorkflowNode(
                node_id="src",
                node_type="data.file_load",
                parameters={"experiment_id": 1, "file_id": 1, "stage": "raw"},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="smooth",
                node_type="preprocess.smooth",
                parameters={"method": "savitzky_golay", "size": 5, "order": 2},
            )
        )
        executor.add_edge(WorkflowEdge(from_node="src", to_node="smooth"))

        result = executor.validate_full()
        assert result.is_valid

    def test_train_test_split_export_preserves_targets(self):
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        node = TrainTestSplitNode(
            node_id="sp_target",
            parameters={"split_method": "random", "test_size": 0.2},
        )
        code = "\n".join(node.generate_python({"X": "data", "y": "target"}))
        assert "bind_split_target" in code
        assert "materialize_split_outputs" in code
        assert "_y_input = target" in code

    def test_sample_partition_spxy_export(self):
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        node = TrainTestSplitNode(
            node_id="sp2",
            parameters={"split_method": "spxy", "test_size": 0.2},
        )
        lines = node.generate_python({"X": "data", "y": "target"})
        code = "\n".join(lines)
        assert "spxy" in code
        assert "results['sp2']" in code

    def test_sample_partition_stratified_export(self):
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        node = TrainTestSplitNode(
            node_id="sp3",
            parameters={"split_method": "stratified", "test_size": 0.3, "random_seed": 0},
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
        # Generated execution delegates to the same canonical implementation
        # as live DAG execution; it may not carry a second VIP implementation.
        assert "_variable_select_execute" in code
        assert "results['vs1']" in code
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
        assert "_variable_select_execute" in code
        assert "results['vs3']" in code

    def test_variable_select_peak_window_negative_extrema_is_opt_in(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        default_node = VariableSelectNode(
            node_id="vs_peak_default",
            parameters={"method": "peak_window", "peak_prominence": 0.1, "peak_half_window": 5},
        )
        default_code = "\n".join(default_node.generate_python({"X": "data"}))
        assert "'include_negative_extrema': False" in default_code

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
        assert "'include_negative_extrema': True" in opt_in_code

    def test_variable_select_export_preserves_targets(self):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs_target",
            parameters={"method": "interval", "region_start": 1000, "region_end": 2000},
        )
        code = "\n".join(node.generate_python({"X": "data"}))
        assert "_variable_select_execute" in code
        assert "results['vs_target'] = _vs_outputs" in code

    def test_variable_select_unknown_method_defines_mask(self):
        """Even for unknown/selectivity_ratio methods, _mask must be defined."""
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        node = VariableSelectNode(
            node_id="vs4",
            parameters={"method": "selectivity_ratio", "threshold": 1.0},
        )
        lines = node.generate_python({"X": "data"})
        code = "\n".join(lines)
        assert "_variable_select_execute" in code


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


def test_classification_evaluator_export_uses_the_canonical_authority():
    import inspect

    from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import ClassificationEvaluatorV2Node
    from spectra_sherpa.app.services.dag.nodes.diagnostics import CrossValidationNode

    cv_source = inspect.getsource(CrossValidationNode.execute)
    assert '"accuracy":' not in cv_source
    assert '"f1_score":' not in cv_source

    node = ClassificationEvaluatorV2Node(node_id="score", parameters={})
    code = "\n".join(node.generate_python({"y_true": "y_true", "default": "y_pred"}, indent=""))

    assert "evaluate_classification_v2" in code
    assert "y_pred, y_true" in code
    assert "results['score']" in code


def test_regression_diagnostic_exports_use_canonical_metric_authorities():
    from spectra_sherpa.app.services.dag.nodes.diagnostics import CrossValidationNode
    from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import RegressionEvaluatorV2Node

    cv_node = CrossValidationNode(node_id="cv_1", parameters={})
    cv_code = "\n".join(
        cv_node.generate_python(
            {"evidence": "oof_evidence"},
            indent="",
        )
    )

    # The canonical exporter delegates to the same closed evaluator as live
    # execution.  Split-qualified metric names are proved from that evaluator's
    # output in test_c2_cross_validation_contract.py; this regression test must
    # not freeze the deleted hand-written export implementation.
    assert "_cross_validation_execute" in cv_code
    assert "oof_evidence" in cv_code
    assert "results['cv_1'] = _cv_outputs" in cv_code
    assert "'r2': _r2" not in cv_code
    assert "'rmse': _rmse" not in cv_code

    evaluator = RegressionEvaluatorV2Node(node_id="score", parameters={})
    evaluator_code = "\n".join(evaluator.generate_python({"y_true": "y_true", "default": "y_pred"}, indent=""))

    assert "evaluate_regression_v2" in evaluator_code
    assert "y_pred, y_true" in evaluator_code
    assert "results['score']" in evaluator_code
    assert "'R2'" not in evaluator_code
    assert "'RMSEP'" not in evaluator_code


# ---------------------------------------------------------------------------
# Bug #4: load_apply feature_mask ordering
# ---------------------------------------------------------------------------


class TestLoadApplyFeatureMask:
    """Feature mask must be applied BEFORE n_features validation,
    and wavelength comparison must use masked values."""

    def test_feature_mask_applied_before_nfeatures_check(self):
        """The shared authority accepts raw width, masks it, then validates prepared width."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services import model_application

        dataset = SherpaDataset(X=np.arange(8, dtype=np.float64).reshape(2, 4))
        manifest = {
            "n_features": 2,
            "feature_mask": [False, True, False, True],
        }

        matrix = np.asarray(dataset.X)
        model_application.validate_feature_contract(matrix, dataset, manifest)
        prepared, warnings = model_application._apply_feature_mask(matrix, dataset, manifest)
        model_application.validate_prepared_feature_contract(prepared, manifest)

        np.testing.assert_array_equal(prepared, matrix[:, [1, 3]])
        assert warnings == ["Applied saved feature mask (4 -> 2 features)"]

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
        """A non-contiguous mask compares selected coordinates, never an axis prefix."""
        from spectra_sherpa.app.lib.axes import FeatureAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services.model_application import validate_feature_contract

        dataset = SherpaDataset(
            X=np.ones((2, 4), dtype=np.float64),
            feature_axis=FeatureAxis(
                values=np.array([100.0, 200.0, 300.0, 400.0]),
                units="cm-1",
            ),
        )
        manifest = {
            "n_features": 2,
            "feature_mask": [False, True, False, True],
            "feature_axis": [200.0, 400.0],
            "feature_axis_units": "cm^-1",
        }

        validate_feature_contract(np.asarray(dataset.X), dataset, manifest)

        with pytest.raises(ValueError, match="feature-axis values differ"):
            validate_feature_contract(
                np.asarray(dataset.X),
                dataset,
                {**manifest, "feature_axis": [100.0, 200.0]},
            )
