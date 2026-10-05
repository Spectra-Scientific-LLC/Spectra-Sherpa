"""M4.15b tests for deriving managed candidates from saved workbench DAGs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import spectra_sherpa.app.services.dag.nodes.data.loaders  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge as WorkflowEdgeRecord
from spectra_sherpa.app.models.workflow_node import WorkflowNode as WorkflowNodeRecord
from spectra_sherpa.app.services.canonical_workbench_baseline import load_canonical_workbench_baseline
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import (
    CanonicalWorkbenchBaseline,
    CanonicalWorkbenchBaselineError,
    canonical_workbench_baseline_from_records,
)
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.types import type_registry


@dataclass
class _Node:
    node_id: str
    node_type: str
    parameters: dict[str, object]


@dataclass
class _Edge:
    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


@pytest.fixture(autouse=True)
def _load_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def test_legacy_baseline_digest_fixtures_and_grouping_version_dispatch() -> None:
    from dataclasses import replace

    from spectra_sherpa.app.services.dag.canonical_workbench_baseline import CanonicalSeedExecutionBaseline

    nodes, edges, integrity = _records()
    source = canonical_workbench_baseline_from_records(
        workflow_id=10, stored_integrity_hash=integrity, nodes=nodes, edges=edges
    )
    # These fixtures project the current admitted graph, including its current
    # source-bound Scale contract, through three serialization versions. They
    # are not a claim that previously persisted baseline bytes changed.
    assert source.digest == "3619fe3595f81d5144116b7f5393df8d78d5dad192d1929133c4ab725413e133"
    legacy_source = replace(source, schema_version="spectra-canonical-workbench-baseline/5")
    assert legacy_source.digest == "39301c7bf2c2dabc65ee1142d70943e8d3b1a5d39a8d46c99fbb73acddac539a"
    derived = CanonicalSeedExecutionBaseline(
        workflow_id=source.workflow_id,
        workflow_integrity_hash=source.workflow_integrity_hash,
        dataset=source.dataset,
        graph=source.graph,
        source_baseline=source,
        seed_public_id="seed-legacy",
        seed_evidence_digest="a" * 64,
        examination_digest="b" * 64,
    )
    assert derived.digest == "021bf44babad696345830cb3ed7bb9de1b56f49f0b9b312b26f559ff420b2fbc"
    for baseline in (source, legacy_source, derived):
        assert CanonicalWorkbenchBaseline.from_dict(baseline.as_dict()).as_dict() == baseline.as_dict()
    assert "saved_grouping" not in derived.as_dict()


def test_saved_grouping_closed_utf8_custody_and_derived_dispatch() -> None:
    import hashlib
    import json
    from copy import deepcopy
    from dataclasses import replace

    from spectra_sherpa.app.services.dag.canonical_workbench_baseline import (
        GROUPED_SEED_EXECUTION_BASELINE_VERSION,
        CanonicalSeedExecutionBaseline,
        read_saved_grouping,
    )

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    grouping = {
        "schema_version": "spectra-development-grouping/1",
        "mode": "required_column",
        "column": "échantillon",
        "grouped": True,
        "dataset_content_digest": "a" * 64,
    }
    custody = {
        "schema_version": "spectra-saved-run-grouping/1",
        "projection_version": "spectra-saved-run-optimization-projection/1",
        "projection_digest": "b" * 64,
        "retained_definition_digest": "c" * 64,
        "grouping": grouping,
        "grouping_digest": digest(grouping),
    }
    custody["custody_digest"] = digest(custody)
    assert read_saved_grouping(custody) == custody
    current_custody = {
        **custody,
        "projection_version": "spectra-saved-run-optimization-projection/2",
    }
    current_custody["custody_digest"] = digest(
        {key: value for key, value in current_custody.items() if key != "custody_digest"}
    )
    assert read_saved_grouping(current_custody) == current_custody
    nodes, edges, integrity = _records()
    source = canonical_workbench_baseline_from_records(
        workflow_id=10, stored_integrity_hash=integrity, nodes=nodes, edges=edges
    )
    derived = CanonicalSeedExecutionBaseline(
        workflow_id=source.workflow_id,
        workflow_integrity_hash=source.workflow_integrity_hash,
        dataset=source.dataset,
        graph=source.graph,
        source_baseline=source,
        seed_public_id="seed-current",
        seed_evidence_digest="a" * 64,
        examination_digest="b" * 64,
        schema_version=GROUPED_SEED_EXECUTION_BASELINE_VERSION,
        saved_grouping=custody,
    )
    assert CanonicalWorkbenchBaseline.from_dict(derived.as_dict()).as_dict() == derived.as_dict()
    derived.require_grouping(grouping)
    with pytest.raises(CanonicalWorkbenchBaselineError):
        derived.require_grouping({**grouping, "column": "alternate"})
    with pytest.raises(CanonicalWorkbenchBaselineError):
        replace(derived, schema_version="spectra-canonical-seed-execution-baseline/1")
    for field, value in (
        ("schema_version", "unknown"),
        ("projection_version", "unknown"),
        ("projection_digest", "bad"),
        ("grouping_digest", "0" * 64),
        ("custody_digest", "0" * 64),
        ("extra", True),
    ):
        with pytest.raises(CanonicalWorkbenchBaselineError):
            read_saved_grouping({**custody, field: value})
    for field, value in (("grouped", 1), ("column", ""), ("mode", "unknown"), ("extra", True)):
        forged = deepcopy(custody)
        forged["grouping"][field] = value
        forged["grouping_digest"] = digest(forged["grouping"])
        forged["custody_digest"] = digest({k: v for k, v in forged.items() if k != "custody_digest"})
        with pytest.raises(CanonicalWorkbenchBaselineError):
            read_saved_grouping(forged)


def _records() -> tuple[list[_Node], list[_Edge], str]:
    nodes = [
        _Node(
            "source",
            "data.file_load",
            {
                "experiment_id": 11,
                "file_id": 12,
                "stage": "raw",
                "asset_id": "a",
                "target_authority": _target_authority("Moisture", "continuous", "a" * 64),
            },
        ),
        _Node("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        _Node("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        _Node("score", "diagnostics.regression_evaluator", {}),
    ]
    edges = [_Edge("source", "scale"), _Edge("scale", "model"), _Edge("model", "score")]
    integrity = compute_workflow_hash(
        [{"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in nodes],
        [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in edges
        ],
    )
    return nodes, edges, integrity


def _integrity(nodes: list[_Node], edges: list[_Edge]) -> str:
    return compute_workflow_hash(
        [{"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in nodes],
        [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in edges
        ],
    )


def _target_authority(column: str, target_type: str, source_digest: str) -> dict[str, object]:
    return {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": column,
        "target_type": target_type,
        "units": None,
        "source_digest": source_digest,
    }


def test_saved_workbench_baseline_binds_integrity_source_and_admitted_graph() -> None:
    nodes, edges, integrity = _records()

    baseline = canonical_workbench_baseline_from_records(
        workflow_id=9,
        stored_integrity_hash=integrity,
        nodes=nodes,
        edges=edges,
    )

    assert baseline.workflow_id == 9
    assert baseline.workflow_integrity_hash == integrity
    assert baseline.dataset.as_dict() == {
        "experiment_id": 11,
        "file_id": 12,
        "stage": "raw",
        "asset_id": "a",
        "source_node_id": "source",
        "target_authority": _target_authority("Moisture", "continuous", "a" * 64),
        "group_column": None,
    }
    assert [node.node_id for node in baseline.graph.nodes] == ["scale", "model", "score"]
    assert baseline.as_dict()["mutable_slots"] == []
    assert len(baseline.digest) == 64


def test_persisted_baseline_re_admission_rejects_tampered_scientific_identity() -> None:
    """The Runner may reuse only the exact baseline originally admitted from the canvas."""

    nodes, edges, integrity = _records()
    baseline = canonical_workbench_baseline_from_records(
        workflow_id=9,
        stored_integrity_hash=integrity,
        nodes=nodes,
        edges=edges,
    )

    assert CanonicalWorkbenchBaseline.from_dict(baseline.as_dict()) == baseline

    tampered = baseline.as_dict()
    tampered["validation_graph"]["nodes"][1]["parameters"]["n_components"] = 3
    with pytest.raises(CanonicalWorkbenchBaselineError, match="graph cannot be re-admitted|digest"):
        CanonicalWorkbenchBaseline.from_dict(tampered)


def test_persisted_version_five_baseline_replays_with_its_original_digest() -> None:
    nodes, edges, integrity = _records()
    current = canonical_workbench_baseline_from_records(
        workflow_id=9,
        stored_integrity_hash=integrity,
        nodes=nodes,
        edges=edges,
    )
    legacy = CanonicalWorkbenchBaseline(
        workflow_id=current.workflow_id,
        workflow_integrity_hash=current.workflow_integrity_hash,
        dataset=current.dataset,
        graph=current.graph,
        schema_version="spectra-canonical-workbench-baseline/5",
    )

    payload = legacy.as_dict()
    assert "group_column" not in payload["dataset"]
    assert CanonicalWorkbenchBaseline.from_dict(payload) == legacy


def test_saved_workbench_baseline_rejects_stale_integrity_and_untrusted_source_shapes() -> None:
    nodes, edges, integrity = _records()
    with pytest.raises(CanonicalWorkbenchBaselineError, match="integrity"):
        canonical_workbench_baseline_from_records(
            workflow_id=9,
            stored_integrity_hash="0" * 64,
            nodes=nodes,
            edges=edges,
        )

    nodes[0].parameters["unexpected"] = "not an admission channel"
    integrity = compute_workflow_hash(
        [{"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in nodes],
        [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in edges
        ],
    )
    with pytest.raises(CanonicalWorkbenchBaselineError, match="canonical node parameters"):
        canonical_workbench_baseline_from_records(
            workflow_id=9,
            stored_integrity_hash=integrity,
            nodes=nodes,
            edges=edges,
        )


def test_saved_workbench_baseline_requires_exactly_one_source_at_the_scientific_root() -> None:
    nodes, edges, integrity = _records()
    nodes.append(
        _Node(
            "source-two",
            "data.file_load",
            {
                "experiment_id": 13,
                "file_id": 14,
                "stage": "raw",
                "target_authority": _target_authority("Moisture", "continuous", "d" * 64),
            },
        )
    )
    integrity = _integrity(nodes, edges)
    with pytest.raises(CanonicalWorkbenchBaselineError, match="exactly one"):
        canonical_workbench_baseline_from_records(
            workflow_id=9,
            stored_integrity_hash=integrity,
            nodes=nodes,
            edges=edges,
        )


def test_saved_workbench_baseline_admits_exact_grouped_collection_supervision() -> None:
    nodes = [
        _Node(
            "source",
            "data.load_group",
            {
                "source_mode": "experiment_collection",
                "folder_path": "",
                "pattern": "",
                "recursive": False,
                "sort_by": "filename",
                "group_title": "Grouped corpus",
                "asset_id": "spectrum",
                "experiment_id": 11,
                "stage": "raw",
                "source_manifest_sha256": "a" * 64,
                "collection_definition_sha256": "b" * 64,
                "scientific_collection_sha256": "c" * 64,
            },
        ),
        _Node(
            "supervision",
            "data.attach_target",
            {
                "target_source": "sample_table_column",
                "target_type": "categorical",
                "target_column": "specimen_id",
                "target_authority": _target_authority("specimen_id", "categorical", "c" * 64),
                "group_column": "block",
            },
        ),
        _Node(
            "window",
            "selection.variable_select",
            {"method": "interval", "region_start": 3100.0, "region_end": 650.0},
        ),
        _Node("model", "classification.plsda", {"n_components": 5, "scale": False}),
        _Node("score", "diagnostics.classification_evaluator", {}),
    ]
    edges = [
        _Edge("source", "supervision", to_input="X"),
        _Edge("supervision", "window"),
        _Edge("window", "model"),
        _Edge("model", "score", from_output="predictions"),
    ]

    baseline = canonical_workbench_baseline_from_records(
        workflow_id=10,
        stored_integrity_hash=_integrity(nodes, edges),
        nodes=nodes,
        edges=edges,
    )

    assert baseline.dataset.as_dict() == {
        "experiment_id": 11,
        "file_id": None,
        "stage": "raw",
        "asset_id": "spectrum",
        "source_node_id": "source",
        "target_authority": _target_authority("specimen_id", "categorical", "c" * 64),
        "group_column": "block",
    }
    assert [node.node_id for node in baseline.graph.nodes] == ["window", "model", "score"]

    for field, value in (
        ("source_manifest_sha256", "not-a-digest"),
        ("source_mode", "folder"),
    ):
        mutated = [_Node(node.node_id, node.node_type, dict(node.parameters)) for node in nodes]
        mutated[0].parameters[field] = value
        with pytest.raises(CanonicalWorkbenchBaselineError):
            canonical_workbench_baseline_from_records(
                workflow_id=10,
                stored_integrity_hash=_integrity(mutated, edges),
                nodes=mutated,
                edges=edges,
            )

    wrong_port_edges = [_Edge("source", "supervision", to_input="sample_table"), *edges[1:]]
    with pytest.raises(CanonicalWorkbenchBaselineError):
        canonical_workbench_baseline_from_records(
            workflow_id=10,
            stored_integrity_hash=_integrity(nodes, wrong_port_edges),
            nodes=nodes,
            edges=wrong_port_edges,
        )

    extra_input_edges = [*edges, _Edge("window", "supervision", to_input="y")]
    with pytest.raises(CanonicalWorkbenchBaselineError):
        canonical_workbench_baseline_from_records(
            workflow_id=10,
            stored_integrity_hash=_integrity(nodes, extra_input_edges),
            nodes=nodes,
            edges=extra_input_edges,
        )


@pytest.mark.asyncio
async def test_database_loader_is_actor_scoped_and_reads_persisted_records(tmp_path) -> None:
    """A route cannot name another user's saved baseline by integer ID."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'baseline.db'}")
    tables = [
        User.__table__,
        Experiment.__table__,
        ExperimentFile.__table__,
        Workflow.__table__,
        WorkflowNodeRecord.__table__,
        WorkflowEdgeRecord.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    nodes, edges, integrity = _records()
    async with factory() as session:
        session.add_all([User(id=1, username="owner", is_active=True), User(id=2, username="other", is_active=True)])
        session.add(
            Experiment(
                id=11,
                user_id=1,
                name="Campaign spectra",
                metadata_path="/tmp/campaign-spectra.json",
            )
        )
        session.add(
            ExperimentFile(
                id=12,
                experiment_id=11,
                file_path="/tmp/campaign-spectra.npz",
                stage="raw",
            )
        )
        session.add(
            Workflow(
                id=9,
                user_id=1,
                name="Saved PLS baseline",
                status="active",
                purpose="analysis",
                integrity_hash=integrity,
            )
        )
        session.add(
            Workflow(
                id=10,
                user_id=1,
                name="Ordinary analysis",
                status="active",
                purpose="analysis",
                integrity_hash=integrity,
            )
        )
        session.add_all(
            [
                WorkflowNodeRecord(
                    workflow_id=9,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    parameters=node.parameters,
                )
                for node in nodes
            ]
        )
        session.add_all(
            [
                WorkflowEdgeRecord(
                    workflow_id=9,
                    from_node_id=edge.from_node_id,
                    to_node_id=edge.to_node_id,
                    from_output=edge.from_output,
                    to_input=edge.to_input,
                )
                for edge in edges
            ]
        )
        await session.commit()
    async with factory() as session:
        baseline = await load_canonical_workbench_baseline(session, workflow_id=9, actor_user_id=1)
        assert baseline.graph.digest
        with pytest.raises(CanonicalWorkbenchBaselineError, match="not found"):
            await load_canonical_workbench_baseline(session, workflow_id=9, actor_user_id=2)
        with pytest.raises(CanonicalWorkbenchBaselineError):
            await load_canonical_workbench_baseline(session, workflow_id=10, actor_user_id=1)
        # A canvas can become stale after it was saved. Admission must re-check
        # the binding rather than letting a campaign discover the mismatch in
        # a later worker step.
        experiment = await session.get(Experiment, 11)
        assert experiment is not None
        experiment.user_id = 2
        await session.commit()
        with pytest.raises(CanonicalWorkbenchBaselineError, match="dataset was not found"):
            await load_canonical_workbench_baseline(session, workflow_id=9, actor_user_id=1)
    await engine.dispose()
