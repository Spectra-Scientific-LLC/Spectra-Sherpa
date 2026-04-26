# Governance — OSS / Commercial Boundary

This document defines the governance model for the SpectraSherpa platform: how
contracts, specs, and extension points are owned across the OSS core
(`spectra-sherpa`) and the commercial server, and how conflicts are
resolved.

This document is the authoritative public statement of the boundary model.
Commercial-side design notes may exist in private repositories, but public
OSS contributors should rely on this document rather than private ADR
references.

> **Scope of "OSS."** In this document, "OSS" means the `spectra-sherpa`
> package as installed from the public repo. It is AGPL-3.0 licensed and
> stands alone as a complete local-first workbench. The commercial server
> is an *optional* extension package.

---

## 1. Core principle — boundary ownership

Contracts are owned by the side of the boundary whose consumers see them.

- **Public contracts** — consumed by OSS clients (the OSS frontend, CLI users,
  external contributors, plugin authors, local/hybrid-standalone installs) —
  are owned by **OSS**. They live in the OSS tree; they are the stable
  surface the wider world depends on.

- **Proprietary contracts** — consumed only within the commercial server
  (managed-auth internals, subscription entitlements, admin CRUD shapes,
  deployment-key lifecycle, demo policy wiring, internal server-to-server
  interfaces) — are owned by the **server**. They are invisible to OSS and
  to the OSS frontend unless surfaced through a public contract.

- **Shared seams** — points where OSS and server meet (contracts/
  registrations, overlay fields, public extension points) — are versioned
  intentionally. Both sides validate their half. Drift is caught on the
  side whose boundary was crossed.

There is no blanket rule of "OSS always wins" or "server always wins."
Conflicts are resolved by asking *whose boundary was crossed*, and fixing the
artifact on that side. This keeps the model honest and prevents either side
from preserving mistakes by precedence alone.

---

## 2. OSS standalone invariant

The OSS slice must remain a complete, working product without the server
— but only for the unmanaged, single-user experience. Managed
authentication is a server responsibility end-to-end and is not something
OSS maintains a fallback for.

- **Local mode** (`APP_MODE=local`): implicit single user, no auth, no
  login/register/admin/profile/password UX. Full DAG platform works
  standalone. Per-user BYOK API keys are hashed with `hashlib.sha256`.
  The Topbar user menu shows only Settings and Documentation — no
  "Sign Out," "My Profile," or "Change Password" entries.
- **Hybrid with optional deployment key** (`APP_MODE=hybrid` + optional
  `SPECTRASHERPA_API_KEY`): loopback clients get implicit local identity.
  If a deployment key is set, OSS forwards server-backed calls (advisor,
  server-authored workflows) to a remote server; local DAG executes
  against OSS's `NodeRegistry`. Still no OSS managed-auth UX.
- **Managed-auth modes** (hybrid multi-user, enterprise): require the
  server. The server ships a frontend module served as a static asset
  at `/ui/auth.js` (non-API path, public via the OSS gateway's
  `is_frontend_path` bypass — avoiding a login bootstrap deadlock). OSS
  imports it dynamically at boot when `features.authUI` is set
  (deployment-level signal from the config overlay). The module
  registers `/login`, `/register` routes; contributes user-menu entries
  via the OSS `useTopbarMenu` API; and wires the server-backed methods
  of the auth store. Admin is a separate module at `/ui/admin.js`,
  fetched only **after** identity resolves and `user.capabilities.admin`
  is true on the `/auth/me` response (user-level signal, not a
  deployment feature flag). Registration UX reads `registrationEnabled`
  and `registrationRequiresCode` from `/api/v1/config` (overlay-owned
  fields). **If any required module fails to load, the frontend fails
  closed** — OSS does NOT fall back to any OSS-hosted auth view.
  JWT validation in enterprise mode is owned entirely by server's
  `EnterpriseEnforcementMiddleware`, which stamps `request.state` before
  OSS's gateway middleware runs.

The invariant is therefore: **local mode works standalone; managed modes
require the server; there is no hybrid middle ground that requires OSS
to carry managed-auth UX or OSS-issued JWT.**

Designs that break this invariant are rejected. In particular:

- OSS must not import the commercial server implementation package.
- OSS must not mirror proprietary server artifacts into the public slice.
- OSS must not have a "no-server" fallback that silently invokes server-only
  code paths. If OSS needs behavior, it ships a default implementation in OSS;
  server overrides through a registered contract.

---

## 3. What OSS owns

### 3.1 Scientific platform

- DAG engine, node registry, scheduler, executor, type system
- SherpaDataset and the adapter layer (numpy, sklearn, SpectroChemPy)
- Built-in node library (preprocessing, modeling, classification, etc.)
- File I/O (CSV, JDX, SPC, SPA, SPG, OPUS, MAT, Excel)
- Model artifact persistence (ModelStore)
- Python/Jupyter export from workflows

