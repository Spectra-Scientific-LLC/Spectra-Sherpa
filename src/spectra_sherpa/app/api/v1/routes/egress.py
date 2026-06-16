"""
Data Egress Settings API

Allows users to configure what data can be shared with external services
(SpectraSherpa, LLM providers, exports, NIST).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.data_egress import (
    DataEgressPermission as DataEgressPermissionModel,
)
from spectra_sherpa.app.models.data_egress import (
    DataType,
    EgressDestination,
)
from spectra_sherpa.app.models.data_egress import (
    UserEgressDefaults as UserEgressDefaultsModel,
)
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.data_egress import (
    BulkPermissionUpdate,
    DataEgressPermission,
    DataEgressPermissionCreate,
    DataEgressPermissionUpdate,
    EgressSettingsSummary,
    UserEgressDefaults,
    UserEgressDefaultsUpdate,
)

router = APIRouter(prefix="/egress", tags=["egress"], dependencies=[Depends(get_current_user)])


# ============================================================================
# Egress Defaults
# ============================================================================


@router.get("/defaults", response_model=Optional[UserEgressDefaults])
async def get_egress_defaults(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's default egress settings"""
    result = await session.execute(
        select(UserEgressDefaultsModel).where(UserEgressDefaultsModel.user_id == current_user.id)
    )
    defaults = result.scalar_one_or_none()
    return defaults


