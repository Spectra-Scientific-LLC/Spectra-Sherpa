"""Resolve an operational application from one explicitly reviewed artifact."""

from asyncio import to_thread
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.services.canonical_project_custody import CanonicalArtifactReadGrant
from spectra_sherpa.app.services.model_store import verify_model_artifact_storage_record
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA


@dataclass(frozen=True)
class DeploymentBinding:
    workflow: Workflow
    artifact: ModelArtifact | None
    canonical_artifact_id: int | None = None
    canonical_plan_digest: str | None = None
    canonical_read_grant: CanonicalArtifactReadGrant | None = None
    canonical_application_plan: dict | None = None
    uncertainty_provider: object | None = None

    @property
    def workflow_version_id(self) -> int | None:
        return self.artifact.workflow_version_id if self.artifact is not None else None


async def resolve_deployment_binding(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
    artifact_uid: str | None,
    expected_version_id: int | None = None,
    canonical_artifact_id: int | None = None,
    expected_plan_digest: str | None = None,
    uncertainty_record: dict | None = None,
    uncertainty_population: str | None = None,
) -> DeploymentBinding:
    if uncertainty_record is None and uncertainty_population is not None:
        raise ValueError("Population declaration requires an uncertainty record")
    if canonical_artifact_id is not None:
        if artifact_uid is not None or expected_version_id is not None:
            raise ValueError("Select exactly one saved model or canonical campaign solution")
        return await _resolve_canonical_binding(
            session,
            user_id=user_id,
            workflow_id=workflow_id,
            canonical_artifact_id=canonical_artifact_id,
            expected_plan_digest=expected_plan_digest,
            uncertainty_record=uncertainty_record,
            uncertainty_population=uncertainty_population,
        )
    if uncertainty_record is not None:
        raise ValueError("Prediction intervals require a canonical frozen pipeline")
    if expected_plan_digest is not None:
        raise ValueError("Canonical deployment identity is missing")
    if not artifact_uid:
        raise ValueError("Select one exact deploy-ready model artifact; an unbound workflow cannot be deployed")
    artifact = await session.scalar(
        select(ModelArtifact)
        .where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == user_id,
            ModelArtifact.workflow_id == workflow_id,
            ModelArtifact.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    from spectra_sherpa.app.core.mode_policy import is_local

    if artifact is None or (not is_local() and not artifact.is_deploy_ready):
        raise ValueError("The selected model is unavailable or is not marked deploy-ready")
    if artifact.model_type in {"hca", "dbscan"}:
        raise ValueError("This clustering artifact does not predict new observations")
    if artifact.workflow_version_id is None:
        # Execution may retain an exact graph before a separately named workflow
        # version exists. Its source run is equally immutable provenance; never
        # substitute today's canvas or an unrelated latest version.
        from spectra_sherpa.app.models.execution_run import ExecutionRun
        from spectra_sherpa.app.schemas.run_evidence import RunEvidence
        from spectra_sherpa.app.services.run_output_retention import read_output

        run = await session.scalar(
            select(ExecutionRun).where(
                ExecutionRun.id == artifact.source_run_id,
                ExecutionRun.user_id == user_id,
                ExecutionRun.workflow_id == workflow_id,
                ExecutionRun.project_id == artifact.project_id,
            )
        )
        if run is None or artifact_uid not in (run.produced_artifact_uids or []):
            raise ValueError("The selected model has no exact source workflow version or producing run")
        evidence = RunEvidence.model_validate(run.evidence_completeness)
        definition = evidence.outputs.get("__workflow__", {}).get("definition")
        if evidence.qualification != "qualified" or definition is None or definition.state != "exact":
            raise ValueError("The selected model's source run has no exact retained workflow definition")
        await to_thread(read_output, user_id, definition)
    if expected_version_id is not None and artifact.workflow_version_id != expected_version_id:
        raise ValueError("The selected model no longer matches the bound workflow version")
    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == artifact.workflow_version_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
    )
    source = await session.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id))
    if (artifact.workflow_version_id is not None and version is None) or source is None:
        raise ValueError("The selected model's exact workflow/version provenance is unavailable")
    await to_thread(verify_model_artifact_storage_record, artifact)
    # Apply Saved Model owns its fitted preprocessing and prediction authority.
    # The operational graph never executes today's mutable training canvas.
    workflow = Workflow(
        id=workflow_id,
        user_id=user_id,
        project_id=artifact.project_id,
        name=artifact.name,
        purpose=ANALYSIS_WORKFLOW,
    )
    workflow.nodes = [
        WorkflowNode(
            node_id="deployment_input",
            node_type="deploy.input",
            label="Incoming sample",
            parameters={
                "stream_name": "sample",
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
            position_x=0,
            position_y=0,
        ),
        WorkflowNode(
            node_id="deployment_model",
            node_type="model.load_apply",
            label=artifact.name,
            parameters={"model_id": artifact_uid},
            position_x=200,
            position_y=0,
        ),
    ]
    workflow.edges = [
        WorkflowEdge(
            from_node_id="deployment_input", to_node_id="deployment_model", from_output="default", to_input="X_new"
        )
    ]
    return DeploymentBinding(workflow=workflow, artifact=artifact)


async def _resolve_canonical_binding(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
    canonical_artifact_id: int,
    expected_plan_digest: str | None,
    uncertainty_record: dict | None,
    uncertainty_population: str | None,
) -> DeploymentBinding:
    """Re-admit sealed application authority; never execute a mutable canvas."""
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
    from spectra_sherpa.app.services.canonical_project_custody import (
        resolve_canonical_application_plan_provenance,
        resolve_canonical_artifact_read_grant,
    )
    from spectra_sherpa.app.services.canonical_project_dependencies import canonical_project_dependency_readiness
    from spectra_sherpa.app.services.workflow_access import canonical_application_integrity_hash
    from spectra_sherpa.sdk.canonical_application_execution import application_workflow
    from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact

    record = await session.scalar(
        select(CanonicalProjectArtifact)
        .where(
            CanonicalProjectArtifact.id == canonical_artifact_id,
            CanonicalProjectArtifact.user_id == user_id,
            CanonicalProjectArtifact.workflow_id == workflow_id,
        )
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise ValueError("Canonical campaign solution is unavailable")
    try:
        grant = await resolve_canonical_artifact_read_grant(session, user_id=user_id, workflow_id=workflow_id)
        provenance = await resolve_canonical_application_plan_provenance(
            session, user_id=user_id, workflow_id=workflow_id
        )
    except PermissionError as exc:
        raise ValueError(str(exc)) from exc
    plan = provenance.application_plan
    if expected_plan_digest is not None and plan.application_plan_digest != expected_plan_digest:
        raise ValueError("Canonical campaign application no longer matches the bound plan")
    readiness = canonical_project_dependency_readiness(plan)
    if not readiness.ready:
        raise ValueError(" ".join(readiness.remediation))
    artifact = await to_thread(CanonicalFittedArtifact.load, grant.artifact_dir)
    if artifact.artifact_digest != grant.artifact_digest:
        raise ValueError("Canonical fitted artifact identity has changed")
    source = await session.scalar(
        select(Workflow)
        .where(
            Workflow.id == workflow_id,
            Workflow.user_id == user_id,
        )
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or canonical_application_integrity_hash(source.nodes, source.edges) != grant.application_integrity_hash
    ):
        raise ValueError("Canonical application graph differs from the imported solution")
    from spectra_sherpa.sdk.prediction_uncertainty import BoundPredictionUncertainty, UncertaintyRecord

    uncertainty_provider = (
        None
        if uncertainty_record is None
        else BoundPredictionUncertainty.bind(UncertaintyRecord.load(uncertainty_record), plan, uncertainty_population)
    )
    spec = application_workflow(plan)
    from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash

    # The SDK adds one input root. Everything downstream must match the
    # independently retained graph admitted during package import.
    # WorkflowSpec canonicalizes by node identity, not topological order. A
    # preprocessing node may sort before the SDK input root.
    input_ids = {n["node_id"] for n in spec.payload["nodes"] if n["node_type"] == "deploy.input"}
    application_nodes = [n for n in spec.payload["nodes"] if n["node_id"] not in input_ids]
    application_edges = [
        e for e in spec.payload["edges"] if e["from_node_id"] not in input_ids and e["to_node_id"] not in input_ids
    ]
    if (
        len(input_ids) != 1
        or compute_workflow_hash(application_nodes, application_edges) != grant.application_integrity_hash
    ):
        raise ValueError("Canonical sealed plan differs from the imported application graph")
    workflow = Workflow(
        id=workflow_id, user_id=user_id, project_id=grant.project_id, name=source.name, purpose=ANALYSIS_WORKFLOW
    )
    workflow.nodes = [
        WorkflowNode(
            node_id=n["node_id"], node_type=n["node_type"], parameters=n["parameters"], position_x=0, position_y=0
        )
        for n in spec.payload["nodes"]
    ]
    workflow.edges = [
        WorkflowEdge(
            from_node_id=e["from_node_id"],
            to_node_id=e["to_node_id"],
            from_output=e["from_output"],
            to_input=e["to_input"],
        )
        for e in spec.payload["edges"]
    ]
    return DeploymentBinding(
        workflow=workflow,
        artifact=None,
        canonical_artifact_id=record.id,
        canonical_plan_digest=plan.application_plan_digest,
        canonical_read_grant=grant,
        canonical_application_plan=plan.as_dict(),
        uncertainty_provider=uncertainty_provider,
    )
