"""Canonical dataset-to-template compatibility decisions.

The join is intentionally model-neutral on the dataset side. A dataset states
what it contains; template ``data_roles`` state what an analysis requires.
Every pair receives one explicit status and stable reason codes. Example-data
qualification may be reported separately, but it never makes a scientifically
compatible dataset disappear from the catalog.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict, get_args

from spectra_sherpa.app.lib.data_roles import DATA_ROLES, ROLE_TO_MODALITY, get_dataset_data_role
from spectra_sherpa.app.schemas.template_schema import TemplateStatus

logger = logging.getLogger(__name__)

COMPATIBILITY_SCHEMA = "spectra-sherpa-dataset-template-compatibility/1"

CompatibilityStatus = Literal["compatible", "needs_input", "incompatible", "pending"]
TEMPLATE_QUALIFICATION_STATUSES = frozenset(get_args(TemplateStatus))
CompatibilityDisplayGroup = Literal[
    "compatible",
    "needs_target",
    "needs_source",
    "incompatible",
    "pending",
    "unavailable",
]


class CompatibilityReason(TypedDict):
    code: str
    message: str
    role: str | None


def analysis_profile_from_dataset(dataset: Any) -> dict[str, Any]:
    """Project one admitted dataset into the source-neutral capability schema.

    This is the runtime counterpart of the governed catalog declarations. It is
    deliberately based on typed scientific state, not filenames or dataset
    provenance, so ordinary paid/OSS uploads and registered references follow
    exactly the same compatibility rules.
    """

    role = get_dataset_data_role(dataset) or "X_spectra"
    target_context = getattr(dataset, "target_context", None)
    target_type = getattr(target_context, "target_type", None)
    target_fields = list(getattr(target_context, "target_names", None) or [])
    target_name = getattr(target_context, "target_name", None)
    if target_name and target_name not in target_fields:
        target_fields.append(target_name)

    sample_axis = getattr(dataset, "sample_axis", None)
    if target_type is None and sample_axis is not None and getattr(sample_axis, "classes", None) is not None:
        target_type = "categorical"
        target_fields = [getattr(sample_axis, "primary_class_set_name", None) or "class"]

    sample_table = getattr(sample_axis, "sample_table", None) if sample_axis is not None else None
    columns = list(sample_table) if isinstance(sample_table, Mapping) else []
    identity_fields = [name for name in columns if name in {"sample_id", "specimen_id"}]
    target_field_set = set(target_fields)
    group_fields = [
        name
        for name in columns
        if name in {"block", "batch", "group", "instrument", "replicate_group", "specimen_id"}
        and name not in target_field_set
        and _distinct_nonmissing_count(sample_table[name]) > 1
    ]
    domain = getattr(dataset, "domain", None)
    technique = getattr(domain, "technique", None) or "Unknown"
    return normalize_analysis_profile(
        {
            "primary_role": role,
            "modality": ROLE_TO_MODALITY[role],
            "technique": technique,
            "target_type": target_type,
            "target_fields": target_fields,
            "identity_fields": identity_fields,
            "group_fields": group_fields,
            "ordered_samples": bool(getattr(dataset, "is_time_series", False)),
        }
    )


def normalize_analysis_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return one closed analysis profile suitable for every dataset source."""

    required = {
        "primary_role",
        "modality",
        "technique",
        "target_type",
        "target_fields",
        "identity_fields",
        "group_fields",
        "ordered_samples",
    }
    if set(value) != required:
        raise ValueError("dataset analysis profile fields differ from the closed schema")
    role = value["primary_role"]
    if role not in DATA_ROLES:
        raise ValueError("dataset analysis profile has an unsupported primary role")
    modality = value["modality"]
    if modality != ROLE_TO_MODALITY[role]:
        raise ValueError("dataset analysis role and modality disagree")
    technique = value["technique"]
    if not isinstance(technique, str) or not technique.strip():
        raise ValueError("dataset analysis technique must be non-empty text")
    target_type = value["target_type"]
    if target_type not in {None, "continuous", "categorical", "ordinal"}:
        raise ValueError("dataset analysis target type is unsupported")
    target_fields = _text_fields(value["target_fields"], "target_fields")
    if (target_type is None) != (not target_fields):
        raise ValueError("dataset analysis target type and fields disagree")
    identity_fields = _text_fields(value["identity_fields"], "identity_fields")
    group_fields = _text_fields(value["group_fields"], "group_fields")
    ordered = value["ordered_samples"]
    if type(ordered) is not bool:
        raise ValueError("dataset analysis ordered_samples must be boolean")
    result = {
        "primary_role": role,
        "modality": modality,
        "technique": technique.strip(),
        "target_type": target_type,
        "target_fields": target_fields,
        "identity_fields": identity_fields,
        "group_fields": group_fields,
        "ordered_samples": ordered,
    }
    return result


