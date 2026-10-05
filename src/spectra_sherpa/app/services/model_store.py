"""
Model artifact file storage — manifest.json + arrays.npz persistence.

Each artifact lives at ``{base_dir}/models/{artifact_uid}/`` and contains:

- ``manifest.json`` — human-readable metadata, array inventory, provenance
- ``arrays.npz`` — numpy compressed archive of all model arrays

The manifest is designed to be inspectable: users can open it to see
exactly what's in a model without loading the arrays.
"""

from __future__ import annotations

import errno
import io
import json
import logging
import os
import shutil
import tempfile
import time
import uuid as _uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.file_permissions import restrict_file_descriptor
from spectra_sherpa.core.model_artifact import (
    CANONICAL_MODEL_ARTIFACT_AUTHORITY,
    ORDINARY_MODEL_ARTIFACT_AUTHORITY,
    ModelArtifactIntegrityError,
    ModelManifestJSONError,
    assign_model_artifact_authority,
    experiment_training_dataset_id,
    parse_model_manifest_json,
    require_model_artifact_authority,
)
from spectra_sherpa.core.model_artifact import (
    require_artifact_identity as _require_artifact_identity,
)
from spectra_sherpa.core.model_artifact import (
    sha256_file as _sha256_file,
)

logger = logging.getLogger(__name__)


class ModelArtifactCollisionError(FileExistsError):
    """A create-new publication encountered an existing artifact identity."""


_PUBLICATION_THREAD_LOCKS_GUARD = Lock()
_PUBLICATION_THREAD_LOCKS: dict[str, Lock] = {}


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_store: ModelStore | None = None


def init_model_store(base_dir: Path) -> ModelStore:
    """Initialize the global ModelStore (called once at app startup)."""
    global _store
    _store = ModelStore(base_dir)
    return _store


def get_model_store() -> ModelStore:
    """Get the global ModelStore instance.

    Raises RuntimeError if :func:`init_model_store` has not been called.
    """
    if _store is None:
        raise RuntimeError("ModelStore not initialized — call init_model_store(base_dir) at startup")
    return _store


def verify_model_artifact_storage_record(model: Any) -> None:
    """Cross-bind one owner-scoped DB row to its verified stored artifact."""

    store = get_model_store()
    manifest, arrays = store.load(model.artifact_uid, verify=True)
    if manifest.get("integrity_hash") != model.integrity_hash:
        raise ModelArtifactIntegrityError("stored model digest contradicts its database record")
    authority = require_model_artifact_authority(manifest)
    declared_origin = getattr(model, "artifact_origin", None)
    if declared_origin is None:
        if authority != ORDINARY_MODEL_ARTIFACT_AUTHORITY:
            raise ModelArtifactIntegrityError("ordinary model database record contradicts stored authority")
        linked_dataset_id = experiment_training_dataset_id(manifest)
        if linked_dataset_id is not None and linked_dataset_id != getattr(model, "training_dataset_id", None):
            raise ModelArtifactIntegrityError("ordinary model training source contradicts its database record")
        if manifest.get("training_scientific_digest") != getattr(model, "training_scientific_digest", None):
            raise ModelArtifactIntegrityError("ordinary model scientific training identity contradicts its record")
        return

    from spectra_sherpa.app.services.canonical_model_bridge import (
        CANONICAL_MODEL_ORIGIN,
        CanonicalModelBridgeError,
        validate_canonical_plsda_model_artifact,
    )

    training_dataset_id = getattr(model, "training_dataset_id", None)
    if (
        declared_origin != CANONICAL_MODEL_ORIGIN
        or authority != CANONICAL_MODEL_ARTIFACT_AUTHORITY
        or training_dataset_id is None
    ):
        raise ModelArtifactIntegrityError("canonical model database record has unsupported authority")
    try:
        lineage = validate_canonical_plsda_model_artifact(
            manifest,
            arrays,
            expected_training_dataset_id=training_dataset_id,
        )
        classes = json.loads(model.classes_json) if model.classes_json is not None else None
        feature_axis = json.loads(model.feature_axis_json) if model.feature_axis_json is not None else None
        preprocessing = json.loads(model.preprocessing_summary) if model.preprocessing_summary is not None else None
    except (CanonicalModelBridgeError, TypeError, ValueError) as exc:
        raise ModelArtifactIntegrityError("canonical model scientific lineage is invalid") from exc
    if (
        manifest.get("artifact_uid") != model.artifact_uid
        or manifest.get("integrity_hash") != model.integrity_hash
        or manifest.get("model_type") != model.model_type
        or manifest.get("node_id") != model.node_id
        or manifest.get("n_features") != model.n_features
        or manifest.get("n_components") != model.n_components
        or manifest.get("classes") != classes
        or manifest.get("feature_axis") != feature_axis
        or manifest.get("preprocessing_chain") != preprocessing
        or manifest.get("training_data_hash") != model.training_data_hash
        or manifest.get("training_scientific_digest") != model.training_scientific_digest
        or lineage.get("lineage_digest") != model.canonical_lineage_digest
        or lineage.get("validation_execution_digest") != model.validation_evidence_digest
    ):
        raise ModelArtifactIntegrityError("stored model artifact contradicts its database record")


