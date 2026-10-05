"""Scientific source inheritance uses identity and full parameters, never order."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.schemas.workflows import WorkflowDagSpec, WorkflowDagSpecNode
from spectra_sherpa.app.services.tools.builtin.workflow import (
    _data_loader_fingerprints,
    source_binding_snapshot,
    substitute_parent_data_loaders,
    validate_dag_spec_for_parent,
)


def parent(node_id="source", **parameters):
    return SimpleNamespace(
        node_id=node_id, node_type="data.file_load", parameters={"experiment_id": 1, "file_id": 2, **parameters}
    )


def proposal(*nodes):
    return {"nodes": list(nodes), "edges": []}


def source(node_id="source", **parameters):
    return {"id": node_id, "type": "data.file_load", "parameters": parameters}


def test_omitted_stage_is_restored_by_identity_with_receipt():
    original = parent(stage="preprocessed")
    candidate = proposal(source(experiment_id=1, file_id=2))
    receipt = substitute_parent_data_loaders(candidate, [original])
    assert candidate["nodes"][0]["parameters"] == original.parameters
    assert receipt[0]["restored_fields"] == ["stage"]
    assert receipt[0]["binding_sha256"] == source_binding_snapshot([original])["source"]


def test_pydantic_child_inherits_full_nested_target_and_mask_without_aliasing():
    original = parent(
        target_authority={"column": "cetane", "target_type": "continuous", "units": "index"}, exclusions=[2, 9]
    )
    candidate = WorkflowDagSpec(nodes=[WorkflowDagSpecNode(id="source", type="data.file_load")], edges=[])
    substitute_parent_data_loaders(candidate, [original])
    assert candidate.nodes[0].parameters == original.parameters
    candidate.nodes[0].parameters["target_authority"]["column"] = "changed"
    assert original.parameters["target_authority"]["column"] == "cetane"


def test_reordered_sources_preserve_training_and_test_files():
    train = parent("train", file_id=10, stage="preprocessed")
    test = parent("test", file_id=11, stage="raw")
    candidate = proposal(source("test"), source("train"))
    substitute_parent_data_loaders(candidate, [train, test])
    assert [node["parameters"]["file_id"] for node in candidate["nodes"]] == [11, 10]
    assert [node["parameters"]["stage"] for node in candidate["nodes"]] == ["raw", "preprocessed"]


@pytest.mark.parametrize(
    "conflict",
    [
        {"file_id": 99},
        {"asset_id": "other"},
        {"target_authority": {"column": "other"}},
        {"group_column": "test_group"},
        {"exclusions": [8]},
        {"file_id": True},
    ],
)
def test_conflicting_scientific_authority_is_refused_without_partial_rewrite(conflict):
    original = parent(asset_id="spectra", target_authority={"column": "class"}, group_column="batch", exclusions=[3])
    candidate = proposal(source("first"), source(**conflict))
    before = deepcopy(candidate)
    with pytest.raises(ValueError, match="conflicts"):
        substitute_parent_data_loaders(candidate, [parent("first"), original])
    assert candidate == before


@pytest.mark.parametrize("nodes", [[source("renamed")], [source(), source()], [source(), source("extra")], []])
def test_renamed_duplicate_extra_or_missing_sources_are_refused(nodes):
    with pytest.raises(ValueError):
        substitute_parent_data_loaders(proposal(*nodes), [parent()])


def test_same_asset_different_target_has_distinct_scientific_binding():
    first = parent(target_authority={"column": "cetane"})
    second = parent(target_authority={"column": "viscosity"})

    def as_dict(node):
        return {"node_type": node.node_type, "node_id": node.node_id, "parameters": node.parameters}

    assert _data_loader_fingerprints([as_dict(first)]) == _data_loader_fingerprints([as_dict(second)])
    assert source_binding_snapshot([first]) != source_binding_snapshot([second])


def test_two_roles_for_same_asset_are_not_collapsed_to_a_fingerprint_set():
    originals = [
        parent("response_a", target_authority={"column": "a"}),
        parent("response_b", target_authority={"column": "b"}),
    ]
    candidate = proposal(source("response_b"), source("response_a"))
    substitute_parent_data_loaders(candidate, originals)
    assert [node["parameters"]["target_authority"]["column"] for node in candidate["nodes"]] == ["b", "a"]
    with pytest.raises(ValueError):
        substitute_parent_data_loaders(proposal(source("response_a")), originals)


@pytest.mark.asyncio
async def test_changed_parent_source_receipt_refuses_before_candidate_mutation():
    old = parent(target_authority={"column": "a"})
    current = parent(target_authority={"column": "b"})
    result = SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(nodes=[current]))
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    candidate = proposal(source())
    before = deepcopy(candidate)
    validation = await validate_dag_spec_for_parent(
        candidate, 1, session, SimpleNamespace(id=7), source_binding_snapshot([old])
    )
    assert validation["valid"] is False
    assert validation["issues"][0]["code"] == "source_binding_refused"
    assert "changed during generation" in validation["issues"][0]["message"]
    assert candidate == before


def test_unbound_reference_source_cannot_be_added_silently():
    candidate = proposal(source(), {"id": "new-reference", "type": "data.nist_library", "parameters": {}})
    with pytest.raises(ValueError, match="no parent source identity"):
        substitute_parent_data_loaders(candidate, [parent()])


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_parent", [False, True])
async def test_advisory_and_persistence_lock_scope(lock_parent):
    from sqlalchemy.dialects import postgresql

    captured = []

    class Session:
        async def execute(self, statement):
            captured.append(str(statement.compile(dialect=postgresql.dialect())))
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    await validate_dag_spec_for_parent(proposal(), 1, Session(), SimpleNamespace(id=7), lock_parent=lock_parent)
    assert ("FOR UPDATE" in captured[0]) is lock_parent