def evaluate_template_compatibility(
    analysis_profile: Mapping[str, Any],
    template: Mapping[str, Any],
    *,
    node_binding_filter: str | None = None,
    provided_roles: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Evaluate structural readiness against one declarative workflow template.

    ``node_binding_filter`` and ``provided_roles`` let runtime instantiation use
    this same authority after explicit secondary bindings have been supplied.
    They do not weaken the catalog decision, which evaluates every required
    role with no supplied inputs.
    """

    profile = normalize_analysis_profile(analysis_profile)
    supplied = provided_roles or {}
    template_data = template.get("template_data")
    if not isinstance(template_data, Mapping):
        raise ValueError("template_data must be a mapping")
    roles = template_data.get("data_roles")
    if not isinstance(roles, Mapping) or not roles:
        raise ValueError("template data_roles must be a non-empty mapping")

    status_authority = str(template_data.get("status") or template.get("status") or "wip")
    if status_authority not in TEMPLATE_QUALIFICATION_STATUSES:
        raise ValueError("template has no declared supported status")
    reasons: list[CompatibilityReason] = []
    primary_binding: str | None = None
    primary_role_requirement: list[str] = []
    required_target_type: str | None = None

    for role_name, raw_role in roles.items():
        if not isinstance(role_name, str) or not isinstance(raw_role, Mapping):
            raise ValueError("template data_roles contain a malformed role")
        if not raw_role.get("required", True):
            continue
        role_type = str(raw_role.get("role_type") or "")
        binding_mode = str(raw_role.get("binding_mode") or "embedded")
        node_binding = str(raw_role.get("node_binding") or "")
        if node_binding_filter is not None and node_binding != node_binding_filter:
            continue

        if role_type in DATA_ROLES:
            if role_name in supplied:
                continue
            accepted = [str(item) for item in (raw_role.get("accepted_data_roles") or [role_type])]
            if any(item not in DATA_ROLES for item in accepted):
                raise ValueError(f"template role {role_name!r} has unsupported accepted_data_roles")
            if primary_binding is None:
                primary_binding = node_binding
                primary_role_requirement = accepted
                if profile["primary_role"] not in accepted:
                    _append_reason(
                        reasons,
                        "data_role_incompatible",
                        f"Requires {', '.join(accepted)} data; this dataset is {profile['primary_role']}.",
                        role_name,
                    )
            elif node_binding != primary_binding or binding_mode == "separate_source":
                _append_reason(
                    reasons,
                    "additional_data_source_required",
                    f"Requires an additional {role_type} data source.",
                    role_name,
                )
            if raw_role.get("is_time_series") is True and not profile["ordered_samples"]:
                _append_reason(
                    reasons,
                    "ordered_samples_required",
                    "Requires an explicitly ordered evolution coordinate; arbitrary sample order is not admitted.",
                    role_name,
                )
            continue

        if role_type in {"Y_reference", "class_labels"}:
            expected = raw_role.get("target_type")
            if expected is None and role_type == "class_labels":
                expected = "categorical"
            required_target_type = str(expected) if expected is not None else None
            if role_name in supplied:
                supplied_type = supplied[role_name]
                if supplied_type is None or required_target_type is None or supplied_type == required_target_type:
                    continue
                _append_reason(
                    reasons,
                    _missing_target_code(required_target_type),
                    (
                        f"Requires {_target_label(required_target_type)}; the supplied target provides "
                        f"{_target_label(str(supplied_type))}."
                    ),
                    role_name,
                )
                continue
            if binding_mode == "separate_source" or (primary_binding is not None and node_binding != primary_binding):
                _append_reason(
                    reasons,
                    "separate_target_required",
                    _target_message(required_target_type, separate=True),
                    role_name,
                )
            elif profile["target_type"] is None:
                _append_reason(
                    reasons,
                    _missing_target_code(required_target_type),
                    _target_message(required_target_type),
                    role_name,
                )
            elif required_target_type is not None and profile["target_type"] != required_target_type:
                _append_reason(
                    reasons,
                    _missing_target_code(required_target_type),
                    (
                        f"Requires {_target_label(required_target_type)}; this dataset provides "
                        f"{_target_label(str(profile['target_type']))}."
                    ),
                    role_name,
                )
            continue

        code_and_message = {
            "wavelength_axis": ("wavelength_axis_required", "Requires a separate wavelength-axis source."),
            "validation_set": ("validation_set_required", "Requires a separate validation dataset."),
            "background_spectrum": ("background_spectrum_required", "Requires a separate background spectrum."),
            "sample_metadata": ("sample_metadata_required", "Requires separate sample metadata."),
        }.get(role_type)
        if role_name in supplied:
            continue
        if code_and_message is None:
            _append_reason(
                reasons,
                "unsupported_template_requirement",
                f"Template requirement {role_type or role_name!r} is not recognized.",
                role_name,
            )
        else:
            _append_reason(reasons, *code_and_message, role_name)

    if primary_binding is None and node_binding_filter is None:
        raise ValueError("template has no required primary data role")

    accepted_techniques = _primary_accepted_techniques(roles)
    technique_recommended = not accepted_techniques or any(
        _technique_matches(profile["technique"], accepted) for accepted in accepted_techniques
    )
    technique_required = any(
        isinstance(raw_role, Mapping)
        and raw_role.get("required", True)
        and raw_role.get("role_type") in DATA_ROLES
        and raw_role.get("technique_match") == "required"
        for raw_role in roles.values()
    )
    if technique_required and not technique_recommended:
        _append_reason(
            reasons,
            "technique_incompatible",
            (f"Requires {', '.join(accepted_techniques)} data; " f"the dataset technique is {profile['technique']}."),
            None,
        )

    incompatible = any(
        reason["code"] in {"data_role_incompatible", "technique_incompatible", "unsupported_template_requirement"}
        for reason in reasons
    )
    if status_authority != "ready":
        status: CompatibilityStatus = "pending"
        reasons.insert(
            0,
            {
                "code": "template_pending_qualification",
                "message": "This analysis template is pending scientific qualification.",
                "role": None,
            },
        )
    elif incompatible:
        status = "incompatible"
    elif reasons:
        status = "needs_input"
    else:
        status = "compatible"

    advisories: list[CompatibilityReason] = []
    if not technique_recommended and not technique_required:
        advisories.append(
            {
                "code": "technique_not_recommended",
                "message": (
                    f"This analysis recommends {', '.join(accepted_techniques)} data; "
                    f"the dataset technique is {profile['technique']}."
                ),
                "role": None,
            }
        )
    result = {
        "schema_version": COMPATIBILITY_SCHEMA,
        "scope": "structural",
        "status": status,
        "compatible": status == "compatible",
        "can_use_as_primary": not incompatible,
        "reason_codes": [reason["code"] for reason in reasons],
        "reasons": reasons,
        "requirements": {
            "accepted_primary_roles": primary_role_requirement,
            "target_type": required_target_type,
            "accepted_techniques": accepted_techniques,
        },
        "technique_recommended": technique_recommended,
        "advisory_codes": [advisory["code"] for advisory in advisories],
        "advisories": advisories,
    }
    result["display_group"] = compatibility_display_group(result)
    return result


def compatibility_display_group(decision: Mapping[str, Any]) -> CompatibilityDisplayGroup:
    """Project one canonical decision into the shared scientist-facing group."""

    status = decision.get("status")
    if status in {"compatible", "incompatible", "pending"}:
        return status  # type: ignore[return-value]
    if status != "needs_input":
        return "unavailable"
    codes = {str(code) for code in decision.get("reason_codes", [])}
    if any(code.endswith("_target_missing") or code == "target_missing" for code in codes):
        return "needs_target"
    return "needs_source"


def build_compatibility_matrix(
    datasets: Sequence[Mapping[str, Any]],
    templates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return a deterministic total matrix for identified datasets/templates."""

    matrix: list[dict[str, Any]] = []
    for dataset in sorted(datasets, key=lambda item: str(item["dataset_id"])):
        for template in sorted(templates, key=lambda item: str(item["slug"])):
            decision = evaluate_template_compatibility(dataset["analysis_profile"], template)
            matrix.append(
                {
                    "dataset_id": str(dataset["dataset_id"]),
                    "template_slug": str(template["slug"]),
                    **decision,
                }
            )
    return matrix


def build_dataset_analysis_readiness(
    dataset: Any,
    templates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize one admitted dataset against every active analysis starter."""

    try:
        profile = analysis_profile_from_dataset(dataset)
    except (KeyError, TypeError, ValueError):
        logger.warning("Dataset analysis metadata is incomplete", exc_info=True)
        return unavailable_dataset_analysis_readiness(
            code="analysis_profile_incomplete",
            message="Analysis matching is unavailable until the dataset target metadata is reconciled.",
            detail="The dataset target metadata is incomplete or invalid.",
        )
    return build_analysis_profile_readiness(profile, templates)


def build_analysis_profile_readiness(
    analysis_profile: Mapping[str, Any],
    templates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate one explicit structural profile through the canonical engine.

    This is also the preview authority used after a scientist selects a target
    in My Dataset. The saved-workflow admission path independently derives the
    profile from the admitted source, so this navigation projection cannot
    weaken execution-time checks.
    """

    try:
        profile = normalize_analysis_profile(analysis_profile)
    except (KeyError, TypeError, ValueError):
        logger.warning("Dataset analysis metadata is incomplete", exc_info=True)
        return unavailable_dataset_analysis_readiness(
            code="analysis_profile_incomplete",
            message="Analysis matching is unavailable until the dataset target metadata is reconciled.",
            detail="The dataset target metadata is incomplete or invalid.",
        )
    decisions: list[dict[str, Any]] = []
    counts = _empty_readiness_counts()
    diagnostics: list[dict[str, str]] = []
    for template in sorted(templates, key=lambda item: str(item["name"])):
        try:
            decision = evaluate_template_compatibility(profile, template)
        except (KeyError, TypeError, ValueError):
            logger.warning("Analysis template contract is invalid", exc_info=True)
            counts["unavailable"] += 1
            diagnostics.append(
                {
                    "code": "template_contract_invalid",
                    "message": f"Analysis {template.get('name') or template.get('slug') or 'unknown'} is unavailable.",
                    "detail": "The analysis template configuration is invalid.",
                }
            )
            continue
        runtime_readiness = template.get("runtime_readiness")
        runtime_unavailable = isinstance(runtime_readiness, Mapping) and runtime_readiness.get("ready") is False
        display_status = "unavailable" if runtime_unavailable else decision["display_group"]
        counts[display_status] += 1
        # File preview needs the named grouping and its explanation, not the
        # complete compatibility contract already available from the workflow
        # catalog endpoint.
        decisions.append(
            {
                "template_slug": str(template["slug"]),
                "template_name": str(template["name"]),
                "category": str(template.get("category") or "other"),
                "display_status": display_status,
                "status": decision["status"],
                "reason_codes": (
                    [str(value) for value in runtime_readiness.get("blockers", [])]
                    if runtime_unavailable
                    else decision["reason_codes"]
                ),
                "reasons": (
                    [
                        {
                            "code": str((runtime_readiness.get("blockers") or ["runtime_unavailable"])[0]),
                            "message": " ".join(str(value) for value in runtime_readiness.get("remediation", []))
                            or "The active server runtime cannot execute this analysis.",
                            "role": None,
                        }
                    ]
                    if runtime_unavailable
                    else decision["reasons"]
                ),
            }
        )
    return {
        "schema_version": "spectra-sherpa-dataset-analysis-readiness/1",
        "scope": "structural",
        "status": "partial" if diagnostics else "ready",
        "profile": profile,
        "template_count": len(templates),
        "counts": counts,
        "decisions": decisions,
        "diagnostics": diagnostics,
    }


def _empty_readiness_counts() -> dict[str, int]:
    return {
        "compatible": 0,
        "needs_target": 0,
        "needs_source": 0,
        "incompatible": 0,
        "pending": 0,
        "unavailable": 0,
    }


def unavailable_dataset_analysis_readiness(*, code: str, message: str, detail: str) -> dict[str, Any]:
    """Return the one fail-soft wire projection for derived readiness failures."""

    return {
        "schema_version": "spectra-sherpa-dataset-analysis-readiness/1",
        "scope": "structural",
        "status": "unavailable",
        "profile": None,
        "template_count": 0,
        "counts": _empty_readiness_counts(),
        "decisions": [],
        "diagnostics": [{"code": code, "message": message, "detail": detail}],
    }


def _text_fields(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"dataset analysis {name} must be canonical text")
    fields = [item.strip() for item in value]
    if len(fields) != len(set(fields)):
        raise ValueError(f"dataset analysis {name} must be unique")
    return fields


def _distinct_nonmissing_count(values: Any) -> int:
    """Count scalar levels without treating a constant annotation as a group."""

    try:
        candidates = list(values)
    except TypeError:
        return 0
    distinct: set[tuple[str, str]] = set()
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, float) and value != value:
            continue
        text = str(value).strip()
        if not text:
            continue
        distinct.add((type(value).__name__, text))
        if len(distinct) > 1:
            return len(distinct)
    return len(distinct)


def _append_reason(reasons: list[CompatibilityReason], code: str, message: str, role: str | None) -> None:
    if code not in {reason["code"] for reason in reasons}:
        reasons.append({"code": code, "message": message, "role": role})


def _missing_target_code(target_type: str | None) -> str:
    return f"{target_type}_target_missing" if target_type in {"continuous", "categorical"} else "target_missing"


def _target_label(target_type: str) -> str:
    return {
        "continuous": "a numeric target",
        "categorical": "categorical class labels",
        "ordinal": "an ordinal target",
    }.get(target_type, "a target")


def _target_message(target_type: str | None, *, separate: bool = False) -> str:
    qualifier = "a separate " if separate else ""
    if target_type is None:
        return f"Requires {qualifier}target data."
    return f"Requires {qualifier}{_target_label(target_type)}."


def _primary_accepted_techniques(roles: Mapping[str, Any]) -> list[str]:
    for role in roles.values():
        if isinstance(role, Mapping) and role.get("required", True) and role.get("role_type") in DATA_ROLES:
            return [str(item) for item in (role.get("accepted_techniques") or [])]
    return []


def _technique_matches(dataset_technique: str, accepted: str) -> bool:
    left = dataset_technique.strip().casefold()
    right = accepted.strip().casefold()
    return left == right or left in right or right in left


__all__ = [
    "COMPATIBILITY_SCHEMA",
    "build_analysis_profile_readiness",
    "build_compatibility_matrix",
    "build_dataset_analysis_readiness",
    "compatibility_display_group",
    "evaluate_template_compatibility",
    "normalize_analysis_profile",
    "unavailable_dataset_analysis_readiness",
]
