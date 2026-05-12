"""Regression tests for v0.4.3 algorithm-audit fixes (issues #1–#5).

Covers:
  1. MCR-ALS tol default tightened from 0.1 → 1e-5 + loose-tol warning
  2. PLS regression node now emits per-sample Hotelling T² + Q with
     Pomerantsev (J. Chemom. 2008) DD critical limits
  3. PLS scale default flipped True → False (spectroscopy convention)
  4. PLS-DA gained a Mahalanobis (mdatools-style) Bayesian rule alongside softmax
  5. SIMCA defaults to Pomerantsev DD limits, with the classical F/χ² path preserved

The diagnostics helpers ship in
``spectra_sherpa/app/services/dag/nodes/_chemometric_diagnostics.py``; the unit
tests here pin their numerical behaviour against textbook formulae so a future
refactor can't silently change semantics.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
import yaml

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes._chemometric_diagnostics import (
    hotelling_t2_per_sample,
    pomerantsev_dd_limit,
    q_residuals_per_sample,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import (
    _plsda_mahalanobis_probabilities,
)

_skip_no_scp = pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")


@pytest.fixture
def make_node():
    def _make(node_type: str, params: dict | None = None, node_id: str = "test"):
        return node_registry.create_node(node_type, node_id, params or {})

    return _make


def _make_spectral_dataset(
    n_samples: int = 30,
    n_features: int = 60,
    *,
    n_targets: int = 0,
    target_type: str = "continuous",
    seed: int = 42,
) -> SherpaDataset:
    rng = np.random.RandomState(seed)
    X = np.abs(rng.randn(n_samples, n_features).astype(np.float64)) + 0.1

    target = None
    target_context = None
    if n_targets > 0:
        if target_type == "continuous":
            target = rng.randn(n_samples, n_targets) if n_targets > 1 else rng.randn(n_samples)
        else:
            classes = np.array(["A", "B", "C"], dtype=object)
            target = np.resize(classes, n_samples)
        target_context = TargetContext(target_type=target_type)

    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.linspace(350, 900, n_features), title="Wavelength", units="nm"),
        sample_axis=SampleAxis(values=np.arange(n_samples), title="Sample", units=""),
        domain=DomainContext(technique="UV-Vis", data_quantity="Absorbance", expected_units="nm"),
        target=target,
        target_context=target_context,
        backend="numpy",
    )


# ---------------------------------------------------------------------------
# _chemometric_diagnostics — unit tests
# ---------------------------------------------------------------------------


class TestDiagnosticsHelpers:
    def test_t2_pca_form_matches_explicit_sum(self):
        """T²_i = Σ_h t_{i,h}² / λ_h for orthogonal PCA scores."""
        rng = np.random.RandomState(0)
        scores = rng.randn(20, 3)
        eigenvalues = np.array([4.0, 1.5, 0.5])
        expected = np.sum((scores**2) / eigenvalues, axis=1)
        actual = hotelling_t2_per_sample(scores, eigenvalues=eigenvalues)
        np.testing.assert_allclose(actual, expected, rtol=1e-12)

    def test_t2_pls_form_matches_explicit_mahalanobis(self):
        """T²_i = t_i' Σ⁻¹ t_i for non-orthogonal PLS scores."""
        rng = np.random.RandomState(1)
        scores = rng.randn(50, 4)
        cov = (scores.T @ scores) / (scores.shape[0] - 1)
        cov_inv = np.linalg.inv(cov)
        expected = np.array([s @ cov_inv @ s for s in scores])
        actual = hotelling_t2_per_sample(scores, score_covariance=cov)
        np.testing.assert_allclose(actual, expected, rtol=1e-12)

    def test_t2_requires_eigenvalues_or_covariance(self):
        with pytest.raises(ValueError, match="eigenvalues"):
            hotelling_t2_per_sample(np.zeros((3, 2)))

    def test_q_residuals_is_squared_row_norm_of_residual(self):
        rng = np.random.RandomState(2)
        X = rng.randn(15, 8)
        X_hat = rng.randn(15, 8)
        expected = np.sum((X - X_hat) ** 2, axis=1)
        actual = q_residuals_per_sample(X, X_hat)
        np.testing.assert_allclose(actual, expected, rtol=1e-12)

    def test_q_residuals_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            q_residuals_per_sample(np.zeros((3, 4)), np.zeros((3, 5)))

    def test_pomerantsev_dd_limit_matches_method_of_moments(self):
        """DoF = 2μ²/σ²; crit = μ/DoF · χ²(α, DoF)."""
        from scipy.stats import chi2

        rng = np.random.RandomState(3)
        # Chi-square-like values; DD method should recover something close to
        # the empirical 95th percentile.
        vals = chi2.rvs(df=4, size=2000, random_state=rng)
        crit, dof, h = pomerantsev_dd_limit(vals, 0.95)
        mean_v = np.mean(vals)
        var_v = np.var(vals, ddof=1)
        expected_dof = 2 * mean_v * mean_v / var_v
        expected_h = mean_v / expected_dof
        expected_crit = expected_h * chi2.ppf(0.95, expected_dof)
        np.testing.assert_allclose(crit, expected_crit, rtol=1e-10)
        np.testing.assert_allclose(dof, expected_dof, rtol=1e-10)
        np.testing.assert_allclose(h, expected_h, rtol=1e-10)
        # Sanity: DD limit should bracket the empirical 95th percentile within
        # a generous tolerance on a chi-square-distributed input.
        assert abs(crit - np.quantile(vals, 0.95)) / np.quantile(vals, 0.95) < 0.25

    def test_pomerantsev_dd_limit_falls_back_for_degenerate_input(self):
        # Single-value sample → empirical quantile fallback, NaN DoF/h.
        crit, dof, h = pomerantsev_dd_limit(np.array([1.0]), 0.95)
        assert crit == pytest.approx(1.0)
        assert np.isnan(dof)
        assert np.isnan(h)

    def test_pomerantsev_dd_limit_zero_variance_fallback(self):
        # Zero variance → can't form moments; should fall back to quantile.
        crit, dof, h = pomerantsev_dd_limit(np.array([2.5, 2.5, 2.5, 2.5]), 0.99)
        assert crit == pytest.approx(2.5)
        assert np.isnan(dof)
        assert np.isnan(h)


