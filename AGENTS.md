# Working on SpectraSherpa OSS

Read [docs/AUTHORITIES.md](docs/AUTHORITIES.md) before changing scientific or
user-facing behavior. Derive from the named authority; do not redeclare node,
term, axis, help-link, or admission knowledge in a consumer.

- Computation belongs in canonical workflow nodes. Inspectors, Runs and Reports
  present retained results; basic descriptive arithmetic is allowed.
- Keep sample identity, inclusion and units on the typed dataset axes/context.
  Do not create a second authority in free-form metadata.
- Keep actionable warnings and compact scientific context. Put methodology in
  contextual `?` help, short explanations in hover, and omit redundant prose.
  Do not add Guidance to this GUI cleanup. Preserve offline report claim scope.
- Preserve functionality. Ask before removing or consolidating user capabilities.
- Test Data View independently of plots. For scientific GUI changes, verify the
  affected workflow in Chrome and record dataset, workflow, node, port and outcome.
- Use `python scripts/run_public_tests.py` for the standalone test profile.
  Do not remove failing gates or rewrite immutable historical evidence.
- Maintainer changes shared with the monorepo need linked OSS/monorepo PRs.
  Keep unrelated worktrees untouched. Do not merge without explicit approval.
