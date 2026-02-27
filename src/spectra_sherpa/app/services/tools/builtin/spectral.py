"""
Built-in spectral domain tools.

These tools expose the DAG node registry to the LLM so it can
reason about available operations, their parameters, and
recommended preprocessing pipelines.
"""

from __future__ import annotations

from typing import Any, Optional

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory

# ---------------------------------------------------------------------------
# list_node_types
# ---------------------------------------------------------------------------


@register_tool(
    "list_node_types",
    "List available DAG node types, optionally filtered by category. " "Returns node type IDs, labels, and categories.",
    category=ToolCategory.spectral,
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Filter by node category. Common values: "
                    "preprocessing, modeling, classification, data, "
                    "output, diagnostics, custom, time_series"
                ),
            },
        },
        "required": [],
    },
)
def list_node_types(category: Optional[str] = None) -> list[dict[str, str]]:
    """Return a compact list of registered node types."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    results = []
    for node_type, node_cls in sorted(node_registry._nodes.items()):
        meta = node_cls.metadata
        if category and meta.category != category:
            continue
        results.append(
            {
                "node_type": meta.node_type,
                "label": meta.label,
                "category": meta.category,
                "description": meta.description[:120],
            }
        )
    return results


# ---------------------------------------------------------------------------
# describe_node
# ---------------------------------------------------------------------------


@register_tool(
    "describe_node",
    "Get detailed information about a specific DAG node type including "
    "all parameters, input/output ports, and description.",
    category=ToolCategory.spectral,
    parameters={
        "type": "object",
        "properties": {
            "node_type": {
                "type": "string",
                "description": (
                    "Node type identifier (e.g. 'model.pca', " "'preprocess.scale', 'baseline.penalized_ls')"
                ),
            },
        },
        "required": ["node_type"],
    },
)
def describe_node(node_type: str) -> dict[str, Any]:
    """Return the full metadata for a single node type."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    node_cls = node_registry._nodes.get(node_type)
    if node_cls is None:
        available = sorted(node_registry._nodes.keys())
        return {"error": f"Unknown node type: {node_type!r}", "available": available}

    meta = node_cls.metadata
    params = []
    for p in meta.parameters:
        entry: dict[str, Any] = {
            "name": p.name,
            "label": p.label,
            "type": p.param_type,
            "required": p.required,
        }
        if p.default is not None:
            entry["default"] = p.default
        if p.description:
            entry["description"] = p.description
        if p.options:
            entry["options"] = p.options
        if p.min_value is not None:
            entry["min"] = p.min_value
        if p.max_value is not None:
            entry["max"] = p.max_value
        if p.category:
            entry["category"] = p.category
        params.append(entry)

    result: dict[str, Any] = {
        "node_type": meta.node_type,
        "label": meta.label,
        "category": meta.category,
        "description": meta.description,
        "parameters": params,
        "input_types": meta.input_types,
        "output_type": meta.output_type,
    }

    if meta.input_ports:
        result["input_ports"] = [
            {
                "name": port.name,
                "type_ref": port.type_ref,
                "required": port.required,
                "label": port.label,
            }
            for port in meta.input_ports
        ]

    if meta.output_ports:
        result["output_ports"] = [
            {
                "name": port.name,
                "type_ref": port.type_ref,
                "label": port.label,
            }
            for port in meta.output_ports
        ]

    return result


# ---------------------------------------------------------------------------
# suggest_preprocessing
# ---------------------------------------------------------------------------

# Technique-specific recommendations based on spectroscopy domain knowledge.
# These are general guidelines, not absolute rules.
_TECHNIQUE_RECOMMENDATIONS: dict[str, list[dict[str, str]]] = {
    "IR": [
        {"step": "baseline.penalized_ls", "reason": "Remove baseline drift common in IR spectra"},
        {"step": "preprocess.normalize", "reason": "Correct scatter effects (path-length variations)"},
        {"step": "preprocess.smooth", "reason": "Reduce high-frequency noise"},
    ],
    "NIR": [
        {"step": "preprocess.normalize", "reason": "NIR spectra are dominated by scatter — SNV is standard"},
        {"step": "preprocess.derivative", "reason": "First derivative resolves overlapping NIR bands"},
        {"step": "preprocess.smooth", "reason": "Smooth before or after derivative"},
    ],
    "Raman": [
        {"step": "baseline.penalized_ls", "reason": "Remove fluorescence background"},
        {"step": "preprocess.cosmic_ray", "reason": "Remove cosmic ray spikes"},
        {"step": "preprocess.normalize", "reason": "Normalize intensity variations"},
    ],
    "UV-Vis": [
        {"step": "baseline.rubberband", "reason": "Correct baseline curvature"},
        {"step": "preprocess.normalize", "reason": "Scale to comparable intensities"},
    ],
}

_DEFAULT_RECOMMENDATIONS = [
    {"step": "preprocess.scale", "reason": "Center and scale for general chemometrics"},
    {"step": "preprocess.smooth", "reason": "Reduce noise while preserving spectral features"},
]


@register_tool(
    "suggest_preprocessing",
    "Suggest a preprocessing pipeline based on spectral technique and "
    "intended analysis. Returns ordered steps with rationale.",
    category=ToolCategory.spectral,
    parameters={
        "type": "object",
        "properties": {
            "technique": {
                "type": "string",
                "description": "Spectral technique: IR, NIR, Raman, UV-Vis",
                "enum": ["IR", "NIR", "Raman", "UV-Vis"],
            },
            "goal": {
                "type": "string",
                "description": ("Analysis goal: 'classification', 'regression', " "'clustering', 'exploration'"),
                "enum": ["classification", "regression", "clustering", "exploration"],
            },
        },
        "required": [],
    },
)
def suggest_preprocessing(
    technique: Optional[str] = None,
    goal: Optional[str] = None,
) -> dict[str, Any]:
    """Recommend preprocessing steps with explanations."""
    steps = list(_TECHNIQUE_RECOMMENDATIONS.get(technique or "", _DEFAULT_RECOMMENDATIONS))

    # Add goal-specific suggestions
    if goal == "classification":
        steps.append(
            {
                "step": "preprocess.scale",
                "reason": "Autoscaling is common before classification to equalize feature variance",
            }
        )
    elif goal == "regression":
        steps.append({"step": "preprocess.scale", "reason": "Mean centering is standard for PLS regression"})
    elif goal == "clustering":
        steps.append(
            {
                "step": "preprocess.scale",
                "reason": "Autoscaling prevents high-intensity features from dominating distance metrics",
            }
        )

    # Deduplicate by step name
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for s in steps:
        if s["step"] not in seen:
            seen.add(s["step"])
            unique.append(s)

    return {
        "technique": technique or "generic",
        "goal": goal or "general",
        "recommended_steps": unique,
        "note": (
            "These are general recommendations. Optimal preprocessing "
            "depends on specific data characteristics. Examine your data "
            "after each step."
        ),
    }
