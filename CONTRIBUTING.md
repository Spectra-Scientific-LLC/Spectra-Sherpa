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

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 22+ (for frontend)
- [Poetry](https://python-poetry.org/) (`pip install poetry`)

### Backend

```bash
git clone https://github.com/Spectra-Scientific-LLC/spectrasherpa.git
cd spectrasherpa
poetry install --with dev            # core + dev tools (black, ruff, pytest)
poetry install --with dev -E scp     # optional: SpectroChemPy spectral nodes
```

### Frontend

```bash
cd frontend && npm ci
```

### Quick Start

```bash
make dev    # starts backend (:8000) + frontend (:5173) — Ctrl+C stops both
```

Or run them separately:

```bash
# Terminal 1: backend
poetry run uvicorn spectra_sherpa.app.main:create_app --factory --reload --port 8000

# Terminal 2: frontend
cd frontend && npm run dev
```

### Running Tests

```bash
make test          # backend pytest suite
make test-all      # backend + frontend type-check
```

### Environment

Copy `.env.example` to `.env`. The defaults work for local development with no
changes needed. See `.env.enterprise.example` for hybrid/enterprise settings.

> **Note:** Enterprise enforcement (password gating, session expiry, strict CORS,
> SQLite prohibition) is implemented in `spectra-server`, not in this repository.
> This OSS codebase provides mode awareness, rate limiting, and the Demo Contract
> (`DemoContract` in `config.py`) for capability-based feature gating.

## Contribution Workflow

1. Fork the repository and create a topic branch.
2. Make focused changes with tests.
3. Run checks locally (`make test`, `make lint`).
4. Open a pull request with:
   - problem statement
   - solution summary
   - test evidence
   - migration notes (if any)

## Pull Request Checklist

Before submitting:

- [ ] Tests pass locally (`make test`)
- [ ] ESLint passes (`cd frontend && npm run lint`)
- [ ] If UI changed: `cd frontend && npm run build` and commit updated static assets
- [ ] If new env var: added to `.env.example` (and `.env.enterprise.example` if enterprise-only)
- [ ] If new DAG node: registered via `@register_node` decorator with `NodeMetadata`

## Code Style

### Backend

- **Formatter:** black (line-length 120) — config in `pyproject.toml`
- **Linter:** ruff (E, F, I rule sets) — config in `pyproject.toml`
- Imports: always use `from spectra_sherpa.app.X import Y` (never bare `from app.`)
- Async: use `async def` for all DB and I/O operations
- Format locally: `make fmt`

> **Note:** The backend has not yet been bulk-formatted with black/ruff. A dedicated
> format-only PR will establish the baseline. Until then, `make fmt` is available
> locally but not enforced in CI.

### Frontend

- **Formatter:** Prettier (see `frontend/.prettierrc`)
- **Linter:** ESLint with Vue + TypeScript rules (see `frontend/eslint.config.js`)
- Components: Vue 3 Composition API with `<script setup lang="ts">`
- State: Pinia stores (never component-local state for shared data)
- See `frontend/README.md` for architecture details

## Coding Expectations

- Keep changes scoped and reviewable.
- Add or update tests for bug fixes and new behavior.
- Preserve backward compatibility unless the PR explicitly documents a breaking
  change.
- Keep docs in sync with product behavior.
- Never move SpectroChemPy from optional extras to core dependencies. It must
  remain opt-in via `pip install spectra-sherpa[scp]`.

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

Maintainers may, at their sole discretion, merge changes that affect **only**
whitespace, spelling, punctuation, or comment text — touching no executable
code, configuration, or build files — without a signed CLA. This does not
create a waiver for future contributions.

## Code of Conduct

Contributors are expected to communicate professionally and constructively in
issues, pull requests, and discussions.

## Security Reports

Do not open public issues for potential vulnerabilities. Report security issues
privately to the maintainers through the project security contact channel.
