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
        result = asyncio.get_event_loop().run_until_complete(
            partition_node.execute(X=dataset_with_target, y=dataset_with_target.target)
        )
        X_cal = result.outputs["X_cal"]
        assert X_cal.target is not None, "X_cal must have target reattached"
        assert len(X_cal.target) == X_cal.data.shape[0]

    def test_xtest_has_target(self, partition_node, dataset_with_target):
        result = asyncio.get_event_loop().run_until_complete(
            partition_node.execute(X=dataset_with_target, y=dataset_with_target.target)
        )
        X_test = result.outputs["X_test"]
        assert X_test.target is not None, "X_test must have target reattached"
        assert len(X_test.target) == X_test.data.shape[0]

    def test_target_values_match_indices(self, partition_node, dataset_with_target):
        """Targets on X_cal/X_test must be the correct slices, not shuffled."""
        result = asyncio.get_event_loop().run_until_complete(
            partition_node.execute(X=dataset_with_target, y=dataset_with_target.target)
        )
        cal_idx = result.outputs["cal_indices"]
        test_idx = result.outputs["test_indices"]
        y_full = dataset_with_target.target

        np.testing.assert_array_equal(result.outputs["X_cal"].target, y_full[cal_idx])
        np.testing.assert_array_equal(result.outputs["X_test"].target, y_full[test_idx])

    def test_no_target_when_y_is_none(self, partition_node):
        """When no y is provided, X_cal/X_test should not have spurious targets."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.randn(20, 50))
        result = asyncio.get_event_loop().run_until_complete(partition_node.execute(X=ds))
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
# Bug #3: load_apply feature_mask ordering
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
        result = asyncio.get_event_loop().run_until_complete(node.execute(X=ds))
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
