from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_specimen import ExperimentSpecimen
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.acquisition_plans import (
    AcquisitionPlanRevisionConflict,
    read_acquisition_plan,
    replace_acquisition_plan,
)


async def _create_experiment(client: AsyncClient, name: str = "Plate study") -> int:
    response = await client.post("/api/v1/experiments", json={"name": name, "metadata": {}})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_acquisition_plan_round_trip_is_canonical_and_dataset_scoped(client: AsyncClient):
    first = await _create_experiment(client, "First")
    second = await _create_experiment(client, "Second")
    initial = (await client.get(f"/api/v1/experiments/{first}/acquisition-plan")).json()

    saved = await client.put(
        f"/api/v1/experiments/{first}/acquisition-plan",
        json={
            "plate_format_id": "plate-96",
            "expected_revision": initial["revision"],
            "wells": [{"well_position": "B2"}, {"well_position": "A1"}],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["schema_version"] == "spectrasherpa-acquisition-plan/3"
    assert saved.json()["plate_format_label"] == "96-well plate"
    assert saved.json()["capacity"] == 96
    assert saved.json()["wells"] == [
        {
            "well_position": "A01",
            "planned_sample_label": None,
            "sample_id": None,
            "mixture_id": None,
            "factor_values": {},
        },
        {
            "well_position": "B02",
            "planned_sample_label": None,
            "sample_id": None,
            "mixture_id": None,
            "factor_values": {},
        },
    ]
    assert len(saved.json()["revision"]) == 64
    assert (await client.get(f"/api/v1/experiments/{first}/acquisition-plan")).json() == saved.json()
    assert (await client.get(f"/api/v1/experiments/{second}/acquisition-plan")).json()["wells"] == []


@pytest.mark.asyncio
async def test_acquisition_plan_rejects_duplicate_and_out_of_format_wells(client: AsyncClient):
    experiment_id = await _create_experiment(client)
    revision = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()["revision"]

    duplicate = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": revision,
            "wells": [{"well_position": "A1"}, {"well_position": "A01"}],
        },
    )
    outside = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={"expected_revision": revision, "wells": [{"well_position": "A13"}]},
    )

    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Acquisition plan assigns A01 more than once"
    assert outside.status_code == 400
    assert "outside 96-well plate" in outside.json()["detail"]


@pytest.mark.asyncio
async def test_acquisition_plan_rejects_malformed_specimen_uid(client: AsyncClient):
    experiment_id = await _create_experiment(client)
    revision = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()["revision"]

    response = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": revision,
            "samples": [{"sample_id": "oil", "source_specimen_uid": "sample:21", "name": "Oil"}],
        },
    )

    assert response.status_code == 422
    assert "source_specimen_uid" in response.text


@pytest.mark.asyncio
async def test_acquisition_plan_requires_experiment_ownership(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/experiments/999/acquisition-plan")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_acquisition_plan_preserves_retained_sample_labels(
    client: AsyncClient,
):
    experiment_id = await _create_experiment(client)
    initial = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()
    first = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": initial["revision"],
            "wells": [
                {"well_position": "A01", "planned_sample_label": "standard-1"},
                {"well_position": "A02"},
            ],
        },
    )
    response = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={"expected_revision": first.json()["revision"], "plate_format_id": "plate-96"},
    )

    assert response.status_code == 200
    assert [(well["well_position"], well["planned_sample_label"]) for well in response.json()["wells"]] == [
        ("A01", "standard-1"),
        ("A02", None),
    ]


@pytest.mark.asyncio
async def test_acquisition_plan_can_save_an_unchanged_well(client: AsyncClient):
    experiment_id = await _create_experiment(client)
    initial = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()
    first = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={"expected_revision": initial["revision"], "wells": [{"well_position": "A01"}]},
    )

    unchanged = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={"expected_revision": first.json()["revision"], "wells": [{"well_position": "A01"}]},
    )

    assert first.status_code == 200
    assert unchanged.status_code == 200
    assert unchanged.json()["wells"][0]["well_position"] == "A01"


@pytest.mark.asyncio
async def test_acquisition_plan_rejects_stale_revision_without_losing_first_save(
    client: AsyncClient,
):
    experiment_id = await _create_experiment(client)
    initial = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()

    first = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": initial["revision"],
            "wells": [{"well_position": "A01"}],
        },
    )
    stale = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": initial["revision"],
            "wells": [{"well_position": "B01"}],
        },
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert "Reload the plan" in stale.json()["detail"]
    current = await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")
    assert current.json()["wells"][0]["well_position"] == "A01"


