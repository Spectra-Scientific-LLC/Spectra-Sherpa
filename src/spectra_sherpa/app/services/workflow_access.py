"""Shared workflow execution access checks.

DAG nodes run outside the FastAPI dependency stack. Any endpoint or service
that turns stored workflow rows into a DAGExecutor must validate data and
model references before execution, because individual nodes may dereference
filesystem-backed artifacts without user/project context.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import QUALIFIED_SCIENTIFIC_NODES, require_scientific_access
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dataset_access import (
    DatasetAccessError,
)
from spectra_sherpa.app.services.dataset_access import (
    require_experiment_access as require_experiment_access_domain,
)
from spectra_sherpa.app.services.dataset_access import (
    require_file_access as require_file_access_domain,
)

DATA_ACCESS_NODE_TYPES = {"data.collection_load", "data.file_load", "data.load_group"}
TRIAL_SOURCE_NODE_TYPES = DATA_ACCESS_NODE_TYPES | {
    "custom.catmull_rom_curve",
    "custom.concentration_curve",
    "data.nist_library",
    "data.synthetic_curve",
    "deploy.input",
}
MODEL_LOAD_NODE_TYPES = {"model.load_apply"}
CANONICAL_APPLICATION_NODE_TYPES = {
    "classification.apply_plsda",
    "model.apply_fitted_pls",
    "model.apply_fitted_pcr",
    "model.apply_fitted_svr",
    "model.apply_fitted_linear_regression",
    "preprocess.apply_fitted_emsc",
    "preprocess.apply_fitted_msc",
    "preprocess.apply_fitted_osc",
    "preprocess.apply_fitted_scale",
}
CANONICAL_ARTIFACT_BINDING_FIELDS = frozenset(
    {
        "artifact_digest",
        "state_node_id",
        "state_digest",
        "state_content_digest",
        "serializer",
        "source_contract_digest",
    }
)
CANONICAL_LOCAL_SOURCE_NODE_ID = "canonical-local-source"


def workflow_requires_canonical_artifact_grant(nodes: list[Any]) -> bool:
    """Whether this saved graph requests imported canonical-artifact custody.

    ``model.apply_fitted_pls`` and ``classification.apply_plsda`` each
    support two explicit custody modes: a typed local fitted-state edge, or a
    complete imported-artifact binding in node parameters.  Node type alone
    therefore cannot decide whether project-level artifact custody is needed.
    Treat any declared binding field as artifact intent so malformed partial
    bindings still fail closed in the custody/preflight path.
    """

    for node in nodes:
        if getattr(node, "node_type", None) not in CANONICAL_APPLICATION_NODE_TYPES:
            continue
        parameters = getattr(node, "parameters", None)
        if isinstance(parameters, dict) and any(
            field in parameters and parameters[field] is not None for field in CANONICAL_ARTIFACT_BINDING_FIELDS
        ):
            return True
    return False


def validate_canonical_artifact_bindings(nodes: list[Any], artifact_digest: str) -> None:
    """Ensure every canonical apply node names the one durable read grant.

    This is deliberately checked before a node runs.  The reader verifies the
    full state binding again, but an edited workflow must not even reach an
    executor with a digest that differs from its project custody record.
    """

    for node in nodes:
        if getattr(node, "node_type", None) not in CANONICAL_APPLICATION_NODE_TYPES:
            continue
        params = getattr(node, "parameters", None)
        if not isinstance(params, dict) or params.get("artifact_digest") != artifact_digest:
            raise HTTPException(status_code=404, detail="Canonical artifact is unavailable for this workflow")


def canonical_application_integrity_hash(nodes: list[Any], edges: list[Any]) -> str:
    """Hash the immutable imported application graph, excluding its local input.

    The canonical package never contains a scientist's sample data.  Its one
    permitted local edit is therefore the ``canonical-local-source`` node and
    the one edge that connects that source to the immutable application graph.
    Everything else must remain byte-for-byte equivalent at the structured
    workflow level to the graph re-admitted during import.
    """

    application_nodes = [node for node in nodes if getattr(node, "node_id", None) != CANONICAL_LOCAL_SOURCE_NODE_ID]
    application_edges = [
        edge
        for edge in edges
        if getattr(edge, "from_node_id", None) != CANONICAL_LOCAL_SOURCE_NODE_ID
        and getattr(edge, "to_node_id", None) != CANONICAL_LOCAL_SOURCE_NODE_ID
    ]
    return compute_workflow_hash(
        [
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "parameters": node.parameters,
            }
            for node in application_nodes
        ],
        [
            {
                "from_node_id": edge.from_node_id,
                "from_output": edge.from_output,
                "to_node_id": edge.to_node_id,
                "to_input": edge.to_input,
            }
            for edge in application_edges
        ],
    )


def validate_canonical_application_graph(
    nodes: list[Any],
    edges: list[Any],
    expected_integrity_hash: str,
) -> None:
    """Fail closed when a canonical application graph differs from custody.

    A known artifact digest grants neither authority nor freedom to revise the
    imported scientific procedure.  The persistent local-source binding is
    allowed, but it must be a single ordinary ``data.file_load`` root into the
    one root of the re-admitted application graph.
    """

    if (
        len(expected_integrity_hash) != 64
        or canonical_application_integrity_hash(nodes, edges) != expected_integrity_hash
    ):
        raise HTTPException(status_code=404, detail="Canonical application graph is unavailable for this workflow")

    source_nodes = [node for node in nodes if getattr(node, "node_id", None) == CANONICAL_LOCAL_SOURCE_NODE_ID]
    if len(source_nodes) != 1 or source_nodes[0].node_type != "data.file_load":
        raise HTTPException(status_code=404, detail="Canonical application graph is unavailable for this workflow")
    source_parameters = source_nodes[0].parameters
    if (
        not isinstance(source_parameters, dict)
        or set(source_parameters)
        not in (
            {"experiment_id", "file_id", "stage"},
            {"experiment_id", "file_id", "stage", "asset_id"},
        )
        or not isinstance(source_parameters["experiment_id"], int)
        or source_parameters["experiment_id"] < 1
        or not isinstance(source_parameters["file_id"], int)
        or source_parameters["file_id"] < 1
        or source_parameters["stage"] not in {"raw", "preprocessed", "synthetic"}
        or (
            "asset_id" in source_parameters
            and (
                not isinstance(source_parameters["asset_id"], str)
                or not source_parameters["asset_id"]
                or source_parameters["asset_id"] != source_parameters["asset_id"].strip()
            )
        )
    ):
        raise HTTPException(status_code=404, detail="Canonical application graph is unavailable for this workflow")
    source_edges = [
        edge
        for edge in edges
        if getattr(edge, "from_node_id", None) == CANONICAL_LOCAL_SOURCE_NODE_ID
        or getattr(edge, "to_node_id", None) == CANONICAL_LOCAL_SOURCE_NODE_ID
    ]
    application_node_ids = {
        node.node_id for node in nodes if getattr(node, "node_id", None) != CANONICAL_LOCAL_SOURCE_NODE_ID
    }
    application_incoming = {
        edge.to_node_id
        for edge in edges
        if getattr(edge, "from_node_id", None) in application_node_ids
        and getattr(edge, "to_node_id", None) in application_node_ids
    }
    root_ids = application_node_ids - application_incoming
    if (
        len(root_ids) != 1
        or len(source_edges) != 1
        or source_edges[0].from_node_id != CANONICAL_LOCAL_SOURCE_NODE_ID
        or source_edges[0].from_output != "default"
        or source_edges[0].to_node_id not in root_ids
        or source_edges[0].to_input != "default"
    ):
        raise HTTPException(status_code=404, detail="Canonical application graph is unavailable for this workflow")


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _merged_node_parameters(node: Any, initial_data: dict[str, Any] | None) -> dict[str, Any]:
    params = getattr(node, "parameters", None)
    merged = dict(params) if isinstance(params, dict) else {}
    node_id = getattr(node, "node_id", None)
    overrides = initial_data.get(node_id) if initial_data and node_id is not None else None
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


async def require_experiment_access(
    session: AsyncSession,
    experiment_id: int,
    user_id: int,
    workflow_project_id: int | None,
) -> None:
    try:
        await require_experiment_access_domain(session, experiment_id, user_id, workflow_project_id)
    except DatasetAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def require_file_access(
    session: AsyncSession,
    experiment_id: int,
    file_id: int,
    user_id: int,
    stage: str | None = None,
) -> None:
    try:
        await require_file_access_domain(session, experiment_id, file_id, user_id, stage)
    except DatasetAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def require_model_artifact_access(
    session: AsyncSession,
    artifact_uid: str,
    user_id: int,
    workflow_project_id: int | None,
) -> None:
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            or_(ModelArtifact.user_id == user_id, uses_managed_project_access()),
            ModelArtifact.is_active.is_(True),
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model artifact '{artifact_uid}' not found")
    if uses_managed_project_access():
        if workflow_project_id is None or model.project_id != workflow_project_id:
            raise HTTPException(404, "Model artifact not found in this project")
        await require_scientific_access(session, user_id, model.project_id, "read")
    if workflow_project_id is not None and model.project_id is not None and model.project_id != workflow_project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Model artifact '{artifact_uid}' is not available in this project",
        )
    from spectra_sherpa.app.services.model_store import (
        ModelArtifactIntegrityError,
        verify_model_artifact_storage_record,
    )

    try:
        verify_model_artifact_storage_record(model)
    except (FileNotFoundError, RuntimeError, ModelArtifactIntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Model artifact storage is unavailable or invalid") from exc


async def validate_workflow_execution_access(
    nodes: list[Any],
    initial_data: dict[str, Any] | None,
    user_id: int,
    workflow_project_id: int | None,
    session: AsyncSession,
) -> dict[str, Any]:
    """Fail closed before workflow execution dereferences DB/file artifacts."""
    from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

    admitted_datasets: dict[str, Any] = {}
    for node in nodes:
        node_type = getattr(node, "node_type", None)

        if uses_managed_project_access():
            # Admit only reviewed scientific journeys. Local-path and plugin
            # nodes never inherit admission from a numerical node family.
            if node_type not in QUALIFIED_SCIENTIFIC_NODES:
                raise HTTPException(403, detail={"code": "scientific_node_not_qualified", "node_type": node_type})
            from spectra_sherpa.app.services.dag.node_base import node_registry

            try:
                # Validate the same effective parameters the executor receives,
                # including request overrides. Admission must not silently clamp
                # or substitute the scientist's saved values.
                node_registry.get_metadata(node_type).canonicalize_managed_parameters(
                    _merged_node_parameters(node, initial_data)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    422,
                    detail={
                        "code": "scientific_parameters_not_qualified",
                        "node_type": node_type,
                        "reason": str(exc),
                    },
                ) from exc
            if node_type == "data.file_load":
                params = _merged_node_parameters(node, initial_data)
                if _int_or_none(params.get("experiment_id")) is None or _int_or_none(params.get("file_id")) is None:
                    raise HTTPException(403, "An exact project experiment file is required")

        if node_type in MODEL_LOAD_NODE_TYPES:
            params = _merged_node_parameters(node, initial_data)
            model_id = params.get("model_id")
            if isinstance(model_id, str) and model_id:
                await require_model_artifact_access(session, model_id, user_id, workflow_project_id)
            elif uses_managed_project_access():
                raise HTTPException(403, "An exact admitted model_id is required")
            continue

        if node_type not in TRIAL_SOURCE_NODE_TYPES:
            continue

        params = _merged_node_parameters(node, initial_data)
        experiment_id = _int_or_none(params.get("experiment_id"))
        file_id = _int_or_none(params.get("file_id"))
        stage = params.get("stage")
        asset_id = params.get("asset_id")
        # Canonical collection nodes persist an empty string to represent the
        # single automatically selected asset.  The trial-grant boundary uses
        # ``None`` for that same meaning; forwarding ``""`` would turn an
        # omitted selector into an explicit (and necessarily invalid) asset.
        admitted_asset_id = asset_id if isinstance(asset_id, str) and asset_id else None

        collection_selectors = {}
        if node_type == "data.collection_load":
            selected = params.get("selected_file_ids")
            if not isinstance(selected, list) or not selected:
                raise HTTPException(422, "Collection loading requires exact selected file IDs")
            member_ids = [
                int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else _int_or_none(value)
                for value in selected
            ]
            if any(value is None or value < 1 for value in member_ids) or len(set(member_ids)) != len(member_ids):
                raise HTTPException(422, "Collection file IDs must be distinct positive integers")
            collection_selectors["file_ids"] = member_ids
        admission = await require_trial_dataset_access(
            session=session,
            user_id=user_id,
            workflow_project_id=workflow_project_id,
            experiment_id=experiment_id,
            stage=stage if isinstance(stage, str) else None,
            file_id=file_id,
            asset_id=admitted_asset_id,
            **collection_selectors,
        )
        node_id = getattr(node, "node_id", None)
        if admission is not None and isinstance(node_id, str) and node_id:
            admitted_datasets[node_id] = admission

        if node_type not in DATA_ACCESS_NODE_TYPES or experiment_id is None:
            continue

        await require_experiment_access(session, experiment_id, user_id, workflow_project_id)
        if file_id is not None:
            await require_file_access(
                session,
                experiment_id,
                file_id,
                user_id,
                stage=stage if isinstance(stage, str) else None,
            )
    return admitted_datasets


def admitted_model_artifact_ids(nodes, initial_data) -> tuple[str, ...] | None:
    """Project already-validated model references into runtime read authority.

    Must be called immediately after validate_workflow_execution_access.
    A connected model_ref cannot grant ambient access to a different artifact.
    """
    if not uses_managed_project_access():
        return None
    return tuple(
        sorted(
            {
                _merged_node_parameters(node, initial_data)["model_id"]
                for node in nodes
                if getattr(node, "node_type", None) in MODEL_LOAD_NODE_TYPES
            }
        )
    )
