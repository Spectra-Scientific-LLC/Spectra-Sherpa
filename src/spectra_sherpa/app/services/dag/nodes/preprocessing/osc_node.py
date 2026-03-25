"""
Orthogonal Signal Correction (OSC) node.
"""

from __future__ import annotations

import numpy as np

from ._shared import (
    EFFECT_SCATTER_CORRECTED,
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    SherpaDataset,
    _format_value,
    add_processing_step,
    bind_X,
    bind_y,
    build_dataset_like,
    register_node,
    scp,
    to_numpy_1d,
    to_numpy_2d,
)


@register_node
class OSCNode(Node):
    """
    Orthogonal Signal Correction (OSC) node.

    Removes systematic variation in X that is orthogonal to Y.
    """

    metadata = NodeMetadata(
        node_type="preprocess.osc",
        category="preprocessing",
        label="OSC Filter",
        description="Orthogonal Signal Correction - remove variation uncorrelated with Y",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of OSC Components",
                param_type="number",
                default=1,
                min_value=1,
                max_value=10,
                step=1,
                description="Number of orthogonal components to remove",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-6,
                min_value=1e-10,
                max_value=1e-3,
                step=1e-7,
                description="Tolerance for convergence",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                step=10,
                description="Maximum iterations per component",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix to correct",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target (y)",
                description="Target values \u2014 optional if dataset has embedded target",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html",
    )

    python_extra_imports = [
        "import numpy as np",
        "import spectrochempy as scp",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        x_expr = inputs.get("X", "X")
        y_expr = inputs.get("y", "y")
        params = self._resolve_params()
        n_comp = params.get("n_components", 1)
        tol = params.get("tol", 1e-6)
        max_iter = params.get("max_iter", 100)
        return [
            f"{indent}# --- OSC Filter ({self.node_id}) ---",
            f"{indent}_X = np.array({x_expr}.data)",
            f"{indent}_y = np.array({y_expr}).reshape(-1, 1) if np.array({y_expr}).ndim == 1 else np.array({y_expr})",
            f"{indent}_X_osc = _X.copy()",
            f"{indent}for _comp in range({n_comp}):",
            f"{indent}    _Xd = scp.NDDataset(_X_osc)",
            f"{indent}    _yd = scp.NDDataset(_y)",
            f"{indent}    _pls = scp.PLSRegression(n_components=1, scale=False)",
            f"{indent}    _pls.fit(_Xd, _yd)",
            f"{indent}    _t = np.array(_pls.x_scores_)",
            f"{indent}    _w = np.array(_pls.x_weights_)",
            f"{indent}    for _ in range({max_iter}):",
            f"{indent}        _wosc = _X_osc.T @ (_X_osc @ _t.flatten())",
            f"{indent}        _wosc = _wosc.reshape(-1, 1)",
            f"{indent}        _wosc = _wosc - (_wosc.T @ _w) * _w",
            f"{indent}        _n = np.linalg.norm(_wosc)",
            f"{indent}        if _n < 1e-10: break",
            f"{indent}        _wosc = _wosc / _n",
            f"{indent}        _t_new = _X_osc @ _wosc",
            f"{indent}        if np.linalg.norm(_t_new - _t) < {_format_value(tol)}: break",
            f"{indent}        _t = _t_new",
            f"{indent}    _p = (_X_osc.T @ _t) / (_t.T @ _t)",
            f"{indent}    _X_osc = _X_osc - _t @ _p.T",
            f"{indent}results['{self.node_id}'] = scp.NDDataset(_X_osc)",
            f"{indent}if hasattr({x_expr}, 'x') and {x_expr}.x is not None:",
            f"{indent}    results['{self.node_id}'].x = {x_expr}.x.copy()",
        ]

    async def execute(self, X=None, y=None, **kwargs) -> SherpaDataset:
        """Execute OSC filtering."""
        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be a dataset object",
            allow_array=True,
        )
        y_value = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            dataset_as_data=True,
            missing_message=(
                "No target values found. Either:\n"
                "  1. Use a data source with embedded targets (e.g., Corn M5, sklearn)\n"
                "  2. Connect target values to the 'y' input port\n"
                "  3. Use 'Attach Target' node to add targets to your dataset"
            ),
        )

        n_components = self.parameters.get("n_components", 1)
        tol = self.parameters.get("tol", 1e-6)
        max_iter = self.parameters.get("max_iter", 100)

        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_data = to_numpy_1d(
            y_value,
            name="y",
            expected_length=X_data.shape[0],
            dtype=np.float64,
        ).reshape(-1, 1)
        y_dataset = scp.NDDataset(y_data)

        X_osc = X_data.copy()
        variance_removed_per_comp = []
        OSC_NORM_THRESHOLD = 1e-10

        for comp in range(n_components):
            X_osc_dataset = scp.NDDataset(X_osc)
            pls = scp.PLSRegression(n_components=1, scale=False)
            pls.fit(X_osc_dataset, y_dataset)

            t_pred = np.array(pls.x_scores_)
            x_weights = np.array(pls.x_weights_)

            t_osc_old = None

            for iteration in range(max_iter):
                w_osc = X_osc.T @ (X_osc @ t_pred.flatten())
                w_osc = w_osc.reshape(-1, 1)

                w_osc_initial_norm = np.linalg.norm(w_osc)
                if w_osc_initial_norm < OSC_NORM_THRESHOLD:
                    break

                x_weights_norm = np.linalg.norm(x_weights)
                if x_weights_norm > OSC_NORM_THRESHOLD:
                    projection = (w_osc.T @ x_weights) * x_weights
                    w_osc = w_osc - projection

                w_osc_norm = np.linalg.norm(w_osc)
                if w_osc_norm < OSC_NORM_THRESHOLD:
                    break
                w_osc = w_osc / w_osc_norm

                t_osc = X_osc @ w_osc

                if t_osc_old is not None and np.linalg.norm(t_osc - t_osc_old) < tol:
                    break
                t_osc_old = t_osc.copy()

            t_osc_norm_sq = t_osc.T @ t_osc
            if t_osc_norm_sq < OSC_NORM_THRESHOLD:
                continue
            p_osc = (X_osc.T @ t_osc) / t_osc_norm_sq

            var_before = np.var(X_osc)
            X_osc = X_osc - t_osc @ p_osc.T
            var_after = np.var(X_osc)
            var_removed = 100 * (1 - var_after / var_before) if var_before > 0 else 0
            variance_removed_per_comp.append(var_removed)

        total_var_original = np.var(X_data)
        total_var_corrected = np.var(X_osc)
        total_variance_removed = 100 * (1 - total_var_corrected / total_var_original) if total_var_original > 0 else 0

        result = build_dataset_like(X_osc, X_ds)
        add_processing_step(
            result,
            "preprocess.osc",
            {
                "n_components": n_components,
                "tol": tol,
                "max_iter": max_iter,
                "variance_removed_percent": total_variance_removed,
            },
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )

        return result
