# Release preparation

This is a contributor checklist, not a release announcement or authorization
to publish. The v0.6.4 candidate remains unreleased until its review,
qualification and publication gates are complete.

## Candidate and evidence

1. Include reviewed fixes before selecting the candidate for manual validation.
   Record the exact source revision and built artifact identity.
2. Run the full public scientific browser qualification on Linux, Windows and
   macOS. PR smoke or a successful run on an older revision does not qualify
   the candidate. Preserve independent table, plot, identity, inclusion, units
   and export assertions.
3. Investigate reproducible failures before proceeding. Use retained images
   and environment versions to distinguish rendering changes from capture
   defects; do not raise pixel tolerances simply to make a test pass.
4. Check generated contracts, reference documentation, evidence and saved-model
   compatibility against the candidate. Generation alone is not qualification.
5. Validate fresh installation, upgrade, save/reopen, report/CSV export and
   local model application. Optional dependencies must be explicit.
6. If the candidate changes, rerun affected qualification and record the new
   identity. Do not relabel earlier evidence.

## Version and publication

Prepare version metadata and release notes in a dedicated release change.
Check the actual package/frontend version inventory, not an assumed file count.
Move reviewed Unreleased changes into a dated section and update the release
guide, navigation and README together. Installation instructions must distinguish
the published package from a source candidate.

For v0.6.4, verify the public-index baseline explicitly: source-only versions
are not PyPI upgrade checkpoints. Cover the 0.6.0 → 0.6.4 upgrade in the release
guide, including the KNN/SIMCA retraining decision, PLS-DA serializer and
calibration-versus-validation changes, and the database migration adding
`project.goal`. Preserve the 0.6.0 saved-model compatibility reference; do not
silently substitute a source-only release. Exercise these changes on a backed-up
copy of an older profile, not the scientist's only working copy.

Obtain explicit maintainer approval before tagging or publishing. PyPI
publication does not imply a native installer is available; desktop packaging
has its own authorization and qualification gates.

The private release map is a publication receipt, not a preparation checklist.
Its new entry is written by the publication workflow only after the exact public
and upstream revisions exist. Do not invent a 0.6.4 entry during release prep.

See [Testing and release](testing-release.md) and
[Repository governance](repository-governance.md).
