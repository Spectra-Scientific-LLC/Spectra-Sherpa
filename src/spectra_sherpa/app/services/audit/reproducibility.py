"""Workflow-run reproducibility-record builder (Phase 1d).

Single source of truth for the record that every ``workflow.run.*``
audit event must carry. Per
``packages/spectra-server/docs/audit/minimum-reproducibility-record.md``
the record carries enough information for an independent investigator
to reconstruct the run: identity, hierarchy, workflow definition,
parameters, model linkage, and the execution environment.

This module owns the **environment block** (software version, git
commit SHA, Python runtime + lockfile hash, node-registry hash, runtime
image, hostname/pid/container id). Per-run fields are supplied by the
caller. Environment fields that can be resolved once per process are
cached in :class:`EnvironmentSnapshot`; everything dynamic (e.g.
``node_registry_hash`` after plugins load) is recomputed on each call.

Phase 1d covers:

  * identity + hierarchy + workflow definition fields
  * execution-environment block (cached + lazy node-registry hash)
  * convenience wiring for the ``_auto_persist_run`` hook

Phase 3 will extend the contract with:

  * automatic input-port hashing (multi-port workflows)
  * ``preprocessing_fitted_state_hashes`` per fitted preprocessor
  * ``train_test_split_indices`` (when a split is applied)
  * ``target_hash`` (when supervised labels are present)
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import socket
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Process-lifetime environment fields for the reproducibility record.

    Resolved once at first access via :func:`get_environment_snapshot`.
    Frozen so the cached snapshot cannot be mutated by callers.
    """

    software_version: str
    git_commit_sha: str | None
    python_runtime: str
    python_lockfile_hash: str | None
    runtime_image: str | None
    hostname: str | None
    pid: int
    container_id: str | None


@lru_cache(maxsize=1)
def get_environment_snapshot() -> EnvironmentSnapshot:
    """Return the cached environment snapshot for this process.

    Cached so repeated workflow runs don't repeatedly fork ``git`` or
    re-read the lockfile. Tests can invalidate via
    :func:`_reset_environment_snapshot_for_tests`.
    """
    return EnvironmentSnapshot(
        software_version=_resolve_software_version(),
        git_commit_sha=_resolve_git_sha(),
        python_runtime=f"{platform.python_implementation()} {sys.version.split()[0]}",
        python_lockfile_hash=_resolve_lockfile_hash(),
        runtime_image=os.environ.get("RUNTIME_IMAGE") or None,
        hostname=_safe_hostname(),
        pid=os.getpid(),
        container_id=_resolve_container_id(),
    )


def _reset_environment_snapshot_for_tests() -> None:
    """Test helper — clear the cached snapshot so tests can re-resolve."""
    get_environment_snapshot.cache_clear()


def _resolve_software_version() -> str:
    try:
        from importlib.metadata import version

        return version("spectra-sherpa")
    except Exception:
        return "unknown"


def _resolve_git_sha() -> str | None:
    # CI / container pipelines set GIT_COMMIT_SHA at build time.
    env_sha = os.environ.get("GIT_COMMIT_SHA")
    if env_sha:
        return env_sha.strip() or None
    # Fall back to git rev-parse from inside the source tree (dev mode).
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(Path(__file__).resolve().parent),
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            return sha or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _resolve_lockfile_hash() -> str | None:
    """SHA-256 of the first lockfile found walking up from this module.

    Looks for ``poetry.lock`` → ``uv.lock`` → ``requirements.lock``.
    Returns ``None`` when none is found (e.g. installed-package mode
    where the lockfile isn't on disk).
    """
    candidates = ("poetry.lock", "uv.lock", "requirements.lock")
    for parent in Path(__file__).resolve().parents:
        for name in candidates:
            lockfile = parent / name
            if lockfile.exists():
                try:
                    h = hashlib.sha256()
                    h.update(lockfile.read_bytes())
                    return h.hexdigest()
                except OSError:
                    return None
    return None


def _resolve_container_id() -> str | None:
    """Best-effort container-id detection.

    Reads ``/proc/self/cgroup`` for the common Docker / Kubernetes
    patterns. Returns ``None`` on non-Linux hosts and on hosts where
    the file does not surface a container id (bare metal, macOS dev).
    """
    cgroup_path = Path("/proc/self/cgroup")
    if not cgroup_path.exists():
        return None
    try:
        for line in cgroup_path.read_text().splitlines():
            if "/docker/" in line:
                return line.rsplit("/", 1)[-1].strip() or None
            if "/kubepods/" in line:
                return line.rsplit("/", 1)[-1].strip() or None
    except OSError:
        return None
    return None


