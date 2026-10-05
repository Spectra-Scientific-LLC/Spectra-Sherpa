"""Issue and verify target authorities against materialized datasets."""

from __future__ import annotations

from collections.abc import Mapping

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.core.target_authority import TargetAuthority, TargetAuthorityType


def _digest(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return None


def dataset_target_source_digest(dataset: SherpaDataset) -> str:
    """Return the exact source identity to which target selection is bound."""

    source_collection = dataset.meta.get("source_collection")
    if isinstance(source_collection, Mapping):
        scientific = _digest(source_collection.get("scientific_collection_sha256"))
        if scientific is not None:
            return scientific
        manifest = _digest(source_collection.get("manifest_digest"))
        if manifest is not None:
            return manifest

    ingestion = dataset.get_extra("ingestion.authority")
    if isinstance(ingestion, Mapping):
        members = ingestion.get("source_members")
        if isinstance(members, list) and len(members) == 1 and isinstance(members[0], Mapping):
            member = _digest(members[0].get("sha256"))
            if member is not None:
                return member
    raise ValueError("dataset does not expose an exact source digest for target selection")


def _target_units(dataset: SherpaDataset, column: str) -> str | None:
    context = dataset.target_context
    if context is None:
        return None
    selected = context.selected_authority
    if selected is not None and selected.column == column:
        return selected.units
    names = list(context.target_names or ())
    if context.target_name == column or (len(names) == 1 and names[0] == column):
        return context.target_units
    # A shared unit remains authoritative for a declared multi-response set.
    if column in names and context.target_units is not None:
        return context.target_units
    return None


def issue_target_authority(
    dataset: SherpaDataset,
    *,
    column: str,
    target_type: TargetAuthorityType,
    source_digest: str | None = None,
) -> TargetAuthority:
    """Create one closed authority from an admitted dataset and selection."""

    return TargetAuthority(
        column=column,
        target_type=target_type,
        units=_target_units(dataset, column),
        source_digest=source_digest or dataset_target_source_digest(dataset),
    )


def verify_target_authority(
    dataset: SherpaDataset,
    authority: TargetAuthority,
    *,
    source_digest: str | None = None,
) -> TargetAuthority:
    """Require an authority to reproduce from the exact admitted dataset."""

    observed = issue_target_authority(
        dataset,
        column=authority.column,
        target_type=authority.target_type,
        source_digest=source_digest,
    )
    if observed != authority:
        raise ValueError("target authority does not match the admitted dataset source, type, and units")
    return observed


__all__ = [
    "dataset_target_source_digest",
    "issue_target_authority",
    "verify_target_authority",
]
