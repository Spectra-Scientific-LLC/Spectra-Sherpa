from __future__ import annotations

import importlib.util

from spectra_sherpa.app.contracts.ai_provider_registry import (
    DisabledAIProvider,
    get_sherpa_advisor,
    reset_sherpa_advisor,
    set_sherpa_advisor,
)


def test_get_sherpa_advisor_defaults_to_disabled_provider():
    reset_sherpa_advisor()

    advisor = get_sherpa_advisor()

    assert isinstance(advisor, DisabledAIProvider)
    assert advisor.is_available is False


def test_set_and_reset_sherpa_advisor():
    reset_sherpa_advisor()

    class FakeProvider:
        is_available = True

    set_sherpa_advisor(FakeProvider())
    advisor = get_sherpa_advisor()
    assert type(advisor).__name__ == "FakeProvider"
    assert advisor.is_available is True

    reset_sherpa_advisor()
    advisor = get_sherpa_advisor()
    assert isinstance(advisor, DisabledAIProvider)


def test_expired_ai_provider_compatibility_modules_are_absent():
    assert importlib.util.find_spec("spectra_sherpa.app.services.sherpa_advisor") is None
    assert importlib.util.find_spec("spectra_sherpa.app.services.ai_provider_errors") is None
