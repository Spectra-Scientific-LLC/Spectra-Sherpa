"""SBC — Slope/Bias Correction for calibration transfer.

Registered as ``transfer.sbc``.

Global linear correction that maps secondary instrument spectra to the
primary instrument space using a simple per-wavelength slope and bias:

    x_standardized[j] = slope[j] * x_secondary[j] + bias[j]

where slope and bias are estimated from paired transfer samples by
ordinary least squares at each wavelength independently.

SBC is simpler and more robust than PDS when the spectral distortion
between instruments is approximately linear (e.g. intensity scaling,
baseline offset) but less effective for nonlinear or wavelength-shifted
distortions.

Reference: Shenk & Westerhaus, Crop Science 31 (1991) 1694-1696.

Also provides Direct Standardization (DS), which uses a single global
multivariate regression (no windowing), as an intermediate between
SBC and PDS.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _sbc_fit(
    X_primary: np.ndarray,
    X_secondary: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit per-wavelength slope and bias.

    For each wavelength j:
        x_primary[:,j] = slope[j] * x_secondary[:,j] + bias[j]

    Returns:
        (slope, bias) — each of shape (n_features,)
    """
    n_features = X_primary.shape[1]
    slope = np.ones(n_features, dtype=np.float64)
    bias = np.zeros(n_features, dtype=np.float64)

    for j in range(n_features):
        x_s = X_secondary[:, j]
        x_p = X_primary[:, j]

        # OLS: x_p = a * x_s + b
        x_mean = np.mean(x_s)
        y_mean = np.mean(x_p)
        ss_xx = np.sum((x_s - x_mean) ** 2)

        if ss_xx > 1e-12:
            slope[j] = np.sum((x_s - x_mean) * (x_p - y_mean)) / ss_xx
            bias[j] = y_mean - slope[j] * x_mean
        else:
            # Constant signal — just correct the offset
            slope[j] = 1.0
            bias[j] = y_mean - x_mean

    return slope, bias


def _ds_fit(
    X_primary: np.ndarray,
    X_secondary: np.ndarray,
    regularization: float = 1e-6,
) -> np.ndarray:
    """Fit global Direct Standardization transfer matrix.

    X_primary = X_secondary @ F  =>  F = pinv(X_secondary) @ X_primary

    Args:
        X_primary: (n_transfer, n_features)
        X_secondary: (n_transfer, n_features)
        regularization: Ridge parameter for stability.

    Returns:
        F: (n_features, n_features) transfer matrix.
    """
    U, s, Vt = np.linalg.svd(X_secondary, full_matrices=False)
    scale = max(float(np.mean(s**2)) if s.size else 0.0, 1.0)
    lam = max(float(regularization), 0.0) * scale
    shrink = s / (s**2 + lam)
    return (Vt.T * shrink) @ (U.T @ X_primary)


