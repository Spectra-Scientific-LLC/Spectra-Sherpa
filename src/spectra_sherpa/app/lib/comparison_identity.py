"""Optional comparison identity, without rewriting source scientific payloads.

Numerical fitting and display do not require identity-qualified pairing. Actual
identity joins still use the strict sample_identity authority directly.
"""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.lib.sample_identity import sample_ids

LEGACY_IDENTITY_REASON = (
    "Sample identity unavailable: this legacy importer has no independently retained identity-origin proof. "
    "Numerical results remain available; paired-population comparison is not qualified."
)
INVALID_IDENTITY_REASON = (
    "Sample identity unavailable: declared sample_id values are not unique, nonblank, aligned identities. "
    "Numerical results remain available; paired-population comparison is not qualified."
)


def _source_format(identity: Any) -> str | None:
    return identity.get("source_format") if isinstance(identity, dict) else getattr(identity, "source_format", None)


def comparison_sample_ids(dataset: Any) -> tuple[list[str] | None, str | None]:
    """Admit IDs for optional presentation; never mutate or mint source IDs.

    The current native DSO/process-log parsers do not declare observation IDs.
    Their historical label-derived columns remain in the serialized source for
    saved-selection compatibility. Unique labels alone cannot certify origin.
    """
    metadata = getattr(dataset, "meta", {}) or {}
    identities = [getattr(dataset, "source_identity", None)]
    members = metadata.get("source_member_metadata")
    if isinstance(members, list):
        identities.extend(member.get("source_identity") for member in members if isinstance(member, dict))
    provenance = getattr(dataset, "provenance", None)
    operations = getattr(provenance, "operations", None)
    if operations is None and isinstance(provenance, list):
        operations = [entry.get("op_id") for entry in provenance if isinstance(entry, dict)]
    legacy_provenance = any(op in {"import.matlab_dso", "import.matlab_process_log"} for op in operations or [])
    if legacy_provenance or any(
        _source_format(identity) in {"eigenvector-dso", "matlab-process-log"} for identity in identities
    ):
        return None, LEGACY_IDENTITY_REASON
    try:
        return sample_ids(dataset), None
    except ValueError:
        return None, INVALID_IDENTITY_REASON
