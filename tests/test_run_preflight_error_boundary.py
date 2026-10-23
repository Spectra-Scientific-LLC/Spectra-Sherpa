"""Batch compatibility must not echo dependency HTTP exception internals."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import runs
from spectra_sherpa.app.services.batch_verification import preflight_refusal_reason
from spectra_sherpa.app.services.legacy_model_application import LEGACY_WARNING, LegacyAcknowledgementRequired


@pytest.mark.parametrize(
    ("code", "fields", "expected"),
    [
        ("reference_targets_required", (), "This workflow requires reference targets for training/evaluation."),
        (
            "fitted_input_mismatch",
            ("signal_units",),
            "application input differs from fitted input authority: signal_units; "
            "use an explicit conversion or refit with the correct metadata",
        ),
        (
            "target_mismatch",
            (),
            "The saved model's target could not be matched. Bind the matching target before application.",
        ),
    ],
)
async def test_scientific_refusal_preserves_reason_but_not_exception_details(
    auth_client, monkeypatch, code, fields, expected
):
    from spectra_sherpa.core.scientific_refusal import ScientificInputRefusal

    if code == "fitted_input_mismatch":
        from spectra_sherpa.app.services.dag.fitted_input_identity import FittedInputMismatch

        refusal = FittedInputMismatch(fields)
        refusal.args = ("Traceback: /private/server.py SELECT private_column",)
    else:
        refusal = ScientificInputRefusal(code, detail="Traceback: /private/server.py SELECT private_column")
    monkeypatch.setattr(runs, "_prepare_verification_pair", AsyncMock(side_effect=refusal))
    response = await auth_client.post(
        "/api/v1/runs/verification/preflight",
        json={"project_id": 1, "mode": "run_workflow", "pairs": [{"workflow_id": 1, "dataset": {"experiment_id": 1}}]},
    )
    assert response.status_code == 200
    assert response.json() == {"pairs": [{"index": 0, "compatible": False, "reason": expected}]}
    assert "Traceback" not in response.text and "private_column" not in response.text


async def test_target_context_is_separate_from_exception_and_scoped_to_each_pair(auth_client, monkeypatch):
    from spectra_sherpa.core.scientific_refusal import ScientificInputRefusal

    async def prepare(payload, pair, session, user_id, *, refusal_context):
        if pair.workflow_id == 1:
            refusal_context.target_name = "Oil"
        if pair.workflow_id in (1, 2):
            raise ScientificInputRefusal("target_mismatch", detail="Traceback: /private/server.py leaked_target")
        return {"receipt": "c" * 64, "metadata": {"n_included_samples": 33}}

    monkeypatch.setattr(runs, "_prepare_verification_pair", prepare)
    response = await auth_client.post(
        "/api/v1/runs/verification/preflight",
        json={
            "project_id": 1,
            "mode": "run_workflow",
            "pairs": [{"workflow_id": n, "dataset": {"experiment_id": 1}} for n in (1, 2, 3)],
        },
    )
    assert response.status_code == 200
    first, second, accepted = response.json()["pairs"]
    assert first["compatible"] is False and "'Oil'" in first["reason"]
    assert second["compatible"] is False and "Oil" not in second["reason"]
    assert accepted["compatible"] is True and accepted["receipt"] == "c" * 64
    assert "Traceback" not in response.text and "leaked_target" not in response.text


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("local_only", "Legacy exploratory model recovery is available only in local OSS with application permission"),
        ("plsda_axis_unavailable", "Legacy PLS-DA has no exact typed feature axis; refit it before application"),
        ("axis_unavailable", "Legacy model has no complete retained numeric feature axis; refit it"),
        ("axis_type_mismatch", "Application data has no matching typed feature axis for the legacy model"),
        ("axis_malformed", "Legacy model feature axis is malformed or incomplete"),
        ("coordinates_mismatch", "Application feature coordinates differ from the legacy fitted axis"),
        ("units_mismatch", "Application feature-axis units differ from the legacy model"),
        ("quantity_mismatch", "Application feature-axis quantity differs from the legacy model"),
    ],
)
async def test_preflight_preserves_classified_scientific_refusals_without_reflection(
    auth_client, monkeypatch, code, reason
):
    from spectra_sherpa.app.services.legacy_model_application import LegacyInputRefusal

    refusal = LegacyInputRefusal(code)
    # Even a dependency adding private detail cannot change the public reason.
    refusal.args = ("Traceback: /private/server/model.py SELECT internal_column",)
    monkeypatch.setattr(runs, "_prepare_verification_pair", AsyncMock(side_effect=refusal))
    response = await auth_client.post(
        "/api/v1/runs/verification/preflight",
        json={
            "project_id": 1,
            "mode": "run_workflow",
            "pairs": [{"workflow_id": 1, "dataset": {"experiment_id": 1}}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"pairs": [{"index": 0, "compatible": False, "reason": reason}]}
    assert "Traceback" not in response.text and "internal_column" not in response.text


def test_legacy_public_refusal_vocabulary_is_closed():
    from spectra_sherpa.app.services.legacy_model_application import LegacyInputRefusal, legacy_refusal_reason

    with pytest.raises(KeyError):
        LegacyInputRefusal("Traceback: /private/server/model.py")
    with pytest.raises(KeyError):
        legacy_refusal_reason("unreviewed-reason")


@pytest.mark.parametrize("legacy", [False, True])
async def test_preflight_value_errors_never_echo_details(auth_client, monkeypatch, caplog, legacy):
    private = "Traceback: /private/server/model.py SELECT internal_column FROM internal_table"
    exception_type = LegacyAcknowledgementRequired if legacy else ValueError
    monkeypatch.setattr(
        runs,
        "_prepare_verification_pair",
        AsyncMock(
            side_effect=[
                exception_type(private),
                {"receipt": "b" * 64, "metadata": {"n_included_samples": 33}},
            ]
        ),
    )
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
    expected = {"index": 0, "compatible": False, "reason": LEGACY_WARNING if legacy else preflight_refusal_reason(422)}
    if legacy:
        expected["code"] = "legacy_ack_required"
    assert refused == expected
    assert private not in response.text and "internal_column" not in response.text
    assert private in caplog.text
    assert accepted == {"index": 1, "compatible": True, "receipt": "b" * 64, "metadata": {"n_included_samples": 33}}


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
