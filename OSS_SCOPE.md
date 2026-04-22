# OSS Scope — SpectraSherpa

This document defines what the open-source SpectraSherpa repository owns
and lists the extension points it exposes for external packages.

The authoritative boundary model — ownership rules, stability guarantees,
conflict resolution, and the full list of shared seams — lives in
[`docs/dev/governance.md`](docs/dev/governance.md). This file summarizes
the split from the OSS side for quick reference.

## What OSS owns

- **DAG workflow engine** — Node registry, scheduler, executor, type system
- **60+ processing nodes** — Preprocessing, PCA, PLS, MCR-ALS, classification, clustering, validation, synthesis, deployment
- **File I/O** — CSV, JDX, SPC, SPA, SPG, OPUS, MAT, Excel readers
- **Dataset management** — Experiments, versioned files, project organization
- **Model artifacts** — Train, persist, reload calibration models
- **Python/Jupyter export** — Generate standalone scripts from any workflow
- **Plugin system** — Custom nodes via drop-in Python files or packages
- **BYO chat proxy** — Single-turn HTTP proxy to any OpenAI-compatible endpoint (`CHAT_ENDPOINT_URL` + `CHAT_ENDPOINT_KEY`). No vendor SDK imports, no tools, no persistence.
- **AI Provider Protocol** — `AIServiceProvider` type surface and registry seam (`set/get/reset_sherpa_advisor`) for extension injection
- **WebSocket dispatch** — Routing `sherpa.*` topics to the registered provider (or the `DisabledAIProvider` default when none is registered)
- **WS event contract** — Published `sherpa-ws-v1.json` schema (package data)
- **Privacy controls** — Fine-grained egress permissions, deny-all default
- **Local-mode identity** — Implicit single-user actor; per-user BYOK API-key
  hashing with `hashlib.sha256` (stdlib only). OSS does not ship login,
  register, admin, profile, or password-change UX; those are managed-auth
  features owned by the commercial server.

## Extension points

OSS defines the following extension seams; a concrete implementation may
be provided by a separate package.

- `AIServiceProvider` Protocol at `contracts/ai_provider.py` —
  non-trivial LLM behavior (prompts, tool selection, conversation
  persistence, entitlement enforcement) is not part of this repo and is
  supplied by whichever extension package registers a provider.
- `AdminResolver` / user-API-key authenticator at
  `contracts/auth_resolver.py` — admin-capability decisions and
  managed user-API-key authentication. OSS has no built-in admin
  concept; when no resolver is registered, no caller is admin.
- `PublicPathProvider` at `contracts/public_path_provider.py` — gateway
  auth-bypass path list. OSS ships the core list; extensions can add
  auth routes.
- `ConfigOverlay` at `contracts/config_overlay.py` — subscription /
  demo / limits overlay fed into `/api/v1/config`.
- `/api/v1/llm/*` and `/api/v1/llm-config` route prefixes — reserved for
  extension packages; OSS itself returns 404 for these paths.
- `/api/v1/auth/*` and `/api/v1/admin/*` — managed-auth route prefixes
  served by the commercial server when installed; OSS alone does not
  expose login, register, admin CRUD, password change, or profile
  endpoints.

## Boundary enforcement

The boundary is enforced by:

1. **Python injection seams** — `contracts/*.py` Protocols and registries
   (ai_provider, ai_provider_registry, auth_resolver, key_resolver,
   public_path_provider, config_overlay, actors, demo_policy,
   auth_policy)
2. **Import-boundary check** — `scripts/check_import_boundary.py`
   refuses any `import spectrasherpa_server.*` in OSS sources
3. **WS event contract** — `sherpa-ws-v1.json` (JSON Schema)
4. **OpenAPI contract** — `openapi-llm-v1.json` (snapshot-tested)

## What OSS does NOT include

- No `import anthropic` or `import openai` anywhere in `src/`
- No LLM orchestration, prompt templates, or conversation store
- No agentic tool execution
- No vendor LLM SDK dependencies
- No `/api/v1/llm/*` route handlers (these return 404 in OSS-only builds)
- No `bcrypt`, no `PyJWT`. JWT and password primitives were deleted
  from OSS in v0.4.1 Phase 2 rather than abstracted behind a contract.
  Enterprise-mode JWT validation is performed by the commercial
  server's enforcement middleware, which stamps `request.state.authenticated`
  before OSS's gateway middleware runs; OSS's `api_key_middleware` reads
  that handoff instead of decoding tokens itself.
- No managed-auth UI source — no LoginView, RegisterView, AdminView,
  ChangePasswordDialog, or UserProfileDialog. The commercial server
  ships these as lazy-loaded frontend modules (`/ui/auth.js`,
  `/ui/admin.js`) that are dynamically imported when the corresponding
  capability is enabled. If a required server module fails to load in
  managed-auth mode, the frontend fails closed — OSS does not provide
  a managed-auth fallback.
- No `User.is_superuser` column — admin is a managed-account concept
  owned by the commercial server.

The `[sherpa]` extras group has been removed from `pyproject.toml`.
`pip install spectra-sherpa` does not install any LLM vendor SDKs.
