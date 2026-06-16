"""TrainTestSplitNode -- split datasets into training and test sets.

Registered as ``data.train_test_split``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, cast

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, bind_y, build_dataset_like, resolve_target_names, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._utils import slice_axis_for_indices

logger = logging.getLogger(__name__)


def _split_filter_terms(pattern: str) -> list[str]:
    """Split comma/newline-separated filter terms for exact-list matching."""
    return [term.strip() for term in re.split(r"[\n,]+", pattern) if term.strip()]


def _normalize_filter_strings(values: list[Any], *, case_sensitive: bool) -> list[str]:
    normalized = ["" if value is None else str(value) for value in values]
    if not case_sensitive:
        normalized = [value.lower() for value in normalized]
    return normalized


def _explicit_filter_values(value: Any) -> list[Any] | None:
    """Return an explicit exact-selection list, preserving an empty list."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return None
    if isinstance(value, np.ndarray):
        return value.astype(object).reshape(-1).tolist()
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return None


def _explicit_filter_mask(values: list[Any], selected_values: list[Any]) -> np.ndarray:
    """Return an exact string-match mask for UI-populated checkbox selections."""
    selected = set(_normalize_filter_strings(selected_values, case_sensitive=True))
    value_strings = _normalize_filter_strings(values, case_sensitive=True)
    return np.asarray([value in selected for value in value_strings], dtype=bool)


def _sample_filter_mask(
    values: list[Any],
    *,
    pattern: str,
    match_mode: str,
    case_sensitive: bool,
) -> np.ndarray:
    """Return a boolean mask for sample metadata text matching."""
    value_strings = _normalize_filter_strings(values, case_sensitive=case_sensitive)
    pattern_text = pattern if case_sensitive else pattern.lower()

    if match_mode == "contains":
        return np.asarray([pattern_text in value for value in value_strings], dtype=bool)
    if match_mode == "equals":
        return np.asarray([value == pattern_text for value in value_strings], dtype=bool)
    if match_mode == "in_list":
        terms = set(_normalize_filter_strings(_split_filter_terms(pattern), case_sensitive=case_sensitive))
        return np.asarray([value in terms for value in value_strings], dtype=bool)
    if match_mode == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression for sample filter: {exc}") from exc
        return np.asarray(
            [regex.search("" if value is None else str(value)) is not None for value in values],
            dtype=bool,
        )

    raise ValueError(f"Unsupported sample filter match mode: {match_mode!r}")


