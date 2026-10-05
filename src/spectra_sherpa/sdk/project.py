"""Offline inspection and byte-exact re-export of canonical projects.

This facade does not execute science or contact a Workbench/server. It admits
the same closed project package used by managed export and keeps package
integrity, publisher identity, validation reproduction, and application
reproduction as four separate outcomes.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from spectra_sherpa.core.file_io import open_regular_readonly

from .canonical_project import CanonicalProjectPackage, CanonicalProjectPackageError

if TYPE_CHECKING:
    from .canonical_reproduction import CanonicalReproductionReport

MAX_PROJECT_FILE_BYTES = 512 * 1024 * 1024


class ProjectIOError(ValueError):
    """A canonical project cannot be read, inspected, compared, or written."""


def read_bounded_regular_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    """Read one bounded regular-file snapshot without following a leaf symlink."""

    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise ProjectIOError(f"{label} is unavailable") from exc
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or not 1 <= status.st_size <= max_bytes:
            raise ProjectIOError(f"{label} size is outside the supported bound")
        chunks: list[bytes] = []
        remaining = status.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ProjectIOError(f"{label} changed during admission")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ProjectIOError(f"{label} changed during admission")
        return b"".join(chunks)
    except OSError as exc:
        raise ProjectIOError(f"{label} is unavailable") from exc
    finally:
        os.close(descriptor)


def load_bounded_json_object(source: str | Path, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    """Read one local governance document from a single bounded descriptor."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ProjectIOError("Campaign Review verification document has duplicate JSON keys")
            output[key] = value
        return output

    raw = read_bounded_regular_file(
        Path(source).expanduser(),
        max_bytes=max_bytes,
        label="Campaign Review verification document",
    )
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectIOError("Campaign Review verification document is invalid") from exc
    if not isinstance(value, dict):
        raise ProjectIOError("Campaign Review verification document must be an object")
    return value


@dataclass(frozen=True)
class VerificationOutcome:
    """One independently stated project-verification outcome."""

    status: str
    reason: str | None

    def as_dict(self) -> dict[str, str | None]:
        """Return the bounded status and optional explanatory reason."""

        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class ProjectVerificationOutcomes:
    """The four non-interchangeable verification statements for a project."""

    integrity_verified: VerificationOutcome
    publisher_authenticated: VerificationOutcome
    validation_reproduced: VerificationOutcome
    application_reproduced: VerificationOutcome

    def as_dict(self) -> dict[str, dict[str, str | None]]:
        """Return all four outcomes without a generic ``verified`` shortcut."""

        return {
            "integrity_verified": self.integrity_verified.as_dict(),
            "publisher_authenticated": self.publisher_authenticated.as_dict(),
            "validation_reproduced": self.validation_reproduced.as_dict(),
            "application_reproduced": self.application_reproduced.as_dict(),
        }


@dataclass(frozen=True)
class ProjectInspection:
    """A data-free identity projection of one admitted canonical project."""

    package_sha256: str
    project_name: str
    package_status: str
    campaign_id: str
    candidate_id: str
    capsule_digest: str
    artifact_digest: str
    application_plan_digest: str
    graph_digest: str
    validation_execution_digest: str
    local_model_record_digest: str
    campaign_evidence_digest: str
    confirmation_history_digest: str
    outcomes: ProjectVerificationOutcomes

    def as_dict(self) -> dict[str, Any]:
        """Return the inspection as JSON-compatible, data-free values."""

        return {
            "package_sha256": self.package_sha256,
            "project_name": self.project_name,
            "package_status": self.package_status,
            "campaign_id": self.campaign_id,
            "candidate_id": self.candidate_id,
            "capsule_digest": self.capsule_digest,
            "artifact_digest": self.artifact_digest,
            "application_plan_digest": self.application_plan_digest,
            "graph_digest": self.graph_digest,
            "validation_execution_digest": self.validation_execution_digest,
            "local_model_record_digest": self.local_model_record_digest,
            "campaign_evidence_digest": self.campaign_evidence_digest,
            "confirmation_history_digest": self.confirmation_history_digest,
            "outcomes": self.outcomes.as_dict(),
        }


