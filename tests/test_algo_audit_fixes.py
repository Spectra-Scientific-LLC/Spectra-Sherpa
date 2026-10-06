"""Regression tests for v0.4.3 algorithm-audit fixes (issues #1–#5).

Covers:
  1. MCR-ALS tol default tightened from 0.1 → 1e-5 + loose-tol warning
  2. PLS regression node now emits per-sample Hotelling T² + Q with
     Pomerantsev (J. Chemom. 2008) DD critical limits
  3. PLS scale default flipped True → False (spectroscopy convention)
  4. SIMCA defaults to Pomerantsev DD limits, with the classical F/χ² path preserved

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
from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import _simca_export_outputs
from tests._optional_scp import HAS_SCP

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
        sample_axis=SampleAxis(values=np.arange(n_samples), title="Sample"),
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
        assert params_dict["normSpec"] == "euclid"

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

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_default_norm_spec_is_euclid_at_runtime(self, make_node):
        ds = _make_spectral_dataset(n_samples=15, n_features=40)
        node = make_node("model.mcr_als", {"n_components": 2, "max_iter": 20})
        result = await node.execute(input_data=ds)
        assert result.diagnostics["normSpec"] == "euclid"
        St = np.asarray(result.outputs["St"].data, dtype=np.float64)
        assert np.linalg.norm(St, axis=1) == pytest.approx(np.ones(St.shape[0]), rel=1e-6, abs=1e-6)
        assert result.outputs["C"].meta["normSpec"] == "euclid"
        assert result.outputs["C"].meta["mcr_spectra_y_units"] == "euclidean-normalized response"
        assert result.outputs["St"].meta["normSpec"] == "euclid"


# ---------------------------------------------------------------------------
# Issue 3 — PLS scale default flipped
# ---------------------------------------------------------------------------


class TestPlsScaleDefault:
    def test_default_scale_is_false(self, make_node):
        node = make_node("model.fitted_pls", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["scale"] is False

    def test_plsda_default_scale_is_false(self, make_node):
        node = make_node("classification.plsda", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["scale"] is False

    def test_shipped_pls_workflows_pin_explicit_scaling_policy(self):
        templates_dir = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/templates"
        pls_node_types = {"model.fitted_pls", "classification.plsda"}
        missing: list[str] = []

        for path in templates_dir.glob("*.yaml"):
            doc = yaml.safe_load(path.read_text())
            nodes = (doc.get("template_data") or {}).get("nodes") or []
            for node in nodes:
                if node.get("node_type") in pls_node_types:
                    params = node.get("parameters") or {}
                    if not isinstance(params.get("scale"), bool):
                        missing.append(f"{path.name}:{node.get('node_id')}")

        assert missing == []


class TestChemometricTemplatePresentationWiring:
    def _template(self, slug: str) -> dict:
        path = Path(__file__).resolve().parents[1] / f"src/spectra_sherpa/data/templates/{slug}.yaml"
        return yaml.safe_load(path.read_text())

    def _nodes(self, slug: str) -> dict[str, dict]:
        doc = self._template(slug)
        nodes = (doc.get("template_data") or {}).get("nodes") or []
        return {str(node["node_id"]): node for node in nodes}

    def _edges(self, slug: str) -> list[dict]:
        doc = self._template(slug)
        return (doc.get("template_data") or {}).get("edges") or []

    def test_simca_templates_expose_their_intended_scientist_paths(self):
        qc_nodes = self._nodes("simca_qc")
        assert qc_nodes["viz_1"]["parameters"]["plot_key"] == "simca_acceptance"
        assert any(
            edge.get("from_node_id") == "model_1"
            and edge.get("to_node_id") == "viz_1"
            and edge.get("from_output") == "plots"
            for edge in self._edges("simca_qc")
        )

        cls_nodes = self._nodes("simca_classification")
        assert {node_id: node["node_type"] for node_id, node in cls_nodes.items()} == {
            "data_1": "data.file_load",
            "partition_1": "data.train_test_split",
            "model_1": "classification.simca",
            "predict_1": "classification.apply_simca",
            "eval_1": "diagnostics.classification_evaluator",
        }

    def test_calibration_transfer_template_compares_fitted_methods_on_one_paired_split(self):
        nodes = self._nodes("calibration_transfer")
        expected = {
            "primary_1": "corn_m5",
            "secondary_1": "corn_mp5",
        }
        for node_id, dataset_name in expected.items():
            assert nodes[node_id]["node_type"] == "data.file_load"
            assert nodes[node_id]["parameters"] == {}
            assert nodes[node_id]["example_binding"] == {
                "source": "eigenvector",
                "dataset_name": dataset_name,
            }
        assert {nodes[node_id]["node_type"] for node_id in ("pds_fit_1", "ds_fit_1", "sws_fit_1")} == {
            "transfer.pds",
            "transfer.ds",
            "transfer.sws",
        }
        assert {nodes[node_id]["node_type"] for node_id in ("pds_apply_1", "ds_apply_1", "sws_apply_1")} == {
            "transfer.apply_fitted"
        }
        edges = self._edges("calibration_transfer")
        for prefix in ("pds", "ds", "sws"):
            assert any(
                edge.get("from_node_id") == f"{prefix}_fit_1"
                and edge.get("to_node_id") == f"{prefix}_apply_1"
                and edge.get("from_output") == "fitted_state"
                and edge.get("to_input") == "fitted_state"
                for edge in edges
            )
            assert any(
                edge.get("from_node_id") == "secondary_split_1"
                and edge.get("to_node_id") == f"{prefix}_apply_1"
                and edge.get("from_output") == "X_test"
                for edge in edges
            )
            assert any(
                edge.get("from_node_id") == f"{prefix}_fit_1"
                and edge.get("to_node_id") == f"{prefix}_table_1"
                and edge.get("from_output") == "transfer_error"
                for edge in edges
            )

    def test_oes_stats_are_wired_to_pca_scores(self):
        assert any(
            edge.get("from_node_id") == "model_1"
            and edge.get("to_node_id") == "stats_1"
            and edge.get("from_output") == "scores"
            for edge in self._edges("oes_process_monitoring")
        )

    def test_simplisma_purity_plot_uses_purity_values(self):
        nodes = self._nodes("simplisma")
        assert nodes["viz_1"]["parameters"]["plot_type"] == "scatter"
        assert any(
            edge.get("from_node_id") == "model_1"
            and edge.get("to_node_id") == "viz_1"
            and edge.get("from_output") == "purity_values"
            for edge in self._edges("simplisma")
        )

    @pytest.mark.parametrize("slug", ["mcr_als", "mcr_als_kinetics"])
    def test_mcr_templates_surface_fit_diagnostics(self, slug):
        nodes = self._nodes(slug)
        assert nodes["stats_1"]["node_type"] == "stats.summary"
        assert any(
            edge.get("from_node_id") == "model_1"
            and edge.get("to_node_id") == "stats_1"
            and edge.get("from_output") == "C"
            for edge in self._edges(slug)
        )


# ---------------------------------------------------------------------------
# Canonical PLS emits reusable fitted state, predictions, and VIP
# ---------------------------------------------------------------------------


class TestCanonicalPlsEmission:
    @pytest.mark.asyncio
    async def test_pls_emits_predictions_and_closed_fitted_state(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=50, n_targets=1)
        node = make_node("model.fitted_pls", {"n_components": 3, "scale": False})
        result = await node.execute(input_data=ds)

        predictions = np.asarray(result.outputs["default"], dtype=np.float64)
        assert predictions.shape == (ds.X.shape[0], 1)
        assert result.outputs["fitted_state"]["serializer"] == "spectra.sherpa-simpls-regression-json/9"
        assert result.diagnostics["fitted_state_serializer"] == "spectra.sherpa-simpls-regression-json/9"

    @pytest.mark.asyncio
    async def test_pls_emits_vip_scores_bound_to_the_fitted_state(self, make_node):
        ds = _make_spectral_dataset(n_samples=32, n_features=45, n_targets=1)
        node = make_node("model.fitted_pls", {"n_components": 2, "scale": False})
        result = await node.execute(input_data=ds)

        vip = np.asarray(result.outputs["vip_scores"], dtype=np.float64)
        state_vip = np.asarray(result.outputs["fitted_state"]["state"]["vip_scores"], dtype=np.float64)
        assert vip.shape == (ds.X.shape[1],)
        np.testing.assert_allclose(vip, state_vip)
        assert result.diagnostics["vip_method"] == "mdatools_combined"


# ---------------------------------------------------------------------------
# Issue 4 — PLS-DA Mahalanobis rule
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue 4 — SIMCA DD limits as default
# ---------------------------------------------------------------------------


class TestSimcaCriticalLimits:
    def test_default_critical_limits_method_is_ddmoments(self, make_node):
        node = make_node("classification.simca", {})
        params_dict = {p.name: p.default for p in node.metadata.parameters}
        assert params_dict["critical_limits_method"] == "ddmoments"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_unlabeled_samples_use_identical_row_indices_live_and_exported(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        assert ds.sample_axis.labels is None
        parameters = {
            "n_components": 2,
            "confidence_level": 0.95,
            "critical_limits_method": "ddmoments",
        }

        live_result = await make_node("classification.simca", parameters).execute(X=ds, y=ds.target)
        exported = _simca_export_outputs(ds, ds.target, parameters=parameters)
        live_plot = live_result.outputs["plots"]["simca_acceptance"]
        exported_plot = exported["plots"]["simca_acceptance"]

        live_hover = [text for trace in live_plot["data"] for text in trace.get("text", [])]
        exported_hover = [text for trace in exported_plot["data"] for text in trace.get("text", [])]
        assert live_hover == exported_hover
        assert sorted(text.split("<br>", 1)[0] for text in live_hover) == sorted(
            str(index) for index in range(ds.X.shape[0])
        )

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
    async def test_simca_emits_acceptance_plot_and_t2_q_matrices(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        node = make_node("classification.simca", {"n_components": 2})
        result = await node.execute(X=ds, y=ds.target)
        outputs = result.outputs if hasattr(result, "outputs") else result

        assert "simca_acceptance" in outputs["plots"]
        plot = outputs["plots"]["simca_acceptance"]
        assert plot["metadata"]["type"] == "simca_acceptance"
        assert plot["layout"]["xaxis"]["title"].startswith("Hotelling T")
        assert plot["layout"]["yaxis"]["title"].startswith("Q residual")

        t2 = np.asarray(outputs["t2_matrix"], dtype=np.float64)
        q = np.asarray(outputs["q_matrix"], dtype=np.float64)
        assert t2.shape == q.shape == (ds.X.shape[0], len(np.unique(ds.target)))
        assert np.all(t2 >= 0)
        assert np.all(q >= 0)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_predict_node_uses_simca_scaled_training_space(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=40, n_targets=1, target_type="categorical")
        train_node = make_node("classification.simca", {"n_components": 2})
        train_result = await train_node.execute(X=ds, y=ds.target)
        fitted_state = train_result.outputs["fitted_state"]
        assert fitted_state["serializer"] == "spectrasherpa.model-artifact.simca/1"
        assert set(fitted_state["metadata"]["T2_limits"]) == set(fitted_state["metadata"]["classes"])
        assert set(fitted_state["metadata"]["Q_limits"]) == set(fitted_state["metadata"]["classes"])

        predict_node = make_node("classification.apply_simca", {}, node_id="predict")
        predict_result = await predict_node.execute(X_new=ds, fitted_state=fitted_state)

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
