"""Generate the public REST contract without starting an application profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "frontend/contracts/openapi-v1.json"


def build_schema() -> dict:
    # The command is a fresh process: no private startup hooks or registrations.
    # Never load a scientist's database or run the application's lifespan.
    with TemporaryDirectory(prefix="sherpa-openapi-") as profile:
        os.environ.update(
            APP_MODE="local",
            SITE_PROFILE="local",
            DATA_DIR=profile,
            DATABASE_URL=f"sqlite+aiosqlite:///{profile}/contract.db",
            EGRESS_ENABLED="false",
            MPLCONFIGDIR=f"{profile}/mpl",
        )
        sys.path.insert(0, str(ROOT / "src"))
        from spectra_sherpa.app.main import create_app

        application = create_app(include_frontend=False, include_server_routers=False)
        return application.openapi()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=TARGET)
    args = parser.parse_args()
    text = json.dumps(build_schema(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != text:
            parser.exit(1, "Public API contract is stale. Run: make generate\n")
        print("Public API contract is current.")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Generated {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}")


if __name__ == "__main__":
    main()