@dataclass(frozen=True)
class ProjectComparison:
    """Field-by-field comparison of two independently admitted projects."""

    left_package_sha256: str
    right_package_sha256: str
    archive_bytes_identical: bool
    scientific_identity_match: bool
    identity_matches: Mapping[str, bool]
    differing_identities: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return explicit identity comparisons without a generic verdict."""

        return {
            "left_package_sha256": self.left_package_sha256,
            "right_package_sha256": self.right_package_sha256,
            "archive_bytes_identical": self.archive_bytes_identical,
            "scientific_identity_match": self.scientific_identity_match,
            "identity_matches": dict(self.identity_matches),
            "differing_identities": list(self.differing_identities),
        }


def load(source: CanonicalProjectPackage | bytes | str | Path) -> CanonicalProjectPackage:
    """Read and fully admit one current canonical project from local input.

    URLs are rejected. Paths are caller-selected and bounded before reading;
    package content cannot redirect this function to another location.
    """

    if isinstance(source, CanonicalProjectPackage):
        raw = source.archive
    elif isinstance(source, bytes):
        raw = source
    elif isinstance(source, (str, Path)):
        if isinstance(source, str) and source.lower().startswith(("http://", "https://")):
            raise ProjectIOError("canonical project loading accepts local paths only; download the export first")
        raw = read_bounded_regular_file(
            Path(source),
            max_bytes=MAX_PROJECT_FILE_BYTES,
            label="canonical project file",
        )
    else:
        raise TypeError("canonical project source must be package bytes or an explicit local path")
    if not 1 <= len(raw) <= MAX_PROJECT_FILE_BYTES:
        raise ProjectIOError("canonical project file size is outside the supported bound")
    try:
        return CanonicalProjectPackage.from_archive(raw)
    except CanonicalProjectPackageError as exc:
        raise ProjectIOError("canonical project integrity admission failed") from exc


def inspect_project(
    source: CanonicalProjectPackage | bytes | str | Path,
    *,
    reproduction_report: CanonicalReproductionReport | Mapping[str, Any] | None = None,
) -> ProjectInspection:
    """Inspect identities and four distinct verification outcomes offline."""

    package = load(source)
    metadata = package.project_payload["metadata"]["canonical_project"]
    request = package.capsule.payload["admitted_request"]
    campaign = package.campaign_evidence.payload["campaign"]
    return ProjectInspection(
        package_sha256=package.archive_sha256,
        project_name=package.project_payload["name"],
        package_status=metadata["package_status"],
        campaign_id=campaign["campaign_id"],
        candidate_id=request["candidate_id"],
        capsule_digest=package.capsule.capsule_digest,
        artifact_digest=package.artifact.artifact_digest,
        application_plan_digest=package.application_plan.application_plan_digest,
        graph_digest=metadata["graph_digest"],
        validation_execution_digest=metadata["validation_execution_digest"],
        local_model_record_digest=package.local_model_record.record_digest,
        campaign_evidence_digest=package.campaign_evidence.content_digest,
        confirmation_history_digest=package.confirmation_history.content_digest,
        outcomes=_outcomes(package, reproduction_report),
    )


def compare_projects(
    left: CanonicalProjectPackage | bytes | str | Path,
    right: CanonicalProjectPackage | bytes | str | Path,
) -> ProjectComparison:
    """Compare package bytes and every portable scientific identity."""

    left_inspection = inspect_project(left)
    right_inspection = inspect_project(right)
    fields = (
        "campaign_id",
        "candidate_id",
        "capsule_digest",
        "artifact_digest",
        "application_plan_digest",
        "graph_digest",
        "validation_execution_digest",
        "local_model_record_digest",
        "campaign_evidence_digest",
        "confirmation_history_digest",
    )
    matches = {field: getattr(left_inspection, field) == getattr(right_inspection, field) for field in fields}
    differences = tuple(field for field, matches_field in matches.items() if not matches_field)
    return ProjectComparison(
        left_package_sha256=left_inspection.package_sha256,
        right_package_sha256=right_inspection.package_sha256,
        archive_bytes_identical=left_inspection.package_sha256 == right_inspection.package_sha256,
        scientific_identity_match=not differences,
        identity_matches=MappingProxyType(dict(matches)),
        differing_identities=differences,
    )


def reexport(
    source: CanonicalProjectPackage | bytes | str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Verify and atomically write the exact canonical project bytes."""

    package = load(source)
    target = Path(destination)
    if target.exists() and not overwrite:
        raise ProjectIOError("canonical project destination exists; pass overwrite=True to replace it")
    if not target.parent.is_dir():
        raise ProjectIOError("canonical project destination directory does not exist")
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(package.archive)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        raise ProjectIOError("canonical project could not be written") from exc
    return target


def _outcomes(
    package: CanonicalProjectPackage,
    report_value: CanonicalReproductionReport | Mapping[str, Any] | None,
) -> ProjectVerificationOutcomes:
    if report_value is None:
        return ProjectVerificationOutcomes(
            integrity_verified=VerificationOutcome("passed", None),
            publisher_authenticated=VerificationOutcome("not_provided", "publisher_attestation_not_supplied"),
            validation_reproduced=VerificationOutcome("not_run", "reproduction_report_not_supplied"),
            application_reproduced=VerificationOutcome("not_run", "reproduction_report_not_supplied"),
        )
    from .canonical_reproduction import CanonicalReproductionReport

    report = (
        report_value
        if isinstance(report_value, CanonicalReproductionReport)
        else CanonicalReproductionReport.from_dict(report_value)
    )
    expected = {
        "package_sha256": package.archive_sha256,
        "capsule_digest": package.capsule.capsule_digest,
        "artifact_digest": package.artifact.artifact_digest,
        "application_plan_digest": package.application_plan.application_plan_digest,
    }
    if any(report.payload[field] != value for field, value in expected.items()):
        raise ProjectIOError("reproduction report belongs to another canonical project")
    return ProjectVerificationOutcomes(
        integrity_verified=_outcome(report.payload["integrity_verified"]),
        publisher_authenticated=_outcome(report.payload["publisher_authenticated"]),
        validation_reproduced=_outcome(report.payload["validation_reproduced"]),
        application_reproduced=_outcome(report.payload["application_reproduced"]),
    )


def _outcome(value: Mapping[str, Any]) -> VerificationOutcome:
    reason = value.get("reason")
    return VerificationOutcome(status=str(value["status"]), reason=reason if isinstance(reason, str) else None)


__all__ = [
    "MAX_PROJECT_FILE_BYTES",
    "ProjectComparison",
    "ProjectIOError",
    "ProjectInspection",
    "ProjectVerificationOutcomes",
    "VerificationOutcome",
    "compare_projects",
    "inspect_project",
    "load",
    "load_bounded_json_object",
    "read_bounded_regular_file",
    "reexport",
]
