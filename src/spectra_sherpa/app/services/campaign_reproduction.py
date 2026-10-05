"""Local, bounded reference reproduction using the public SDK contract."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from spectra_sherpa.sdk.campaign_review import CampaignReviewPackage
from spectra_sherpa.sdk.canonical_public_fixture import load_registered_reference_fixture
from spectra_sherpa.sdk.canonical_reproduction import reproduce_canonical_project


def reproduce_reference_upload(
    *,
    package_bytes: bytes,
    fixture_bytes: bytes,
    keys_bytes: bytes,
    projection_id: str,
    expected_package_sha256: str,
    max_bytes: int,
) -> dict:
    """Never fetch provider data or infer successful science from import integrity."""
    review = CampaignReviewPackage.from_archive(package_bytes, max_uncompressed_bytes=max_bytes)
    if review.application.archive_sha256 != expected_package_sha256:
        raise ValueError("Selected package does not match this imported project")
    try:
        keys = json.loads(keys_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Publisher verification keys must be valid JSON") from exc
    if not isinstance(keys, dict):
        raise ValueError("Publisher verification keys must be a JSON object")
    # A server-created path avoids trusting upload names or persisting source data.
    with TemporaryDirectory(prefix="sherpa-local-reproduction-") as temporary:
        source = Path(temporary) / "reference"
        source.write_bytes(fixture_bytes)
        local = load_registered_reference_fixture(source, review.application, projection_id=projection_id)
        report = reproduce_canonical_project(
            review.application,
            fixture=local.capability,
            split_plan=local.split_plan,
            publisher_attestation=review.publisher_attestation.as_dict(),
            publisher_trust_anchors=keys,
        )
    return report.as_dict()
