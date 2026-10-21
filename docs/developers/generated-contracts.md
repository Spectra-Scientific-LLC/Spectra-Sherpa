# Generated contracts and references

!!! abstract "Summary"
    For contributors: which files are generated from backend authorities (API types, node reference tables) and how to regenerate them instead of editing by hand.

Backend schemas and node metadata own public transport and node-reference
definitions. Generated files are projections, not new authorities. Frontend
view models may remain handwritten where they express presentation state.

## Regenerate and check

With the development Python environment and frontend dependencies installed:

```sh
make generate
make generate-check
make docs
python scripts/check_built_help.py --site-dir site
```

`make generate-check` does not rewrite files. To use an already activated Python
environment rather than Poetry, pass `PYTHON=python` to Make. Review generated
diffs alongside their schema or registry changes; do not edit generated tables
or TypeScript declarations directly.

The public OpenAPI generator constructs only the OSS application in a temporary
local profile, without running its lifespan, reading a user's database or
registering private routes. Its snapshot is
`frontend/contracts/openapi-v1.json`. The existing LLM contract remains a
separate input for its established clients.

## Consumers and boundaries

- Generated transport declarations describe wire data. API adapters explicitly
  convert them to frontend view models; they must not infer scientific identity,
  units, population or validation status.
- Node reference regions are generated from the live registry. Methodology and
  examples outside marked regions remain hand-authored.
- Help checks resolve the existing method-topic and node-help declarations
  against actual built pages and anchors. This is not a live-site publishing
  check.
- The versioned frontend extension contract is shared by the host and its
  extensions. The runtime compatibility check remains necessary for bundles
  built and deployed separately.

Some endpoints still expose loose records, and some frontend boundaries remain
unmigrated. A generated schema cannot make those records scientifically typed.
The migration ratchet records remaining handwritten boundaries; it is not a
claim that every consumer has been migrated.

## Diagnostic review authority

`app/services/diagnostic_review_summary.py` is the common entry point for saved
PCA, PLS regression and PLS-DA review facts. The PLS-DA projector remains a
private family-specific implementation because its retained calibration receipt
differs from regression and PCA receipts. Its historical entry point is a
compatibility adapter, not a second authority.

The projection performs no fit and does not change recorded screening methods
or limits. PLS-DA calibration evidence does not establish held-out classifier
performance. Unsupported model families return explicit unavailability; PCR
and SIMCA diagnostics are not added by this consolidation. Authentication,
retained-receipt verification and disclosure decisions remain caller obligations.

This work introduces no new agent transport, remote execution interface or
feature commitment.
