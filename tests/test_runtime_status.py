"""Extension connectivity may restrict egress, never bypass user consent."""

import pytest

from spectra_sherpa.app.contracts import runtime_status as status
from spectra_sherpa.app.core import security


@pytest.fixture(autouse=True)
def isolate_policy():
    previous = status.set_runtime_status_provider(None)
    yield
    status.set_runtime_status_provider(previous)


@pytest.mark.parametrize("enabled,degraded,expected", [(True, False, True), (True, True, False), (False, False, False)])
def test_extension_can_only_restrict_egress(monkeypatch, enabled, degraded, expected):
    monkeypatch.setattr(security.app_config, "egress_enabled", enabled)
    status.set_runtime_status_provider(lambda: {"is_degraded": degraded})
    assert security.is_egress_enabled() is expected


@pytest.mark.parametrize("result", [None, {}, {"is_degraded": "false"}])
def test_missing_or_malformed_connectivity_refuses_egress(result):
    status.set_runtime_status_provider(lambda: result)
    assert status.external_services_available() is False


def test_failed_provider_refuses_egress_and_reports_degradation():
    def broken():
        raise RuntimeError("provider failed")

    status.set_runtime_status_provider(broken)
    assert status.external_services_available() is False
    assert status.runtime_status("enterprise")["is_degraded"] is True


def test_no_extension_uses_local_status():
    assert status.runtime_status("local") == {
        "mode": "local",
        "effective_mode": "local",
        "is_online": True,
        "is_degraded": False,
        "network_state": {},
    }


@pytest.mark.parametrize("state", [None, {}, {"is_degraded": False}, {"is_online": "true"}])
def test_incomplete_status_has_explicit_degraded_response(state):
    status.set_runtime_status_provider(lambda: state)
    assert status.runtime_status("local") == {
        "mode": "local",
        "effective_mode": "local",
        "is_online": False,
        "is_degraded": True,
        "network_state": {},
    }
