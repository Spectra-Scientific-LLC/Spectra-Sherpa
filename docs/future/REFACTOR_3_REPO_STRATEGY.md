# 3-Repo Refactor Strategy (with MCP and Skills)

## Purpose

This document summarizes how to refactor the current monorepo into a clean
3-repository architecture, why the change is needed, and how to support future
extensions such as MCP and skills without creating new coupling.

Target repositories:

1. `spectra-sherpa` (Repo 1): OSS client, local-first, Python + SQLite
2. `spectrasherpa-server` (Repo 2): commercial backend, multi-user SaaS logic
3. `spectra-ops` (Repo 3): deployment and operations (Docker/K8s/secrets)

---

## Why Refactor Now

The current implementation is functional but tightly coupled across local,
hybrid, and demo paths:

- Modes are already distinct at the product level (`local`, `hybrid`, `demo`)
  but implemented in one codebase.
- Deployment artifacts (`deploy/`, Dockerfiles, compose files) coexist with
  pip-install local workflows.
- Database behavior mixes SQLite and PostgreSQL paths in shared runtime logic.
- Current docs explicitly note that local mode has stronger coverage than
  hybrid/demo paths.

Business and engineering reasons to refactor:

- Preserve low-friction OSS adoption (`pip install`) without cloud complexity.
- Enable commercial velocity in server code without destabilizing local users.
- Improve contributor clarity: where to contribute, what is open, what is not.
- Reduce release risk by separating runtime concerns and ownership.
- Support enterprise/on-prem with a dedicated infrastructure repo.

---

## Target Operating Scenarios

### Scenario A: Local Science (with optional Hybrid)

- User runs Repo 1 only.
- SQLite only, no required external services.
- Full offline chemometrics remains first-class.
- Optional cloud offload is additive, not required.

### Scenario B: Cloud Backend

- Repo 2 deployed by Repo 3.
- PostgreSQL + Redis + API surface for hybrid clients.
- Always-on context, quotas, identity, and managed compute.

### Scenario C: Full Platform Demo/Enterprise

- Repo 1 UI + Repo 2 API + Repo 3 deployment stack.
- Public demo and enterprise installs use the same deploy primitives with
  environment-specific policy.

---

## Repository Boundaries (Hard Rules)

### Repo 1: `spectra-sherpa` (OSS Client)

- Owns local workflow execution, DAG builder UI, plugin SDK, local storage.
- Must run with SQLite only and no required Docker/Postgres dependencies.
- May call server APIs only through versioned client contracts.
- Must not contain production deployment manifests.

### Repo 2: `spectrasherpa-server` (Commercial Backend)

- Owns multi-user auth, tenancy, quotas, managed LLM keys, remote audit,
  cloud-only advisory/compute services.
- Exposes stable API/WebSocket contracts consumed by Repo 1.
- Must not depend on Repo 3 deployment implementation details.

### Repo 3: `spectra-ops` (Infra/Ops)

- Owns Docker/K8s/Helm/Terraform/CI deploy workflows and secrets wiring.
- Builds and deploys Repo 2 and serves Repo 1 assets when needed.
- Contains no product business logic.

---

## Execution Order (Monorepo First)

Do not split repositories yet. Complete contract discipline, test safety, and
policy centralization inside the current monorepo first, then build MCP
foundations, then perform extraction.

### Step 1: Freeze and Document Contracts (Phase 0, 1-2 days)

1. Export and version the FastAPI OpenAPI spec from `/openapi.json`.
2. Document all current WebSocket action schemas (currently six action types)
   with payload and response shapes.
3. Document Sherpa sync/chat contracts explicitly.
4. Create a `contracts/` directory with versioned schema files and changelog.

Deliverable:

- A single source of truth for HTTP + WebSocket + Sherpa contract surfaces.

Why now:

- You cannot split safely without explicit contracts.
- MCP will introduce new contract surface area, so contract governance must
  exist first.

### Step 2: Add Mode-Matrix Regression Tests (Phase 1a, 2-3 days)

1. Add parametrized tests for key behavior in `local`, `hybrid`, and `demo`.
2. Cover auth semantics by mode:
   - local: no-auth behavior
   - hybrid: loopback bypass + protected remote behavior
   - demo: JWT-required behavior
3. Cover mode-specific feature flags.
4. Cover mode-specific egress defaults.
5. Cover rate-limiting activation and enforcement paths by mode.

Deliverable:

- A regression safety net for refactor work across all three operational modes.

Why now:

- Structural refactors without mode coverage create blind regressions.
- Stabilizing existing failing tests plus adding mode coverage materially lowers
  migration risk.

### Step 3: Centralize Mode Policy (Phase 1b, 1-2 days)

1. Create `app/core/mode_policy.py`.
2. Move scattered `if app_config.mode == ...` branches into policy functions,
   for example:
   - `requires_auth()`
   - `allows_export()`
   - `egress_default()`
   - `max_token_ttl()`
3. Replace direct mode branching in routes/services with policy calls.

Deliverable:

- Explicit, testable mode seams without moving repositories yet.

Why now:

- This is the real decoupling work.
- Future extraction becomes targeted and mechanical instead of a broad search.

### Step 4: Build MCP Tool Foundation (3-5 days)