# ---------------------------------------------------------------------------
# Issue 1 — MCR-ALS default tol tightened
# ---------------------------------------------------------------------------


class TestMcrDefaults:
    def test_default_tol_is_tight(self, make_node):
        node = make_node("model.mcr_als", {})
        # Either set explicitly on the registered param, or the executor's
        # fallback — both should be the new 1e-5.
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["tol"] == pytest.approx(1e-5)
        assert params_dict["max_iter"] == 200

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_loose_tol_emits_warning(self, make_node, caplog):
        ds = _make_spectral_dataset(n_samples=15, n_features=40)
        node = make_node("model.mcr_als", {"n_components": 2, "tol": 0.1, "max_iter": 20})
        with caplog.at_level(logging.WARNING):
            await node.execute(input_data=ds)
        assert any(
            "loose" in rec.message.lower() and "mcr-als" in rec.message.lower() for rec in caplog.records
        ), "Expected a loose-tolerance warning when MCR-ALS runs with tol > 1e-3"


# ---------------------------------------------------------------------------
# Issue 3 — PLS scale default flipped
# ---------------------------------------------------------------------------


class TestPlsScaleDefault:
    def test_default_scale_is_false(self, make_node):
        node = make_node("model.pls", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["scale"] is False

    def test_plsda_default_scale_is_false(self, make_node):
        node = make_node("classification.plsda", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["scale"] is False

    def test_shipped_pls_workflows_pin_scale_false(self):
        templates_dir = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/templates"
        pls_node_types = {"model.pls", "classification.plsda"}
        missing: list[str] = []

        for path in templates_dir.glob("*.yaml"):
            doc = yaml.safe_load(path.read_text())
            nodes = (doc.get("template_data") or {}).get("nodes") or []
            for node in nodes:
                if node.get("node_type") in pls_node_types:
                    params = node.get("parameters") or {}
                    if params.get("scale") is not False:
                        missing.append(f"{path.name}:{node.get('node_id')}")

        assert missing == []


# ---------------------------------------------------------------------------
# Issue 2 — PLS regression emits T² + Q with DD limits
# ---------------------------------------------------------------------------


class TestPlsT2QEmission:
    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_emits_per_sample_t2_and_q(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=50, n_targets=1)
        node = make_node("model.pls", {"n_components": 3, "cv_method": "none"})
        result = await node.execute(X=ds)
        outputs = result.outputs if hasattr(result, "outputs") else result
        x_scores = outputs["X_scores"]
        meta = x_scores.meta

        assert "hotelling_t2" in meta, "PLS node must emit per-sample Hotelling T²"
        assert "q_residuals" in meta, "PLS node must emit per-sample Q-residuals"
        assert "t2_limit" in meta and "q_limit" in meta
        assert meta["t2_q_method"] == "pomerantsev_dd_moments"
        assert meta["t2_q_confidence"] == 0.95

        t2 = np.asarray(meta["hotelling_t2"], dtype=np.float64)
        q = np.asarray(meta["q_residuals"], dtype=np.float64)
        assert t2.shape == (ds.X.shape[0],)
        assert q.shape == (ds.X.shape[0],)
        assert np.all(t2 >= -1e-9)
        assert np.all(q >= -1e-9)
        assert meta["t2_limit"] > 0.0
        assert meta["q_limit"] > 0.0

        diagnostics = result.diagnostics if hasattr(result, "diagnostics") else {}
        assert diagnostics.get("t2_limit") is not None
        assert diagnostics.get("q_limit") is not None
        assert diagnostics.get("n_t2_outliers") is not None
        assert diagnostics.get("n_q_outliers") is not None


# ---------------------------------------------------------------------------
# Issue 4 — PLS-DA Mahalanobis rule
# ---------------------------------------------------------------------------


class TestPlsdaMahalanobisRule:
    def test_mahalanobis_classifies_well_separated_clusters(self):
        """On two clusters separated by 5σ in score space, the Bayesian rule
        must assign every test point to its correct class with probability ≈ 1.
        """
        rng = np.random.RandomState(7)
        n_per_class = 50
        # Class A near (0,0), class B near (5,5)
        train_a = rng.randn(n_per_class, 2)
        train_b = rng.randn(n_per_class, 2) + np.array([5.0, 5.0])
        train_scores = np.vstack([train_a, train_b])
        train_labels = np.array(["A"] * n_per_class + ["B"] * n_per_class, dtype=object)
        classes = np.array(["A", "B"], dtype=object)

        # Test points clearly in each cluster
        test_scores = np.array([[0.1, -0.1], [4.9, 5.1], [-0.5, 0.3], [5.5, 4.8]])
        probs = _plsda_mahalanobis_probabilities(train_scores, train_labels, test_scores, classes)
        # Rows sum to 1
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, rtol=1e-10)
        # Hard classifications match expected cluster
        assert classes[np.argmax(probs[0])] == "A"
        assert classes[np.argmax(probs[1])] == "B"
        assert classes[np.argmax(probs[2])] == "A"
        assert classes[np.argmax(probs[3])] == "B"
        # Confidence should be high (>= 0.99) for well-separated clusters
        assert probs[0, 0] >= 0.99
        assert probs[1, 1] >= 0.99

    def test_mahalanobis_handles_balanced_priors(self):
        """Equal-sized classes → priors are equal, so a sample exactly at the
        midpoint should yield 50/50 probabilities."""
        rng = np.random.RandomState(8)
        train_a = rng.randn(20, 2)
        train_b = rng.randn(20, 2) + np.array([4.0, 0.0])
        train_scores = np.vstack([train_a, train_b])
        train_labels = np.array(["A"] * 20 + ["B"] * 20, dtype=object)
        # Test sample at exact midpoint between class means, projected to (2, 0)
        test_scores = np.array([[2.0, 0.0]])
        probs = _plsda_mahalanobis_probabilities(
            train_scores, train_labels, test_scores, np.array(["A", "B"], dtype=object)
        )
        # Equal priors + equidistant midpoint → roughly 50/50 (allow some
        # slack because the empirical class means won't be exactly at 0 and 4).
        assert abs(probs[0, 0] - 0.5) < 0.15

    def test_mahalanobis_param_is_recorded_in_metadata(self, make_node):
        node = make_node("classification.plsda", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert "probability_method" in params_dict
        assert params_dict["probability_method"] == "softmax"  # default preserves BC

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mahalanobis_state_is_used_by_predict_node(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        train_node = make_node(
            "classification.plsda",
            {"n_components": 2, "cv_folds": 3, "probability_method": "mahalanobis", "scale": False},
        )
        train_result = await train_node.execute(X=ds, y=ds.target)
        model = train_result.outputs["model"]

        assert model["probability_method"] == "mahalanobis"
        assert "class_score_means" in model
        assert "score_covariance_inverse" in model
        assert "class_priors" in model

        predict_node = make_node("classification.predict", {}, node_id="predict")
        predict_result = await predict_node.execute(X_new=ds, model=model)
        probs = np.asarray(predict_result.outputs["y_prob"], dtype=np.float64)

        assert predict_result.diagnostics["probability_method"] == "mahalanobis"
        assert probs.shape == (ds.X.shape[0], len(model["classes"]))
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, rtol=1e-10)


# ---------------------------------------------------------------------------
# Issue 5 — SIMCA DD limits as default
# ---------------------------------------------------------------------------


class TestSimcaCriticalLimits:
    def test_default_critical_limits_method_is_ddmoments(self, make_node):
        node = make_node("classification.simca", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["critical_limits_method"] == "ddmoments"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_ddmoments_path_produces_finite_limits(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        node = make_node("classification.simca", {"n_components": 2})
        result = await node.execute(X=ds, y=ds.target)
        outputs = result.outputs if hasattr(result, "outputs") else result
        scores = outputs["default"]
        stats = scores.meta["acceptance_stats"]
        assert stats["critical_limits_method"] == "ddmoments"
        assert "dd_diagnostics" in stats
        for cls_key, t2_limit in stats["T2_limits"].items():
            assert np.isfinite(t2_limit) and t2_limit > 0, f"Bad T² limit for class {cls_key}"
        for cls_key, q_limit in stats["Q_limits"].items():
            assert np.isfinite(q_limit) and q_limit > 0, f"Bad Q limit for class {cls_key}"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_predict_node_uses_simca_scaled_training_space(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        train_node = make_node("classification.simca", {"n_components": 2})
        train_result = await train_node.execute(X=ds, y=ds.target)
        model = train_result.outputs["model"]

        for class_model in model["class_models"].values():
            assert "x_mean" in class_model
            assert "x_scale" in class_model
            assert "pca_mean" in class_model

        predict_node = make_node("classification.predict", {}, node_id="predict")
        predict_result = await predict_node.execute(X_new=ds, model=model)

        assert predict_result.outputs["y_pred"] == [str(label) for label in train_result.outputs["predictions"]]

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_classical_limits_path_still_works(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        node = make_node(
            "classification.simca",
            {"n_components": 2, "critical_limits_method": "classical"},
        )
        result = await node.execute(X=ds, y=ds.target)
        outputs = result.outputs if hasattr(result, "outputs") else result
        scores = outputs["default"]
        stats = scores.meta["acceptance_stats"]
        assert stats["critical_limits_method"] == "classical"
        # Classical path doesn't populate DD diagnostics; should be empty dict.
        assert stats["dd_diagnostics"] == {}
