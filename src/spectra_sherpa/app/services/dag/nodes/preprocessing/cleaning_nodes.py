"""
Cleaning nodes: CosmicRayRemovalNode, ClipRangeNode, ClipFloorNode, WavenumberAlignNode.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._shared import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    SherpaDataset,
    TransformSpec,
    TransformSpecNode,
    _format_value,
    add_processing_step,
    coerce_to_sherpa,
    copy_processing_history,
    register_node,
)
from ._transforms import _cosmic_ray_export, _cosmic_ray_transform


@register_node
class CosmicRayRemovalNode(TransformSpecNode):
    """
    Cosmic ray removal node.

    Removes spike-like outliers (cosmic rays) from spectral data.
    """

    metadata = NodeMetadata(
        node_type="preprocess.cosmic_ray",
        category="preprocessing",
        label="Cosmic Ray Removal",
        description="Remove spike outliers using local median and MAD statistics",
        parameters=[
            NodeParameter(
                name="window",
                label="Window Size",
                param_type="number",
                default=7,
                min_value=3,
                max_value=31,
                step=2,
                description="Window size for local statistics (must be odd)",
                required=True,
            ),
            NodeParameter(
                name="zscore",
                label="Z-Score Threshold",
                param_type="number",
                default=3.0,
                min_value=1.5,
                max_value=10.0,
                step=0.5,
                description="Z-score threshold for spike detection",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=_cosmic_ray_transform,
        export_lines_fn=_cosmic_ray_export,
        extra_imports=["import numpy as np", "from scipy.ndimage import median_filter"],
    )


@register_node
class ClipRangeNode(Node):
    """
    Wavenumber range clipping node.

    Crops the spectral data to a specified wavenumber range.
    """

    metadata = NodeMetadata(
        node_type="preprocess.clip_range",
        category="preprocessing",
        label="Clip Range",
        description="Crop spectrum to a specified wavenumber range",
        parameters=[
            NodeParameter(
                name="min_wavenumber",
                label="Min Wavenumber (cm\u207b\u00b9)",
                param_type="number",
                default=400,
                min_value=0,
                max_value=10000,
                description="Minimum wavenumber to keep (lower bound)",
                required=False,
            ),
            NodeParameter(
                name="max_wavenumber",
                label="Max Wavenumber (cm\u207b\u00b9)",
                param_type="number",
                default=4000,
                min_value=0,
                max_value=10000,
                description="Maximum wavenumber to keep (upper bound)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        min_wn = params.get("min_wavenumber")
        max_wn = params.get("max_wavenumber")
        lines = [f"{indent}# --- Clip Range ({self.node_id}) ---"]
        if use_scp:
            # SCP coordinate-aware slicing
            lines.append(f"{indent}_clipped = {inp}.copy()")
            if min_wn is not None and max_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, {min_wn}:{max_wn}]")
            elif min_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, {min_wn}:]")
            elif max_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, :{max_wn}]")
            lines.append(f"{indent}results['{self.node_id}'] = _clipped")
        else:
            # numpy path: find column indices from x-axis values
            lines.append(f"{indent}_x = getattr({inp}, 'x', None)")
            lines.append(f"{indent}_x_vals = np.asarray(_x.data) if _x is not None and _x.data is not None else None")
            lines.append(f"{indent}if _x_vals is not None:")
            lines.append(f"{indent}    _mask = np.ones(len(_x_vals), dtype=bool)")
            if min_wn is not None:
                lines.append(f"{indent}    _mask &= _x_vals >= {min_wn}")
            if max_wn is not None:
                lines.append(f"{indent}    _mask &= _x_vals <= {max_wn}")
            lines.append(f"{indent}    _new_data = np.array({inp}.data)[:, _mask]")
            if use_scp:
                lines.append(f"{indent}    results['{self.node_id}'] = scp.NDDataset(_new_data)")
                lines.append(f"{indent}    if hasattr({inp}, 'x') and {inp}.x is not None:")
                lines.append(f"{indent}        results['{self.node_id}'].x = {inp}.x[_mask]")
            else:
                lines.append(f"{indent}    from spectra_sherpa.app.lib.axes import SpectralAxis")
                lines.append(f"{indent}    _clipped_fa = SpectralAxis(values=_x_vals[_mask])")
                lines.append(
                    f"{indent}    results['{self.node_id}'] = SherpaDataset(" f"_new_data, feature_axis=_clipped_fa)"
                )
            lines.append(f"{indent}else:")
            # No axis info — integer column slicing fallback
            lo = int(min_wn) if min_wn is not None else 0
            hi = int(max_wn) if max_wn is not None else None
            hi_str = str(hi) if hi is not None else ""
            lines.append(f"{indent}    _new_data = np.array({inp}.data)[:, {lo}:{hi_str}]")
            if use_scp:
                lines.append(f"{indent}    results['{self.node_id}'] = scp.NDDataset(_new_data)")
            else:
                lines.append(f"{indent}    results['{self.node_id}'] = SherpaDataset(_new_data)")
        return lines

    async def execute(self, input_data: Any) -> Any:
        """Execute wavenumber range clipping."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")

        min_wn = self.parameters.get("min_wavenumber")
        max_wn = self.parameters.get("max_wavenumber")

        input_shape = input_ds.shape

        if min_wn is not None and max_wn is not None and min_wn > max_wn:
            min_wn, max_wn = max_wn, min_wn

        # Clip by x_axis values (wavenumber range)
        result = self._clip_by_index(input_ds, min_wn, max_wn)
        add_processing_step(
            result,
            "preprocess.clip_range",
            {"min_wavenumber": min_wn, "max_wavenumber": max_wn},
            node_id=self.node_id,
            input_shape=input_shape,
        )

        return result

    @staticmethod
    def _clip_by_index(ds: Any, min_wn, max_wn) -> Any:
        """Clip columns by x-axis values (wavenumber range) when available."""
        # SherpaDataset path (canonical)
        if hasattr(ds, "feature_axis"):
            feature_axis = ds.feature_axis
            x_vals = feature_axis.values if feature_axis is not None else None

            if x_vals is None:
                lo = int(min_wn) if min_wn is not None else 0
                hi = int(max_wn) if max_wn is not None else ds.shape[1]
                return ds[:, lo:hi]

            mask = np.ones(len(x_vals), dtype=bool)
            if min_wn is not None:
                mask &= x_vals >= min_wn
            if max_wn is not None:
                mask &= x_vals <= max_wn
            return ds[:, mask]

        # Index-based fallback
        x_vals = None
        if hasattr(ds, "x") and ds.x is not None:
            x_vals = ds.x.data

        if x_vals is None:
            lo = int(min_wn) if min_wn is not None else 0
            hi = int(max_wn) if max_wn is not None else ds.shape[1]
            return ds[:, lo:hi]

        mask = np.ones(len(x_vals), dtype=bool)
        if min_wn is not None:
            mask &= x_vals >= min_wn
        if max_wn is not None:
            mask &= x_vals <= max_wn

        return ds[:, mask]


