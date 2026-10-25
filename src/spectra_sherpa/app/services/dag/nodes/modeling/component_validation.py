"""Conservative eligibility for automatic component-validation curves."""

from __future__ import annotations

from typing import Any

SAFE_PREMODEL_OPERATIONS = frozenset(
    {
        "data.train_test_split",
        "preprocess.normalize",
        "preprocess.smooth",
        "preprocess.derivative",
        "preprocess.clip_range",
        "preprocess.clip_floor",
        "data.load_group",
        "data.synthetic_curve",
        "data.attach_target",
    }
)

RAW_SOURCE_OPERATIONS = frozenset({"data.file_load", "spectrasherpa.experiment_dataset_read/2"})
KNOWN_IMPORT_OPERATIONS = frozenset(
    {
        "import.matlab_dso",
        "import.matlab_process_log",
        "import.registered_reference",
    }
)


def automatic_curve_workload_reason(rows: int, features: int, components: int, folds: int) -> str | None:
    """Bound optional refits so a routine model fit is not dominated by its curve."""

    if rows * features > 1_000_000 or rows * features * components * (folds + 1) > 50_000_000:
        return (
            "Automatic component validation exceeds the 1,000,000-cell or "
            "50,000,000-work-unit budget; use an explicit validation workflow."
        )
    return None


def cv_unavailable_reason(dataset: Any) -> str | None:
    """Only sample-local or partition-only upstream steps can be reused in folds.

    Population-fitted transforms and supervised selection must be refitted in
    each fold by an explicit validation workflow; this automatic curve never
    claims to have replayed them.
    """

    provenance = getattr(dataset, "provenance", None)
    if provenance is None:
        return "Input provenance is unavailable; fold-local preprocessing cannot be verified."
    for entry in provenance:
        operation = getattr(entry, "op_id", None)
        if not isinstance(operation, str):
            return "Input preprocessing provenance cannot be verified for fold-local fitting."
        if operation in RAW_SOURCE_OPERATIONS:
            parameters = getattr(entry, "parameters", None)
            # A generated source is the original, unprocessed acquisition for
            # its synthetic cohort. It is as fold-local as a raw file; a
            # preprocessed source is not.
            if not hasattr(parameters, "get") or parameters.get("stage") not in {"raw", "synthetic"}:
                return f"Input source {operation} is not a verified raw stage."
            continue
        if operation == "data.train_test_split":
            parameters = getattr(entry, "parameters", None)
            if not hasattr(parameters, "get") or parameters.get("split") != "train":
                return "Input split is not verified as the training partition; automatic component CV is unavailable."
            continue
        if operation == "data.filter_samples":
            parameters = getattr(entry, "parameters", None)
            # Explicit source curation defines the analysis population; it
            # learns no transform or target-dependent selector across folds.
            if (
                hasattr(parameters, "get")
                and parameters.get("field") == "source_inclusion"
                and parameters.get("invert") is False
            ):
                continue
            return "Input sample filtering is not verified as explicit source inclusion."
        if operation in SAFE_PREMODEL_OPERATIONS or operation in KNOWN_IMPORT_OPERATIONS:
            continue
        return f"Input contains {operation}; its fold-local safety was not established."
    return None
