# Contributing

Contributions should improve the scientific reliability, usability, and maintainability of SpectraSherpa.

Scientific operations enter the installed product through source review and
the built-in canonical registry. SpectraSherpa does not load runtime plugins
or execute third-party packages from user directories or entry points. A new
operation therefore needs a closed node contract, a scientific reference,
typed ports, fail-closed parameter admission, and tests before it ships.

The practical path is [Adding a Scientific Node](adding-a-node.md). It follows
one operation from scientific definition through registry admission, oracle
tests, presentation, and paired-platform qualification.

## Good Contributions

- clearer node ports and validation
- better file-format disclosure
- reproducible templates
- well-labeled plots and metrics
- robust model artifacts
- focused tests
- documentation grounded in shipped behavior

## Pull Request Expectations

Describe:

- what changed
- why it matters scientifically or operationally
- what users see
- what tests or docs builds were run
- whether there is any code, migration, or deployment impact

For changes to files, provenance, permissions or offline execution, use the
[Windows portability contract](windows-portability.md). It records the v0.6
failure classes, shared helpers and regression tests that preserve scientific
authority across Windows, macOS and Linux.

For page layout, navigation, subtabs, action placement and Advisor context, use
the [GUI workspace design](gui-workspace-design.md). It is the proposed target
arrangement; its appendix distinguishes required changes from shipped behavior.
Map every moved function to a destination and preserve its identity, capability
and scientific scope. Keep dated UI audits as evidence rather than competing
design authorities.
