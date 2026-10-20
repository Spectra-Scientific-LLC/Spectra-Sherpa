# Repository governance

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

`python scripts/check_user_copy.py` scans static Vue text and selected static
attributes plus workflow-guide prose. It excludes scripts, styles, code blocks,
dynamic bindings and interpolations. Scientific terms (including holdout in
methodology, T², Q, RMSEC/RMSECV/RMSEP) and identifiers are not rewritten.
Dynamic JavaScript strings, backend copy, other docs and translations are
outside this initial gate; this is not a claim of complete prose lint coverage.

Existing occurrences are inventoried in `user-copy-baseline.json`, per file and
rule. New occurrences fail; removal requires shrinking the baseline so it
cannot leave growth credit. The explicit baseline-writing option exists for
reviewed inventory maintenance, never automatic CI recovery.

Pre-commit runs source checks from the correct frontend directory using installed
tools. It must not download unpinned tools, build or stage static bundles.
