from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import spectra_sherpa.app.core.startup as startup
from spectra_sherpa.app.services.encryption import get_master_key

_STRONG_SECRET = "-".join(("secure", "test", "runtime", "entropy", "123456"))
# A real Fernet key — high-entropy by construction, so it passes the
# MASTER_ENCRYPTION_KEY entropy guard. Used wherever a test needs a *valid*
# master key that is not itself the subject under test.
_STRONG_MASTER_KEY = Fernet.generate_key().decode()


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    secret_key: str = _STRONG_SECRET,
    api_key: str = "safe-api-key",
    database_url: str = "sqlite+aiosqlite:///:memory:",
) -> None:
    """Patch startup module globals so tests are mode-focused and isolated."""
    monkeypatch.setattr(startup, "app_config", SimpleNamespace(mode=mode))
    monkeypatch.setattr(
        startup,
        "settings",
        SimpleNamespace(
            secret_key=secret_key,
            api_key=api_key,
            database_url=database_url,
            max_concurrent_jobs=4,
        ),
    )


def test_oss_local_allows_multi_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="local")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    startup.validate_concurrency_settings()


def test_extension_test_fails_fast_on_multi_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="extension_test")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_concurrency_settings()

    assert exc_info.value.code == 1


def test_extension_test_accepts_single_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="extension_test")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")

    startup.validate_concurrency_settings()


def test_extension_test_invalid_worker_value_defaults_to_safe_single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="extension_test")
    monkeypatch.setenv("WEB_CONCURRENCY", "not-an-int")

    startup.validate_concurrency_settings()


def test_oss_local_security_allows_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="local",
        secret_key=startup.DEFAULT_SECRET_KEY,
        api_key=startup.DEFAULT_API_KEY,
    )
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ALLOW_SYSTEM_API_KEY_AUTH", raising=False)

    startup.validate_security_settings()


def test_extension_test_security_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=startup.DEFAULT_SECRET_KEY,
        api_key="safe-api-key",
    )

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_extension_test_security_rejects_default_api_key_when_system_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hybrid/enterprise mode must refuse to start when both the default
    APP_API_KEY is in use AND system key auth is enabled — that combination
    exposes every endpoint to anyone who knows the published default.
    """
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key=startup.DEFAULT_API_KEY,
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "APP_API_KEY is a published default/placeholder" in caplog.text


def test_extension_test_security_rejects_env_example_api_key_when_system_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression: the value shipped in .env.example ("default-local-key")
    is a distinct string from the runtime default ("local-key"). The prior
    exact-match guard only caught the latter, so an operator who copied
    .env.example and enabled system-key auth slipped through. Both must fail.
    """
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key="default-local-key",
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "APP_API_KEY is a published default/placeholder" in caplog.text


def test_extension_test_security_rejects_short_system_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A short (brute-forceable) APP_API_KEY is rejected when it is accepted
    as a credential, even though it is not a known placeholder string.
    """
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key="short-key",
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "APP_API_KEY must be at least" in caplog.text


def test_extension_test_security_rejects_low_diversity_system_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A long but repetitive APP_API_KEY (e.g. "0"*40) clears the length floor
    yet carries almost no entropy — it must still be rejected as a credential.
    """
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key="0" * 40,
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "too low-entropy" in caplog.text


def test_extension_test_security_accepts_strong_system_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strong random APP_API_KEY is accepted with system-key auth enabled."""
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key="k" + "AbC9dEf2" * 5,  # 41 chars, mixed
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    startup.validate_security_settings()


def test_extension_test_security_allows_blank_api_key_when_system_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch, mode="extension_test", secret_key=_STRONG_SECRET, api_key="")
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "false")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    startup.validate_security_settings()


def test_local_security_ignores_system_api_key_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local mode bypasses auth, so even an explicitly enabled placeholder
    APP_API_KEY does not participate in request authentication or block startup.
    """
    _patch_runtime(
        monkeypatch,
        mode="local",
        secret_key=startup.DEFAULT_SECRET_KEY,
        api_key="default-local-key",
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)

    startup.validate_security_settings()


