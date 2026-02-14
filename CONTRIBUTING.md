# Contributing to SpectraSherpa

Thanks for your interest in improving SpectraSherpa.

This project is open source under AGPL-3.0, with centralized copyright
ownership to support consistent license enforcement, compliance handling,
and long-term stewardship.

## Before You Contribute

1. Read `README.md` and this file.
2. Review the project license in `LICENSE`.
3. Sign the Contributor License Agreement in `CLA.md` before any non-trivial
   contribution is merged.

## Contribution Workflow

1. Fork the repository and create a topic branch.
2. Make focused changes with tests.
3. Run checks locally.
4. Open a pull request with:
   - problem statement
   - solution summary
   - test evidence
   - migration notes (if any)

## Development Setup

```bash
git clone https://github.com/Spectra-Scientific-LLC/spectrasherpa.git
cd spectrasherpa
pip install -e ".[scp,sherpa]"
```

For frontend development:

```bash
cd frontend
npm install
npm run dev
```

## Tests

Run the relevant test suites for your change:

```bash
pytest -q
```

If your change affects UI behavior, include browser-level verification notes in
the PR description.

## Coding Expectations

- Keep changes scoped and reviewable.
- Add or update tests for bug fixes and new behavior.
- Preserve backward compatibility unless the PR explicitly documents a breaking
  change.
- Keep docs in sync with product behavior.

## Pull Request Review Criteria

Maintainers prioritize:

1. correctness
2. regressions and compatibility
3. security and data safety
4. test coverage
5. maintainability

## Contributor License Agreement (CLA)

To contribute, you must agree to the terms in `CLA.md`.

Summary:

- You assign copyright in accepted contributions to Spectra Scientific LLC.
- Your accepted contributions are distributed under AGPL-3.0 (or later, if
  chosen by the project maintainers).
- You represent that you have the legal right to submit the contribution.
- If you contribute on behalf of an employer, required employer or entity
  authorization must be in place.

Pull requests may be blocked until CLA requirements are satisfied.

## Trivial Changes

Maintainers may, at their sole discretion, merge very small edits without a
signed CLA (for example, typo fixes). This does not create a waiver for future
contributions.

## Code of Conduct

Contributors are expected to communicate professionally and constructively in
issues, pull requests, and discussions.

## Security Reports

Do not open public issues for potential vulnerabilities. Report security issues
privately to the maintainers through the project security contact channel.
