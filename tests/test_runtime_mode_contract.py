"""Unknown runtime modes are not enabled by package discovery or configuration."""

import pytest

from spectra_sherpa.app.contracts import runtime_mode


@pytest.fixture(autouse=True)
def isolate_modes(monkeypatch):
    monkeypatch.setattr(runtime_mode, "_policies", {})


@pytest.mark.parametrize("name", ["local", "enterprise"])
def test_extension_cannot_replace_core_mode(name):
    with pytest.raises(ValueError, match="cannot replace"):
        runtime_mode.register_runtime_mode(runtime_mode.RuntimeModePolicy(name=name))


def test_only_explicit_registration_admits_product_mode():
    with pytest.raises(ValueError, match="owning product"):
        runtime_mode.validate_runtime_mode("test_product")
    policy = runtime_mode.RuntimeModePolicy(name="test_product")
    runtime_mode.register_runtime_mode(policy)
    assert runtime_mode.validate_runtime_mode("test_product") == "test_product"
    assert runtime_mode.runtime_mode_policy("test_product") == policy


def test_duplicate_registration_cannot_change_authentication():
    runtime_mode.register_runtime_mode(runtime_mode.RuntimeModePolicy(name="test_product"))
    with pytest.raises(ValueError, match="different policy"):
        runtime_mode.register_runtime_mode(
            runtime_mode.RuntimeModePolicy(name="test_product", implicit_loopback_identity=True)
        )
