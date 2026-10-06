"""Readiness responses retain useful status without exposing exception internals."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.lib import dataset_compatibility as compatibility

PRIVATE_DETAIL = "/srv/private/customer-model.json: SELECT secret FROM credentials"


@pytest.mark.parametrize("error_type", [KeyError, TypeError, ValueError])
@pytest.mark.parametrize("stage", ["dataset", "profile", "template"])
def test_analysis_readiness_logs_private_errors_without_returning_them(monkeypatch, caplog, stage, error_type):
    def fail(*args, **kwargs):
        raise error_type(PRIVATE_DETAIL)

    caplog.set_level("WARNING", logger=compatibility.logger.name)
    monkeypatch.setattr(compatibility.logger, "disabled", False)
    monkeypatch.setattr(compatibility.logger, "propagate", True)
    profile = {
        "primary_role": "X_spectra",
        "modality": "spectra",
        "technique": "FTIR",
        "target_type": None,
        "target_fields": [],
        "identity_fields": [],
        "group_fields": [],
        "ordered_samples": False,
    }
    if stage == "dataset":
        monkeypatch.setattr(compatibility, "analysis_profile_from_dataset", fail)
        result = compatibility.build_dataset_analysis_readiness(object(), [])
    else:
        monkeypatch.setattr(
            compatibility,
            "normalize_analysis_profile" if stage == "profile" else "evaluate_template_compatibility",
            fail,
        )
        result = compatibility.build_analysis_profile_readiness(profile, [{"name": "Starter", "slug": "starter"}])
    assert PRIVATE_DETAIL not in json.dumps(result)
    assert PRIVATE_DETAIL in caplog.text
    diagnostic = result["diagnostics"][0]
    assert diagnostic["code"] == ("template_contract_invalid" if stage == "template" else "analysis_profile_incomplete")
    assert diagnostic["detail"]
    assert result["status"] in {"unavailable", "partial"}


@pytest.mark.parametrize("error_type", [ValueError, PermissionError, OSError])
async def test_canonical_target_refusal_does_not_disclose_binding_errors(monkeypatch, caplog, error_type):
    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.services import application_release

    caplog.set_level("WARNING", logger=deploy.logger.name)
    monkeypatch.setattr(deploy.logger, "disabled", False)
    monkeypatch.setattr(deploy.logger, "propagate", True)

    monkeypatch.setattr(application_release, "revoke_stale_releases", AsyncMock(return_value=False))
    release = AsyncMock()
    monkeypatch.setattr(application_release, "ensure_canonical_release", release)
    monkeypatch.setattr(deploy, "resolve_deployment_binding", AsyncMock(side_effect=error_type(PRIVATE_DETAIL)))
    record = SimpleNamespace(id=1, workflow_id=2, artifact_digest="a" * 64, application_plan_digest="b" * 64)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(record, "Model")])))
    result = await deploy.list_canonical_targets(project_id=3, session=session, current_user=SimpleNamespace(id=4))
    assert PRIVATE_DETAIL not in json.dumps(result)
    assert PRIVATE_DETAIL in caplog.text
    assert result[0]["deploy_ready"] is False
    assert result[0]["application_handle"] is None
    assert result[0]["refusal"]
    release.assert_not_called()


@pytest.mark.parametrize("error_type", [ValueError, PermissionError, OSError])
async def test_qc_refusal_does_not_disclose_binding_errors(monkeypatch, caplog, error_type):
    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.services import instrument_qc

    caplog.set_level("WARNING", logger=deploy.logger.name)
    monkeypatch.setattr(deploy.logger, "disabled", False)
    monkeypatch.setattr(deploy.logger, "propagate", True)

    watch = SimpleNamespace(id=1, workflow_id=2)
    monkeypatch.setattr(deploy, "_get_user_watch", AsyncMock(return_value=watch))
    monkeypatch.setattr(deploy, "_qualification_workflow", AsyncMock())
    monkeypatch.setattr(deploy, "_qc_binding", AsyncMock(side_effect=error_type(PRIVATE_DETAIL)))
    monkeypatch.setattr(instrument_qc, "qc_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(instrument_qc, "qc_qualification_state", AsyncMock(return_value=None))
    result = await deploy.get_watch_qc(watch_id=1, session=object(), current_user=SimpleNamespace(id=4))
    assert PRIVATE_DETAIL not in json.dumps(result)
    assert PRIVATE_DETAIL in caplog.text
    assert result["application_refusal"]
    assert result["snapshot"]["status"] != "within_declared_limits"
