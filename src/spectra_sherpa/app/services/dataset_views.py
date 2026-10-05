"""Exact, reusable My Dataset selections shared by Workflow and Batch."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from spectra_sherpa.app.lib.target_authority import verify_target_authority
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset
from spectra_sherpa.app.services.model_application import LoadedProjectDataset
from spectra_sherpa.core.target_authority import admit_target_authority

DATASET_VIEW_SCHEMA = "spectrasherpa-dataset-view/1"


def receipt_sha256(receipt: dict) -> str:
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


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