@register_node
class SBCNode(Node):
    """Slope/Bias Correction (SBC) and Direct Standardization (DS).

    Corrects spectral differences between two instruments using either:
    - **SBC**: Per-wavelength linear correction (slope + bias)
    - **DS**: Global multivariate transfer matrix

    SBC is robust for linear intensity/offset differences.
    DS handles cross-channel correlations but needs more transfer samples.

    Connect paired transfer samples from both instruments to fit,
    then apply to new secondary spectra.
    """

    metadata = NodeMetadata(
        node_type="transfer.sbc",
        category="preprocessing",
        label="SBC / DS Transfer",
        description="Slope/Bias Correction or Direct Standardization for instrument transfer",
        parameters=[
            NodeParameter(
                name="method",
                label="Transfer Method",
                param_type="select",
                options=[
                    {"label": "Slope/Bias Correction (SBC)", "value": "sbc"},
                    {"label": "Direct Standardization (DS)", "value": "ds"},
                ],
                default="sbc",
                description="SBC: per-wavelength linear; DS: global multivariate matrix",
            ),
            NodeParameter(
                name="regularization",
                label="Regularization (DS)",
                param_type="number",
                default=1e-4,
                min_value=1e-8,
                step=0.0001,
                description="Ridge regularization for DS (ignored for SBC)",
                category="advanced",
                visible_when={"method": ["ds"]},
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X_primary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Primary Transfer Spectra",
                description="Transfer samples on primary (master) instrument",
            ),
            PortMetadata(
                name="X_secondary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Secondary Transfer Spectra",
                description="Same samples on secondary instrument",
            ),
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Secondary Spectra",
                description="New secondary spectra to standardize",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_standardized",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Standardized Spectra",
            ),
            PortMetadata(
                name="transfer_error",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Transfer Diagnostics",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["rmse_transfer", "method", "n_features"],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python code for SBC/DS calibration transfer."""
        X_pri_expr = inputs.get("X_primary", "X_primary")
        X_sec_expr = inputs.get("X_secondary", "X_secondary")
        X_new_expr = inputs.get("X_new", "X_new")

        params = self._resolve_params()
        method = params.get("method", "sbc")
        regularization = float(params.get("regularization", 1e-4))

        lines: list[str] = []
        lines.append(f"{indent}# --- SBC/DS Calibration Transfer ({self.node_id}) ---")
        lines.append(
            f"{indent}_X_pri = np.asarray("
            f"{X_pri_expr}.data if hasattr({X_pri_expr}, 'data') else {X_pri_expr}, dtype=np.float64)"
        )
        lines.append(
            f"{indent}_X_sec = np.asarray("
            f"{X_sec_expr}.data if hasattr({X_sec_expr}, 'data') else {X_sec_expr}, dtype=np.float64)"
        )
        lines.append(
            f"{indent}_X_new_arr = np.asarray("
            f"{X_new_expr}.data if hasattr({X_new_expr}, 'data') else {X_new_expr}, dtype=np.float64)"
        )
        lines.append(f"{indent}_X_pri = np.atleast_2d(_X_pri)")
        lines.append(f"{indent}_X_sec = np.atleast_2d(_X_sec)")
        lines.append(f"{indent}_X_new_arr = np.atleast_2d(_X_new_arr)")

        if method == "sbc":
            lines.append(f"{indent}# SBC: per-wavelength slope/bias correction")
            lines.append(f"{indent}_n_feat = _X_pri.shape[1]")
            lines.append(f"{indent}_slope = np.ones(_n_feat)")
            lines.append(f"{indent}_bias_sbc = np.zeros(_n_feat)")
            lines.append(f"{indent}for _j in range(_n_feat):")
            lines.append(f"{indent}    _xs = _X_sec[:, _j]; _xp = _X_pri[:, _j]")
            lines.append(f"{indent}    _xm = np.mean(_xs); _ym = np.mean(_xp)")
            lines.append(f"{indent}    _ssxx = np.sum((_xs - _xm) ** 2)")
            lines.append(f"{indent}    if _ssxx > 1e-12:")
            lines.append(f"{indent}        _slope[_j] = np.sum((_xs - _xm) * (_xp - _ym)) / _ssxx")
            lines.append(f"{indent}        _bias_sbc[_j] = _ym - _slope[_j] * _xm")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        _slope[_j] = 1.0; _bias_sbc[_j] = _ym - _xm")
            lines.append(f"{indent}_X_standardized = _X_new_arr * _slope[np.newaxis, :] + _bias_sbc[np.newaxis, :]")
            lines.append(f"{indent}_X_sec_std = _X_sec * _slope[np.newaxis, :] + _bias_sbc[np.newaxis, :]")
        else:
            lines.append(f"{indent}# DS: global multivariate transfer matrix")
            lines.append(f"{indent}_U, _s, _Vt = np.linalg.svd(_X_sec, full_matrices=False)")
            lines.append(f"{indent}_scale = max(float(np.mean(_s ** 2)) if _s.size else 0.0, 1.0)")
            lines.append(f"{indent}_lam = max({regularization}, 0.0) * _scale")
            lines.append(f"{indent}_shrink = _s / (_s ** 2 + _lam)")
            lines.append(f"{indent}_F = (_Vt.T * _shrink) @ (_U.T @ _X_pri)")
            lines.append(f"{indent}_X_standardized = _X_new_arr @ _F")
            lines.append(f"{indent}_X_sec_std = _X_sec @ _F")

        lines.append(f"{indent}_resid = _X_pri - _X_sec_std")
        lines.append(f"{indent}_rmse_transfer = float(np.sqrt(np.mean(_resid ** 2)))")

        # Wrap as SherpaDataset
        lines.append(f"{indent}_fa = getattr({X_new_expr}, 'feature_axis', None)")
        lines.append(f"{indent}_X_std_ds = SherpaDataset(_X_standardized, feature_axis=_fa)")

        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_standardized': _X_std_ds,")
        lines.append(f"{indent}    'transfer_error': {{'rmse_transfer': _rmse_transfer, 'method': {method!r}}},")
        lines.append(f"{indent}}}")
        lines.append(
            f'{indent}print(f"  {method.upper()} Transfer:'
            f' {{_X_new_arr.shape[0]}} spectra, RMSE={{_rmse_transfer:.6f}}")'
        )

        return lines

    async def execute(
        self,
        X_primary: Any = None,
        X_secondary: Any = None,
        X_new: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        params = self._resolve_params()
        method = params.get("method", "sbc")
        regularization = float(params.get("regularization", 1e-4))

        X_pri_ds = bind_X(X_primary, missing_message="SBC requires X_primary", allow_array=True)
        X_sec_ds = bind_X(X_secondary, missing_message="SBC requires X_secondary", allow_array=True)
        X_new_ds = bind_X(X_new, missing_message="SBC requires X_new", allow_array=True)

        X_pri = to_numpy_2d(X_pri_ds, name="X_primary", dtype=np.float64)
        X_sec = to_numpy_2d(X_sec_ds, name="X_secondary", dtype=np.float64)
        X_new_arr = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        # Validate
        if X_pri.shape[0] != X_sec.shape[0]:
            raise ValueError(f"Transfer samples must be paired: {X_pri.shape[0]} vs {X_sec.shape[0]}")
        if X_pri.shape[1] != X_sec.shape[1]:
            raise ValueError(f"Feature count mismatch: primary={X_pri.shape[1]}, secondary={X_sec.shape[1]}")
        if X_new_arr.shape[1] != X_sec.shape[1]:
            raise ValueError(f"X_new features ({X_new_arr.shape[1]}) must match secondary ({X_sec.shape[1]})")

        n_features = X_pri.shape[1]

        if method == "sbc":
            slope, bias = _sbc_fit(X_pri, X_sec)
            # Apply to transfer samples (diagnostics)
            X_sec_std = X_sec * slope[np.newaxis, :] + bias[np.newaxis, :]
            # Apply to new spectra
            X_standardized = X_new_arr * slope[np.newaxis, :] + bias[np.newaxis, :]

            method_info = {
                "slope_range": [float(slope.min()), float(slope.max())],
                "bias_range": [float(bias.min()), float(bias.max())],
                "mean_slope": float(np.mean(slope)),
                "mean_bias": float(np.mean(bias)),
            }
        else:
            # Direct Standardization
            F = _ds_fit(X_pri, X_sec, regularization)
            X_sec_std = X_sec @ F
            X_standardized = X_new_arr @ F
            method_info = {
                "matrix_condition": float(np.linalg.cond(F)),
                "regularization": regularization,
            }

        # Transfer quality on paired samples
        residuals = X_pri - X_sec_std
        rmse_transfer = float(np.sqrt(np.mean(residuals**2)))
        max_error = float(np.max(np.abs(residuals)))
        per_feature_rmse = np.sqrt(np.mean(residuals**2, axis=0))

        # Build output
        X_std_ds = build_dataset_like(X_standardized, X_new_ds)
        fa = getattr(X_new_ds, "feature_axis", None)
        if fa is not None:
            X_std_ds.feature_axis = fa

        add_processing_step(
            X_std_ds,
            f"transfer.{method}",
            {
                "method": method,
                "n_transfer_samples": X_pri.shape[0],
                "rmse_transfer": rmse_transfer,
            },
            self.node_id,
        )

        transfer_diagnostics = {
            "method": method,
            "rmse_transfer": rmse_transfer,
            "max_error": max_error,
            "per_feature_rmse": per_feature_rmse.tolist(),
            "n_transfer_samples": X_pri.shape[0],
            "n_features": n_features,
            **method_info,
        }

        logger.info(
            f"{method.upper()}: {X_new_arr.shape[0]} spectra standardized, " f"transfer RMSE={rmse_transfer:.6f}"
        )

        return NodeResult(
            outputs={
                "X_standardized": X_std_ds,
                "transfer_error": transfer_diagnostics,
            },
            diagnostics={
                "rmse_transfer": rmse_transfer,
                "max_error": max_error,
                "method": method,
                "n_features": n_features,
                "n_transfer_samples": X_pri.shape[0],
            },
        )