# ---------------------------------------------------------------------------
# ModelStore
# ---------------------------------------------------------------------------


class ModelStore:
    """Persist and load model artifacts (NPZ + JSON manifest)."""

    def __init__(self, base_dir: Path) -> None:
        self.models_dir = Path(base_dir) / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)

    # ── Write ────────────────────────────────────────────────────────

    def save(
        self,
        artifact_uid: str,
        manifest: dict[str, Any],
        arrays: dict[str, np.ndarray],
    ) -> str:
        """Save manifest.json + arrays.npz.

        Parameters
        ----------
        artifact_uid:
            Unique identifier (UUID) for this artifact.
        manifest:
            Metadata dict to write as manifest.json.  An ``arrays`` key is
            automatically added with shape/dtype info for each array.
        arrays:
            Named numpy arrays to store in arrays.npz.

        Returns
        -------
        str
            SHA-256 hex digest of the saved arrays.npz file.
        """
        return self._save(artifact_uid, manifest, arrays, replace_existing=True)

    def save_new(
        self,
        artifact_uid: str,
        manifest: dict[str, Any],
        arrays: dict[str, np.ndarray],
    ) -> str:
        """Atomically create one artifact without replacing an existing UID."""

        return self._save(artifact_uid, manifest, arrays, replace_existing=False)

    def _save(
        self,
        artifact_uid: str,
        manifest: dict[str, Any],
        arrays: dict[str, np.ndarray],
        *,
        replace_existing: bool,
    ) -> str:
        artifact_dir = self._artifact_dir(artifact_uid)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # Stage the full artifact (npz + manifest) into a
        # private temp dir on the *same filesystem*, fsync it, then
        # promote it into place with an atomic directory rename.  This
        # guarantees a reader never sees a torn artifact (npz written
        # but manifest missing, or vice versa), and a crash mid-write
        # leaves either the previous complete artifact or none — never a
        # corrupt one.  Re-saving over an existing uid keeps the old
        # artifact fully intact until the instant of promotion.
        staging = Path(tempfile.mkdtemp(prefix=f".staging-{artifact_uid}-", dir=self.models_dir))
        try:
            npz_path = staging / "arrays.npz"
            manifest_path = staging / "manifest.json"

            np.savez_compressed(str(npz_path), **arrays)
            integrity_hash = _sha256_file(npz_path)

            array_inventory: dict[str, dict[str, Any]] = {}
            for name, arr in arrays.items():
                array_inventory[name] = {
                    "shape": list(arr.shape),
                    "dtype": str(arr.dtype),
                }

            manifest["arrays"] = array_inventory
            manifest["integrity_hash"] = integrity_hash
            manifest["artifact_uid"] = artifact_uid
            assign_model_artifact_authority(manifest)

            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2, default=_json_default)
                f.flush()
                os.fsync(f.fileno())
            _fsync_file(npz_path)
            _fsync_dir(staging)

            # Replacement and create-only publication share one per-identity
            # claim.  In particular, create-only must not observe the brief
            # absent-target window while replacement has moved the old
            # generation aside for its crash-recoverable promotion.
            with self._publication_claim(artifact_uid):
                try:
                    if replace_existing:
                        self._promote(staging, artifact_dir)
                    else:
                        self._promote_new(staging, artifact_dir)
                    _fsync_dir(self.models_dir)
                except Exception:
                    # A create-only promotion can fail after the rename (for
                    # example while fsyncing the parent).  If staging has
                    # disappeared, this invocation owns the newly promoted
                    # target; remove it while the same UID claim is held.  A
                    # collision leaves staging present and must never delete
                    # the pre-existing winner.
                    if not replace_existing and not staging.exists() and artifact_dir.exists():
                        shutil.rmtree(artifact_dir)
                        _fsync_dir(self.models_dir)
                    raise
        finally:
            # On the happy path ``staging`` was renamed away and no
            # longer exists; this only fires if promotion failed.
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        logger.info(
            "Saved model artifact %s (%d arrays, hash=%s)",
            artifact_uid,
            len(arrays),
            integrity_hash[:12],
        )
        return integrity_hash

    @staticmethod
    def _promote_new(staging: Path, target: Path) -> None:
        """Atomically claim an absent artifact identity without overwrite."""

        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ModelArtifactCollisionError(f"Model artifact identity already exists: {target.name}")
        try:
            os.rename(staging, target)
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise ModelArtifactCollisionError(f"Model artifact identity already exists: {target.name}") from exc
            raise

    @contextmanager
    def _publication_claim(self, artifact_uid: str):
        """Hold one process- and host-wide exclusive artifact identity claim.

        The persistent lock file is harmless after a crash: the operating
        system releases the advisory lock with the file descriptor.  A local
        thread lock is retained as well because advisory-lock behavior for two
        descriptors in one process differs across supported platforms.
        """

        lock_root = self.models_dir.parent / ".model-publication-locks"
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_stat = lock_root.lstat()
        if not lock_root.is_dir() or lock_root.is_symlink():
            raise RuntimeError("Model publication lock root is not a private directory")
        if root_stat.st_mode & 0o077:
            os.chmod(lock_root, 0o700)
        lock_name = _uuid.uuid5(_uuid.NAMESPACE_URL, f"spectrasherpa:model:{artifact_uid}").hex + ".lock"
        lock_path = lock_root / lock_name
        lock_key = str(lock_path.resolve())
        with _PUBLICATION_THREAD_LOCKS_GUARD:
            thread_lock = _PUBLICATION_THREAD_LOCKS.setdefault(lock_key, Lock())
        with thread_lock:
            flags = os.O_RDWR | os.O_CREAT
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(lock_path, flags, 0o600)
            unlock = None
            try:
                restrict_file_descriptor(fd)
                try:
                    import fcntl
                except ImportError:  # pragma: no cover - Windows only
                    try:
                        import msvcrt
                    except ImportError as exc:  # pragma: no cover - unsupported platform
                        raise RuntimeError("No safe model publication lock is available") from exc
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

                    def unlock() -> None:
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

                else:
                    fcntl.flock(fd, fcntl.LOCK_EX)

                    def unlock() -> None:
                        fcntl.flock(fd, fcntl.LOCK_UN)

                yield
            finally:
                if unlock is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    unlock()
                os.close(fd)

    def _promote(self, staging: Path, target: Path) -> None:
        """Atomically move a fully-written staging dir into ``target``.

        Same-filesystem directory renames are atomic on POSIX.  When
        ``target`` already exists (re-save / import collision) the old
        dir is moved aside to ``<uid>.old-<hex>`` first because ``rename``
        cannot replace a non-empty directory; an in-process exception
        restores it so we never destroy a good artifact for a bad one.

        There is still a window between the two renames where a *hard
        kill* (OOM / power loss) leaves the canonical dir missing and the
        ``.old-`` backup as the only complete copy.  ``.old-`` is
        therefore NOT scratch: ``reconcile_orphan_artifacts`` restores it
        whenever the canonical artifact is absent, which is what makes the
        "either the old complete artifact or the new one" durability guarantee
        hold across a crash (POSIX has no portable atomic directory swap, so
        recover-on-startup is the backstop).
        """
        if not target.exists():
            os.replace(staging, target)
            return
        backup = target.with_name(f"{target.name}.old-{_uuid.uuid4().hex}")
        os.replace(target, backup)
        try:
            os.replace(staging, target)
        except Exception:
            os.replace(backup, target)  # best-effort restore of the prior artifact
            raise
        shutil.rmtree(backup, ignore_errors=True)

    # ── Read ─────────────────────────────────────────────────────────

    def load_manifest(self, artifact_uid: str) -> dict[str, Any]:
        """Load manifest.json only (cheap metadata inspection)."""
        manifest_path = self._artifact_dir(artifact_uid) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Model artifact not found: {artifact_uid}")
        with open(manifest_path, "rb") as f:
            try:
                manifest = parse_model_manifest_json(f.read())
            except ModelManifestJSONError as exc:
                raise ModelArtifactIntegrityError(
                    f"Model artifact {artifact_uid}: manifest JSON is ambiguous or malformed"
                ) from exc
        require_model_artifact_authority(manifest)
        return manifest

    def load_arrays(self, artifact_uid: str) -> dict[str, np.ndarray]:
        """Load arrays.npz → dict of numpy arrays."""
        npz_path = self._artifact_dir(artifact_uid) / "arrays.npz"
        if not npz_path.exists():
            raise FileNotFoundError(f"Model arrays not found: {artifact_uid}")
        with np.load(str(npz_path), allow_pickle=False) as npz:
            return dict(npz)

    def load(
        self,
        artifact_uid: str,
        *,
        verify: bool = True,
    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        """Load both manifest and arrays.

        ``verify`` (default on) re-hashes ``arrays.npz``
        and compares it to the manifest's recorded ``integrity_hash``,
        raising :class:`ModelArtifactIntegrityError` on any mismatch.
        Callers that load a model to *use* it (prediction / inspection)
        must keep verification on so a corrupt or truncated npz fails
        loud instead of producing silently wrong results.  Pass
        ``verify=False`` only for tooling that explicitly wants the
        bytes regardless of integrity.
        """
        manifest = self.load_manifest(artifact_uid)
        if verify:
            self._assert_integrity(artifact_uid, manifest)
        _require_artifact_identity(manifest, expected_uid=artifact_uid)
        arrays = self.load_arrays(artifact_uid)
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
            canonical_model_validation_required,
        )

        if canonical_model_validation_required(manifest):
            from spectra_sherpa.app.services.canonical_model_bridge import (
                CanonicalModelBridgeError,
                validate_canonical_plsda_model_artifact,
            )

            try:
                validate_canonical_plsda_model_artifact(manifest, arrays)
            except CanonicalModelBridgeError as exc:
                raise ModelArtifactIntegrityError(
                    f"Model artifact {artifact_uid}: canonical scientific lineage is invalid"
                ) from exc
        return manifest, arrays

    def _assert_integrity(self, artifact_uid: str, manifest: dict[str, Any]) -> None:
        """Raise ModelArtifactIntegrityError unless the npz matches its hash."""
        expected = manifest.get("integrity_hash", "")
        npz_path = self._artifact_dir(artifact_uid) / "arrays.npz"
        if not npz_path.exists():
            raise ModelArtifactIntegrityError(f"Model artifact {artifact_uid}: arrays.npz is missing")
        if not expected:
            raise ModelArtifactIntegrityError(f"Model artifact {artifact_uid}: manifest has no integrity_hash")
        actual = _sha256_file(npz_path)
        if actual != expected:
            raise ModelArtifactIntegrityError(
                f"Model artifact {artifact_uid}: arrays.npz hash mismatch "
                f"(expected {expected[:12]}…, got {actual[:12]}…) — artifact is corrupt"
            )

    def verify_integrity(self, artifact_uid: str) -> bool:
        """Check that arrays.npz matches the stored hash (boolean form)."""
        try:
            self._assert_integrity(artifact_uid, self.load_manifest(artifact_uid))
        except (ModelArtifactIntegrityError, FileNotFoundError):
            return False
        return True

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, artifact_uid: str) -> None:
        """Remove artifact directory from disk."""
        artifact_dir = self._artifact_dir(artifact_uid)
        if artifact_dir.exists():
            import shutil

            shutil.rmtree(artifact_dir)
            logger.info("Deleted model artifact %s from disk", artifact_uid)

    # ── List ─────────────────────────────────────────────────────────

    def list_artifacts(self) -> list[str]:
        """List all artifact_uids on disk."""
        if not self.models_dir.exists():
            return []
        return [d.name for d in self.models_dir.iterdir() if d.is_dir() and (d / "manifest.json").exists()]

    # ── Helpers ──────────────────────────────────────────────────────

    def _artifact_dir(self, artifact_uid: str) -> Path:
        """Resolve artifact directory with path traversal protection."""
        resolved = (self.models_dir / artifact_uid).resolve()
        if not resolved.is_relative_to(self.models_dir.resolve()):
            raise ValueError(f"Invalid artifact_uid: path traversal detected ({artifact_uid!r})")
        return resolved

    def artifact_directory(self, artifact_uid: str) -> str:
        """Return the root-confined directory recorded by executor evidence."""

        return str(self._artifact_dir(artifact_uid))


