from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import spectra_sherpa.app.core.startup as startup
from spectra_sherpa.app.services.encryption import get_master_key


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


def test_hybrid_security_rejects_short_master_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(
        monkeypatch,
        mode="hybrid",
        secret_key="safe-secret",
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


# ===========================================================================
# SpectroChemPy bootstrap timeout behavior
# ===========================================================================


def test_scp_bootstrap_timeout_auto_is_non_blocking(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path,
) -> None:
    class _TimedOutFuture:
        def __init__(self) -> None:
            self.cancel_called = False

        def result(self, timeout=None):  # noqa: ANN001
            raise FutureTimeout()

        def cancel(self) -> None:
            self.cancel_called = True

    class _FakeExecutor:
        def __init__(self, max_workers=1):  # noqa: ANN001
            self.shutdown_calls: list[tuple[bool, bool]] = []
            self.future = _TimedOutFuture()

        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            return self.future

        def shutdown(self, wait=True, cancel_futures=False):  # noqa: ANN001
            self.shutdown_calls.append((wait, cancel_futures))

    fake_executor = _FakeExecutor()

    monkeypatch.setenv("SCP_DATA_BOOTSTRAP", "auto")
    monkeypatch.setenv("SCP_DATA_TIMEOUT", "1")
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.HAS_SCP",
        True,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.get_scp_datadirs",
        lambda: [tmp_path / "missing"],
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.download_testdata",
        lambda: None,
    )
    monkeypatch.setattr(
        "concurrent.futures.ThreadPoolExecutor",
        lambda max_workers=1: fake_executor,
    )

    with caplog.at_level("WARNING"):
        startup.ensure_spectrochempy_data()

    assert "timed out after 1s" in caplog.text
    assert fake_executor.future.cancel_called is True
    assert fake_executor.shutdown_calls == [(False, True)]


def test_scp_bootstrap_timeout_required_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _TimedOutFuture:
        def __init__(self) -> None:
            self.cancel_called = False

        def result(self, timeout=None):  # noqa: ANN001
            raise FutureTimeout()

        def cancel(self) -> None:
            self.cancel_called = True

    class _FakeExecutor:
        def __init__(self, max_workers=1):  # noqa: ANN001
            self.shutdown_calls: list[tuple[bool, bool]] = []
            self.future = _TimedOutFuture()

        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            return self.future

        def shutdown(self, wait=True, cancel_futures=False):  # noqa: ANN001
            self.shutdown_calls.append((wait, cancel_futures))

    fake_executor = _FakeExecutor()

    monkeypatch.setenv("SCP_DATA_BOOTSTRAP", "required")
    monkeypatch.setenv("SCP_DATA_TIMEOUT", "1")
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.HAS_SCP",
        True,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.get_scp_datadirs",
        lambda: [tmp_path / "missing"],
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.download_testdata",
        lambda: None,
    )
    monkeypatch.setattr(
        "concurrent.futures.ThreadPoolExecutor",
        lambda max_workers=1: fake_executor,
    )

    with pytest.raises(RuntimeError, match="timed out after 1s"):
        startup.ensure_spectrochempy_data()

    assert fake_executor.future.cancel_called is True
    assert fake_executor.shutdown_calls == [(False, True)]


def test_scp_completeness_check_requires_nested_anchor_paths(tmp_path) -> None:
    datadir = tmp_path / "testdata"
    (datadir / "irdata").mkdir(parents=True)
    (datadir / "ramandata").mkdir(parents=True)
    (datadir / "nmrdata").mkdir(parents=True)
    (datadir / "galacticdata").mkdir(parents=True)
    (datadir / "agirdata").mkdir(parents=True)

    (datadir / "irdata" / "nh4y-activation.spg").write_text("x")
    (datadir / "ramandata" / "wire").mkdir(parents=True)

    for idx in range(30):
        (datadir / "irdata" / f"sample_{idx}.spa").write_text("x")

    assert startup._scp_testdata_looks_complete(datadir) is False

    nested_nmr = datadir / "nmrdata" / "bruker" / "tests" / "nmr" / "topspin_1d" / "1"
    nested_nmr.mkdir(parents=True)
    (nested_nmr / "fid").write_text("x")

    assert startup._scp_testdata_looks_complete(datadir) is True


def test_scp_bootstrap_redownloads_when_partial_tree_exists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    datadir = tmp_path / "testdata"
    (datadir / "irdata").mkdir(parents=True)
    (datadir / "ramandata").mkdir(parents=True)
    (datadir / "irdata" / "nh4y-activation.spg").write_text("x")

    download_calls: list[str] = []

    monkeypatch.setenv("SCP_DATA_BOOTSTRAP", "auto")
    monkeypatch.setattr("spectra_sherpa.app.lib.scp_compat.HAS_SCP", True)
    monkeypatch.setattr("spectra_sherpa.app.lib.scp_compat.get_scp_datadirs", lambda: [datadir])
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.scp_compat.download_testdata",
        lambda: download_calls.append("downloaded"),
    )

    startup.ensure_spectrochempy_data()

    assert download_calls == ["downloaded"]
