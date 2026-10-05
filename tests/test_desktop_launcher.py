from __future__ import annotations

import os
from pathlib import Path

import pytest

from spectra_sherpa import desktop_launcher


def test_choose_loopback_port_binds_ephemeral_loopback_socket(monkeypatch) -> None:
    class _Socket:
        bound_to: tuple[str, int] | None = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, address: tuple[str, int]) -> None:
            self.bound_to = address

        def getsockname(self) -> tuple[str, int]:
            return (desktop_launcher.LOOPBACK_HOST, 27182)

    socket = _Socket()
    monkeypatch.setattr(desktop_launcher.socket, "socket", lambda *_args: socket)

    assert desktop_launcher.choose_loopback_port() == 27182
    assert socket.bound_to == (desktop_launcher.LOOPBACK_HOST, 0)


def test_desktop_instance_lock_rejects_another_live_launcher(tmp_path) -> None:
    first = desktop_launcher.DesktopInstanceLock(tmp_path)
    first.acquire()
    try:
        second = desktop_launcher.DesktopInstanceLock(tmp_path)
        with pytest.raises(desktop_launcher.DesktopInstanceAlreadyRunning):
            second.acquire()
    finally:
        first.release()

    assert not (tmp_path / desktop_launcher.DesktopInstanceLock.filename).exists()


def test_desktop_instance_lock_replaces_stale_pid_file(monkeypatch, tmp_path) -> None:
    lock_path = tmp_path / desktop_launcher.DesktopInstanceLock.filename
    lock_path.write_text("999999\n", encoding="utf-8")
    monkeypatch.setattr(
        desktop_launcher.DesktopInstanceLock,
        "_pid_is_running",
        staticmethod(lambda _pid: False),
    )

    lock = desktop_launcher.DesktopInstanceLock(tmp_path)
    lock.acquire()
    try:
        assert lock_path.read_text(encoding="utf-8") == f"{os.getpid()}\n"
    finally:
        lock.release()


def test_desktop_instance_lock_does_not_unlink_a_newly_created_empty_lock(monkeypatch, tmp_path) -> None:
    lock_path = tmp_path / desktop_launcher.DesktopInstanceLock.filename
    lock_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop_launcher.time, "time", lambda: lock_path.stat().st_mtime)

    with pytest.raises(desktop_launcher.DesktopInstanceAlreadyRunning):
        desktop_launcher.DesktopInstanceLock(tmp_path).acquire()

    assert lock_path.exists()


