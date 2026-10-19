"""Exact, reusable My Dataset selections shared by Workflow and Batch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.target_authority import verify_target_authority
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset
from spectra_sherpa.core.target_authority import admit_target_authority


@dataclass
class LoadedProjectDataset:
    """Portable admitted source binding shared by application and SDK execution."""

    dataset: SherpaDataset
    experiment_id: int
    experiment_name: str
    project_id: int | None
    file_ids: list[int]
    stage: str
    asset_id: str | None
    source_manifest_sha256: str
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str | None = None


CURATED_VIEW_SCHEMA = "spectrasherpa-dataset-view/2"

DATASET_VIEW_SCHEMA = "spectrasherpa-dataset-view/1"


def receipt_sha256(receipt: dict) -> str:
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def selection_file_ids_match(receipt: dict, selected_file_ids: list[int] | None) -> bool:
    """An all-files receipt may execute its captured files as an explicit scope."""
    return selected_file_ids == receipt["selected_file_ids"] or (
        receipt["selected_file_ids"] is None and selected_file_ids == receipt["file_ids"]
    )


def selection_receipt(
    loaded: LoadedProjectDataset,
    *,
    selected_file_ids: list[int] | None,
    target_authority: object = None,
    group_column: str | None = None,
) -> dict:
    """Capture the admitted cohort, not a recipe that can drift on reload."""

    authority = admit_target_authority(target_authority)
    if group_column and authority is None:
        raise ValueError("A validation group requires a selected target")
    if authority is not None:
        verify_target_authority(loaded.dataset, authority)
        # This also validates the selected target/group against the admitted
        # response or portable sample table before the view can be saved.
        attach_selected_target_dataset(
            loaded.dataset,
            target_type=authority.target_type,
            target_column=authority.column,
            group_column=group_column or "",
            node_id="dataset-view-admission",
            target_authority=authority,
        )
    n_samples = loaded.dataset.n_samples
    sample_axis = loaded.dataset.sample_axis
    mask = (
        np.asarray(sample_axis.include_mask, dtype=bool)
        if sample_axis is not None and sample_axis.include_mask is not None
        else np.ones(n_samples, dtype=bool)
    )
    if mask.shape != (n_samples,) or not mask.any():
        raise ValueError("A saved view requires an exact non-empty included-sample cohort")
    return {
        "schema_version": DATASET_VIEW_SCHEMA,
        "experiment_id": loaded.experiment_id,
        "project_id": loaded.project_id,
        "stage": loaded.stage,
        "selected_file_ids": selected_file_ids,
        "file_ids": loaded.file_ids,
        "asset_id": loaded.asset_id,
        "source_manifest_sha256": loaded.source_manifest_sha256,
        "source_files": loaded.dataset.meta["source_collection"]["files"],
        "collection_definition_sha256": loaded.collection_definition_sha256,
        "scientific_collection_sha256": loaded.scientific_collection_sha256,
        "n_samples": n_samples,
        "included_count": int(mask.sum()),
        "included_sample_mask_hex": np.packbits(mask, bitorder="little").tobytes().hex(),
        "target_authority": authority.canonical_dict() if authority is not None else None,
        "group_column": group_column or None,
    }


def verify_selection_receipt(loaded: LoadedProjectDataset, receipt: dict) -> LoadedProjectDataset:
    """Fail closed if files, projection, or included specimens have changed."""

    if receipt.get("schema_version") == CURATED_VIEW_SCHEMA:
        base = receipt.get("source_selection", {})
        verify_selection_receipt(loaded, base)
        from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

        rows = verified_source_observations(loaded.dataset)
        if rows != receipt.get("observations"):
            raise ValueError("Saved curation no longer matches the exact source rows")
        excluded = receipt.get("excluded_ids")
        if not isinstance(excluded, list) or excluded != [r["sample_id"] for r in rows if r["sample_id"] in excluded]:
            raise ValueError("Saved curation has an invalid excluded cohort")
        observed = _curated_receipt(base, rows, excluded, receipt.get("decision"))
        if observed != receipt:
            raise ValueError("Saved curation definition changed")
        return loaded
    if receipt.get("schema_version") != DATASET_VIEW_SCHEMA:
        raise ValueError("Saved dataset view uses an unsupported definition")
    observed = selection_receipt(
        loaded,
        selected_file_ids=receipt.get("selected_file_ids"),
        target_authority=receipt.get("target_authority"),
        group_column=receipt.get("group_column"),
    )
    if observed != receipt:
        raise ValueError("Saved dataset view no longer matches its exact source and included samples")
    return loaded


def materialize_selection_receipt(loaded: LoadedProjectDataset, receipt: dict) -> LoadedProjectDataset:
    """Verify and apply a saved definition's target/group selection once."""
    from dataclasses import replace

    verify_selection_receipt(loaded, receipt)
    authority = admit_target_authority(receipt.get("target_authority"))
    dataset = loaded.dataset
    if authority is not None:
        dataset = attach_selected_target_dataset(
            loaded.dataset,
            target_type=authority.target_type,
            target_column=authority.column,
            group_column=receipt.get("group_column") or "",
            node_id="dataset-view-application",
            target_authority=authority,
        )
    if receipt.get("schema_version") == CURATED_VIEW_SCHEMA:
        from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import filter_samples_dataset

        mask = _unpack_mask(receipt)
        # Filter verified row positions without rewriting the source inclusion
        # mask, which is part of any attached supervision's scientific identity.
        source_role = str(dataset.data_role)
        dataset = filter_samples_dataset(
            dataset,
            field="sample_index",
            pattern=",".join(str(index + 1) for index in np.flatnonzero(mask)),
            match_mode="exact",
            case_sensitive=True,
            invert=False,
            sample_table_column="",
            allow_empty=False,
            intensity_metric="mean",
            intensity_operator="gt",
            intensity_threshold=0.0,
            intensity_upper_threshold=0.0,
            filter_values=None,
            node_id="dataset-view-curation",
        )
        if source_role == "X_hsi":
            dataset.data_role = "X_spectra"
        dataset.meta["dataset_curation"] = {
            "selection_sha256": receipt_sha256(receipt),
            "excluded_ids": receipt["excluded_ids"],
            "decision": receipt["decision"],
            "review_context": receipt["review_context"],
        }
    return replace(loaded, dataset=dataset)


