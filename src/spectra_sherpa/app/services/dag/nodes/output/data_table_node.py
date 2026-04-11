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
        Convert input data to a frontend-compatible table payload.

        The frontend ``outputPreview`` at ``NodeDetailView.vue`` reads from
        ``nodeOutput.data`` (a flat top-level ``data`` key on the port) and
        already handles two row shapes:

        * numeric rows (``list[list[float]]``) → emits ``col_0, col_1, ...``
          columns, with real names pulled from ``metadata.column_names``;
        * dict rows (``list[dict]``) → uses the dict keys directly as column
          names (see the "PeakFinding stats output" branch).

        We emit into whichever shape is most natural for the input and
        attach useful metadata for column naming.  This replaces the old
        ``{columns, rows}`` shape that nothing on the frontend consumed —
        which was why the Metrics Table panel looked empty even when the
        backend produced valid metrics.
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
                "data": [],
                "metadata": {"type": "empty", "message": "No data to display"},
            }

        return {"visualization": table_data}

    def _table_from_dataset(self, dataset: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert SherpaDataset to table format.

        Emits numeric rows as ``list[list[float]]`` under ``data`` and puts
        per-column headers into ``metadata.column_names`` so the frontend's
        ``outputPreviewColumns`` picks them up.  Sample labels (if the
        dataset has a ``sample_axis`` with labels) are forwarded through
        ``metadata.sample_labels`` so the preview table adds a Label column.
        """
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

        # Build column headers.  Prefer the feature axis' categorical
        # ``labels`` when present (e.g. PLS "LV1", "LV2" …) — otherwise
        # fall back to formatting the numeric axis values (e.g. wavelengths
        # "1100.00", "1102.00" …).  This keeps PLS scores tables readable
        # instead of showing the numeric index of the latent variable.
        x_coord = dataset.feature_axis
        columns: list[str] = []
        if x_coord is not None and not transpose:
            raw_labels = getattr(x_coord, "labels", None)
            if raw_labels is not None:
                try:
                    labels_list = list(raw_labels)
                    if len(labels_list) >= n_cols:
                        columns = [str(v) for v in labels_list[:n_cols]]
                except Exception:
                    columns = []
            if not columns:
                try:
                    x_vals = np.asarray(x_coord.data)
                    if x_vals.size == n_cols and np.issubdtype(x_vals.dtype, np.number):
                        columns = [f"{float(x):.2f}" for x in x_vals[:n_cols]]
                except Exception:
                    columns = []
        if not columns:
            columns = [f"Col_{i+1}" for i in range(n_cols)]

        # Forward sample labels to the frontend if present
        sample_labels: list[str] | None = None
        try:
            sample_axis = getattr(dataset, "sample_axis", None)
            if sample_axis is not None:
                raw_labels = getattr(sample_axis, "labels", None)
                if raw_labels is not None:
                    sample_labels = [str(x) for x in list(raw_labels)[:n_rows]]
        except Exception:
            sample_labels = None

        # Emit rows as flat numeric lists — outputPreview on the frontend
        # auto-generates col_0, col_1, ... fields and overrides them with
        # ``metadata.column_names`` when present.
        rows = [list(map(float, data[i].tolist())) for i in range(n_rows)]

        meta: Dict[str, Any] = {
            "type": "NDDataset",
            "shape": list(dataset.shape),
            "n_rows": n_rows,
            "n_cols": n_cols,
            "truncated": truncated,
            "show_index": show_index,
            "column_names": columns,
        }
        if sample_labels:
            meta["sample_labels"] = sample_labels

        return {"data": rows, "metadata": meta}

    def _table_from_dict(
        self, data: Dict[str, Any], max_rows: int, transpose: bool, show_index: bool
    ) -> Dict[str, Any]:
        """Convert dict to table format.

        Three recognised shapes:

        * ``{"data": [row_dict, row_dict, ...]}`` → metrics payload from
          HoldoutEvaluation / per-class classification reports.  Pass the
          row dicts straight through under ``data``; the frontend's
          ``outputPreview`` generates columns from the dict keys.
        * ``{"data": ndarray}`` or ``{"data": [[values], ...]}`` → numeric
          rows from PCA/MCR; forward to ``_table_from_array``.
        * ``{"scores": ndarray, ...}`` → PCA-style scores; convert to
          numeric rows with ``pc_labels`` as column names.

        Anything else falls back to a key/value table (for flat scalar
        dicts like model diagnostics).
        """
        # Metrics payloads: list of row dicts from HoldoutEvaluation /
        # classification reports.  Forward straight through so the frontend
        # preview machinery can use the dict keys as column headers.
        if "data" in data and isinstance(data["data"], list) and data["data"] and isinstance(data["data"][0], dict):
            rows_in = data["data"][:max_rows]
            # Column order: union of keys seen across rows, first-seen wins.
            columns: list[str] = []
            seen: set[str] = set()
            for row in rows_in:
                if not isinstance(row, dict):
                    continue
                for key in row.keys():
                    if key not in seen:
                        seen.add(key)
                        columns.append(str(key))
            source_metadata = data.get("metadata")
            meta: Dict[str, Any] = {
                "type": "metrics",
                "n_rows": len(rows_in),
                "n_cols": len(columns),
                "truncated": len(data["data"]) > max_rows,
                "show_index": show_index,
                "column_names": columns,
            }
            if source_metadata is not None:
                meta["source_metadata"] = source_metadata
            return {"data": rows_in, "metadata": meta}

        # Numeric payloads from PCA/MCR: forward the array to the numeric path.
        if "data" in data and isinstance(data["data"], (list, np.ndarray)):
            return self._table_from_array(data["data"], max_rows, transpose, show_index)

        if "scores" in data:
            scores = np.array(data["scores"])
            if scores.ndim == 1:
                scores = scores.reshape(-1, 1)
            n_rows = min(scores.shape[0], max_rows)
            n_cols = scores.shape[1] if scores.ndim > 1 else 1
            columns = list(data.get("pc_labels", [f"PC{i+1}" for i in range(n_cols)]))[:n_cols]
            rows = [list(map(float, scores[i].tolist())) for i in range(n_rows)]
            return {
                "data": rows,
                "metadata": {
                    "type": "PCA_scores",
                    "n_rows": n_rows,
                    "n_cols": n_cols,
                    "truncated": scores.shape[0] > max_rows,
                    "column_names": columns,
                },
            }

        # Fallback: flatten a scalar dict into a two-column key/value table.
        items = list(data.items())[:max_rows]
        rows = [{"Key": str(k), "Value": str(v)} for k, v in items]
        return {
            "data": rows,
            "metadata": {
                "type": "dict",
                "n_rows": len(items),
                "n_cols": 2,
                "truncated": len(data) > max_rows,
                "column_names": ["Key", "Value"],
            },
        }

    def _table_from_array(self, data: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert a 2D array-like to numeric rows.

        Rows come out as ``list[list[float]]`` for frontend preview
        consumption; column names default to ``Col_1..N`` but are placed
        in ``metadata.column_names`` so a caller can override them via a
        higher-level wrapper if needed.
        """
        arr = np.asarray(data, dtype=np.float64)

        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)

        n_rows, n_cols = arr.shape

        if n_rows > max_rows:
            arr = arr[:max_rows]
            truncated = True
        else:
            truncated = False

        if transpose:
            arr = arr.T
            n_rows, n_cols = n_cols, n_rows

        columns = [f"Col_{i+1}" for i in range(n_cols)]
        rows = [list(map(float, arr[i].tolist())) for i in range(n_rows)]

        return {
            "data": rows,
            "metadata": {
                "type": "array",
                "shape": list(arr.shape),
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
                "column_names": columns,
            },
        }
