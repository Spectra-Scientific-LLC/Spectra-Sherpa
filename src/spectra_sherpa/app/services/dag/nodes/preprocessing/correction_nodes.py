"""
Correction nodes: EMSCNode (and autoscale helpers).
"""

from __future__ import annotations

import numpy as np

from ._shared import (
    EFFECT_SCATTER_CORRECTED,
    HAS_SCP,
    NDDataset,
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    SherpaDataset,
    _wrap_result_lines,
    add_processing_step,
    bind_X,
    build_dataset_like,
    register_node,
    to_numpy_2d,
)


@register_node
class EMSCNode(Node):
    """
    Extended Multiplicative Signal Correction (EMSC) node.

    Extends MSC by adding polynomial baseline correction and optional
    constituent spectra (interferents) to the design matrix.

    Design matrix: [reference | poly_1 .. poly_d | constituent_1 .. constituent_k]
    """

    metadata = NodeMetadata(
        node_type="preprocess.emsc",
        category="preprocessing",
        label="EMSC",
        description="Extended MSC with polynomial baseline and optional constituent spectra",
        parameters=[
            NodeParameter(
                name="reference",
                label="Reference Spectrum",
                param_type="select",
                default="mean",
                options=["mean", "median", "first"],
                description="Reference spectrum for EMSC",
                required=False,
            ),
            NodeParameter(
                name="poly_order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=0,
                max_value=5,
                step=1,
                description="Order of polynomial baseline (0=no baseline correction)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to correct",
            ),
            PortMetadata(
                name="constituents",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Constituent Spectra",
                description="Known interferent/constituent spectra (rows = constituents, cols = wavenumbers)",
            ),
        ],
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = inputs.get("default", next(iter(inputs.values()))) if inputs else "input_data"
        const_inp = inputs.get("constituents")
        params = self._resolve_params()
        ref = params.get("reference", "mean")
        poly = params.get("poly_order", 2)
        lines = [
            f"{indent}# --- EMSC ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}_n, _p = _data.shape",
        ]
        if ref == "mean":
            lines.append(f"{indent}_ref = np.mean(_data, axis=0)")
        elif ref == "median":
            lines.append(f"{indent}_ref = np.median(_data, axis=0)")
        else:
            lines.append(f"{indent}_ref = _data[0]")
        # Design matrix: [poly_terms (incl. constant) | reference | constituents]
        lines += [
            f"{indent}_x = np.arange(_p, dtype=np.float64)",
            f"{indent}_xn = (_x - _x.mean()) / _x.std() if _p > 1 else _x",
            f"{indent}_design = [_xn ** _d for _d in range({poly} + 1)]",
            f"{indent}_ref_col = len(_design)",
            f"{indent}_design.append(_ref)",
        ]
        if const_inp:
            lines += [
                f"{indent}_const = np.array({const_inp}.data, dtype=np.float64)",
                f"{indent}if _const.ndim == 1: _const = _const.reshape(1, -1)",
                f"{indent}for _k in range(_const.shape[0]):",
                f"{indent}    _design.append(_const[_k])",
            ]
        lines += [
            f"{indent}_design = np.column_stack(_design)",
            f"{indent}_bl_cols = [_j for _j in range(_design.shape[1]) if _j != _ref_col]",
            f"{indent}_corrected = np.zeros_like(_data)",
            f"{indent}for _i in range(_n):",
            f"{indent}    _c, _, _, _ = np.linalg.lstsq(_design, _data[_i], rcond=None)",
            f"{indent}    _bl = _design[:, _bl_cols] @ _c[_bl_cols] if _bl_cols else 0",
            f"{indent}    _corrected[_i] = (_data[_i] - _bl) / _c[_ref_col] if abs(_c[_ref_col]) > 1e-8 else _data[_i]",
        ]
        lines += _wrap_result_lines(self.node_id, "_corrected", inp, indent, use_scp)
        return lines

    async def execute(self, input_data=None, constituents=None, **kwargs) -> SherpaDataset:
        """Execute EMSC correction with optional constituent spectra."""
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectra)",
            dataset_error_message="input_data must be a dataset object",
            allow_array=True,
        )
        reference_type = self.parameters.get("reference", "mean")
        poly_order = self.parameters.get("poly_order", 2)

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        n_samples, n_features = data.shape

        if reference_type == "mean":
            reference = np.mean(data, axis=0)
        elif reference_type == "median":
            reference = np.median(data, axis=0)
        elif reference_type == "first":
            reference = data[0]
        else:
            reference = np.mean(data, axis=0)

        # Build design matrix: [poly_terms (incl. constant) | reference | constituents]
        # Column order: [1, x, x^2, ..., x^d, reference, constituent_1, ...]
        # The reference coefficient is at index poly_order+1 (last non-constituent).
        X_design: list[np.ndarray] = []
        x_axis = np.arange(n_features, dtype=np.float64)
        x_norm = (x_axis - x_axis.mean()) / x_axis.std() if n_features > 1 else x_axis
        for deg in range(poly_order + 1):
            X_design.append(x_norm**deg)
        ref_col_idx = len(X_design)  # index of the reference column
        X_design.append(reference)

        n_constituents = 0
        if constituents is not None:
            if isinstance(constituents, SherpaDataset):
                const_data = np.asarray(constituents.data, dtype=np.float64)
            elif HAS_SCP and isinstance(constituents, NDDataset):
                const_data = np.asarray(constituents.data, dtype=np.float64)
            else:
                const_data = np.asarray(constituents, dtype=np.float64)
            if const_data.ndim == 1:
                const_data = const_data.reshape(1, -1)
            elif const_data.ndim != 2:
                raise ValueError("constituents must be 1D or 2D array-like")
            n_constituents = const_data.shape[0]
            for k in range(n_constituents):
                X_design.append(const_data[k])

        X_design_arr: np.ndarray = np.column_stack(X_design)
        corrected_data = np.zeros_like(data)
        EMSC_COEF_THRESHOLD = 1e-8

        # Mask for non-reference columns (polynomial + constituent terms = baseline)
        n_cols = X_design_arr.shape[1]
        baseline_cols = [j for j in range(n_cols) if j != ref_col_idx]

        for i in range(n_samples):
            spectrum = data[i]
            coef, _, _, _ = np.linalg.lstsq(X_design_arr, spectrum, rcond=None)

            # Baseline = polynomial + constituent contributions (everything except reference)
            if baseline_cols:
                baseline = X_design_arr[:, baseline_cols] @ coef[baseline_cols]
                if np.abs(coef[ref_col_idx]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = (spectrum - baseline) / coef[ref_col_idx]
                else:
                    corrected_data[i] = spectrum
            else:
                if np.abs(coef[ref_col_idx]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = spectrum / coef[ref_col_idx]
                else:
                    corrected_data[i] = spectrum

        result = build_dataset_like(corrected_data, input_ds)
        add_processing_step(
            result,
            "preprocess.emsc",
            {"reference": reference_type, "poly_order": poly_order, "n_constituents": n_constituents},
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )

        return result
