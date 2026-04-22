# Developer Contributor Guide

This guide is for contributors focused on the software infrastructure:
the Python API server, the browser interface, CI/CD pipelines, packaging,
performance, security, and tooling.

If you are a scientist who wants to add a chemometrics algorithm,
see the [Scientist Contributor Guide](scientist-guide.md) instead — it is
shorter and does not require web development knowledge.

---

## Architecture overview

SpectraSherpa has two layers:

- **Python API** — FastAPI server with async SQLAlchemy, a DAG workflow
  execution engine, and optional integrations (SpectroChemPy, LLM providers).
  Lives in `src/spectra_sherpa/`.
- **Browser interface** — Vue 3 + TypeScript single-page application.
  Lives in `frontend/`. Built by Vite; output goes to
  `src/spectra_sherpa/static/` which is included in the Python wheel.

See [docs/dev/architecture.md](../dev/architecture.md) for a deeper walkthrough.

---

## What you need

| What | Why | Install |
|------|-----|---------|
| Python 3.11+ | Runs the API server | [python.org](https://python.org) |
| Poetry | Manages Python packages and virtual environments | `pip install poetry` |
| Node.js 22+ | Only needed to change the browser interface | [nodejs.org](https://nodejs.org) |

---

## Getting started

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa/spectra-sherpa
poetry install --with dev            # installs the app + dev tools
poetry install --with dev -E scp     # also installs SpectroChemPy (optional)
```

If you are working on the browser interface:

```bash
cd frontend && npm ci
```

### Settings file

```bash
cp .env.example .env    # all defaults work for local development
```

### Start the development server

```bash
make dev    # starts Python API on :8000 + browser app on :5173
```

Or start them separately:

```bash
# Window 1: Python server
poetry run uvicorn spectra_sherpa.app.main:create_app --factory --reload --port 8000

# Window 2: browser app (only if you are changing the browser interface)
cd frontend && npm run dev
```

---

## Run tests

```bash
make test          # Python test suite (pytest)
make test-all      # Python + browser interface type checks
```

---

## Frontend static assets

The compiled browser app (`src/spectra_sherpa/static/`) is committed to the
repository so the Python wheel can be installed without Node.js.

Changes under `frontend/` must keep the committed static bundle in sync.
CI verifies that a build completes and that the generated bundle is internally
consistent. Maintainers can also run the `Rebuild Frontend Static Bundle`
workflow or `cd frontend && npm run build` when preparing a wheel/static update.

If you have the pre-commit hooks installed (`pre-commit install`), the
rebuild runs automatically before each commit when you change files
under `frontend/src/`.

---

## Contribution workflow

### For contributors

1. **Fork** the repository and create a **branch** for your change.
2. Make focused changes with tests.
3. Run `make test` and `make lint` locally.
4. Open a **pull request** with:
   - what problem you are solving
   - how your change solves it
   - evidence that your tests pass
   - any notes on behavior that changes for existing users
5. Wait for CI to pass (all checks must be green).
6. A maintainer will deploy your branch to staging for final validation.
7. Once verified on staging, the maintainer merges to `main`.
8. Merging to `main` triggers an automatic deploy to production.

### For maintainers

After CI passes on a pull request, deploy the branch to the staging
environment for manual verification before merging:

```bash
ssh root@<STAGING_IP>
cd ~/spectra-platform/spectra
git fetch origin
git checkout <branch-name>

# Frontend-only change:
cd packages/spectra-ops/docker
docker compose -f docker-compose.prod.yaml up -d --build frontend

# Backend or full-stack change:
cd packages/spectra-ops/docker
docker compose -f docker-compose.prod.yaml up -d --build
```

Verify the change on the staging URL, then merge the PR on GitHub.
After merging, return staging to `main`:

```bash
cd ~/spectra-platform/spectra
git checkout main && git pull
cd packages/spectra-ops/docker
docker compose -f docker-compose.prod.yaml up -d --build
```

Merging to `main` automatically deploys to production via GitHub Actions.

---

## Pull request checklist

- [ ] `make test` passes
- [ ] `make lint` passes (or `make fmt` was run to auto-fix formatting)
- [ ] If you changed the browser interface: the CI rebuild handles packaging
- [ ] If you added a new configuration option: document it in `.env.example`
- [ ] If you added a new processing node: register it with `@register_node`

---

## Adding a new processing node

A node is one processing step in the Workflow Builder. Use the scaffold
generator — it handles most of the boilerplate:

```bash
make node-scaffold
```

See the [Node Scaffold Generator guide](../dev/node_scaffold_generator.md)
and the [Scientist Contributor Guide](scientist-guide.md) for the full
implementation and testing pattern.

### Manual checklist (if not using the generator)

- [ ] Choose the right base class:
  - `TransformSpecNode` — stateless data-in / data-out transforms
  - `EstimatorSpecNode` — fit/predict workflows (scikit-learn style)
  - `Node` — everything else (diagnostics, plots, custom logic)
- [ ] Set `numpy_expr` (TransformSpec) or `estimator_import` (EstimatorSpec)
  for automatic Python export
- [ ] Confirm `node.supports_python_export()` returns `True`
- [ ] Add `@register_node` — this makes the node appear in the palette
- [ ] Write a test for `execute()` with known input and expected output
- [ ] Write a test for `generate_python()` to confirm the exported code is valid
- [ ] Document parameters, inputs, and outputs in `NodeMetadata`

---

## Code style

Run `make fmt` before committing — it auto-formats everything.

### Python

- **Formatter:** black (120-character lines) — `make fmt` applies it
- **Linter:** ruff (E, F, I rule sets) — `make fmt` fixes auto-fixable issues
- Always use the full import path: `from spectra_sherpa.app.X import Y`
  (not the shorter `from app.`)
- Use `async def` for any function that reads from or writes to the database
  or a file
- Every pull request is automatically checked for style on GitHub

### Browser interface (JavaScript/TypeScript)

- **Formatter:** Prettier — `make fmt` or `cd frontend && npx prettier --write src/`
- **Linter:** ESLint — `cd frontend && npm run lint`
- Components use Vue 3 Composition API with TypeScript
- Shared data belongs in a Pinia store (a centralized state container),
  not duplicated inside individual components
- See `frontend/README.md` for the full architecture

---

## Coding expectations

- Keep changes focused and reviewable — one concern per pull request.
- Add or update tests for bug fixes and new behavior.
- Do not change behavior in a way that breaks existing users without
  documenting it in the pull request.
- Keep documentation in sync with the code.
- Never make SpectroChemPy a required dependency — it must stay optional
  (`pip install spectra-sherpa[scp]` installs it on top).

---

## Pull request review criteria

Maintainers prioritize in this order:

1. Correctness
2. Regressions and compatibility
3. Security and data safety
4. Test coverage
5. Maintainability

---

## mypy type checking

The project uses gradual type enforcement:

- `app/core/` — enforced in CI (failures block merges)
- `app/services/dag/` — visible in CI output but non-blocking; fix reported
  issues when you touch those files

---

## Security reports

Do not open public issues for potential vulnerabilities. Report security
issues privately to the maintainers through the project security contact
channel.
