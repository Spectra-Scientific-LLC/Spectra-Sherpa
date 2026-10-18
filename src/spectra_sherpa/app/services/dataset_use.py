"""Portable disclosure of known dataset use, not an independence authority.

Records travel with evidence and qualification receipts. Names are labels only:
renaming a view cannot clear a known result reveal for the same identity. An
empty history cannot establish that someone has never inspected the data.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatasetUseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_identity: str | None = None
    sample_identity_digest: str | None = None
    source_receipt: str | None = None
    label: str | None = None
    basis: Literal["observed", "declared", "unknown"] = "unknown"
    role: Literal["development", "validation", "outlier_challenge", "unknown"] = "unknown"
    results_revealed: bool | None = None
    revealed_at: str | None = None
    influenced_development: bool | None = None
    affected_artifact_or_recipe: str | None = None
    known_fit_overlap_count: int | None = Field(None, ge=0)


def summarize_dataset_use(records: list[DatasetUseRecord]) -> dict:
    """Union positive knowledge; never let a later name/declaration erase it."""
    groups: dict[str, list[DatasetUseRecord]] = {}
    for index, record in enumerate(records):
        identity = record.dataset_identity or record.sample_identity_digest or f"unknown:{index}"
        groups.setdefault(identity, []).append(record)
    populations = []
    for identity, values in groups.items():
        populations.append(
            {
                "identity": None if identity.startswith("unknown:") else identity,
                "labels": sorted({r.label for r in values if r.label}),
                "basis": (
                    "observed"
                    if any(r.basis == "observed" for r in values)
                    else "declared" if any(r.basis == "declared" for r in values) else "unknown"
                ),
                "results_revealed": True if any(r.results_revealed is True for r in values) else None,
                "influenced_development": True if any(r.influenced_development is True for r in values) else None,
                "known_fit_overlap_count": max(
                    (r.known_fit_overlap_count for r in values if r.known_fit_overlap_count is not None), default=None
                ),
                "records": [r.model_dump() for r in values],
            }
        )
    return {
        "schema_version": "spectrasherpa-dataset-use/1",
        "populations": populations,
        "independence": "not_established_by_usage_history",
        "notice": (
            "Recorded use and user declarations do not prove that data has never been seen. "
            "Known reveal or development use survives renamed references. A separate later validation "
            "does not reopen a campaign or authorize another protected consultation."
        ),
    }


def dossier_dataset_use(dossier) -> dict:
    """Project the portable, digest-verified dossier; never create a second ledger.

    Export/import already retains the complete dossier, including recorded
    selection/fit identities. Display names are deliberately not identity.
    This says results exist, not that the laboratory population was unseen.
    """
    independence = dossier.calculation.get("independence") or {}
    comparisons = independence.get("comparisons") or []
    fit_overlaps = [
        set(row["specimen_overlap"])
        for row in comparisons
        if row.get("role") == "fit" and isinstance(row.get("specimen_overlap"), list)
    ]
    selected = any(row.get("role") == "selection" and bool(row.get("specimen_overlap")) for row in comparisons)
    return summarize_dataset_use(
        [
            DatasetUseRecord(
                dataset_identity=dossier.original_cohort_digest,
                sample_identity_digest=dossier.specimen_identity_digest,
                source_receipt=dossier.record_digest,
                basis="observed",
                role="validation",
                results_revealed=True,
                influenced_development=True if selected else None,
                affected_artifact_or_recipe=dossier.artifact_digest,
                known_fit_overlap_count=len(set().union(*fit_overlaps)) if fit_overlaps else None,
            )
        ]
    )


def imported_confirmation_dataset_use(history: dict | None) -> dict:
    """Read the existing closed portable history, without authenticating origin."""
    if history is None:
        return summarize_dataset_use([])
    from spectra_sherpa.sdk.canonical_confirmation_history import CanonicalConfirmationHistory

    verified = CanonicalConfirmationHistory.from_dict(history).as_dict()
    grant = verified.get("grant")
    if grant is None:
        return summarize_dataset_use([])
    return summarize_dataset_use(
        [
            DatasetUseRecord(
                dataset_identity=grant["confirmation_content_digest"],
                source_receipt=verified["content_digest"],
                basis="declared",
                role="validation",
                results_revealed=True if grant["valid_result_released"] else None,
                # Revealing a result alone does not prove it influenced later choices.
                influenced_development=None,
                affected_artifact_or_recipe=grant["capsule_digest"],
            )
        ]
    )
