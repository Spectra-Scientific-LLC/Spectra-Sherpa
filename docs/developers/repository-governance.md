# Repository governance

!!! abstract "Summary"
    For contributors: where each kind of truth lives in the repository and the checks that enforce it.

Start with [Where truth lives](../AUTHORITIES.md). Each row separates the owner,
normative document, enforcing check and consumers. Consumers derive from that
owner; new projections do not become competing authorities.

## Evidence is not a passing test receipt

In the public checkout, `make evidence` regenerates the public registry reference;
`make evidence-check` checks it and the repository governance rules without
rewriting files. `make generate` / `make generate-check` additionally cover API
and TypeScript projections. Use `PYTHON=/path/to/python` to select a prepared
environment.

The integration monorepo owns private qualification inputs and its broader
`make evidence` pipeline. It retains two distinct checks:

- Semantic compatibility: the contract, population and value assertions.
- Implementation identity: exact source/dependency digests of what was qualified.

Neither substitutes for the other. Generation cannot create a successful test
receipt, refresh a runtime attestation, advance reviewed retention decisions,
or certify a changed implementation. A stale qualification requires the existing
reviewed qualification procedure and genuine execution evidence. Do not
refresh hashes merely to clear a failure.

Current executable bindings belong in evidence data, not historical planning
prose. Keep old observations and receipts immutable. Link superseded plans to
current authorities rather than treating their historical counts as current.

## Two-repository changes

Submit linked public/integration changes. Compare shared files, including CI
and scripts. Intentional host differences must be classified, reviewed and
tested; listing a difference is not permission to overwrite public code.
Independently changed, unequal blobs require an exact baseline/public/candidate
reconciliation record. A change to any blob invalidates that record. Already
equal blobs need no exception. Release stamp handling remains separately
verified by the publication tool.

## Copy policy

Use the [glossary](../concepts/glossary.md). The initial gate deliberately checks
only three product phrases: “Execute workflow” → “Run workflow”, “Data Portfolio”
→ “Dataset”, and “Short scientific summary” → “Short summary”.

`python scripts/check_user_copy.py` scans Vue text, selected static attributes,
quoted literals in bound attributes/interpolations and frontend JavaScript or
TypeScript (including component scripts), plus workflow-guide prose. It excludes
comments, styles, code blocks, test fixtures and generated files. Scientific terms (including holdout in
methodology, T², Q, RMSEC/RMSECV/RMSEP) and identifiers are not rewritten.
Runtime-composed strings, backend copy, other docs and translations remain
outside this gate; it does not evaluate code or claim complete prose coverage.

The three-phrase inventory has been burned down to **zero**. The baseline must
remain empty; editing it to match new occurrences fails the check. The explicit
baseline-writing option refuses to record violations. This gate runs through
`make evidence-check` in public CI as well as the lightweight copy check.

## Ratchet checkpoints

The copy inventory is zero now and may not grow. For transport boundaries,
`legacy-boundaries.json` records migration debt, not permission to add another
type authority. Any PR changing a listed API consumer must either retire that
consumer's handwritten transport boundary through an explicit generated-type
adapter or document why its view-model type is not a transport declaration.
The count must not grow to accommodate new copies.

At 0.6.4 release-prep review, publish the before/after inventory and remaining
named boundaries with the [release checklist](release-preparation.md).
At the next cohesion review, each remaining boundary needs an owning migration
slice (workflow, dataset, run, deploy, or extension). Do not set an arbitrary
line quota or remove scientific typing just to reduce the count.

## Publication and pre-commit checks

Upstream CI compares the **entire tracked public subtree**, not only paths
changed by the current pair. A reviewed `pair-target.json` pins the public
revision and both baselines. The candidate must include current public main;
an intervening public fix requires updating/reconciling the pin. Differences
need both classification and exact-blob reconciliation; neither an old
unchanged divergence nor a manifest entry is an exemption.

Pre-commit runs source checks from the correct frontend directory using installed
tools. It must not download unpinned tools, build or stage static bundles.
