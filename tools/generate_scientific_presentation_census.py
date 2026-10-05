#!/usr/bin/env python3
"""Generate the checked all-node scientific-presentation census."""

from __future__ import annotations

import argparse
import json

from _provenance import ensure_local_checkout_on_path, require_local_checkout

_PACKAGE_ROOT = ensure_local_checkout_on_path(__file__)

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins

require_local_checkout(_PACKAGE_ROOT)

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.presentation_contract import build_scientific_presentation_census


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the checked census matches the live canonical registry",
    )
    arguments = parser.parse_args()
    repository_root = _PACKAGE_ROOT.parents[1]
    output_path = repository_root / "docs" / "evidence" / "scientific-presentation-census.json"
    census = build_scientific_presentation_census(node_registry.list_nodes())
    rendered = json.dumps(census, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != rendered:
            checked_digest = "missing"
            if output_path.exists():
                try:
                    checked_digest = str(json.loads(output_path.read_text(encoding="utf-8")).get("census_digest"))
                except (json.JSONDecodeError, AttributeError):
                    checked_digest = "malformed"
            raise SystemExit(
                "stale scientific-presentation census: "
                f"checked={checked_digest} live={census['census_digest']} path={output_path}"
            )
        print(f"scientific-presentation census is current: {census['census_digest']}")
        return
    output_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
