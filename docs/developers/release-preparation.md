# 0.6.4 preparation — not release authorization

The version bump belongs to a separate linked OSS/monorepo release-prep pair.
This checklist and the Unreleased changelog prepare that work; they do not
declare a released version, successful qualification, or permission to publish.

## Required order

1. Merge the reviewed cohesion repairs, including OSS #123 / monorepo #1336.
   A structured target-authority refusal must be part of the candidate used
   for manual validation, not added after that candidate is qualified.
2. Close the macOS full-suite reopen regression on the final candidate.
   Run the full public browser qualification on Linux, Windows and macOS.
   PR smoke, a local Chrome pass, or a rerun of an older revision is not
   equivalent. Keep numerical, identity, inclusion and visual assertions.
3. Prepare the lockstep 0.6.4 version update across the packages and frontend
   metadata, using the 0.6.3 release-prep inventory as a starting point and
   checking the actual current tree. Do not assume the old file count is exact.
4. Move the reviewed Unreleased narrative into the dated release section.
   Include all six cohesion pairs: identity/units, theme tokens, browser
   qualification, generated contracts, evidence/governance and scoped state.
   Add `docs/releases/0.6.4.md`, documentation navigation and README references
   in that release-prep pair; run the existing static release checks.
5. Verify paired publication, generated contracts, evidence, compatibility and
   hosted CI on the final release-prep heads. Preserve the Pro hosted compute
   indicator and its intentional test differences.
6. Manually validate the fixed, versioned artifact. Record its exact source and
   artifact identity. If it changes, qualify the changed candidate; do not
   relabel earlier evidence.

## Explicit open gates

- Repeated red-main macOS browser failures block manual release validation.
  Diagnose retained images and environment versions before changing rendering
  capture. Do not raise pixel tolerances merely to make the test pass.
- Target-authority refusal issues remain open until the repair is merged and
  verified. No maintainer deferral is recorded.
- Monorepo #1337 tracks the audit-chainer serialization investigation.
  Do not call it harmless without determining whether events are lost. Actual
  silent audit-event loss escalates the trust-surface severity.
- Desktop packaging remains paused through October 31, 2026, inclusive, and
  requires explicit approval to resume afterward. Source tests are distinct
  from packaging. No tag, publish, deploy or packaging action is authorized
  by this checklist.
