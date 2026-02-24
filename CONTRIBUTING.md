# Contributing to SpectraSherpa

Thanks for your interest in improving SpectraSherpa.

This project is open source under AGPL-3.0, with an exclusive license grant
CLA to support consistent license enforcement, compliance handling, and
long-term stewardship. Contributors retain copyright ownership.

## Before You Contribute

1. Read `README.md` and this file.
2. Review the project license in `LICENSE`.
3. Sign the Contributor License Agreement ([`CLA.md`](CLA.md) for individuals,
   [`CLA-entity.md`](CLA-entity.md) for organizations) before any non-trivial
   contribution is merged.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 22+ (for frontend)
- [Poetry](https://python-poetry.org/) (`pip install poetry`)

### Backend

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
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
changes needed.

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
- [ ] If new env var: added to `.env.example`
- [ ] If new DAG node: registered via `@register_node` decorator with `NodeMetadata`

## New Node Checklist

Adding a new DAG node? **Use the Node Scaffold Generator** for 75% time savings:

### Quick Start (30 minutes instead of 2 hours)

```bash
make node-scaffold
```

The generator will:
- ✅ Generate complete node implementation (transform, estimator, or custom)
- ✅ Create test file with pytest fixtures
- ✅ Generate documentation template
- ✅ Include usage examples and best practices
- ✅ Validate naming and structure

**See**: [docs/dev/node_scaffold_generator.md](docs/dev/node_scaffold_generator.md) for detailed guide

### Manual Checklist (if not using scaffold)

- [ ] Choose the right base class:
  - `TransformSpecNode` for stateless Dataset-in / Dataset-out transforms (preferred)
  - `EstimatorSpecNode` for sklearn-style fit/predict workflows (preferred)
  - `Node` for everything else (diagnostics, visualization, custom logic)
- [ ] Set `numpy_expr` (TransformSpec) or `estimator_import` (EstimatorSpec) for automatic Python export
- [ ] Verify `node.supports_python_export()` returns `True`
- [ ] Register via `@register_node` — node appears in the Workflow Builder palette
- [ ] Add a test for `execute()` with known input/output
- [ ] Add a test for `generate_python()` output (both SCP and numpy modes if applicable)
- [ ] Document parameters, inputs, and outputs in metadata

## Code Style

### Backend

- **Formatter:** black (line-length 120) — config in `pyproject.toml`
- **Linter:** ruff (E, F, I rule sets) — config in `pyproject.toml`
- Imports: always use `from spectra_sherpa.app.X import Y` (never bare `from app.`)
- Async: use `async def` for all DB and I/O operations
- Format before committing: `make fmt` (runs black + ruff --fix + prettier)
- CI enforces `black --check` and `ruff check` on every PR

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

All contributors must sign a CLA before their first non-trivial PR is merged.

- **Individuals:** Read and sign [`CLA.md`](CLA.md) — the CLA bot will prompt
  you automatically when you open a PR. Sign by commenting on the PR.
- **Organizations:** Read and sign [`CLA-entity.md`](CLA-entity.md) — requires
  an offline signature from an authorized representative. Contact maintainers
  to arrange.

Summary of terms (Harmony HA-CLA-I/E-E v1.0, Exclusive License Grant):

- **You retain copyright** in your contributions.
- You grant Spectra Scientific LLC an exclusive, perpetual, irrevocable license
  to use, sublicense, and distribute your contributions under any terms —
  including open source (AGPL-3.0) and commercial licenses.
- You grant a non-exclusive patent license covering your contributions.
- You represent that you have the legal right to submit the contribution.

Pull requests are blocked by the CLA bot until requirements are satisfied.

## Trivial Changes

Maintainers may, at their sole discretion, merge changes that affect **only**
whitespace, spelling, punctuation, or comment text — touching no executable
code, configuration, or build files — without a signed CLA. This exception:

- Applies only when a maintainer explicitly invokes it on the PR.
- Does not create a waiver or precedent for future contributions.
- May be revoked at any time; maintainers may still require a signed CLA for
  any contribution regardless of scope.

## Code of Conduct

Contributors are expected to communicate professionally and constructively in
issues, pull requests, and discussions.

## Security Reports

Do not open public issues for potential vulnerabilities. Report security issues
privately to the maintainers through the project security contact channel.
