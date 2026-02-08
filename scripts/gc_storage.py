#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from app.services.version_storage import ContentAddressableStorage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Garbage collect experiment storage")
    parser.add_argument("--experiment-id", type=int, required=True)
    parser.add_argument("--grace-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    storage = ContentAddressableStorage(args.experiment_id)

    cutoff = datetime.now(timezone.utc).timestamp() - args.grace_days * 86400
    orphans = storage.find_orphaned_objects()
    eligible = [path for path in orphans if path.stat().st_mtime <= cutoff]

    if args.dry_run:
        for path in eligible:
            print(path)
        print(f"Eligible orphaned objects: {len(eligible)}")
        return

    deleted = storage.garbage_collect(grace_period_days=args.grace_days)
    print(f"Deleted objects: {len(deleted)}")


if __name__ == "__main__":
    main()