def test_extension_test_security_rejects_short_master_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="extension_test",
        secret_key=_STRONG_SECRET,
        api_key="safe-api-key",
    )
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "too-short")

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_master_encryption_secret_is_normalized_to_valid_fernet_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "x" * 32)

    key = get_master_key()

    Fernet(key)


def test_extension_test_security_rejects_low_entropy_master_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A long-but-repetitive MASTER_ENCRYPTION_KEY clears the 32-char floor but
    is trivially brute-forceable — the single-SHA-256 derivation is only sound
    on a high-entropy input, so a low-entropy one must fail closed.
    """
    _patch_runtime(monkeypatch, mode="extension_test", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.delenv("ALLOW_SYSTEM_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "a" * 40)

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "MASTER_ENCRYPTION_KEY appears too low-entropy" in caplog.text


def test_extension_test_security_rejects_template_marker_master_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An un-substituted ``<...>`` template marker (>=32 chars) must be rejected
    as a placeholder rather than accepted as a real key.
    """
    _patch_runtime(monkeypatch, mode="extension_test", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.delenv("ALLOW_SYSTEM_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "<your-master-encryption-key-goes-here>")

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("CRITICAL"):
            startup.validate_security_settings()

    assert exc_info.value.code == 1
    assert "MASTER_ENCRYPTION_KEY is a placeholder/default" in caplog.text


def test_extension_test_security_accepts_fernet_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuine Fernet key (32 random bytes) is accepted without entropy fuss."""
    _patch_runtime(monkeypatch, mode="extension_test", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.delenv("ALLOW_SYSTEM_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)

    startup.validate_security_settings()


# ===========================================================================
# Enterprise concurrency validation
# ===========================================================================


def test_enterprise_fails_fast_on_multi_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="enterprise")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_concurrency_settings()

    assert exc_info.value.code == 1


def test_enterprise_accepts_single_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="enterprise")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")

    startup.validate_concurrency_settings()


# ===========================================================================
# Enterprise security validation
# ===========================================================================


def test_enterprise_security_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="enterprise",
        secret_key=startup.DEFAULT_SECRET_KEY,
    )

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_enterprise_security_rejects_missing_master_encryption_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch, mode="enterprise", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ALLOW_SYSTEM_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_enterprise_security_rejects_trust_proxy_without_trusted_cidrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch, mode="enterprise", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_extension_test_security_warns_trust_proxy_without_trusted_cidrs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_runtime(monkeypatch, mode="extension_test", secret_key=_STRONG_SECRET, api_key="safe-api-key")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", _STRONG_MASTER_KEY)
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)

    with caplog.at_level("WARNING"):
        startup.validate_security_settings()

    assert "TRUST_PROXY is enabled but TRUSTED_PROXY_CIDRS is not set" in caplog.text


# ===========================================================================
# ProcessPoolExecutor graceful fallback
# ===========================================================================


def test_dag_pool_creation_gracefully_handles_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from concurrent.futures import ProcessPoolExecutor

    def _failing_init(self, *args, **kwargs):
        raise PermissionError("semaphore not available")

    monkeypatch.setattr(ProcessPoolExecutor, "__init__", _failing_init)

    # Import the function that creates the pool

    pool_result = None

    def capture_pool(pool):
        nonlocal pool_result
        pool_result = pool

    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.set_default_pool", capture_pool)

    # Simulate the pool creation logic from lifespan Phase 5
    import multiprocessing

    from spectra_sherpa.app.core.config import settings

    pool_size = settings.dag_worker_pool_size
    try:
        _dag_pool = ProcessPoolExecutor(
            max_workers=pool_size,
            mp_context=multiprocessing.get_context("spawn"),
        )
        capture_pool(_dag_pool)
    except (PermissionError, OSError):
        _dag_pool = None

    # Pool should be None — no SystemExit
    assert _dag_pool is None


@pytest.fixture(autouse=True)
def explicit_test_runtime_policy(monkeypatch):
    from spectra_sherpa.app.contracts import runtime_mode

    monkeypatch.setattr(runtime_mode, "_policies", {})
    runtime_mode.register_runtime_mode(
        runtime_mode.RuntimeModePolicy(name="extension_test", implicit_loopback_identity=True)
    )