def _sample_index_mask(pattern: str, *, n_samples: int, match_mode: str, case_sensitive: bool) -> np.ndarray:
    """Return a mask for 1-based sample index selectors like ``1, 3-5``."""
    if match_mode == "regex":
        values = [str(i + 1) for i in range(n_samples)]
        return _sample_filter_mask(values, pattern=pattern, match_mode=match_mode, case_sensitive=case_sensitive)

    selected: set[int] = set()
    for term in _split_filter_terms(pattern):
        if "-" in term:
            left, right = term.split("-", 1)
            try:
                start = int(left.strip())
                stop = int(right.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid sample index range {term!r}. Use values like 1, 3-5.") from exc
            if start > stop:
                start, stop = stop, start
            selected.update(range(start, stop + 1))
        else:
            try:
                selected.add(int(term))
            except ValueError as exc:
                raise ValueError(f"Invalid sample index {term!r}. Use values like 1, 3-5.") from exc

    invalid = sorted(index for index in selected if index < 1 or index > n_samples)
    if invalid:
        raise ValueError(f"Sample index out of range: {invalid}. Dataset has samples 1 through {n_samples}.")

    return np.asarray([(i + 1) in selected for i in range(n_samples)], dtype=bool)


def _numeric_filter_compare(
    values: np.ndarray,
    *,
    operator: str,
    threshold: float,
    upper_threshold: float,
) -> np.ndarray:
    if operator == "gt":
        return values > threshold
    if operator == "gte":
        return values >= threshold
    if operator == "lt":
        return values < threshold
    if operator == "lte":
        return values <= threshold
    if operator == "eq":
        return np.isclose(values, threshold)
    if operator == "neq":
        return ~np.isclose(values, threshold)
    if operator == "between":
        low, high = sorted((threshold, upper_threshold))
        return (values >= low) & (values <= high)
    raise ValueError(f"Unsupported intensity filter operator: {operator!r}")


def _intensity_filter_mask(
    data: np.ndarray,
    *,
    metric: str,
    operator: str,
    threshold: float,
    upper_threshold: float,
) -> np.ndarray:
    """Return a sample mask based on row-wise intensity summaries."""
    if metric == "mean":
        values = np.nanmean(data, axis=1)
        return _numeric_filter_compare(values, operator=operator, threshold=threshold, upper_threshold=upper_threshold)
    if metric == "max":
        values = np.nanmax(data, axis=1)
        return _numeric_filter_compare(values, operator=operator, threshold=threshold, upper_threshold=upper_threshold)
    if metric == "min":
        values = np.nanmin(data, axis=1)
        return _numeric_filter_compare(values, operator=operator, threshold=threshold, upper_threshold=upper_threshold)
    if metric == "any":
        point_mask = _numeric_filter_compare(
            data,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
        )
        return np.any(point_mask, axis=1)
    if metric == "all":
        point_mask = _numeric_filter_compare(
            data,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
        )
        return np.all(point_mask, axis=1)
    raise ValueError(f"Unsupported intensity filter metric: {metric!r}")


def _flatten_filter_values(values: Any, *, field: str, n_samples: int) -> list[Any]:
    arr = np.asarray(values, dtype=object)
    if arr.ndim == 0:
        raise ValueError(f"Sample filter field {field!r} is scalar; expected one value per sample.")
    if arr.ndim > 1:
        if arr.shape[1:] == (1,):
            arr = arr.reshape(n_samples)
        else:
            raise ValueError(
                f"Sample filter field {field!r} has shape {arr.shape}; "
                "multi-column metadata cannot be filtered directly."
            )
    if arr.shape[0] != n_samples:
        raise ValueError(
            f"Sample filter field {field!r} has {arr.shape[0]} values, but dataset has {n_samples} samples."
        )
    return arr.tolist()


def _sample_filter_values(X_ds: Any, *, field: str, sample_table_column: str, n_samples: int) -> list[Any]:
    sample_axis = getattr(X_ds, "sample_axis", None)

    if field == "sample_label":
        labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
        if labels is None:
            raise ValueError("Dataset has no sample labels to filter. Use Sample Index or attach sample labels first.")
        return _flatten_filter_values(labels, field=field, n_samples=n_samples)

    if field == "sample_class":
        classes = getattr(sample_axis, "classes", None) if sample_axis is not None else None
        if classes is None:
            raise ValueError("Dataset has no sample classes to filter.")
        return _flatten_filter_values(classes, field=field, n_samples=n_samples)

    if field == "target":
        target = getattr(X_ds, "target", None)
        if target is None:
            raise ValueError("Dataset has no target values to filter.")
        return _flatten_filter_values(target, field=field, n_samples=n_samples)

    if field == "sample_table":
        column = sample_table_column.strip()
        if not column:
            raise ValueError("Sample Table Column is required when filtering by sample table.")
        sample_table = getattr(sample_axis, "sample_table", None) if sample_axis is not None else None
        if sample_table is None or column not in sample_table:
            available = sorted(sample_table) if sample_table else []
            raise ValueError(
                f"Dataset sample table has no column {column!r}. "
                f"Available columns: {', '.join(available) if available else 'none'}."
            )
        return _flatten_filter_values(sample_table[column], field=f"sample_table.{column}", n_samples=n_samples)

    if field == "sample_index":
        return [str(i + 1) for i in range(n_samples)]

    raise ValueError(f"Unsupported sample filter field: {field!r}")


def _slice_dataset_rows(source: Any, data: np.ndarray, indices: np.ndarray) -> Any:
    """Slice dataset rows while preserving aligned sample metadata."""
    result = build_dataset_like(data[indices], source)

    sample_axis = getattr(source, "sample_axis", None)
    if sample_axis is not None and len(sample_axis) > 0:
        sliced_axis = slice_axis_for_indices(sample_axis, indices)
        if sliced_axis is not None:
            result.sample_axis = cast(Any, sliced_axis)

    target = getattr(source, "target", None)
    if target is not None:
        target_array = np.asarray(target)
        if target_array.shape[0] == data.shape[0]:
            result.target = target_array[indices]
        else:
            result.target = None

    return result


@register_node
class FilterSamplesNode(Node):
    """Filter or subsample dataset rows using sample metadata."""

    metadata = NodeMetadata(
        node_type="data.filter_samples",
        category="data",
        label="Filter Samples",
        description="Filter dataset rows using sample labels, classes, targets, metadata, or row numbers",
        parameters=[
            NodeParameter(
                name="field",
                label="Filter Field",
                param_type="select",
                options=[
                    {"label": "Sample Label", "value": "sample_label"},
                    {"label": "Sample Class", "value": "sample_class"},
                    {"label": "Target", "value": "target"},
                    {"label": "Sample Table", "value": "sample_table"},
                    {"label": "Sample Index", "value": "sample_index"},
                    {"label": "Intensity", "value": "intensity"},
                ],
                default="sample_label",
                description="Sample metadata field used to select rows",
                required=True,
            ),
            NodeParameter(
                name="pattern",
                label="Pattern",
                param_type="text",
                default="",
                description="Text, comma-separated values, or regular expression to match",
                required=False,
            ),
            NodeParameter(
                name="match_mode",
                label="Match Mode",
                param_type="select",
                options=[
                    {"label": "Contains", "value": "contains"},
                    {"label": "Equals", "value": "equals"},
                    {"label": "In List", "value": "in_list"},
                    {"label": "Regex", "value": "regex"},
                ],
                default="contains",
                description="How the pattern is matched against each sample",
                required=True,
            ),
            NodeParameter(
                name="case_sensitive",
                label="Case Sensitive",
                param_type="boolean",
                default=False,
                description="Require exact letter case when matching text",
                required=False,
            ),
            NodeParameter(
                name="invert",
                label="Invert Selection",
                param_type="boolean",
                default=False,
                description="Keep samples that do not match the filter",
                required=False,
            ),
            NodeParameter(
                name="sample_table_column",
                label="Sample Table Column",
                param_type="text",
                default="",
                description="Metadata column to use when Filter Field is sample_table",
                required=False,
                visible_when={"field": ["sample_table"]},
            ),
            NodeParameter(
                name="intensity_metric",
                label="Intensity Metric",
                param_type="select",
                options=[
                    {"label": "Mean Intensity", "value": "mean"},
                    {"label": "Max Intensity", "value": "max"},
                    {"label": "Min Intensity", "value": "min"},
                    {"label": "Any Point", "value": "any"},
                    {"label": "All Points", "value": "all"},
                ],
                default="max",
                description="How each sample spectrum is summarized for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_operator",
                label="Intensity Operator",
                param_type="select",
                options=[
                    {"label": "Greater Than", "value": "gt"},
                    {"label": "Greater Than or Equal", "value": "gte"},
                    {"label": "Less Than", "value": "lt"},
                    {"label": "Less Than or Equal", "value": "lte"},
                    {"label": "Equal", "value": "eq"},
                    {"label": "Not Equal", "value": "neq"},
                    {"label": "Between", "value": "between"},
                ],
                default="gte",
                description="Numeric comparison used for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_threshold",
                label="Intensity Threshold",
                param_type="number",
                default=0.0,
                description="Numeric threshold for intensity filtering",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="intensity_upper_threshold",
                label="Upper Threshold",
                param_type="number",
                default=1.0,
                description="Upper threshold used by the Between operator",
                required=False,
                visible_when={"field": ["intensity"]},
            ),
            NodeParameter(
                name="allow_empty",
                label="Allow Empty Result",
                param_type="boolean",
                default=False,
                description="Allow the filter to produce a dataset with zero samples",
                required=False,
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Dataset whose samples should be filtered",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Filtered Dataset",
                description="Dataset containing only selected samples",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for sample filtering."""
        params = self._resolve_params()
        field = params.get("field", "sample_label")
        pattern = str(params.get("pattern", ""))
        match_mode = params.get("match_mode", "contains")
        case_sensitive = bool(params.get("case_sensitive", False))
        invert = bool(params.get("invert", False))
        sample_table_column = str(params.get("sample_table_column", ""))
        allow_empty = bool(params.get("allow_empty", False))
        intensity_metric = str(params.get("intensity_metric", "max"))
        intensity_operator = str(params.get("intensity_operator", "gte"))
        intensity_threshold = float(params.get("intensity_threshold", 0.0))
        intensity_upper_threshold = float(params.get("intensity_upper_threshold", 1.0))
        explicit_values = _explicit_filter_values(params.get("filter_values"))
        X_expr = inputs.get("X", inputs.get("default", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- Filter Samples ({self.node_id}) ---")
        lines.append(f"{indent}import re")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.asarray(getattr(_X_input, 'data', _X_input), dtype=np.float64)")
        lines.append(f"{indent}_filter_pattern = {pattern!r}")
        lines.append(f"{indent}if not _filter_pattern.strip():")
        lines.append(f"{indent}    _filter_idx = np.arange(_X_data.shape[0])")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _sample_axis = getattr(_X_input, 'sample_axis', None)")
        lines.append(f"{indent}    _filter_field = {field!r}")
        lines.append(f"{indent}    if _filter_field == 'sample_label':")
        lines.append(f"{indent}        _filter_values = getattr(_sample_axis, 'labels', None)")
        lines.append(f"{indent}    elif _filter_field == 'sample_class':")
        lines.append(f"{indent}        _filter_values = getattr(_sample_axis, 'classes', None)")
        lines.append(f"{indent}    elif _filter_field == 'target':")
        lines.append(f"{indent}        _filter_values = getattr(_X_input, 'target', None)")
        lines.append(f"{indent}    elif _filter_field == 'sample_table':")
        lines.append(f"{indent}        _table = getattr(_sample_axis, 'sample_table', None) or {{}}")
        lines.append(f"{indent}        _filter_values = _table.get({sample_table_column!r})")
        lines.append(f"{indent}    elif _filter_field == 'sample_index':")
        lines.append(f"{indent}        _filter_values = [str(i + 1) for i in range(_X_data.shape[0])]")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        raise ValueError(f'Unsupported sample filter field: {{_filter_field!r}}')")
        lines.append(f"{indent}    if _filter_values is None:")
        lines.append(
            f"{indent}        raise ValueError(" f"f'No values available for sample filter field {{_filter_field!r}}')"
        )
        lines.append(f"{indent}    _filter_values = np.asarray(_filter_values, dtype=object).reshape(-1)")
        lines.append(f"{indent}    _filter_values = ['' if v is None else str(v) for v in _filter_values]")
        lines.append(
            f"{indent}    _cmp_values = _filter_values if {case_sensitive!r} "
            "else [v.lower() for v in _filter_values]"
        )
        lines.append(f"{indent}    _cmp_pattern = _filter_pattern if {case_sensitive!r} else _filter_pattern.lower()")
        if match_mode == "contains":
            lines.append(f"{indent}    _filter_mask = np.asarray([_cmp_pattern in v for v in _cmp_values], dtype=bool)")
        elif match_mode == "equals":
            lines.append(f"{indent}    _filter_mask = np.asarray([v == _cmp_pattern for v in _cmp_values], dtype=bool)")
        elif match_mode == "in_list":
            lines.append(
                f"{indent}    _terms = set(" "t.strip() for t in re.split(r'[\\n,]+', _cmp_pattern) if t.strip())"
            )
            lines.append(f"{indent}    _filter_mask = np.asarray([v in _terms for v in _cmp_values], dtype=bool)")
        elif match_mode == "regex":
            lines.append(f"{indent}    _flags = 0 if {case_sensitive!r} else re.IGNORECASE")
            lines.append(f"{indent}    _regex = re.compile(_filter_pattern, _flags)")
            lines.append(
                f"{indent}    _filter_mask = np.asarray("
                "[_regex.search(v) is not None for v in _filter_values], dtype=bool)"
            )
        else:
            lines.append(f"{indent}    raise ValueError('Unsupported sample filter match mode: {match_mode}')")
        lines.append(f"{indent}    if {invert!r}:")
        lines.append(f"{indent}        _filter_mask = ~_filter_mask")
        lines.append(f"{indent}    _filter_idx = np.flatnonzero(_filter_mask)")
        if explicit_values is not None and field != "sample_index":
            lines = [
                f"{indent}# --- Filter Samples ({self.node_id}) ---",
                f"{indent}_X_input = {X_expr}",
                f"{indent}_X_data = np.asarray(getattr(_X_input, 'data', _X_input), dtype=np.float64)",
                f"{indent}_sample_axis = getattr(_X_input, 'sample_axis', None)",
                f"{indent}_filter_field = {field!r}",
                f"{indent}if _filter_field == 'sample_label':",
                f"{indent}    _filter_values = getattr(_sample_axis, 'labels', None)",
                f"{indent}elif _filter_field == 'sample_class':",
                f"{indent}    _filter_values = getattr(_sample_axis, 'classes', None)",
                f"{indent}elif _filter_field == 'target':",
                f"{indent}    _filter_values = getattr(_X_input, 'target', None)",
                f"{indent}elif _filter_field == 'sample_table':",
                f"{indent}    _table = getattr(_sample_axis, 'sample_table', None) or {{}}",
                f"{indent}    _filter_values = _table.get({sample_table_column!r})",
                f"{indent}else:",
                f"{indent}    raise ValueError(f'Unsupported sample filter field: {{_filter_field!r}}')",
                f"{indent}if _filter_values is None:",
                f"{indent}    raise ValueError(f'No values available for sample filter field {{_filter_field!r}}')",
                f"{indent}_filter_values = np.asarray(_filter_values, dtype=object).reshape(-1)",
                f"{indent}_filter_values = ['' if v is None else str(v) for v in _filter_values]",
                f"{indent}_selected_values = {explicit_values!r}",
                f"{indent}_selected_values = set('' if v is None else str(v) for v in _selected_values)",
                f"{indent}_filter_mask = np.asarray([v in _selected_values for v in _filter_values], dtype=bool)",
                f"{indent}if {invert!r}:",
                f"{indent}    _filter_mask = ~_filter_mask",
                f"{indent}_filter_idx = np.flatnonzero(_filter_mask)",
            ]
        if field == "intensity":
            lines = [
                f"{indent}# --- Filter Samples ({self.node_id}) ---",
                f"{indent}_X_input = {X_expr}",
                f"{indent}_X_data = np.asarray(getattr(_X_input, 'data', _X_input), dtype=np.float64)",
                f"{indent}_metric = {intensity_metric!r}",
                f"{indent}_operator = {intensity_operator!r}",
                f"{indent}_threshold = {intensity_threshold!r}",
                f"{indent}_upper = {intensity_upper_threshold!r}",
                f"{indent}def _cmp(v):",
                f"{indent}    if _operator == 'gt': return v > _threshold",
                f"{indent}    if _operator == 'gte': return v >= _threshold",
                f"{indent}    if _operator == 'lt': return v < _threshold",
                f"{indent}    if _operator == 'lte': return v <= _threshold",
                f"{indent}    if _operator == 'eq': return np.isclose(v, _threshold)",
                f"{indent}    if _operator == 'neq': return ~np.isclose(v, _threshold)",
                f"{indent}    if _operator == 'between':",
                f"{indent}        _low, _high = sorted((_threshold, _upper))",
                f"{indent}        return (v >= _low) & (v <= _high)",
                f"{indent}    raise ValueError(f'Unsupported intensity filter operator: {{_operator!r}}')",
                f"{indent}if _metric == 'mean':",
                f"{indent}    _filter_mask = _cmp(np.nanmean(_X_data, axis=1))",
                f"{indent}elif _metric == 'max':",
                f"{indent}    _filter_mask = _cmp(np.nanmax(_X_data, axis=1))",
                f"{indent}elif _metric == 'min':",
                f"{indent}    _filter_mask = _cmp(np.nanmin(_X_data, axis=1))",
                f"{indent}elif _metric == 'any':",
                f"{indent}    _filter_mask = np.any(_cmp(_X_data), axis=1)",
                f"{indent}elif _metric == 'all':",
                f"{indent}    _filter_mask = np.all(_cmp(_X_data), axis=1)",
                f"{indent}else:",
                f"{indent}    raise ValueError(f'Unsupported intensity filter metric: {{_metric!r}}')",
                f"{indent}if {invert!r}:",
                f"{indent}    _filter_mask = ~_filter_mask",
                f"{indent}_filter_idx = np.flatnonzero(_filter_mask)",
            ]
        lines.append(f"{indent}if _filter_idx.size == 0 and not {allow_empty!r}:")
        lines.append(f"{indent}    raise ValueError('Sample filter selected 0 samples')")
        lines.append(f"{indent}try:")
        lines.append(f"{indent}    _result = _X_input[_filter_idx]")
        lines.append(f"{indent}except Exception:")
        lines.append(f"{indent}    _result = _X_data[_filter_idx]")
        lines.append(f"{indent}results['{self.node_id}'] = _result")
        lines.append(f'{indent}print(f"  Filtered samples: {{_filter_idx.size}} / {{_X_data.shape[0]}}")')
        return lines

    async def execute(self, X: Any = None, **kwargs: Any) -> dict[str, Any]:
        """Filter dataset samples by labels or aligned sample metadata."""
        field = str(self.parameters.get("field", "sample_label"))
        pattern = str(self.parameters.get("pattern", ""))
        match_mode = str(self.parameters.get("match_mode", "contains"))
        case_sensitive = bool(self.parameters.get("case_sensitive", False))
        invert = bool(self.parameters.get("invert", False))
        sample_table_column = str(self.parameters.get("sample_table_column", ""))
        allow_empty = bool(self.parameters.get("allow_empty", False))
        intensity_metric = str(self.parameters.get("intensity_metric", "max"))
        intensity_operator = str(self.parameters.get("intensity_operator", "gte"))
        intensity_threshold = float(self.parameters.get("intensity_threshold", 0.0))
        intensity_upper_threshold = float(self.parameters.get("intensity_upper_threshold", 1.0))
        explicit_values = _explicit_filter_values(self.parameters.get("filter_values"))

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be an NDDataset or SherpaDataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        n_samples = X_array.shape[0]

        if field == "intensity":
            mask = _intensity_filter_mask(
                X_array,
                metric=intensity_metric,
                operator=intensity_operator,
                threshold=intensity_threshold,
                upper_threshold=intensity_upper_threshold,
            )
            if invert:
                mask = ~mask
            indices = np.flatnonzero(mask)
            if indices.size == 0 and not allow_empty:
                raise ValueError(
                    f"Sample filter selected 0 of {n_samples} samples. "
                    "Check the intensity threshold or enable Allow Empty Result."
                )
            result = _slice_dataset_rows(X_ds, X_array, indices)
            no_filter = False
        elif explicit_values is not None and field != "sample_index":
            values = _sample_filter_values(
                X_ds,
                field=field,
                sample_table_column=sample_table_column,
                n_samples=n_samples,
            )
            mask = _explicit_filter_mask(values, explicit_values)
            if invert:
                mask = ~mask

            indices = np.flatnonzero(mask)
            if indices.size == 0 and not allow_empty:
                raise ValueError(
                    f"Sample filter selected 0 of {n_samples} samples. "
                    "Check selected values or enable Allow Empty Result."
                )
            result = _slice_dataset_rows(X_ds, X_array, indices)
            no_filter = False
        elif not pattern.strip():
            indices = np.arange(n_samples)
            result = X_ds.copy()
            no_filter = True
        else:
            if field == "sample_index":
                mask = _sample_index_mask(
                    pattern,
                    n_samples=n_samples,
                    match_mode=match_mode,
                    case_sensitive=case_sensitive,
                )
            else:
                values = _sample_filter_values(
                    X_ds,
                    field=field,
                    sample_table_column=sample_table_column,
                    n_samples=n_samples,
                )
                mask = _sample_filter_mask(
                    values,
                    pattern=pattern,
                    match_mode=match_mode,
                    case_sensitive=case_sensitive,
                )
            if invert:
                mask = ~mask

            indices = np.flatnonzero(mask)
            if indices.size == 0 and not allow_empty:
                raise ValueError(
                    f"Sample filter selected 0 of {n_samples} samples. "
                    "Check the pattern or enable Allow Empty Result."
                )
            result = _slice_dataset_rows(X_ds, X_array, indices)
            no_filter = False

        add_processing_step(
            result,
            "data.filter_samples",
            {
                "field": field,
                "pattern": pattern,
                "match_mode": match_mode,
                "case_sensitive": case_sensitive,
                "invert": invert,
                "sample_table_column": sample_table_column,
                "allow_empty": allow_empty,
                "n_input": n_samples,
                "n_selected": int(indices.size),
                "selected_indices": indices.tolist(),
                "no_filter": no_filter,
                "intensity_metric": intensity_metric,
                "intensity_operator": intensity_operator,
                "intensity_threshold": intensity_threshold,
                "intensity_upper_threshold": intensity_upper_threshold,
                "filter_values": explicit_values,
            },
            node_id=self.node_id,
        )

        logger.debug("Filter Samples: selected %s / %s rows", indices.size, n_samples)

        return {"default": result}


@register_node
class TrainTestSplitNode(Node):
    """
    Split dataset into training and test sets.

    Enables proper ML workflow with separate train/test evaluation.
    Supports random, stratified, and grouped splitting strategies.

    Multi-output node with 4 output ports:
    - X_train: Training feature data
    - X_test: Test feature data
    - y_train: Training targets (if y provided)
    - y_test: Test targets (if y provided)
    """

    metadata = NodeMetadata(
        node_type="data.train_test_split",
        category="data",
        label="Train/Test Split",
        description="Split data into training and test sets with optional stratification",
        parameters=[
            NodeParameter(
                name="test_size",
                label="Test Size",
                param_type="number",
                default=0.2,
                min_value=0.01,
                step=0.05,
                description="Fraction of data to use for testing (0.2 = 20%)",
                required=True,
            ),
            NodeParameter(
                name="split_method",
                label="Split Method",
                param_type="select",
                options=["random", "stratified", "sequential"],
                default="random",
                description="How to split the data",
                required=True,
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                description="Seed for reproducible random splits",
                required=False,
            ),
            NodeParameter(
                name="shuffle",
                label="Shuffle",
                param_type="boolean",
                default=True,
                description="Shuffle data before splitting (for random method)",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Full dataset to split into train/test",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values (optional)",
                description="Target array for stratified splitting (1D or 2D)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_train",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Training Data",
                description="Training subset of input data",
            ),
            PortMetadata(
                name="X_test",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Test Data",
                description="Test subset of input data",
            ),
            PortMetadata(
                name="y_train",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Targets",
                description="Training subset of targets (1D or 2D)",
            ),
            PortMetadata(
                name="y_test",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Test Targets",
                description="Test subset of targets (1D or 2D)",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",  # Returns dict with multiple outputs
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for train/test splitting."""
        params = self._resolve_params()
        test_size = params.get("test_size", 0.2)
        split_method = params.get("split_method", "random")
        random_seed = params.get("random_seed", 42)
        shuffle = params.get("shuffle", True)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- Train/Test Split ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Extract y
        if y_expr:
            lines.append(f"{indent}_y_input = {y_expr}")
            lines.append(f"{indent}_y_data = np.array(")
            lines.append(f"{indent}    _y_input.data if hasattr(_y_input, 'data') else _y_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
        else:
            lines.append(f"{indent}_y_data = getattr(_X_input, 'target', None)")
            lines.append(f"{indent}if _y_data is not None:")
            lines.append(f"{indent}    _y_data = np.asarray(_y_data, dtype=np.float64)")

        # Split
        if split_method == "sequential":
            lines.append(f"{indent}_n = _X_data.shape[0]")
            lines.append(f"{indent}_n_test = int(_n * {test_size})")
            lines.append(f"{indent}_n_train = _n - _n_test")
            lines.append(f"{indent}_train_idx = np.arange(_n_train)")
            lines.append(f"{indent}_test_idx = np.arange(_n_train, _n)")
        else:
            lines.append(f"{indent}_n = _X_data.shape[0]")
            lines.append(f"{indent}_indices = np.arange(_n)")
            if shuffle:
                lines.append(f"{indent}_rng = np.random.RandomState({random_seed})")
                lines.append(f"{indent}_rng.shuffle(_indices)")
            lines.append(f"{indent}_n_test = int(_n * {test_size})")
            lines.append(f"{indent}_n_train = _n - _n_test")
            lines.append(f"{indent}_train_idx = _indices[:_n_train]")
            lines.append(f"{indent}_test_idx = _indices[_n_train:]")

        lines.append(f"{indent}_X_train = _X_data[_train_idx]")
        lines.append(f"{indent}_X_test = _X_data[_test_idx]")

        # Wrap results
        if use_scp:
            lines.append(f"{indent}_X_train_ds = scp.NDDataset(_X_train)")
            lines.append(f"{indent}_X_test_ds = scp.NDDataset(_X_test)")
            lines.append(f"{indent}if hasattr(_X_input, 'x') and _X_input.x is not None:")
            lines.append(f"{indent}    _X_train_ds.x = _X_input.x.copy()")
            lines.append(f"{indent}    _X_test_ds.x = _X_input.x.copy()")
        else:
            lines.append(f"{indent}_fa = getattr(_X_input, 'feature_axis', None)")
            lines.append(f"{indent}_X_train_ds = SherpaDataset(_X_train, feature_axis=_fa)")
            lines.append(f"{indent}_X_test_ds = SherpaDataset(_X_test, feature_axis=_fa)")

        # Build result dict
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_train': _X_train_ds,")
        lines.append(f"{indent}    'X_test': _X_test_ds,")
        lines.append(f"{indent}}}")

        # Split y if available
        lines.append(f"{indent}if _y_data is not None:")
        lines.append(f"{indent}    results['{self.node_id}']['y_train'] = _y_data[_train_idx]")
        lines.append(f"{indent}    results['{self.node_id}']['y_test'] = _y_data[_test_idx]")

        lines.append(f'{indent}print(f"  Split: {{_n_train}} train, {{_n_test}} test ({test_size*100:.0f}% test)")')

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Split data into train and test sets.

        Args:
            X: Input dataset (NDDataset or SpectralResult)
            y: Optional target array for stratification
            **kwargs: Additional inputs (ignored)

        Returns:
            dict with keys: X_train, X_test, y_train (if y provided), y_test (if y provided)
        """
        test_size = self.parameters.get("test_size", 0.2)
        split_method = self.parameters.get("split_method", "random")
        random_seed = self.parameters.get("random_seed", 42)
        shuffle = self.parameters.get("shuffle", True)

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be an NDDataset or SherpaDataset object",
            allow_array=True,
        )
        y_value = bind_y(
            y,
            X=X_ds,
            required=False,
            infer_from_X=True,
            dataset_as_data=False,
        )

        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_value, name="y", expected_samples=X_array.shape[0]) if y_value is not None else None

        n_samples = X_array.shape[0]
        n_test = int(n_samples * test_size)
        n_train = n_samples - n_test

        if n_test < 1 or n_train < 1:
            raise ValueError(
                f"Test size {test_size} results in {n_test} test samples. " f"Need at least 1 train and 1 test sample."
            )

        # Generate indices
        if split_method == "sequential":
            # Sequential split (first N for train, rest for test)
            train_idx = np.arange(n_train)
            test_idx = np.arange(n_train, n_samples)

        elif split_method == "stratified" and y_array is not None:
            # Stratified split (preserve class proportions)
            from sklearn.model_selection import train_test_split

            indices = np.arange(n_samples)

            train_idx, test_idx = train_test_split(
                indices,
                test_size=test_size,
                random_state=random_seed,
                stratify=y_array,
                shuffle=shuffle,
            )

        else:
            # Random split
            indices = np.arange(n_samples)
            if shuffle:
                rng = np.random.RandomState(random_seed)
                rng.shuffle(indices)

            train_idx = indices[:n_train]
            test_idx = indices[n_train:]

        # Split data
        X_train_array = X_array[train_idx]
        X_test_array = X_array[test_idx]

        X_train = build_dataset_like(X_train_array, X_ds)
        X_test = build_dataset_like(X_test_array, X_ds)

        # Slice sample-axis metadata to match train/test rows.
        tts_y_coord = X_ds.sample_axis
        if tts_y_coord is not None and len(tts_y_coord) > 1:
            _train_ax = slice_axis_for_indices(tts_y_coord, train_idx)
            _test_ax = slice_axis_for_indices(tts_y_coord, test_idx)
            if _train_ax is not None:
                X_train.sample_axis = cast(Any, _train_ax)
            if _test_ax is not None:
                X_test.sample_axis = cast(Any, _test_ax)

        # Keep dataset.target aligned after row splitting.
        target = getattr(X_ds, "target", None)
        if target is not None:
            target_array = np.asarray(target)
            if target_array.shape[0] == n_samples:
                X_train.target = target_array[train_idx]
                X_test.target = target_array[test_idx]
            else:
                X_train.target = None
                X_test.target = None

        # Record provenance in dataset.meta
        add_processing_step(
            X_train,
            "data.train_test_split",
            {
                "split": "train",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        add_processing_step(
            X_test,
            "data.train_test_split",
            {
                "split": "test",
                "test_size": test_size,
                "split_method": split_method,
                "random_seed": random_seed,
                "shuffle": shuffle,
                "n_train": n_train,
                "n_test": n_test,
            },
            node_id=self.node_id,
        )

        # Build result dict
        result = {
            "X_train": X_train,
            "X_test": X_test,
        }

        # Split targets if provided/inferred
        if y_array is not None:
            result["y_train"] = y_array[train_idx]
            result["y_test"] = y_array[test_idx]

        logger.debug(f"Train/Test Split: {n_train} train, {n_test} test samples ({test_size*100:.0f}% test)")

        return result


@register_node
class AttachTargetNode(Node):
    """Attach target values to a dataset for supervised modeling.

    Use this when target data comes from a different source than X,
    or when you need to override the embedded target.
    """

    metadata = NodeMetadata(
        node_type="data.attach_target",
        category="data",
        label="Attach Target",
        description="Attach target values to a dataset for supervised modeling",
        parameters=[
            NodeParameter(
                name="target_type",
                label="Target Type",
                param_type="select",
                options=["continuous", "categorical"],
                default="continuous",
                description="Type of target variable",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Dataset to attach target values to",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Target Values",
                description="Target values (1D or 2D array, or dataset with target)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset with Target",
                description="Dataset with embedded target values",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for attaching target to dataset."""
        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- Attach Target ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")

        # Extract y
        if y_expr:
            lines.append(f"{indent}_y_input = {y_expr}")
            lines.append(f"{indent}_y_data = np.array(")
            lines.append(f"{indent}    _y_input.data if hasattr(_y_input, 'data') else _y_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
        else:
            lines.append(f"{indent}_y_data = None")

        if use_scp:
            # SCP mode: copy NDDataset and store target alongside
            lines.append(f"{indent}_result = _X_input.copy() if hasattr(_X_input, 'copy') else _X_input")
            lines.append(f"{indent}if _y_data is not None:")
            lines.append(f"{indent}    _result.target = _y_data")
            lines.append(f"{indent}results['{self.node_id}'] = _result")
        else:
            # numpy mode: wrap in SherpaDataset with target
            lines.append(f"{indent}_X_data = np.array(")
            lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
            lines.append(f"{indent}results['{self.node_id}'] = SherpaDataset(")
            lines.append(f"{indent}    _X_data,")
            lines.append(f"{indent}    feature_axis=getattr(_X_input, 'feature_axis', None),")
            lines.append(f"{indent}    target=_y_data,")
            lines.append(f"{indent})")

        lines.append(f'{indent}print(f"  Target attached: shape={{_y_data.shape if _y_data is not None else None}}")')

        return lines

    async def execute(self, X=None, y=None, **kwargs):
        """Attach target to dataset."""
        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            allow_array=True,
        )

        # Resolve target names BEFORE bind_y strips dataset metadata
        _resolved_target_names = resolve_target_names(y, X_ds)

        y_raw = bind_y(
            y,
            X=None,  # Don't infer from X — we're explicitly attaching
            required=True,
            infer_from_X=False,
            dataset_as_data=True,
            missing_message="Missing required input: y (target values)",
        )

        y_arr = to_numpy_y(y_raw, name="y", expected_samples=X_ds.shape[0])

        result = X_ds.copy()
        result.target = y_arr

        target_type = self.parameters.get("target_type", "continuous")
        if target_type == "categorical":
            n_unique = len(np.unique(y_arr))
            result.target_context = TargetContext(
                target_type="categorical",
                n_classes=n_unique,
                target_names=_resolved_target_names,
            )
        else:
            result.target_context = TargetContext(
                target_type="continuous",
                target_names=_resolved_target_names,
            )

        add_processing_step(
            result,
            "data.attach_target",
            {"target_type": target_type, "target_shape": list(y_arr.shape)},
            node_id=self.node_id,
        )

        return {"default": result}
