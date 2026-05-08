"""
API endpoints for workflow organization (tags and folders).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow_folder import WorkflowFolder
from spectra_sherpa.app.models.workflow_tag import WorkflowTag
from spectra_sherpa.app.schemas.workflows import (
    WorkflowFolderCreate,
    WorkflowFolderOut,
    WorkflowFolderUpdate,
    WorkflowTagCreate,
    WorkflowTagOut,
    WorkflowTagUpdate,
)

router = APIRouter()


# ===== Tag Endpoints =====


@router.get("/tags", response_model=list[WorkflowTagOut])
async def list_tags(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowTagOut]:
    """List all tags for the current user."""
    user_id = current_user.id

    query = select(WorkflowTag).where(WorkflowTag.user_id == user_id).order_by(WorkflowTag.name)
    result = await session.execute(query)
    tags = result.scalars().all()

    return [WorkflowTagOut.model_validate(tag) for tag in tags]


@router.post("/tags", response_model=WorkflowTagOut, status_code=201)
async def create_tag(
    payload: WorkflowTagCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowTagOut:
    """Create a new tag."""
    user_id = current_user.id

    # Check if tag with same name already exists for this user
    existing_query = select(WorkflowTag).where(WorkflowTag.user_id == user_id).where(WorkflowTag.name == payload.name)
    existing_result = await session.execute(existing_query)
    existing_tag = existing_result.scalar_one_or_none()

    if existing_tag:
        raise HTTPException(status_code=400, detail=f"Tag with name '{payload.name}' already exists")

    tag = WorkflowTag(
        user_id=user_id,
        name=payload.name,
        color=payload.color,
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    return WorkflowTagOut.model_validate(tag)


@router.get("/tags/{tag_id}", response_model=WorkflowTagOut)
async def get_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowTagOut:
    """Get a specific tag by ID."""
    user_id = current_user.id

    query = select(WorkflowTag).where(WorkflowTag.id == tag_id).where(WorkflowTag.user_id == user_id)
    result = await session.execute(query)
    tag = result.scalar_one_or_none()

    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    return WorkflowTagOut.model_validate(tag)


@router.put("/tags/{tag_id}", response_model=WorkflowTagOut)
async def update_tag(
    tag_id: int,
    payload: WorkflowTagUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowTagOut:
    """Update a tag."""
    user_id = current_user.id

    query = select(WorkflowTag).where(WorkflowTag.id == tag_id).where(WorkflowTag.user_id == user_id)
    result = await session.execute(query)
    tag = result.scalar_one_or_none()

    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Check if new name conflicts with existing tag
    if payload.name and payload.name != tag.name:
        existing_query = (
            select(WorkflowTag).where(WorkflowTag.user_id == user_id).where(WorkflowTag.name == payload.name)
        )
        existing_result = await session.execute(existing_query)
        existing_tag = existing_result.scalar_one_or_none()

        if existing_tag:
            raise HTTPException(status_code=400, detail=f"Tag with name '{payload.name}' already exists")

    if payload.name is not None:
        tag.name = payload.name
    if payload.color is not None:
        tag.color = payload.color

    await session.commit()
    await session.refresh(tag)

    return WorkflowTagOut.model_validate(tag)


from fastapi import Response


@router.delete("/tags/{tag_id}", status_code=204, response_class=Response)
async def delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a tag."""
    user_id = current_user.id

    query = select(WorkflowTag).where(WorkflowTag.id == tag_id).where(WorkflowTag.user_id == user_id)
    result = await session.execute(query)
    tag = result.scalar_one_or_none()

    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    await session.delete(tag)
    await session.commit()


# ===== Folder Endpoints =====


@router.get("/folders", response_model=list[WorkflowFolderOut])
async def list_folders(
    parent_id: int | None = Query(None, description="Filter by parent folder"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowFolderOut]:
    """List all folders for the current user, optionally filtered by parent."""
    user_id = current_user.id

    query = select(WorkflowFolder).where(WorkflowFolder.user_id == user_id)

    if parent_id is not None:
        query = query.where(WorkflowFolder.parent_id == parent_id)

    query = query.order_by(WorkflowFolder.name)
    result = await session.execute(query)
    folders = result.scalars().all()

    return [WorkflowFolderOut.model_validate(folder) for folder in folders]


@router.post("/folders", response_model=WorkflowFolderOut, status_code=201)
async def create_folder(
    payload: WorkflowFolderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowFolderOut:
    """Create a new folder."""
    user_id = current_user.id

    # Verify parent folder exists and belongs to user if parent_id is provided
    if payload.parent_id:
        parent_query = (
            select(WorkflowFolder)
            .where(WorkflowFolder.id == payload.parent_id)
            .where(WorkflowFolder.user_id == user_id)
        )
        parent_result = await session.execute(parent_query)
        parent_folder = parent_result.scalar_one_or_none()

        if parent_folder is None:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    folder = WorkflowFolder(
        user_id=user_id,
        name=payload.name,
        parent_id=payload.parent_id,
    )
    session.add(folder)
    await session.commit()
    await session.refresh(folder)

    return WorkflowFolderOut.model_validate(folder)


@router.get("/folders/{folder_id}", response_model=WorkflowFolderOut)
async def get_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowFolderOut:
    """Get a specific folder by ID."""
    user_id = current_user.id

    query = select(WorkflowFolder).where(WorkflowFolder.id == folder_id).where(WorkflowFolder.user_id == user_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()

    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    return WorkflowFolderOut.model_validate(folder)


@router.put("/folders/{folder_id}", response_model=WorkflowFolderOut)
async def update_folder(
    folder_id: int,
    payload: WorkflowFolderUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowFolderOut:
    """Update a folder."""
    user_id = current_user.id

    query = select(WorkflowFolder).where(WorkflowFolder.id == folder_id).where(WorkflowFolder.user_id == user_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()

    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Verify new parent folder exists if parent_id is being changed
    if payload.parent_id is not None:
        # Prevent setting folder as its own parent
        if payload.parent_id == folder_id:
            raise HTTPException(status_code=400, detail="Folder cannot be its own parent")

        # Verify parent folder exists and belongs to user
        parent_query = (
            select(WorkflowFolder)
            .where(WorkflowFolder.id == payload.parent_id)
            .where(WorkflowFolder.user_id == user_id)
        )
        parent_result = await session.execute(parent_query)
        parent_folder = parent_result.scalar_one_or_none()

        if parent_folder is None:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    if payload.name is not None:
        folder.name = payload.name
    if payload.parent_id is not None:
        folder.parent_id = payload.parent_id

    await session.commit()
    await session.refresh(folder)

    return WorkflowFolderOut.model_validate(folder)


@router.delete("/folders/{folder_id}", status_code=204, response_class=Response)
async def delete_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a folder.

    Workflows in the folder will have their folder_id set to NULL.
    Subfolders will be deleted (cascade).
    """
    user_id = current_user.id

    query = select(WorkflowFolder).where(WorkflowFolder.id == folder_id).where(WorkflowFolder.user_id == user_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()

    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    await session.delete(folder)
    await session.commit()
