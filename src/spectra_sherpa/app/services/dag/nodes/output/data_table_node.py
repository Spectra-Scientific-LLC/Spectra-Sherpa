"""
Data Table visualization node.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag import presentation_limits
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, SalientFeatures, register_node


def _is_numeric_array(arr: np.ndarray) -> bool:
    """Return True when an array can be safely emitted as numeric rows."""
    return np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_)


def _copy_scientific_metadata(meta: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Preserve high-value provenance fields when converting data to a table."""
    for key in (
        "data_role",
        "sherpa.data_role",
        "data_modality",
        "sherpa.data_modality",
        "processing_history",
        "provenance",
        "quality_summary",
        "target_context",
        "selection_provenance",
        "source_context",
        "peak_groups",
        "column_units",
        "measurement_policy",
    ):
        if key in source:
            meta[key] = source[key]


def _canonical_table_parameters(raw: dict[str, object]) -> dict[str, object]:
    """Close the bounded table-preview settings."""

    unknown = sorted(set(raw) - {"max_rows", "transpose", "show_index"})
    if unknown:
        raise ValueError(f"output.data_table received unknown parameters: {', '.join(unknown)}")
    max_rows = raw.get("max_rows", 100_000)
    if isinstance(max_rows, bool) or not isinstance(max_rows, (int, np.integer)):
        raise ValueError("output.data_table max_rows must be an integer")
    max_rows = int(max_rows)
    if not 10 <= max_rows <= 100_000:
        raise ValueError("output.data_table max_rows must be between 10 and 100000")
    transpose = raw.get("transpose", False)
    show_index = raw.get("show_index", True)
    if not isinstance(transpose, bool) or not isinstance(show_index, bool):
        raise ValueError("output.data_table transpose and show_index must be boolean")
    return {"max_rows": max_rows, "transpose": transpose, "show_index": show_index}


