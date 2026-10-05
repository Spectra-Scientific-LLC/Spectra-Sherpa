"""Phase 3 selection node tests.

Covers:
- Nested CV (leakage-safe variable selection inside folds)
- Selection Audit Trail
- Compare Selections (consensus dashboard)
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.model_selection import KFold

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from tests.performance_contract import PerformanceCeiling

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

    def test_nested_cv_export_calls_the_registered_dispatcher_with_exact_parameters(self):
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

        assert "_nested_cv_dispatch" in code
        assert "'coef_threshold': 0.123" in code
        assert "PLSRegression" not in code

    @pytest.mark.asyncio
    async def test_nested_cv_generated_python_is_numerically_identical_to_live_execution(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        node = NestedCVNode(
            "parity",
            {
                "selection_method": "coef_abs",
                "n_components": 2,
                "cv_folds": 3,
                "coef_threshold": 0.01,
                "random_seed": 42,
            },
        )
        live = await node.execute(X=ds, y=y)
        namespace = {"X": ds, "y": y, "results": {}}
        exec("\n".join(node.generate_python({"X": "X", "y": "y"}, indent="")), namespace)
        generated = namespace["results"]["parity"]

        assert generated["oof_evidence"] == live.outputs["oof_evidence"]
        assert generated["cv_metrics"] == live.outputs["cv_metrics"]
        assert generated["stability"] == live.outputs["stability"]

    @pytest.mark.parametrize(
        ("method", "fixed_settings"),
        [
            ("cars", {"n_iterations": 30, "cv_folds_max": 3}),
            (
                "mcuve",
                {"n_resamples": 30, "calibration_fraction": 0.8, "max_selected_variables": 20},
            ),
            (
                "spa",
                {
                    "max_selected_variables": 20,
                    "cv_folds_max": 3,
                    "cv_order": "seeded_random",
                },
            ),
        ],
    )
    def test_nested_cv_selector_profile_exposes_fixed_scientific_choices(self, method, fixed_settings):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _selector_profile

        assert _selector_profile(method) == {
            "schema_version": "spectra-nested-selector-profile/1",
            "method": method,
            "fixed_settings": fixed_settings,
        }

    def test_nested_cv_contract_states_target_seed_and_group_boundary(self):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        contract = NestedCVNode.metadata.resolved_execution_contract()
        assert contract is not None
        assert contract.payload["lifecycle_kind"] == "evaluator"
        assert contract.payload["target_access"] == "required"
        assert contract.payload["group_access"] == "optional"
        assert contract.payload["deterministic"] is False
        assert contract.payload["seed_parameter"] == "random_seed"
        assert contract.payload["managed_optimization_eligibility"] == ("local",)
        component_ids = {item["component_id"] for item in contract.payload["implementation_components"]}
        assert "spectra_sherpa.sdk.validate" in component_ids

    @pytest.mark.asyncio
    async def test_nested_cv_split_identity_is_reproducible_and_seed_bound(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        first = await NestedCVNode(
            "first",
            {"selection_method": "none", "n_components": 2, "cv_folds": 3, "random_seed": 42},
        ).execute(X=ds, y=y)
        repeat = await NestedCVNode(
            "repeat",
            {"selection_method": "none", "n_components": 2, "cv_folds": 3, "random_seed": 42},
        ).execute(X=ds, y=y)
        changed = await NestedCVNode(
            "changed",
            {"selection_method": "none", "n_components": 2, "cv_folds": 3, "random_seed": 43},
        ).execute(X=ds, y=y)

        assert first.outputs["cv_metrics"]["split_plan_digest"] == repeat.outputs["cv_metrics"]["split_plan_digest"]
        assert first.outputs["cv_metrics"]["split_plan_digest"] != changed.outputs["cv_metrics"]["split_plan_digest"]
        assert first.outputs["oof_evidence"]["predictions"] == repeat.outputs["oof_evidence"]["predictions"]
        assert first.outputs["oof_evidence"]["fold_assignments"] == repeat.outputs["oof_evidence"]["fold_assignments"]
        assert first.outputs["oof_evidence"]["split_plan_digest"] == repeat.outputs["oof_evidence"]["split_plan_digest"]
        assert first.outputs["oof_evidence"]["producer"]["node_id"] == "first"
        assert repeat.outputs["oof_evidence"]["producer"]["node_id"] == "repeat"
        assert first.outputs["oof_evidence"]["fold_assignments"] != changed.outputs["oof_evidence"]["fold_assignments"]

    @pytest.mark.asyncio
    async def test_nested_cv_selection_sees_outer_training_rows_only(self, monkeypatch):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node

        X = np.column_stack([np.arange(18, dtype=float), np.linspace(0.0, 1.0, 18)])
        y = 2.0 * X[:, 0] + X[:, 1]
        observed_training_rows: list[tuple[int, ...]] = []

        def record_training_rows(X_train, y_train, method, n_components, **kwargs):
            del y_train, method, n_components, kwargs
            observed_training_rows.append(tuple(sorted(X_train[:, 0].astype(int).tolist())))
            return np.ones(X_train.shape[1], dtype=bool)

        monkeypatch.setattr(nested_cv_node, "_select_variables_inner", record_training_rows)
        await nested_cv_node.NestedCVNode(
            "leakage-proof",
            {"selection_method": "none", "n_components": 1, "cv_folds": 3, "random_seed": 42},
        ).execute(X=X, y=y)

        expected = [
            tuple(sorted(train.tolist())) for train, _ in KFold(n_splits=3, shuffle=True, random_state=42).split(X)
        ]
        assert observed_training_rows == expected
        assert all(len(rows) == 12 for rows in observed_training_rows)

    @pytest.mark.asyncio
    async def test_nested_cv_fails_instead_of_substituting_a_mean_prediction(self, monkeypatch, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node

        ds, y = spectral_dataset
        monkeypatch.setattr(
            nested_cv_node,
            "_select_variables_inner",
            lambda X_train, *args, **kwargs: np.zeros(X_train.shape[1], dtype=bool),
        )
        node = nested_cv_node.NestedCVNode(
            "fail-closed",
            {"selection_method": "vip", "n_components": 2, "cv_folds": 3},
        )
        with pytest.raises(ValueError, match="no component candidate.*every inner fold"):
            await node.execute(X=ds, y=y)

    @pytest.mark.asyncio
    async def test_nested_cv_rejects_silent_multi_target_truncation(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        ds, y = spectral_dataset
        multi_target = np.column_stack([y, y + 1.0])
        with pytest.raises(ValueError, match="exactly one quantitative target"):
            await NestedCVNode("multi", {"selection_method": "none"}).execute(X=ds, y=multi_target)

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"n_components": 0}, "n_components"),
            ({"cv_folds": 1}, "cv_folds"),
            ({"random_seed": -1}, "random_seed"),
            ({"vip_threshold": float("nan")}, "finite"),
            ({"coef_threshold": -0.1}, "coef_threshold"),
        ],
    )
    def test_nested_cv_dispatch_rejects_parameters_outside_the_declared_contract(self, overrides, message):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _canonical_nested_cv_parameters

        parameters = {
            "selection_method": "none",
            "n_components": 2,
            "cv_folds": 3,
            "vip_threshold": 1.0,
            "coef_threshold": 0.01,
            "random_seed": 42,
        }
        parameters.update(overrides)

        with pytest.raises(ValueError, match=message):
            _canonical_nested_cv_parameters(parameters)

    def test_nested_cv_maximum_seed_has_overflow_safe_distinct_derived_seeds(self):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _derive_seed

        derived = {
            _derive_seed(4_294_967_295, purpose=purpose, fold_index=fold)
            for purpose in ("selector", "component_tuning")
            for fold in range(20)
        }
        assert len(derived) == 40
        assert all(0 <= seed <= 4_294_967_295 for seed in derived)

    def test_inner_component_selection_scores_only_the_reported_component_count(self, monkeypatch):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node

        fitted: list[int] = []

        class RecordingPLS:
            def __init__(self, n_components):
                self.n_components = n_components

            def predict(self, X):
                return np.zeros((len(X), 1), dtype=float)

        def record_fit(_X, _y, *, n_components, scale):
            assert scale is False
            fitted.append(n_components)
            return RecordingPLS(n_components)

        monkeypatch.setattr(nested_cv_node.pls_core, "fit_simpls_exact", record_fit)
        selected = nested_cv_node._choose_pls_components_inner_cv(
            np.arange(12, dtype=float).reshape(4, 3),
            np.arange(4, dtype=float),
            max_components=2,
            random_seed=42,
            inner_folds=3,
        )

        assert selected == 1
        assert fitted and set(fitted) == {1}

    def test_nested_cv_sep_removes_declared_positive_prediction_bias(self):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _regression_cv_metrics

        target = np.arange(8, dtype=float)
        scored = _regression_cv_metrics(target, target + 1.0)

        assert scored["bias"] == pytest.approx(1.0)
        assert scored["sep"] == pytest.approx(0.0)
        assert scored["rer"] is None
        assert scored["rer_status"] == "undefined_zero_sep"
        assert scored["metric_registry_version"] == "2"

    def test_nested_cv_rejects_a_split_with_a_one_sample_training_fold(self):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node

        with pytest.raises(ValueError, match="at least two training samples in every outer fold"):
            nested_cv_node._nested_cv_dispatch(
                np.arange(6, dtype=float).reshape(3, 2),
                np.arange(3, dtype=float),
                producer_node_id="nested",
                selection_method="none",
                n_components=1,
                cv_folds=2,
                vip_threshold=1.0,
                coef_threshold=0.01,
                random_seed=42,
            )

    def test_nested_cv_split_digest_is_the_sdk_split_plan_identity(self):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node
        from spectra_sherpa.sdk.validate import Fold, SplitPlan

        X = np.arange(24, dtype=float).reshape(8, 3)
        y = np.arange(8, dtype=float)
        outputs, _ = nested_cv_node._nested_cv_dispatch(
            X,
            y,
            producer_node_id="nested",
            selection_method="none",
            n_components=1,
            cv_folds=4,
            vip_threshold=1.0,
            coef_threshold=0.01,
            random_seed=42,
        )
        folds = tuple(
            Fold(train=np.asarray(train), test=np.asarray(test))
            for train, test in KFold(n_splits=4, shuffle=True, random_state=42).split(X)
        )
        expected = SplitPlan(method="kfold", n_samples=8, folds=folds, grouped=False)

        assert outputs["cv_metrics"]["split_plan_digest"] == expected.digest
        assert outputs["cv_metrics"]["split_plan"]["digest"] == expected.digest
        assert outputs["cv_metrics"]["split_plan"]["root_seed"] == 42

    def test_cars_returns_the_mask_that_produced_the_best_rmsecv(self, monkeypatch):
        from spectra_sherpa.app.services.dag.nodes.selection import cars_node

        class WidthSensitivePLS:
            def __init__(self, width):
                self.width = width
                self.coefficients = np.arange(width, 0, -1, dtype=float).reshape(-1, 1)

            def predict(self, X):
                if self.width == 4:
                    return X[:, :1]
                return np.zeros((len(X), 1), dtype=float)

        monkeypatch.setattr(
            cars_node.pls_core,
            "fit_simpls_exact",
            lambda X, _y, **_kwargs: WidthSensitivePLS(X.shape[1]),
        )
        X = np.column_stack([np.arange(12, dtype=float), np.ones((12, 3))])
        y = X[:, 0]
        mask, _, trace = cars_node._cars_run(
            X,
            y,
            max_components=1,
            cv_folds=3,
            n_iterations=2,
            seed=42,
            fail_on_fit_error=True,
        )

        assert trace[0] == pytest.approx(0.0)
        assert np.array_equal(mask, np.ones(4, dtype=bool))

    @pytest.mark.parametrize(("method", "helper_name"), [("cars", "_cars_run"), ("mcuve", "_mcuve_dispatch")])
    def test_nested_cv_requires_strict_delegated_selector_execution(self, monkeypatch, method, helper_name):
        from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node

        observed: list[bool] = []

        def reject_permissive_execution(*args, **kwargs):
            del args
            observed.append(method == "mcuve" or kwargs.get("fail_on_fit_error"))
            raise RuntimeError("declared selector failure")

        helper_module = nested_cv_node.cars_node if method == "cars" else nested_cv_node.mcuve_node
        monkeypatch.setattr(helper_module, helper_name, reject_permissive_execution)
        X = np.arange(30, dtype=float).reshape(10, 3)
        y = np.arange(10, dtype=float)

        with pytest.raises(RuntimeError, match="declared selector failure"):
            nested_cv_node._select_variables_inner(X, y, method, 2, 1.0, 0.01, 42)

        assert observed == [True]

    @pytest.mark.parametrize(
        ("module_name", "helper_name", "arguments", "message"),
        [
            (
                "cars_node",
                "_cars_run",
                {"max_components": 2, "cv_folds": 3, "n_iterations": 3},
                "CARS Monte Carlo calibration PLS fit failed",
            ),
            (
                "mcuve_node",
                "_mcuve_dispatch",
                {
                    "n_components": 2,
                    "n_resamples": 20,
                    "calibration_fraction": 0.8,
                    "n_variables": 2,
                    "random_seed": 42,
                },
                "MC-UVE PLS fit failed at resample 0",
            ),
        ],
    )
    def test_delegated_selector_strict_mode_rejects_fit_failure(
        self, monkeypatch, module_name, helper_name, arguments, message
    ):
        from spectra_sherpa.app.services.dag.nodes.selection import cars_node, mcuve_node

        module = cars_node if module_name == "cars_node" else mcuve_node

        def fail_fit(*_args, **_kwargs):
            raise ValueError("synthetic fit failure")

        monkeypatch.setattr(module.pls_core, "fit_simpls_exact", fail_fit)
        X = np.arange(40, dtype=float).reshape(10, 4)
        y = np.arange(10, dtype=float)

        with pytest.raises(RuntimeError, match=message):
            if module_name == "cars_node":
                getattr(module, helper_name)(X, y, seed=42, fail_on_fit_error=True, **arguments)
            else:
                getattr(module, helper_name)(X, y, **arguments)

    @pytest.mark.asyncio
    async def test_nested_cv_fixed_local_workload_stays_inside_reviewed_ceiling(self):
        from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode

        rng = np.random.RandomState(9)
        X = rng.normal(size=(40, 25))
        y = X[:, :3].sum(axis=1) + rng.normal(scale=0.05, size=40)
        with PerformanceCeiling("selection.nested_cv", "40x25-none-3-fold", 5.0).measure():
            await NestedCVNode(
                "bounded",
                {"selection_method": "none", "n_components": 2, "cv_folds": 3, "random_seed": 42},
            ).execute(X=X, y=y)

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

        evidence = result.outputs["oof_evidence"]
        y_pred = np.asarray(evidence["predictions"])
        assert y_pred.shape == (60,)
        assert np.all(np.isfinite(y_pred))
        fold_assignments = np.asarray(evidence["fold_assignments"])
        assert fold_assignments.shape == (60,)
        # JSON round-tripping yields the platform's native integer width
        # (int32 on Windows, int64 on 64-bit Unix). The scientific contract is
        # integral fold identity, not one platform-specific storage width.
        assert np.issubdtype(fold_assignments.dtype, np.integer)
        np.testing.assert_array_equal(np.unique(fold_assignments), np.arange(5))

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
        assert sum(fa_info["include_mask"]) == 25
        assert len(fa_info["selection_scores"]) == 50
        assert len(fa_info["selection_scores_sha256"]) == 64


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
        assert report["method_count"] == 2
        assert "jaccard_matrix" in report
        assert report["consensus_count"] > 0
        assert 0 <= report["mean_pairwise_jaccard"] <= 1.0

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
        assert report["method_count"] == 3
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
        with pytest.raises(ValueError, match="requires mask_1 and mask_2"):
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

        counts = result.outputs["report"]["vote_counts"]
        # 25 features selected by both (freq=2), 25 by one only (freq=1)
        assert counts.count(2) == 25
        assert counts.count(1) == 25
        assert counts.count(0) == 0
