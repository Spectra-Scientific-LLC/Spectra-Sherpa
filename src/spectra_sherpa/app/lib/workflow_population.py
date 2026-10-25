"""Source-owned workflow curation, separate from saved My Dataset curation.

Row references bind to one exact ordered scientific source. They are navigation
references, not specimen IDs: display labels never establish identity. The
typed sample axis remains the sole inclusion authority. Only its active rows
leave the source's ordinary output; the complete source remains inspectable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

OBSERVATION_REF = "workflow_observation_refs"
WORKFLOW_POPULATION_OPERATION = "spectrasherpa.workflow_population/1"
MAX_WORKFLOW_OBSERVATIONS = 100_000


class WorkflowExclusions(BaseModel):
    """A closed, source-bound workflow override (never a global dataset edit)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_refs: list[StrictStr] = Field(max_length=MAX_WORKFLOW_OBSERVATIONS)

    @model_validator(mode="after")
    def exact_references(self) -> WorkflowExclusions:
        if len(set(self.excluded_refs)) != len(self.excluded_refs):
            raise ValueError("Workflow observation references must be unique")
        if any(not ref or ref != ref.strip() for ref in self.excluded_refs):
            raise ValueError("Workflow observation references must be exact")
        return self


def canonical_exclusions(value: Any) -> dict[str, Any] | None:
    return None if value is None else WorkflowExclusions.model_validate(value).model_dump()


def workflow_exclusion_count(parameters: Mapping[str, Any]) -> int:
    """Summary-only projection shared by Advisor and canonical Guidance."""
    decision = canonical_exclusions(parameters.get("workflow_exclusions"))
    return 0 if decision is None else len(decision["excluded_refs"])


