"""Collection starter admission preserves scientific advice, not storage paths."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["storage", "wrapped", "scientific", "cross_project"])
async def test_collection_binding_refusal_privacy(test_session, test_user, monkeypatch, caplog, kind):
    caplog.set_level(logging.WARNING)
    project = Project(user_id=test_user.id, name="Binding privacy")
    other = Project(user_id=test_user.id, name="Other scope")
    test_session.add_all([project, other])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Collection", metadata_path="{}")
    test_session.add(experiment)
    await test_session.commit()
    private_path = "/private/operator-data/source.mat"
    scientific_reason = "Sample identities differ across collection members; choose an explicitly aligned collection"
    if kind == "wrapped":
        try:
            raise PermissionError(13, "Cannot read", private_path)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as exc:
                failure = exc
    elif kind == "scientific":
        failure = ValueError(scientific_reason)
    else:
        failure = PermissionError(13, "Cannot read", private_path)
    load = AsyncMock(side_effect=failure)
    monkeypatch.setattr(routes, "load_project_dataset", load)
    binding = routes.DataBindingSpec(experiment_id=experiment.id, all_files=True, stage="raw")
    with pytest.raises(HTTPException) as refused:
        await routes._validate_binding(
            test_session, test_user.id, binding, other.id if kind == "cross_project" else project.id
        )
    assert private_path not in str(refused.value.detail)
    if kind == "cross_project":
        assert refused.value.status_code == 404
        assert "project" in refused.value.detail.lower()
        load.assert_not_awaited()
        return
    load.assert_awaited_once()
    assert refused.value.status_code == (503 if kind == "storage" else 400)
    if kind == "scientific":
        assert scientific_reason in refused.value.detail
    else:
        assert "check storage access" in refused.value.detail
        assert private_path in caplog.text
