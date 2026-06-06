# Testing and Release Hygiene

Release documentation should match shipped behavior.

## Before Release

- run backend tests relevant to changed code
- run frontend tests for changed UI
- build docs with MkDocs strict mode
- verify templates that appear in onboarding
- ensure changelog entries reflect shipped features
- remove stale branches after merge

## Documentation Rule

Do not ship aspirational docs in the main sidebar. If a workflow is not verified enough for a new user, keep it out of the public onboarding path.
