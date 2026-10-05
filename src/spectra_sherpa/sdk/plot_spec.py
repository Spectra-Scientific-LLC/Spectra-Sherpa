"""Closed, renderer-independent visualization records.

The scientific DAG emits JSON data, never a live renderer object.  A
Workbench or notebook renderer may consume this record, but renderer imports
and mutable figure state are deliberately outside the execution contract.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

CANONICAL_PLOT_SPEC_VERSION = "spectra-canonical-plot-spec/1"
MAX_CANONICAL_PLOT_SPEC_BYTES = 32 * 1024 * 1024
MAX_CANONICAL_PLOT_TRACES = 512

_TOP_LEVEL_FIELDS = frozenset({"schema_version", "plot_type", "data", "layout", "metadata"})
_PLOT_TYPES = frozenset(
    {
        "bar",
        "biplot",
        "contour",
        "dendrogram",
        "explained_variance",
        "features",
        "generic",
        "heatmap",
        "line",
        "loadings",
        "metrics",
        "plot",
        "profiles",
        "scatter",
        "scores",
        "spectra",
        "surface",
        "transfer_error",
    }
)
_TRACE_TYPES = frozenset({"bar", "contour", "heatmap", "scatter", "surface"})
_TRACE_FIELDS = frozenset(
    {
        "colorbar",
        "colorscale",
        "connectgaps",
        "contours",
        "customdata",
        "hoverinfo",
        "hovertemplate",
        "hoverlabel",
        "fill",
        "fillcolor",
        "legendgroup",
        "line",
        "marker",
        "mode",
        "name",
        "opacity",
        "orientation",
        "showlegend",
        "showscale",
        "stackgroup",
        "text",
        "textfont",
        "textposition",
        "type",
        "visible",
        "width",
        "x",
        "xaxis",
        "y",
        "yaxis",
        "z",
        "zmax",
        "zmid",
        "zmin",
    }
)
_LAYOUT_FIELDS = frozenset(
    {
        "annotations",
        "autosize",
        "barmode",
        "height",
        "font",
        "paper_bgcolor",
        "plot_bgcolor",
        "hovermode",
        "legend",
        "margin",
        "scene",
        "shapes",
        "showlegend",
        "title",
        "width",
        "xaxis",
        "yaxis",
        "yaxis2",
    }
)


class CanonicalPlotSpecError(ValueError):
    """A visualization record is not the current closed specification."""


def _json_safe(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalPlotSpecError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalPlotSpecError(f"{path} contains a non-text key")
            normalized[key] = _json_safe(item, path=f"{path}.{key}")
        return normalized
    # NumPy scalar values expose item() without forcing NumPy into this core
    # contract module. Arrays are intentionally rejected: nodes must project
    # them to deterministic JSON lists before constructing a plot spec.
    item = getattr(value, "item", None)
    if callable(item):
        candidate = item()
        if candidate is not value:
            return _json_safe(candidate, path=path)
    raise CanonicalPlotSpecError(f"{path} is not JSON-safe")


def _closed_mapping(value: Any, *, path: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalPlotSpecError(f"{path} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CanonicalPlotSpecError(f"{path} contains unsupported fields: {', '.join(unknown)}")
    return _json_safe(value, path=path)


@dataclass(frozen=True)
class CanonicalPlotSpec:
    """One portable visualization declaration shared by DAG and renderers."""

    plot_type: str
    data: tuple[dict[str, Any], ...]
    layout: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        plot_type: str,
        data: Any,
        layout: Any,
        metadata: Any | None = None,
    ) -> "CanonicalPlotSpec":
        if plot_type not in _PLOT_TYPES:
            raise CanonicalPlotSpecError("plot_type is unsupported")
        if not isinstance(data, list) or not data or len(data) > MAX_CANONICAL_PLOT_TRACES:
            raise CanonicalPlotSpecError("data must contain between 1 and 512 traces")
        traces: list[dict[str, Any]] = []
        for index, raw_trace in enumerate(data):
            trace = _closed_mapping(raw_trace, path=f"data[{index}]", allowed=_TRACE_FIELDS)
            if trace.get("type") not in _TRACE_TYPES:
                raise CanonicalPlotSpecError(f"data[{index}].type is unsupported")
            if "visible" in trace and not (isinstance(trace["visible"], bool) or trace["visible"] == "legendonly"):
                raise CanonicalPlotSpecError(f"data[{index}].visible must be true, false, or 'legendonly'")
            traces.append(trace)
        closed_layout = _closed_mapping(layout, path="layout", allowed=_LAYOUT_FIELDS)
        closed_metadata = _json_safe(metadata or {}, path="metadata")
        if not isinstance(closed_metadata, dict):
            raise CanonicalPlotSpecError("metadata must be an object")
        spec = cls(
            plot_type=plot_type,
            data=tuple(traces),
            layout=closed_layout,
            metadata=closed_metadata,
        )
        encoded = json.dumps(spec.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_CANONICAL_PLOT_SPEC_BYTES:
            raise CanonicalPlotSpecError("plot specification exceeds the byte budget")
        return spec

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalPlotSpec":
        unknown = sorted(set(value) - _TOP_LEVEL_FIELDS)
        missing = sorted(_TOP_LEVEL_FIELDS - set(value))
        if unknown or missing:
            raise CanonicalPlotSpecError(f"plot specification fields differ: missing={missing}, unknown={unknown}")
        if value.get("schema_version") != CANONICAL_PLOT_SPEC_VERSION:
            raise CanonicalPlotSpecError("plot specification schema is unsupported")
        return cls.create(
            plot_type=value.get("plot_type"),
            data=value.get("data"),
            layout=value.get("layout"),
            metadata=value.get("metadata"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANONICAL_PLOT_SPEC_VERSION,
            "plot_type": self.plot_type,
            "data": [dict(trace) for trace in self.data],
            "layout": dict(self.layout),
            "metadata": dict(self.metadata),
        }


def canonical_plot_spec_from_projection(value: Mapping[str, Any]) -> CanonicalPlotSpec:
    """Close one node-owned presentation projection into the public schema."""

    unknown = sorted(set(value) - {"plot_type", "data", "layout", "metadata", "type"})
    if unknown:
        raise CanonicalPlotSpecError(f"presentation projection contains unsupported fields: {', '.join(unknown)}")
    raw_metadata = value.get("metadata", {})
    if not isinstance(raw_metadata, Mapping):
        raise CanonicalPlotSpecError("presentation projection metadata must be an object")
    metadata = dict(raw_metadata)
    source_type = value.get("type")
    if source_type is not None:
        if not isinstance(source_type, str) or not source_type:
            raise CanonicalPlotSpecError("presentation projection type must be non-empty text")
        metadata["source_projection_type"] = source_type
    return CanonicalPlotSpec.create(
        plot_type=value.get("plot_type"),
        data=value.get("data"),
        layout=value.get("layout"),
        metadata=metadata,
    )


__all__ = [
    "CANONICAL_PLOT_SPEC_VERSION",
    "MAX_CANONICAL_PLOT_SPEC_BYTES",
    "MAX_CANONICAL_PLOT_TRACES",
    "CanonicalPlotSpec",
    "CanonicalPlotSpecError",
    "canonical_plot_spec_from_projection",
]
