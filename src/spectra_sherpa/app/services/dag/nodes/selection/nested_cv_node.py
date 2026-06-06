"""Leakage-safe Nested Cross-Validation node.

Registered as ``selection.nested_cv``.

Performs variable selection *inside* each CV fold to prevent information
leakage.  For each outer fold:
  1. Select variables on the training set only
  2. Tune the PLS latent-variable count by inner CV on selected training variables
  3. Fit PLS on the selected training variables
  4. Predict the held-out set using only selected variables

Reports honest (unbiased) RMSECV, R², Q² and per-fold selection stability.

This is the correct way to evaluate variable selection in chemometrics —
selecting on full data then cross-validating is optimistically biased.

Reference: Filzmoser et al., J. Chemometrics 23 (2009) 160-171.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold

from ...io_contracts import bind_X, bind_y, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _select_variables_inner(
    X_train: np.ndarray,
    y_train: np.ndarray,
    method: str,
    n_components: int,
    **method_kwargs: Any,
) -> np.ndarray:
    """Run variable selection on training fold only. Returns boolean mask."""
    n_features = X_train.shape[1]

    if method == "vip":
        threshold = method_kwargs.get("vip_threshold", 1.0)
        pls = PLSRegression(n_components=min(n_components, X_train.shape[0] - 1, n_features - 1), scale=False)
        pls.fit(X_train, y_train)
        from ._vip import calculate_vip

        # sklearn: x_weights_ (n_features, n_comp) -> need (n_comp, n_features)
        # sklearn: y_loadings_ (n_targets, n_comp) -> pass as-is
        vip = calculate_vip(
            pls.x_scores_,
            pls.x_weights_.T,
            pls.y_loadings_,
            n_features,
        )
        mask = vip >= threshold
        if np.sum(mask) == 0:
            # Fallback: keep top 10% by VIP
            n_keep = max(1, n_features // 10)
            top_idx = np.argsort(vip)[-n_keep:]
            mask = np.zeros(n_features, dtype=bool)
            mask[top_idx] = True
        return mask

    elif method == "cars":
        from .cars_node import _cars_run

        mask, _, _ = _cars_run(
            X_train,
            y_train,
            n_components,
            cv_folds=min(3, X_train.shape[0]),
            n_iterations=method_kwargs.get("cars_iterations", 30),
        )
        if np.sum(mask) == 0:
            return np.ones(n_features, dtype=bool)
        return mask

    elif method == "uve":
        from .uve_node import _uve_mc

        real_rel, noise_rel = _uve_mc(
            X_train,
            y_train,
            n_components,
            n_resamples=method_kwargs.get("uve_resamples", 30),
            test_fraction=0.2,
        )
        cutoff = np.percentile(noise_rel, method_kwargs.get("uve_cutoff", 90.0))
        mask = real_rel > cutoff
        if np.sum(mask) == 0:
            return np.ones(n_features, dtype=bool)
        return mask

    elif method == "spa":
        from .spa_node import _spa_projections

        n_select = method_kwargs.get("spa_n_select", min(20, n_features))
        X_mc = X_train - X_train.mean(axis=0)
        selected_idx = _spa_projections(X_mc, n_select)
        mask = np.zeros(n_features, dtype=bool)
        mask[selected_idx] = True
        return mask

    elif method == "coef_abs":
        threshold = method_kwargs.get("coef_threshold", 0.01)
        pls = PLSRegression(n_components=min(n_components, X_train.shape[0] - 1, n_features - 1), scale=False)
        pls.fit(X_train, y_train)
        coef = np.abs(pls.coef_.flatten()[:n_features])
        mask = coef >= threshold
        if np.sum(mask) == 0:
            n_keep = max(1, n_features // 10)
            top_idx = np.argsort(coef)[-n_keep:]
            mask = np.zeros(n_features, dtype=bool)
            mask[top_idx] = True
        return mask

    else:
        # No selection — use all variables
        return np.ones(n_features, dtype=bool)


def _choose_pls_components_inner_cv(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    max_components: int,
    inner_folds: int = 3,
) -> int:
    """Choose PLS latent variables by inner CV inside one outer training fold."""
    n_samples, n_features = X_train.shape
    max_valid = max(1, min(int(max_components), n_features, n_samples - 1))
    if max_valid == 1 or n_samples < 4:
        return 1

    n_splits = min(int(inner_folds), n_samples)
    if n_splits < 2:
        return 1

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=17)
    best_components = 1
    best_mse = float("inf")

    for n_comp in range(1, max_valid + 1):
        fold_errors: list[float] = []
        for inner_train_idx, inner_val_idx in kf.split(X_train):
            n_comp_fit = min(n_comp, len(inner_train_idx) - 1, X_train.shape[1])
            if n_comp_fit < 1:
                continue
            pls = PLSRegression(n_components=n_comp_fit, scale=False)
            pls.fit(X_train[inner_train_idx], y_train[inner_train_idx])
            y_hat = pls.predict(X_train[inner_val_idx]).reshape(-1)
            fold_errors.append(float(np.mean((y_train[inner_val_idx] - y_hat) ** 2)))
        if not fold_errors:
            continue
        mse = float(np.mean(fold_errors))
        if mse < best_mse:
            best_mse = mse
            best_components = n_comp

    return int(best_components)


@register_node
class NestedCVNode(Node):
    """Leakage-safe Nested CV — variable selection inside each fold.

    For each outer CV fold:
    1. Select variables on training data only (VIP, CARS, UVE, SPA, or |coef|)
    2. Tune the latent-variable count by inner CV
    3. Fit PLS on selected training variables
    4. Predict held-out samples with selected variables only

    Reports honest RMSECV, R², Q² that are unbiased by selection or LV tuning.
    Also reports per-fold selection stability (Jaccard between folds).
    """

    metadata = NodeMetadata(
        node_type="selection.nested_cv",
        category="selection",
        label="Evaluate Nested CV Selection",
        description="Variable selection inside CV folds — honest, unbiased performance estimates",
        parameters=[
            NodeParameter(
                name="selection_method",
                label="Selection Method",
                param_type="select",
                options=[
                    {"label": "VIP", "value": "vip"},
                    {"label": "|Coefficient|", "value": "coef_abs"},
                    {"label": "CARS", "value": "cars"},
                    {"label": "UVE (MC)", "value": "uve"},
                    {"label": "SPA", "value": "spa"},
                    {"label": "None (full spectrum)", "value": "none"},
                ],
                default="vip",
                description="Variable selection method applied inside each fold",
            ),
            NodeParameter(
                name="n_components",
                label="Max PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                step=1,
                description="Maximum latent variables considered by the inner CV loop",
            ),
            NodeParameter(
                name="cv_folds",
                label="Outer CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                step=1,
                description="Number of outer cross-validation folds",
            ),
            NodeParameter(
                name="vip_threshold",
                label="VIP Threshold",
                param_type="number",
                default=1.0,
                min_value=0.1,
                step=0.1,
                description="VIP threshold (for VIP method)",
                category="advanced",
                visible_when={"selection_method": ["vip"]},
            ),
            NodeParameter(
                name="coef_threshold",
                label="Coefficient Threshold",
                param_type="number",
                default=0.01,
                min_value=0.0,
                step=0.001,
                description="Absolute PLS coefficient threshold (for |Coefficient| method)",
                category="advanced",
                visible_when={"selection_method": ["coef_abs"]},
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset or multivariate feature table",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="cv_metrics",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="CV Metrics",
            ),
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="CV Predictions",
            ),
            PortMetadata(
                name="stability",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Selection Stability",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["rmsecv", "r2_cv", "q2", "mean_n_selected", "selection_stability"],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python code for leakage-safe nested cross-validation."""
        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y", "None")

        params = self._resolve_params()
        selection_method = params.get("selection_method", "vip")
        n_components = int(params.get("n_components", 5))
        cv_folds = int(params.get("cv_folds", 5))
        vip_threshold = float(params.get("vip_threshold", 1.0))
        coef_threshold = float(params.get("coef_threshold", 0.01))

        lines: list[str] = []
        lines.append(f"{indent}# --- Nested CV / Leakage-safe ({self.node_id}) ---")
        lines.append(f"{indent}from sklearn.cross_decomposition import PLSRegression as _PLSRegression")
        lines.append(f"{indent}from sklearn.model_selection import KFold as _KFold")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(
            f"{indent}_X_ncv = np.asarray(_X_input.data if hasattr(_X_input, 'data') else _X_input, dtype=np.float64)"
        )
        lines.append(f"{indent}_X_ncv = np.atleast_2d(_X_ncv)")

        # Target extraction
        lines.append(f"{indent}_y_raw = {y_expr}")
        lines.append(f"{indent}if _y_raw is None and hasattr(_X_input, 'target') and _X_input.target is not None:")
        lines.append(f"{indent}    _y_raw = _X_input.target")
        lines.append(f"{indent}_y_ncv = np.asarray(_y_raw, dtype=np.float64).ravel()")

        lines.append(f"{indent}_n_samples, _n_features = _X_ncv.shape")
        lines.append(f"{indent}_cv_folds = min({cv_folds}, _n_samples)")
        lines.append(f"{indent}_kf = _KFold(n_splits=_cv_folds, shuffle=True, random_state=42)")
        lines.append(f"{indent}_y_pred_all = np.full(_n_samples, np.nan)")
        lines.append(f"{indent}_fold_masks = []")
        lines.append(f"{indent}_fold_n_selected = []")
        lines.append(f"{indent}_fold_n_components = []")
        lines.append("")
        lines.append(f"{indent}for _fold_i, (_train_idx, _test_idx) in enumerate(_kf.split(_X_ncv)):")
        lines.append(f"{indent}    _X_train, _X_test = _X_ncv[_train_idx], _X_ncv[_test_idx]")
        lines.append(f"{indent}    _y_train, _y_test = _y_ncv[_train_idx], _y_ncv[_test_idx]")

        # Variable selection inside fold
        if selection_method == "vip":
            lines.append(f"{indent}    # VIP-based variable selection on training data only")
            lines.append(f"{indent}    _nc = min({n_components}, _X_train.shape[0] - 1, _n_features - 1)")
            lines.append(f"{indent}    _pls_sel = _PLSRegression(n_components=max(_nc, 1), scale=False)")
            lines.append(f"{indent}    _pls_sel.fit(_X_train, _y_train)")
            lines.append(f"{indent}    _W = _pls_sel.x_weights_")
            lines.append(f"{indent}    _T = _pls_sel.x_scores_")
            lines.append(f"{indent}    _Q = _pls_sel.y_loadings_")
            lines.append(f"{indent}    _p = _W.shape[0]")
            lines.append(f"{indent}    _ss = np.sum(_T ** 2, axis=0) * np.sum(_Q ** 2, axis=0)")
            lines.append(
                f"{indent}    _vip = np.sqrt(_p * np.sum("
                f"_ss * (_W / np.linalg.norm(_W, axis=0)) ** 2, axis=1) / np.sum(_ss))"
            )
            lines.append(f"{indent}    _mask = _vip >= {vip_threshold}")
            lines.append(f"{indent}    if np.sum(_mask) == 0:")
            lines.append(f"{indent}        _top_n = max(int(0.1 * _p), 1)")
            lines.append(f"{indent}        _mask = np.zeros(_p, dtype=bool)")
            lines.append(f"{indent}        _mask[np.argsort(_vip)[-_top_n:]] = True")
        elif selection_method == "coef_abs":
            lines.append(f"{indent}    # |Coefficient|-based variable selection on training data only")
            lines.append(f"{indent}    _nc = min({n_components}, _X_train.shape[0] - 1, _n_features - 1)")
            lines.append(f"{indent}    _pls_sel = _PLSRegression(n_components=max(_nc, 1), scale=False)")
            lines.append(f"{indent}    _pls_sel.fit(_X_train, _y_train)")
            lines.append(f"{indent}    _coefs = np.abs(_pls_sel.coef_.ravel())")
            lines.append(f"{indent}    _thresh = {coef_threshold}")
            lines.append(f"{indent}    _mask = _coefs >= _thresh")
            lines.append(f"{indent}    if np.sum(_mask) == 0:")
            lines.append(f"{indent}        _top_n = max(int(0.1 * _n_features), 1)")
            lines.append(f"{indent}        _mask = np.zeros(_n_features, dtype=bool)")
            lines.append(f"{indent}        _mask[np.argsort(_coefs)[-_top_n:]] = True")
        else:
            # "none" or other — use all variables
            lines.append(f"{indent}    # No variable selection — use all variables")
            lines.append(f"{indent}    _mask = np.ones(_n_features, dtype=bool)")

        lines.append(f"{indent}    _fold_masks.append(_mask)")
        lines.append(f"{indent}    _n_sel = int(np.sum(_mask))")
        lines.append(f"{indent}    _fold_n_selected.append(_n_sel)")
        lines.append(f"{indent}    if _n_sel == 0:")
        lines.append(f"{indent}        _mask = np.ones(_n_features, dtype=bool)")
        lines.append(f"{indent}        _n_sel = _n_features")
        lines.append(f"{indent}    _X_train_sel = _X_train[:, _mask]")
        lines.append(f"{indent}    _max_comp = max(1, min({n_components}, _n_sel, len(_train_idx) - 1))")
        lines.append(f"{indent}    _best_comp, _best_mse = 1, float('inf')")
        lines.append(f"{indent}    if len(_train_idx) >= 4 and _max_comp > 1:")
        lines.append(
            f"{indent}        _inner = _KFold(" f"n_splits=min(3, len(_train_idx)), shuffle=True, random_state=17)"
        )
        lines.append(f"{indent}        for _nc_try in range(1, _max_comp + 1):")
        lines.append(f"{indent}            _errs = []")
        lines.append(f"{indent}            for _itr, _ival in _inner.split(_X_train_sel):")
        lines.append(f"{indent}                _nc_inner = min(_nc_try, len(_itr) - 1, _X_train_sel.shape[1])")
        lines.append(f"{indent}                if _nc_inner < 1:")
        lines.append(f"{indent}                    continue")
        lines.append(f"{indent}                _pls_inner = _PLSRegression(n_components=_nc_inner, scale=False)")
        lines.append(f"{indent}                _pls_inner.fit(_X_train_sel[_itr], _y_train[_itr])")
        lines.append(f"{indent}                _pred_inner = _pls_inner.predict(_X_train_sel[_ival]).ravel()")
        lines.append(f"{indent}                _errs.append(float(np.mean((_y_train[_ival] - _pred_inner) ** 2)))")
        lines.append(f"{indent}            if _errs and float(np.mean(_errs)) < _best_mse:")
        lines.append(f"{indent}                _best_mse = float(np.mean(_errs))")
        lines.append(f"{indent}                _best_comp = _nc_try")
        lines.append(f"{indent}    _nc_fit = _best_comp")
        lines.append(f"{indent}    _fold_n_components.append(_nc_fit)")
        lines.append(f"{indent}    _pls_fold = _PLSRegression(n_components=_nc_fit, scale=False)")
        lines.append(f"{indent}    _pls_fold.fit(_X_train_sel, _y_train)")
        lines.append(f"{indent}    _y_pred_all[_test_idx] = _pls_fold.predict(_X_test[:, _mask]).flatten()")
        lines.append("")

        # Compute metrics
        lines.append(f"{indent}_valid = ~np.isnan(_y_pred_all)")
        lines.append(f"{indent}_yt = _y_ncv[_valid]")
        lines.append(f"{indent}_yp = _y_pred_all[_valid]")
        lines.append(f"{indent}_ss_res = float(np.sum((_yt - _yp) ** 2))")
        lines.append(f"{indent}_ss_tot = float(np.sum((_yt - np.mean(_yt)) ** 2))")
        lines.append(f"{indent}_rmsecv = float(np.sqrt(np.mean((_yt - _yp) ** 2)))")
        lines.append(f"{indent}_r2 = 1.0 - _ss_res / max(_ss_tot, 1e-12)")
        lines.append(f"{indent}_q2 = _r2  # Q² = 1 - PRESS/TSS for CV")
        lines.append(f"{indent}_bias = float(np.mean(_yp - _yt))")

        # Stability
        lines.append(f"{indent}_jaccards = []")
        lines.append(f"{indent}for _i in range(len(_fold_masks)):")
        lines.append(f"{indent}    for _j in range(_i + 1, len(_fold_masks)):")
        lines.append(f"{indent}        _inter = np.sum(_fold_masks[_i] & _fold_masks[_j])")
        lines.append(f"{indent}        _union = np.sum(_fold_masks[_i] | _fold_masks[_j])")
        lines.append(f"{indent}        _jaccards.append(float(_inter / max(_union, 1)))")
        lines.append(f"{indent}_mean_jaccard = float(np.mean(_jaccards)) if _jaccards else 1.0")

        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'cv_metrics': {{'rmsecv': _rmsecv, 'r2': _r2, 'q2': _q2, 'bias': _bias,")
        lines.append(
            f"{indent}        'selection_method': {selection_method!r}, 'n_folds': _cv_folds,"
            f" 'component_selection': 'inner_cv', 'per_fold_n_components': _fold_n_components}},"
        )
        lines.append(f"{indent}    'y_pred': _y_pred_all,")
        lines.append(
            f"{indent}    'stability': {{'mean_jaccard': _mean_jaccard,"
            f" 'mean_n_selected': float(np.mean(_fold_n_selected))}},"
        )
        lines.append(f"{indent}}}")
        lines.append(
            f'{indent}print(f"  Nested CV: RMSECV={{_rmsecv:.4f}}, R²={{_r2:.4f}},'
            f' Q²={{_q2:.4f}}, stability={{_mean_jaccard:.3f}}")'
        )

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        selection_method = params.get("selection_method", "vip")
        n_components = int(params.get("n_components", 5))
        cv_folds = int(params.get("cv_folds", 5))
        vip_threshold = float(params.get("vip_threshold", 1.0))

        X_ds = bind_X(X, missing_message="Nested CV requires X", allow_array=True)
        y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
        if y_array.ndim > 1:
            y_array = y_array[:, 0]

        n_samples, n_features = X_array.shape
        cv_folds = min(cv_folds, n_samples)

        kf = KFold(n_splits=cv_folds, shuffle=True, random_state=42)
        y_pred_all = np.full(n_samples, np.nan)

        fold_masks: list[np.ndarray] = []
        fold_n_selected: list[int] = []
        fold_n_components: list[int] = []
        fold_errors: list[float] = []

        method_kwargs = {
            "vip_threshold": vip_threshold,
        }

        for fold_i, (train_idx, test_idx) in enumerate(kf.split(X_array)):
            X_train, X_test = X_array[train_idx], X_array[test_idx]
            y_train, y_test = y_array[train_idx], y_array[test_idx]

            # Step 1: Variable selection on training data ONLY
            mask = _select_variables_inner(X_train, y_train, selection_method, n_components, **method_kwargs)
            fold_masks.append(mask)
            n_sel = int(np.sum(mask))
            fold_n_selected.append(n_sel)

            if n_sel == 0:
                logger.warning(f"Fold {fold_i}: selection eliminated all variables, using full spectrum")
                mask = np.ones(n_features, dtype=bool)
                n_sel = n_features

            # Step 2: Tune PLS latent-variable count by inner CV.
            X_train_sel = X_train[:, mask]
            n_comp = _choose_pls_components_inner_cv(
                X_train_sel,
                y_train,
                max_components=min(n_components, n_sel, len(train_idx) - 1),
                inner_folds=min(3, len(train_idx)),
            )
            if n_comp < 1:
                n_comp = 1
            fold_n_components.append(n_comp)

            try:
                pls = PLSRegression(n_components=n_comp, scale=False)
                pls.fit(X_train_sel, y_train)

                # Step 3: Predict held-out set with SAME selected variables
                y_hat = pls.predict(X_test[:, mask]).flatten()
                y_pred_all[test_idx] = y_hat
                fold_errors.append(float(np.mean((y_test - y_hat) ** 2)))
            except Exception as e:
                logger.warning(f"Fold {fold_i} failed: {e}")
                y_pred_all[test_idx] = np.mean(y_train)
                fold_errors.append(float(np.mean((y_test - np.mean(y_train)) ** 2)))

        # Compute metrics
        valid = ~np.isnan(y_pred_all)
        y_t = y_array[valid]
        y_p = y_pred_all[valid]

        ss_res = float(np.sum((y_t - y_p) ** 2))
        ss_tot = float(np.sum((y_t - np.mean(y_t)) ** 2))
        rmsecv = float(np.sqrt(np.mean((y_t - y_p) ** 2)))
        r2 = 1.0 - ss_res / max(ss_tot, 1e-12)
        q2 = 1.0 - ss_res / max(ss_tot, 1e-12)  # Q² = 1 - PRESS/TSS
        bias = float(np.mean(y_p - y_t))
        sep = float(np.sqrt(np.mean((y_t - y_p - bias) ** 2)))
        y_range = float(np.max(y_t) - np.min(y_t))
        rer = y_range / max(sep, 1e-12)

        # Selection stability: pairwise Jaccard between fold masks
        if len(fold_masks) >= 2:
            jaccards = []
            for i in range(len(fold_masks)):
                for j in range(i + 1, len(fold_masks)):
                    inter = np.sum(fold_masks[i] & fold_masks[j])
                    union = np.sum(fold_masks[i] | fold_masks[j])
                    jaccards.append(float(inter / max(union, 1)) if union > 0 else 0.0)
            mean_jaccard = float(np.mean(jaccards))
        else:
            mean_jaccard = 1.0

        # Per-variable selection frequency across folds
        if fold_masks:
            freq = np.mean(np.stack(fold_masks, axis=0).astype(float), axis=0)
        else:
            freq = np.ones(n_features)

        cv_metrics = {
            "metadata": {"type": "RegressionCV"},
            "rmsecv": rmsecv,
            "r2_cv": r2,
            "r2": r2,
            "q2": q2,
            "bias": bias,
            "sep": sep,
            "rer": rer,
            "n_folds": cv_folds,
            "selection_method": selection_method,
            "component_selection": "inner_cv",
            "per_fold_n_selected": fold_n_selected,
            "per_fold_n_components": fold_n_components,
            "per_fold_mse": fold_errors,
        }

        stability_report = {
            "mean_jaccard": mean_jaccard,
            "per_variable_frequency": freq.tolist(),
            "mean_n_selected": float(np.mean(fold_n_selected)),
            "std_n_selected": float(np.std(fold_n_selected)),
        }

        logger.info(
            f"Nested CV ({selection_method}): RMSECV={rmsecv:.4f}, R²={r2:.4f}, "
            f"Q²={q2:.4f}, stability={mean_jaccard:.3f}, "
            f"mean {np.mean(fold_n_selected):.0f}/{n_features} selected"
        )

        return NodeResult(
            outputs={
                "cv_metrics": cv_metrics,
                "y_pred": y_pred_all,
                "stability": stability_report,
            },
            diagnostics={
                "metadata": {"type": "RegressionCV"},
                "rmsecv": rmsecv,
                "r2_cv": r2,
                "r2": r2,
                "q2": q2,
                "sep": sep,
                "rer": rer,
                "bias": bias,
                "mean_n_selected": float(np.mean(fold_n_selected)),
                "selection_stability": mean_jaccard,
                "selection_method": selection_method,
                "mean_n_components": float(np.mean(fold_n_components)) if fold_n_components else None,
                "component_selection": "inner_cv",
            },
        )
