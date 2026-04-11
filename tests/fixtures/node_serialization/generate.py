"""CLI: regenerate node-serialization fixtures.

Run when the backend serialization shape intentionally changes and the
new shape is what consumers should rely on going forward.  Backend CI
will then compare the committed fixture against the live runtime,
catching any unintended drift.

Usage (from repo root)::

    python -m tests.fixtures.node_serialization.generate

The script is deterministic: it uses seeded RNGs and volatile-field
placeholders, so consecutive invocations produce identical files
(modulo intentional backend changes).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ._contract import (
    FIXTURE_SPECS,
    FixtureSpec,
    _json_default,
    capture_fixture,
    fixture_path,
    write_fixture,
)


def _try_capture(spec: FixtureSpec) -> dict[str, Any] | None:
    try:
        return capture_fixture(spec)
    except Exception as exc:  # noqa: BLE001 — we want to report any failure mode
        print(
            f"  SKIP  {spec.name}: builder raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def main() -> int:
    print(f"Regenerating {len(FIXTURE_SPECS)} fixture(s)...")
    written = 0
    skipped = 0
    for spec in FIXTURE_SPECS:
        print(f"- {spec.name}")
        fixture = _try_capture(spec)
        if fixture is None:
            skipped += 1
            continue
        # Round-trip through json.dumps to make sure the committed file
        # is valid JSON before we write it.
        _ = json.dumps(fixture, default=_json_default)
        write_fixture(spec, fixture)
        print(f"  wrote {fixture_path(spec).relative_to(fixture_path(spec).parents[3])}")
        written += 1
    print(f"Done. {written} written, {skipped} skipped.")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
