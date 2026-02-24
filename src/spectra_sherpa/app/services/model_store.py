"""
Model artifact file storage — manifest.json + arrays.npz persistence.

Each artifact lives at ``{base_dir}/models/{artifact_uid}/`` and contains:

- ``manifest.json`` — human-readable metadata, array inventory, provenance
- ``arrays.npz`` — numpy compressed archive of all model arrays

The manifest is designed to be inspectable: users can open it to see
exactly what's in a model without loading the arrays.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

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
        raise RuntimeError(
            "ModelStore not initialized — call init_model_store(base_dir) at startup"
        )
    return _store


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
        artifact_dir = self._artifact_dir(artifact_uid)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        npz_path = artifact_dir / "arrays.npz"
        manifest_path = artifact_dir / "manifest.json"

        # Save arrays
        np.savez_compressed(str(npz_path), **arrays)

        # Compute integrity hash
        integrity_hash = _sha256_file(npz_path)

        # Enrich manifest with array inventory
        array_inventory: dict[str, dict[str, Any]] = {}
        for name, arr in arrays.items():
            array_inventory[name] = {
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
            }

        manifest["arrays"] = array_inventory
        manifest["integrity_hash"] = integrity_hash
        manifest["artifact_uid"] = artifact_uid

        # Write manifest
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2, default=_json_default)

        logger.info(
            "Saved model artifact %s (%d arrays, hash=%s)",
            artifact_uid,
            len(arrays),
            integrity_hash[:12],
        )
        return integrity_hash

    # ── Read ─────────────────────────────────────────────────────────

    def load_manifest(self, artifact_uid: str) -> dict[str, Any]:
        """Load manifest.json only (cheap metadata inspection)."""
        manifest_path = self._artifact_dir(artifact_uid) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Model artifact not found: {artifact_uid}"
            )
        with open(manifest_path) as f:
            return json.load(f)

    def load_arrays(self, artifact_uid: str) -> dict[str, np.ndarray]:
        """Load arrays.npz → dict of numpy arrays."""
        npz_path = self._artifact_dir(artifact_uid) / "arrays.npz"
        if not npz_path.exists():
            raise FileNotFoundError(
                f"Model arrays not found: {artifact_uid}"
            )
        with np.load(str(npz_path), allow_pickle=False) as npz:
            return dict(npz)

    def load(
        self, artifact_uid: str
    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        """Load both manifest and arrays."""
        manifest = self.load_manifest(artifact_uid)
        arrays = self.load_arrays(artifact_uid)
        return manifest, arrays

    def verify_integrity(self, artifact_uid: str) -> bool:
        """Check that arrays.npz matches the stored hash."""
        manifest = self.load_manifest(artifact_uid)
        expected = manifest.get("integrity_hash", "")
        npz_path = self._artifact_dir(artifact_uid) / "arrays.npz"
        if not npz_path.exists():
            return False
        actual = _sha256_file(npz_path)
        return actual == expected

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
        return [
            d.name
            for d in self.models_dir.iterdir()
            if d.is_dir() and (d / "manifest.json").exists()
        ]

    # ── Helpers ──────────────────────────────────────────────────────

    def _artifact_dir(self, artifact_uid: str) -> Path:
        """Resolve artifact directory with path traversal protection."""
        resolved = (self.models_dir / artifact_uid).resolve()
        if not resolved.is_relative_to(self.models_dir.resolve()):
            raise ValueError(
                f"Invalid artifact_uid: path traversal detected ({artifact_uid!r})"
            )
        return resolved


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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

    Returns
    -------
    list[ModelArtifact]
        The created DB rows (already added to session, not yet committed).
    """
    if not saved_artifacts:
        return []

    from sqlalchemy import select as sa_select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

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
        row = ModelArtifact(
            artifact_uid=artifact_uid,
            user_id=user_id,
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            node_id=art.get("node_id", ""),
            model_type=model_type,
            name=f"{model_type.upper()} — {artifact_uid[:8]}",
            artifact_dir=art.get("artifact_dir", ""),
            integrity_hash=art.get("integrity_hash", ""),
            n_features=art.get("n_features", 0),
            n_components=art.get("n_components"),
            classes_json=art.get("classes_json"),
            feature_axis_json=art.get("feature_axis_json"),
            metrics_json=art.get("metrics_json"),
            preprocessing_summary=art.get("preprocessing_summary"),
        )
        session.add(row)
        rows.append(row)
        logger.info(
            "Created ModelArtifact DB row: %s (type=%s, node=%s)",
            artifact_uid,
            model_type,
            art.get("node_id"),
        )

    return rows
