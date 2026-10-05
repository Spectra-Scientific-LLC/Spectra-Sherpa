# Testing and Release Hygiene

Release documentation should match shipped behavior.

## Before Release

- run backend tests relevant to changed code
- run frontend tests for changed UI
- build docs with MkDocs strict mode
- verify templates that appear in onboarding
- ensure changelog entries reflect shipped features
- verify OSS mirror tags before publishing to PyPI
- remove stale branches after merge

## Scientific Surface Review

Use the [Scientific Result Surface Contract](scientific-result-surface-contract.md)
as the design and acceptance authority for nodes, plots, tables, statistics,
workflow editors, result views, and exports. Verify the minimum five deliberately
dissimilar cases, including a lifecycle case, and add multiway or spatial data
when supported. Assertions must cover scientific identity, populations,
denominators, units, effective parameters, and disclosed transformations—not
only successful rendering. Explicitly check identity, population, parameters,
interpretation, and replay. Plot and metric populations must match or their
difference must be disclosed.

Keep dated audits as revision-specific evidence. Link each fixed issue to its
regression and evidence review; a shared defensive change does not close every
issue in a group.

## Canonical artifact handoff gate

Run `python -m pytest tests/test_canonical_model_artifact_lifecycle.py` from the
OSS package. The registry census requires a fixture for every fitted model and
model decomposition. Follow the [artifact acceptance contract](scientific-result-surface-contract.md#canonical-node-artifact-acceptance): a green numerical fit with no saved model, missing run lineage, or an unusable Deploy application is a release defect. Keep pipeline-only state and cohort replay distinct from new-sample inference.

## Workspace Navigation Review

Use the [GUI workspace design](gui-workspace-design.md) for page/subtab layout,
project and campaign ownership, action placement and Advisor attention. Its
acceptance journeys cover Data, canvas sheets, all four Runs tabs, campaign
stages, local deployment and report generation. For a moved control, verify its
old capability has a reachable destination, with the same object authority and
profile restrictions. Include deep links, Back/Forward, project changes, pending
responses and narrow layouts. A functionality map is design evidence, not proof
that the redesigned frontend has passed browser qualification.

## PyPI Policy

Publishing the public OSS mirror is not the same as publishing to PyPI. The mirror workflow creates the public `spectra-sherpa-vX.Y.Z` tag, then maintainers verify the public repository, CI, documentation, and release notes.

Only after that verification should a maintainer manually run the public **Publish to PyPI** workflow with the exact tag and `confirm=publish`. Do not treat every OSS mirror tag as PyPI-ready.

## Documentation Rule

Do not ship aspirational docs in the main sidebar. If a workflow is not verified enough for a new user, keep it out of the public onboarding path.

## Cross-platform scientific evidence

Use the [Windows portability contract](windows-portability.md) when changing
scientific files, registry text, snapshots, provenance, filesystem authority or
offline tests. Check bytes, encodings, handle lifetime and authority on the actual
platform. Retain the original failing test IDs and require them to pass; an
installer build or a focused suite alone does not replace full qualification.
