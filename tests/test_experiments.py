"""Tests for experiment endpoints"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_list_experiments_empty(client: AsyncClient):
    """Test listing experiments when none exist"""
    response = await client.get("/api/v1/experiments")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_experiment(client: AsyncClient, test_user: User):
    """Test creating a new experiment"""
    payload = {
        "name": "Test Experiment",
        "description": "A test experiment",
        "metadata": {"key": "value"},
    }

    response = await client.post("/api/v1/experiments", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Test Experiment"
    assert data["description"] == "A test experiment"
    assert data["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_get_experiment(client: AsyncClient, test_user: User):
    """Test getting a specific experiment"""
    # Create an experiment first
    create_payload = {
        "name": "Test Experiment",
        "description": "A test experiment",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Get the experiment
    response = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == experiment_id
    assert data["name"] == "Test Experiment"


@pytest.mark.asyncio
async def test_get_nonexistent_experiment(client: AsyncClient):
    """Test getting a nonexistent experiment"""
    response = await client.get("/api/v1/experiments/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_experiment(client: AsyncClient, test_user: User):
    """Test updating an experiment"""
    # Create an experiment first
    create_payload = {
        "name": "Original Name",
        "description": "Original description",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Update the experiment
    update_payload = {
        "name": "Updated Name",
        "description": "Updated description",
    }

    response = await client.put(
        f"/api/v1/experiments/{experiment_id}", json=update_payload
    )
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


@pytest.mark.asyncio
async def test_delete_experiment(client: AsyncClient, test_user: User):
    """Test deleting an experiment"""
    # Create an experiment first
    create_payload = {
        "name": "To Delete",
        "description": "Will be deleted",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Delete the experiment
    response = await client.delete(f"/api/v1/experiments/{experiment_id}")
    assert response.status_code == 200

    # Verify it's gone
    get_response = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert get_response.status_code == 404