@router.put("/defaults", response_model=UserEgressDefaults)
async def update_egress_defaults(
    defaults_update: UserEgressDefaultsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's default egress settings (creates if not exists)"""
    from spectra_sherpa.app.core.security import (
        llm_egress_defaults_enabled,
        llm_egress_defaults_forced,
    )

    force_llm_defaults = llm_egress_defaults_forced()
    enable_llm_defaults = llm_egress_defaults_enabled()
    result = await session.execute(
        select(UserEgressDefaultsModel).where(UserEgressDefaultsModel.user_id == current_user.id)
    )
    defaults = result.scalar_one_or_none()

    if defaults is None:
        if force_llm_defaults:
            allow_llm_chat = True
            allow_llm_context = True
        else:
            allow_llm_chat = (
                defaults_update.allow_llm_chat if defaults_update.allow_llm_chat is not None else enable_llm_defaults
            )
            allow_llm_context = (
                defaults_update.allow_llm_context
                if defaults_update.allow_llm_context is not None
                else enable_llm_defaults
            )
        if not allow_llm_chat:
            allow_llm_context = False
        defaults = UserEgressDefaultsModel(
            user_id=current_user.id,
            allow_spectrasherpa_sync=defaults_update.allow_spectrasherpa_sync or False,
            allow_llm_chat=allow_llm_chat,
            allow_llm_context=allow_llm_context,
            allow_export=defaults_update.allow_export if defaults_update.allow_export is not None else False,
            allow_nist_queries=(
                defaults_update.allow_nist_queries if defaults_update.allow_nist_queries is not None else False
            ),
            allow_hitran_queries=(
                defaults_update.allow_hitran_queries if defaults_update.allow_hitran_queries is not None else False
            ),
        )
        session.add(defaults)
    else:
        # Update existing
        if defaults_update.allow_spectrasherpa_sync is not None:
            defaults.allow_spectrasherpa_sync = defaults_update.allow_spectrasherpa_sync
        if force_llm_defaults:
            defaults.allow_llm_chat = True
            defaults.allow_llm_context = True
        else:
            if defaults_update.allow_llm_chat is not None:
                defaults.allow_llm_chat = defaults_update.allow_llm_chat
            if defaults_update.allow_llm_context is not None:
                defaults.allow_llm_context = defaults_update.allow_llm_context
            if not defaults.allow_llm_chat:
                defaults.allow_llm_context = False
        if defaults_update.allow_export is not None:
            defaults.allow_export = defaults_update.allow_export
        if defaults_update.allow_nist_queries is not None:
            defaults.allow_nist_queries = defaults_update.allow_nist_queries
        if defaults_update.allow_hitran_queries is not None:
            defaults.allow_hitran_queries = defaults_update.allow_hitran_queries

    await session.commit()
    await session.refresh(defaults)
    return defaults


# ============================================================================
# Per-Data-Type Permissions
# ============================================================================


@router.get("/permissions", response_model=list[DataEgressPermission])
async def list_permissions(
    data_type: Optional[str] = None,
    destination: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List the current user's egress permissions with optional filtering"""
    query = select(DataEgressPermissionModel).where(DataEgressPermissionModel.user_id == current_user.id)

    if data_type:
        query = query.where(DataEgressPermissionModel.data_type == data_type)
    if destination:
        query = query.where(DataEgressPermissionModel.destination == destination)

    result = await session.execute(query)
    return result.scalars().all()


@router.post("/permissions", response_model=DataEgressPermission, status_code=status.HTTP_201_CREATED)
async def create_permission(
    permission: DataEgressPermissionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new egress permission (or update if exists)"""
    # Validate data_type and destination
    if permission.data_type not in DataType.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data_type. Must be one of: {', '.join(DataType.ALL)}",
        )
    if permission.destination not in EgressDestination.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid destination. Must be one of: {', '.join(EgressDestination.ALL)}",
        )

    # Check if exists
    result = await session.execute(
        select(DataEgressPermissionModel).where(
            DataEgressPermissionModel.user_id == current_user.id,
            DataEgressPermissionModel.data_type == permission.data_type,
            DataEgressPermissionModel.destination == permission.destination,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing
        existing.allowed = permission.allowed
        await session.commit()
        await session.refresh(existing)
        return existing

    # Create new
    db_permission = DataEgressPermissionModel(
        user_id=current_user.id,
        data_type=permission.data_type,
        destination=permission.destination,
        allowed=permission.allowed,
    )
    session.add(db_permission)
    await session.commit()
    await session.refresh(db_permission)
    return db_permission


@router.put("/permissions/{permission_id}", response_model=DataEgressPermission)
async def update_permission(
    permission_id: int,
    permission_update: DataEgressPermissionUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update an existing permission"""
    result = await session.execute(
        select(DataEgressPermissionModel).where(
            DataEgressPermissionModel.id == permission_id,
            DataEgressPermissionModel.user_id == current_user.id,
        )
    )
    permission = result.scalar_one_or_none()

    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    permission.allowed = permission_update.allowed
    await session.commit()
    await session.refresh(permission)
    return permission


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a permission (reverts to default behavior)"""
    result = await session.execute(
        select(DataEgressPermissionModel).where(
            DataEgressPermissionModel.id == permission_id,
            DataEgressPermissionModel.user_id == current_user.id,
        )
    )
    permission = result.scalar_one_or_none()

    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    await session.delete(permission)
    await session.commit()


@router.post("/permissions/bulk", response_model=list[DataEgressPermission])
async def bulk_update_permissions(
    bulk: BulkPermissionUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Bulk create/update permissions"""
    results = []

    for perm in bulk.permissions:
        # Validate
        if perm.data_type not in DataType.ALL:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid data_type: {perm.data_type}")
        if perm.destination not in EgressDestination.ALL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid destination: {perm.destination}"
            )

        # Check if exists
        result = await session.execute(
            select(DataEgressPermissionModel).where(
                DataEgressPermissionModel.user_id == current_user.id,
                DataEgressPermissionModel.data_type == perm.data_type,
                DataEgressPermissionModel.destination == perm.destination,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.allowed = perm.allowed
            results.append(existing)
        else:
            new_perm = DataEgressPermissionModel(
                user_id=current_user.id,
                data_type=perm.data_type,
                destination=perm.destination,
                allowed=perm.allowed,
            )
            session.add(new_perm)
            results.append(new_perm)

    await session.commit()
    for r in results:
        await session.refresh(r)

    return results


# ============================================================================
# Summary
# ============================================================================


@router.get("/summary", response_model=EgressSettingsSummary)
async def get_egress_summary(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a complete summary of the user's egress settings"""
    # Get defaults
    defaults_result = await session.execute(
        select(UserEgressDefaultsModel).where(UserEgressDefaultsModel.user_id == current_user.id)
    )
    defaults = defaults_result.scalar_one_or_none()

    # Get all permissions
    perms_result = await session.execute(
        select(DataEgressPermissionModel).where(DataEgressPermissionModel.user_id == current_user.id)
    )
    permissions = perms_result.scalars().all()

    return EgressSettingsSummary(defaults=defaults, permissions=list(permissions))


# ============================================================================
# Utility Endpoints
# ============================================================================


@router.get("/data-types", response_model=list[str])
async def list_data_types():
    """List all valid data types"""
    return DataType.ALL


@router.get("/destinations", response_model=list[str])
async def list_destinations():
    """List all valid destinations"""
    return EgressDestination.ALL