### 3.2 Public API surface

- All routes exposed at `/api/v1/*` that OSS ships by default
- OpenAPI spec for the public API surface: `frontend/contracts/openapi-llm-v1.json`
  is the **canonical** source; the frontend's generated TypeScript client is
  derived from it; the server validates its implementations of public-surface
  routes against it
- WebSocket event contract: `docs/contracts/sherpa-ws-v1.json`

### 3.3 Extension contracts

Located in `src/spectra_sherpa/app/contracts/`:

- `ai_provider.py`, `ai_provider_registry.py`, `ai_provider_errors.py` — AI advisor protocol
- `actors.py`, `auth_resolver.py`, `key_resolver.py` — auth/identity injection seams
- `capabilities.py` — capability vocabulary (string constants only)
- `config_overlay.py` — config overlay provider
- `demo_policy.py` — demo policy provider
- `public_path_provider.py` — gateway auth bypass list (OSS core paths;
  server may extend)

Password hashing and JWT primitives are **not** OSS contracts. Server owns
these entirely; OSS carries no `bcrypt` or `PyJWT` dependency. JWT
validation for enterprise mode happens in server middleware, which stamps
`request.state` so OSS's gateway can short-circuit.

Each contract is either a Protocol (types only, pure) or a registry module
(holds a single mutable global plus `set_*`/`get_*`/`reset_*`). Contracts
never execute proprietary behavior; they define the shape and delegate.

### 3.4 Plugin contracts

The DAG plugin system is an OSS contract. The canonical types live in
`src/spectra_sherpa/app/services/dag/node_base.py`:

- `Node` base class
- `NodeMetadata`, `NodeParameter`, `PortMetadata`, `NodePolicy`
- `@register_node` decorator, `NodeRegistry.register()`
- `validate_execute_port_contract()` — enforced at registration time
- Namespacing rule: plugins use a vendor-namespaced `node_type` (e.g.
  `vendor.my_operation`) to avoid collisions with built-ins after
  `freeze_builtins()`

Plugin packages — whether user-authored Custom nodes, third-party plugins,
or proprietary server-side plugin packages — **must** comply with this
contract. Server plugin packages appear alongside Custom and Deployment
categories in the Add Node UI because they register through the same
registry and expose the same `NodeMetadata` schema. Non-conformance is
refused at registration time; no special-case server path exists.

### 3.5 Data model (core)

- User, Project, Experiment, ExperimentFile, ExpVersion
- Workflow, WorkflowNode, WorkflowEdge, WorkflowVersion, ExecutionRun, BatchPrediction
- ModelArtifact, ProjectScript, ProjectVersion, WorkflowFolder, FolderWatch

Server may add its own tables (managed accounts, subscriptions, managed API
keys, deployment keys, conversation store). It may not modify OSS tables
outside the Alembic migration chain that the OSS package ships.

---

## 4. What the server owns

### 4.1 Proprietary domains

- Sherpa Advisor: prompts, context builder, conversation store,
  agentic tools, vendor SDK dependencies, cost attribution
- Managed authentication: registration, login, password change, admin user CRUD
- Subscription and entitlement state
- Deployment keys and tenant wiring
- Demo mode enforcement and limits
- Enterprise enforcement middleware (CORS, SQLite ban, strict security)

### 4.2 Server-only route surfaces

- `/api/v1/llm/*` (chat, peak-id, code-gen, report, data-story, conversations)
- `/api/v1/llm-config` (per-user provider configuration)
- `/api/v1/auth/*` (login, register, password, me)
- `/api/v1/admin/*` (user CRUD, deployment keys, managed keys)
- `/api/v1/config/subscription` (deployment-key scoped overlay)

These are registered via the `extra_routers` parameter of `create_app()`.
They mount at the OSS-global `/api/v1` prefix but are owned by the server.

### 4.3 Server-private contracts

Specs for server-only routes (admin, subscription entitlements, deployment
keys, managed auth internals) are maintained alongside the commercial
server and validated against server implementations. They are not
mirrored into OSS and are not part of the public API surface.

### 4.4 Proprietary node plugin packages

Server may ship proprietary plugin packages that register nodes through the
OSS plugin contract (§3.4). Those nodes:

- Appear in the Add Node UI alongside Custom, Deployment, and built-in
  categories
- Must subclass `Node`, provide `NodeMetadata`, pass
  `validate_execute_port_contract`, and use a server-namespaced `node_type`
- Can have proprietary implementations
- Are bound by the OSS plugin contract; breaking changes to the contract
  affect them the same as any other plugin

---

## 5. Shared seams

