"""
PLS-DA training and prediction nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_extractors import PLSDAExtract, PLSExtract, _safe_getattr
from spectra_sherpa.app.lib.scp_compat import scp
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)

from ...io_contracts import (
    bind_X,
    bind_y,
    to_numpy_2d,
)
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node
from ..modeling import create_spectral_dataset
from ..visualization import generate_confusion_matrix_heatmap
from .core_utils import (
    classification_metrics_contract as _classification_metrics_contract,
)
from .core_utils import (
    classification_scalar_metrics as _classification_scalar_metrics,
)
from .core_utils import (
    coerce_numeric_array as _coerce_numeric_array,
)
from .core_utils import (
    make_labeled_coord as _make_labeled_coord,
)
from .core_utils import (
    prepare_class_labels as _prepare_class_labels,
)


def _fit_plsda_mahalanobis_state(
    train_scores: np.ndarray,
    train_labels: np.ndarray,
    classes: np.ndarray,
) -> dict[str, np.ndarray]:
    """Fit mdatools-style Gaussian discriminant state in PLS score space."""
    train_scores = np.asarray(train_scores, dtype=np.float64)
    if train_scores.ndim == 1:
        train_scores = train_scores.reshape(-1, 1)
    train_labels = np.asarray(train_labels)
    classes = np.asarray(classes)

    n_train, n_components = train_scores.shape
    n_classes = len(classes)

    class_means = np.zeros((n_classes, n_components), dtype=np.float64)
    class_counts = np.zeros(n_classes, dtype=np.int64)
    deviations = np.zeros_like(train_scores)

    for k, cls in enumerate(classes):
        mask = train_labels == cls
        cnt = int(mask.sum())
        class_counts[k] = cnt
        if cnt:
            class_means[k] = train_scores[mask].mean(axis=0)
            deviations[mask] = train_scores[mask] - class_means[k]

    if n_train - n_classes > 0:
        pooled_cov = (deviations.T @ deviations) / float(n_train - n_classes)
    else:
        pooled_cov = (deviations.T @ deviations) / max(1, n_train - 1)

    try:
        cov_inv = np.linalg.inv(pooled_cov + 1e-10 * np.eye(n_components))
    except np.linalg.LinAlgError:
        diag = np.diag(pooled_cov)
        cov_inv = np.diag(1.0 / np.where(diag > 1e-12, diag, 1.0))

    class_priors = np.maximum(class_counts / max(1, n_train), 1e-12)
    class_priors /= class_priors.sum()
    return {
        "class_score_means": class_means,
        "score_covariance_inverse": cov_inv,
        "class_priors": class_priors,
    }


def _plsda_mahalanobis_probabilities_from_state(
    test_scores: np.ndarray,
    class_score_means: np.ndarray,
    score_covariance_inverse: np.ndarray,
    class_priors: np.ndarray,
) -> np.ndarray:
    """Apply a fitted Gaussian discriminant state to PLS scores."""
    test_scores = np.asarray(test_scores, dtype=np.float64)
    if test_scores.ndim == 1:
        test_scores = test_scores.reshape(-1, 1)
    class_score_means = np.asarray(class_score_means, dtype=np.float64)
    score_covariance_inverse = np.asarray(score_covariance_inverse, dtype=np.float64)
    class_priors = np.asarray(class_priors, dtype=np.float64)

    n_test = test_scores.shape[0]
    n_classes = class_score_means.shape[0]
    log_priors = np.log(np.maximum(class_priors, 1e-12))

    log_post = np.empty((n_test, n_classes), dtype=np.float64)
    for k in range(n_classes):
        diff = test_scores - class_score_means[k]
        d2 = np.einsum("ij,jk,ik->i", diff, score_covariance_inverse, diff)
        log_post[:, k] = -0.5 * d2 + log_priors[k]

    log_post -= log_post.max(axis=1, keepdims=True)
    probs = np.exp(log_post)
    probs /= probs.sum(axis=1, keepdims=True)
    return probs


def _plsda_mahalanobis_probabilities(
    train_scores: np.ndarray,
    train_labels: np.ndarray,
    test_scores: np.ndarray,
    classes: np.ndarray,
) -> np.ndarray:
    """mdatools-style PLS-DA posterior probabilities.

    Gaussian discriminant analysis in PLS score space:
      μ_k = mean(T_train[y==k])
      Σ   = pooled within-class covariance of (T_train − μ_{y_train})
      d²_{i,k} = (t_i − μ_k)' Σ⁻¹ (t_i − μ_k)
      π_k = n_k / n
      P(k | t_i) ∝ exp(−d²_{i,k} / 2) · π_k    (normalised across k)

    Falls back to a diagonal covariance if the pooled covariance is
    rank-deficient (very small CV fold sizes). Identical scores for two
    classes (degenerate calibration) return uniform probabilities.

    Reference: Kucheryavskiy, *Chemometrics with R*, ch. 9 (mdatools
    `plsda()` classification rule).
    """
    state = _fit_plsda_mahalanobis_state(train_scores, train_labels, classes)
    return _plsda_mahalanobis_probabilities_from_state(
        test_scores,
        state["class_score_means"],
        state["score_covariance_inverse"],
        state["class_priors"],
    )


logger = logging.getLogger(__name__)


@register_node
class PLSDANode(Node):
    """
    Partial Least Squares Discriminant Analysis (PLS-DA) node.

    Performs supervised classification using PLS regression on categorical data.
    PLS-DA extends PLS by encoding class labels as dummy variables (one-hot encoding)
    and using PLS regression to find discriminant directions.

    Common in chemometrics for spectroscopic classification tasks.
    """

    metadata = NodeMetadata(
        node_type="classification.plsda",
        category="classification",
        label="Train PLS-DA Classifier",
        description=(
            "Train a Partial Least Squares Discriminant Analysis classifier. "
            "⚠ Class probabilities are derived via softmax on raw PLS regression outputs "
            "and are NOT calibrated — they indicate relative confidence only. "
            "For reliable probability estimates apply Platt scaling or isotonic regression "
            "to the CV predictions after training."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=2,
                min_value=1,
                step=1,
                description="Number of PLS components (latent variables)",
                required=True,
                category="basic",
                hint=(
                    "Must be ≤ min(n_samples − 1, n_features, n_classes). "
                    "Typical chemometrics range: 2–10 LVs. "
                    "Use cross-validation to select the optimal number — the model node reports CV accuracy per LV."
                ),
            ),
            NodeParameter(
                name="scale",
                label="Mean Center + Unit Variance",
                param_type="boolean",
                default=False,
                description=(
                    "Apply mean centering and unit-variance scaling inside PLS-DA. "
                    "Default is off so workflow templates can express preprocessing explicitly "
                    "and avoid double scaling."
                ),
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="cv_folds",
                label="Cross-Validation Folds",
                param_type="number",
                default=5,
                min_value=2,
                step=1,
                description="Number of folds for cross-validation (must be ≤ smallest class count)",
                required=False,
                category="advanced",
                hint=(
                    "For datasets with n < 50 samples, consider using LOOCV (n folds) via the "
                    "Cross-Validation node. "
                    "Minimum: cv_folds ≤ smallest class count — an error is raised if this is violated."
                ),
            ),
            NodeParameter(
                name="calibrate_probabilities",
                label="Calibrate Probabilities (Platt Scaling)",
                param_type="boolean",
                default=False,
                description=(
                    "Apply Platt scaling (sigmoid calibration) to cross-validated predictions "
                    "to produce statistically calibrated posterior probabilities. "
                    "Reference: Platt (1999). Recommended when probability estimates are used "
                    "for downstream decision-making. Applied only when probability_method='softmax'."
                ),
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="probability_method",
                label="Probability Rule",
                param_type="select",
                default="softmax",
                options=["softmax", "mahalanobis"],
                description=(
                    "How class probabilities and the classification decision are derived. "
                    "'softmax' (default, backwards-compatible): softmax of raw PLS Y-hat — "
                    "fast, common in engineering practice, but probabilities are uncalibrated. "
                    "'mahalanobis' (mdatools-style): Gaussian discriminant in PLS score space — "
                    "estimate per-class score means and pooled within-class covariance, "
                    "compute Mahalanobis distance to each class mean, convert to posterior "
                    "via Bayes' rule with class priors π_k = n_k/n. Theoretically grounded "
                    "and recommended for regulated reporting (Kucheryavskiy, Chemometrics with R, ch. 9)."
                ),
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Data Matrix (X)",
                description="Spectral data, PCA scores, or multivariate feature table",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=False,
                label="Class Labels (y)",
                description="Class labels for each sample (auto-extracted from X if not provided)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
                description="PLS-DA latent X scores (samples × latent variables)",
            ),
            PortMetadata(
                name="X_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
                description="Alias of default: PLS-DA latent X scores",
            ),
            PortMetadata(
                name="X_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="X Loadings",
                description="PLS-DA X loadings (latent variables × input features)",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Loadings",
                description="Alias of X_loadings for plot/table nodes",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted PLS-DA Classifier",
                description="Fitted PLS-DA classifier produced by this training node",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="CV Predictions",
                description="Cross-validated class predictions",
            ),
            PortMetadata(
                name="probabilities",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities",
                description="Cross-validated class probabilities",
            ),
            PortMetadata(
                name="class_probabilities",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities",
                description="Alias of probabilities for direct model comparison",
            ),
            PortMetadata(
                name="metrics",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Classification Metrics",
                description="Canonical train/CV/test classification metrics for run history, comparison, and guidance",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PLS-DA classification."""
        if not use_scp:
            return [
                f"{indent}# --- PLS-DA ({self.node_id}) ---",
                f"{indent}# PLS-DA requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('PLS-DA requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 2)
        scale = params.get("scale", False)
        cv_folds = params.get("cv_folds", 5)
        probability_method = params.get("probability_method", "softmax")
        if probability_method not in ("softmax", "mahalanobis"):
            probability_method = "softmax"

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- PLS-DA ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Extract y (class labels)
        if y_expr:
            lines.append(f"{indent}_y_raw = {y_expr}")
            lines.append(f"{indent}_y_labels = np.asarray(_y_raw.data if hasattr(_y_raw, 'data') else _y_raw).ravel()")
        else:
            lines.append(f"{indent}_y_labels = np.asarray(")
            lines.append(f"{indent}    _X_input.target if hasattr(_X_input, 'target') and _X_input.target is not None")
            lines.append(f"{indent}    else _X_input.meta.get('target'),")
            lines.append(f"{indent}).ravel()")

        # One-hot encode → PLS → classify
        scale_str = "True" if scale else "False"
        lines.append(f"{indent}_classes = sorted(set(_y_labels.tolist()))")
        lines.append(f"{indent}_class_map = {{c: i for i, c in enumerate(_classes)}}")
        lines.append(f"{indent}_y_idx = np.array([_class_map[c] for c in _y_labels.tolist()])")
        lines.append(f"{indent}_Y_dummy = np.eye(len(_classes))[_y_idx]")
        lines.append(f"{indent}from sklearn.metrics import confusion_matrix")
        lines.append(f"{indent}from sklearn.model_selection import StratifiedKFold")
        lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.core_utils import (")
        lines.append(f"{indent}    classification_metrics_contract,")
        lines.append(f"{indent}    classification_scalar_metrics,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}_Y_ndd = scp.NDDataset(_Y_dummy)")
        lines.append(f"{indent}_pls = scp.PLSRegression(n_components={n_components}, scale={scale_str})")
        lines.append(f"{indent}_pls.fit(_X_ndd, _Y_ndd)")
        lines.append(f"{indent}_y_pred_raw = np.asarray(_pls.predict(_X_ndd).data, dtype=np.float64)")
        lines.append(f"{indent}if _y_pred_raw.ndim == 1:")
        lines.append(f"{indent}    _y_pred_raw = _y_pred_raw.reshape(-1, len(_classes))")
        lines.append(f"{indent}_probability_method = {probability_method!r}")
        lines.append(f"{indent}_mahalanobis_state = None")
        lines.append(f"{indent}if _probability_method == 'mahalanobis':")
        lines.append(f"{indent}    _scores = np.asarray(_pls.transform(_X_ndd).data, dtype=np.float64)")
        lines.append(f"{indent}    if _scores.ndim == 1:")
        lines.append(f"{indent}        _scores = _scores.reshape(-1, 1)")
        lines.append(f"{indent}    _means = np.zeros((len(_classes), _scores.shape[1]), dtype=np.float64)")
        lines.append(f"{indent}    _counts = np.zeros(len(_classes), dtype=np.int64)")
        lines.append(f"{indent}    _dev = np.zeros_like(_scores)")
        lines.append(f"{indent}    for _k, _cls in enumerate(_classes):")
        lines.append(f"{indent}        _mask = _y_labels == _cls")
        lines.append(f"{indent}        _counts[_k] = int(_mask.sum())")
        lines.append(f"{indent}        if _counts[_k]:")
        lines.append(f"{indent}            _means[_k] = _scores[_mask].mean(axis=0)")
        lines.append(f"{indent}            _dev[_mask] = _scores[_mask] - _means[_k]")
        lines.append(f"{indent}    _denom = max(1, _scores.shape[0] - len(_classes))")
        lines.append(f"{indent}    _cov = (_dev.T @ _dev) / float(_denom)")
        lines.append(f"{indent}    try:")
        lines.append(f"{indent}        _cov_inv = np.linalg.inv(_cov + 1e-10 * np.eye(_scores.shape[1]))")
        lines.append(f"{indent}    except np.linalg.LinAlgError:")
        lines.append(f"{indent}        _diag = np.diag(_cov)")
        lines.append(f"{indent}        _cov_inv = np.diag(1.0 / np.where(_diag > 1e-12, _diag, 1.0))")
        lines.append(f"{indent}    _priors = np.maximum(_counts / max(1, _scores.shape[0]), 1e-12)")
        lines.append(f"{indent}    _priors = _priors / _priors.sum()")
        lines.append(f"{indent}    _log_post = np.empty((_scores.shape[0], len(_classes)), dtype=np.float64)")
        lines.append(f"{indent}    for _k in range(len(_classes)):")
        lines.append(f"{indent}        _diff = _scores - _means[_k]")
        lines.append(f"{indent}        _d2 = np.einsum('ij,jk,ik->i', _diff, _cov_inv, _diff)")
        lines.append(f"{indent}        _log_post[:, _k] = -0.5 * _d2 + np.log(_priors[_k])")
        lines.append(f"{indent}    _log_post -= _log_post.max(axis=1, keepdims=True)")
        lines.append(f"{indent}    _probs = np.exp(_log_post)")
        lines.append(f"{indent}    _probs = _probs / _probs.sum(axis=1, keepdims=True)")
        lines.append(
            f"{indent}    _mahalanobis_state = {{'class_score_means': _means, "
            f"'score_covariance_inverse': _cov_inv, 'class_priors': _priors}}"
        )
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    # Softmax to probabilities")
        lines.append(f"{indent}    _exp = np.exp(_y_pred_raw - _y_pred_raw.max(axis=1, keepdims=True))")
        lines.append(f"{indent}    _probs = _exp / _exp.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}_pred_idx = np.argmax(_probs, axis=1)")
        lines.append(f"{indent}_pred_labels = np.array([_classes[i] for i in _pred_idx])")
        lines.append(f"{indent}_accuracy = np.mean(_pred_labels == _y_labels)")
        lines.append(f"{indent}_class_counts = np.array([np.sum(_y_labels == _cls) for _cls in _classes])")
        lines.append(f"{indent}_cv_folds = int({cv_folds})")
        lines.append(f"{indent}if _cv_folds > int(_class_counts.min()):")
        lines.append(
            f"{indent}    raise ValueError(f'cv_folds must be <= smallest class count "
            f"({{int(_class_counts.min())}}). Got {{_cv_folds}}.')"
        )
        lines.append(f"{indent}_y_pred_cv = np.empty(_y_labels.shape, dtype=_y_labels.dtype)")
        lines.append(f"{indent}_y_prob_cv = np.zeros((_X_data.shape[0], len(_classes)), dtype=np.float64)")
        lines.append(f"{indent}_cv = StratifiedKFold(n_splits=_cv_folds, shuffle=True, random_state=42)")
        lines.append(f"{indent}for _train_idx, _test_idx in _cv.split(_X_data, _y_labels):")
        lines.append(f"{indent}    _X_fold = scp.NDDataset(_X_data[_train_idx])")
        lines.append(f"{indent}    _y_fold_idx = np.array([_class_map[c] for c in _y_labels[_train_idx].tolist()])")
        lines.append(f"{indent}    _Y_fold = scp.NDDataset(np.eye(len(_classes))[_y_fold_idx])")
        lines.append(
            f"{indent}    _fold_components = min({n_components}, _X_data.shape[1], max(1, len(_train_idx) - 1))"
        )
        lines.append(f"{indent}    _pls_fold = scp.PLSRegression(n_components=_fold_components, scale={scale_str})")
        lines.append(f"{indent}    _pls_fold.fit(_X_fold, _Y_fold)")
        lines.append(f"{indent}    _X_test_fold = scp.NDDataset(_X_data[_test_idx])")
        lines.append(f"{indent}    if _probability_method == 'mahalanobis':")
        lines.append(f"{indent}        _train_scores_raw = getattr(_pls_fold, 'x_scores', None)")
        lines.append(f"{indent}        if _train_scores_raw is None:")
        lines.append(f"{indent}            _train_scores_raw = getattr(_pls_fold, '_x_scores', None)")
        lines.append(f"{indent}        if _train_scores_raw is None:")
        lines.append(f"{indent}            _train_scores_raw = _pls_fold.transform(_X_fold)")
        lines.append(
            f"{indent}        _train_scores = np.asarray("
            f"_train_scores_raw.data if hasattr(_train_scores_raw, 'data') else _train_scores_raw, "
            f"dtype=np.float64)"
        )
        lines.append(f"{indent}        _test_scores_raw = _pls_fold.transform(_X_test_fold)")
        lines.append(
            f"{indent}        _test_scores = np.asarray("
            f"_test_scores_raw.data if hasattr(_test_scores_raw, 'data') else _test_scores_raw, "
            f"dtype=np.float64)"
        )
        lines.append(f"{indent}        if _train_scores.ndim == 1:")
        lines.append(f"{indent}            _train_scores = _train_scores.reshape(-1, 1)")
        lines.append(f"{indent}        if _test_scores.ndim == 1:")
        lines.append(f"{indent}            _test_scores = _test_scores.reshape(-1, 1)")
        lines.append(
            f"{indent}        _means_fold = np.zeros((len(_classes), _train_scores.shape[1]), dtype=np.float64)"
        )
        lines.append(f"{indent}        _counts_fold = np.zeros(len(_classes), dtype=np.int64)")
        lines.append(f"{indent}        _dev_fold = np.zeros_like(_train_scores)")
        lines.append(f"{indent}        for _k, _cls in enumerate(_classes):")
        lines.append(f"{indent}            _mask_fold = _y_labels[_train_idx] == _cls")
        lines.append(f"{indent}            _counts_fold[_k] = int(_mask_fold.sum())")
        lines.append(f"{indent}            if _counts_fold[_k]:")
        lines.append(f"{indent}                _means_fold[_k] = _train_scores[_mask_fold].mean(axis=0)")
        lines.append(f"{indent}                _dev_fold[_mask_fold] = _train_scores[_mask_fold] - _means_fold[_k]")
        lines.append(f"{indent}        _denom_fold = max(1, _train_scores.shape[0] - len(_classes))")
        lines.append(f"{indent}        _cov_fold = (_dev_fold.T @ _dev_fold) / float(_denom_fold)")
        lines.append(f"{indent}        try:")
        lines.append(
            f"{indent}            _cov_inv_fold = np.linalg.inv(" f"_cov_fold + 1e-10 * np.eye(_train_scores.shape[1]))"
        )
        lines.append(f"{indent}        except np.linalg.LinAlgError:")
        lines.append(f"{indent}            _diag_fold = np.diag(_cov_fold)")
        lines.append(
            f"{indent}            _cov_inv_fold = np.diag(1.0 / np.where(_diag_fold > 1e-12, _diag_fold, 1.0))"
        )
        lines.append(f"{indent}        _priors_fold = np.maximum(_counts_fold / max(1, _train_scores.shape[0]), 1e-12)")
        lines.append(f"{indent}        _priors_fold = _priors_fold / _priors_fold.sum()")
        lines.append(
            f"{indent}        _log_post_fold = np.empty((_test_scores.shape[0], len(_classes)), dtype=np.float64)"
        )
        lines.append(f"{indent}        for _k in range(len(_classes)):")
        lines.append(f"{indent}            _diff_fold = _test_scores - _means_fold[_k]")
        lines.append(
            f"{indent}            _d2_fold = np.einsum('ij,jk,ik->i', " f"_diff_fold, _cov_inv_fold, _diff_fold)"
        )
        lines.append(f"{indent}            _log_post_fold[:, _k] = -0.5 * _d2_fold + np.log(_priors_fold[_k])")
        lines.append(f"{indent}        _log_post_fold -= _log_post_fold.max(axis=1, keepdims=True)")
        lines.append(f"{indent}        _prob_fold = np.exp(_log_post_fold)")
        lines.append(f"{indent}        _prob_fold = _prob_fold / _prob_fold.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        _raw_fold = np.asarray(")
        lines.append(f"{indent}            _pls_fold.predict(_X_test_fold).data,")
        lines.append(f"{indent}            dtype=np.float64,")
        lines.append(f"{indent}        )")
        lines.append(f"{indent}        if _raw_fold.ndim == 1:")
        lines.append(f"{indent}            _raw_fold = _raw_fold.reshape(-1, len(_classes))")
        lines.append(f"{indent}        _exp_fold = np.exp(_raw_fold - _raw_fold.max(axis=1, keepdims=True))")
        lines.append(f"{indent}        _prob_fold = _exp_fold / _exp_fold.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}    _idx_fold = np.argmax(_prob_fold, axis=1)")
        lines.append(f"{indent}    _y_pred_cv[_test_idx] = np.array([_classes[i] for i in _idx_fold])")
        lines.append(f"{indent}    _y_prob_cv[_test_idx] = _prob_fold")
        lines.append(
            f"{indent}_train_metrics = classification_scalar_metrics("
            "_y_labels, _pred_labels, _classes, prefix='train_')"
        )
        lines.append(
            f"{indent}_cv_metrics = classification_scalar_metrics(_y_labels, _y_pred_cv, _classes, prefix='cv_')"
        )
        lines.append(f"{indent}_cm_train = confusion_matrix(_y_labels, _pred_labels, labels=_classes)")
        lines.append(f"{indent}_cm_cv = confusion_matrix(_y_labels, _y_pred_cv, labels=_classes)")
        lines.append(f"{indent}_classification_metrics = classification_metrics_contract(")
        lines.append(f"{indent}    classes=_classes,")
        lines.append(f"{indent}    train_metrics=_train_metrics,")
        lines.append(f"{indent}    cv_metrics=_cv_metrics,")
        lines.append(f"{indent}    primary_split='cv',")
        lines.append(f"{indent}    method='plsda',")
        lines.append(f"{indent}    confusion_matrices={{'train': _cm_train.tolist(), 'cv': _cm_cv.tolist()}},")
        lines.append(f"{indent})")
        lines.append(f"{indent}_cm_labels = [str(c) for c in _classes]")
        lines.append(f"{indent}_cm_train_plot = {{")
        lines.append(
            f"{indent}    'data': [{{'type': 'heatmap', 'z': _cm_train.tolist(), " "'x': _cm_labels, 'y': _cm_labels}],"
        )
        lines.append(f"{indent}    'layout': {{'title': 'Confusion Matrix (Training)'}},")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}_cm_cv_plot = {{")
        lines.append(
            f"{indent}    'data': [{{'type': 'heatmap', 'z': _cm_cv.tolist(), " "'x': _cm_labels, 'y': _cm_labels}],"
        )
        lines.append(f"{indent}    'layout': {{'title': 'Confusion Matrix (Cross-Validation)'}},")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}_scores_raw = getattr(_pls, 'x_scores', None)")
        lines.append(f"{indent}if _scores_raw is None:")
        lines.append(f"{indent}    _scores_raw = getattr(_pls, '_x_scores', None)")
        lines.append(f"{indent}if _scores_raw is None:")
        lines.append(f"{indent}    _scores_raw = _pls.transform(_X_ndd)")
        lines.append(f"{indent}_scores = np.asarray(_scores_raw.data if hasattr(_scores_raw, 'data') else _scores_raw)")
        lines.append(f"{indent}_loadings_raw = getattr(_pls, 'x_loadings', None)")
        lines.append(f"{indent}if _loadings_raw is None:")
        lines.append(f"{indent}    _loadings_raw = getattr(_pls, '_x_loadings', None)")
        lines.append(f"{indent}_loadings = (")
        lines.append(f"{indent}    np.asarray(_loadings_raw.data if hasattr(_loadings_raw, 'data') else _loadings_raw)")
        lines.append(f"{indent}    if _loadings_raw is not None else np.empty((0, _X_data.shape[1]))")
        lines.append(f"{indent})")
        lines.append(
            f'{indent}print(f"  PLS-DA ({n_components} LVs): accuracy={{_accuracy:.4f}} ({{len(_classes)}} classes)")'
        )

        # Store result
        lines.append(
            f"{indent}_model_payload = {{'model': _pls, 'classes': _classes, "
            f"'type': 'plsda', 'probability_method': _probability_method}}"
        )
        lines.append(f"{indent}if _mahalanobis_state is not None:")
        lines.append(f"{indent}    _model_payload.update(_mahalanobis_state)")
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _scores,")
        lines.append(f"{indent}    'X_scores': _scores,")
        lines.append(f"{indent}    'loadings': _loadings,")
        lines.append(f"{indent}    'X_loadings': _loadings,")
        lines.append(f"{indent}    'model': _model_payload,")
        lines.append(f"{indent}    'predictions': _pred_labels,")
        lines.append(f"{indent}    'probabilities': _probs,")
        lines.append(f"{indent}    'class_probabilities': _probs,")
        lines.append(f"{indent}    'y_prob': _y_prob_cv,")
        lines.append(f"{indent}    'train_accuracy': float(_accuracy),")
        lines.append(f"{indent}    'cv_accuracy': float(")
        lines.append(f"{indent}        _cv_metrics.get('cv_accuracy', np.mean(_y_pred_cv == _y_labels))")
        lines.append(f"{indent}    ),")
        lines.append(f"{indent}    'confusion_matrix': _cm_cv,")
        lines.append(f"{indent}    'confusion_matrix_train': _cm_train,")
        lines.append(f"{indent}    'confusion_matrix_cv': _cm_cv,")
        lines.append(f"{indent}    'metrics': {{")
        lines.append(f"{indent}        **_train_metrics,")
        lines.append(f"{indent}        **_cv_metrics,")
        lines.append(f"{indent}        'classification_metrics': _classification_metrics,")
        lines.append(f"{indent}    }},")
        lines.append(
            f"{indent}    'metadata': {{'y_true': _y_labels.tolist(), 'y_pred': _pred_labels.tolist(), "
            f"'y_pred_cv': _y_pred_cv.tolist(), 'label_categories': [str(c) for c in _classes]}},"
        )
        lines.append(
            f"{indent}    'plots': {{'confusion_matrix_train': _cm_train_plot, "
            f"'confusion_matrix_cv': _cm_cv_plot}},"
        )
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PLS-DA classification.

        Args:
            X: NDDataset containing spectral data (predictors)
            y: Class labels

        Returns:
            PLS-DA model with classification results
        """
        from sklearn.metrics import classification_report, confusion_matrix

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be an dataset object",
            allow_array=False,
        )
        y = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            target_type="categorical",
            missing_message=(
                "Missing required input: y (class labels)\n"
                "Either provide labels via the 'y' input port, or use a dataset with labels in X.y"
            ),
            dataset_missing_message=(
                "Dataset passed to y port has no embedded labels. " "Use the y-axis coordinate to store class labels."
            ),
        )

        n_components = self.parameters.get("n_components", 2)
        requested_n_components = int(n_components)
        component_limit_reason = None
        scale = self.parameters.get("scale", False)
        cv_folds = self.parameters.get("cv_folds", 5)
        probability_method = self.parameters.get("probability_method", "softmax")
        if probability_method not in ("softmax", "mahalanobis"):
            logger.warning(
                "[PLS-DA] Unknown probability_method=%r; falling back to 'softmax'",
                probability_method,
            )
            probability_method = "softmax"

        # Convert inputs to numpy arrays
        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            logger.warning(
                "[PLS-DA] n_components=%d exceeds max allowed (%d = min(n_samples-1=%d, n_features=%d)). "
                "Clamping to %d. Consider reducing n_components in the node parameters.",
                n_components,
                max_components,
                X_data.shape[0] - 1,
                X_data.shape[1],
                max_components,
            )
            n_components = max_components
            component_limit_reason = (
                f"Requested {requested_n_components} components, but PLS-DA is limited to "
                f"min(n_samples - 1, n_features) = {max_components} for this dataset."
            )

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # PLS-DA uses class labels to construct Y, but its latent variables are
        # still PLS components of X. Do not cap components by n_classes; binary
        # PLS-DA can legitimately fit more than two LVs when X has enough rank.

        class_counts = np.array([(y_array == cls).sum() for cls in classes])
        min_class_count = int(class_counts.min()) if class_counts.size else 0
        if cv_folds > min_class_count:
            raise ValueError(f"cv_folds must be <= smallest class count ({min_class_count}). Got {cv_folds}.")

        # One-hot encode class labels
        Y_dummy = np.zeros((len(y_array), n_classes))
        for i, cls in enumerate(classes):
            Y_dummy[y_array == cls, i] = 1

        # Prepare data as NDDatasets for SpectroChemPy.
        # X may be SherpaDataset (sklearn path) so wrap X_data explicitly.
        X_ndd = scp.NDDataset(X_data)
        Y_dummy_dataset = scp.NDDataset(Y_dummy)

        # Fit PLS-DA model using SpectroChemPy
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, Y_dummy_dataset)

        # Make predictions on training data
        Y_pred_raw = pls.predict(X_ndd)
        # Extract numpy array from result (these are raw PLS regression outputs, NOT probabilities)
        Y_pred_raw_np = to_numpy_2d(Y_pred_raw, name="Y_pred_raw", dtype=np.float64)

        # Validate prediction shape before processing
        if Y_pred_raw_np.ndim != 2:
            raise ValueError(
                f"PLS-DA predict returned unexpected shape: {Y_pred_raw_np.shape}. "
                f"Expected 2D array with shape (n_samples, n_classes)."
            )
        if Y_pred_raw_np.shape[1] != n_classes:
            raise ValueError(
                f"PLS-DA predict returned {Y_pred_raw_np.shape[1]} columns but expected {n_classes} classes. "
                f"Model may be corrupted or incompatible."
            )

        # Convert raw PLS predictions to class probabilities. Two rules:
        #   softmax     — softmax of Y-hat (engineering shortcut; default for BC)
        #   mahalanobis — Gaussian discriminant in PLS score space (mdatools-style)
        from scipy.special import softmax

        mahalanobis_state = None
        if probability_method == "mahalanobis":
            # Extract training X-scores to fit class means + pooled covariance.
            train_scores_raw = _safe_getattr(pls, ("x_scores", "_x_scores", "x_scores_"))
            if train_scores_raw is None:
                train_scores_raw = pls.transform(X_ndd)
            train_scores_np = np.asarray(
                train_scores_raw.data if hasattr(train_scores_raw, "data") else train_scores_raw,
                dtype=np.float64,
            )
            mahalanobis_state = _fit_plsda_mahalanobis_state(train_scores_np, y_array, classes)
            Y_pred_prob = _plsda_mahalanobis_probabilities_from_state(
                train_scores_np,
                mahalanobis_state["class_score_means"],
                mahalanobis_state["score_covariance_inverse"],
                mahalanobis_state["class_priors"],
            )
        else:
            Y_pred_prob = softmax(Y_pred_raw_np, axis=1)

        # Cross-validation predictions (probability rule honours probability_method)
        y_pred_cv, Y_pred_cv_prob = self._cross_val_predict_plsda(
            X_ds, y_array, classes, n_components, scale, cv_folds, probability_method
        )

        # Optional: Platt scaling for calibrated posterior probabilities (Platt 1999)
        calibrate = self.parameters.get("calibrate_probabilities", False)
        if calibrate and probability_method != "softmax":
            logger.info(
                "[PLS-DA] calibrate_probabilities is only applicable when probability_method='softmax'; "
                "skipping Platt scaling because probability_method=%r already returns proper posteriors.",
                probability_method,
            )
            calibrate = False
        if calibrate:
            try:
                from sklearn.base import BaseEstimator, ClassifierMixin
                from sklearn.calibration import CalibratedClassifierCV

                class _PLSDAWrapper(BaseEstimator, ClassifierMixin):
                    """Thin wrapper so CalibratedClassifierCV can calibrate PLS-DA."""

                    def __init__(self, pls_model, classes, scale_flag):
                        self.pls_model = pls_model
                        self.classes_ = classes
                        self.scale_flag = scale_flag

                    def fit(self, X, y):
                        return self  # Already fitted

                    def predict(self, X):
                        Y_raw = np.asarray(self.pls_model.predict(X))
                        return self.classes_[np.argmax(softmax(Y_raw, axis=1), axis=1)]

                    def decision_function(self, X):
                        return np.asarray(self.pls_model.predict(X))

                X_np = to_numpy_2d(X_ds, name="X_ds", dtype=np.float64)
                wrapper = _PLSDAWrapper(pls, classes, scale)
                cal = CalibratedClassifierCV(wrapper, method="sigmoid", cv="prefit")
                # Encode y as integers for calibration
                y_int = np.searchsorted(classes, y_array)
                cal.fit(X_np, y_int)
                Y_pred_prob = cal.predict_proba(X_np)
                calibrate = True  # confirmed success
                logger.info("Platt scaling applied — probabilities are now calibrated")
            except Exception as exc:
                logger.warning("Platt scaling failed, falling back to softmax: %s", exc)
                calibrate = False

        y_pred_train = classes[np.argmax(Y_pred_prob, axis=1)]

        # Calculate metrics using the shared classification contract.
        train_metrics = _classification_scalar_metrics(y_array, y_pred_train, classes, prefix="train_")
        cv_metrics = _classification_scalar_metrics(y_array, y_pred_cv, classes, prefix="cv_")
        train_accuracy = train_metrics["train_accuracy"]
        cv_accuracy = cv_metrics["cv_accuracy"]

        # Confusion matrices
        cm_train = confusion_matrix(y_array, y_pred_train, labels=classes)
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)
        classification_metrics = _classification_metrics_contract(
            classes=classes,
            train_metrics=train_metrics,
            cv_metrics=cv_metrics,
            primary_split="cv",
            method="plsda",
            confusion_matrices={
                "train": cm_train.tolist(),
                "cv": cm_cv.tolist(),
            },
            extra={
                "cv_method": f"stratified-k-fold (k={cv_folds})",
                "n_components": int(n_components),
                "requested_n_components": requested_n_components,
                "effective_n_components": int(n_components),
                "probability_method": probability_method,
            },
        )

        # Classification report
        class_report = classification_report(
            y_array, y_pred_cv, target_names=[str(c) for c in classes], output_dict=True
        )

        # Classification-appropriate metrics
        cv_balanced_accuracy = cv_metrics["cv_balanced_accuracy"]
        cv_f1_macro = cv_metrics["cv_f1_macro"]

        # Get PLS scores for visualization (extract numpy arrays from SpectroChemPy model)
        # Use _safe_getattr for version-resilient attribute access (SCP 0.8.1+)
        raw_scores = _safe_getattr(pls, ("x_scores", "_x_scores", "x_scores_"))
        if raw_scores is None:
            raw_scores = pls.transform(X_ndd)
        X_scores = _coerce_numeric_array(raw_scores)

        raw_loadings = _safe_getattr(pls, ("x_loadings", "_x_loadings", "x_loadings_"))
        if raw_loadings is None:
            raise RuntimeError("Could not extract x_loadings from PLS-DA model")
        X_loadings = _coerce_numeric_array(raw_loadings)

        # Calculate VIP scores (Variable Importance in Projection)
        vip_error = None
        try:
            vip_scores = self._calculate_vip(pls, X_data, Y_dummy)
        except Exception as e:
            logger.warning("VIP calculation failed: %s", e, exc_info=True)
            vip_scores = np.zeros(X_data.shape[1], dtype=float)
            vip_error = f"{type(e).__name__}: {e}"

        # Extract wavenumbers and feature_names from input coordinates for plot generation
        _x_coord = X_ds.feature_axis
        _y_coord = X_ds.sample_axis
        wavenumbers = None
        feature_names = None

        if _x_coord is not None:
            try:
                x_data = _x_coord.data
                if x_data is not None:
                    wavenumbers = np.array(x_data).tolist()
            except Exception:
                pass
            if hasattr(_x_coord, "labels") and _x_coord.labels is not None:
                try:
                    labels = _x_coord.labels
                    feature_names = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                except Exception:
                    pass

        # Generate plots for visualization
        plot_error = None

        try:
            plots = self._generate_plsda_plots(
                X_scores, X_loadings, vip_scores, y_array, classes, n_components, wavenumbers, feature_names
            )

            # Add confusion matrix heatmaps (using shared utility)
            plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
                cm_train, classes, "Confusion Matrix (Training Set)"
            )
            plots["confusion_matrix_cv"] = generate_confusion_matrix_heatmap(
                cm_cv, classes, "Confusion Matrix (Cross-Validation)"
            )

        except Exception as e:
            error_msg = f"Plot generation failed: {str(e)}"
            logger.warning("Plot generation failed: %s", e, exc_info=True)
            # Return partial plots with error info instead of silently failing
            plots = {
                "_error": error_msg,
                "_error_type": type(e).__name__,
            }
            plot_error = error_msg

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Build LV labels for scores dataset x-axis
        lv_labels = [f"LV{i+1}" for i in range(n_components)]

        # =====================================================================
        # Create SherpaDataset outputs with proper coordinate coupling
        # =====================================================================

        # Scores: shape (n_samples, n_components)
        scores_dataset = create_spectral_dataset(
            data=X_scores,
            x_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PLS-DA Scores",
            data_role="X_features",
        )

        # Loadings: shape (n_components, n_features)
        loadings_dataset = create_spectral_dataset(
            data=X_loadings,
            x_coord=_x_coord,  # Preserve wavenumber/feature axis from input
            y_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            units="loading",
            title="PLS-DA Loadings",
        )

        # Add processing history
        copy_processing_history(X_ds, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.plsda.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(X_ds, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "classification.plsda.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. Scores rows are samples;
        # loadings rows are latent variables — origin tags only.
        inherit_sample_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, loadings_dataset)

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "type": "PLS_DA",
                "n_components": n_components,
                "requested_n_components": requested_n_components,
                "effective_n_components": int(n_components),
                "component_limit_warning": component_limit_reason,
                "probabilities_calibrated": calibrate,
                "probability_method": probability_method,
                "probabilities_warning": (
                    "Class probabilities are softmax-transformed raw PLS regression outputs. "
                    "They are NOT statistically calibrated — do not interpret as true posterior "
                    "probabilities. Apply Platt scaling or isotonic regression on the CV "
                    "predictions for calibrated confidence estimates (Platt 1999)."
                    if probability_method == "softmax" and not calibrate
                    else (
                        "Class probabilities are Bayesian posteriors from a Gaussian discriminant "
                        "on PLS scores (mdatools-style) with class priors π_k = n_k/n. "
                        "Reference: Kucheryavskiy, Chemometrics with R, ch. 9."
                        if probability_method == "mahalanobis"
                        else "Class probabilities have been calibrated via Platt scaling (Platt 1999)."
                    )
                ),
                "label_categories": label_categories,
                "lv_labels": lv_labels,
                "train_accuracy": train_accuracy,
                "cv_accuracy": cv_accuracy,
                "train_balanced_accuracy": train_metrics["train_balanced_accuracy"],
                "cv_balanced_accuracy": cv_balanced_accuracy,
                "train_f1_macro": train_metrics["train_f1_macro"],
                "cv_f1_macro": cv_metrics["cv_f1_macro"],
                "train_precision_macro": train_metrics["train_precision_macro"],
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "train_recall_macro": train_metrics["train_recall_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "train_sensitivity_macro": train_metrics["train_sensitivity_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "train_specificity_macro": train_metrics["train_specificity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "confusion_matrix_train": cm_train.tolist(),
                "confusion_matrix_cv": cm_cv.tolist(),
                "metrics": classification_metrics,
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": y_pred_train.tolist(),
                "y_pred_cv": y_pred_cv.tolist(),
                "vip_scores": vip_scores.tolist(),
                "vip_error": vip_error,
                "plot_error": plot_error,
                "quality_summary": {
                    "n_components": int(n_components),
                    "requested_n_components": requested_n_components,
                    "effective_n_components": int(n_components),
                    "n_classes": int(len(classes)),
                    "cv_method": f"k-fold (k={cv_folds})",
                    "train_accuracy": float(train_accuracy),
                    "cv_accuracy": float(cv_accuracy),
                    "cv_balanced_accuracy": float(cv_balanced_accuracy),
                    "cv_f1_macro": float(cv_f1_macro),
                    "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                    "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                    "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                    "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                    "probability_method": probability_method,
                },
            }
        )

        model_payload = {
            "model": pls,
            "classes": classes.tolist(),
            "type": "plsda",
            "probability_method": probability_method,
        }
        if mahalanobis_state is not None:
            model_payload.update(
                {
                    "class_score_means": mahalanobis_state["class_score_means"].tolist(),
                    "score_covariance_inverse": mahalanobis_state["score_covariance_inverse"].tolist(),
                    "class_priors": mahalanobis_state["class_priors"].tolist(),
                }
            )

        from ..modeling._artifact_builder import build_model_artifact

        extracted = PLSExtract.from_scp(pls, X_ndd, Y_ndd=Y_dummy_dataset)
        if extracted.coef is None or extracted.x_mean is None or extracted.y_mean is None:
            raise RuntimeError("Could not extract PLS-DA coefficients for model artifact persistence")
        plsda_extract = PLSDAExtract(
            coef=extracted.coef,
            x_mean=extracted.x_mean,
            y_mean=extracted.y_mean,
            classes=label_categories,
            x_loadings=extracted.x_loadings,
            y_loadings=extracted.y_loadings,
            n_components=int(n_components),
        )
        artifact = build_model_artifact(
            plsda_extract,
            X_ds,
            node_id=self.node_id,
            metrics={
                "train_accuracy": float(train_accuracy),
                "cv_accuracy": float(cv_accuracy),
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "cv_balanced_accuracy": float(cv_balanced_accuracy),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "cv_f1_macro": float(cv_f1_macro),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                "classification_metrics": classification_metrics,
                "probability_method": probability_method,
            },
        )
        artifact["metadata"]["probability_method"] = probability_method
        if probability_method != "softmax":
            artifact["metadata"]["prediction_note"] = (
                "Persisted PLS-DA artifacts currently replay the softmax PLS regression rule. "
                f"The training node used probability_method={probability_method!r} for diagnostics."
            )

        # SherpaDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: scores (n_samples, n_components)
                "X_scores": scores_dataset,  # Alias of default for the declared X_scores port
                "loadings": loadings_dataset,  # SherpaDataset: loadings (n_components, n_features)
                "X_loadings": loadings_dataset,  # Alias for direct port wiring
                "model": model_payload,  # Wrapped model dict for ClassifierPredictNode
                "predictions": y_pred_cv.tolist(),
                "probabilities": Y_pred_cv_prob.tolist(),
                "class_probabilities": Y_pred_cv_prob.tolist(),
                "metrics": classification_metrics,
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
                "_model_artifact": artifact,
            },
            diagnostics={
                "train_accuracy": train_accuracy,
                "cv_accuracy": cv_accuracy,
                "cv_balanced_accuracy": cv_balanced_accuracy,
                "cv_f1_macro": cv_f1_macro,
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "metrics": classification_metrics,
                "n_components": n_components,
                "requested_n_components": requested_n_components,
                "effective_n_components": int(n_components),
                "component_limit_warning": component_limit_reason,
                "n_classes": len(classes),
                "confusion_matrix_cv": cm_cv.tolist(),
                "probability_method": probability_method,
            },
        )

    def _cross_val_predict_plsda(
        self,
        X,
        y,
        classes,
        n_components,
        scale,
        cv_folds,
        probability_method: str = "softmax",
    ):
        """
        Perform cross-validated predictions for PLS-DA using SpectroChemPy.

        Args:
            probability_method: 'softmax' applies softmax to PLS Y-hat;
                'mahalanobis' fits Gaussian discriminant on the training-fold
                PLS scores and classifies the held-out fold's scores by
                Mahalanobis distance with class priors.

        Returns:
            y_pred: Predicted class labels
            Y_pred_prob: Prediction probabilities
        """
        from sklearn.model_selection import StratifiedKFold

        X_data = to_numpy_2d(X, name="X", dtype=np.float64)

        y_pred = np.zeros_like(y)
        Y_pred_prob = np.zeros((len(y), len(classes)))
        kf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)

        for train_idx, test_idx in kf.split(X_data, y):
            X_train_data, X_test_data = X_data[train_idx], X_data[test_idx]
            y_train = y[train_idx]

            # One-hot encode training labels
            Y_train_dummy = np.zeros((len(y_train), len(classes)))
            for i, cls in enumerate(classes):
                Y_train_dummy[y_train == cls, i] = 1

            # Create NDDatasets for SpectroChemPy
            X_train = scp.NDDataset(X_train_data)
            X_test = scp.NDDataset(X_test_data)
            Y_train_dummy_dataset = scp.NDDataset(Y_train_dummy)

            # Fit PLS model on training fold using SpectroChemPy
            pls = scp.PLSRegression(n_components=n_components, scale=scale)
            pls.fit(X_train, Y_train_dummy_dataset)

            if probability_method == "mahalanobis":
                # Project both train and test folds onto the fold's PLS LVs,
                # then apply Gaussian discriminant with class priors. No raw
                # Y-hat is needed.
                train_scores_raw = _safe_getattr(pls, ("x_scores", "_x_scores", "x_scores_"))
                if train_scores_raw is None:
                    train_scores_raw = pls.transform(X_train)
                test_scores_raw = pls.transform(X_test)
                train_scores_np = np.asarray(
                    train_scores_raw.data if hasattr(train_scores_raw, "data") else train_scores_raw,
                    dtype=np.float64,
                )
                test_scores_np = np.asarray(
                    test_scores_raw.data if hasattr(test_scores_raw, "data") else test_scores_raw,
                    dtype=np.float64,
                )
                Y_test_pred_prob = _plsda_mahalanobis_probabilities(
                    train_scores=train_scores_np,
                    train_labels=y_train,
                    test_scores=test_scores_np,
                    classes=classes,
                )
            else:
                # Predict on test fold
                Y_test_pred_raw = pls.predict(X_test)
                # Extract numpy array (raw PLS regression outputs, NOT probabilities)
                Y_test_pred_raw_np = to_numpy_2d(Y_test_pred_raw, name="Y_test_pred_raw", dtype=np.float64)

                # Validate prediction shape before argmax
                if Y_test_pred_raw_np.ndim != 2 or Y_test_pred_raw_np.shape[1] != len(classes):
                    raise ValueError(
                        f"CV fold prediction has unexpected shape {Y_test_pred_raw_np.shape}. "
                        f"Expected (n_test_samples, {len(classes)})."
                    )

                # CRITICAL: Apply softmax to convert raw PLS outputs to proper probabilities
                from scipy.special import softmax

                Y_test_pred_prob = softmax(Y_test_pred_raw_np, axis=1)

            y_pred[test_idx] = classes[np.argmax(Y_test_pred_prob, axis=1)]
            Y_pred_prob[test_idx] = Y_test_pred_prob

        return y_pred, Y_pred_prob

    def _calculate_vip(self, pls_model, X, Y):
        """
        Calculate Variable Importance in Projection (VIP) scores.

        VIP scores indicate the importance of each variable in the PLS model.
        VIP > 1 indicates important variables.

        Delegates to the shared VIP utility in the selection package.
        """
        from ..selection._vip import extract_vip_from_pls_model

        return extract_vip_from_pls_model(pls_model, X.shape[1])

    def _generate_plsda_plots(
        self, scores, loadings, vip_scores, y_array, classes, n_components, wavenumbers, feature_names=None
    ):
        """
        Generate plots for PLS-DA visualization.

        Args:
            scores: PLS scores array
            loadings: PLS loadings array
            vip_scores: VIP scores array
            y_array: Class labels array
            classes: Unique class labels
            n_components: Number of components
            wavenumbers: Wavenumber values (optional)
            feature_names: Feature names (e.g., ["Sepal Length", "Sepal Width"] for iris) (optional)

        Returns:
            Dict with plot specifications for Quick Plot
        """

        plots = {}

        # 1. Scores Plot (LV1 vs LV2) with confidence ellipses
        if n_components >= 2:
            traces = []

            # Standard Plotly color palette (same as frontend)
            PLOTLY_COLORS = [
                "#636EFA",
                "#EF553B",
                "#00CC96",
                "#AB63FA",
                "#FFA15A",
                "#19D3F3",
                "#FF6692",
                "#B6E880",
                "#FF97FF",
                "#FECB52",
            ]

            # Create scatter traces for each class with confidence ellipses
            for idx, cls in enumerate(classes):
                mask = y_array == cls
                class_scores = scores[mask]

                # Assign color from palette
                color = PLOTLY_COLORS[idx % len(PLOTLY_COLORS)]

                # Scatter trace for this class
                trace = {
                    "x": class_scores[:, 0].tolist(),
                    "y": class_scores[:, 1].tolist(),
                    "type": "scatter",
                    "mode": "markers",
                    "name": str(cls),
                    "marker": {"size": 8, "color": color},
                }
                traces.append(trace)

                # Calculate 95% confidence ellipse
                if len(class_scores) >= 3:  # Need at least 3 points for ellipse
                    ellipse_trace = self._calculate_confidence_ellipse(
                        class_scores[:, 0], class_scores[:, 1], confidence=0.95, name=f"{cls} (95%)", color=color
                    )
                    # Only add ellipse if successfully calculated (not degenerate)
                    if ellipse_trace is not None:
                        traces.append(ellipse_trace)

            plots["scores"] = {
                "data": traces,
                "layout": {
                    "title": "PLS-DA Scores Plot",
                    "xaxis": {"title": "LV1"},
                    "yaxis": {"title": "LV2"},
                    "showlegend": True,
                },
            }

        # 2A. Loadings Line Plot (like PCA) - shows each LV as a line across features
        if len(loadings) > 0:
            # loadings shape: (n_components, n_features)
            n_features = loadings.shape[1]

            # Priority: feature_names > wavenumbers > feature indices
            x_values = None
            x_title = "Feature Index"
            x_reversed = False

            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == n_features
            ):
                x_values = feature_names
                x_title = "Feature"
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == n_features
            ):
                x_values = wavenumbers
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True

            if x_values is None:
                x_values = list(range(n_features))

            # Create line traces for each LV
            traces = []
            for i in range(n_components):
                traces.append(
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "x": x_values,
                        "y": loadings[i, :].tolist(),  # LV i's loadings across all features
                        "name": f"LV{i+1}",
                        "line": {"width": 2},
                    }
                )

            plots["loadings_lines"] = {
                "data": traces,
                "layout": {
                    "title": "PLS-DA Loadings (Component Patterns)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "Loading"},
                    "showlegend": True,
                },
            }

        # 2B. Loadings Biplot (LV1 vs LV2) - shows how features relate to latent variables
        # This is the correct chemometric biplot visualization: arrows showing feature relationships
        if len(loadings) > 0 and n_components >= 2:
            # Create labels for each feature with safety checks
            # loadings shape: (n_components, n_features), we need labels for n_features (columns)
            n_features = loadings.shape[1]

            labels = None
            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == n_features
            ):
                labels = feature_names
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == n_features
            ):
                # For spectral data, use wavenumber values as labels (limit to prevent overcrowding)
                if len(wavenumbers) <= 50:
                    labels = [f"{w:.0f}" for w in wavenumbers]
                else:
                    # For many features, only label every Nth feature
                    step = len(wavenumbers) // 20
                    labels = [f"{wavenumbers[i]:.0f}" if i % step == 0 else "" for i in range(len(wavenumbers))]

            if labels is None:
                labels = [f"F{i}" for i in range(n_features)]

            # Quiver plot: arrows from origin to each feature's loading position
            # Create annotations for arrows (Plotly arrows are annotations)
            # loadings shape: (n_components, n_features) where rows are LVs and columns are features
            annotations = []
            for i in range(n_features):  # Iterate over features (columns)
                lv1 = float(loadings[0, i])  # Loading of feature i on LV1 (component 0)
                lv2 = float(loadings[1, i])  # Loading of feature i on LV2 (component 1)

                # Arrow annotation from (0,0) to (lv1, lv2)
                annotations.append(
                    {
                        "x": lv1,
                        "y": lv2,
                        "ax": 0,  # Arrow starts at origin x
                        "ay": 0,  # Arrow starts at origin y
                        "xref": "x",
                        "yref": "y",
                        "axref": "x",
                        "ayref": "y",
                        "showarrow": True,
                        "arrowhead": 2,
                        "arrowsize": 1,
                        "arrowwidth": 2,
                        "arrowcolor": "steelblue",
                    }
                )

                # Text label at 1.15x the arrow length
                annotations.append(
                    {
                        "x": lv1 * 1.15,
                        "y": lv2 * 1.15,
                        "text": labels[i],
                        "xref": "x",
                        "yref": "y",
                        "showarrow": False,
                        "font": {"size": 10, "color": "black"},
                        "xanchor": "center",
                        "yanchor": "middle",
                    }
                )

            plots["loadings_biplot"] = {
                "data": [
                    {
                        # Dummy invisible trace needed for Plotly to render annotations
                        "x": [0],
                        "y": [0],
                        "type": "scatter",
                        "mode": "markers",
                        "marker": {"size": 0.1, "opacity": 0},
                        "showlegend": False,
                        "hoverinfo": "skip",
                    }
                ],
                "layout": {
                    "title": "PLS-DA Loadings Biplot (Feature Correlations)",
                    "xaxis": {"title": "Loading on LV1", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "yaxis": {"title": "Loading on LV2", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "showlegend": False,
                    "annotations": annotations,
                    "hovermode": "closest",
                },
            }

        # Set default "loadings" to line plot for consistency with PCA
        if "loadings_lines" in plots:
            plots["loadings"] = plots["loadings_lines"]

        # 3. VIP Scores Bar Plot
        if len(vip_scores) > 0:
            # Show only top N VIP scores for clarity
            top_n = min(50, len(vip_scores))
            top_indices = np.argsort(vip_scores)[-top_n:][::-1]

            # Priority: feature_names > wavenumbers > feature indices (with safety checks)
            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == len(vip_scores)
            ):
                x_values = [feature_names[i] for i in top_indices]
                x_title = "Feature"
                x_reversed = False
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == len(vip_scores)
            ):
                x_values = [wavenumbers[i] for i in top_indices]
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True
            else:
                x_values = [i for i in top_indices]
                x_title = "Feature Index"
                x_reversed = False

            plots["vip"] = {
                "data": [
                    {
                        "x": x_values,
                        "y": vip_scores[top_indices].tolist(),
                        "type": "bar",
                        "name": "VIP Scores",
                        "marker": {
                            "color": vip_scores[top_indices].tolist(),
                            "colorscale": "Viridis",
                            "showscale": True,
                            "colorbar": {"title": "VIP"},
                        },
                    }
                ],
                "layout": {
                    "title": f"Top {top_n} VIP Scores (VIP > 1 indicates importance)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "VIP Score"},
                    "shapes": [
                        {
                            "type": "line",
                            "x0": 0,  # Start from first bar position
                            "x1": len(x_values) - 1,  # End at last bar position
                            "y0": 1,
                            "y1": 1,
                            "line": {"color": "red", "width": 2, "dash": "dash"},
                        }
                    ],
                },
            }

        return plots

    def _calculate_confidence_ellipse(self, x, y, confidence=0.95, name="Ellipse", color=None):
        """
        Calculate confidence ellipse for 2D data.

        Args:
            x: X coordinates
            y: Y coordinates
            confidence: Confidence level (default 0.95 for 95%)
            name: Name for the trace
            color: Line color (optional, uses default if not provided)

        Returns:
            Plotly trace dict for the ellipse, or None if data is degenerate
        """
        from scipy import stats

        # Calculate covariance
        data = np.column_stack([x, y])
        mean = np.mean(data, axis=0)
        cov = np.cov(data.T)

        # Eigenvalues and eigenvectors
        eigenvalues, eigenvectors = np.linalg.eig(cov)

        # Handle degenerate cases (collinear points, zero variance, numerical errors)
        # Ensure eigenvalues are non-negative (they should be, but numerical errors can occur)
        eigenvalues = np.maximum(eigenvalues.real, 0)

        # Skip ellipse if data is essentially degenerate (all points nearly identical)
        if np.max(eigenvalues) < 1e-10:
            return None

        # Ensure both eigenvalues are positive (minimum threshold for numerical stability)
        eigenvalues = np.maximum(eigenvalues, 1e-10)

        # Chi-squared value for confidence level (2 degrees of freedom)
        chi2_val = stats.chi2.ppf(confidence, 2)

        # Calculate ellipse parameters
        angle = np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0])
        width = 2 * np.sqrt(chi2_val * eigenvalues[0])
        height = 2 * np.sqrt(chi2_val * eigenvalues[1])

        # Generate ellipse points
        t = np.linspace(0, 2 * np.pi, 100)
        ellipse = np.column_stack([width / 2 * np.cos(t), height / 2 * np.sin(t)])

        # Rotate ellipse
        rotation_matrix = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        ellipse_rotated = ellipse @ rotation_matrix.T

        # Translate to mean
        ellipse_final = ellipse_rotated + mean

        line_style = {"dash": "dash", "width": 2}
        if color:
            line_style["color"] = color

        return {
            "x": ellipse_final[:, 0].tolist(),
            "y": ellipse_final[:, 1].tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": name,
            "line": line_style,
            "showlegend": False,
        }
