"""
Custom Algo CRUD API endpoints — project-scoped.

Each mutating endpoint performs a three-phase commit:
1. Validate + DB write
2. Atomic file write (.tmp → os.replace)
3. Registry reload (unregister old → import new)

On failure at any phase, earlier phases are compensated.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.models.custom_algo import CustomAlgo
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.custom_algos import (
    CustomAlgoCreate,
    CustomAlgoDetail,
    CustomAlgoUpdate,
)
from spectra_sherpa.app.schemas.workflows import NodeMetadataInfo, NodePortInfo
from spectra_sherpa.app.services.custom_algo_codegen import (
    make_node_type,
    reload_into_registry,
    unregister_and_remove,
    validate_code_syntax,
    validate_slug,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/custom-algos")


def _check_custom_code_allowed() -> None:
    """Fail closed when server policy disables custom code execution."""
    from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution

    if not allows_custom_code_execution():
        raise HTTPException(
            status_code=403,
            detail="Custom code execution is disabled by server policy",
        )




# ── List ────────────────────────────────────────────────────────────


@router.get("", response_model=list[CustomAlgoDetail])
async def list_custom_algos(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[CustomAlgoDetail]:
    """List all custom algos for a project (includes code)."""
    await require_project(project_id, current_user.id, session)

    result = await session.execute(
        select(CustomAlgo)
        .where(CustomAlgo.project_id == project_id)
        .order_by(CustomAlgo.name)
    )
    return [CustomAlgoDetail.model_validate(a) for a in result.scalars().all()]


@router.get("/nodes", response_model=list[NodeMetadataInfo])
async def list_custom_algo_nodes(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[NodeMetadataInfo]:
    """Return node library metadata for this project's custom algos.

    Used by the frontend toolbar to inject custom algo nodes alongside
    built-in nodes.
    """
    await require_project(project_id, current_user.id, session)

    from spectra_sherpa.app.services.dag.node_base import node_registry

    result = await session.execute(
        select(CustomAlgo)
        .where(CustomAlgo.project_id == project_id)
        .order_by(CustomAlgo.name)
    )
    algos = result.scalars().all()

    nodes: list[NodeMetadataInfo] = []
    for algo in algos:
        try:
            meta = node_registry.get_metadata(algo.node_type)
        except KeyError:
            # Not loaded yet (e.g. file missing) — skip
            logger.warning("Custom algo %s not in registry, skipping", algo.node_type)
            continue

        input_ports = None
        if meta.input_ports:
            input_ports = [
                NodePortInfo(
                    name=p.name,
                    type_ref=p.type_ref,
                    required=p.required,
                    label=p.label,
                    description=p.description,
                )
                for p in meta.input_ports
            ]

        output_ports = None
        if meta.output_ports:
            output_ports = [
                NodePortInfo(
                    name=p.name,
                    type_ref=p.type_ref,
                    required=p.required,
                    label=p.label,
                    description=p.description,
                )
                for p in meta.output_ports
            ]

        nodes.append(
            NodeMetadataInfo(
                node_type=meta.node_type,
                category=meta.category,
                label=meta.label,
                description=meta.description,
                parameters=[],
                input_types=meta.input_types,
                output_type=meta.output_type,
                input_ports=input_ports,
                output_ports=output_ports,
                diagnostics=meta.diagnostics,
            )
        )

    return nodes


# ── Create ──────────────────────────────────────────────────────────


@router.post("", response_model=CustomAlgoDetail, status_code=201)
async def create_custom_algo(
    project_id: int,
    payload: CustomAlgoCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CustomAlgoDetail:
    """Create a new custom algo in the project."""
    _check_custom_code_allowed()
    await require_project(project_id, current_user.id, session)

    # Validate
    slug = validate_slug(payload.slug)
    validate_code_syntax(payload.code)

    node_type = make_node_type(project_id, slug)

    # Check uniqueness
    existing = await session.execute(
        select(CustomAlgo).where(CustomAlgo.node_type == node_type)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Custom algo with slug '{slug}' already exists in this project",
        )

    algo = CustomAlgo(
        project_id=project_id,
        user_id=current_user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        code=payload.code,
        mode=payload.mode,
        icon=payload.icon,
        node_type=node_type,
    )
    session.add(algo)

    # Phase 1: DB commit
    await session.commit()
    await session.refresh(algo)

    # Phase 2+3: Write file + reload into registry
    try:
        reload_into_registry(algo)
    except Exception as exc:
        # Compensate: remove DB record
        await session.delete(algo)
        await session.commit()
        logger.exception("Failed to load custom algo %s into registry", algo.node_type)
        raise HTTPException(
            status_code=500,
            detail=f"Custom algo saved but failed to load: {exc}",
        )

    logger.info(
        "Created custom algo '%s' (%s) in project %s",
        algo.name, algo.node_type, project_id,
    )
    return CustomAlgoDetail.model_validate(algo)


# ── Update ──────────────────────────────────────────────────────────


@router.put("/{algo_id}", response_model=CustomAlgoDetail)
async def update_custom_algo(
    project_id: int,
    algo_id: int,
    payload: CustomAlgoUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CustomAlgoDetail:
    """Update a custom algo (code, name, description, mode, icon)."""
    _check_custom_code_allowed()
    await require_project(project_id, current_user.id, session)

    result = await session.execute(
        select(CustomAlgo).where(
            CustomAlgo.id == algo_id,
            CustomAlgo.project_id == project_id,
        )
    )
    algo = result.scalar_one_or_none()
    if algo is None:
        raise HTTPException(status_code=404, detail="Custom algo not found")

    # Validate new code if provided
    update_data = payload.model_dump(exclude_unset=True)
    if "code" in update_data:
        validate_code_syntax(update_data["code"])

    # Snapshot old values for rollback
    old_values = {key: getattr(algo, key) for key in update_data}

    # Apply updates
    for key, value in update_data.items():
        setattr(algo, key, value)

    # Phase 1: DB commit
    await session.commit()
    await session.refresh(algo)

    # Phase 2+3: Rewrite file + reload
    try:
        reload_into_registry(algo)
    except Exception as exc:
        # Compensate: restore old DB values and try to reload the old version
        logger.exception("Failed to reload custom algo %s — rolling back", algo.node_type)
        for key, value in old_values.items():
            setattr(algo, key, value)
        await session.commit()
        await session.refresh(algo)
        try:
            reload_into_registry(algo)
        except Exception:
            logger.exception("Failed to restore old version of %s", algo.node_type)
        raise HTTPException(
            status_code=500,
            detail=f"Custom algo update failed to load — reverted to previous version: {exc}",
        )

    logger.info("Updated custom algo '%s' (%s)", algo.name, algo.node_type)
    return CustomAlgoDetail.model_validate(algo)


# ── Delete ──────────────────────────────────────────────────────────


@router.delete("/{algo_id}", status_code=204, response_class=Response)
async def delete_custom_algo(
    project_id: int,
    algo_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a custom algo and its plugin file."""
    _check_custom_code_allowed()
    await require_project(project_id, current_user.id, session)

    result = await session.execute(
        select(CustomAlgo).where(
            CustomAlgo.id == algo_id,
            CustomAlgo.project_id == project_id,
        )
    )
    algo = result.scalar_one_or_none()
    if algo is None:
        raise HTTPException(status_code=404, detail="Custom algo not found")

    # Unregister + remove file first (so stale registry entries don't linger)
    unregister_and_remove(algo)

    await session.delete(algo)
    await session.commit()

    logger.info(
        "Deleted custom algo '%s' (%s) from project %s",
        algo.name, algo.node_type, project_id,
    )
    return Response(status_code=204)