Where OSS and server must agree, the seam is made explicit and versioned.

| Seam | OSS artifact | Server responsibility |
|------|--------------|------------------------|
| AI provider | `contracts/ai_provider.py` Protocol + `contracts/ai_provider_registry.py` registry | Implements and registers at startup |
| Public path list | `contracts/public_path_provider.py` | Registers auth route paths |
| JWT validation | (none — OSS has no JWT machinery) | Enterprise middleware validates and stamps `request.state.authenticated` |
| Config overlay | `contracts/config_overlay.py` | Provides subscription/demo/limits overlay |
| Actor bootstrap | `contracts/actors.py` | May register a managed actor resolver |
| Extra key resolver | `contracts/key_resolver.py` | Resolves managed API keys |
| Extra user API-key authenticator | `contracts/auth_resolver.py` | Authenticates managed user API keys |
| Demo policy | `contracts/demo_policy.py` | Provides demo limits and wiring |
| Capability vocabulary | `contracts/capabilities.py` (strings) | Owns capability values via overlay |
| WS actions | per-app `ws_action_registry` | Registers server-owned actions |
| Public API routes | `openapi-llm-v1.json` in OSS | Implementation conforms to spec |
| WS event schema | `sherpa-ws-v1.json` in OSS | Outbound events validate against schema |
| Node plugin contract | `services/dag/node_base.py` types | Proprietary plugin packages register through it |

**Stability guarantees.** These contracts are the platform's ABI/API.
Breaking changes require a deliberate, coordinated update to both sides.
They are not changed to "match" one side unilaterally.

- Contract types (Protocols, dataclasses) follow semantic versioning at the
  OSS package level. A breaking change is a minor-version bump at minimum,
  ideally accompanied by a superseding ADR.
- Plugin-facing types in `node_base.py` are *especially* stability-sensitive:
  every change breaks every registered plugin across OSS, server, third
  parties, and user Custom nodes. Evolve deliberately.
- Public API specs are versioned by URL prefix (`/api/v1`). Breaking changes
  produce `/api/v2`.
- WS event topics are versioned in the topic name (`sherpa.v1.*`) and in the
  schema filename (`sherpa-ws-v1.json`).

---

## 6. Conflict resolution

When an OSS artifact and a server artifact disagree, the fix site is
determined by whose boundary was crossed — not by OSS precedence.

| Kind of divergence | Fix site | Rationale |
|--------------------|----------|-----------|
| Server implements a public API route differently from the OSS spec | Whichever is wrong, but the public spec is canonical — usually update the server implementation | Public spec is the contract clients rely on |
| OSS contract Protocol drift from server's registered implementation | Coordinate: decide whether the Protocol grew or the impl was wrong; both sides updated in lockstep | Shared seam — neither side owns unilaterally |
| Server-private route spec differs from server code | Update whichever is wrong; OSS is not involved | Out of scope for OSS |
| Plugin contract change in OSS breaks a proprietary server plugin | OSS evolves deliberately with a version bump; server plugin updates | OSS owns the plugin contract, but evolving it is not a free action |
| Capability flag vocabulary divergence | OSS owns the *string* (e.g., `"sherpaAdvisor"`); server owns its *value* via overlay | Already-split ownership |

The rule: **find the boundary, find the owner, fix there.** Manual
correction, not automated "OSS wins" enforcement.

---

## 7. Forbidden and allowed designs

### Rejected

- OSS imports from the commercial server implementation package
- OSS mirrors proprietary server artifacts into the public slice (e.g.,
  mirroring server's admin OpenAPI spec into OSS)
- OSS has a "fallback to server" code path that imports server modules
  dynamically when the user installs them
- OSS source grep turns up server package identifiers outside of controlled
  boundary checks or explanatory commentary

### Allowed

- Server imports from `spectra_sherpa.*` (server depends on OSS as a library)
- Server registers implementations of OSS contracts at startup
- Server ships proprietary node plugin packages that register through the
  OSS plugin contract
- Server owns its own OpenAPI/route/schema specs for server-only surfaces
- Server overrides OSS-default implementations (e.g., actor resolver,
  config overlay, key resolver, demo policy) via registered contracts
- OSS assumes its own default implementation when no server is registered
  (this is how the standalone invariant is preserved)

---

## 8. Changes to this document

This governance document is load-bearing. Changes that alter ownership
boundaries, add new seams, or revise stability guarantees should:

1. Be proposed as a PR with rationale (in the PR body and/or a new ADR
   maintained alongside the commercial server for commercial-boundary
   changes)
2. Update both this document and the related ADR text where applicable
3. Be reflected in the server-side `SERVER_SCOPE.md` companion document

Changes that clarify wording without altering ownership do not require an ADR.
