"""PDS — Piecewise Direct Standardization.

Registered as ``transfer.pds``.

Transfers spectra from a secondary instrument to the response space of
a primary (master) instrument using local multivariate regression in
sliding wavelength windows.

For each wavelength j on the primary instrument, PDS fits a regression
model using a window of neighbouring wavelengths on the secondary:
    x_primary[j] = F_j @ x_secondary[j-w : j+w+1]

The fitted transformation matrices are then applied to new secondary
spectra to produce standardized spectra compatible with the primary
calibration model.

References:
    Wang et al., Analytical Chemistry 63 (1991) 2750-2756.
    Bouveresse & Massart, Vibrational Spectroscopy 11 (1996) 3-8.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _pds_fit(
    X_primary: np.ndarray,
    X_secondary: np.ndarray,
    half_window: int,
    n_components: int,
) -> list[np.ndarray]:
    """Fit PDS transformation matrices.

    Args:
        X_primary: Transfer samples on primary instrument (n_transfer, n_features).
        X_secondary: Same samples on secondary instrument (n_transfer, n_features).
        half_window: Half-width of the local window (full width = 2*half_window + 1).
        n_components: Max PLS/PCA components for local regression (0 = OLS).

    Returns:
        List of n_features transformation vectors/matrices, one per wavelength.
    """
    n_transfer, n_features = X_primary.shape
    transforms: list[np.ndarray] = []

    for j in range(n_features):
        # Window indices on secondary
        lo = max(0, j - half_window)
        hi = min(n_features, j + half_window + 1)
        X_win = X_secondary[:, lo:hi]  # (n_transfer, window_size)

        y_j = X_primary[:, j]  # (n_transfer,)

        window_size = hi - lo

        if n_components > 0 and window_size > 1:
            # PCA-based local regression (regularised)
            n_comp = min(n_components, window_size, n_transfer - 1)
            # Center
            X_mean = X_win.mean(axis=0)
            y_mean = y_j.mean()
            Xc = X_win - X_mean
            yc = y_j - y_mean

            # SVD for pseudo-inverse with truncation
            try:
                U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
                s_inv = np.zeros_like(s)
                s_inv[:n_comp] = 1.0 / np.maximum(s[:n_comp], 1e-12)
                beta = Vt.T @ np.diag(s_inv) @ U.T @ yc
                intercept = y_mean - X_mean @ beta
            except np.linalg.LinAlgError:
                # Fallback: ridge regression
                lam = 1e-6 * np.trace(Xc.T @ Xc) / max(window_size, 1)
                beta = np.linalg.solve(Xc.T @ Xc + lam * np.eye(window_size), Xc.T @ yc)
                intercept = y_mean - X_mean @ beta
        else:
            # OLS with ridge regularization
            X_mean = X_win.mean(axis=0)
            y_mean = y_j.mean()
            Xc = X_win - X_mean
            yc = y_j - y_mean
            lam = 1e-6 * max(np.trace(Xc.T @ Xc) / max(window_size, 1), 1e-12)
            beta = np.linalg.solve(Xc.T @ Xc + lam * np.eye(window_size), Xc.T @ yc)
            intercept = y_mean - X_mean @ beta

        transforms.append(
            {
                "beta": beta,
                "intercept": intercept,
                "lo": lo,
                "hi": hi,
            }
        )

    return transforms


def _pds_transform(
    X_secondary: np.ndarray,
    transforms: list[dict],
) -> np.ndarray:
    """Apply PDS transformation to secondary spectra.

    Args:
        X_secondary: New spectra from secondary instrument (n_samples, n_features).
        transforms: Fitted transformation parameters from _pds_fit.

    Returns:
        Standardized spectra (n_samples, n_features).
    """
    n_samples, n_features = X_secondary.shape
    X_std = np.zeros_like(X_secondary)

    for j, t in enumerate(transforms):
        X_win = X_secondary[:, t["lo"] : t["hi"]]
        X_std[:, j] = X_win @ t["beta"] + t["intercept"]

    return X_std


@register_node
class PDSNode(Node):
    """Piecewise Direct Standardization (PDS).

    Transfers spectra from a secondary instrument to match the primary
    instrument's response using local window regression on paired
    transfer samples.

    Connect paired transfer samples (same physical samples measured on
    both instruments) to fit the transfer function, then apply it to
    new secondary spectra.
    """

    metadata = NodeMetadata(
        node_type="transfer.pds",
        category="preprocessing",
        label="PDS Transfer",
        description="Piecewise Direct Standardization — multi-instrument calibration transfer",
        parameters=[
            NodeParameter(
                name="half_window",
                label="Half Window",
                param_type="number",
                default=3,
                min_value=1,
                step=1,
                description="Half-width of the local regression window (full = 2*w+1 channels)",
            ),
            NodeParameter(
                name="n_components",
                label="Local Components",
                param_type="number",
                default=2,
                min_value=0,
                step=1,
                description="PCA components for local regression (0 = OLS, >0 = PCA-regularised)",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X_primary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Primary Transfer Spectra",
                description="Transfer samples measured on the primary (master) instrument",
            ),
            PortMetadata(
                name="X_secondary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Secondary Transfer Spectra",
                description="Same transfer samples measured on the secondary instrument",
            ),
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Secondary Spectra",
                description="New spectra from secondary instrument to standardize",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_standardized",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Standardized Spectra",
                description="Secondary spectra transformed to primary instrument space",
            ),
            PortMetadata(
                name="transfer_error",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Transfer Diagnostics",
                description="Transfer quality metrics on the paired samples",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["rmse_transfer", "max_error", "half_window", "n_features"],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python code for PDS calibration transfer."""
        X_pri_expr = inputs.get("X_primary", "X_primary")
        X_sec_expr = inputs.get("X_secondary", "X_secondary")
        X_new_expr = inputs.get("X_new", "X_new")

        params = self._resolve_params()
        half_window = int(params.get("half_window", 3))
        n_components = int(params.get("n_components", 2))

        lines: list[str] = []
        lines.append(f"{indent}# --- PDS Calibration Transfer ({self.node_id}) ---")
        lines.append(f"{indent}# Piecewise Direct Standardization (Wang et al., Anal. Chem. 1991)")
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
        lines.append(f"{indent}_half_window = {half_window}")
        lines.append(f"{indent}_n_comp_pds = {n_components}")
        lines.append(f"{indent}_n_feat = _X_pri.shape[1]")
        lines.append("")
        lines.append(f"{indent}# Fit PDS: local regression at each wavelength")
        lines.append(f"{indent}_pds_transforms = []")
        lines.append(f"{indent}for _j in range(_n_feat):")
        lines.append(f"{indent}    _lo = max(0, _j - _half_window)")
        lines.append(f"{indent}    _hi = min(_n_feat, _j + _half_window + 1)")
        lines.append(f"{indent}    _X_win = _X_sec[:, _lo:_hi]")
        lines.append(f"{indent}    _y_j = _X_pri[:, _j]")
        lines.append(f"{indent}    _ws = _hi - _lo")
        lines.append(f"{indent}    _X_mean = _X_win.mean(axis=0)")
        lines.append(f"{indent}    _y_mean = _y_j.mean()")
        lines.append(f"{indent}    _Xc = _X_win - _X_mean")
        lines.append(f"{indent}    _yc = _y_j - _y_mean")
        lines.append(f"{indent}    if _n_comp_pds > 0 and _ws > 1:")
        lines.append(f"{indent}        _nc = min(_n_comp_pds, _ws, _X_sec.shape[0] - 1)")
        lines.append(f"{indent}        try:")
        lines.append(f"{indent}            _U, _s, _Vt = np.linalg.svd(_Xc, full_matrices=False)")
        lines.append(f"{indent}            _s_inv = np.zeros_like(_s)")
        lines.append(f"{indent}            _s_inv[:_nc] = 1.0 / np.maximum(_s[:_nc], 1e-12)")
        lines.append(f"{indent}            _beta = _Vt.T @ np.diag(_s_inv) @ _U.T @ _yc")
        lines.append(f"{indent}        except np.linalg.LinAlgError:")
        lines.append(f"{indent}            _lam = 1e-6 * np.trace(_Xc.T @ _Xc) / max(_ws, 1)")
        lines.append(f"{indent}            _beta = np.linalg.solve(_Xc.T @ _Xc + _lam * np.eye(_ws), _Xc.T @ _yc)")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        _lam = 1e-6 * max(np.trace(_Xc.T @ _Xc) / max(_ws, 1), 1e-12)")
        lines.append(f"{indent}        _beta = np.linalg.solve(_Xc.T @ _Xc + _lam * np.eye(_ws), _Xc.T @ _yc)")
        lines.append(f"{indent}    _intercept = _y_mean - _X_mean @ _beta")
        lines.append(
            f"{indent}    _pds_transforms.append({{'beta': _beta, 'intercept': _intercept, 'lo': _lo, 'hi': _hi}})"
        )
        lines.append("")
        lines.append(f"{indent}# Apply PDS to new secondary spectra")
        lines.append(f"{indent}_X_std = np.zeros_like(_X_new_arr)")
        lines.append(f"{indent}for _j, _t in enumerate(_pds_transforms):")
        lines.append(f"{indent}    _X_std[:, _j] = _X_new_arr[:, _t['lo']:_t['hi']] @ _t['beta'] + _t['intercept']")
        lines.append("")

        # Wrap as SherpaDataset
        lines.append(f"{indent}_fa = getattr({X_new_expr}, 'feature_axis', None)")
        lines.append(f"{indent}_X_std_ds = SherpaDataset(_X_std, feature_axis=_fa)")

        # Transfer diagnostics
        lines.append(f"{indent}_X_sec_std = np.zeros_like(_X_sec)")
        lines.append(f"{indent}for _j, _t in enumerate(_pds_transforms):")
        lines.append(f"{indent}    _X_sec_std[:, _j] = _X_sec[:, _t['lo']:_t['hi']] @ _t['beta'] + _t['intercept']")
        lines.append(f"{indent}_resid = _X_pri - _X_sec_std")
        lines.append(f"{indent}_rmse_transfer = float(np.sqrt(np.mean(_resid ** 2)))")
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_standardized': _X_std_ds,")
        lines.append(
            f"{indent}    'transfer_error': {{'rmse_transfer': _rmse_transfer,"
            f" 'n_features': _n_feat, 'half_window': _half_window}},"
        )
        lines.append(f"{indent}}}")
        lines.append(
            f'{indent}print(f"  PDS Transfer: {{_X_new_arr.shape[0]}} spectra standardized,'
            f' RMSE={{_rmse_transfer:.6f}}")'
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
        half_window = int(params.get("half_window", 3))
        n_components = int(params.get("n_components", 2))

        X_pri_ds = bind_X(
            X_primary, missing_message="PDS requires X_primary (master transfer spectra)", allow_array=True
        )
        X_sec_ds = bind_X(
            X_secondary, missing_message="PDS requires X_secondary (secondary transfer spectra)", allow_array=True
        )
        X_new_ds = bind_X(
            X_new, missing_message="PDS requires X_new (new secondary spectra to standardize)", allow_array=True
        )

        X_pri = to_numpy_2d(X_pri_ds, name="X_primary", dtype=np.float64)
        X_sec = to_numpy_2d(X_sec_ds, name="X_secondary", dtype=np.float64)
        X_new_arr = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        # Validate paired samples
        if X_pri.shape[0] != X_sec.shape[0]:
            raise ValueError(
                f"Transfer samples must be paired: X_primary has {X_pri.shape[0]} samples "
                f"but X_secondary has {X_sec.shape[0]}"
            )
        if X_pri.shape[1] != X_sec.shape[1]:
            raise ValueError(f"Primary and secondary must have same features: " f"{X_pri.shape[1]} vs {X_sec.shape[1]}")
        if X_new_arr.shape[1] != X_sec.shape[1]:
            raise ValueError(
                f"X_new must have same features as secondary: " f"{X_new_arr.shape[1]} vs {X_sec.shape[1]}"
            )

        n_features = X_pri.shape[1]

        # Fit PDS
        transforms = _pds_fit(X_pri, X_sec, half_window, n_components)

        # Apply to transfer samples for diagnostics
        X_sec_std = _pds_transform(X_sec, transforms)
        residuals = X_pri - X_sec_std
        rmse_transfer = float(np.sqrt(np.mean(residuals**2)))
        max_error = float(np.max(np.abs(residuals)))
        per_feature_rmse = np.sqrt(np.mean(residuals**2, axis=0))

        # Apply to new spectra
        X_standardized = _pds_transform(X_new_arr, transforms)
        X_std_ds = build_dataset_like(X_standardized, X_new_ds)

        # Copy feature axis from the new dataset
        fa = getattr(X_new_ds, "feature_axis", None)
        if fa is not None:
            X_std_ds.feature_axis = fa

        add_processing_step(
            X_std_ds,
            "transfer.pds",
            {
                "half_window": half_window,
                "n_components": n_components,
                "n_transfer_samples": X_pri.shape[0],
                "rmse_transfer": rmse_transfer,
            },
            self.node_id,
        )

        transfer_diagnostics = {
            "rmse_transfer": rmse_transfer,
            "max_error": max_error,
            "per_feature_rmse": per_feature_rmse.tolist(),
            "n_transfer_samples": X_pri.shape[0],
            "n_features": n_features,
            "half_window": half_window,
            "window_size": 2 * half_window + 1,
        }

        logger.info(
            f"PDS: {X_new_arr.shape[0]} spectra standardized, "
            f"transfer RMSE={rmse_transfer:.6f}, window={2*half_window+1}"
        )

        return NodeResult(
            outputs={
                "X_standardized": X_std_ds,
                "transfer_error": transfer_diagnostics,
            },
            diagnostics={
                "rmse_transfer": rmse_transfer,
                "max_error": max_error,
                "half_window": half_window,
                "n_features": n_features,
                "n_transfer_samples": X_pri.shape[0],
            },
        )
