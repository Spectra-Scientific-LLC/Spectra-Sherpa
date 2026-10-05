#!/usr/bin/env python3
"""Generate the checked-in M4.2 node-contract census from the live registry."""

from __future__ import annotations

import json

from _provenance import ensure_local_checkout_on_path, require_local_checkout

_PACKAGE_ROOT = ensure_local_checkout_on_path(__file__)

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins

require_local_checkout(_PACKAGE_ROOT)

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.node_catalog_contract import (
    build_node_contract_census,
    census_digest,
    render_census_markdown,
    validate_census_help_references,
)


def main() -> None:
    package_root = _PACKAGE_ROOT
    repository_root = package_root.parents[1]
    evidence_dir = repository_root / "docs" / "evidence"
    census = build_node_contract_census(node_registry.list_nodes())
    validate_census_help_references(census, package_root=package_root)
    output = {"registry_digest": census_digest(census), **census}
    (evidence_dir / "m4-node-contract-census.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (evidence_dir / "m4-node-contract-census.md").write_text(render_census_markdown(census), encoding="utf-8")


if __name__ == "__main__":
    main()
