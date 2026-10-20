#!/usr/bin/env python3
"""Generate the checked scientific-output semantics census from live authority."""

from __future__ import annotations

import argparse
import json

from _provenance import ensure_local_checkout_on_path, require_local_checkout

_PACKAGE_ROOT = ensure_local_checkout_on_path(__file__)

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins

require_local_checkout(_PACKAGE_ROOT)

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.scientific_values import build_scientific_output_semantics_census


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repository_root = _PACKAGE_ROOT.parents[1]
    output_path = repository_root / "docs" / "evidence" / "scientific-output-semantics-census.json"
    census = build_scientific_output_semantics_census(node_registry.list_nodes())
    expected = json.dumps(census, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != expected:
            raise SystemExit("Stale output semantics: make evidence (monorepo root); review the diff")
    else:
        output_path.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
