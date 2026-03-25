"""
Data Table visualization node.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node


@register_node
class DataTableNode(Node):
    """
    Data Table visualization node.

    Displays tabular data with interactive features like sorting, filtering,
    and column selection. Useful for inspecting numerical results, model outputs,
    and statistical summaries.
    """

    metadata = NodeMetadata(
        node_type="output.data_table",
        category="output",
        label="Data Table",
        description="Display data in an interactive table with sorting and filtering",
        parameters=[
            NodeParameter(
                name="max_rows",
                label="Max Rows",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                step=10,
                description="Maximum number of rows to display",
                required=False,
            ),
            NodeParameter(
                name="transpose",
                label="Transpose",
                param_type="boolean",
                default=False,
                description="Swap rows and columns",
                required=False,
            ),
            NodeParameter(
                name="show_index",
                label="Show Index",
                param_type="boolean",
                default=True,
                description="Display row indices",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict", "array"],
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
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Table Data",
                description="Table configuration and data",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Convert input data to table format.

        Args:
            input_data: Data to display in table (SherpaDataset, dict, or array)

        Returns:
            Dict with table data (columns, rows) and metadata
        """
        max_rows = self.parameters.get("max_rows", 100)
        transpose = self.parameters.get("transpose", False)
        show_index = self.parameters.get("show_index", True)

        # Coerce NDDataset -> SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        # Convert input to table format
        if isinstance(input_data, SherpaDataset):
            table_data = self._table_from_dataset(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, dict):
            table_data = self._table_from_dict(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, (list, np.ndarray)):
            table_data = self._table_from_array(input_data, max_rows, transpose, show_index)
        else:
            table_data = {
                "columns": [],
                "rows": [],
                "metadata": {"type": "empty", "message": "No data to display"},
            }

        return {"visualization": table_data}

    def _table_from_dataset(self, dataset: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert SherpaDataset to table format."""
        data = np.array(dataset.data)

        # Handle 1D data
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        n_rows, n_cols = data.shape

        # Apply max_rows limit
        if n_rows > max_rows:
            data = data[:max_rows]
            truncated = True
        else:
            truncated = False

        # Transpose if requested
        if transpose:
            data = data.T
            n_rows, n_cols = n_cols, n_rows

        # Build column headers
        x_coord = dataset.feature_axis
        if x_coord is not None and not transpose:
            # Use feature axis values (wavenumber/time/m/z/etc.) as column headers
            x_vals = np.array(x_coord.data)
            if len(x_vals) == n_cols:
                columns = [f"{float(x):.2f}" for x in x_vals[:n_cols]]
            else:
                columns = [f"Col_{i+1}" for i in range(n_cols)]
        else:
            columns = [f"Col_{i+1}" for i in range(n_cols)]

        # Build rows
        rows = []
        for i in range(n_rows):
            row_data = data[i].tolist()
            rows.append({"index": i, "values": row_data} if show_index else {"values": row_data})

        return {
            "columns": columns,
            "rows": rows,
            "metadata": {
                "type": "NDDataset",
                "shape": dataset.shape,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
            },
        }

    def _table_from_dict(
        self, data: Dict[str, Any], max_rows: int, transpose: bool, show_index: bool
    ) -> Dict[str, Any]:
        """Convert dict to table format."""
        # Handle common dict structures from modeling nodes
        if "data" in data and isinstance(data["data"], (list, np.ndarray)):
            # Use 'data' field (e.g., from PCA, MCR nodes)
            return self._table_from_array(data["data"], max_rows, transpose, show_index)

        elif "scores" in data:
            # PCA scores
            scores = np.array(data["scores"])
            if scores.ndim == 1:
                scores = scores.reshape(-1, 1)

            n_rows = min(scores.shape[0], max_rows)
            n_cols = scores.shape[1] if scores.ndim > 1 else 1

            columns = data.get("pc_labels", [f"PC{i+1}" for i in range(n_cols)])
            rows = [
                {"index": i, "values": scores[i].tolist()} if show_index else {"values": scores[i].tolist()}
                for i in range(n_rows)
            ]

            return {
                "columns": columns[:n_cols],
                "rows": rows,
                "metadata": {
                    "type": "PCA_scores",
                    "n_rows": n_rows,
                    "n_cols": n_cols,
                    "truncated": scores.shape[0] > max_rows,
                },
            }

        # Fallback: treat dict as key-value table
        items = list(data.items())[:max_rows]
        return {
            "columns": ["Key", "Value"],
            "rows": [
                {"index": i, "values": [str(k), str(v)]} if show_index else {"values": [str(k), str(v)]}
                for i, (k, v) in enumerate(items)
            ],
            "metadata": {
                "type": "dict",
                "n_rows": len(items),
                "n_cols": 2,
                "truncated": len(data) > max_rows,
            },
        }

    def _table_from_array(self, data: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert array to table format."""
        arr = np.array(data)

        # Handle 1D arrays
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)

        n_rows, n_cols = arr.shape

        # Apply max_rows limit
        if n_rows > max_rows:
            arr = arr[:max_rows]
            truncated = True
        else:
            truncated = False

        # Transpose if requested
        if transpose:
            arr = arr.T
            n_rows, n_cols = n_cols, n_rows

        columns = [f"Col_{i+1}" for i in range(n_cols)]
        rows = [
            {"index": i, "values": arr[i].tolist()} if show_index else {"values": arr[i].tolist()}
            for i in range(n_rows)
        ]

        return {
            "columns": columns,
            "rows": rows,
            "metadata": {
                "type": "array",
                "shape": arr.shape,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
            },
        }
