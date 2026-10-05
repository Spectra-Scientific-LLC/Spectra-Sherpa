#!/usr/bin/env python3
"""Record the exact runtime required by the live managed optimization profile."""

from __future__ import annotations

import json

from _provenance import ensure_local_checkout_on_path, require_local_checkout

_PACKAGE_ROOT = ensure_local_checkout_on_path(__file__)

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate the complete built-in registry

require_local_checkout(_PACKAGE_ROOT)

from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile


def main() -> None:
    package_root = _PACKAGE_ROOT
    repository_root = package_root.parents[1]
    evidence_path = repository_root / "docs" / "evidence" / "managed-optimization-runtime-attestation.json"
    evidence_path.write_text(
        json.dumps(managed_optimization_profile().runtime_attestation().as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
