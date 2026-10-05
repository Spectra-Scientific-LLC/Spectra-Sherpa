"""
End-to-end execution tests for the key workflow templates.

Verifies that the recently-audited nodes execute correctly with the
``diesel_nir``-shaped generated data (NIR, 784 samples, 401 channels).

Covered fixes (from the chemometrician audit):
  #1  Outlier Detection requires eigenvalues (no score-variance fallback)
  #2  NMF rejects negative data with an actionable error
  #3  Baseline lambda auto-selects from technique tag (NIR → 1×10⁶)
  #4  CrossValidation reports SEP, RER, bias
  #5  CrossValidation records an explicitly supplied LOOCV split plan

The ``diesel_nir`` catalog entry is also confirmed to be first in DATASET_CATALOG
(so it appears at the top of the Inspector dropdown without any frontend change).
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.decomposition import PCA

from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag import out_of_fold_evidence
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.sdk.validate import make_split_plan
from tests.eigenvector_test_fixtures import generated_eigenvector_result
from tests.pca_test_fixtures import closed_pca_diagnostic_state


def _bound_evidence(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    n_splits: int,
    task_type: str = "regression",
) -> dict[str, object]:
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
        task_type=task_type,
        observations=observed,
        predictions=predicted,
        split_plan=split_plan,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def diesel_nir_dataset() -> SherpaDataset:
    """Create a diesel_nir-shaped SherpaDataset with NIR domain."""
    result = generated_eigenvector_result("diesel_nir")
    wl = result["wavelengths"]
    spectra = result["spectra"]

    feature_axis = SpectralAxis(
        values=wl if wl is not None else np.arange(spectra.shape[1], dtype=float),
        units="nm",
        title="Wavelength",
    )
    ds = SherpaDataset(
        X=spectra,
        feature_axis=feature_axis,
        title="Diesel NIR",
    )
    ds.domain = DomainContext(technique="NIR")
    return ds


@pytest.fixture(scope="module")
def diesel_pca_model(diesel_nir_dataset: SherpaDataset) -> dict:
    """Build the typed PCA diagnostic envelope without requiring the fit extra."""
    return closed_pca_diagnostic_state(diesel_nir_dataset, n_components=5)


# ---------------------------------------------------------------------------
# 1. Dataset ordering — diesel_nir must be first in the catalog
# ---------------------------------------------------------------------------


def test_diesel_nir_is_first_in_dataset_catalog():
    """diesel_nir must be the first entry in DATASET_CATALOG (top of Inspector dropdown)."""
    first_key = next(iter(DATASET_CATALOG))
    assert first_key == "diesel_nir", (
        f"Expected 'diesel_nir' to be first in DATASET_CATALOG, got '{first_key}'. "
        "Move it to the top of the dict to make it the default in the Inspector dropdown."
    )


def test_diesel_nir_has_nir_technique_tag():
    """diesel_nir must carry the NIR domain tag used by scientist-facing context."""
    catalog_entry = DATASET_CATALOG["diesel_nir"]
    assert catalog_entry.get("technique", "").upper() == "NIR"


# ---------------------------------------------------------------------------
# 2. Canonical baseline executes the exact displayed lambda
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_penalized_ls_uses_exact_canvas_lambda(diesel_nir_dataset: SherpaDataset):
    """NIR metadata must not silently replace the lambda shown on the canvas."""
    node = node_registry.create_node(
        node_type="baseline.penalized_ls",
        node_id="baseline_test",
        parameters={"method": "als", "lam": 1e5},
    )

    # Capture the exact implementation argument without substituting by technique.
    import spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node as prep_mod

    captured_lam: list[float] = []
    original_fn = prep_mod._penalized_baseline_dispatch

    def _spy_baseline(data, method, lam, **kw):
        captured_lam.append(float(lam))
        return original_fn(data, method=method, lam=lam, **kw)

    prep_mod._penalized_baseline_dispatch = _spy_baseline
    try:
        result = await node.execute(input_data=diesel_nir_dataset)
    finally:
        prep_mod._penalized_baseline_dispatch = original_fn

    assert captured_lam, "canonical baseline implementation was never called"
    effective_lam = captured_lam[0]
    assert effective_lam == pytest.approx(1e5)

    # Result should be a valid SherpaDataset with same shape
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset as SD
    from spectra_sherpa.app.services.dag.node_base import NodeResult

    if isinstance(result, NodeResult):
        provenance = result.outputs["default"].provenance.to_list()[-1]
        assert provenance["parameters"]["lam"] == pytest.approx(1e5)
        assert "_lam_auto_technique" not in provenance["parameters"]
        result = result.outputs.get("default", result.outputs)
    assert isinstance(result, SD) or isinstance(result, dict)


# ---------------------------------------------------------------------------
# 3. Fix #2 — OutlierDetectionNode requires eigenvalues (no score-variance fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outlier_detection_raises_without_eigenvalues(diesel_nir_dataset: SherpaDataset):
    """OutlierDetectionNode must raise ValueError when eigenvalues are absent (fix #2)."""
    X = diesel_nir_dataset.data
    X_c = X - X.mean(axis=0)
    pca = PCA(n_components=3)
    scores = pca.fit_transform(X_c)

    # Provide a pca_model dict WITHOUT explained_variance
    bad_model = {
        "model": pca,
        "scores": scores,
        "loadings": pca.components_,
        "n_components": 3,
        "n_observations": X.shape[0],
        # 'eigenvalues' intentionally omitted
        "_internal": {"input_data": X},
        "metadata": {"type": "PCAModel"},
    }

    node = node_registry.create_node(
        node_type="diagnostics.outliers",
        node_id="outlier_test",
        parameters={"confidence_level": 0.95},
    )

    with pytest.raises(ValueError, match="eigenvalues"):
        await node.execute(pca_model=bad_model)


@pytest.mark.asyncio
async def test_outlier_detection_succeeds_with_eigenvalues(diesel_pca_model: dict):
    """OutlierDetectionNode must complete successfully when eigenvalues are supplied."""
    node = node_registry.create_node(
        node_type="diagnostics.outliers",
        node_id="outlier_ok_test",
        parameters={"confidence_level": 0.95},
    )

    result = await node.execute(pca_model=diesel_pca_model)

    from spectra_sherpa.app.services.dag.node_base import NodeResult

    assert isinstance(result, NodeResult)
    assert "T2" in result.outputs
    assert "Q" in result.outputs
    assert "flags" in result.outputs
    t2_arr = np.asarray(result.outputs["T2"])
    assert t2_arr.shape == (diesel_pca_model["n_observations"],), f"T² array has wrong shape: {t2_arr.shape}"
    # T² values must be non-negative
    assert np.all(t2_arr >= 0), "T² values contain negatives — eigenvalue computation is broken"


# ---------------------------------------------------------------------------
# 4. Fix #5 & #6 — CrossValidationNode returns SEP, RER, bias
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_validation_reports_sep_rer_bias():
    """CrossValidationNode must include SEP, RER, and bias for regression (fix #5)."""
    rng = np.random.default_rng(7)
    n = 80
    y_true = rng.uniform(20, 60, n)
    y_pred = y_true + rng.normal(0, 2.5, n)  # realistic calibration noise

    node = node_registry.create_node(
        node_type="diagnostics.cross_validation",
        node_id="cv_test",
        parameters={},
    )

    result = await node.execute(evidence=_bound_evidence(y_true, y_pred, n_splits=5))

    metrics = result.outputs.get("cv_metrics", {})
    overall = metrics["overall_metrics"]
    assert "sep" in overall, f"SEP missing from CV metrics (fix #5). Keys: {list(overall)}"
    assert "rer" in overall, f"RER missing from CV metrics (fix #5). Keys: {list(overall)}"
    assert "bias" in overall, f"bias missing from CV metrics (fix #5). Keys: {list(overall)}"

    # Sanity-check numeric reasonableness
    assert overall["sep"] >= 0
    assert overall["rer"] > 0
    assert isinstance(overall["bias"], float)
    # RER ≥ 10 is the ASTM E1655 minimum for a useful calibration
    assert overall["rer"] >= 5, f"RER={overall['rer']:.1f} seems very low — is the formula correct?"


@pytest.mark.asyncio
async def test_cross_validation_records_supplied_loocv_assignments():
    """One unique fold per sample is accepted only when it is supplied explicitly."""
    rng = np.random.default_rng(99)
    n = 30  # small dataset → LOOCV expected
    y_true = rng.uniform(0, 1, n)
    y_pred = y_true + rng.normal(0, 0.05, n)

    node = node_registry.create_node(
        node_type="diagnostics.cross_validation",
        node_id="cv_loocv_test",
        parameters={},
    )

    result = await node.execute(evidence=_bound_evidence(y_true, y_pred, n_splits=n))

    metrics = result.outputs.get("cv_metrics", {})
    assert metrics["n_folds"] == n
    assert result.outputs["fold_assignments"] == list(range(n))
    assert "rmsecv" in metrics["overall_metrics"]
    assert "r2_cv" in metrics["overall_metrics"]


@pytest.mark.asyncio
async def test_cross_validation_rejects_classification_without_an_authorized_producer():
    """The UI must not imply classification CV before an authoritative producer exists."""
    observed = np.array(["low", "low", "high", "high"])
    predicted = np.array(["low", "high", "high", "high"])
    with pytest.raises(ValueError, match="supports regression only"):
        _bound_evidence(observed, predicted, n_splits=2, task_type="classification")


# ---------------------------------------------------------------------------
# 5. Canonical held-out regression evaluation regressions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_evaluator_rejects_non_finite_regression_predictions():
    node = node_registry.create_node(
        node_type="diagnostics.regression_evaluator",
        node_id="holdout_nan_test",
        parameters={},
    )

    with pytest.raises(ValueError, match="finite prediction or target matrix"):
        node.score_held_out_predictions(
            np.array([1.1, np.nan, 2.9, np.inf]),
            np.array([1.0, 2.0, 3.0, 4.0]),
        )


def test_canonical_evaluator_generate_python_uses_the_regression_authority():
    node = node_registry.create_node(
        node_type="diagnostics.regression_evaluator",
        node_id="holdout_export_test",
        parameters={},
    )

    code = "\n".join(node.generate_python({"default": "y_pred", "y_true": "y_true"}))

    assert "evaluate_regression_v2" in code
    assert "y_pred, y_true" in code
    assert "classification_report" not in code


# ---------------------------------------------------------------------------
# 6. Fix #3 — NMF rejects negative data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nmf_rejects_negative_data():
    """NMFNode must raise ValueError (not silently shift) for negative data (fix #3)."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset as SD

    rng = np.random.default_rng(42)
    X_neg = rng.normal(-1.0, 0.5, (20, 50))  # deliberately negative
    ds_neg = SD(X=X_neg)

    node = node_registry.create_node(
        node_type="model.nmf",
        node_id="nmf_test",
        parameters={"n_components": 2},
    )

    with pytest.raises(ValueError, match="non-negative"):
        await node.execute(input_data=ds_neg)


# ---------------------------------------------------------------------------
# 6. Fix #10 — sklearn datasets flagged as non-spectroscopic
# ---------------------------------------------------------------------------


def test_sklearn_datasets_have_non_spectroscopic_warning():
    """sklearn catalog entries must carry is_spectra=False and a warning (fix #10)."""
    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG

    for name, entry in SKLEARN_CATALOG.items():
        assert entry.get("is_spectra") is False, f"sklearn dataset '{name}' missing is_spectra=False"
        assert entry.get("warning"), f"sklearn dataset '{name}' missing non-spectroscopic warning"


# ---------------------------------------------------------------------------
# 7. Fix #9 — NodeParameter accepts hint field
# ---------------------------------------------------------------------------


def test_node_parameter_hint_field():
    """NodeParameter must accept and store the hint field without error (fix #9)."""
    from spectra_sherpa.app.services.dag.node_base import NodeParameter

    param = NodeParameter(
        name="test_param",
        label="Test",
        param_type="number",
        default=5.0,
        hint="This is a static advisory hint for the Inspector.",
    )
    assert param.hint == "This is a static advisory hint for the Inspector."


def test_baseline_node_lam_parameter_has_hint():
    """BaselinePenalizedLSNode lam parameter must have an Inspector hint."""
    node = node_registry.create_node(
        node_type="baseline.penalized_ls",
        node_id="hint_test",
        parameters={},
    )
    lam_param = next(
        (p for p in node.metadata.parameters if p.name == "lam"),
        None,
    )
    assert lam_param is not None, "lam parameter not found on BaselinePenalizedLSNode"
    assert lam_param.hint, "lam parameter hint is empty — Inspector guidance missing"
