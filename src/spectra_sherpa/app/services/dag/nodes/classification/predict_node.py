"""
Consolidated classifier prediction node.

Auto-detects model type (PLS-DA, KNN, SIMCA) from the model dict
and dispatches to the appropriate prediction logic.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import scp
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import (
    _plsda_mahalanobis_probabilities_from_state,
)

logger = logging.getLogger(__name__)


@register_node
class ClassifierPredictNode(Node):
    """
    Apply a trained classification model to predict class labels for new samples.

    Auto-detects the model type from the input dict:
    - SIMCA: identified by ``class_models`` key (per-class PCA models)
    - KNN: identified by sklearn model with ``predict_proba`` method
    - PLS-DA: SpectroChemPy PLS model (fallback)

    Consolidated classifier prediction node. Auto-detects the classifier type
    from the model and dispatches accordingly.
    """

    metadata = NodeMetadata(
        node_type="classification.predict",
        category="classification",
        label="Apply Classification Model",
        description="Apply a fitted classification model (PLS-DA, KNN, or SIMCA) to inference data",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Inference Spectra",
                description="Spectral data to classify; must match the fitted model contract",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted Classification Model",
                description="Fitted classification model from a training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predicted Classes",
                description="Predicted class labels",
            ),
            PortMetadata(
                name="y_prob",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities / Distances",
                description="Predicted class probabilities (PLS-DA/KNN) or distances (SIMCA)",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for classifier prediction."""
        X_expr = inputs.get("X_new", inputs.get("default", "input_data"))
        model_expr = inputs.get("model", "model")

        lines: list[str] = []
        lines.append(f"{indent}# --- Apply Classification Model ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Get model dict and dispatch by type
        lines.append(f"{indent}_model_dict = {model_expr}")
        lines.append(f"{indent}_model_type = _model_dict.get('type', '') if isinstance(_model_dict, dict) else ''")
        lines.append("")
        lines.append(f"{indent}if _model_type == 'knn':")
        lines.append(f"{indent}    # KNN — sklearn predict + predict_proba")
        lines.append(f"{indent}    _estimator = _model_dict['model']")
        lines.append(f"{indent}    _y_pred = _estimator.predict(_X_data)")
        lines.append(f"{indent}    _y_prob = _estimator.predict_proba(_X_data)")
        lines.append(f"{indent}elif _model_type == 'plsda':")
        lines.append(f"{indent}    # PLS-DA — persisted probability rule + class mapping")
        lines.append(f"{indent}    _pls_model = _model_dict['model']")
        lines.append(f"{indent}    _classes = _model_dict['classes']")
        lines.append(f"{indent}    _prob_method = _model_dict.get('probability_method', 'softmax')")
        lines.append(f"{indent}    if _prob_method == 'mahalanobis':")
        lines.append(f"{indent}        _means = np.asarray(_model_dict['class_score_means'], dtype=np.float64)")
        lines.append(
            f"{indent}        _cov_inv = np.asarray(" "_model_dict['score_covariance_inverse'], dtype=np.float64)"
        )
        lines.append(f"{indent}        _priors = np.asarray(_model_dict['class_priors'], dtype=np.float64)")
        if use_scp:
            lines.append(
                f"{indent}        _scores = np.asarray("
                "_pls_model.transform(scp.NDDataset(_X_data)).data, dtype=np.float64)"
            )
        else:
            lines.append(f"{indent}        _scores = np.asarray(_pls_model.transform(_X_data), dtype=np.float64)")
        lines.append(f"{indent}        if _scores.ndim == 1:")
        lines.append(f"{indent}            _scores = _scores.reshape(-1, 1)")
        lines.append(f"{indent}        _log_priors = np.log(np.maximum(_priors, 1e-12))")
        lines.append(f"{indent}        _log_post = np.empty((_scores.shape[0], len(_classes)), dtype=np.float64)")
        lines.append(f"{indent}        for _k in range(len(_classes)):")
        lines.append(f"{indent}            _diff = _scores - _means[_k]")
        lines.append(f"{indent}            _d2 = np.einsum('ij,jk,ik->i', _diff, _cov_inv, _diff)")
        lines.append(f"{indent}            _log_post[:, _k] = -0.5 * _d2 + _log_priors[_k]")
        lines.append(f"{indent}        _log_post -= _log_post.max(axis=1, keepdims=True)")
        lines.append(f"{indent}        _y_prob = np.exp(_log_post)")
        lines.append(f"{indent}        _y_prob = _y_prob / _y_prob.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}    elif _prob_method == 'softmax':")
        if use_scp:
            lines.append(
                f"{indent}        _y_raw = np.asarray("
                "_pls_model.predict(scp.NDDataset(_X_data)).data, dtype=np.float64)"
            )
        else:
            lines.append(f"{indent}        _y_raw = np.asarray(_pls_model.predict(_X_data), dtype=np.float64)")
        lines.append(f"{indent}        if _y_raw.ndim == 1:")
        lines.append(f"{indent}            _y_raw = _y_raw.reshape(-1, len(_classes))")
        lines.append(f"{indent}        _exp = np.exp(_y_raw - _y_raw.max(axis=1, keepdims=True))")
        lines.append(f"{indent}        _y_prob = _exp / _exp.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        raise ValueError(f'Unsupported PLS-DA probability_method: {{_prob_method}}')")
        lines.append(f"{indent}    _y_pred = np.array([_classes[i] for i in np.argmax(_y_prob, axis=1)])")
        lines.append(f"{indent}elif _model_type == 'simca':")
        lines.append(f"{indent}    # SIMCA — per-class distance classification")
        lines.append(f"{indent}    _cm = _model_dict['class_models']")
        lines.append(f"{indent}    _classes = _model_dict['classes']")
        lines.append(f"{indent}    _T2_lim = _model_dict.get('T2_limits', {{}})")
        lines.append(f"{indent}    _Q_lim = _model_dict.get('Q_limits', {{}})")
        lines.append(f"{indent}    _y_pred, _y_prob = [], []")
        lines.append(f"{indent}    _accepted_classes, _membership_matrix = [], []")
        lines.append(f"{indent}    for _i in range(len(_X_data)):")
        lines.append(f"{indent}        _dists = {{}}")
        lines.append(f"{indent}        _accepted, _members = [], []")
        lines.append(f"{indent}        for _cls in _classes:")
        lines.append(f"{indent}            _m = _cm[_cls]")
        lines.append(f"{indent}            _loadings = np.array(_m['loadings'])")
        lines.append(f"{indent}            _eigvals = np.array(_m['eigenvalues'])")
        lines.append(f"{indent}            if 'x_mean' in _m and 'x_scale' in _m:")
        lines.append(f"{indent}                _x_mean = np.asarray(_m['x_mean'], dtype=np.float64)")
        lines.append(
            f"{indent}                _x_scale = np.maximum(" "np.asarray(_m['x_scale'], dtype=np.float64), 1e-12)"
        )
        lines.append(
            f"{indent}                _pca_mean = np.asarray("
            "_m.get('pca_mean', np.zeros_like(_x_mean)), dtype=np.float64)"
        )
        lines.append(f"{indent}                _x_work = (_X_data[_i] - _x_mean) / _x_scale")
        lines.append(f"{indent}                _centered = _x_work - _pca_mean")
        lines.append(f"{indent}                _t = _centered @ _loadings.T")
        lines.append(f"{indent}                _resid = _x_work - (_t @ _loadings + _pca_mean)")
        lines.append(f"{indent}            else:")
        lines.append(f"{indent}                _mean = np.array(_m['class_mean'])")
        lines.append(f"{indent}                _centered = _X_data[_i] - _mean")
        lines.append(f"{indent}                _t = _centered @ _loadings.T")
        lines.append(f"{indent}                _resid = _centered - _t @ _loadings")
        lines.append(f"{indent}            _T2 = np.sum(_t**2 / np.maximum(_eigvals, 1e-10))")
        lines.append(f"{indent}            _Q = np.sum(_resid**2)")
        lines.append(f"{indent}            _t2l = float(_T2_lim.get(_cls, 1.0))")
        lines.append(f"{indent}            _ql = float(_Q_lim.get(_cls, 1.0))")
        lines.append(f"{indent}            _is_member = bool(_T2 <= _t2l and _Q <= _ql)")
        lines.append(f"{indent}            _dists[_cls] = _T2 / max(_t2l, 1e-10) + _Q / max(_ql, 1e-10)")
        lines.append(f"{indent}            _members.append(_is_member)")
        lines.append(f"{indent}            if _is_member:")
        lines.append(f"{indent}                _accepted.append(str(_cls))")
        lines.append(f"{indent}        _y_pred.append(min(_accepted, key=_dists.get) if _accepted else 'unassigned')")
        lines.append(f"{indent}        _y_prob.append(_dists)")
        lines.append(f"{indent}        _accepted_classes.append(_accepted)")
        lines.append(f"{indent}        _membership_matrix.append(_members)")
        lines.append(f"{indent}    _y_pred = np.array(_y_pred)")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    # Fallback: bare estimator with predict()")
        lines.append(
            f"{indent}    _estimator = _model_dict.get('model', _model_dict)"
            f" if isinstance(_model_dict, dict) else _model_dict"
        )
        lines.append(f"{indent}    if hasattr(_estimator, 'predict_proba'):")
        lines.append(f"{indent}        _y_pred = _estimator.predict(_X_data)")
        lines.append(f"{indent}        _y_prob = _estimator.predict_proba(_X_data)")
        lines.append(f"{indent}    elif hasattr(_estimator, 'predict'):")
        lines.append(f"{indent}        _y_pred = _estimator.predict(_X_data)")
        lines.append(f"{indent}        _y_prob = None")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        raise ValueError('Model does not support predict()')")
        lines.append(f'{indent}print(f"  Classifier Predict: {{len(_y_pred)}} samples classified")')

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'y_pred': _y_pred.tolist() if hasattr(_y_pred, 'tolist') else list(_y_pred),")
        lines.append(
            f"{indent}    'y_prob': _y_prob if isinstance(_y_prob, list)"
            f" else (_y_prob.tolist() if _y_prob is not None"
            f" and hasattr(_y_prob, 'tolist') else _y_prob),"
        )
        lines.append(f"{indent}    'accepted_classes': _accepted_classes if '_accepted_classes' in locals() else None,")
        lines.append(
            f"{indent}    'membership_matrix': _membership_matrix if '_membership_matrix' in locals() else None,"
        )
        lines.append(
            f"{indent}    'n_rejected': int(np.sum(_y_pred == 'unassigned')) "
            "if '_accepted_classes' in locals() else 0,"
        )
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> NodeResult:
        if X_new is None:
            raise ValueError("Missing required input: X_new (new spectra)")
        if model is None:
            raise ValueError("Missing required input: model (trained classification model)")

        if not isinstance(model, dict):
            raise ValueError("Model must be a dict containing trained model and metadata")

        X_new_ds = bind_X(
            X_new,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be a dataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        # Auto-detect model type and dispatch
        if "class_models" in model:
            return self._predict_simca(X_array, model)
        elif hasattr(model.get("model"), "predict_proba"):
            return self._predict_knn(X_array, model)
        else:
            return self._predict_plsda(X_array, model)

    # ------------------------------------------------------------------
    # PLS-DA prediction
    # ------------------------------------------------------------------
    def _predict_plsda(self, X_array: np.ndarray, model: dict) -> NodeResult:
        from spectra_sherpa.app.lib.scp_compat import HAS_SCP

        if not HAS_SCP:
            raise ImportError(
                "PLS-DA prediction requires SpectroChemPy. " "Install with: pip install spectra-sherpa[scp]"
            )

        from scipy.special import softmax

        pls_model = model.get("model")
        classes = np.array(model.get("classes", []))
        probability_method = model.get("probability_method", "softmax")

        if pls_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained PLS-DA model")

        X_dataset = scp.NDDataset(X_array)

        n_classes = len(classes)
        if probability_method == "mahalanobis":
            required_keys = ("class_score_means", "score_covariance_inverse", "class_priors")
            missing = [key for key in required_keys if key not in model]
            if missing:
                raise ValueError(
                    "PLS-DA model was trained with probability_method='mahalanobis' "
                    f"but is missing persisted discriminant state: {', '.join(missing)}"
                )
            scores = pls_model.transform(X_dataset)
            scores_np = to_numpy_2d(scores, name="X_scores", dtype=np.float64)
            Y_pred_prob = _plsda_mahalanobis_probabilities_from_state(
                scores_np,
                np.asarray(model["class_score_means"], dtype=np.float64),
                np.asarray(model["score_covariance_inverse"], dtype=np.float64),
                np.asarray(model["class_priors"], dtype=np.float64),
            )
        elif probability_method == "softmax":
            Y_pred_raw = pls_model.predict(X_dataset)
            Y_pred_raw_np = to_numpy_2d(Y_pred_raw, name="Y_pred_raw", dtype=np.float64)

            if Y_pred_raw_np.ndim != 2:
                raise ValueError(
                    f"PLS-DA predict returned unexpected shape: {Y_pred_raw_np.shape}. "
                    f"Expected 2D array with shape (n_samples, n_classes)."
                )
            if Y_pred_raw_np.shape[1] != n_classes:
                raise ValueError(
                    f"PLS-DA predict returned {Y_pred_raw_np.shape[1]} columns but expected {n_classes} classes. "
                    f"Model may be incompatible with the provided class labels."
                )

            Y_pred_prob = softmax(Y_pred_raw_np, axis=1)
        else:
            raise ValueError(f"Unsupported PLS-DA probability_method: {probability_method!r}")

        y_pred = classes[np.argmax(Y_pred_prob, axis=1)]

        mean_max_prob = float(np.mean(Y_pred_prob.max(axis=1))) if Y_pred_prob.size else 0.0
        return NodeResult(
            outputs={
                "y_pred": y_pred.tolist(),
                "y_prob": Y_pred_prob.tolist(),
            },
            diagnostics={
                "method": "plsda",
                "probability_method": probability_method,
                "n_predicted": int(len(y_pred)),
                "n_classes": int(len(np.unique(y_pred))),
                "mean_max_prob": mean_max_prob,
            },
        )

    # ------------------------------------------------------------------
    # KNN prediction
    # ------------------------------------------------------------------
    def _predict_knn(self, X_array: np.ndarray, model: dict) -> NodeResult:
        knn_model = model.get("model")

        if knn_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained KNN model")

        y_pred = knn_model.predict(X_array)
        y_prob = knn_model.predict_proba(X_array)

        mean_max_prob = float(np.mean(y_prob.max(axis=1))) if y_prob.size else 0.0
        return NodeResult(
            outputs={
                "y_pred": y_pred.tolist(),
                "y_prob": y_prob.tolist(),
            },
            diagnostics={
                "method": "knn",
                "n_predicted": int(len(y_pred)),
                "n_classes": int(len(np.unique(y_pred))),
                "mean_max_prob": mean_max_prob,
            },
        )

    # ------------------------------------------------------------------
    # SIMCA prediction
    # ------------------------------------------------------------------
    def _predict_simca(self, X_array: np.ndarray, model: dict) -> NodeResult:
        class_models = model.get("class_models")
        classes = model.get("classes", [])
        T2_limits = model.get("T2_limits", {})
        Q_limits = model.get("Q_limits", {})

        if class_models is None:
            raise ValueError("Model dict does not contain 'class_models' key")
        if not classes:
            raise ValueError("Model dict does not contain 'classes' list")

        n_samples = X_array.shape[0]
        predictions = []
        all_distances = []
        all_accepted_classes: list[list[str]] = []
        all_memberships: list[list[bool]] = []

        for i in range(n_samples):
            sample = X_array[i]
            sample_distances = {}
            sample_accepted: list[str] = []
            sample_membership: list[bool] = []

            for cls in classes:
                cls_str = str(cls)
                class_model = class_models.get(cls_str)

                if class_model is None:
                    raise ValueError(f"Missing model for class '{cls}'")

                loadings = np.array(class_model["loadings"])
                eigenvalues = np.array(class_model["eigenvalues"])

                T2_limit = T2_limits.get(cls_str, T2_limits.get(cls, 1.0))
                Q_limit = Q_limits.get(cls_str, Q_limits.get(cls, 1.0))
                T2_limit = max(float(T2_limit), 1e-10)
                Q_limit = max(float(Q_limit), 1e-10)

                if loadings.ndim == 1:
                    loadings = loadings.reshape(1, -1)

                x_mean = class_model.get("x_mean")
                x_scale = class_model.get("x_scale")
                if x_mean is not None and x_scale is not None:
                    x_mean_np = np.asarray(x_mean, dtype=np.float64)
                    x_scale_np = np.maximum(np.asarray(x_scale, dtype=np.float64), 1e-12)
                    pca_mean = np.asarray(class_model.get("pca_mean", np.zeros_like(x_mean_np)), dtype=np.float64)
                    working_sample = (sample - x_mean_np) / x_scale_np
                    centered_sample = working_sample - pca_mean
                    scores = centered_sample @ loadings.T
                    reconstructed = scores @ loadings + pca_mean
                    residual = working_sample - reconstructed
                else:
                    class_mean = class_model.get("class_mean")
                    if class_mean is None:
                        raise ValueError(
                            f"Class model for '{cls}' is missing scaler state and class_mean. "
                            f"The SIMCA model may be incompatible; please retrain it."
                        )
                    class_mean = np.array(class_mean)
                    centered_sample = sample - class_mean
                    scores = centered_sample @ loadings.T
                    reconstructed = scores @ loadings
                    residual = centered_sample - reconstructed

                n_components = loadings.shape[0]
                eigenvalues = np.maximum(eigenvalues[:n_components], 1e-10)

                T2 = np.sum((scores**2) / eigenvalues)

                Q = np.sum(residual**2)

                distance = (T2 / T2_limit) + (Q / Q_limit)
                sample_distances[cls_str] = distance
                accepted = bool(T2 <= T2_limit and Q <= Q_limit)
                sample_membership.append(accepted)
                if accepted:
                    sample_accepted.append(cls_str)

            if sample_accepted:
                predictions.append(min(sample_accepted, key=lambda k: sample_distances[k]))
            else:
                predictions.append("unassigned")
            all_distances.append(sample_distances)
            all_accepted_classes.append(sample_accepted)
            all_memberships.append(sample_membership)

        logger.debug("Classified %d samples into %d classes", n_samples, len(set(predictions)))

        min_distances: list[float] = []
        for dist_dict in all_distances:
            if dist_dict:
                try:
                    min_distances.append(float(min(dist_dict.values())))
                except Exception:
                    pass
        mean_min_distance = float(np.mean(min_distances)) if min_distances else 0.0
        return NodeResult(
            outputs={
                "y_pred": predictions,
                "y_prob": all_distances,
                "accepted_classes": all_accepted_classes,
                "membership_matrix": all_memberships,
                "n_rejected": int(sum(pred == "unassigned" for pred in predictions)),
            },
            diagnostics={
                "method": "simca",
                "n_predicted": int(len(predictions)),
                "n_classes": int(len(set(predictions))),
                "mean_min_distance": mean_min_distance,
                "n_rejected": int(sum(pred == "unassigned" for pred in predictions)),
            },
        )
