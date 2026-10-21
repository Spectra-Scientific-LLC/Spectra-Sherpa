"""Disposable local application for scientific browser acceptance.

Never attaches to the scientist's profile or an existing server. Playwright owns
this process and terminates it after the suite; the temporary profile is removed
on graceful shutdown. No provider dataset is downloaded by this launcher.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8041)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / "src/spectra_sherpa/static/index.html").is_file():
        parser.error("Build the frontend first: cd frontend && npm run build")
    sys.path.insert(0, str(root / "src"))
    with TemporaryDirectory(prefix="sherpa-browser-acceptance-") as profile:
        os.environ.update(
            APP_MODE="local",
            SITE_PROFILE="local",
            DATA_DIR=profile,
            DATABASE_URL=f"sqlite+aiosqlite:///{profile}/spectra_platform.db",
            EGRESS_ENABLED="false",
            MPLCONFIGDIR=f"{profile}/mpl",
            # Disposable launch credential; never reuse a published fixture key.
            APP_API_KEY=secrets.token_urlsafe(32),
        )
        import uvicorn

        uvicorn.run(
            "spectra_sherpa.app.main:create_app",
            factory=True,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
