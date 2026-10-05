"""Application-owned loading and authorization for canonical DAG baselines."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import (
    CanonicalWorkbenchBaseline,
    CanonicalWorkbenchBaselineError,
    canonical_workbench_baseline_from_records,
)
from spectra_sherpa.app.services.dataset_access import (
    DatasetAccessError,
    require_experiment_access,
    require_file_access,
)


async def load_canonical_workbench_baseline(
    session: AsyncSession,
    *,
    workflow_id: int,
    actor_user_id: int,
    graph_projector=canonical_workbench_baseline_from_records,
) -> CanonicalWorkbenchBaseline:
    """Load one actor-owned workflow and derive its immutable baseline."""

    workflow = await session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == actor_user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    if workflow is None:
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow was not found")
    # Purpose is presentation metadata, not scientific admission authority.
    # The projector still verifies exact graph integrity and fold-safe topology.
    baseline = graph_projector(
        workflow_id=workflow.id,
        stored_integrity_hash=workflow.integrity_hash,
        nodes=workflow.nodes,
        edges=workflow.edges,
    )
    try:
        await require_experiment_access(
            session,
            baseline.dataset.experiment_id,
            actor_user_id,
            workflow.project_id,
        )
        if baseline.dataset.file_id is not None:
            await require_file_access(
                session,
                baseline.dataset.experiment_id,
                baseline.dataset.file_id,
                actor_user_id,
                baseline.dataset.stage,
            )
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=actor_user_id,
            workflow_project_id=workflow.project_id,
            experiment_id=baseline.dataset.experiment_id,
            stage=baseline.dataset.stage,
            file_id=baseline.dataset.file_id,
            asset_id=baseline.dataset.asset_id,
        )
    except DatasetAccessError as exc:
        # A canvas may outlive or be edited away from its authorized data.
        # Re-check exact ownership at admission and keep failures non-disclosing.
        raise CanonicalWorkbenchBaselineError("Saved workbench workflow dataset was not found") from exc
    return baseline


__all__ = ["load_canonical_workbench_baseline"]
