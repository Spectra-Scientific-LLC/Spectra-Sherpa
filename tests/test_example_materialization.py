from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core import config as config_mod
from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dag.nodes.data.source import DataSourceNode
from spectra_sherpa.app.services.experiments import import_reference_dataset


@pytest.mark.asyncio
async def test_import_reference_dataset_recurses_scp_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    source_root = tmp_path / "scp-source" / "ramandata"
    (source_root / "wire").mkdir(parents=True)
    (source_root / "wire" / "sample_a.spc").write_text("a", encoding="ascii")
    (source_root / "wire" / "nested").mkdir()
    (source_root / "wire" / "nested" / "sample_b.txt").write_text("b", encoding="ascii")
    (source_root / "_hidden").mkdir()
    (source_root / "_hidden" / "skip.me").write_text("hidden", encoding="ascii")

    data_dir = tmp_path / "app-data"
    monkeypatch.setattr(
        "spectra_sherpa.app.services.experiments.settings",
        SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.experiments._resolve_scp_path",
        lambda name: source_root,
    )

    experiment = Experiment(
        user_id=test_user.id,
        name="Recursive SCP Import",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()

    files = await import_reference_dataset(test_session, experiment.id, "spectrochempy", "ramandata")

    imported_paths = sorted(file.file_path for file in files)
    assert imported_paths == [
        "raw/scp_ramandata/wire/nested/sample_b.txt",
        "raw/scp_ramandata/wire/sample_a.spc",
    ]
    for rel_path in imported_paths:
        assert (data_dir / "experiments" / f"exp_{experiment.id:03d}" / rel_path).exists()


@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy is required for experiment-backed multi-file loading")
@pytest.mark.asyncio
async def test_data_source_experiment_loads_all_materialized_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    data_dir = tmp_path / "app-data"
    monkeypatch.setattr(config_mod, "settings", SimpleNamespace(data_dir=data_dir))

    @asynccontextmanager
    async def override_async_session():
        yield test_session

    monkeypatch.setattr(
        "spectra_sherpa.app.db.session.async_session",
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

    node = DataSourceNode(
        "src_1",
        {
            "source": "experiment",
            "experiment_id": experiment.id,
            "stage": "raw",
        },
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
