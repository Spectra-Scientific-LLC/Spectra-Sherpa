"""
Built-in dataset inspection tools.

These tools let the LLM inspect dataset metadata, domain context,
and quality metrics using dataset handles (dataset_id).
"""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory


@register_tool(
    "describe_dataset",
    "Generate a structured summary of a dataset including domain, "
    "processing state, and quality metrics.",
    category=ToolCategory.data,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "Dataset handle ID",
            },
            "tier": {
                "type": "integer",
                "description": (
                    "Detail tier: 0=shape+domain, 1=+state+axes, "
                    "2=+provenance, 3=+quality+statistics"
                ),
            },
        },
        "required": ["dataset_id"],
    },
)
def describe_dataset(dataset_id: str, tier: int = 1, user: Any = None) -> dict[str, Any]:
    """Return a tiered summary for a registered dataset handle."""
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    user_id = getattr(user, "id", None) if user is not None else None
    try:
        ds = dataset_registry.get(dataset_id, user_id=user_id)
    except KeyError as exc:
        raise ValueError(f"Unknown dataset_id: {dataset_id}") from exc
    except PermissionError as exc:
        raise ValueError("Dataset is not accessible for this user") from exc

    summarizer = DatasetSummarizer()
    return {
        "dataset_id": ds.dataset_id,
        "summary": summarizer.summarize(ds, tier=tier),
        "structured": summarizer.to_structured(ds, tier=tier),
    }


@register_tool(
    "get_dataset_quality",
    "Get quality metrics and evaluation results for a dataset.",
    category=ToolCategory.data,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "Dataset handle ID",
            },
        },
        "required": ["dataset_id"],
    },
)
def get_dataset_quality(dataset_id: str, user: Any = None) -> dict[str, Any]:
    """Extract quality metrics and evaluation history from a dataset handle."""
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    user_id = getattr(user, "id", None) if user is not None else None
    try:
        ds = dataset_registry.get(dataset_id, user_id=user_id)
    except KeyError as exc:
        raise ValueError(f"Unknown dataset_id: {dataset_id}") from exc
    except PermissionError as exc:
        raise ValueError("Dataset is not accessible for this user") from exc

    q = ds.quality
    result: dict[str, Any] = {
        "dataset_id": ds.dataset_id,
        "snr": q.snr,
        "n_evaluations": len(q.evaluations),
    }
    if q.latest:
        result["latest"] = q.latest.model_dump(exclude_none=True)
    return result
