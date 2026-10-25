"""Exact supervision handoff for registered-reference singleton assembly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.target_authority import issue_target_authority
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    bind_sample_table_supervision,
)
from spectra_sherpa.core.target_authority import admit_target_authority


@dataclass(frozen=True)
class RegisteredSupervisionHandoff:
    """Verified selection carried across a custody-only singleton assembly."""

    scientific_sha256: str
    target_column: str
    target_type: str
    group_column: str | None


def _assembly_science_sha256(dataset: SherpaDataset) -> str:
    projection = dataset.scientific_projection(include_provenance=False)
    # Assembly may change the display title and operational provenance only.
    # The canonical projection includes X, masks, axes, annotations and units;
    # hashing it avoids allocating a second full source matrix.
    projection.pop("title")
    return hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def capture_registered_supervision(
    dataset: SherpaDataset, *, selected_asset_id: str | None
) -> RegisteredSupervisionHandoff | None:
    projection_id = dataset.get_extra("reference.projection_id")
    if not isinstance(projection_id, str) or projection_id != selected_asset_id:
        return None
    original = admit_attached_sample_table_supervision(dataset)
    if original is None:
        return None
    authority = admit_target_authority(original.record["target_authority"], optional=False)
    assert authority is not None
    return RegisteredSupervisionHandoff(
        scientific_sha256=_assembly_science_sha256(dataset),
        target_column=authority.column,
        target_type=authority.target_type,
        group_column=original.record["group_column"],
    )


def restore_registered_supervision(
    dataset: SherpaDataset, handoff: RegisteredSupervisionHandoff | None
) -> SherpaDataset:
    if handoff is None:
        return dataset
    if _assembly_science_sha256(dataset) != handoff.scientific_sha256:
        raise ValueError("Registered reference assembly changed the supervised observations")
    result = dataset.snapshot()
    authority = issue_target_authority(result, column=handoff.target_column, target_type=handoff.target_type)
    rebound = bind_sample_table_supervision(
        result,
        target_column=handoff.target_column,
        target_type=handoff.target_type,
        group_column=handoff.group_column,
        target_authority=authority,
    )
    # Custody rebinding is not a new target selection or computation. Preserve
    # the original selected response context and deterministic provenance, so
    # existing collection scientific digests (and trial grants) remain exact.
    # The re-admitted receipt, not a rewritten native selection, binds custody.
    result.meta["supervision_binding"] = {**rebound.record, "supervision_binding_sha256": rebound.digest}
    return result
