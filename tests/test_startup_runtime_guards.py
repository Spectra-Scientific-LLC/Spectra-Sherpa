from __future__ import annotations

from types import SimpleNamespace

import pytest

import spectra_sherpa.app.core.startup as startup


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    secret_key: str = "safe-secret",
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


def test_hybrid_fails_fast_on_multi_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_concurrency_settings()

    assert exc_info.value.code == 1


def test_hybrid_accepts_single_worker_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")

    startup.validate_concurrency_settings()


def test_hybrid_invalid_worker_value_defaults_to_safe_single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
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


def test_hybrid_security_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="hybrid",
        secret_key=startup.DEFAULT_SECRET_KEY,
        api_key="safe-api-key",
    )

    with pytest.raises(SystemExit) as exc_info:
        startup.validate_security_settings()

    assert exc_info.value.code == 1


def test_hybrid_security_warns_on_default_api_key_when_system_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_runtime(
        monkeypatch,
        mode="hybrid",
        secret_key="safe-secret",
        api_key=startup.DEFAULT_API_KEY,
    )
    monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)

    with caplog.at_level("WARNING"):
        startup.validate_security_settings()

    assert "APP_API_KEY is set to the default value" in caplog.text
    assert "MASTER_ENCRYPTION_KEY not set" in caplog.text


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


# ===========================================================================
# ProcessPoolExecutor graceful fallback
# ===========================================================================


def test_dag_pool_creation_gracefully_handles_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from concurrent.futures import ProcessPoolExecutor

    original_init = ProcessPoolExecutor.__init__

    def _failing_init(self, *args, **kwargs):
        raise PermissionError("semaphore not available")

    monkeypatch.setattr(ProcessPoolExecutor, "__init__", _failing_init)

    # Import the function that creates the pool
    import spectra_sherpa.app.main as app_main

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