def _fsync_file(path: Path) -> None:
    """Flush a file's bytes to stable storage (best-effort)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:  # pragma: no cover - platform/fs dependent
        logger.debug("fsync(%s) skipped: %s", path, exc)


def _fsync_dir(path: Path) -> None:
    """Flush a directory entry so a rename/create survives a crash."""
    try:
        fd = os.open(str(path), os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, AttributeError) as exc:  # pragma: no cover - platform dependent
        logger.debug("fsync dir(%s) skipped: %s", path, exc)


def _json_default(obj: Any) -> Any:
    """JSON serializer fallback for numpy types and other non-standard objects."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# DB record creation helper
# ---------------------------------------------------------------------------


async def persist_model_artifact_records(
    session: Any,
    saved_artifacts: list[dict[str, Any]],
    user_id: int,
    workflow_id: int | None = None,
    workflow_version_id: int | None = None,
    project_id: int | None = None,
    source_run_id: int | None = None,
    training_dataset_id: int | None = None,
    run_name: str | None = None,
) -> list[Any]:
    """Create ModelArtifact DB rows for artifacts saved during DAG execution.

    Call this after ``executor.execute()`` using ``executor.saved_artifacts``.

    Parameters
    ----------
    session:
        Async SQLAlchemy session (already open).
    saved_artifacts:
        List of dicts from ``DAGExecutor.saved_artifacts``.
    user_id:
        Owner of the artifacts.
    workflow_id, workflow_version_id, project_id:
        Optional context to associate with the artifacts.
    source_run_id, training_dataset_id:
        Optional lineage links. ``source_run_id`` may be attached later by
        ``_auto_persist_run`` because workflow execution saves artifacts before
        the run row exists.
    run_name:
        Optional human name used to seed display_name.

    Returns
    -------
    list[ModelArtifact]
        The created DB rows (already added to session, not yet committed).
    """
    if not saved_artifacts:
        return []

    from sqlalchemy import select as sa_select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.services.audit import audit_emitter

    # Check which artifact_uids already exist (idempotency guard)
    uids = [a["artifact_uid"] for a in saved_artifacts]
    existing_result = await session.execute(
        sa_select(ModelArtifact.artifact_uid).where(ModelArtifact.artifact_uid.in_(uids))
    )
    existing_uids = set(existing_result.scalars().all())

    rows = []
    for art in saved_artifacts:
        model_type = art.get("model_type", "unknown")
        artifact_uid = art["artifact_uid"]
        if artifact_uid in existing_uids:
            logger.info("ModelArtifact %s already exists — skipping", artifact_uid)
            continue
        await _persist_model_artifact_durably_if_configured(
            session=session,
            user_id=user_id,
            artifact_uid=artifact_uid,
            artifact_dir=art.get("artifact_dir", ""),
        )
        default_name = f"{model_type.upper()} — {artifact_uid[:8]}"
        display_name = art.get("display_name")
        if not display_name and run_name:
            node_label = art.get("node_label") or art.get("node_id", "")
            suffix = f" — {node_label}" if node_label else ""
            display_name = f"{model_type.upper()} — {run_name}{suffix}"
        display_name = display_name or default_name
        row = ModelArtifact(
            artifact_uid=artifact_uid,
            user_id=user_id,
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            source_run_id=source_run_id,
            training_dataset_id=training_dataset_id,
            node_id=art.get("node_id", ""),
            model_type=model_type,
            name=default_name,
            display_name=display_name,
            artifact_dir=art.get("artifact_dir", ""),
            integrity_hash=art.get("integrity_hash", ""),
            n_features=art.get("n_features", 0),
            n_components=art.get("n_components"),
            classes_json=art.get("classes_json"),
            feature_axis_json=art.get("feature_axis_json"),
            metrics_json=art.get("metrics_json"),
            preprocessing_summary=art.get("preprocessing_summary"),
            training_data_hash=art.get("training_data_hash"),
            training_scientific_digest=art.get("training_scientific_digest"),
            artifact_origin=art.get("artifact_origin"),
            canonical_lineage_digest=art.get("canonical_lineage_digest"),
            validation_evidence_digest=art.get("validation_evidence_digest"),
            tags=list(art.get("tags") or []),
            is_deploy_ready=bool(art.get("is_deploy_ready", False)),
        )
        session.add(row)
        rows.append(row)
        logger.info(
            "Created ModelArtifact DB row: %s (type=%s, node=%s)",
            artifact_uid,
            model_type,
            art.get("node_id"),
        )

        # Emit an audit event in the SAME transaction as the artifact
        # row. Fail-closed: if audit insert fails on commit, the whole
        # transaction rolls back and the model artifact is not created
        # either. target_id is the stable artifact_uid (string), not
        # the autoincrement PK — that way deletion / re-creation audits
        # link cleanly even if the integer row id changes.
        audit_emitter.emit(
            session=session,
            action="model_artifact.created",
            target_type="ModelArtifact",
            target_id=artifact_uid,
            after={
                "artifact_uid": artifact_uid,
                "model_type": model_type,
                "workflow_id": workflow_id,
                "workflow_version_id": workflow_version_id,
                "project_id": project_id,
                "source_run_id": source_run_id,
                "training_dataset_id": training_dataset_id,
                "user_id": user_id,
                "node_id": art.get("node_id"),
                "display_name": display_name,
                "n_features": art.get("n_features"),
                "n_components": art.get("n_components"),
                "integrity_hash": art.get("integrity_hash"),
            },
        )

    return rows


