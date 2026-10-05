from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core import config as config_mod
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader
from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver


@pytest.mark.asyncio
async def test_experiment_dataset_reader_loads_all_materialized_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    data_dir = tmp_path / "app-data"
    monkeypatch.setattr(config_mod, "settings", SimpleNamespace(data_dir=data_dir))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.settings",
        SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.experiments.settings",
        SimpleNamespace(data_dir=data_dir),
    )

    @asynccontextmanager
    async def override_async_session():
        yield test_session

    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.async_session",
        override_async_session,
    )

    experiment = Experiment(
        user_id=test_user.id,
        name="Materialized Example",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()

    exp_dir = data_dir / "experiments" / f"exp_{experiment.id:03d}" / "raw"
    exp_dir.mkdir(parents=True, exist_ok=True)

    file_a = exp_dir / "part_a.csv"
    file_b = exp_dir / "part_b.csv"
    file_a.write_text(
        "sample_id,1000.0,1001.0,Moisture,Oil\n" "a1,1.0,1.1,10.0,4.0\n" "a2,2.0,2.1,11.0,5.0\n",
        encoding="ascii",
    )
    file_b.write_text(
        "sample_id,1000.0,1001.0,Moisture,Oil\n" "b1,3.0,3.1,12.0,6.0\n" "b2,4.0,4.1,13.0,7.0\n",
        encoding="ascii",
    )

    t0 = datetime.now(UTC)
    test_session.add_all(
        [
            ExperimentFile(
                experiment_id=experiment.id,
                file_path="raw/part_a.csv",
                file_type="csv",
                stage="raw",
                file_size_bytes=file_a.stat().st_size,
                created_at=t0,
            ),
            ExperimentFile(
                experiment_id=experiment.id,
                file_path="raw/part_b.csv",
                file_type="csv",
                stage="raw",
                file_size_bytes=file_b.stat().st_size,
                created_at=t0 + timedelta(seconds=1),
            ),
        ]
    )
    await test_session.commit()

    node = ExperimentDatasetReader(
        "src_1",
        {
            "dataset_id": experiment.id,
        },
        source_resolver=ApplicationDatasetSourceResolver(),
    )

    result = await node.execute()

    dataset = result["default"]
    assert dataset.data.shape == (4, 2)
    assert dataset.target is not None
    np.testing.assert_allclose(
        dataset.target,
        np.array(
            [
                [10.0, 4.0],
                [11.0, 5.0],
                [12.0, 6.0],
                [13.0, 7.0],
            ]
        ),
    )
    assert dataset.target_context is not None
    assert dataset.target_context.target_names == ["Moisture", "Oil"]
