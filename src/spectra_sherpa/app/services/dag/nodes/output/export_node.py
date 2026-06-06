"""
Export node for saving results.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node


@register_node
class ExportNode(Node):
    """
    Export node for saving results.

    Exports data to various file formats.
    """

    metadata = NodeMetadata(
        node_type="output.export",
        category="output",
        label="Export",
        description="Export data to file",
        parameters=[
            NodeParameter(
                name="filename",
                label="Filename",
                param_type="text",
                default="output.csv",
                description="Output filename",
                required=True,
            ),
            NodeParameter(
                name="format",
                label="Format",
                param_type="select",
                default="csv",
                options=["csv", "json", "jdx"],
                description="Output file format",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="file_info",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="File Info",
                description="Status and path of exported file",
            ),
        ],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="full_data",
        ),
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate Python code for data export."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        filename = self.parameters.get("filename", "output.csv")
        fmt = self.parameters.get("format", "csv")

        lines: List[str] = []
        lines.append(f"{indent}# --- Export ({self.node_id}) ---")
        lines.append(f"{indent}_export_input = {input_expr}")
        lines.append(f"{indent}if hasattr(_export_input, 'data'):")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input.data)")
        lines.append(f"{indent}elif isinstance(_export_input, dict) and 'data' in _export_input:")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input['data'])")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input)")
        lines.append(f"{indent}if _export_data.ndim == 0:")
        lines.append(f"{indent}    _export_data = _export_data.reshape(1, 1)")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _export_data = np.atleast_2d(_export_data)")
        lines.append(f"{indent}_export_is_numeric = (")
        lines.append(f"{indent}    np.issubdtype(_export_data.dtype, np.number)")
        lines.append(f"{indent}    or np.issubdtype(_export_data.dtype, np.bool_)")
        lines.append(f"{indent})")

        # Write next to the script (DATA_DIR sibling) so export_artifacts()
        # can pick it up later.  os is already imported at script level.
        lines.append(f"{indent}_export_path = os.path.join(")
        lines.append(f"{indent}    os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd(),")
        lines.append(f"{indent}    {repr(filename)},")
        lines.append(f"{indent})")
        if fmt == "csv":
            lines.append(f"{indent}if _export_is_numeric:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data, delimiter=',')")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data.astype(str), delimiter=',', fmt='%s')")
        elif fmt == "json":
            lines.append(f"{indent}import json as _json")
            lines.append(f"{indent}with open(_export_path, 'w') as _f:")
            lines.append(f"{indent}    _json.dump(_export_data.tolist(), _f)")
        elif fmt == "jdx":
            lines.append(f"{indent}# JCAMP-DX export")
            lines.append(f"{indent}with open(_export_path, 'w') as _f:")
            lines.append(f"{indent}    _f.write('##TITLE=SpectraSherpa Export\\n')")
            lines.append(f"{indent}    _f.write('##JCAMP-DX=5.00\\n')")
            lines.append(f"{indent}    _f.write('##DATA TYPE=INFRARED SPECTRUM\\n')")
            lines.append(f"{indent}    _n = _export_data.shape[-1] if _export_data.ndim > 1 else len(_export_data)")
            lines.append(f"{indent}    _f.write(f'##NPOINTS={{_n}}\\n')")
            lines.append(f"{indent}    _f.write('##XYDATA=(X++(Y..Y))\\n')")
            lines.append(f"{indent}    _row = _export_data[0] if _export_data.ndim > 1 else _export_data")
            lines.append(f"{indent}    for _i, _v in enumerate(_row):")
            lines.append(f"{indent}        _f.write(f'{{_i}} {{_v:.6g}}\\n')")
            lines.append(f"{indent}    _f.write('##END=\\n')")
        else:
            # Unknown format fallback to CSV
            lines.append(f"{indent}if _export_is_numeric:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data, delimiter=',')")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data.astype(str), delimiter=',', fmt='%s')")

        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'file_info': {{")
        lines.append(f"{indent}        'filename': {repr(filename)},")
        lines.append(f"{indent}        'format': {repr(fmt)},")
        lines.append(f"{indent}        'data_points': int(np.prod(_export_data.shape)),")
        lines.append(f"{indent}    }}")
        lines.append(f"{indent}}}")
        lines.append(f'{indent}print(f"  Export: saved {{_export_data.shape}} to {{_export_path}}")')

        return lines

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Export data to file.

        Args:
            input_data: Data to export

        Returns:
            Dict with export status and path
        """
        filename = self.parameters.get("filename", "output.csv")
        fmt = self.parameters.get("format", "csv")

        # For now, just return metadata about what would be exported
        # Actual file writing would happen here in production

        # Coerce NDDataset -> SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        if isinstance(input_data, SherpaDataset):
            shape = input_data.shape
            n_points = np.prod(shape)
        elif isinstance(input_data, dict):
            payload = None
            if isinstance(input_data.get("default"), SherpaDataset):
                payload = input_data["default"].data
            for key in (
                "data",
                "scores",
                "X_scores",
                "transformed",
                "result",
                "predictions",
                "labels",
                "cluster_assignment",
                "y_pred",
                "probabilities",
                "class_probabilities",
                "distances",
                "neighbor_indices",
                "class_distance_matrix",
            ):
                if payload is None and key in input_data and input_data[key] is not None:
                    payload = input_data[key]
                    break
            if payload is not None:
                if isinstance(payload, SherpaDataset):
                    n_points = int(np.prod(payload.shape))
                else:
                    n_points = int(np.asarray(payload, dtype=object).size)
            else:
                n_points = len(input_data)
        elif isinstance(input_data, (list, tuple, np.ndarray)):
            n_points = int(np.asarray(input_data, dtype=object).size)
        else:
            n_points = 0

        return {
            "file_info": {
                "status": "ready",
                "filename": filename,
                "format": fmt,
                "data_points": int(n_points),
                "message": f"Ready to export {n_points} data points to {filename}",
            }
        }
