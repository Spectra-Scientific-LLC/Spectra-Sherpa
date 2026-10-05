#!/usr/bin/env python3
"""Validate protected-benchmark governance and prove artifact absence.

The committed registry contains only opaque governance references and
cryptographic attestations. This verifier makes that boundary executable:

* JSON documents must satisfy the published closed schemas.
* Status history must prove the current status and any claim promotion.
* Public fixtures cannot be relabeled as protected entries.
* A public-performance preregistration must name a claim-eligible entry.
* Files and members of built archives may not match protected artifact
  digests.

An empty registry is valid P1 machinery, not P2 evidence. Once P2 adds a real
entry, the same scan starts enforcing its data-absence attestations without a
workflow change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from jsonschema import Draft7Validator, FormatChecker

PROTECTED_STATUSES = frozenset({"provisional_internal", "claim_eligible", "retired"})
_ALLOWED_TRANSITIONS = frozenset(
    {
        ("provisional_internal", "claim_eligible"),
        ("provisional_internal", "retired"),
        ("claim_eligible", "retired"),
    }
)
_REQUIRED_PROHIBITED_USES = frozenset(
    {
        "workflow_development",
        "model_selection_tuning",
        "raw_data_repository_distribution",
    }
)
_ARTIFACT_DIGEST_FIELDS = (
    "dataset_digest",
    "labels_digest",
    "development_split_digest",
    "confirmation_split_digest",
)
_SKIP_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)
_ARCHIVE_SUFFIXES = frozenset({".bz2", ".gz", ".tar", ".whl", ".xz", ".zip"})


class BenchmarkGovernanceError(ValueError):
    """Raised when benchmark governance or absence verification fails."""


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object with a stable governance-oriented error."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkGovernanceError(f"cannot load JSON document {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkGovernanceError(f"JSON document must be an object: {path}")
    return payload


def validate_registry(registry: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """Validate the closed registry schema and status-transition semantics."""
    _validate_schema_instance(registry, schema, document_name="protected benchmark registry")
    entries = registry["entries"]
    observed_ids: set[str] = set()
    for index, entry in enumerate(entries):
        benchmark_id = entry["benchmark_id"]
        if benchmark_id in observed_ids:
            raise BenchmarkGovernanceError(f"duplicate protected benchmark_id: {benchmark_id!r}")
        observed_ids.add(benchmark_id)
        _validate_entry_semantics(entry, index=index)


def validate_preregistration(
    preregistration: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
    document_digest: str | None = None,
) -> None:
    """Validate a frozen protocol and, when supplied, its registry binding."""
    _validate_schema_instance(preregistration, schema, document_name="benchmark preregistration")
    if registry is None:
        return
    if document_digest is None:
        raise BenchmarkGovernanceError("registry-bound preregistration validation requires the exact document digest")
    benchmark_id = preregistration["benchmark"]["benchmark_id"]
    matching = [entry for entry in registry["entries"] if entry["benchmark_id"] == benchmark_id]
    if len(matching) != 1:
        raise BenchmarkGovernanceError(
            f"preregistration benchmark_id must resolve to exactly one protected entry: {benchmark_id!r}"
        )
    entry = matching[0]
    attestations = entry["artifact_attestations"]
    if preregistration["protocol_id"] != entry["protocol"]["protocol_ref"]:
        raise BenchmarkGovernanceError("preregistration protocol_id does not match registry protocol_ref")
    if document_digest != entry["protocol"]["protocol_digest"]:
        raise BenchmarkGovernanceError("preregistration document does not match registry protocol_digest")
    for field in ("development_split_digest", "confirmation_split_digest"):
        if preregistration["benchmark"][field] != attestations[field]:
            raise BenchmarkGovernanceError(f"preregistration {field} does not match registry attestation")
    if preregistration["intended_claim_class"] == "public_performance" and entry["status"] != "claim_eligible":
        raise BenchmarkGovernanceError("public_performance preregistration requires a claim_eligible benchmark")


def verify_protected_artifact_absence(
    registry: Mapping[str, Any],
    scan_roots: Sequence[Path],
) -> None:
    """Reject raw protected artifacts in source trees or built archives."""
    digest_roles = _protected_artifact_digest_roles(registry)
    if not digest_roles:
        return
    matches: list[str] = []
    observed_paths: set[Path] = set()
    for root in scan_roots:
        for path in _iter_files(root):
            resolved = path.resolve()
            if resolved in observed_paths:
                continue
            observed_paths.add(resolved)
            digest = _sha256_path(path)
            if digest in digest_roles:
                matches.append(_format_match(path, digest, digest_roles))
            if path.suffix.lower() in _ARCHIVE_SUFFIXES:
                matches.extend(_archive_matches(path, digest_roles))
    if matches:
        details = "\n".join(f"- {match}" for match in sorted(matches))
        raise BenchmarkGovernanceError(f"protected benchmark artifacts are present in scanned outputs:\n{details}")


def _validate_schema_instance(
    instance: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    document_name: str,
) -> None:
    try:
        Draft7Validator.check_schema(schema)
    except Exception as exc:
        raise BenchmarkGovernanceError(f"invalid published schema for {document_name}: {exc}") from exc
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: [str(part) for part in error.absolute_path])
    if not errors:
        return
    formatted: list[str] = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        formatted.append(f"{path}: {error.message}")
    raise BenchmarkGovernanceError(f"invalid {document_name}: " + "; ".join(formatted))


def _validate_entry_semantics(entry: Mapping[str, Any], *, index: int) -> None:
    benchmark_id = entry["benchmark_id"]
    status = entry["status"]
    if status not in PROTECTED_STATUSES:
        raise BenchmarkGovernanceError(f"entries[{index}] is not a protected benchmark: {benchmark_id!r}")

    history = entry["status_history"]
    first = history[0]
    if first["from"] is not None or first["to"] != "provisional_internal":
        raise BenchmarkGovernanceError(f"{benchmark_id}: status history must start at null -> provisional_internal")
    previous = "provisional_internal"
    previous_effective_at = _parse_datetime(first["effective_at"])
    for transition_index, transition in enumerate(history[1:], start=1):
        edge = (transition["from"], transition["to"])
        if transition["from"] != previous or edge not in _ALLOWED_TRANSITIONS:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: invalid status transition at index {transition_index}: {edge!r}"
            )
        effective_at = _parse_datetime(transition["effective_at"])
        if effective_at <= previous_effective_at:
            raise BenchmarkGovernanceError(f"{benchmark_id}: status transition timestamps must increase monotonically")
        previous = transition["to"]
        previous_effective_at = effective_at
    if previous != status:
        raise BenchmarkGovernanceError(
            f"{benchmark_id}: current status {status!r} does not match status history {previous!r}"
        )

    allowed = set(entry["allowed_uses"])
    prohibited = set(entry["prohibited_uses"])
    missing_prohibited = sorted(_REQUIRED_PROHIBITED_USES - prohibited)
    if missing_prohibited:
        raise BenchmarkGovernanceError(f"{benchmark_id}: protected entries must prohibit uses {missing_prohibited}")
    if "blind_confirmation_evaluation" not in allowed and status != "retired":
        raise BenchmarkGovernanceError(f"{benchmark_id}: active protected entry must allow blind confirmation")

    if status == "provisional_internal":
        if "internal_architectural_evaluation" not in allowed:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: provisional_internal must allow internal_architectural_evaluation"
            )
        if "claim_eligible_performance_evaluation" in allowed:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: provisional_internal cannot allow claim-eligible performance evaluation"
            )
        if "public_performance_claims" not in prohibited:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: provisional_internal must prohibit public performance claims"
            )

    if status == "claim_eligible":
        if "claim_eligible_performance_evaluation" not in allowed:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: claim_eligible must allow claim_eligible_performance_evaluation"
            )
        if "public_performance_claims" in prohibited:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: claim_eligible conflicts with a public-performance prohibition"
            )
        claim_review = entry.get("claim_review")
        if not isinstance(claim_review, Mapping):
            raise BenchmarkGovernanceError(f"{benchmark_id}: claim_eligible requires claim_review")
        claim_transition = next(transition for transition in history if transition["to"] == "claim_eligible")
        if claim_transition["actor_ref"] != claim_review["reviewer_ref"]:
            raise BenchmarkGovernanceError(f"{benchmark_id}: claim promotion actor must be the independent reviewer")
        if claim_transition["decision_digest"] != claim_review["review_digest"]:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: claim promotion decision must match the independent review digest"
            )
        if claim_transition["effective_at"] != claim_review["reviewed_at"]:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: claim promotion time must match the independent review time"
            )
        disallowed_reviewers = {
            entry["governance"]["steward_ref"],
            entry["governance"]["custodian_ref"],
            claim_review["study_operator_ref"],
        }
        if claim_review["reviewer_ref"] in disallowed_reviewers:
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: claim reviewer must be independent of steward, custodian, and study operator"
            )

    if status == "retired" and allowed:
        raise BenchmarkGovernanceError(f"{benchmark_id}: retired benchmark cannot allow further use")
    if status == "retired" and any(transition["to"] == "claim_eligible" for transition in history):
        if not isinstance(entry.get("claim_review"), Mapping):
            raise BenchmarkGovernanceError(
                f"{benchmark_id}: retired formerly claim-eligible entry must retain claim_review"
            )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _protected_artifact_digest_roles(registry: Mapping[str, Any]) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {}
    for entry in registry["entries"]:
        benchmark_id = entry["benchmark_id"]
        for field in _ARTIFACT_DIGEST_FIELDS:
            digest = entry["artifact_attestations"][field]
            roles.setdefault(digest, set()).add(f"{benchmark_id}:{field}")
    return roles


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    if root.is_file():
        if not root.is_symlink():
            yield root
        return
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        yield path


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _archive_matches(path: Path, digest_roles: Mapping[str, set[str]]) -> list[str]:
    matches: list[str] = []
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    with archive.open(member) as stream:
                        digest = _sha256_stream(stream)
                    if digest in digest_roles:
                        matches.append(_format_match(path, digest, digest_roles, member=member.filename))
            return matches
        if tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    stream = archive.extractfile(member)
                    if stream is None:
                        continue
                    with stream:
                        digest = _sha256_stream(stream)
                    if digest in digest_roles:
                        matches.append(_format_match(path, digest, digest_roles, member=member.name))
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        # The whole archive file was still hashed. A corrupt archive is owned by
        # the package/content validators rather than silently broadening this
        # governance verifier into a general archive-integrity tool.
        return matches
    return matches


def _format_match(
    path: Path,
    digest: str,
    digest_roles: Mapping[str, set[str]],
    *,
    member: str | None = None,
) -> str:
    location = f"{path}!{member}" if member is not None else str(path)
    return f"{location} matches {digest} ({', '.join(sorted(digest_roles[digest]))})"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path("."),
        help="spectra-sherpa package root containing benchmarks/ and src/",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="registry JSON path (default: <package-root>/benchmarks/protected-registry-v1.json)",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        type=Path,
        default=[],
        help="source/output tree to scan; repeatable (default: package root)",
    )
    parser.add_argument(
        "--artifacts",
        action="append",
        type=Path,
        default=[],
        help="additional built artifact or directory to scan; repeatable",
    )
    parser.add_argument(
        "--preregistration",
        action="append",
        type=Path,
        default=[],
        help="pre-registration JSON document to validate and bind; repeatable",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    package_root = args.package_root.resolve()
    registry_path = (
        args.registry.resolve()
        if args.registry is not None
        else package_root / "benchmarks" / "protected-registry-v1.json"
    )
    registry_schema = load_json(
        package_root / "src" / "spectra_sherpa" / "contracts" / "protected_benchmark_registry_v1.json"
    )
    preregistration_schema = load_json(
        package_root / "src" / "spectra_sherpa" / "contracts" / "benchmark_preregistration_v1.json"
    )
    registry = load_json(registry_path)
    validate_registry(registry, registry_schema)
    for preregistration_path in args.preregistration:
        resolved_preregistration_path = preregistration_path.resolve()
        preregistration = load_json(resolved_preregistration_path)
        validate_preregistration(
            preregistration,
            preregistration_schema,
            registry=registry,
            document_digest=_sha256_path(resolved_preregistration_path),
        )
    scan_roots = [path.resolve() for path in args.scan_root] or [package_root]
    scan_roots.extend(path.resolve() for path in args.artifacts)
    verify_protected_artifact_absence(registry, scan_roots)
    print(
        "Protected benchmark governance verified: "
        f"{len(registry['entries'])} entries; {len(args.preregistration)} preregistrations; "
        f"{len(scan_roots)} scan roots."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
