"""Import-light, read-only authority for canonical fitted artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from spectra_sherpa.sdk.canonical_fitted_artifact import (
    CanonicalFittedArtifact,
    CanonicalFittedArtifactError,
    require_private_artifact_directory,
)

_CANONICAL_ARTIFACT_DIRECTORY = "canonical_fitted_artifacts"
_DIGEST_LENGTH = 64


class CanonicalArtifactStoreError(RuntimeError):
    """A canonical fitted artifact is missing, unsafe, or mismatched."""


class ReadOnlyCanonicalArtifactReader:
    """Root-confined read capability for one closed set of artifact digests."""

    def __init__(
        self,
        base_dir: Path,
        *,
        allowed_artifact_digests: tuple[str, ...],
        artifact_root: Path | None = None,
    ) -> None:
        if artifact_root is None:
            self._root = canonical_artifact_root(base_dir, create=False)
        else:
            root = Path(artifact_root)
            if not root.is_absolute() or root.is_symlink():
                raise CanonicalArtifactStoreError("canonical artifact root is unavailable or not private")
            try:
                self._root = require_private_artifact_directory(root)
            except CanonicalFittedArtifactError as exc:
                raise CanonicalArtifactStoreError("canonical artifact root is unavailable or not private") from exc
        if not allowed_artifact_digests:
            raise CanonicalArtifactStoreError("canonical artifact reader requires an explicit read grant")
        self._allowed_artifact_digests = frozenset(
            require_digest(value, "canonical artifact read grant digest") for value in allowed_artifact_digests
        )
        if len(self._allowed_artifact_digests) != len(allowed_artifact_digests):
            raise CanonicalArtifactStoreError("canonical artifact read grant repeats a digest")

    def load(self, artifact_digest: str) -> CanonicalFittedArtifact:
        digest = require_digest(artifact_digest, "artifact digest")
        if digest not in self._allowed_artifact_digests:
            raise CanonicalArtifactStoreError("canonical fitted artifact is not authorized by this read grant")
        path = self._root / digest
        if path.parent != self._root:
            raise CanonicalArtifactStoreError("canonical artifact path escapes its configured root")
        try:
            artifact = CanonicalFittedArtifact.load(path)
        except CanonicalFittedArtifactError as exc:
            raise CanonicalArtifactStoreError("canonical fitted artifact is unavailable or invalid") from exc
        if artifact.artifact_digest != digest:
            raise CanonicalArtifactStoreError("canonical fitted artifact digest differs from its lookup identity")
        return artifact

    def load_bound_state(
        self,
        binding: Mapping[str, object],
        *,
        expected_source_contract_digest: str,
        expected_serializer: str,
    ) -> dict[str, object]:
        required = {
            "artifact_digest",
            "state_node_id",
            "state_digest",
            "state_content_digest",
            "serializer",
            "source_contract_digest",
        }
        if not isinstance(binding, Mapping) or set(binding) != required:
            raise CanonicalArtifactStoreError("canonical artifact binding fields are closed")
        artifact_digest = require_digest(binding["artifact_digest"], "artifact binding digest")
        state_node_id = binding["state_node_id"]
        if not isinstance(state_node_id, str) or not state_node_id:
            raise CanonicalArtifactStoreError("canonical artifact state identity is invalid")
        for field in ("state_digest", "state_content_digest", "source_contract_digest"):
            require_digest(binding[field], f"canonical artifact {field}")
        if (
            binding["source_contract_digest"] != expected_source_contract_digest
            or binding["serializer"] != expected_serializer
        ):
            raise CanonicalArtifactStoreError("canonical artifact binding differs from this application operation")
        artifact = self.load(artifact_digest)
        member = next(
            (candidate for candidate in artifact.payload["state_members"] if candidate["node_id"] == state_node_id),
            None,
        )
        if not isinstance(member, Mapping):
            raise CanonicalArtifactStoreError("canonical artifact does not declare this application state")
        for field in ("state_digest", "state_content_digest", "serializer", "contract_digest"):
            expected = binding["source_contract_digest"] if field == "contract_digest" else binding[field]
            if member.get(field) != expected:
                raise CanonicalArtifactStoreError("canonical artifact state differs from its application binding")
        raw = artifact.state_bytes.get(state_node_id)
        if raw is None or hashlib.sha256(raw).hexdigest() != binding["state_content_digest"]:
            raise CanonicalArtifactStoreError("canonical artifact state bytes differ from its application binding")
        try:
            state = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalArtifactStoreError("canonical artifact state is unavailable") from exc
        if not isinstance(state, dict):
            raise CanonicalArtifactStoreError("canonical artifact state is malformed")
        return state


def canonical_artifact_root(base_dir: Path, *, create: bool) -> Path:
    base = Path(base_dir)
    if not base.is_absolute():
        raise CanonicalArtifactStoreError("canonical artifact base directory is unavailable")
    root = base / _CANONICAL_ARTIFACT_DIRECTORY
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if __import__("os").name != "nt":
            root.chmod(0o700)
    try:
        return require_private_artifact_directory(root)
    except CanonicalFittedArtifactError as exc:
        raise CanonicalArtifactStoreError("canonical artifact root is unavailable or not private") from exc


def require_digest(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CanonicalArtifactStoreError(f"{name} is not a SHA-256 digest")
    return value


__all__ = [
    "CanonicalArtifactStoreError",
    "ReadOnlyCanonicalArtifactReader",
    "canonical_artifact_root",
    "require_digest",
]