def _safe_hostname() -> str | None:
    try:
        return socket.gethostname() or None
    except OSError:
        return None


def compute_node_registry_hash() -> str | None:
    """Hash the registered node catalogue.

    Captures the set of available node types with their port signatures.
    A different node-registry hash on two runs means the available
    chemometric nodes were different — a plugin drift signal that
    auditors care about.

    Computed on each call (cheap; the registry rarely changes during a
    process lifetime, but plugins may register after startup).
    """
    try:
        from spectra_sherpa.app.services.dag.node_base import node_registry

        items: list[dict[str, Any]] = []
        for node_type in sorted(getattr(node_registry, "_nodes", {}).keys()):
            try:
                meta = node_registry.get_metadata(node_type)
            except Exception:
                meta = None
            if meta is None:
                items.append({"type": node_type})
                continue
            inputs = sorted((str(p.name), str(getattr(p, "type", ""))) for p in getattr(meta, "inputs", []) or [])
            outputs = sorted((str(p.name), str(getattr(p, "type", ""))) for p in getattr(meta, "outputs", []) or [])
            items.append({"type": node_type, "inputs": inputs, "outputs": outputs})
        canonical = repr(items).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
    except Exception:
        logger.debug("Audit: failed to compute node_registry_hash", exc_info=True)
        return None


def build_reproducibility_record(
    *,
    workflow_id: int | None,
    workflow_version_id: int | None = None,
    workflow_integrity_hash: str | None = None,
    parameter_set: dict[str, Any] | None = None,
    input_ports: list[dict[str, Any]] | None = None,
    model_artifact_uids: list[str] | None = None,
    parent_model_artifact_uid: str | None = None,
    target_hash: str | None = None,
    train_test_split: dict[str, Any] | None = None,
    preprocessing_fitted_state_hashes: dict[str, str] | None = None,
    output_hash: str | None = None,
    output_artefact_uids: list[str] | None = None,
    qc_outcome: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Build the canonical reproducibility record for a workflow run.

    Caller supplies per-run fields. The execution-environment block is
    folded in from the cached :class:`EnvironmentSnapshot` plus a fresh
    ``node_registry_hash`` (resolved on every call so plugin changes
    surface in audit). Returns a JSON-safe dict ready to drop into
    ``audit_event.context["reproducibility_record"]``.
    """
    env = get_environment_snapshot()
    return {
        # Identity and workflow definition
        "workflow_id": workflow_id,
        "workflow_version_id": workflow_version_id,
        "workflow_integrity_hash": workflow_integrity_hash,
        "parameter_set": parameter_set or {},
        # Inputs and outputs
        "input_ports": input_ports or [],
        "target_hash": target_hash,
        "train_test_split": train_test_split,
        "preprocessing_fitted_state_hashes": preprocessing_fitted_state_hashes,
        "output_hash": output_hash,
        "output_artefact_uids": list(output_artefact_uids or []),
        "qc_outcome": qc_outcome,
        "duration_ms": duration_ms,
        # Model linkage
        "model_artifact_uids": list(model_artifact_uids or []),
        "parent_model_artifact_uid": parent_model_artifact_uid,
        # Execution environment
        "software_version": env.software_version,
        "git_commit_sha": env.git_commit_sha,
        "node_registry_hash": compute_node_registry_hash(),
        "python_runtime": env.python_runtime,
        "python_lockfile_hash": env.python_lockfile_hash,
        "runtime_image": env.runtime_image,
        "hostname": env.hostname,
        "pid": env.pid,
        "container_id": env.container_id,
    }


# Phase 1d minimum-required field names — used by tests to assert that
# every ``workflow.run.*`` event carries an audit-grade record.
REQUIRED_REPRODUCIBILITY_FIELDS: tuple[str, ...] = (
    "workflow_id",
    "workflow_integrity_hash",
    "parameter_set",
    "software_version",
    "python_runtime",
    "node_registry_hash",
    "hostname",
    "pid",
)


def assert_reproducibility_record_complete(record: dict[str, Any]) -> None:
    """Test helper — assert the record carries every required field.

    Raises :class:`AssertionError` listing every missing key so failures
    point at the exact gap. The set of required fields is intentionally
    a subset of the v0.5 spec — fields that depend on user data or
    environment that may be legitimately absent (``container_id``,
    ``runtime_image``, ``git_commit_sha`` in tarball installs, ...) are
    not required, but the record key must be *present* (possibly
    ``None``).
    """
    missing = [k for k in REQUIRED_REPRODUCIBILITY_FIELDS if k not in record]
    assert not missing, f"reproducibility record missing required fields: {missing}"
