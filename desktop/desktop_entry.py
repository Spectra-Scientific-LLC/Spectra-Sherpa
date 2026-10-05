"""PyInstaller entry script for the local desktop workbench."""

import multiprocessing
import os
import sys
import traceback
from pathlib import Path

from spectra_sherpa.desktop_launcher import main


def _acquire_windows_mutex() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    # Create a mutex in the Global namespace so the installer can detect the application.
    # Inno Setup will check for 'Global\SpectraSherpaAppMutex'.
    mutex_name = "Global\\SpectraSherpaAppMutex"
    # CreateMutexW(lpMutexAttributes, bInitialOwner, lpName)
    ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)


def _ensure_streams() -> None:
    """Give a windowed build usable stdio.

    PyInstaller builds this entry point with ``console=False``, so on Windows
    ``sys.stdout``/``sys.stderr`` are ``None``. ``--version`` and any ordinary
    ``print`` then raise ``AttributeError`` on ``None.write``, which surfaces
    as a fatal startup dialog instead of the output the caller asked for.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _dialogs_allowed() -> bool:
    """A modal dialog blocks until someone clicks it.

    Headless callers (CI, the packaged smoke test, any ``--no-browser`` run)
    have nobody to click, so a crash there must fail fast on the log rather
    than hang the process until a job timeout.
    """
    if os.environ.get("CI") or os.environ.get("SPECTRA_DESKTOP_NO_DIALOG"):
        return False
    return "--no-browser" not in sys.argv and "--desktop-ipc" not in sys.argv


def _handle_fatal_exception(e: Exception) -> None:
    error_text = traceback.format_exc()
    log_path = Path(sys.executable).parent / "spectra-fatal-crash.log"
    try:
        log_path.write_text(error_text, encoding="utf-8")
    except Exception:
        pass

    print(error_text, file=sys.stderr)

    if sys.platform == "win32" and _dialogs_allowed():
        import ctypes

        # MB_OK | MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(
            0,
            f"A fatal error occurred during startup. See {log_path} for details.\n\n{str(e)}",
            "Spectra Sherpa Fatal Error",
            0x10,
        )
    sys.exit(1)


if __name__ == "__main__":
    # The local workbench starts a process pool. In a frozen application this
    # intercepts multiprocessing's worker/resource-tracker invocations before
    # they reach the desktop argument parser.
    multiprocessing.freeze_support()
    # Some JIT-enabled clients ship real source. Never create __pycache__
    # inside the signed application; compilation caches belong to user data.
    sys.dont_write_bytecode = True
    _ensure_streams()
    _acquire_windows_mutex()
    # Opt-in CI diagnostics: stack frames only, never locals or launch credentials.
    if os.environ.get("SPECTRA_DESKTOP_STARTUP_TRACE") == "1":
        import faulthandler

        faulthandler.dump_traceback_later(45, file=sys.stderr)
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--verify-hitran-clients":
            from hitran_runtime_check import check

            check(Path(sys.argv[2]))
        else:
            main()
    except Exception as e:
        _handle_fatal_exception(e)
