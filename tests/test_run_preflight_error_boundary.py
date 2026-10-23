"""Batch compatibility must not echo dependency HTTP exception internals."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import runs


@pytest.mark.parametrize("status", [400, 409, 422])
@pytest.mark.parametrize("structured", [False, True])
async def test_preflight_keeps_exception_details_in_server_logs(auth_client, monkeypatch, caplog, status, structured):
    private = "Traceback: /private/server/model.py SELECT internal_column FROM internal_table"
    detail = {"exception": private} if structured else private
    prepare = AsyncMock(
        side_effect=[
            HTTPException(status, detail),
            {"receipt": "a" * 64, "metadata": {"n_included_samples": 33}},
        ]
    )
    monkeypatch.setattr(runs, "_prepare_verification_pair", prepare)
    # Application logging need not propagate to pytest's root handler.
    monkeypatch.setattr(runs.logger, "disabled", False)
    caplog.set_level(logging.WARNING, logger=runs.logger.name)
    runs.logger.addHandler(caplog.handler)
    try:
        response = await auth_client.post(
            "/api/v1/runs/verification/preflight",
            json={
                "project_id": 1,
                "mode": "run_workflow",
                "pairs": [{"workflow_id": n, "dataset": {"experiment_id": 1}} for n in (1, 2)],
            },
        )
    finally:
        runs.logger.removeHandler(caplog.handler)
    assert response.status_code == 200
    refused, accepted = response.json()["pairs"]
    assert refused["index"] == 0 and refused["compatible"] is False
    assert refused["reason"] and private not in response.text
    assert "Traceback" not in response.text and "internal_column" not in response.text
    assert private in caplog.text  # operator-only traceback, not response body
    assert accepted == {"index": 1, "compatible": True, "receipt": "a" * 64, "metadata": {"n_included_samples": 33}}


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_preflight_does_not_swallow_access_or_server_failures(auth_client, monkeypatch, status):
    monkeypatch.setattr(runs, "_prepare_verification_pair", AsyncMock(side_effect=HTTPException(status, "Refused")))
    response = await auth_client.post(
        "/api/v1/runs/verification/preflight",
        json={
            "project_id": 1,
            "mode": "run_workflow",
            "pairs": [{"workflow_id": 1, "dataset": {"experiment_id": 1}}],
        },
    )
    assert response.status_code == status
