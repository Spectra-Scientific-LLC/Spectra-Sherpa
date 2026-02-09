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

## Phased Refactor Plan

### Phase 0: Contract First (Do this before splitting repos)

1. Freeze API/WebSocket contracts used by hybrid/demo features.
2. Publish versioned schemas (OpenAPI + typed WebSocket message schema).
3. Define compatibility policy (for example: client supports current server and
   previous minor version).

Deliverable:

- One shared contract package or generated schema artifacts consumed by both
  Repo 1 and Repo 2.

### Phase 1: Internal Decoupling Inside Current Repo

1. Isolate server-only modules behind clear package boundaries.
2. Isolate local-only modules and remove server assumptions.
3. Move deployment concerns behind `deploy/` entry points only.
4. Add mode-matrix tests for local/hybrid/demo behavior.

Deliverable:

- Monorepo still works end-to-end, but seams are explicit and testable.

### Phase 2: Extract Repo 2 (Server)

1. Create `spectrasherpa-server` from server-specific modules.
2. Keep external protocol identical at first (no breaking contract changes).
3. Stand up independent CI/CD and versioning for Repo 2.

Deliverable:

- Existing hybrid/demo clients function without client-side rewrites.

### Phase 3: Extract Repo 3 (Ops)

1. Move `deploy/`, Dockerfiles, reverse proxy configs, and production compose.
2. Add environment overlays for demo, production SaaS, and enterprise on-prem.
3. Centralize secrets management and rollout workflows.

Deliverable:

- Deployments no longer require product code repositories to own ops logic.

### Phase 4: Clean Repo 1 to Pure Local-First OSS

1. Remove Docker/Postgres/deploy dependencies from Repo 1.
2. Keep optional cloud integration via API key and contract clients only.
3. Verify zero-regression local quickstart and offline workflows.

Deliverable:

- Repo 1 remains independently installable and useful without Sherpa cloud.

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