def source_population_outputs(
    dataset: SherpaDataset, *, node_id: str, exclusions: Any = None, source_binding: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Materialize before branching, retaining exact source/result row mapping.

    Restoring an override cannot restore a row excluded in My Dataset. Binding
    includes values, axes, target authority and ordered identities but excludes
    processing timestamps, so reruns are stable and source changes fail closed.
    """
    from spectra_sherpa.app.services.dag.io_contracts import extract_target_like
    from spectra_sherpa.app.services.dag.sample_subset_supervision import rebind_sample_subset_supervision
    from spectra_sherpa.app.services.dag.supervision_binding import (
        admit_attached_sample_table_supervision,
        bind_sample_table_supervision,
    )
    from spectra_sherpa.core.target_authority import admit_target_authority

    if dataset.ndim != 2:
        if exclusions is not None:
            raise ValueError("Workflow source curation requires a two-dimensional sample-feature matrix")
        # N-D sources retain all axis masks until their explicit projection;
        # reducing dim-0 here would silently change the recorded source shape.
        return {
            "default": dataset,
            "target": extract_target_like(dataset),
            "exclusions": {
                "schema_version": "spectrasherpa-workflow-population/1",
                "availability": "unavailable",
                "source_node_id": node_id,
                "source_count": dataset.n_samples,
                "rows": [],
                "reason": "Workflow source curation requires a two-dimensional sample-feature matrix.",
            },
        }
    observation_axis = dataset.get_observation_axis()
    navigation_unavailable = dataset.n_samples > MAX_WORKFLOW_OBSERVATIONS or (
        observation_axis is not None and not isinstance(observation_axis, SampleAxis)
    )
    if navigation_unavailable:
        if exclusions is not None:
            raise ValueError("Plot-driven source curation requires a sample axis within the 100000-observation budget")
        # A UI-navigation limit must never prevent an otherwise valid dataset
        # from loading, rewrite its axis, or bypass its existing inclusion.
        admit_attached_sample_table_supervision(dataset)
        mask = None if observation_axis is None else observation_axis.include_mask
        active = dataset
        if mask is not None and not all(mask):
            if not any(mask):
                raise ValueError("Keep at least one active workflow observation")
            active = dataset[np.asarray(mask, dtype=bool)]
            rebind_sample_subset_supervision(dataset, active)
        return {
            "default": active,
            "target": extract_target_like(active),
            "exclusions": {
                "schema_version": "spectrasherpa-workflow-population/1",
                "availability": "unavailable",
                "source_node_id": node_id,
                "source_count": dataset.n_samples,
                "active_count": active.n_samples,
                "rows": [],
                "reason": (
                    "Plot-driven curation requires a sample axis and at most 100000 source observations; "
                    "existing source inclusion is preserved."
                ),
            },
        }
    original_supervision = admit_attached_sample_table_supervision(dataset)
    # Prepared exports may carry typed navigation references from another
    # sheet. Re-scope them; the scientific projection deliberately omits them.
    dataset = dataset.copy()
    custody_fields = {
        "manifest_digest",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "dataset_view_sha256",
    }
    collection = dataset.meta.get("source_collection")
    custody = {
        key: value
        for key, value in (collection.items() if isinstance(collection, Mapping) else [])
        if key in custody_fields
    }
    from spectra_sherpa.core.spectra_meta import get_spectra_meta

    source_meta = get_spectra_meta(dataset)
    custom = source_meta.custom if source_meta is not None else None
    group_load = custom.get("group_load_params") if isinstance(custom, Mapping) else None
    if isinstance(group_load, Mapping) and isinstance(group_load.get("source_manifest"), Mapping):
        custody["group_manifest_digest"] = group_load["source_manifest"].get("manifest_digest")
    binding_fields = custody_fields | {
        "experiment_id",
        "file_id",
        "selected_file_ids",
        "asset_id",
        "stage",
        "dataset_view_id",
        "source_mode",
        "folder_path",
        "pattern",
        "recursive",
        "sort_by",
    }
    projection = {
        "science": dataset.scientific_projection(include_provenance=False),
        "custody": custody,
        "binding": {key: value for key, value in (source_binding or {}).items() if key in binding_fields},
    }
    digest = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    ids = sample_ids(dataset)
    refs = [f"{node_id}:{digest}:{i}" for i in range(dataset.n_samples)]
    decision = None if exclusions is None else WorkflowExclusions.model_validate(exclusions)
    if decision is not None and decision.source_digest != digest:
        raise ValueError(
            "Workflow exclusions belong to a different source. Restore or reselect the source observations."
        )
    excluded = set() if decision is None else set(decision.excluded_refs)
    if not excluded.issubset(refs):
        raise ValueError("Workflow exclusion contains an unknown source observation")
    full = dataset  # already detached above; do not copy the source matrix twice
    axis = full.sample_axis or SampleAxis(count=full.n_samples)
    base = list(axis.include_mask) if axis.include_mask is not None else [True] * full.n_samples
    mask = [bool(included) and ref not in excluded for included, ref in zip(base, refs)]
    if not any(mask):
        raise ValueError("Keep at least one active workflow observation")
    axis = axis.model_copy(
        deep=True,
        update={
            "include_mask": axis.include_mask if all(mask) else mask,
            "workflow_observation_refs": refs,
        },
    )
    full.sample_axis = axis
    if original_supervision is not None:
        # Input was re-admitted before source materialization. This trusted
        # source operation changes only inclusion and navigation references;
        # preserve the original response/group authority, never issue a new one.
        authority = admit_target_authority(original_supervision.record["target_authority"], optional=False)
        rebound = bind_sample_table_supervision(
            full,
            target_column=authority.column,
            target_type=authority.target_type,
            group_column=original_supervision.record["group_column"],
            target_authority=authority,
        )
        full.meta["supervision_binding"] = {**rebound.record, "supervision_binding_sha256": rebound.digest}
    active = full if all(mask) else full[np.asarray(mask, dtype=bool)]
    if active is not full:
        rebind_sample_subset_supervision(full, active)
        active.provenance.append(
            op_id=WORKFLOW_POPULATION_OPERATION,
            node_id=node_id,
            parameters={
                "source_digest": digest,
                "source_count": full.n_samples,
                "active_count": sum(mask),
                "excluded_source_rows": [i + 1 for i, flag in enumerate(mask) if not flag],
                "scope": "workflow_source_before_all_branches",
            },
            input_shape=full.shape,
            output_shape=active.shape,
            state_effects=["workflow_population_curated"],
        )
    result_rows = iter(range(1, sum(mask) + 1))
    labels = list(axis.labels) if axis.labels is not None else [None] * full.n_samples
    state = {
        "schema_version": "spectrasherpa-workflow-population/1",
        "source_node_id": node_id,
        "source_digest": digest,
        "identity_basis": "typed_sample_id" if ids is not None else "source_bound_row",
        "source_count": full.n_samples,
        "active_count": sum(mask),
        "workflow_excluded_count": len(excluded),
        "rows": [
            {
                "observation_ref": ref,
                "source_row": i + 1,
                "sample_id": None if ids is None else ids[i],
                "sample_label": labels[i],
                "included": mask[i],
                "source_included": bool(base[i]),
                "workflow_excluded": ref in excluded,
                "result_row": next(result_rows) if mask[i] else None,
            }
            for i, ref in enumerate(refs)
        ],
    }
    state["data"] = state["rows"]  # canonical structured-record table projection
    state["metadata"] = {
        "column_names": [
            "source_row",
            "sample_label",
            *(["sample_id"] if ids else []),
            "included",
            "result_row",
            "source_included",
            "workflow_excluded",
        ]
    }
    return {"default": active, "target": extract_target_like(active), "__source_population": full, "exclusions": state}
