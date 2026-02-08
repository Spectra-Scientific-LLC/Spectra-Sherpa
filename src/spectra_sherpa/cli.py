"""CLI entry point: ``spectra-sherpa`` command.

Usage::

    spectra-sherpa                  # Start on port 8000, open browser
    spectra-sherpa --port 8001      # Custom port
    spectra-sherpa --no-browser     # Don't auto-open browser
    spectra-sherpa --data-dir ~/my_data
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser


def _open_browser(url: str, delay: float = 2.0) -> None:
    """Open the browser after a short delay (daemon thread)."""
    time.sleep(delay)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    from spectra_sherpa import __version__

    parser = argparse.ArgumentParser(
        prog="spectra-sherpa",
        description="SpectraSherpa — local spectroscopy platform",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number (default: 8000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the browser automatically",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory (default: ~/.spectra_sherpa/ or <repo>/data)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args(argv)

    # Load .env before setting defaults, so .env values take precedence
    from spectra_sherpa._paths import get_env_file_search_paths
    from dotenv import load_dotenv

    for _env_candidate in get_env_file_search_paths():
        if _env_candidate.is_file():
            load_dotenv(_env_candidate)
            break

    # Set environment before any app imports (only if not already set via .env)
    os.environ.setdefault("APP_MODE", "local")
    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir

    # Limit threads for single-user local mode
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")

    # Auto-open browser
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        t = threading.Thread(target=_open_browser, args=(url,), daemon=True)
        t.start()

    print(f"Starting SpectraSherpa v{__version__}")
    print(f"  -> {url}")
    print("  Press Ctrl+C to stop.\n")

    import uvicorn

    uvicorn.run(
        "spectra_sherpa.app.main:app",
        host=args.host,
        port=args.port,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