async def _persist_model_artifact_durably_if_configured(
    *,
    session: Any,
    user_id: int,
    artifact_uid: str,
    artifact_dir: str,
) -> None:
    from spectra_sherpa.app.contracts.durable_artifacts import get_durable_artifact_persister

    persister = get_durable_artifact_persister()
    if persister is None:
        return
    payload = _zip_artifact_dir(Path(artifact_dir))
    await persister(
        session=session,
        user_id=user_id,
        artifact_uid=f"model_{artifact_uid}",
        artifact_kind="model_artifact",
        payload=payload,
    )


def _zip_artifact_dir(path: Path) -> bytes:
    if not path.is_dir():
        raise FileNotFoundError(f"Model artifact directory not found: {path}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in sorted(path.iterdir()):
            if child.is_file():
                archive.write(child, arcname=child.name)
    return buffer.getvalue()


# Default grace window for orphan reconciliation.  Disk artifacts younger
# than this are never reaped — they may belong to a concurrent request
# that has written the files but not yet committed its DB row.
ORPHAN_RECONCILE_GRACE_SEC = 3600.0


async def reconcile_orphan_artifacts(
    session: Any,
    *,
    store: ModelStore | None = None,
    grace_seconds: float = ORPHAN_RECONCILE_GRACE_SEC,
) -> list[str]:
    """Delete on-disk artifacts that have no ``ModelArtifact`` DB row.

    Orphan reconciliation defence-in-depth.  Caught failures get a compensating
    ``store.delete()`` at the call site, but a hard process kill (OOM /
    pod eviction) between ``store.save()`` and the DB commit raises no
    exception and leaves an orphan file with no DB row, never GC'd.
    This idempotent sweep — safe to run at startup — removes disk
    artifacts that (a) have no DB row and (b) are older than
    ``grace_seconds`` (so an in-flight concurrent save is never reaped),
    plus leftover ``.staging-*`` scratch.  A ``<uid>.old-<hex>`` re-save
    backup is *recovered* (renamed back to the canonical uid) when the
    canonical dir is missing — a crash mid-``_promote`` — and only
    deleted as stale once the canonical artifact is present again.
    Returns the uids removed (recoveries are logged, not in the list).
    """
    from sqlalchemy import select as sa_select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    store = store or get_model_store()
    models_dir = store.models_dir
    if not models_dir.exists():
        return []

    db_rows = (await session.execute(sa_select(ModelArtifact.artifact_uid, ModelArtifact.is_active))).all()
    db_active_by_uid = {artifact_uid: bool(is_active) for artifact_uid, is_active in db_rows}
    now = time.time()
    removed: list[str] = []
    recovered: list[str] = []

    for child in models_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name

        # ``<uid>.old-<hex>`` is a re-save backup, NOT scratch: during
        # ``_promote`` it is the *only* complete copy between the two
        # renames.  A hard kill in that window leaves the canonical dir
        # missing with this backup as the sole survivor — and a renamed
        # dir keeps its original (old) mtime, so a grace check would not
        # protect it.  Recover it the instant the canonical is absent
        # (grace does not apply to recovery); only treat it as deletable
        # scratch once the canonical artifact is confirmed present.  This
        # is what makes the "either the old complete artifact or the
        # new one" durability guarantee hold across a crash.
        if ".old-" in name:
            base_uid = name.rsplit(".old-", 1)[0]
            canonical = models_dir / base_uid
            if not canonical.exists():
                try:
                    os.replace(child, canonical)
                    logger.warning(
                        "Recovered model artifact %s from an interrupted re-save backup (%s)",
                        base_uid,
                        name,
                    )
                    recovered.append(base_uid)
                except OSError as exc:  # pragma: no cover - leave for a human
                    logger.error("Could not recover %s from backup %s: %s", base_uid, name, exc)
                continue
            # Canonical present → the promote completed; this backup is
            # genuinely stale.  Fall through to the grace-gated delete.

        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age < grace_seconds:
            continue
        # Abandoned promote scratch (incomplete staging write never
        # touched the canonical dir) or a now-stale .old- backup.
        if name.startswith(".staging-") or ".old-" in name:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(name)
            continue
        if name in db_active_by_uid and db_active_by_uid[name]:
            continue
        if name in db_active_by_uid and not db_active_by_uid[name]:
            try:
                store.delete(name)
                removed.append(name)
            except Exception as exc:  # pragma: no cover - best-effort janitor
                logger.warning("Inactive artifact reconcile could not delete %s: %s", name, exc)
            continue
        # Real-looking artifact dir with no DB row → orphan.
        try:
            store.delete(name)
            removed.append(name)
        except Exception as exc:  # pragma: no cover - best-effort janitor
            logger.warning("Orphan reconcile could not delete %s: %s", name, exc)

    if removed or recovered:
        logger.info(
            "Reconciled model-artifact dirs: removed=%s recovered=%s",
            removed,
            recovered,
        )
    return removed
