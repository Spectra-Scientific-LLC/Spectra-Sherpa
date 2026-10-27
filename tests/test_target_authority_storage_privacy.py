"""Single-file target admission never issues authority on a storage refusal."""

import logging
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
from spectra_sherpa.app.models.experiment_file import ExperimentFile


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "kind"),
    [("digest", "storage")]
    + [(stage, kind) for stage in ("sidecar", "projection", "native") for kind in ("storage", "wrapped", "validation")],
)
async def test_target_authority_storage_privacy(auth_client, test_session, monkeypatch, caplog, stage, kind):
    from spectra_sherpa import io

    caplog.set_level(logging.WARNING)
    created = await auth_client.post("/api/v1/experiments", json={"name": "Target authority privacy"})
    assert created.status_code == 201
    experiment_id = created.json()["id"]
    record = ExperimentFile(experiment_id=experiment_id, file_path="raw/source.mat", stage="raw", file_type="mat")
    test_session.add(record)
    await test_session.commit()
    path = "/private/operator-data/source.mat"
    if kind == "wrapped":
        try:
            raise PermissionError(13, "Cannot read", path)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as exc:
                error = exc
    elif kind == "validation":
        error = ValueError("registered reference selected target differs from its authority")
    else:
        error = PermissionError(13, "Cannot read", path)
    digest = Mock(return_value="a" * 64)
    sidecar = Mock(return_value={"member_sha256": "a" * 64, "projection_id": "qualified"})
    projection = Mock()
    native = Mock()
    if stage == "native":
        sidecar.return_value = None
    chosen = {"digest": digest, "sidecar": sidecar, "projection": projection, "native": native}[stage]
    chosen.side_effect = error
    monkeypatch.setattr(routes, "_sha256_path", digest)
    monkeypatch.setattr(routes, "read_registered_reference_sidecar", sidecar)
    monkeypatch.setattr(routes, "materialize_reference_member", projection)
    monkeypatch.setattr(io, "ingest", native)
    issue = Mock()
    monkeypatch.setattr(routes, "issue_target_authority", issue)
    binding = routes.DataBindingSpec(experiment_id=experiment_id, file_id=record.id, stage="raw")
    with pytest.raises(HTTPException) as refused:
        await routes._issue_file_target_authority(
            test_session, binding, selected_target="concentration", target_type="continuous"
        )
    assert refused.value.status_code == (503 if kind == "storage" else 400)
    assert path not in refused.value.detail
    chosen.assert_called_once()
    issue.assert_not_called()
    if kind == "validation" and stage != "sidecar":
        assert str(error) in refused.value.detail
    if kind != "validation":
        assert path in caplog.text
