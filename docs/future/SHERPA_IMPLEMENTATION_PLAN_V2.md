# Sherpa Implementation Plan V2

## Status

This V2 plan supersedes the sequencing in `SHERPA_IMPLEMENTATION_PLAN.md`.

The original plan has strong technical ideas, but V2 changes execution order to
match current priorities:

1. Contract discipline first
2. Mode safety net second
3. Policy centralization third
4. MCP/tool capability build fourth
5. Physical repo split last

---

## Why V2 Exists

The original Sherpa plan assumed immediate server extraction and focused on
building server-side intelligence first. The current strategy is monorepo-first
to reduce migration risk and avoid speculative boundaries.

V2 keeps what is valuable from the original:

- Sherpa endpoint and payload model concepts
- Skill taxonomy and structured `SKILL.md` approach
- Managed-key LLM provider model
- Verification mindset for round-trip behavior

V2 changes the order so that contracts and mode behavior are stable before MCP
expands the surface area.

---

## Legacy-to-V2 Mapping

| Legacy Plan Element | Keep? | V2 Placement |
|---|---|---|
| Sherpa protocol models and endpoint contracts | Yes | Step 1 (`contracts/`) |
| Skills directory + category taxonomy | Yes | Step 4 (tool/skill foundation) |
| Server-side LLM provider with managed keys | Yes | Step 4 (after contracts + tests) |
| Immediate separate `spectrasherpa-server` implementation | Not yet | Step 5 (post-stabilization extraction) |
| “No local app changes needed” assumption | No | Replace with MCP-aware local + frontend integration in Step 4 |

---

## Execution Plan

### Step 1: Freeze Contracts (Phase 0, 1-2 days)

Create versioned contract artifacts in-repo before any major refactor.

Suggested structure:

```text
contracts/
├── openapi/
│   └── v1/
│       └── openapi.json
├── websocket/
│   └── v1/
│       ├── actions.md
│       └── message_schemas.json
├── sherpa/
│   └── v1/
│       ├── sync_request.json
│       ├── sync_response.json
│       ├── decide_request.json
│       └── health_response.json
└── CHANGELOG.md
```

Actions:

1. Export OpenAPI from current app (`/openapi.json`) and commit it.
2. Document current WebSocket actions and payload shapes.
3. Capture Sherpa sync/decide/chat contract schemas explicitly.
4. Add contract versioning policy in `contracts/CHANGELOG.md`.

Done criteria:

- Contract files exist and are reviewed.
- Backend and frontend references point to versioned artifacts, not implicit behavior.

### Step 2: Mode-Matrix Tests (Phase 1a, 2-3 days)

Add parameterized tests that run the same behavior across `local`, `hybrid`,
and `demo`.

Minimum matrix:

1. Auth behavior by mode
2. Feature flags by mode
3. Egress defaults by mode
4. Rate-limiting activation by mode

Suggested test entry points:

- `tests/` for API/integration matrix coverage
- Existing auth/security routes and dependencies in:
  - `src/spectra_sherpa/app/api/deps.py`
  - `src/spectra_sherpa/app/core/security.py`
  - `src/spectra_sherpa/app/api/v1/routes/auth.py`
  - `src/spectra_sherpa/app/api/v1/routes/config.py`

Done criteria:

- Matrix tests run in CI/local and fail on mode regressions.

### Step 3: Centralize Mode Policy (Phase 1b, 1-2 days)

Create `src/spectra_sherpa/app/core/mode_policy.py` as the single source of
truth for mode decisions.

Policy API examples:

- `requires_auth(mode, request_context)`
- `allows_export(mode, user)`
- `egress_default(mode)`
- `max_token_ttl(mode)`
- `rate_limits_enabled(mode)`

Actions:

1. Move scattered mode branching into policy helpers.
2. Replace direct `if app_config.mode == ...` checks in routes/services.
3. Keep behavior unchanged while refactoring call sites.

Done criteria:

- Major mode rules are invoked through policy functions.
- Branching is centralized and directly testable.

### Step 4: MCP and Tool Foundation (3-5 days)

Build MCP-ready tooling in the monorepo before extraction.

Suggested backend layout:

```text
src/spectra_sherpa/app/services/
└── tools/
    ├── registry.py
    ├── executor.py
    ├── schemas.py
    └── builtin/
```

Suggested frontend additions:

- `frontend/src/stores/tools.ts`
- Chat/workflow UI hooks for discovery and invocation

Integration targets:

1. `src/spectra_sherpa/app/services/llm.py` for tool/function-calling context
2. `src/spectra_sherpa/app/main.py` for tool-related WebSocket actions
3. `src/spectra_sherpa/app/services/plugin_loader.py` for manifest loading
4. `src/spectra_sherpa/app/services/dag/node_base.py` for DAG-exposed tools

Reuse from legacy plan:

- Skill category model from `SHERPA_IMPLEMENTATION_PLAN.md`
- Structured skill manifests with explicit node/tool triggers

Done criteria:

- Built-in tools can be discovered and invoked.
- Tool contracts are typed and versioned.
- Chat path can call at least one real tool end-to-end.

### Step 5: Extract Repositories After MCP Stabilization

Split only after Steps 1-4 are stable and test-backed.

Extraction order:

1. `spectrasherpa-server` (commercial server logic)
2. `spectra-ops` (deployment and infra)
3. Cleanup `spectra-sherpa` to strict local-first OSS scope

Done criteria:

- Split follows proven seams (contracts + policy + MCP ownership), not guesses.

---

## Acceptance Gates Before Split

Do not begin physical extraction until all are true:

1. Contract artifacts are versioned and reviewed.
2. Mode matrix tests pass consistently.
3. Mode policy centralization is complete for core auth/egress/export logic.
4. MCP/tool foundation supports at least one production-meaningful tool flow.
5. Sherpa contract compatibility checks are automated.

---

## Notes for MCP and Skills Ownership

Boundary rule:

- Local-only tools/skills remain in Repo 1 scope.
- Tenant-aware or proprietary tools/skills move to Repo 2 scope.
- Deployment, auth gateway, secret injection, scaling, and observability stay in
  Repo 3 scope.

This rule should drive extraction decisions, not folder names.

---

## Immediate Next Action

Start with Step 1 by adding `contracts/` artifacts from current
`/openapi.json`, WebSocket actions, and Sherpa payload definitions.
