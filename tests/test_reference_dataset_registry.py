"""One governed qualification contract for every public reference dataset."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.reference_datasets import (
    REFERENCE_DATASET_REGISTRY_PATH,
    ReferenceDatasetRegistryError,
    get_reference_dataset,
    load_reference_dataset_registry,
    materialize_reference_dataset,
    reference_dataset_registry_digest,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import execute_candidate_validation
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.validate import make_split_plan

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def entries():
    return load_reference_dataset_registry()


@pytest.fixture(scope="module", autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(PACKAGE_ROOT / "src" / "spectra_sherpa" / "app" / "types")


@pytest.mark.parametrize("dataset_id", [entry.dataset_id for entry in load_reference_dataset_registry()])
def test_every_governed_dataset_has_one_closed_reproducibility_contract(entries, dataset_id: str) -> None:
    entry = next(candidate for candidate in entries if candidate.dataset_id == dataset_id)
    payload = entry.as_dict()

    assert payload["visibility"] == "public_reproducibility_only"
    assert payload["spectral_domain"] in {"ftir", "nir", "raman", "uv_vis"}
    assert payload["supervised_eligible"] is True
    assert payload["target"]["kind"] == "continuous"
    assert payload["feature_axis"]["kind"] == "spectral"
    assert payload["feature_axis"]["digest_encoding"] == "little-endian-float64"
    assert payload["source"]["reference_name"] == payload["loader"]["reference_name"]
    assert set(entry.development_indices).isdisjoint(entry.confirmation_indices)
    assert set(entry.development_indices) | set(entry.confirmation_indices) == set(range(payload["shape"]["n_samples"]))
    assert any("performance claims" in use for use in payload["prohibited_uses"])
    assert payload["attribution"]["license_id"].startswith("LicenseRef-")


@pytest.mark.parametrize("dataset_id", [entry.dataset_id for entry in load_reference_dataset_registry()])
def test_every_available_reference_materializes_and_verifies_source_content_and_split_digests(
    dataset_id: str,
) -> None:
    entry = get_reference_dataset(dataset_id)
    cache_root = PACKAGE_ROOT / "data" / "reference_cache" / "eigenvector"
    source = entry.payload["source"]
    eigenvector_data_dir = cache_root if entry.payload["loader"]["kind"] == "eigenvector" else None
    if eigenvector_data_dir is not None and not (cache_root / source["local_path"]).exists():
        pytest.skip(f"upstream bytes for {dataset_id} are intentionally not redistributed")

    dataset = materialize_reference_dataset(entry, eigenvector_data_dir=eigenvector_data_dir)

    assert dataset.source_path is not None
    assert dataset.source_path.is_file()
    assert dataset.X.shape == (entry.payload["shape"]["n_samples"], entry.payload["shape"]["n_features"])
    assert dataset.y.shape == (entry.payload["shape"]["n_samples"],)
    assert dataset.feature_axis.length == entry.payload["shape"]["n_features"]
    assert dataset.development[0].shape[0] == entry.development_indices.size
    assert dataset.confirmation[0].shape[0] == entry.confirmation_indices.size


@pytest.mark.parametrize(
    "dataset_id",
    [entry.dataset_id for entry in load_reference_dataset_registry()],
)
def test_every_available_reference_dataset_executes_one_canonical_dag_and_evidence_contract(dataset_id: str) -> None:
    entry = get_reference_dataset(dataset_id)
    source = entry.payload["source"]
    cache_root = PACKAGE_ROOT / "data" / "reference_cache" / "eigenvector"
    eigenvector_data_dir = cache_root if entry.payload["loader"]["kind"] == "eigenvector" else None
    if eigenvector_data_dir is not None and not (cache_root / source["local_path"]).exists():
        pytest.skip(f"upstream bytes for {dataset_id} are intentionally not redistributed")
    dataset = materialize_reference_dataset(entry, eigenvector_data_dir=eigenvector_data_dir)
    features, target = dataset.development
    split = make_split_plan(features.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=features, target=target, feature_axis=dataset.feature_axis.copy()),
        custody_id=dataset_id,
        dataset_ref_digest=hashlib.sha256(dataset_id.encode("utf-8")).hexdigest(),
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
    execution = asyncio.run(execute_candidate_validation(graph, capability, split))
    profile = managed_optimization_profile()
    operation_ids = tuple(node.node_type for node in nodes)
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for operation_id in operation_ids
        for requirement in profile.operation(operation_id).payload["runtime_requirements"]
    }
    evidence = CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=profile.runtime_attestation(
            operation_ids,
            version_resolver=versions.__getitem__,
        ).as_dict(),
    )
    reloaded = CanonicalExecutionEvidence.from_bytes(evidence.canonical_bytes())

    assert execution.graph_digest == graph.digest
    assert reloaded.validation_execution_digest == execution.digest
    assert reloaded.payload["validation_execution"]["capability_content_digest"] == capability.content_digest


def test_registry_digest_is_semantic_and_line_ending_independent(tmp_path: Path) -> None:
    payload = json.loads(REFERENCE_DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
    lf_path = tmp_path / "lf.json"
    crlf_path = tmp_path / "crlf.json"
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    lf_path.write_text(serialized, encoding="utf-8")
    crlf_path.write_bytes(serialized.replace("\n", "\r\n").encode("utf-8"))

    assert reference_dataset_registry_digest(lf_path) == reference_dataset_registry_digest(crlf_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["datasets"][0].update({"unexpected": True}), "fields are not closed"),
        (
            lambda payload: payload["datasets"][0]["split"]["confirmation_indices"].append(0),
            "sorted and unique",
        ),
        (
            lambda payload: payload["datasets"][0]["content_digests"].update({"complete": "0" * 64}),
            "content does not match",
        ),
        (
            lambda payload: payload["datasets"][0]["feature_axis"].update({"values_digest": "0" * 64}),
            "spectral axis does not match",
        ),
    ],
)
def test_registry_fails_closed_on_uncontracted_or_forged_state(tmp_path: Path, mutation, message: str) -> None:
    payload = json.loads(REFERENCE_DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(payload)
    mutation(mutated)
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    if message in {"content does not match", "spectral axis does not match"}:
        entry = load_reference_dataset_registry(path)[0]
        with pytest.raises(ReferenceDatasetRegistryError, match=message):
            materialize_reference_dataset(entry)
    else:
        with pytest.raises(ReferenceDatasetRegistryError, match=message):
            load_reference_dataset_registry(path)


def test_unknown_dataset_identity_does_not_fall_back_to_a_default() -> None:
    with pytest.raises(ReferenceDatasetRegistryError, match="unknown governed reference dataset"):
        get_reference_dataset("corn")


def test_loaded_entry_does_not_expose_mutable_registry_authority() -> None:
    entry = get_reference_dataset("public-atmospheric-regression-v1")
    detached = entry.payload
    detached["target"]["name"] = "forged"

    assert entry.payload["target"]["name"] == "Carbon dioxide"


def test_remote_qualification_source_references_artifact_authority_without_repeating_bytes() -> None:
    source = get_reference_dataset("public-corn-m5-moisture-v1").payload["source"]

    assert source == {
        "kind": "remote_eigenvector_archive",
        "reference_name": "corn_m5",
        "local_path": "corn_mat/corn.mat",
        "artifact_projection_id": "public-corn-m5-moisture-v1",
    }


def test_remote_qualification_source_refuses_wrong_same_member_projection(tmp_path: Path) -> None:
    payload = json.loads(REFERENCE_DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
    corn = next(item for item in payload["datasets"] if item["dataset_id"] == "public-corn-m5-moisture-v1")
    corn["source"]["artifact_projection_id"] = "public-corn-mp5-moisture-v1"
    path = tmp_path / "wrong-artifact.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReferenceDatasetRegistryError, match="scientific identity"):
        load_reference_dataset_registry(path)
