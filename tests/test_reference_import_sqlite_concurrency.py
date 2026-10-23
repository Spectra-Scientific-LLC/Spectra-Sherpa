"""Reference imports must not upgrade a stale WAL read snapshot to a writer."""

import sqlite3

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from spectra_sherpa.app.api.v1.routes import experiments as routes
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.db.session import apply_sqlite_pragmas
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.experiments import ReferenceDatasetImportRequest


@pytest.mark.asyncio
async def test_reference_import_serializes_before_its_snapshot_can_be_invalidated(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'reference-race.db'}"
    engine = create_async_engine(url)
    writer = create_async_engine(url, connect_args={"timeout": 0})
    event.listen(engine.sync_engine, "connect", lambda connection, _: apply_sqlite_pragmas(connection))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    competitors = async_sessionmaker(writer, expire_on_commit=False)
    blocked = []
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            user = User(username="reference-race-owner")
            session.add(user)
            await session.flush()
            project = Project(user_id=user.id, name="Import destination")
            session.add(project)
            await session.flush()
            experiment = Experiment(user_id=user.id, project_id=project.id, name="Iris", metadata_path="{}")
            session.add(experiment)
            await session.commit()
            actor, experiment_id = user, experiment.id

        original = routes.import_reference_dataset

        async def import_with_competing_write(session, *args):
            # Establish a real read inside the import savepoint, then attempt a
            # separately connected write. Without BEGIN IMMEDIATE that commit
            # invalidates this snapshot and the real import fails with BUSY.
            await session.scalar(select(func.count()).select_from(Project))
            async with competitors() as other:
                other.add(Project(user_id=actor.id, name="Concurrent unrelated write"))
                try:
                    await other.commit()
                except OperationalError as exc:
                    assert exc.orig.sqlite_errorcode == sqlite3.SQLITE_BUSY
                    blocked.append(True)
                    await other.rollback()
            return await original(session, *args)

        monkeypatch.setattr(routes, "import_reference_dataset", import_with_competing_write)
        async with sessions() as session:
            result = await routes.import_reference_datasets_endpoint(
                experiment_id,
                ReferenceDatasetImportRequest(datasets=[{"source": "sklearn", "name": "iris"}]),
                session,
                actor,
            )
            assert result.imported == 1
            assert await session.scalar(select(func.count()).select_from(ExperimentFile)) == 1
        assert blocked == [True]
        # The lock is not leaked: the same independent writer succeeds after
        # the import transaction finishes, without a retry in product code.
        async with competitors() as other:
            other.add(Project(user_id=actor.id, name="Write after import"))
            await other.commit()
    finally:
        await writer.dispose()
        await engine.dispose()