def _unpack_mask(receipt: dict) -> np.ndarray:
    return np.unpackbits(
        np.frombuffer(bytes.fromhex(receipt["included_sample_mask_hex"]), dtype=np.uint8), bitorder="little"
    )[: receipt["n_samples"]].astype(bool)


def _curated_receipt(base: dict, rows: list[dict], excluded: list[str], decision: dict) -> dict:
    if (
        not isinstance(decision, dict)
        or set(decision)
        != {
            "action",
            "sample_ids",
            "reason",
            "parent_view_id",
            "parent_sha256",
            "review_origin",
            "inherited_review_context",
        }
        or decision["action"] not in {"exclude", "restore"}
        or not isinstance(decision["reason"], str)
        or not decision["reason"].strip()
        or len(decision["reason"]) > 2000
    ):
        raise ValueError("A curation revision requires an explicit reasoned decision")
    inherited = decision.get("inherited_review_context") or {"post_review": False, "heldout_inspected": False}
    if set(inherited) != {"post_review", "heldout_inspected"} or any(type(v) is not bool for v in inherited.values()):
        raise ValueError("Invalid inherited diagnostic review context")
    origin = decision.get("review_origin") or {}
    review_context = {key: inherited[key] or bool(origin.get(key)) for key in inherited}
    mask = _unpack_mask(base)
    source_ids = [r["sample_id"] for r in rows]
    if len(mask) != len(rows) or any(identity not in source_ids for identity in excluded):
        raise ValueError("Curation does not match its original population")
    if any(identity not in source_ids or not mask[source_ids.index(identity)] for identity in excluded):
        raise ValueError("Original source exclusions cannot be changed by curation")
    mask &= np.asarray([identity not in excluded for identity in source_ids], dtype=bool)
    if not mask.any():
        raise ValueError("Keep at least one included observation")
    return {
        **base,
        "schema_version": CURATED_VIEW_SCHEMA,
        "source_selection": base,
        "observations": rows,
        "excluded_ids": excluded,
        "decision": decision,
        "review_context": review_context,
        "included_count": int(mask.sum()),
        "included_sample_mask_hex": np.packbits(mask, bitorder="little").tobytes().hex(),
    }


def curation_receipt(
    loaded: LoadedProjectDataset,
    parent: dict,
    *,
    parent_view_id: int | None,
    action: str,
    sample_ids: list[str],
    reason: str,
    review_origin: dict | None = None,
) -> dict:
    from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

    verify_selection_receipt(loaded, parent)
    base = parent.get("source_selection", parent)
    rows = verified_source_observations(loaded.dataset)
    ids = [row["sample_id"] for row in rows]
    source_mask = _unpack_mask(base)
    if not sample_ids or len(set(sample_ids)) != len(sample_ids) or any(i not in ids for i in sample_ids):
        raise ValueError("Select exact, unique source observations")
    if any(not source_mask[ids.index(i)] for i in sample_ids):
        raise ValueError("Original source exclusions are immutable; only curation exclusions can be restored")
    previous = set(parent.get("excluded_ids", []))
    chosen = set(sample_ids)
    if action == "exclude":
        if chosen & previous:
            raise ValueError("One or more observations are already excluded in this definition")
        excluded = previous | chosen
    elif action == "restore":
        if not chosen <= previous:
            raise ValueError("Restore only observations excluded by this curation history")
        excluded = previous - chosen
    else:
        raise ValueError("Choose exclude or restore")
    return _curated_receipt(
        base,
        rows,
        [i for i in ids if i in excluded],
        {
            "action": action,
            "sample_ids": [i for i in ids if i in chosen],
            "reason": reason.strip(),
            "parent_view_id": parent_view_id,
            "parent_sha256": receipt_sha256(parent),
            "review_origin": review_origin,
            "inherited_review_context": parent.get("review_context"),
        },
    )


def review_curation_binding(dataset, parameters: dict) -> dict | None:
    """Transfer chart selections only with original source and native row custody."""
    from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

    try:
        rows = verified_source_observations(dataset)
    except ValueError:
        return None
    source = dataset.meta.get("source_collection", {})
    scientific = source.get("scientific_collection_sha256")
    manifest = source.get("manifest_digest")
    if not scientific or not manifest or not parameters.get("experiment_id"):
        return None
    return {
        "experiment_id": int(parameters["experiment_id"]),
        "stage": parameters.get("stage") or "raw",
        "selected_file_ids": [int(v) for v in parameters.get("selected_file_ids", [])] or None,
        "asset_id": parameters.get("asset_id") or None,
        "target_authority": parameters.get("target_authority") or None,
        "group_column": parameters.get("group_column") or None,
        "parent_view_id": parameters.get("dataset_view_id") or None,
        "parent_sha256": parameters.get("dataset_view_sha256") or None,
        "source_manifest_sha256": manifest,
        "collection_definition_sha256": source.get("collection_definition_sha256"),
        "scientific_collection_sha256": scientific,
        "observations": rows,
    }