Implement core tool infrastructure before repository extraction:

```text
app/services/
├── tools/
│   ├── registry.py
│   ├── executor.py
│   ├── schemas.py
│   └── builtin/
```

Integration points:

1. `app/services/llm.py`: send tool schemas to providers that support tool or
   function calling.
2. `src/spectra_sherpa/app/main.py`: add WebSocket actions for tool
   discovery/invocation.
3. `src/spectra_sherpa/app/services/plugin_loader.py`: load tool manifests from
   plugin directories and future MCP adapters.
4. `src/spectra_sherpa/app/services/dag/node_base.py`: expose tools as DAG
   addressable capabilities where appropriate.
5. Frontend: add a tools store and tool invocation UX in chat/workflow surfaces.

Deliverable:

- The core capability layer that differentiates Sherpa and clarifies true
  local-vs-cloud boundaries.

Why now:

- MCP defines practical boundaries for Repo 1 vs Repo 2 better than speculative
  upfront partitioning.

### Step 5: Split Repositories After MCP Stabilizes

Perform physical extraction only after Steps 1-4 are stable in production-like
validation:

1. Extract Repo 2 (`spectrasherpa-server`) using established server seams.
2. Extract Repo 3 (`spectra-ops`) for deploy and infrastructure concerns.
3. Clean Repo 1 to strict local-first OSS boundaries.

Deliverable:

- Repo split based on proven seams, not assumptions.

Why now:

- By this point, tool boundaries, contract patterns, and operational needs are
  known and test-backed.

### Priority Summary

| Priority | Action | Duration | Risk if Skipped |
|---|---|---|---|
| 1 | Freeze contracts (OpenAPI + WebSocket schema) | 1-2 days | Client/server drift |
| 2 | Add mode-matrix tests | 2-3 days | Hidden regressions during refactor |
| 3 | Centralize mode policy | 1-2 days | Scattered branches block clean extraction |
| 4 | Build MCP tool foundation | 3-5 days | Product differentiation delayed |
| 5 | Physical repository split | After MCP stability | Premature if done earlier |

---

## Future Extensions: MCP and Skills

Treat extension ownership by runtime context, not by technology.

### MCP Placement

- Repo 1:
  - Local MCP clients and local MCP servers that operate on local files,
    local SQLite, and local datasets.
  - No secrets that require cloud tenancy.
- Repo 2:
  - Cloud MCP servers/integrations requiring tenant identity, quotas, billing,
    managed model routing, or enterprise connectors.
- Repo 3:
  - MCP deployment topology, auth gateway, TLS, scaling, secret injection,
    observability.

### Skills Placement

There are two skill classes:

1. Developer workflow skills (for contributors/agents):
   - Repo-specific skills live with each repo.
   - Shared contributor skills can live in a lightweight tooling repo.
2. Product runtime skills (user-visible capabilities):
   - Offline-capable skills in Repo 1.
   - Cloud-only or proprietary skills in Repo 2.
   - Runtime orchestration and secure service exposure in Repo 3.

### Extension Contract Pattern

Use one versioned extension contract across repos:

- Capability discovery schema
- Tool/skill manifest schema
- Invocation request/response schema
- Error taxonomy and retry semantics

This avoids client/server drift as skills and MCP features grow.

---

## Governance and Release Model

### Versioning

- Repo 1: semantic versioning for OSS client API and plugin SDK.
- Repo 2: semantic versioning for public server contracts.
- Repo 3: release tags tied to deployment bundles and compatibility matrix.

### Compatibility Matrix

Publish and test:

- Repo 1 version -> supported Repo 2 versions
- Repo 2 version -> required contract package version
- Repo 3 bundle -> pinned Repo 1/Repo 2 versions

### CI Requirements

Minimum required automation:

1. Contract compatibility tests (Repo 1 against Repo 2 current and previous).
2. Mode matrix tests for local/hybrid/demo.
3. Smoke deployment test from Repo 3 using pinned artifacts.

---

## Risks and Mitigations

### Risk: Cross-repo drift

Mitigation:

- Contract-first versioning, generated clients, compatibility CI gates.

### Risk: OSS perception drops

Mitigation:

- Keep Repo 1 complete for offline science; avoid artificial crippling.
- Maintain public roadmap for what is open vs commercial.

### Risk: Operational complexity increases

Mitigation:

- Clear ownership, standardized release checklist, and ops runbooks in Repo 3.

### Risk: Migration disruption

Mitigation:

- Extract in phases, preserve behavior first, optimize later.

---

## Success Criteria

The refactor is successful when:

1. Repo 1 can be installed and used fully offline with no Docker/Postgres.
2. Repo 2 can be deployed independently and serves hybrid/demo APIs reliably.
3. Repo 3 can deploy demo/production/on-prem variants from pinned versions.
4. Contract compatibility tests pass across active release lines.
5. MCP and skill extensions can be added without breaking repository boundaries.

---

## Recommended Next Steps (Immediate)

1. Approve repository boundaries and non-negotiable rules.
2. Create shared contract package for API/WebSocket/MCP/skill schemas.
3. Implement mode-matrix tests before physical repo split.
4. Extract Repo 2 first, then Repo 3, then finalize Repo 1 cleanup.
