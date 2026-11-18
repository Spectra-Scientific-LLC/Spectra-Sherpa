"""Portable Eigenvector fixtures for source and installed-wheel tests."""

import pytest


@pytest.fixture
def patch_eigenvector_loader(monkeypatch: pytest.MonkeyPatch):
    """Route Eigenvector execution tests to generated non-upstream fixtures."""
    from tests.eigenvector_test_fixtures import generated_eigenvector_result

    monkeypatch.setattr(
        "spectra_sherpa.app.lib.eigenvector.load_eigenvector_dataset",
        generated_eigenvector_result,
    )
    return generated_eigenvector_result