def test_desktop_launcher_forces_local_mode_and_delegates_to_cli(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    runtime_environment: dict[str, str | None] = {}

    monkeypatch.setenv("APP_MODE", "enterprise")
    monkeypatch.setenv("SITE_PROFILE", "pro")
    monkeypatch.setattr(desktop_launcher, "choose_loopback_port", lambda: 27182)

    def _fake_cli_main(args: list[str]) -> None:
        calls.append(args)
        for name in (
            "APP_MODE",
            "SITE_PROFILE",
            "SPECTRA_SHERPA_DESKTOP",
            "SPECTRA_SHERPA_PRESERVE_PORT",
            "LOG_FILE_PATH",
        ):
            runtime_environment[name] = os.environ.get(name)

    monkeypatch.setattr("spectra_sherpa.cli.main", _fake_cli_main)

    desktop_launcher.main(["--data-dir", str(tmp_path), "--no-browser"])

    assert runtime_environment == {
        "APP_MODE": "local",
        "SITE_PROFILE": None,
        "SPECTRA_SHERPA_DESKTOP": "1",
        "SPECTRA_SHERPA_PRESERVE_PORT": "1",
        "LOG_FILE_PATH": str(tmp_path / "logs" / "desktop.log"),
    }
    assert os.environ["APP_MODE"] == "enterprise"
    assert os.environ["SITE_PROFILE"] == "pro"
    assert "SPECTRA_SHERPA_DESKTOP" not in os.environ
    assert "SPECTRA_SHERPA_PRESERVE_PORT" not in os.environ
    assert "LOG_FILE_PATH" not in os.environ
    assert calls == [["--host", "127.0.0.1", "--port", "27182", "--data-dir", str(tmp_path), "--no-browser"]]


def test_desktop_launcher_rejects_second_live_instance(monkeypatch, tmp_path, capsys) -> None:
    lock = desktop_launcher.DesktopInstanceLock(tmp_path)
    lock.acquire()
    try:
        with pytest.raises(SystemExit) as exc_info:
            desktop_launcher.main(["--data-dir", str(tmp_path)])
    finally:
        lock.release()

    assert exc_info.value.code == 1
    assert "already running" in capsys.readouterr().out


def test_desktop_launcher_honors_explicit_port(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(desktop_launcher, "choose_loopback_port", lambda: 27182)
    monkeypatch.setattr("spectra_sherpa.cli.main", lambda args: calls.append(args))

    desktop_launcher.main(["--port", "29000"])

    assert calls == [["--host", "127.0.0.1", "--port", "29000"]]


def _load_desktop_entry():
    """Load the PyInstaller entry script, which is not an importable package."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "desktop" / "desktop_entry.py"
    spec = importlib.util.spec_from_file_location("spectra_desktop_entry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("env", "argv", "expected"),
    [
        ({}, ["SpectraSherpa"], True),
        ({}, ["SpectraSherpa", "--no-browser"], False),
        ({"CI": "true"}, ["SpectraSherpa"], False),
        ({"SPECTRA_DESKTOP_NO_DIALOG": "1"}, ["SpectraSherpa"], False),
    ],
)
def test_fatal_dialog_is_suppressed_for_headless_callers(monkeypatch, env, argv, expected) -> None:
    """A modal crash dialog must never block a run with nobody to dismiss it.

    The packaged smoke test and CI both launch with ``--no-browser``; a startup
    crash there has to fail fast on the log instead of hanging until a timeout.
    """
    entry = _load_desktop_entry()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SPECTRA_DESKTOP_NO_DIALOG", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", argv)

    assert entry._dialogs_allowed() is expected


def test_ensure_streams_replaces_absent_stdio(monkeypatch) -> None:
    """A ``console=False`` build has no stdio, so ``--version`` would crash."""
    entry = _load_desktop_entry()
    monkeypatch.setattr("sys.stdout", None)
    monkeypatch.setattr("sys.stderr", None)

    entry._ensure_streams()

    import sys as _sys

    assert _sys.stdout is not None
    assert _sys.stderr is not None
    _sys.stdout.write("")  # would raise AttributeError on None


@pytest.mark.asyncio
async def test_version_route_omits_provenance_when_unpackaged(monkeypatch) -> None:
    """A pip install or dev run must keep the historical response shape.

    ``/api/v1/version`` is public and its exact body is locked in two places:
    ``tests/test_e2e_local_mode.py::test_version`` and the wheel qualification
    smoke in ``scripts/qualify_release_artifacts.py``. Emitting null provenance
    fields outside a packaged bundle breaks both.
    """
    import sys

    from starlette.testclient import TestClient

    from spectra_sherpa import __version__
    from spectra_sherpa.app.main import create_app

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    app = create_app(include_server_routers=False, include_actor_compat_route=False)
    with TestClient(app, client=("127.0.0.1", 50001)) as client:
        body = client.get("/api/v1/version").json()

    assert body == {"backend_version": __version__}


@pytest.mark.asyncio
async def test_version_route_surfaces_bundled_provenance(monkeypatch, tmp_path) -> None:
    """A packaged bundle must surface what the About surface promises."""
    import json
    import sys

    from starlette.testclient import TestClient

    from spectra_sherpa import __version__
    from spectra_sherpa.app.main import create_app

    (tmp_path / "provenance.json").write_text(
        json.dumps(
            {
                "version": __version__,
                "python_version": "3.11.9",
                "build_commit": "c0ffee",
                "signing_identity": "THUMBPRINT",
                "package_hashes": {"spectra_sherpa": "abc123"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    app = create_app(include_server_routers=False, include_actor_compat_route=False)
    with TestClient(app, client=("127.0.0.1", 50002)) as client:
        body = client.get("/api/v1/version").json()

    assert body["backend_version"] == __version__
    assert body["python_version"] == "3.11.9"
    assert body["build_commit"] == "c0ffee"
    assert body["signing_identity"] == "THUMBPRINT"
    assert body["package_hashes"] == {"spectra_sherpa": "abc123"}


def test_windows_lock_probe_never_calls_os_kill(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(desktop_launcher.sys, "platform", "win32")
    probe = Mock(return_value=True)
    kill = Mock(side_effect=AssertionError("Windows liveness check must never signal a process"))
    monkeypatch.setattr(desktop_launcher, "_windows_pid_is_running", probe)
    monkeypatch.setattr(desktop_launcher.os, "kill", kill)
    assert desktop_launcher.DesktopInstanceLock._pid_is_running(12345)
    probe.assert_called_once_with(12345)
    kill.assert_not_called()


def test_liveness_probe_preserves_running_owned_child():
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert desktop_launcher.DesktopInstanceLock._pid_is_running(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_windows_profile_acl_warning_is_silent_off_windows(tmp_path) -> None:
    assert (
        desktop_launcher.windows_profile_acl_warning(tmp_path, platform="darwin", user_profile="/Users/alice") is None
    )


def test_windows_profile_acl_warning_accepts_profile_default_location() -> None:
    profile = "C:\\Users\\alice"
    assert (
        desktop_launcher.windows_profile_acl_warning(
            Path(profile) / ".spectra_sherpa", platform="win32", user_profile=profile
        )
        is None
    )


def test_windows_profile_acl_warning_flags_custom_dir_outside_profile() -> None:
    warning = desktop_launcher.windows_profile_acl_warning(
        Path("D:\\shared\\spectra"), platform="win32", user_profile="C:\\Users\\alice"
    )
    assert warning is not None
    assert "outside the Windows user profile" in warning


def test_windows_profile_acl_warning_defers_when_profile_is_unknown(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("USERPROFILE", raising=False)
    assert desktop_launcher.windows_profile_acl_warning(tmp_path, platform="win32") is None
