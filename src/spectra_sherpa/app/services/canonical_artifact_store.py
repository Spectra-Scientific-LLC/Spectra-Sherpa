"""Private local storage and read authority for canonical fitted artifacts.

This is intentionally separate from :mod:`model_store`.  A canonical fitted
artifact is a closed, content-addressed directory produced by the M4 Runner;
it is not a legacy model manifest plus an NPZ file.  Keeping the stores
separate prevents a workbench application node from silently falling back to a
legacy model or from receiving authority to mutate an imported canonical
artifact.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from pathlib import Path

from spectra_sherpa.core.canonical_artifact import (
    CanonicalArtifactStoreError,
    ReadOnlyCanonicalArtifactReader,
    canonical_artifact_root,
)
from spectra_sherpa.sdk.canonical_fitted_artifact import (
    CanonicalFittedArtifact,
    CanonicalFittedArtifactError,
)

_store: CanonicalArtifactStore | None = None


class CanonicalArtifactStore:
    """Application-owned installer; it is not execution read authority."""

    def __init__(self, base_dir: Path) -> None:
        self._root = canonical_artifact_root(base_dir, create=True)

    @property
    def root(self) -> Path:
        """Return the private durable root for startup and import code."""

        return self._root

    def install_from_directory(self, source: str | Path) -> CanonicalFittedArtifact:
        """Verify and atomically install an imported artifact under its digest.

        The source is fully revalidated before a single target byte is
        published.  An existing matching content-addressed directory is
        idempotent; an existing different/invalid directory fails closed.
        """

        try:
            artifact = CanonicalFittedArtifact.load(source)
        except CanonicalFittedArtifactError as exc:
            raise CanonicalArtifactStoreError("canonical fitted artifact import is invalid") from exc
        target = self._root / artifact.artifact_digest
        if target.parent != self._root:
            raise CanonicalArtifactStoreError("canonical artifact target escapes its configured root")
        if target.exists():
            existing = ReadOnlyCanonicalArtifactReader(
                self._root.parent,
                allowed_artifact_digests=(artifact.artifact_digest,),
            ).load(artifact.artifact_digest)
            if existing.as_dict() != artifact.as_dict() or existing.state_bytes != artifact.state_bytes:
                raise CanonicalArtifactStoreError("canonical artifact digest already names different bytes")
            return existing

        stage = Path(tempfile.mkdtemp(prefix=".canonical-artifact-import-", dir=self._root))
        try:
            copied = stage / artifact.artifact_digest
            shutil.copytree(source, copied, copy_function=shutil.copy2)
            _make_private_tree(copied)
            verified = CanonicalFittedArtifact.load(copied)
            if verified.as_dict() != artifact.as_dict() or verified.state_bytes != artifact.state_bytes:
                raise CanonicalArtifactStoreError("canonical artifact changed during import")
            try:
                os.replace(copied, target)
            except OSError as exc:
                # Directory replacement differs slightly across supported
                # filesystems: a concurrent installer may surface either the
                # Python-specific FileExistsError or generic EEXIST/ENOTEMPTY.
                # Only that expected content-address race is idempotent;
                # never turn an unrelated I/O failure into a successful import.
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                existing = ReadOnlyCanonicalArtifactReader(
                    self._root.parent,
                    allowed_artifact_digests=(artifact.artifact_digest,),
                ).load(artifact.artifact_digest)
                if existing.as_dict() != artifact.as_dict() or existing.state_bytes != artifact.state_bytes:
                    raise CanonicalArtifactStoreError("canonical artifact digest already names different bytes")
                return existing
            _fsync_directory(self._root)
            return ReadOnlyCanonicalArtifactReader(
                self._root.parent,
                allowed_artifact_digests=(artifact.artifact_digest,),
            ).load(artifact.artifact_digest)
        except CanonicalFittedArtifactError as exc:
            raise CanonicalArtifactStoreError("canonical fitted artifact import is invalid") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)


def init_canonical_artifact_store(base_dir: Path) -> CanonicalArtifactStore:
    """Initialize mutable application authority during normal startup only."""

    global _store
    _store = CanonicalArtifactStore(base_dir)
    return _store


def _make_private_tree(root: Path) -> None:
    """Copying an archive must not inherit group/world-readable source modes."""

    if os.name == "nt":
        return
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_symlink():
            raise CanonicalArtifactStoreError("canonical artifact import may not contain symbolic links")
        path.chmod(0o700 if path.is_dir() else 0o600)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - filesystem/platform durability enhancement
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - filesystem/platform durability enhancement
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "CanonicalArtifactStore",
    "CanonicalArtifactStoreError",
    "ReadOnlyCanonicalArtifactReader",
    "init_canonical_artifact_store",
]
