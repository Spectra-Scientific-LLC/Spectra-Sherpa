"""OSS-only proof for immutable canonical fitted-state custody."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_applicability import (
    CanonicalApplicabilityEvidenceError,
    build_applicability_evidence,
    validate_applicability_evidence,
)
from spectra_sherpa.sdk.canonical_fitted_artifact import (
    CANONICAL_FITTED_ARTIFACT_VERSION,
    CanonicalFittedArtifact,
    CanonicalFittedArtifactError,
    require_private_artifact_directory,
)
from spectra_sherpa.sdk.validate import make_split_plan


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _refit_execution():
    X = np.arange(96, dtype=float).reshape(12, 8)
    target = X[:, 0] * 0.3 + X[:, 1] * 0.1
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=target),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(
        nodes,
        [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])],
    )
    validation = asyncio.run(execute_candidate_validation(graph, capability, split))
    return asyncio.run(execute_selected_candidate_full_refit(graph, capability, validation))


def test_executor_issued_refit_becomes_a_private_verified_artifact(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = artifact.write_new((tmp_path / "canonical-artifact").resolve())
    loaded = CanonicalFittedArtifact.load(destination)

    assert loaded.as_dict() == artifact.as_dict()
    assert loaded.artifact_digest == artifact.artifact_digest
    assert loaded.payload["schema_version"] == CANONICAL_FITTED_ARTIFACT_VERSION
    assert [member["node_id"] for member in loaded.payload["state_members"]] == ["scale", "model"]
    assert set(loaded.state_bytes) == {"scale", "model"}
    assert "mean" not in json.dumps(loaded.as_dict(), sort_keys=True)
    # Windows exposes only a compatibility subset of POSIX mode bits (see
    # _private_directory's os.name != "nt" guard) -- chmod there cannot
    # produce a synthetic 0o700-style restrictive mode to assert against.
    if os.name != "nt":
        assert (destination / "manifest.json").stat().st_mode & 0o077 == 0
        assert (destination / "states" / "model.json").stat().st_mode & 0o077 == 0


def test_state_tampering_is_detected_before_an_artifact_can_be_consumed(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = artifact.write_new((tmp_path / "canonical-artifact").resolve())
    state_path = destination / "states" / "model.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["n_components"] = 1
    state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(CanonicalFittedArtifactError, match="state bytes differ"):
        CanonicalFittedArtifact.load(destination)


def test_noncanonical_manifest_is_detected_before_an_artifact_can_be_consumed(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = artifact.write_new((tmp_path / "canonical-artifact").resolve())
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(CanonicalFittedArtifactError, match="manifest is not canonical JSON"):
        CanonicalFittedArtifact.load(destination)


def test_undeclared_state_file_is_detected_before_an_artifact_can_be_consumed(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = artifact.write_new((tmp_path / "canonical-artifact").resolve())
    (destination / "states" / "unbound.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CanonicalFittedArtifactError, match="undeclared state members"):
        CanonicalFittedArtifact.load(destination)


def test_loader_rejects_symlinked_and_oversized_authority_before_reading(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = artifact.write_new((tmp_path / "canonical-artifact").resolve())
    manifest = destination / "manifest.json"
    original = destination / "manifest.original"
    manifest.rename(original)
    manifest.symlink_to(original.name)
    with pytest.raises(CanonicalFittedArtifactError, match="symbolic link"):
        CanonicalFittedArtifact.load(destination)

    manifest.unlink()
    original.rename(manifest)
    with manifest.open("r+b") as handle:
        handle.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(CanonicalFittedArtifactError, match="byte ceiling"):
        CanonicalFittedArtifact.load(destination)


def test_forged_refit_cannot_be_promoted_to_a_canonical_artifact() -> None:
    refit = _refit_execution()

    class ForgedRefit:
        fitted_states = refit.fitted_states
        digest = refit.digest

        @staticmethod
        def as_dict():
            return refit.as_dict()

    with pytest.raises(CanonicalFittedArtifactError, match="executor-issued"):
        CanonicalFittedArtifact.from_full_refit_execution(ForgedRefit())


def test_writer_never_overwrites_an_existing_canonical_artifact(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    destination = (tmp_path / "canonical-artifact").resolve()
    artifact.write_new(destination)

    with pytest.raises(CanonicalFittedArtifactError, match="new absolute directory"):
        artifact.write_new(destination)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows exposes only a compatibility subset of POSIX mode bits; "
    "_private_directory intentionally does not enforce this check there",
)
def test_writer_rejects_a_nonprivate_parent_directory(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)

    with pytest.raises(CanonicalFittedArtifactError, match="destination parent is not private"):
        artifact.write_new((parent / "canonical-artifact").resolve())


def test_writer_rejects_a_state_that_exceeds_the_granted_output_budget(tmp_path: Path) -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())

    with pytest.raises(CanonicalFittedArtifactError, match="output member ceiling"):
        artifact.write_new(
            (tmp_path / "canonical-artifact").resolve(),
            max_state_member_bytes=1,
            max_artifact_bytes=1_000_000,
        )


def test_runner_parent_can_validate_its_private_output_root(tmp_path: Path) -> None:
    assert require_private_artifact_directory(tmp_path.resolve()) == tmp_path.resolve()


def test_canonical_artifact_rejects_sample_level_training_scores() -> None:
    artifact = CanonicalFittedArtifact.from_full_refit_execution(_refit_execution())
    manifest = json.loads(json.dumps(artifact.payload))
    state = json.loads(artifact.state_bytes["model"].decode("utf-8"))
    state["scores"] = [[float(row), 0.0] for row in range(state["reference_samples"])]
    raw_state = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    model_member = next(item for item in manifest["state_members"] if item["node_id"] == "model")
    model_member["state_content_digest"] = hashlib.sha256(raw_state).hexdigest()
    unsigned = {
        "schema_version": manifest["schema_version"],
        "full_refit_evidence": manifest["full_refit_evidence"],
        "state_members": manifest["state_members"],
    }
    manifest["artifact_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    state_bytes = dict(artifact.state_bytes)
    state_bytes["model"] = raw_state

    with pytest.raises(CanonicalFittedArtifactError, match="sample-level field"):
        CanonicalFittedArtifact.from_serialized(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            state_bytes,
        )


def test_applicability_evidence_retains_aggregates_without_rows() -> None:
    evidence = build_applicability_evidence(
        np.asarray([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]),
        np.asarray([0.5, 1.0, 1.5]),
        np.asarray([0.1, 0.2, 0.3]),
        t2_limit=2.0,
        q_limit=0.5,
        method="simca_ddmoments",
    )
    assert evidence["limits"] == {"t2": 2.0, "q": 0.5, "method": "simca_ddmoments"}
    assert evidence["score_statistics"]["count"] == 3
    assert evidence["score_statistics"]["dimensions"] == 2
    assert evidence["t2_statistics"]["mean"] == pytest.approx(1.0)
    assert evidence["q_statistics"]["quantiles"]["0.95"] == pytest.approx(0.29)
    assert "scores" not in json.dumps(evidence, sort_keys=True)
    assert validate_applicability_evidence(evidence) == evidence


def test_applicability_evidence_rejects_row_level_statistics() -> None:
    with pytest.raises(CanonicalApplicabilityEvidenceError, match="score mean"):
        validate_applicability_evidence(
            {
                "schema_version": "spectra-canonical-applicability-evidence/1",
                "limits": {"t2": 2.0, "q": 0.5, "method": "test"},
                "score_statistics": {
                    "count": 2,
                    "dimensions": 1,
                    "mean": [[1.0], [2.0]],
                    "std": [0.5],
                    "min": [1.0],
                    "max": [2.0],
                    "quantiles": {"0.05": [1.0], "0.5": [1.5], "0.95": [2.0]},
                },
                "t2_statistics": {
                    "count": 2,
                    "mean": 1.0,
                    "std": 0.5,
                    "min": 0.5,
                    "max": 1.5,
                    "quantiles": {"0.05": 0.5, "0.5": 1.0, "0.95": 1.5},
                },
                "q_statistics": {
                    "count": 2,
                    "mean": 0.2,
                    "std": 0.1,
                    "min": 0.1,
                    "max": 0.3,
                    "quantiles": {"0.05": 0.1, "0.5": 0.2, "0.95": 0.3},
                },
            }
        )
