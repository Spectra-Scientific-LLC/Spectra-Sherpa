"""Keep ordinary graph edits from silently undoing scientist exclusions."""

from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.app.models.sample_review_revision import SampleReviewRevision
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.pca_review_evidence import filter_id, review_path


def _value(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key)


def source_prefix(nodes, edges, pca_id):
    definition = {
        "nodes": [{key: _value(n, key) for key in ("node_id", "node_type", "parameters")} for n in nodes],
        "edges": [
            {key: _value(e, key) for key in ("from_node_id", "to_node_id", "from_output", "to_input")} for e in edges
        ],
    }
    path, edge = review_path(definition, pca_id)
    prefix = path[: next(i for i, n in enumerate(path) if n["node_id"] == edge["from_node_id"]) + 1]
    # Resolve defaults so browser round-trips cannot invalidate unchanged custody.
    return [
        {**n, "parameters": node_registry.create_node(n["node_type"], n["node_id"], n["parameters"])._resolve_params()}
        for n in prefix
    ]


async def snapshot_review_provenance(session, workflow_id):
    """Read under the workflow admission lock; retain the exact decision snapshot."""
    records = (
        await session.scalars(
            select(SampleReviewRevision)
            .where(SampleReviewRevision.workflow_id == workflow_id)
            .order_by(SampleReviewRevision.revision.desc())
        )
    ).all()
    provenance = {}
    for decision in records:
        if decision.pca_node_id not in provenance:
            provenance[decision.pca_node_id] = {
                "revision": decision.revision,
                "origin_run_id": decision.run_id,
                "post_review": bool(decision.state.get("post_review") or decision.state.get("excluded")),
                "calibration_excluded_count": len(decision.state.get("excluded", [])),
                "heldout_review_omitted_count": len(decision.state.get("heldout_excluded", [])),
                "baseline_run_id": (decision.state.get("test_baseline") or {}).get("run_id"),
                # A saved model must show decisions from its own fit, not the
                # latest mutable workflow review. These IDs remain in the
                # owner-scoped, integrity-checked run evidence.
                "marked": list(decision.state.get("marked", [])),
                "excluded": list(decision.state.get("excluded", [])),
                "heldout_excluded": list(decision.state.get("heldout_excluded", [])),
            }
    return provenance


async def require_review_source_preserved(session, workflow, source_node_id, parameters):
    nodes = [
        {
            "node_id": n.node_id,
            "node_type": n.node_type,
            "parameters": parameters if n.node_id == source_node_id else n.parameters,
        }
        for n in workflow.nodes
    ]
    await require_review_filters_preserved(session, workflow.id, nodes, workflow.edges)


async def require_review_filters_preserved(session, workflow_id, nodes, edges):
    # Curation may seed a new analysis/campaign, but cannot replace the source
    # of an existing campaign authority or validation-fold plan through any
    # graph-edit or data-selection entry point.
    from sqlalchemy.orm import selectinload

    from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
    from spectra_sherpa.app.models.dataset_view import DatasetView
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.workflow_data_selections import selection_from_parameters

    workflow = await session.scalar(
        select(Workflow).where(Workflow.id == workflow_id).options(selectinload(Workflow.nodes))
    )
    if workflow is not None and (workflow.purpose != ANALYSIS_WORKFLOW or workflow.fold_validation_plan):
        old = {n.node_id: n.parameters for n in workflow.nodes if n.node_type == "data.collection_load"}
        requested = {
            _value(n, "node_id"): (_value(n, "parameters") or {})
            for n in nodes
            if _value(n, "node_type") == "data.collection_load"
        }
        for identity in old.keys() | requested.keys():
            before, after = old.get(identity, {}), requested.get(identity, {})
            view_ids = {p.get("dataset_view_id") for p in (before, after)} - {None}
            curated = False
            for view_id in view_ids:
                view = await session.get(DatasetView, view_id)
                curated |= view is not None and view.selection.get("schema_version") == "spectrasherpa-dataset-view/2"
            if not curated:
                continue
            try:
                unchanged = selection_from_parameters(before, dataset_name="source") == selection_from_parameters(
                    after, dataset_name="source"
                )
            except (ValueError, KeyError, TypeError):
                unchanged = False
            if not unchanged:
                raise HTTPException(
                    409,
                    "Campaign seeds and validation folds are pinned. "
                    "Start a separate analysis to change the cohort.",
                )
    records = (
        await session.scalars(
            select(SampleReviewRevision)
            .where(SampleReviewRevision.workflow_id == workflow_id)
            .order_by(SampleReviewRevision.revision.desc())
        )
    ).all()
    seen = set()
    active = False
    for record in records:
        if record.pca_node_id in seen:
            continue
        seen.add(record.pca_node_id)
        if not record.state.get("excluded") and not record.state.get("cohort"):
            continue
        active = True
        if record.state.get("cohort"):
            model = next((n for n in nodes if _value(n, "node_id") == record.pca_node_id), None)
            if model is None or _value(model, "node_type") != "model.fitted_pls":
                raise HTTPException(
                    409, "The reviewed PLS model and cohort are pinned. Start a separate analysis to change model kind."
                )
        try:
            prefix = source_prefix(nodes, edges, record.pca_node_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                409,
                (
                    "The reviewed PLS source and split are pinned. Start a separate analysis to change this path."
                    if record.state.get("cohort")
                    else "Restore active exclusions through Sample Review before changing this analysis path."
                ),
            ) from exc
        if prefix != record.state.get("source_prefix"):
            if record.state.get("cohort"):
                raise HTTPException(
                    409,
                    "This review pins the original source and split even after restore. "
                    "Start a separate analysis for a different population.",
                )
            raise HTTPException(
                409,
                "Restore active exclusions through Sample Review before changing "
                "the source selection or source inclusion.",
            )
        if not record.state.get("excluded"):
            continue
        identity = filter_id(record.pca_node_id)
        node = next((n for n in nodes if _value(n, "node_id") == identity), None)
        original = record.state["original_edge"]
        expected_edges = {
            (original["from_node_id"], identity, original["from_output"], "X"),
            (identity, original["to_node_id"], "default", original["to_input"]),
        }
        attached = [e for e in edges if identity in (_value(e, "from_node_id"), _value(e, "to_node_id"))]
        actual_edges = {
            tuple(_value(e, key) for key in ("from_node_id", "to_node_id", "from_output", "to_input")) for e in attached
        }
        expected = {
            "field": "sample_label",
            "filter_values": record.state["excluded"],
            "invert": True,
            "match_mode": "in_list",
            "case_sensitive": True,
        }
        valid = node is not None and _value(node, "node_type") == "data.filter_samples"
        if valid:
            try:
                actual = node_registry.create_node(
                    "data.filter_samples", identity, _value(node, "parameters")
                )._resolve_params()
                canonical = node_registry.create_node("data.filter_samples", identity, expected)._resolve_params()
                valid = actual == canonical
            except (TypeError, ValueError):
                valid = False
        if not valid or len(attached) != 2 or actual_edges != expected_edges:
            raise HTTPException(
                409,
                "This save would change active scientist exclusions. "
                "Reload the workflow; restore samples through Sample Review first.",
            )

    return active