@register_node
class DataTableNode(Node):
    """
    Data Table visualization node.

    Displays tabular data with interactive features like sorting, filtering,
    and column selection. Useful for inspecting numerical results, model outputs,
    and statistical summaries.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
        node_type="output.data_table",
        category="output",
        label="Data Table",
        description="Display data in an interactive table with sorting and filtering",
        parameters=[
            NodeParameter(
                name="max_rows",
                label="Max Rows",
                param_type="number",
                default=100000,
                min_value=10,
                max_value=100000,
                max_value_reason="Bounds browser memory and serialized preview size.",
                step=10,
                description="Maximum number of rows to display before truncating the table preview",
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
        input_types=["SherpaDataset", "dict", "array"],
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
        canonical_parameter_validator=_canonical_table_parameters,
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate a call to the same table authority used live."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Data table ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.output.data_table_node "
                "import build_data_table_result"
            ),
            f"{indent}results[{self.node_id!r}] = build_data_table_result(",
            f"{indent}    {input_expr}, parameters={parameters!r},",
            f"{indent})",
        ]

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
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return build_data_table_result(input_data, parameters=parameters)

    def _build(self, input_data: Any) -> Dict[str, Any]:
        """Project one supported canonical value into a bounded table payload."""
        from spectra_sherpa.app.services.dag.presentation_limits import require_bounded_presentation

        if isinstance(input_data, SalientFeatures):
            input_data = asdict(input_data)
        require_bounded_presentation(input_data, surface="Data table", max_values=500_000)
        max_rows = self.parameters.get("max_rows", 100000)
        transpose = self.parameters.get("transpose", False)
        show_index = self.parameters.get("show_index", True)

        # Convert input to table format
        if isinstance(input_data, SherpaDataset):
            table_data = self._table_from_dataset(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, dict):
            table_data = self._table_from_dict(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, list) and input_data and isinstance(input_data[0], dict):
            rows = input_data[:max_rows]
            columns: list[str] = []
            seen: set[str] = set()
            for row in rows:
                for key in row.keys():
                    if key not in seen:
                        seen.add(key)
                        columns.append(str(key))
            table_data = {
                "data": rows,
                "metadata": {
                    "type": "records",
                    "n_rows": len(rows),
                    "n_cols": len(columns),
                    "truncated": len(input_data) > max_rows,
                    "show_index": show_index,
                    "column_names": columns,
                },
            }
        elif isinstance(input_data, (list, np.ndarray)):
            table_data = self._table_from_array(input_data, max_rows, transpose, show_index)
        else:
            raise ValueError("output.data_table requires a supported canonical dataset, mapping, or array")

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
        if data.ndim != 2 or data.size == 0:
            raise ValueError("output.data_table requires a non-empty one- or two-dimensional canonical dataset")

        n_rows, n_cols = data.shape

        # Apply max_rows limit
        if n_rows > max_rows:
            data = data[:max_rows]
            truncated = True
            n_rows = data.shape[0]
        else:
            truncated = False

        # Transpose if requested
        if transpose:
            data = data.T
            n_rows, n_cols = data.shape

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
                labels_list = list(raw_labels)
                if len(labels_list) >= n_cols:
                    columns = [str(v) for v in labels_list[:n_cols]]
            if not columns:
                x_vals = np.asarray(x_coord.data)
                if x_vals.size == n_cols and np.issubdtype(x_vals.dtype, np.number):
                    columns = [f"{float(x):.2f}" for x in x_vals[:n_cols]]
        if not columns:
            columns = [f"Col_{i + 1}" for i in range(n_cols)]

        # Forward sample labels to the frontend if present
        sample_labels: list[str] | None = None
        sample_axis = getattr(dataset, "sample_axis", None)
        if sample_axis is not None:
            raw_labels = getattr(sample_axis, "labels", None)
            if raw_labels is not None:
                sample_labels = [str(x) for x in list(raw_labels)[:n_rows]]

        # Emit rows as flat numeric lists — outputPreview on the frontend
        # auto-generates col_0, col_1, ... fields and overrides them with
        # ``metadata.column_names`` when present.
        # Table payloads are plain JSON, unlike typed datasets. Preserve missing
        # measurements as null rather than leaking non-JSON NaN/Infinity.
        rows = [[float(value) if np.isfinite(value) else None for value in data[i]] for i in range(n_rows)]

        meta: Dict[str, Any] = {
            "type": "SherpaDataset",
            "shape": list(dataset.shape),
            "n_rows": n_rows,
            "n_cols": n_cols,
            "truncated": truncated,
            "show_index": show_index,
            "column_names": columns,
        }
        _copy_scientific_metadata(meta, getattr(dataset, "meta", {}) or {})
        if getattr(dataset, "data_role", None):
            meta["data_role"] = dataset.data_role
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
        if {"method", "features", "x_units", "x_title", "n_total_variables", "selection_context"} <= data.keys():
            features = data["features"]
            if not isinstance(features, list) or any(
                not isinstance(feature, dict) or not {"position", "importance", "label"} <= feature.keys()
                for feature in features
            ):
                raise ValueError("SalientFeatures requires a list of position, importance and label records")
            is_peaks = data["method"] == "peak_finding"
            index_column = "consensus_group" if is_peaks else "feature_index"
            score_column = "detection_fraction" if is_peaks else "importance"
            columns = [index_column, "position", score_column, "label"]
            return {
                "data": [
                    {
                        index_column: index + 1,
                        "position": feature["position"],
                        score_column: feature["importance"],
                        "label": feature["label"],
                    }
                    for index, feature in enumerate(features[:max_rows])
                ],
                "metadata": {
                    "type": "salient_features",
                    "n_rows": min(len(features), max_rows),
                    "n_cols": len(columns),
                    "truncated": len(features) > max_rows,
                    "show_index": show_index,
                    "column_names": columns,
                    "column_units": {"position": data["x_units"]},
                    "method": data["method"],
                    "x_title": data["x_title"],
                    "x_units": data["x_units"],
                    "n_total_variables": data["n_total_variables"],
                    "selection_context": data["selection_context"],
                    "score_meaning": (
                        "Fraction of input spectra with at least one detected peak in this consensus group (0–1)."
                        if is_peaks
                        else "Producer-supplied importance; interpretation depends on the selection method."
                    ),
                },
            }

        # Metrics payloads: list of row dicts from HoldoutEvaluation /
        # classification reports.  Forward straight through so the frontend
        # preview machinery can use the dict keys as column headers.
        if isinstance(data.get("default"), SherpaDataset):
            return self._table_from_dataset(data["default"], max_rows, transpose, show_index)

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
            if isinstance(source_metadata, dict):
                meta["source_metadata"] = source_metadata
                _copy_scientific_metadata(meta, source_metadata)
            return {"data": rows_in, "metadata": meta}

        # Numeric payloads from PCA/MCR: forward the array to the numeric path.
        if "data" in data and isinstance(data["data"], (list, np.ndarray)):
            table = self._table_from_array(data["data"], max_rows, transpose, show_index)
            source_metadata = data.get("metadata")
            if isinstance(source_metadata, dict):
                table["metadata"]["source_metadata"] = source_metadata
                _copy_scientific_metadata(table["metadata"], source_metadata)
            return table

        if "scores" in data or "X_scores" in data:
            score_payload = data["scores"] if data.get("scores") is not None else data.get("X_scores")
            if isinstance(score_payload, SherpaDataset):
                return self._table_from_dataset(score_payload, max_rows, transpose, show_index)
            scores = np.array(score_payload)
            if scores.ndim == 1:
                scores = scores.reshape(-1, 1)
            n_rows = min(scores.shape[0], max_rows)
            n_cols = scores.shape[1] if scores.ndim > 1 else 1
            columns = list(data.get("pc_labels", [f"PC{i + 1}" for i in range(n_cols)]))[:n_cols]
            numeric_rows: list[list[float]] = [list(map(float, scores[i].tolist())) for i in range(n_rows)]
            return {
                "data": numeric_rows,
                "metadata": {
                    "type": "PCA_scores",
                    "n_rows": n_rows,
                    "n_cols": n_cols,
                    "truncated": scores.shape[0] > max_rows,
                    "column_names": columns,
                },
            }

        if isinstance(data.get("cluster_summary"), list) and data["cluster_summary"]:
            rows_in = data["cluster_summary"][:max_rows]
            if isinstance(rows_in[0], dict):
                columns: list[str] = []
                seen: set[str] = set()
                for row in rows_in:
                    for key in row.keys():
                        if key not in seen:
                            seen.add(key)
                            columns.append(str(key))
                return {
                    "data": rows_in,
                    "metadata": {
                        "type": "cluster_summary",
                        "n_rows": len(rows_in),
                        "n_cols": len(columns),
                        "truncated": len(data["cluster_summary"]) > max_rows,
                        "show_index": show_index,
                        "column_names": columns,
                        "source_metadata": data.get("metadata"),
                    },
                }

        for key in (
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
            if key in data and data[key] is not None:
                table = self._table_from_array(data[key], max_rows, transpose, show_index)
                table["metadata"]["source_key"] = key
                source_metadata = data.get("metadata")
                if isinstance(source_metadata, dict):
                    table["metadata"]["source_metadata"] = source_metadata
                    _copy_scientific_metadata(table["metadata"], source_metadata)
                return table

        # Fallback: flatten a scalar dict into a two-column key/value table.
        # Use a distinct variable name from the numeric-rows branch above so
        # mypy doesn't narrow the type to ``list[list[float]]`` and reject
        # this list-of-dicts assignment (CI #260 caught this on main).
        items = list(data.items())[:max_rows]
        dict_rows: list[dict[str, str]] = [{"Key": str(k), "Value": str(v)} for k, v in items]
        return {
            "data": dict_rows,
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
        arr = np.asarray(data)

        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        if arr.ndim != 2 or arr.size == 0:
            raise ValueError("output.data_table requires a non-empty one- or two-dimensional array")

        n_rows, n_cols = arr.shape

        if n_rows > max_rows:
            arr = arr[:max_rows]
            truncated = True
            n_rows = arr.shape[0]
        else:
            truncated = False

        if transpose:
            arr = arr.T
            n_rows, n_cols = arr.shape

        if n_cols == 1:
            columns = ["Value"]
        else:
            columns = [f"Col_{i + 1}" for i in range(n_cols)]

        if _is_numeric_array(arr):
            rows: list[list[Any]] = [list(map(float, arr[i].tolist())) for i in range(n_rows)]
            value_type = "numeric"
        else:
            rows = [[str(v) for v in np.asarray(arr[i], dtype=object).tolist()] for i in range(n_rows)]
            value_type = "categorical"

        return {
            "data": rows,
            "metadata": {
                "type": "array",
                "value_type": value_type,
                "shape": list(arr.shape),
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
                "column_names": columns,
            },
        }


def build_data_table_result(
    input_data: Any,
    *,
    parameters: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Return the sole live/generated table-presentation payload."""

    canonical = DataTableNode.metadata.canonicalize_parameters(parameters or {})
    node = DataTableNode("canonical-data-table-authority", canonical)
    return node._build(input_data)


bind_stable_execution_contract(
    DataTableNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.output.data-table",
    implementation_version="1.0.2",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/output.md",
    implementation_modules=(presentation_limits,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)


__all__ = ["DataTableNode", "build_data_table_result"]
