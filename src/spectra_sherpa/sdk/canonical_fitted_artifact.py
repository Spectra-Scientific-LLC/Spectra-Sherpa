"""Immutable local custody for one executor-issued canonical full-data refit.

This module is deliberately *not* a project exporter.  A canonical Runner
cannot place fitted-state bytes in its JSON result merely because a later OSS
project must use them.  Instead, while the child still holds the
executor-issued :class:`FullDataRefitExecution`, it materializes one private
directory whose manifest binds each JSON state member to the sample-free
full-refit evidence.  A server-owned parent can then verify and publish that
directory without receiving a state byte through IPC.

The next M4.10 increment turns this immutable custody object into a visible
application DAG.  Keeping custody separate prevents that UI/import work from
creating a second, name-based scientific materializer.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical_applicability import CanonicalApplicabilityEvidenceError, validate_applicability_evidence
from .canonical_full_refit_evidence import (
    CanonicalFullRefitEvidence,
    CanonicalFullRefitEvidenceError,
)

CANONICAL_FITTED_ARTIFACT_VERSION = "spectra-canonical-fitted-artifact/1"
_MANIFEST_FILENAME = "manifest.json"
_STATE_DIRECTORY = "states"
_DIGEST_LENGTH = 64
MAX_CANONICAL_ARTIFACT_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CANONICAL_STATE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_CANONICAL_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_CANONICAL_STATE_MEMBERS = 128


class CanonicalFittedArtifactError(ValueError):
    """A canonical fitted-state artifact is malformed, forged, or unsafe."""


@dataclass(frozen=True)
class CanonicalFittedArtifact:
    """Verified manifest plus private canonical state bytes.

    ``state_bytes`` are deliberately not part of :meth:`as_dict`; callers may
    use that method in a bounded worker result without transmitting scientific
    model parameters.  They are available only to the local writer/verifier
    that already owns the artifact directory.
    """

    payload: dict[str, Any]
    artifact_digest: str
    state_bytes: dict[str, bytes]

    @classmethod
    def from_full_refit_execution(cls, execution: object) -> "CanonicalFittedArtifact":
        """Materialize an artifact only from an executor-issued full refit."""

        try:
            evidence = CanonicalFullRefitEvidence.from_full_refit_execution(execution)
        except CanonicalFullRefitEvidenceError as exc:
            raise CanonicalFittedArtifactError("canonical fitted artifact requires executor-issued refit") from exc

        records = getattr(execution, "fitted_states", None)
        if not isinstance(records, tuple) or not records:
            raise CanonicalFittedArtifactError("canonical full-data refit has no fitted states")
        evidence_states = evidence.payload["full_refit_execution"]["fitted_state_references"]
        if not isinstance(evidence_states, list):  # Defensive: evidence already validates this.
            raise CanonicalFittedArtifactError("canonical full-data refit evidence is malformed")

        members: list[dict[str, Any]] = []
        state_bytes: dict[str, bytes] = {}
        for record, evidence_state in zip(records, evidence_states, strict=True):
            node_id = getattr(record, "node_id", None)
            state = getattr(record, "state", None)
            if not isinstance(node_id, str) or not isinstance(state, Mapping):
                raise CanonicalFittedArtifactError("canonical full-data refit state is malformed")
            if node_id in state_bytes:
                raise CanonicalFittedArtifactError("canonical full-data refit repeats a state node")
            encoded = _canonical_json(state)
            _validate_data_free_state(state)
            content_digest = _sha256(encoded)
            expected = {
                "node_id": node_id,
                "state_digest": getattr(record, "digest", None),
                "serializer": getattr(record, "serializer", None),
                "contract_digest": getattr(record, "contract_digest", None),
                "candidate_node_digest": getattr(record, "candidate_node_digest", None),
                "seed": getattr(record, "seed", None),
            }
            if evidence_state != expected:
                raise CanonicalFittedArtifactError("canonical full-data refit state differs from its evidence")
            if not _is_digest(expected["state_digest"]) or not _is_digest(expected["contract_digest"]):
                raise CanonicalFittedArtifactError("canonical full-data refit state identity is malformed")
            members.append(
                {
                    **expected,
                    "relative_path": f"{_STATE_DIRECTORY}/{node_id}.json",
                    "state_content_digest": content_digest,
                }
            )
            state_bytes[node_id] = encoded

        unsigned_payload = {
            "schema_version": CANONICAL_FITTED_ARTIFACT_VERSION,
            "full_refit_evidence": evidence.as_dict(),
            "state_members": members,
        }
        payload = {
            **unsigned_payload,
            "artifact_digest": _sha256(_canonical_json(unsigned_payload)),
        }
        return cls._validated(payload, state_bytes=state_bytes)

    @classmethod
    def load(cls, directory: str | Path) -> "CanonicalFittedArtifact":
        """Load and verify one local artifact directory without executing it."""

        root = _artifact_directory(directory)
        manifest_path = root / _MANIFEST_FILENAME
        manifest_bytes = _read_bounded_private_regular(
            manifest_path,
            "canonical fitted artifact manifest",
            max_bytes=MAX_CANONICAL_ARTIFACT_MANIFEST_BYTES,
        )
        payload = _parse_canonical_json(manifest_bytes, "canonical fitted artifact manifest")
        if not isinstance(payload, Mapping):
            raise CanonicalFittedArtifactError("canonical fitted artifact manifest must be an object")
        if _canonical_json(payload) != manifest_bytes:
            raise CanonicalFittedArtifactError("canonical fitted artifact manifest is not canonical JSON")
        state_bytes: dict[str, bytes] = {}
        members = payload.get("state_members")
        if not isinstance(members, list) or not 1 <= len(members) <= MAX_CANONICAL_STATE_MEMBERS:
            raise CanonicalFittedArtifactError("canonical fitted artifact members are malformed")
        state_root = root / _STATE_DIRECTORY
        _private_directory(state_root, "canonical fitted artifact state directory")
        retained_bytes = len(manifest_bytes)
        for member in members:
            if not isinstance(member, Mapping):
                raise CanonicalFittedArtifactError("canonical fitted artifact member is malformed")
            node_id = member.get("node_id")
            relative_path = member.get("relative_path")
            if not isinstance(node_id, str) or not isinstance(relative_path, str):
                raise CanonicalFittedArtifactError("canonical fitted artifact member is malformed")
            path = _state_path(root, node_id)
            if relative_path != path.relative_to(root).as_posix():
                raise CanonicalFittedArtifactError("canonical fitted artifact state path is not canonical")
            state_bytes[node_id] = _read_bounded_private_regular(
                path,
                "canonical fitted artifact state",
                max_bytes=min(
                    MAX_CANONICAL_STATE_MEMBER_BYTES,
                    MAX_CANONICAL_ARTIFACT_BYTES - retained_bytes,
                ),
            )
            retained_bytes += len(state_bytes[node_id])
        expected_root_names = {_MANIFEST_FILENAME, _STATE_DIRECTORY}
        if {item.name for item in root.iterdir()} != expected_root_names:
            raise CanonicalFittedArtifactError("canonical fitted artifact has undeclared root members")
        expected_state_names = {f"{member['node_id']}.json" for member in members}
        if {item.name for item in state_root.iterdir()} != expected_state_names:
            raise CanonicalFittedArtifactError("canonical fitted artifact has undeclared state members")
        return cls.from_serialized(manifest_bytes, state_bytes)

    @classmethod
    def from_serialized(
        cls,
        manifest_bytes: bytes,
        state_bytes: Mapping[str, bytes],
    ) -> "CanonicalFittedArtifact":
        """Re-admit canonical artifact members already held as verified bytes.

        A project-package verifier must validate archive members before it
        decides whether any filesystem or database write is permitted.  This
        method provides that same closed artifact admission without extracting
        an untrusted archive to a durable directory first.
        """

        payload = _parse_canonical_json(manifest_bytes, "canonical fitted artifact manifest")
        if not isinstance(payload, Mapping):
            raise CanonicalFittedArtifactError("canonical fitted artifact manifest must be an object")
        if _canonical_json(payload) != manifest_bytes:
            raise CanonicalFittedArtifactError("canonical fitted artifact manifest is not canonical JSON")
        if not isinstance(state_bytes, Mapping) or any(
            not isinstance(node_id, str) or not isinstance(raw, bytes) for node_id, raw in state_bytes.items()
        ):
            raise CanonicalFittedArtifactError("canonical fitted artifact serialized state is malformed")
        return cls._validated(payload, state_bytes=state_bytes)

    @classmethod
    def _validated(cls, payload: Mapping[str, Any], *, state_bytes: Mapping[str, bytes]) -> "CanonicalFittedArtifact":
        expected_fields = {"schema_version", "full_refit_evidence", "state_members", "artifact_digest"}
        fields = set(payload)
        if fields != expected_fields:
            raise CanonicalFittedArtifactError(
                f"canonical fitted artifact fields are closed: missing={sorted(expected_fields - fields)}, "
                f"extra={sorted(fields - expected_fields)}"
            )
        if payload["schema_version"] != CANONICAL_FITTED_ARTIFACT_VERSION:
            raise CanonicalFittedArtifactError("canonical fitted artifact schema is unsupported")
        try:
            evidence = CanonicalFullRefitEvidence.from_dict(
                _mapping(payload["full_refit_evidence"], "full_refit_evidence")
            )
        except CanonicalFullRefitEvidenceError as exc:
            raise CanonicalFittedArtifactError("canonical fitted artifact full-refit evidence is invalid") from exc
        members_value = payload["state_members"]
        if not isinstance(members_value, list) or not members_value:
            raise CanonicalFittedArtifactError("canonical fitted artifact needs state members")
        evidence_members = evidence.payload["full_refit_execution"]["fitted_state_references"]
        if len(members_value) != len(evidence_members):
            raise CanonicalFittedArtifactError("canonical fitted artifact member count differs from refit evidence")
        expected_members: list[dict[str, Any]] = []
        normalized_state_bytes: dict[str, bytes] = {}
        for member, evidence_member in zip(members_value, evidence_members, strict=True):
            item = _mapping(member, "canonical fitted artifact member")
            required = {
                "node_id",
                "state_digest",
                "serializer",
                "contract_digest",
                "candidate_node_digest",
                "seed",
                "relative_path",
                "state_content_digest",
            }
            if set(item) != required:
                raise CanonicalFittedArtifactError("canonical fitted artifact member fields are closed")
            node_id = item["node_id"]
            if not isinstance(node_id, str) or not node_id or "/" in node_id or "\\" in node_id:
                raise CanonicalFittedArtifactError("canonical fitted artifact node identity is invalid")
            try:
                matches_evidence = {key: item[key] for key in evidence_member} == evidence_member
            except KeyError as exc:
                raise CanonicalFittedArtifactError(
                    "canonical fitted artifact member differs from refit evidence"
                ) from exc
            if not matches_evidence:
                raise CanonicalFittedArtifactError("canonical fitted artifact member differs from refit evidence")
            if item["relative_path"] != f"{_STATE_DIRECTORY}/{node_id}.json":
                raise CanonicalFittedArtifactError("canonical fitted artifact member path is invalid")
            if not _is_digest(item["state_content_digest"]):
                raise CanonicalFittedArtifactError("canonical fitted artifact state content digest is invalid")
            raw = state_bytes.get(node_id)
            if raw is None or _sha256(raw) != item["state_content_digest"]:
                raise CanonicalFittedArtifactError("canonical fitted artifact state bytes differ from manifest")
            parsed = _parse_canonical_json(raw, "canonical fitted artifact state")
            if not isinstance(parsed, Mapping) or _canonical_json(parsed) != raw:
                raise CanonicalFittedArtifactError("canonical fitted artifact state is not canonical JSON")
            _validate_data_free_state(parsed)
            normalized_state_bytes[node_id] = raw
            expected_members.append(dict(item))
        if set(state_bytes) != set(normalized_state_bytes):
            raise CanonicalFittedArtifactError("canonical fitted artifact has undeclared state bytes")
        unsigned = {
            "schema_version": payload["schema_version"],
            "full_refit_evidence": evidence.as_dict(),
            "state_members": expected_members,
        }
        expected_digest = _sha256(_canonical_json(unsigned))
        if payload["artifact_digest"] != expected_digest:
            raise CanonicalFittedArtifactError("canonical fitted artifact content digest mismatch")
        return cls(dict(payload), expected_digest, normalized_state_bytes)

    def as_dict(self) -> dict[str, Any]:
        """Return a state-free, bounded identity suitable for IPC or evidence."""

        return dict(self.payload)

    def write_new(
        self,
        directory: str | Path,
        *,
        max_state_member_bytes: int | None = None,
        max_artifact_bytes: int | None = None,
    ) -> Path:
        """Atomically create one private artifact directory, never overwrite it."""

        _validate_output_limits(max_state_member_bytes, max_artifact_bytes)
        manifest_bytes = _canonical_json(self.payload)
        member_sizes = tuple(len(value) for value in self.state_bytes.values())
        if max_state_member_bytes is not None and any(size > max_state_member_bytes for size in member_sizes):
            raise CanonicalFittedArtifactError("canonical fitted artifact state exceeds its output member ceiling")
        if max_artifact_bytes is not None and sum(member_sizes) + len(manifest_bytes) > max_artifact_bytes:
            raise CanonicalFittedArtifactError("canonical fitted artifact exceeds its output size ceiling")
        destination = Path(directory)
        if not destination.is_absolute() or destination.exists() or not destination.name:
            raise CanonicalFittedArtifactError("canonical fitted artifact destination must be a new absolute directory")
        parent = destination.parent
        _private_directory(parent, "canonical fitted artifact destination parent")
        stage = Path(tempfile.mkdtemp(prefix=".canonical-fitted-artifact-", dir=parent))
        try:
            os.chmod(stage, 0o700)
            state_root = stage / _STATE_DIRECTORY
            state_root.mkdir(mode=0o700)
            for member in self.payload["state_members"]:
                node_id = member["node_id"]
                target = _state_path(stage, node_id)
                _write_private_file(target, self.state_bytes[node_id])
            _write_private_file(stage / _MANIFEST_FILENAME, manifest_bytes)
            # Verify the exact on-disk bytes before publication.  This also
            # ensures a future storage backend cannot accidentally change the
            # canonical JSON contract under a successful writer.
            verified = type(self).load(stage)
            if verified.as_dict() != self.as_dict():
                raise CanonicalFittedArtifactError("canonical fitted artifact changed before publication")
            os.replace(stage, destination)
            _fsync_directory(parent)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise
        return destination


def _artifact_directory(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise CanonicalFittedArtifactError("canonical fitted artifact directory is unavailable")
    _private_directory(path, "canonical fitted artifact directory")
    return path


def require_private_artifact_directory(value: str | Path) -> Path:
    """Validate an existing private root before granting a Runner output path.

    The server uses this before it creates an output capability.  It is public
    because that caller must reject an unsafe deployment path *before* a child
    starts, rather than relying on a child-side write failure after it has been
    given scientific execution authority.
    """

    return _artifact_directory(value)


def _private_directory(path: Path, name: str) -> None:
    if path.is_symlink():
        raise CanonicalFittedArtifactError(f"{name} must not be a symbolic link")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise CanonicalFittedArtifactError(f"{name} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise CanonicalFittedArtifactError(f"{name} is unavailable")
    # Windows exposes only a compatibility subset of POSIX mode bits.  The
    # managed Runner custody boundary is Linux and verifies its configured
    # private capability root there; rejecting a normal Windows artifact based
    # on synthetic mode bits would make the OSS verifier needlessly unusable.
    if os.name != "nt" and metadata.st_mode & 0o077:
        raise CanonicalFittedArtifactError(f"{name} is not private")


def _private_regular_file(path: Path, name: str) -> None:
    if path.is_symlink():
        raise CanonicalFittedArtifactError(f"{name} must not be a symbolic link")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise CanonicalFittedArtifactError(f"{name} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CanonicalFittedArtifactError(f"{name} is unavailable")
    if os.name != "nt" and metadata.st_mode & 0o077:
        raise CanonicalFittedArtifactError(f"{name} is not private")


def _read_bounded_private_regular(path: Path, name: str, *, max_bytes: int) -> bytes:
    """Read one private authority without following links or allocating past its ceiling."""

    if max_bytes < 1:
        raise CanonicalFittedArtifactError("canonical fitted artifact exceeds its input size ceiling")
    if path.is_symlink():
        raise CanonicalFittedArtifactError(f"{name} must not be a symbolic link")
    try:
        lexical = path.absolute()
        before = lexical.lstat()
    except OSError as exc:
        raise CanonicalFittedArtifactError(f"{name} is unavailable") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size < 1
        or before.st_size > max_bytes
        or (os.name != "nt" and before.st_mode & 0o077)
    ):
        raise CanonicalFittedArtifactError(f"{name} is unavailable or exceeds its byte ceiling")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lexical, flags)
    except OSError as exc:
        raise CanonicalFittedArtifactError(f"{name} cannot be opened") from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_dev != before.st_dev
            or observed.st_ino != before.st_ino
            or observed.st_size != before.st_size
        ):
            raise CanonicalFittedArtifactError(f"{name} changed during admission")
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise CanonicalFittedArtifactError(f"{name} changed during admission")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise CanonicalFittedArtifactError(f"{name} changed during admission")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _state_path(root: Path, node_id: str) -> Path:
    path = root / _STATE_DIRECTORY / f"{node_id}.json"
    if path.parent != root / _STATE_DIRECTORY:
        raise CanonicalFittedArtifactError("canonical fitted artifact state path escapes its root")
    return path


def _write_private_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform/filesystem dependent durability enhancement
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - platform/filesystem dependent durability enhancement
        pass
    finally:
        os.close(descriptor)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalFittedArtifactError(f"{name} must be an object")
    return value


def _validate_output_limits(max_state_member_bytes: int | None, max_artifact_bytes: int | None) -> None:
    for name, value in (
        ("max_state_member_bytes", max_state_member_bytes),
        ("max_artifact_bytes", max_artifact_bytes),
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise CanonicalFittedArtifactError(f"{name} must be a positive integer when provided")
    if (
        max_state_member_bytes is not None
        and max_artifact_bytes is not None
        and max_state_member_bytes > max_artifact_bytes
    ):
        raise CanonicalFittedArtifactError("canonical fitted artifact member ceiling exceeds total output ceiling")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalFittedArtifactError("canonical fitted artifact JSON must be finite") from exc


def _parse_canonical_json(raw: bytes, name: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError, CanonicalFittedArtifactError) as exc:
        raise CanonicalFittedArtifactError(f"{name} must be canonical JSON") from exc


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalFittedArtifactError("canonical fitted artifact JSON repeats a field")
        result[key] = value
    return result


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _DIGEST_LENGTH and all(char in "0123456789abcdef" for char in value)


# A canonical fitted artifact is an application input, not a run export.  Keep
# this deny-list at the final custody boundary so a newly added node serializer
# cannot silently turn an application package into a sample-level data export.
_SAMPLE_LEVEL_FIELDS = frozenset(
    {
        "data",
        "membership_matrix",
        "predictions",
        "q_matrix",
        "sample_classes",
        "sample_ids",
        "sample_labels",
        "sample_scores",
        "scores",
        "t2_matrix",
        "target_values",
        "training_data",
        "x_scores",
        "y_pred",
        "y_scores",
        "y_true",
    }
)


def _validate_data_free_state(value: Mapping[str, Any]) -> None:
    """Reject row-level payloads while allowing bounded aggregate evidence."""

    reference_samples = _state_reference_sample_count(value)

    def visit(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise CanonicalFittedArtifactError("canonical fitted artifact state has a non-string field")
                normalized = key.casefold().replace("-", "_")
                if normalized in _SAMPLE_LEVEL_FIELDS:
                    raise CanonicalFittedArtifactError(
                        f"canonical fitted artifact state contains sample-level field: {path}.{key}"
                    )
                if normalized in {"applicability", "applicability_evidence"}:
                    try:
                        # Most serializers attach one evidence object.  SIMCA
                        # attaches one aggregate-only object per class, so
                        # validate that closed map one value at a time.
                        if isinstance(child, Mapping) and "schema_version" in child:
                            validate_applicability_evidence(child)
                        elif isinstance(child, Mapping) and child:
                            for evidence in child.values():
                                validate_applicability_evidence(evidence)
                        else:
                            raise CanonicalApplicabilityEvidenceError("applicability evidence map is empty")
                    except CanonicalApplicabilityEvidenceError as exc:
                        raise CanonicalFittedArtifactError(
                            f"canonical fitted artifact applicability evidence is invalid: {path}.{key}"
                        ) from exc
                visit(child, f"{path}.{key}")
            return
        if isinstance(node, list):
            # JSON state arrays are normally parameter vectors or small model
            # matrices.  A nested list with one row per calibration sample is
            # the characteristic shape of a retained score/data table.
            if (
                reference_samples is not None
                and len(node) == reference_samples
                and node
                and all(isinstance(item, list) for item in node)
            ):
                raise CanonicalFittedArtifactError(
                    f"canonical fitted artifact state contains sample-level rows: {path}"
                )
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]")

    visit(value, "state")


def _state_reference_sample_count(value: Mapping[str, Any]) -> int | None:
    for key in ("reference_samples", "n_samples", "n_observations"):
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            return raw
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping):
        return _state_reference_sample_count(metadata)
    return None


__all__ = [
    "CANONICAL_FITTED_ARTIFACT_VERSION",
    "CanonicalFittedArtifact",
    "CanonicalFittedArtifactError",
    "require_private_artifact_directory",
]
