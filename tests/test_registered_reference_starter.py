"""Registered reference starters retain the projection identity used by execution."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.v1.routes import workflow_templates as template_routes
from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.experiments import experiment_dir


@pytest.mark.asyncio
async def test_registered_multiasset_target_authority_uses_exact_projection_asset(
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa import io as scientific_io

    experiment = Experiment(user_id=test_user.id, name="Registered Corn", metadata_path="{}")
    test_session.add(experiment)
    await test_session.flush()
    source = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/corn.mat",
        file_type="mat",
        stage="raw",
        file_size_bytes=16,
    )
    test_session.add(source)
    await test_session.commit()
    path = experiment_dir(experiment.id) / source.file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"multi-asset corn source")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    reference = {"projection_id": "public-corn-m5-moisture-v1", "member_sha256": digest}
    selected: list[str] = []
    projected = SherpaDataset(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        feature_axis=FeatureAxis(labels=["a", "b"]),
        data_role="X_features",
    )

    def materialize(_path: Path, projection_id: str) -> SimpleNamespace:
        selected.append(projection_id)
        return SimpleNamespace(dataset=projected, portable_reference=reference)

    monkeypatch.setattr(scientific_io, "ingest", lambda _path: pytest.fail("must use registered projection"))
    monkeypatch.setattr(template_routes, "materialize_reference_member", materialize)
    monkeypatch.setattr(template_routes, "read_registered_reference_sidecar", lambda _path: reference)

    authority, asset_id = await template_routes._issue_file_target_authority(
        test_session,
        DataBindingSpec(source="experiment", experiment_id=experiment.id, file_id=source.id),
        selected_target="Moisture",
        target_type="continuous",
    )

    assert selected == ["public-corn-m5-moisture-v1"]
    assert asset_id == "public-corn-m5-moisture-v1"
    assert authority.column == "Moisture"
    assert authority.source_digest == digest
    admitted, profile = await template_routes._validate_binding(
        test_session,
        test_user.id,
        DataBindingSpec(source="experiment", experiment_id=experiment.id, file_id=source.id),
        None,
    )
    assert admitted.asset_id == "public-corn-m5-moisture-v1"
    assert profile
    assert selected == ["public-corn-m5-moisture-v1", "public-corn-m5-moisture-v1"]
