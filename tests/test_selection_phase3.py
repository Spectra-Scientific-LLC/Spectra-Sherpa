"""Phase 3 selection node tests.

Covers:
- Nested CV (leakage-safe variable selection inside folds)
- Selection Audit Trail
- Compare Selections (consensus dashboard)
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

# ── Shared Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def spectral_dataset():
    """Synthetic spectral dataset with y correlated to a few features."""
    rng = np.random.RandomState(42)
    n_samples, n_features = 60, 50
    X = rng.randn(n_samples, n_features)
    # y depends on features 10-15 (signal region)
    y = X[:, 10:16].sum(axis=1) + rng.randn(n_samples) * 0.1
    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.linspace(400, 4000, n_features), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"s{i}" for i in range(n_samples)]),
        target=y,
    )
    return ds, y


# ── Nested CV Tests ───────────────────────────────────────────────────


class TestNestedCVNode:
    """Leakage-safe nested cross-validation."""

    @pytest.mark.asyncio
    async def test_basic_nested_cv_vip(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv",
            {
                "selection_method": "vip",
                "n_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        metrics = result.outputs["cv_metrics"]
        assert "rmsecv" in metrics
        assert "r2" in metrics
        assert "q2" in metrics
        assert metrics["selection_method"] == "vip"
        assert metrics["component_selection"] == "inner_cv"
        assert len(metrics["per_fold_n_selected"]) == 3
        assert len(metrics["per_fold_n_components"]) == 3
        assert all(1 <= n <= 3 for n in metrics["per_fold_n_components"])

    @pytest.mark.asyncio
    async def test_nested_cv_no_selection(self, spectral_dataset):
        """None method = full spectrum, should still work."""
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv_none",
            {
                "selection_method": "none",
                "n_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        # All features selected in every fold
        for n in result.outputs["cv_metrics"]["per_fold_n_selected"]:
            assert n == 50

    @pytest.mark.asyncio
    async def test_nested_cv_coef_abs(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv_coef",
            {
                "selection_method": "coef_abs",
                "n_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["rmsecv"] > 0
        assert result.diagnostics["selection_stability"] >= 0

    def test_nested_cv_coef_abs_export_uses_runtime_threshold(self):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        node = NestedCVNode(
            "test_ncv_coef_export",
            {
                "selection_method": "coef_abs",
                "n_components": 3,
                "cv_folds": 3,
                "coef_threshold": 0.123,
            },
        )

        code = "\n".join(node.generate_python({"X": "X", "y": "y"}, indent=""))

        assert "_thresh = 0.123" in code
        assert "np.median(_coefs)" not in code
        assert "_mask[np.argsort(_coefs)[-_top_n:]] = True" in code

    @pytest.mark.asyncio
    async def test_nested_cv_stability_report(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv_stab",
            {
                "selection_method": "vip",
                "n_components": 2,
                "cv_folds": 4,
            },
        )
        result = await node.execute(X=ds, y=y)

        stability = result.outputs["stability"]
        assert "mean_jaccard" in stability
        assert 0 <= stability["mean_jaccard"] <= 1.0
        assert len(stability["per_variable_frequency"]) == 50

    @pytest.mark.asyncio
    async def test_nested_cv_predictions_shape(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv_pred",
            {
                "selection_method": "vip",
                "n_components": 3,
                "cv_folds": 5,
            },
        )
        result = await node.execute(X=ds, y=y)

        y_pred = result.outputs["y_pred"]
        assert y_pred.shape == (60,)
        assert np.all(np.isfinite(y_pred))

    @pytest.mark.asyncio
    async def test_nested_cv_spa_method(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "test_ncv_spa",
            {
                "selection_method": "spa",
                "n_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["selection_method"] == "spa"
        assert result.diagnostics["mean_n_selected"] > 0


# ── Selection Audit Tests ─────────────────────────────────────────────


class TestSelectionAuditNode:
    """Selection audit trail node."""

    @pytest.mark.asyncio
    async def test_audit_with_provenance(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node import SelectionAuditNode

        ds, y = spectral_dataset
        # Add some selection provenance
        add_processing_step(
            ds,
            "selection.variable_select",
            {
                "method": "interval",
                "n_selected": 20,
            },
            "node_1",
        )
        add_processing_step(
            ds,
            "preprocess.smooth",
            {
                "window_length": 11,
            },
            "node_2",
        )
        add_processing_step(
            ds,
            "selection.cars",
            {
                "n_iterations": 50,
                "n_selected": 15,
            },
            "node_3",
        )

        node = SelectionAuditNode("test_audit", {"include_scores": True})
        result = await node.execute(X=ds)

        audit = result.outputs["audit"]
        assert audit["n_selection_steps"] == 2  # only selection.* steps
        assert "selection.variable_select" in audit["methods_applied"]
        assert "selection.cars" in audit["methods_applied"]
        assert audit["total_provenance_steps"] == 3  # includes preprocessing

    @pytest.mark.asyncio
    async def test_audit_empty_provenance(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node import SelectionAuditNode

        ds, _ = spectral_dataset
        node = SelectionAuditNode("test_audit2", {})
        result = await node.execute(X=ds)

        audit = result.outputs["audit"]
        assert audit["n_selection_steps"] == 0
        assert audit["methods_applied"] == []

    @pytest.mark.asyncio
    async def test_audit_passthrough(self, spectral_dataset):
        """Audit node should pass X through unchanged."""
        from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node import SelectionAuditNode

        ds, _ = spectral_dataset
        node = SelectionAuditNode("test_audit3", {})
        result = await node.execute(X=ds)

        assert result.outputs["X_out"] is ds

    @pytest.mark.asyncio
    async def test_audit_feature_axis_info(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node import SelectionAuditNode

        ds, _ = spectral_dataset
        # Apply a mask to the feature axis (re-assign since .feature_axis returns a copy)
        fa = ds.feature_axis
        mask = np.ones(50, dtype=bool)
        mask[25:] = False
        fa.apply_mask(mask, method="test_method", scores=np.random.rand(50))
        ds.feature_axis = fa

        node = SelectionAuditNode("test_audit4", {"include_scores": True})
        result = await node.execute(X=ds)

        fa_info = result.outputs["audit"]["feature_axis"]
        assert fa_info["selection_method"] == "test_method"
        assert fa_info["n_included"] == 25
        assert "scores_summary" in fa_info


# ── Compare Selections Tests ─────────────────────────────────────────


class TestCompareSelectionsNode:
    """Comparative selection dashboard."""

    @pytest.mark.asyncio
    async def test_basic_comparison(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import CompareSelectionsNode

        ds, _ = spectral_dataset
        rng = np.random.RandomState(42)
        mask1 = rng.rand(50) > 0.5
        mask2 = rng.rand(50) > 0.6

        node = CompareSelectionsNode("test_cmp", {"consensus_threshold": 0.5})
        result = await node.execute(X=ds, mask_1=mask1, mask_2=mask2)

        report = result.outputs["report"]
        assert report["n_methods"] == 2
        assert "jaccard_matrix" in report
        assert report["n_consensus"] > 0
        assert 0 <= report["mean_jaccard"] <= 1.0

    @pytest.mark.asyncio
    async def test_comparison_three_masks(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import CompareSelectionsNode

        ds, _ = spectral_dataset
        # Create overlapping masks
        mask1 = np.zeros(50, dtype=bool)
        mask1[:20] = True  # first 20
        mask2 = np.zeros(50, dtype=bool)
        mask2[10:30] = True  # 10-30
        mask3 = np.zeros(50, dtype=bool)
        mask3[15:35] = True  # 15-35

        node = CompareSelectionsNode("test_cmp3", {"consensus_threshold": 0.5})
        result = await node.execute(X=ds, mask_1=mask1, mask_2=mask2, mask_3=mask3)

        report = result.outputs["report"]
        assert report["n_methods"] == 3
        # Consensus at 0.5 means selected by >= 2 of 3 methods
        consensus = result.outputs["consensus_mask"]
        assert consensus.dtype == bool

    @pytest.mark.asyncio
    async def test_comparison_consensus_shape(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import CompareSelectionsNode

        ds, _ = spectral_dataset
        mask1 = np.ones(50, dtype=bool)
        mask2 = np.ones(50, dtype=bool)
        mask2[40:] = False  # exclude last 10

        node = CompareSelectionsNode("test_cmp_shape", {"consensus_threshold": 1.0})
        result = await node.execute(X=ds, mask_1=mask1, mask_2=mask2)

        X_cons = result.outputs["X_consensus"]
        # Consensus at 1.0 = intersection: both must agree
        assert X_cons.X.shape[1] == 40
        assert "feature_mask" in X_cons.meta

    @pytest.mark.asyncio
    async def test_comparison_requires_two_masks(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import CompareSelectionsNode

        ds, _ = spectral_dataset
        mask1 = np.ones(50, dtype=bool)

        node = CompareSelectionsNode("test_cmp_err", {})
        with pytest.raises(ValueError, match="At least 2 masks"):
            await node.execute(X=ds, mask_1=mask1)

    @pytest.mark.asyncio
    async def test_comparison_frequency_histogram(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import CompareSelectionsNode

        ds, _ = spectral_dataset
        mask1 = np.ones(50, dtype=bool)
        mask2 = np.zeros(50, dtype=bool)
        mask2[:25] = True

        node = CompareSelectionsNode("test_cmp_hist", {"consensus_threshold": 0.5})
        result = await node.execute(X=ds, mask_1=mask1, mask_2=mask2)

        hist = result.outputs["report"]["frequency_histogram"]
        assert "bins" in hist
        assert "counts" in hist
        # 25 features selected by both (freq=2), 25 by one only (freq=1)
        assert hist["counts"][2] == 25  # both methods
        assert hist["counts"][1] == 25  # one method only
        assert hist["counts"][0] == 0  # neither
