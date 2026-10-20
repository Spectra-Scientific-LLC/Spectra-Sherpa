"""Scientist-owned review of exact, retained PCA/PLS observations."""

from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.sample_review_revision import SampleReviewRevision
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.sample_review import SampleReviewAction
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.pca_review_evidence import filter_id, review_filter_parameters, review_path
from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot, build_workflow_version_snapshot
from spectra_sherpa.app.services.workflow_data_selections import (
    selection_from_parameters,
    validate_selection,
    workflow_graph_digest,
)

router = APIRouter(prefix="/workflows")


async def _context(session, user, workflow_id, pca_id, *, write=False):
    if write:
        from spectra_sherpa.app.db.session import begin_serialized_sqlite_write

        await begin_serialized_sqlite_write(session)
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.primary_data_source),
        )
    )
    if write:
        query = query.with_for_update()
    workflow = await session.scalar(query)
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    await require_scientific_access(
        session, user.id, workflow.project_id, "write" if write else "read", resource_owner_id=workflow.user_id
    )
    if workflow.purpose != ANALYSIS_WORKFLOW or workflow.fold_validation_plan:
        raise HTTPException(409, "Campaign authority/folds cannot be edited by sample review.")
    definition = build_saved_definition_snapshot(workflow)
    try:
        review_path(definition, pca_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    revision = await session.scalar(
        select(SampleReviewRevision)
        .where(
            SampleReviewRevision.workflow_id == workflow_id,
            SampleReviewRevision.pca_node_id == pca_id,
        )
        .order_by(SampleReviewRevision.revision.desc())
        .limit(1)
    )
    run = await session.scalar(
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
            ExecutionRun.project_id == workflow.project_id,
        )
        .order_by(ExecutionRun.id.desc())
        .limit(1)
    )
    owned = next((n for n in workflow.nodes if n.node_id == filter_id(pca_id)), None)
    if owned is not None:
        if not revision or not revision.state.get("original_edge") or not revision.state.get("excluded"):
            raise HTTPException(409, "This copied or edited filter has no review authority. Use the original analysis.")
        expected = review_filter_parameters(
            revision.state["excluded"], identity_field=revision.state.get("identity_field", "sample_label")
        )
        try:
            actual_params = node_registry.create_node(
                "data.filter_samples", owned.node_id, owned.parameters
            )._resolve_params()
            expected_params = node_registry.create_node(
                "data.filter_samples", owned.node_id, expected
            )._resolve_params()
        except ValueError as exc:
            raise HTTPException(409, "Review filter parameters are invalid.") from exc
        original = revision.state["original_edge"]
        expected_edges = [
            {
                "from_node_id": original["from_node_id"],
                "to_node_id": owned.node_id,
                "from_output": original["from_output"],
                "to_input": "X",
            },
            {
                "from_node_id": owned.node_id,
                "to_node_id": original["to_node_id"],
                "from_output": "default",
                "to_input": original["to_input"],
            },
        ]
        attached = [e for e in workflow.edges if e.from_node_id == owned.node_id or e.to_node_id == owned.node_id]
        if (
            actual_params != expected_params
            or len(attached) != 2
            or not all(any(_edge_matches(e, spec) for e in attached) for spec in expected_edges)
        ):
            raise HTTPException(409, "Review filter or its connections differ from the scientist decision record.")
    elif revision and revision.state.get("excluded"):
        raise HTTPException(409, "Review filter was removed outside review. Restore its saved version.")
    return workflow, revision, run