@pytest.mark.asyncio
async def test_acquisition_plan_serializes_concurrent_sqlite_writers(tmp_path):
    database = tmp_path / "acquisition-plan-cas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        user = User(username="concurrent-planner")
        session.add(user)
        await session.flush()
        experiment = Experiment(
            user_id=user.id,
            name="Concurrent plate",
            metadata_path="metadata.json",
        )
        session.add(experiment)
        await session.commit()
        experiment_id = experiment.id
        initial_revision = (await read_acquisition_plan(session, experiment_id))["revision"]

    async def save(well: str):
        async with sessions() as session:
            return await replace_acquisition_plan(
                session,
                experiment_id,
                [well],
                expected_revision=initial_revision,
            )

    outcomes = await asyncio.gather(save("A01"), save("B01"), return_exceptions=True)
    assert sum(isinstance(item, AcquisitionPlanRevisionConflict) for item in outcomes) == 1
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    async with sessions() as session:
        current = await read_acquisition_plan(session, experiment_id)
    assert [well["well_position"] for well in current["wells"]] in (["A01"], ["B01"])
    await engine.dispose()


@pytest.mark.asyncio
async def test_acquisition_plan_snapshot_never_mutates_or_tracks_specimen_catalog(tmp_path):
    database = tmp_path / "acquisition-plan-specimen-boundary.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        user = User(username="specimen-owner")
        session.add(user)
        await session.flush()
        experiment = Experiment(user_id=user.id, name="Plate", metadata_path="metadata.json")
        session.add(experiment)
        await session.flush()
        specimen = ExperimentSpecimen(
            experiment_id=experiment.id,
            specimen_key="oil",
            name="Catalog oil",
            specimen_type="material",
            brand="Supplier A",
            cas_number="67-64-1",
            active=True,
            notes="catalog note",
        )
        session.add(specimen)
        await session.commit()

        initial = await read_acquisition_plan(session, experiment.id)
        saved = await replace_acquisition_plan(
            session,
            experiment.id,
            {
                "samples": [
                    {
                        "sample_id": "oil",
                        "source_specimen_uid": specimen.specimen_uid,
                        "name": "Frozen plan name",
                        "sample_type": "material",
                        "notes": "frozen plan note",
                    }
                ]
            },
            expected_revision=str(initial["revision"]),
        )
        await session.refresh(specimen)
        assert (specimen.name, specimen.brand, specimen.cas_number, specimen.active, specimen.notes) == (
            "Catalog oil",
            "Supplier A",
            "67-64-1",
            True,
            "catalog note",
        )

        specimen.name = "Edited catalog oil"
        specimen.brand = "Supplier B"
        specimen.notes = "new catalog note"
        await session.commit()

        current = await read_acquisition_plan(session, experiment.id)
        assert current["samples"] == saved["samples"]
        assert current["samples"] == [
            {
                "sample_id": "oil",
                "source_specimen_uid": specimen.specimen_uid,
                "name": "Frozen plan name",
                "sample_type": "material",
                "notes": "frozen plan note",
            }
        ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_acquisition_plan_round_trip_preserves_scientific_intent(client: AsyncClient):
    experiment_id = await _create_experiment(client)
    initial = (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json()
    response = await client.put(
        f"/api/v1/experiments/{experiment_id}/acquisition-plan",
        json={
            "expected_revision": initial["revision"],
            "samples": [{"sample_id": "oil", "name": "Oil", "sample_type": "material"}],
            "mixtures": [
                {
                    "mixture_id": "mix-1",
                    "name": "Standard",
                    "basis": "volume",
                    "components": [{"sample_id": "oil", "amount": 1.5, "unit": "mL"}],
                }
            ],
            "factors": [
                {
                    "factor_id": "temperature",
                    "name": "Temperature",
                    "scope": "method",
                    "factor_type": "numeric",
                    "unit": "C",
                    "levels": [20, 30],
                }
            ],
            "wells": [{"well_position": "A1", "mixture_id": "mix-1"}],
            "acquisition_order": [
                {
                    "sequence_order": 0,
                    "factor_id": "temperature",
                    "level_value": "20",
                }
            ],
            "matching": {
                "rules": {"filename_pattern": "_(\\d+)"},
                "matches": [{"sequence_order": 0, "filename": "run_1.csv", "well_position": "A1"}],
            },
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["samples"][0]["sample_id"] == "oil"
    assert saved["mixtures"][0]["components"] == [{"sample_id": "oil", "amount": 1.5, "unit": "mL"}]
    assert saved["factors"][0]["levels"] == [20, 30]
    assert saved["wells"][0]["mixture_id"] == "mix-1"
    assert saved["acquisition_order"][0]["factor_id"] == "temperature"
    assert saved["matching"]["matches"][0]["well_position"] == "A01"
    assert (await client.get(f"/api/v1/experiments/{experiment_id}/acquisition-plan")).json() == saved


@pytest.mark.asyncio
async def test_user_can_read_and_update_default_plate_format_and_list_presets(client: AsyncClient):
    initial = await client.get("/api/v1/acquisition-preferences")
    updated = await client.put("/api/v1/acquisition-preferences", json={"default_plate_format_id": "plate-96"})
    presets = await client.get("/api/v1/acquisition-preferences/presets")

    assert initial.status_code == 200
    assert initial.json() == {"default_plate_format_id": "plate-96"}
    assert updated.status_code == 200
    assert updated.json() == initial.json()
    assert presets.status_code == 200
    assert presets.json() == []
