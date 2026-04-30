"""Contract tests for ``app/contracts/auth_policy.py``.

The auth-policy module is OSS-owned but server-set at runtime. Both the
default values and the setter idempotency are part of the public
contract that commercial-server startup hooks rely on. Mirrors the
drift-detector pattern from ``test_ai_provider_contract.py``.
"""

from __future__ import annotations

import inspect

import pytest

from spectra_sherpa.app.contracts import auth_policy


@pytest.fixture(autouse=True)
def _reset_auth_policy_flags():
    """Each test starts from a clean OSS-default state."""
    auth_policy._reset_for_tests()
    yield
    auth_policy._reset_for_tests()


# ── Defaults ──────────────────────────────────────────────────────────


class TestDefaults:
    def test_registration_enabled_defaults_false(self) -> None:
        """OSS-only installs must default to registration disabled."""
        assert auth_policy.registration_enabled() is False

    def test_registration_requires_code_defaults_false(self) -> None:
        """OSS-only installs must default to no access-code gate."""
        assert auth_policy.registration_requires_code() is False


# ── Setter idempotency ────────────────────────────────────────────────


class TestSetterIdempotency:
    def test_set_registration_enabled_idempotent(self) -> None:
        auth_policy.set_registration_enabled(True)
        assert auth_policy.registration_enabled() is True
        auth_policy.set_registration_enabled(True)
        assert auth_policy.registration_enabled() is True

    def test_set_registration_enabled_can_be_toggled(self) -> None:
        auth_policy.set_registration_enabled(True)
        auth_policy.set_registration_enabled(False)
        assert auth_policy.registration_enabled() is False

    def test_set_registration_requires_code_idempotent(self) -> None:
        auth_policy.set_registration_requires_code(True)
        assert auth_policy.registration_requires_code() is True
        auth_policy.set_registration_requires_code(True)
        assert auth_policy.registration_requires_code() is True

    def test_setter_coerces_truthy_to_bool(self) -> None:
        """Setters cast truthy/falsy inputs to bool — documented behavior."""
        auth_policy.set_registration_enabled(1)  # type: ignore[arg-type]
        assert auth_policy.registration_enabled() is True
        auth_policy.set_registration_enabled(0)  # type: ignore[arg-type]
        assert auth_policy.registration_enabled() is False


# ── Public surface drift detector ────────────────────────────────────


EXPECTED_FUNCTIONS = {
    "registration_enabled": [],
    "registration_requires_code": [],
    "set_registration_enabled": ["flag"],
    "set_registration_requires_code": ["flag"],
}


class TestPublicSurface:
    def test_all_documented_functions_exist(self) -> None:
        for name in EXPECTED_FUNCTIONS:
            assert hasattr(auth_policy, name), f"missing public function: {name}"
            assert callable(getattr(auth_policy, name)), f"{name} is not callable"

    def test_function_signatures_match_documentation(self) -> None:
        """Catches accidental signature changes (parameter renames, additions)."""
        drift: list[str] = []
        for name, expected_params in EXPECTED_FUNCTIONS.items():
            sig = inspect.signature(getattr(auth_policy, name))
            actual_params = list(sig.parameters.keys())
            if actual_params != expected_params:
                drift.append(f"{name}: expected params {expected_params}, got {actual_params}")
        assert not drift, (
            "auth_policy public-function signatures drifted. "
            "Update docs/dev/boundaries.md and EXPECTED_FUNCTIONS together:\n" + "\n".join(f"  {d}" for d in drift)
        )

    def test_functions_re_exported_from_contracts_package(self) -> None:
        """The four functions are part of the OSS public contract surface."""
        from spectra_sherpa.app import contracts

        for name in EXPECTED_FUNCTIONS:
            assert hasattr(contracts, name), (
                f"{name} is not re-exported from spectra_sherpa.app.contracts. "
                "It is part of the public auth-policy contract."
            )
            assert name in contracts.__all__, f"{name} is not in spectra_sherpa.app.contracts.__all__"
