"""Specimen-independence admission shared by preparation and execution.

Observation IDs identify acquired rows, not independent experimental units.
Only explicitly declared specimen/subject/patient columns establish this rule;
neither display labels nor the number of rows establish independence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np

INDEPENDENT_IDENTITY_FIELDS: Final = ("specimen_id", "subject_id", "patient_id")
ROW_SELECTING_SPLIT_METHODS: Final = frozenset({"kennard_stone", "duplex", "spxy"})


@dataclass(frozen=True)
class IndependenceViolation:
    code: str
    field: str | None
    message: str


def independence_violations(
    table: Mapping[str, Any] | None,
    *,
    n_samples: int,
    target_type: str | None,
    target_names: Sequence[str | None] = (),
    groups: Any = None,
    split_method: str = "stratified",
    validation_goal: str = "unseen_specimens",
) -> tuple[IndependenceViolation, ...]:
    """Return actionable refusals without fitting, splitting, or mutating data.

    Column names are canonical and case-sensitive, as in the sample-table binding.
    Identity values are compared exactly after trimming, never case-folded. A
    coarser patient grouping is allowed only if it keeps every specimen together.
    Exact cross-block membership is validated against the executed partition.
    """

    def violation(code: str, message: str, field: str | None = None) -> tuple[IndependenceViolation, ...]:
        return (IndependenceViolation(code, field, message),)

    if validation_goal not in {"unseen_specimens", "known_specimen_cross_block"}:
        return violation("unknown_goal", "Unknown supervised validation goal")
    if validation_goal == "known_specimen_cross_block" and split_method != "group_holdout":
        return violation("cross_block_method", "Cross-block repeatability requires an explicitly named group holdout")
    if target_type not in {"categorical", "continuous"} or not isinstance(table, Mapping):
        return ()
    for field in INDEPENDENT_IDENTITY_FIELDS:
        if field not in table:
            continue
        identities = np.asarray(table[field], dtype=object)
        if identities.ndim != 1 or identities.size != n_samples:
            return violation("identity_alignment", f"Retained {field} identities do not match the sample rows", field)
        if any(
            value is None
            or (isinstance(value, (float, np.floating)) and not np.isfinite(value))
            or not str(value).strip()
            for value in identities
        ):
            return violation(
                "incomplete_identity", f"Supervised validation requires complete {field} identities", field
            )
        labels = [str(value).strip() for value in identities]
        count = len(set(labels))
        if count == len(labels):
            continue
        if count < 2:
            return violation(
                "one_specimen",
                f"Only one independent {field} is available. A supervised holdout requires at least "
                "two independent specimens; collect additional specimens or use an exploratory workflow "
                "without a held-out performance claim.",
                field,
            )
        if field in target_names:
            return violation(
                "identity_as_response",
                f"{field} identifies repeated specimens and cannot be both the response target "
                "and an independent held-out specimen group. Choose a different scientific target instead.",
                field,
            )
        if groups is None:
            return violation(
                "groups_required",
                f"Repeated {field} values require an independent grouped supervised split. "
                "Select a specimen or coarser patient/subject identity under Groups in My Dataset "
                "and explicitly rebind the workflow source before running. A block-held-out test "
                "of known specimens answers a different repeatability question.",
                field,
            )
        if split_method in ROW_SELECTING_SPLIT_METHODS:
            return violation(
                "row_selecting_method",
                f"{split_method} selects individual rows and cannot hold repeated {field} identities "
                "apart. Choose stratified, random, sequential, or group holdout splitting.",
                field,
            )
        grouped = np.asarray(groups, dtype=object)
        if grouped.ndim != 1 or grouped.size != len(labels):
            return violation(
                "group_alignment", "The bound grouping column does not align with the retained sample rows", field
            )
        if any(
            value is None
            or (isinstance(value, (float, np.floating)) and not np.isfinite(value))
            or not str(value).strip()
            for value in grouped
        ):
            return violation("incomplete_groups", "The bound grouping column contains missing identities", field)
        if validation_goal == "known_specimen_cross_block":
            if len({str(group).strip() for group in grouped}) < 2:
                return violation("one_block", "Cross-block repeatability needs at least two acquisition groups", field)
            continue
        identity_to_group: dict[str, str] = {}
        for identity, group in zip(labels, grouped, strict=True):
            group_label = str(group).strip()
            if identity in identity_to_group and identity_to_group[identity] != group_label:
                return violation(
                    "divided_specimen",
                    f"The bound Groups column divides repeated {field} identities. "
                    f"This split tests unseen {field} identities, not cross-block repeatability of known specimens. "
                    f"Select {field} or a coarser patient/subject identity and explicitly rebind "
                    "the workflow source before running.",
                    field,
                )
            identity_to_group[identity] = group_label
    return ()


def independence_preview(
    table: Mapping[str, Any] | None,
    *,
    n_samples: int | None,
    target_type: str | None,
    target_names: Sequence[str | None] = (),
    group_column: str | None = None,
) -> dict[str, Any]:
    """Advisory preview using the same rule; execution rechecks the bound dataset."""
    if table is None or n_samples is None:
        return {"checked": False, "violations": [], "suggested_groups": []}
    arguments = dict(n_samples=n_samples, target_type=target_type, target_names=target_names)
    violations = independence_violations(table, groups=table.get(group_column), **arguments)
    suggested = []
    for field in INDEPENDENT_IDENTITY_FIELDS:
        values = table.get(field)
        if values is None or field in target_names:
            continue
        if not independence_violations(
            table, groups=values, **{**arguments, "target_type": target_type or "continuous"}
        ):
            if 1 < len({str(value).strip() for value in values}) < n_samples:
                suggested.append(field)
    return {
        "checked": True,
        "violations": [asdict(item) for item in violations],
        "suggested_groups": suggested,
    }


def cross_block_violations(
    table: Mapping[str, Any] | None,
    *,
    n_samples: int,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    targets: Any = None,
    target_type: str | None = None,
) -> tuple[IndependenceViolation, ...]:
    """Validate the actual partition for repeatability of known specimens."""
    fields = [field for field in INDEPENDENT_IDENTITY_FIELDS if isinstance(table, Mapping) and field in table]
    if not fields:
        return (
            IndependenceViolation(
                "missing_specimen_identity",
                None,
                "Cross-block repeatability requires a specimen, subject, or patient identity column",
            ),
        )
    indices = list(train_indices) + list(test_indices)
    if (
        not len(train_indices)
        or not len(test_indices)
        or len(indices) != n_samples
        or len(set(indices)) != n_samples
        or any(not isinstance(index, (int, np.integer)) or index < 0 or index >= n_samples for index in indices)
    ):
        return (IndependenceViolation("invalid_partition", None, "Cross-block partition is incomplete or overlaps"),)
    for field in fields:
        values = np.asarray(table[field], dtype=object)
        if values.ndim != 1 or values.size != n_samples:
            return (
                IndependenceViolation(
                    "identity_alignment",
                    field,
                    f"Retained {field} identities do not match the split rows",
                ),
            )
        if any(
            value is None
            or not str(value).strip()
            or (isinstance(value, (float, np.floating)) and not np.isfinite(value))
            for value in values
        ):
            return (
                IndependenceViolation(
                    "incomplete_identity",
                    field,
                    f"Cross-block repeatability requires complete {field} identities",
                ),
            )
        train = {str(values[index]).strip() for index in train_indices}
        test = {str(values[index]).strip() for index in test_indices}
        if not test <= train:
            return (
                IndependenceViolation(
                    "new_specimen",
                    field,
                    f"Held-out block contains a new {field}; this design tests only repeatability of known specimens. "
                    "Choose a different block or use unseen-specimen validation.",
                ),
            )
    if targets is not None and target_type == "categorical":
        labels = np.asarray(targets)
        if labels.ndim == 2 and labels.shape[1] == 1:
            labels = labels.reshape(-1)
        if labels.ndim != 1 or labels.size != n_samples:
            return (IndependenceViolation("target_alignment", None, "Retained targets do not match the split rows"),)
        classes = set(labels.tolist())
        if set(labels[list(train_indices)].tolist()) != classes or set(labels[list(test_indices)].tolist()) != classes:
            return (
                IndependenceViolation(
                    "missing_class",
                    None,
                    "Every class must occur in both training and held-out blocks",
                ),
            )
    return ()