async def _receipt(run, pca_id):
    from spectra_sherpa.app.services.retained_review_receipt import retained_review_receipt

    try:
        return await retained_review_receipt(run, pca_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


async def _reviewed_run(session, workflow, revision, latest, pca_id):
    try:
        return latest, await _receipt(latest, pca_id)
    except HTTPException:
        # Neither a failed refit nor a successful legacy-label refit without
        # new typed-ID review evidence may strand a reversible edit. The exact
        # originating receipt authorizes restoration of our still-owned graph,
        # never new exclusions or a transfer to another cohort.
        if not (
            latest
            and revision
            and (
                latest.status in {"error", "failed", "partial", "cancelled"}
                or (
                    latest.status == "completed"
                    and revision.state.get("identity_field", "sample_label") == "sample_label"
                )
            )
            and revision.graph_digest == workflow_graph_digest(workflow)
        ):
            raise
        previous = await session.scalar(
            select(ExecutionRun).where(
                ExecutionRun.id == revision.run_id,
                ExecutionRun.workflow_id == workflow.id,
                ExecutionRun.project_id == workflow.project_id,
            )
        )
        return previous, await _receipt(previous, pca_id)


def _state(revision):
    return deepcopy(revision.state) if revision else {"marked": [], "excluded": [], "original_edge": None}


@router.get("/{workflow_id}/sample-review/{pca_id}")
async def get_sample_review(
    workflow_id: int,
    pca_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    workflow, revision, run = await _context(session, current_user, workflow_id, pca_id)
    latest = run
    run, receipt = await _reviewed_run(session, workflow, revision, latest, pca_id)
    graph = workflow_graph_digest(workflow)
    if revision and revision.source_digest != receipt["source_digest"]:
        raise HTTPException(409, "Source identity changed. Start a separate analysis to review this cohort.")
    history = list(
        (
            await session.scalars(
                select(SampleReviewRevision)
                .where(
                    SampleReviewRevision.workflow_id == workflow_id,
                    SampleReviewRevision.pca_node_id == pca_id,
                )
                .order_by(SampleReviewRevision.revision.desc())
                .limit(100)
            )
        ).all()
    )
    state = _state(revision)
    _verify_cohort(state, receipt)
    if receipt.get("model_kind") == "pls":
        from spectra_sherpa.app.services.pls_review_evidence import statistics

        receipt = {
            **receipt,
            "review_subset_statistics": statistics(
                [
                    row
                    for row in receipt["rows"]
                    if row["role"] == "held_out_test" and row["id"] not in state.get("heldout_excluded", [])
                ],
                receipt["target_names"],
            ),
        }
    return {
        **receipt,
        "run_id": run.id,
        "latest_run_id": latest.id,
        "graph_digest": graph,
        "stale": run.id != latest.id or graph != receipt["graph_digest"] or latest.status != "completed",
        "revision": revision.revision if revision else 0,
        "state": state,
        "history": [
            {
                "revision": r.revision,
                "action": r.action,
                "sample_ids": r.sample_ids,
                "reason": r.reason,
                "run_id": r.run_id,
                "created_by": r.created_by,
                "created_at": r.created_at,
            }
            for r in history
        ],
    }


def _verify_cohort(state, receipt):
    from spectra_sherpa.app.services.retained_review_receipt import verify_review_cohort

    try:
        verify_review_cohort(state, receipt)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def _edge_matches(edge, spec):
    return all(getattr(edge, key) == value for key, value in spec.items())


def _replace_filter(workflow, pca_id, state, receipt, reason):
    """Only the generated edge is changed; all other authored graph state survives."""
    identity = filter_id(pca_id)
    node = next((n for n in workflow.nodes if n.node_id == identity), None)
    if node is None and state["excluded"]:
        edge_spec = receipt["insertion_edge"]
        edge = next((e for e in workflow.edges if _edge_matches(e, edge_spec)), None)
        if edge is None or edge.to_node_id == identity:
            raise HTTPException(409, "Insertion edge changed; rerun before excluding samples.")
        from spectra_sherpa.app.services.sample_review_custody import source_prefix

        state["source_prefix"] = source_prefix(workflow.nodes, workflow.edges, pca_id)
        state["original_edge"] = edge_spec
        destination = next(n for n in workflow.nodes if n.node_id == edge.to_node_id)
        node = WorkflowNode(
            node_id=identity,
            node_type="data.filter_samples",
            label="Reviewed sample exclusions",
            parameters={},
            position_x=(destination.position_x or 0) - 180,
            position_y=destination.position_y or 0,
        )
        workflow.nodes.append(node)
        workflow.edges.remove(edge)
        workflow.edges.extend(
            [
                WorkflowEdge(
                    from_node_id=edge_spec["from_node_id"],
                    to_node_id=identity,
                    from_output=edge_spec["from_output"],
                    to_input="X",
                ),
                WorkflowEdge(
                    from_node_id=identity,
                    to_node_id=edge_spec["to_node_id"],
                    from_output="default",
                    to_input=edge_spec["to_input"],
                ),
            ]
        )
    if node is not None:
        if state["excluded"]:
            node.parameters = review_filter_parameters(
                state["excluded"], identity_field=state.get("identity_field", "sample_label")
            )
            node.annotation = f"Scientist-reviewed exclusions. Reason: {reason}. Full history: sample review."
        else:
            original = state.get("original_edge")
            if not original:
                raise HTTPException(409, "Original cohort edge is unavailable; cannot restore automatically.")
            workflow.edges[:] = [e for e in workflow.edges if e.from_node_id != identity and e.to_node_id != identity]
            workflow.edges.append(WorkflowEdge(**original))
            workflow.nodes.remove(node)


@router.post("/{workflow_id}/sample-review/{pca_id}")
async def apply_sample_review(
    workflow_id: int,
    pca_id: str,
    payload: SampleReviewAction,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if current_user.principal_kind != "human":
        raise HTTPException(403, "Sample review decisions require a scientist account.")
    workflow, revision, run = await _context(session, current_user, workflow_id, pca_id, write=True)
    graph = workflow_graph_digest(workflow)
    if graph != payload.expected_graph_digest or (revision.revision if revision else 0) != payload.expected_revision:
        raise HTTPException(409, "Workflow or review changed. Reload before applying this decision.")
    if run is None or run.id != payload.expected_latest_run_id:
        raise HTTPException(409, "A newer run exists. Reload the review before applying this decision.")
    latest = run
    run, receipt = await _reviewed_run(session, workflow, revision, latest, pca_id)
    if run.id != payload.run_id:
        raise HTTPException(409, "Reviewed run changed. Reload before applying this decision.")
    if payload.source_digest != receipt["source_digest"] or (
        revision and revision.source_digest != payload.source_digest
    ):
        raise HTTPException(409, "Source identity changed; review cannot be transferred to another population.")
    state = _state(revision)
    if receipt.get("identity_field") != "sample_id":
        # Historical evidence stays readable and existing exclusions can be
        # restored, but display-label receipts cannot authorize a new review.
        if payload.action not in {"restore", "restore_test"} or revision is None:
            raise HTTPException(
                409,
                "New reviews require typed sample_id values. Attach a sample table with sample_id "
                "or re-import with typed IDs, then rerun. Historical review evidence remains available.",
            )
    else:
        if revision and state.get("identity_field", "sample_label") != "sample_id":
            raise HTTPException(409, "Start a separate analysis to review typed IDs; this review used display labels.")
        state["identity_field"] = "sample_id"
    # Restoring after a failed rerun is safe only when the graph is precisely our last edit.
    stale = run.id != latest.id or receipt["graph_digest"] != graph or latest.status != "completed"
    if stale and not (payload.action in {"restore", "restore_test"} and revision and revision.graph_digest == graph):
        raise HTTPException(409, "Rerun the current workflow before selecting new exclusions.")
    rows = {row["id"]: row for row in receipt["rows"]}
    if any(identity not in rows for identity in payload.sample_ids):
        raise HTTPException(400, "Selection contains IDs outside the exact reviewed source.")
    selected = set(payload.sample_ids)
    _verify_cohort(state, receipt)
    if receipt.get("model_kind") == "pls":
        from spectra_sherpa.app.services.sample_review_custody import source_prefix

        state.setdefault("cohort", {key: receipt[key] for key in ("calibration_ids", "heldout_ids")})
        state.setdefault("source_prefix", source_prefix(workflow.nodes, workflow.edges, pca_id))
        state.setdefault("test_baseline", {"run_id": run.id, "statistics": receipt["full_test_statistics"]})
        state["post_review"] = bool(
            state.get("post_review")
            or payload.action == "exclude"
            or any(rows[x]["role"] == "held_out_test" for x in selected)
        )
    if payload.action in {"exclude_test", "restore_test"}:
        if receipt.get("model_kind") != "pls" or any(rows[x]["role"] != "held_out_test" for x in selected):
            raise HTTPException(400, "Select only original held-out test observations for a review subset.")
        if not payload.acknowledge_post_review:
            raise HTTPException(400, "Acknowledge that this subset is post-review and is not independent validation.")
        masked = set(state.get("heldout_excluded", []))
        masked = masked | selected if payload.action == "exclude_test" else masked - selected
        if len(masked) >= len(receipt["heldout_ids"]):
            raise HTTPException(400, "Keep at least one held-out observation in the review subset.")
        state["heldout_excluded"] = [x for x in receipt["heldout_ids"] if x in masked]
    elif payload.action in {"mark", "unmark"}:
        marks = set(state["marked"])
        state["marked"] = sorted(marks | selected if payload.action == "mark" else marks - selected)
    else:
        excluded = set(state["excluded"])
        if payload.action == "exclude" and any(rows[x]["role"] != "calibration" for x in selected):
            raise HTTPException(
                400,
                "Only active calibration samples can be excluded from training. "
                "Use the separate held-out review subset action.",
            )
        excluded = excluded | selected if payload.action == "exclude" else excluded - selected
        state["excluded"] = [identity for identity in rows if identity in excluded]
        if len(excluded) > 1024 or sum(len(x.encode()) for x in excluded) > 4096:
            raise HTTPException(400, "Combined exclusions exceed 1,024 IDs / 4,096 UTF-8 bytes.")
        if sum(row["role"] != "held_out_test" for row in rows.values()) - len(excluded) <= receipt["n_components"]:
            raise HTTPException(400, "Retain more calibration samples than model components.")
        source = next(n for n in workflow.nodes if n.node_type == "data.collection_load")
        try:
            selection = selection_from_parameters(source.parameters, dataset_name=source.label or source.node_id)
            await validate_selection(
                session, selection=selection, user_id=current_user.id, workflow_project_id=workflow.project_id
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, "Source binding no longer matches the reviewed file.") from exc
        _replace_filter(workflow, pca_id, state, receipt, payload.reason)
    workflow.integrity_hash = workflow_graph_digest(workflow)
    record = SampleReviewRevision(
        workflow_id=workflow_id,
        pca_node_id=pca_id,
        revision=payload.expected_revision + 1,
        run_id=run.id,
        created_by=current_user.id,
        action=payload.action,
        reason=payload.reason,
        sample_ids=payload.sample_ids,
        source_digest=receipt["source_digest"],
        graph_digest=workflow.integrity_hash,
        state=state,
    )
    session.add(record)
    if payload.action in {"exclude", "restore"}:
        version = await session.scalar(
            select(WorkflowVersion.version_number)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version_number.desc())
            .limit(1)
        )
        session.add(
            WorkflowVersion(
                workflow_id=workflow_id,
                version_number=int(version or 0) + 1,
                created_by=current_user.id,
                change_description=f"Sample review: {payload.action}; {payload.reason}",
                snapshot=build_workflow_version_snapshot(workflow),
            )
        )
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.sample_review.applied",
        target_type="Workflow",
        target_id=workflow.id,
        before={"revision": payload.expected_revision, "graph_digest": graph},
        after={
            "revision": record.revision,
            "graph_digest": record.graph_digest,
            "action": payload.action,
            "sample_count": len(payload.sample_ids),
            "run_id": run.id,
        },
        context={"origin": "sample_review", "reason": payload.reason},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Another review was saved. Reload before applying this decision.") from exc
    return {
        "revision": record.revision,
        "graph_digest": record.graph_digest,
        "rerun_required": payload.action in {"exclude", "restore"},
    }
