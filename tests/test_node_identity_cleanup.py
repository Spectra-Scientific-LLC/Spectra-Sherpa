from __future__ import annotations

from pathlib import Path

import pytest

from spectra_sherpa.app.schemas.workflows import WorkflowNodeCreate, WorkflowVersionDetail
from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.saved_graph_admission import admit_saved_workflow_graph
from spectra_sherpa.core.node_identity import SERIALIZED_NODE_TYPE_ALIASES, canonicalize_serialized_workflow


@pytest.mark.parametrize("serialized_alias,canonical", SERIALIZED_NODE_TYPE_ALIASES.items())
def test_registry_accepts_serialized_alias_without_publishing_it(serialized_alias: str, canonical: str) -> None:
    assert serialized_alias in node_registry
    assert node_registry.get_metadata(serialized_alias).node_type == canonical
    assert node_registry.create_node(serialized_alias, "legacy", {}).metadata.node_type == canonical
    assert serialized_alias not in {metadata.node_type for metadata in node_registry.list_nodes()}


def test_saved_workflow_admission_migrates_aliases_without_mutating_input() -> None:
    source = [
        {
            "node_id": "legacy-pls",
            "node_type": "model.fitted_pls_v2",
            "label": "model.fitted_pls_v2",
            "parameters": {},
        }
    ]

    admitted = admit_saved_workflow_graph(source, [], current_graph=True)

    assert source[0]["node_type"] == "model.fitted_pls_v2"
    assert admitted.nodes[0]["node_type"] == "model.fitted_pls"
    assert admitted.nodes[0]["label"] == "model.fitted_pls_v2"


def test_api_models_accept_old_bytes_and_serialize_only_canonical_ids() -> None:
    node = WorkflowNodeCreate.model_validate(
        {"node_id": "legacy-evaluator", "node_type": "diagnostics.regression_evaluator_v2"}
    )
    assert node.model_dump()["node_type"] == "diagnostics.regression_evaluator"

    version = WorkflowVersionDetail.model_validate(
        {
            "id": 1,
            "workflow_id": 2,
            "version_number": 3,
            "created_at": "2026-09-13T00:00:00Z",
            "created_by": 4,
            "change_description": None,
            "snapshot": {
                "nodes": [
                    {
                        "node_id": "legacy-evaluator",
                        "node_type": "diagnostics.classification_evaluator_v2",
                        "parameters": {},
                    }
                ]
            },
        }
    )
    assert version.model_dump()["snapshot"]["nodes"][0]["node_type"] == ("diagnostics.classification_evaluator")


def test_serialized_migration_is_key_directed_and_recursive() -> None:
    payload = {
        "workflows": [
            {
                "nodes": [
                    {
                        "id": "legacy",
                        "type": "model.apply_fitted_pls_v2",
                        "node_type": "model.fitted_pls_v2",
                        "parameters": {
                            "literal": "model.fitted_pls_v2",
                            "node_type": "model.fitted_pls_v2",
                        },
                        "label": "model.fitted_pls_v2",
                    }
                ]
            }
        ]
    }

    migrated = canonicalize_serialized_workflow(payload)

    node = migrated["workflows"][0]["nodes"][0]
    assert node["type"] == "model.apply_fitted_pls"
    assert node["node_type"] == "model.fitted_pls"
    assert node["parameters"]["literal"] == "model.fitted_pls_v2"
    assert node["parameters"]["node_type"] == "model.fitted_pls_v2"
    assert node["label"] == "model.fitted_pls_v2"
    assert payload["workflows"][0]["nodes"][0]["node_type"] == "model.fitted_pls_v2"


def test_integrity_hash_treats_serialized_alias_as_the_canonical_operation() -> None:
    legacy = [{"node_id": "pls", "node_type": "model.fitted_pls_v2", "parameters": {}}]
    canonical = [{"node_id": "pls", "node_type": "model.fitted_pls", "parameters": {}}]
    assert compute_workflow_hash(legacy, []) == compute_workflow_hash(canonical, [])


def test_old_operation_ids_are_confined_to_the_serialization_boundary() -> None:
    package_root = Path(__file__).resolve().parents[1]
    allowed = {
        package_root / "src/spectra_sherpa/core/node_identity.py",
        package_root / "src/spectra_sherpa/alembic/versions/s8t0u2v4w137_canonical_node_identities.py",
        Path(__file__).resolve(),
    }
    offenders: list[str] = []
    for root in (package_root / "src", package_root / "frontend/src", package_root / "docs"):
        for path in root.rglob("*"):
            if not path.is_file() or "static" in path.parts or "__pycache__" in path.parts or path in allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for serialized_alias in SERIALIZED_NODE_TYPE_ALIASES:
                if serialized_alias in text:
                    offenders.append(str(path.relative_to(package_root)))
                    break
    assert offenders == []
