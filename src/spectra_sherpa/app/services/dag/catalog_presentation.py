"""Scientist-facing grouping and naming for the canonical node registry.

Execution contracts digest their implementation modules, including the modules
where node classes declare their original metadata.  Catalog wording and
placement are presentation concerns: changing them must not invalidate a
fitted state, a managed profile, or a saved workflow.  This module therefore
projects registered metadata only when clients enumerate or describe the
catalog.  Node types, class metadata, serializers, and execution contracts are
left untouched.
"""

from __future__ import annotations

from dataclasses import replace

from .node_base import NodeMetadata

CANONICAL_CATALOG_FAMILIES = frozenset(
    {
        "classification",
        "clustering",
        "data",
        "deploy",
        "exploratory",
        "output",
        "preprocessing",
        "regression",
        "selection",
        "synthesis",
        "time_series",
        "transfer",
        "validation",
    }
)

_SYNTHESIS_OPERATIONS = frozenset(
    {
        "custom.catmull_rom_curve",
        "custom.concentration_curve",
        "custom.hybrid_selector",
        "custom.linear_calibration",
        "custom.noise_injection",
        "custom.saturation_model",
        "custom.system_saturation",
    }
)
_TRANSFER_OPERATIONS = frozenset(
    {
        "transfer.apply_fitted",
        "transfer.ds",
        "transfer.pds",
        "transfer.sws",
    }
)
_TIME_SERIES_OPERATIONS = frozenset(
    {
        "time_series.moving_window",
        "time_series.trend_removal",
    }
)
_VALIDATION_OPERATIONS = frozenset(
    {
        "diagnostics.classification_evaluator",
        "diagnostics.labeled_regression_evaluator",
        "diagnostics.regression_evaluator",
    }
)
_REGRESSION_OPERATIONS = frozenset(
    {
        "model.apply_fitted_pls",
        "model.fitted_pls",
        "model.fitted_pcr",
        "model.fitted_svr",
        "model.fitted_linear_regression",
        "model.apply_fitted_pcr",
        "model.apply_fitted_svr",
        "model.apply_fitted_linear_regression",
    }
)

_CATEGORY_OVERRIDES = {
    **{operation: "synthesis" for operation in _SYNTHESIS_OPERATIONS},
    **{operation: "transfer" for operation in _TRANSFER_OPERATIONS},
    **{operation: "time_series" for operation in _TIME_SERIES_OPERATIONS},
    **{operation: "validation" for operation in _VALIDATION_OPERATIONS},
    **{operation: "regression" for operation in _REGRESSION_OPERATIONS},
    "custom.golden_grid_align": "preprocessing",
    "model.load_apply": "deploy",
}

_PLS_FIT_DESCRIPTION = (
    "Fit PLS regression with de Jong's SIMPLS solver. One response is PLS1; multiple responses are PLS2. "
    "Emit typed fitted state and calculate training predictions through the same numerical authority."
)


def project_catalog_metadata(metadata: NodeMetadata) -> NodeMetadata:
    """Return the visible catalog projection without changing execution identity."""

    changes: dict[str, str] = {}
    category = _CATEGORY_OVERRIDES.get(metadata.node_type)
    if category is not None:
        changes["category"] = category
    if metadata.node_type == "model.fitted_pls":
        changes.update(label="Fit PLS1 / PLS2 Regression (SIMPLS)", description=_PLS_FIT_DESCRIPTION)
    elif metadata.node_type == "model.apply_fitted_pls":
        changes.update(
            label="Apply PLS1 / PLS2 Model (SIMPLS)",
            description=(
                "Apply an exact PLS1 or PLS2 SIMPLS state supplied by a local fitted-state edge or an imported "
                "canonical artifact binding. Both custody paths converge before numerical application."
            ),
        )
    return replace(metadata, **changes) if changes else metadata


__all__ = ["CANONICAL_CATALOG_FAMILIES", "project_catalog_metadata"]
