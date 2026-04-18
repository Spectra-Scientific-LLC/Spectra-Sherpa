from __future__ import annotations

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


def test_deprecated_shim_still_works():
    """The services.sherpa_advisor shim re-exports correctly."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from spectra_sherpa.app.services.sherpa_advisor import (
            get_sherpa_advisor as get_via_shim,
        )
        from spectra_sherpa.app.services.sherpa_advisor import (
            reset_sherpa_advisor as reset_via_shim,
        )

    reset_via_shim()
    advisor = get_via_shim()
    assert isinstance(advisor, DisabledAIProvider)
