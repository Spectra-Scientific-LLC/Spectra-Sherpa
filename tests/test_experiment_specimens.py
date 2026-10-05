from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_specimen import ExperimentSpecimen
from spectra_sherpa.app.models.user import User


async def _create_experiment(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/v1/experiments", json={"name": name, "metadata": {}})
    assert response.status_code == 201
    return int(response.json()["id"])


@pytest.mark.asyncio
async def test_experiment_specimen_catalog_has_stable_identity_and_unique_keys(client: AsyncClient):
    experiment_id = await _create_experiment(client, "Specimen study")
    created = await client.post(
        f"/api/v1/experiments/{experiment_id}/specimens",
        json={
            "specimen_key": "  oil-1  ",
            "name": "Lavender oil",
            "specimen_type": "material",
            "brand": "Supplier A",
            "cas_number": "8000-28-0",
            "notes": "retained vial",
        },
    )

    assert created.status_code == 201
    specimen = created.json()
    assert str(uuid.UUID(specimen["specimen_uid"])) == specimen["specimen_uid"]
    assert specimen["specimen_key"] == "oil-1"
    assert specimen["experiment_id"] == experiment_id

    duplicate = await client.post(
        f"/api/v1/experiments/{experiment_id}/specimens",
        json={"specimen_key": "oil-1", "name": "Duplicate"},
    )
    assert duplicate.status_code == 409

    updated = await client.patch(
        f"/api/v1/experiments/{experiment_id}/specimens/{specimen['specimen_uid']}",
        json={"brand": "Supplier B", "active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["specimen_uid"] == specimen["specimen_uid"]
    assert updated.json()["brand"] == "Supplier B"
    assert updated.json()["active"] is False

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/specimens")
    assert listed.status_code == 200
    assert listed.json() == [updated.json()]


@pytest.mark.asyncio
async def test_experiment_specimen_routes_hide_unowned_scopes(auth_client: AsyncClient, test_session: AsyncSession):
    other = User(username="other-specimen-owner")
    test_session.add(other)
    await test_session.flush()
    experiment = Experiment(user_id=other.id, name="Private", metadata_path="private.json")
    test_session.add(experiment)
    await test_session.flush()
    specimen = ExperimentSpecimen(
        experiment_id=experiment.id,
        specimen_key="private-oil",
        name="Private oil",
    )
    test_session.add(specimen)
    await test_session.flush()
    experiment_id = experiment.id
    specimen_uid = specimen.specimen_uid

    listed = await auth_client.get(f"/api/v1/experiments/{experiment_id}/specimens")
    fetched = await auth_client.get(f"/api/v1/experiments/{experiment_id}/specimens/{specimen_uid}")
    updated = await auth_client.patch(
        f"/api/v1/experiments/{experiment_id}/specimens/{specimen_uid}",
        json={"name": "Stolen"},
    )

    assert listed.status_code == 404
    assert fetched.status_code == 404
    assert updated.status_code == 404


@pytest.mark.asyncio
async def test_acquisition_plan_rejects_cross_experiment_specimen_link(client: AsyncClient):
    source_experiment_id = await _create_experiment(client, "Source")
    target_experiment_id = await _create_experiment(client, "Target")
    created = await client.post(
        f"/api/v1/experiments/{source_experiment_id}/specimens",
        json={"specimen_key": "oil", "name": "Oil"},
    )
    specimen_uid = created.json()["specimen_uid"]
    target_plan = (await client.get(f"/api/v1/experiments/{target_experiment_id}/acquisition-plan")).json()

    response = await client.put(
        f"/api/v1/experiments/{target_experiment_id}/acquisition-plan",
        json={
            "expected_revision": target_plan["revision"],
            "samples": [
                {
                    "sample_id": "oil",
                    "source_specimen_uid": specimen_uid,
                    "name": "Frozen oil",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "do not belong to this experiment" in response.json()["detail"]