@register_node
class ClipFloorNode(TransformSpecNode):
    """
    Floor clipping node.

    Clips all values below a specified floor value.
    """

    metadata = NodeMetadata(
        node_type="preprocess.clip_floor",
        category="preprocessing",
        label="Clip Floor",
        description="Clip values below a specified floor (e.g., remove negative values)",
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor Value",
                param_type="number",
                default=0.0,
                min_value=-10.0,
                max_value=10.0,
                step=0.001,
                description="Minimum value; all values below will be set to this",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=lambda data, floor: np.maximum(data, floor),
        numpy_expr="np.maximum(_data, {floor})",
        extra_imports=["import numpy as np"],
    )


@register_node
class WavenumberAlignNode(Node):
    """
    Wavenumber alignment node.

    Aligns multiple spectra to a common wavenumber grid using interpolation.
    """

    metadata = NodeMetadata(
        node_type="preprocess.wavenumber_align",
        category="preprocessing",
        label="Wavenumber Align",
        description="Align spectra to a common wavenumber grid via interpolation",
        parameters=[
            NodeParameter(
                name="method",
                label="Interpolation Method",
                param_type="select",
                default="pchip",
                options=["pchip", "linear", "sinc"],
                description="Interpolation method (pchip: smooth, linear: fast, sinc: spectral)",
                required=True,
            ),
            NodeParameter(
                name="merge_tolerance",
                label="Merge Tolerance (cm\u207b\u00b9)",
                param_type="number",
                default=0.5,
                min_value=0.01,
                max_value=10.0,
                step=0.1,
                description="Tolerance for merging near-duplicate grid points",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from spectra_sherpa.app.lib.preprocessing import build_golden_grid, interpolate_to_grid",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "pchip")
        merge_tol = params.get("merge_tolerance", 0.5)
        lines = [
            f"{indent}# --- Wavenumber Align ({self.node_id}) ---",
            f"{indent}_grid = build_golden_grid([{inp}], merge_tolerance={_format_value(merge_tol)})",
            f"{indent}results['{self.node_id}'] = interpolate_to_grid({inp}, _grid, method='{method}')",
        ]
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute wavenumber alignment via interpolation to a uniform grid."""
        from spectra_sherpa.app.lib.preprocessing import build_golden_grid, interpolate_to_grid

        method = self.parameters.get("method", "pchip")
        merge_tolerance = self.parameters.get("merge_tolerance", 0.5)

        # Build a clean uniform grid from the dataset's own x-axis
        target_grid = build_golden_grid([input_data], merge_tolerance=merge_tolerance)
        result = interpolate_to_grid(input_data, target_grid, method=method)

        copy_processing_history(input_data, result)
        add_processing_step(
            result,
            "preprocess.wavenumber_align",
            {"method": method, "merge_tolerance": merge_tolerance, "n_points": len(target_grid)},
            node_id=self.node_id,
        )

        return result  # type: ignore[no-any-return]
