# 3-Repo Split: Architecture Summary

**Date:** 2026-02-09
**Version:** 1.3.3
**Status:** Complete (Steps 1-5 of refactor strategy)

---

## Overview

The SpectraSherpa monorepo has been split into three independent repositories, each with clear ownership boundaries:

| Repo | Directory | Purpose | License |
|------|-----------|---------|---------|
| **spectra-sherpa** | `Refactored/` | OSS local-first spectroscopy platform | MIT |
| **spectrasherpa-server** | `spectrasherpa-server/` | Commercial multi-user backend | Proprietary |
| **spectra-ops** | `spectra-ops/` | Deployment & operations (Docker, proxy, docs) | — |

### Dependency Graph

```
spectra-sherpa (Repo 1)          ← pip-installable, standalone
     ↑
spectrasherpa-server (Repo 2)    ← pip install spectra-sherpa[cloud]
     ↑
spectra-ops (Repo 3)             ← Docker/compose wrapping Repo 1 or 2
```

Repo 1 has **zero dependencies** on Repos 2 or 3.
Repo 2 depends on Repo 1 as a pip package.
Repo 3 is infrastructure-only — it containerizes and deploys Repo 1 or 2.

---

## Repo 1: spectra-sherpa (OSS Client)

### Stats

| Metric | Count |
|--------|-------|
| Python files (`src/spectra_sherpa/`) | 179 |
| Frontend files (`frontend/src/`) | 103 (.ts + .vue) |
| Test files (`tests/`) | 10 |
| Total source lines (approx.) | ~185,000 |

### Directory Structure

```
spectra-sherpa/
├── src/
│   └── spectra_sherpa/
│       ├── __init__.py           # _AppAliasFinder import hook
│       ├── __main__.py           # python -m spectra_sherpa
│       ├── cli.py                # `spectra-sherpa` CLI entry point
│       ├── _paths.py             # Dual-mode path resolution (dev/pip)
│       ├── app/
│       │   ├── main.py           # create_app() factory + WebSocket
│       │   ├── api/
│       │   │   ├── deps.py       # Shared dependency injection
│       │   │   └── v1/
│       │   │       ├── api.py    # build_api_router() + get_server_routers()
│       │   │       └── routes/   # 22 route modules (auth/admin removed)
│       │   ├── core/
│       │   │   ├── config.py     # Settings + AppConfig
│       │   │   ├── security.py   # JWT, passwords, egress, API key middleware
│       │   │   ├── mode_policy.py # 13 centralized mode policy functions
│       │   │   ├── startup.py    # DB init, seeds, hybrid linking
│       │   │   ├── demo_enforcement.py
│       │   │   ├── llm_registry.py
│       │   │   └── logging.py
│       │   ├── db/
│       │   │   ├── session.py    # SQLite/Postgres conditional config
│       │   │   ├── base.py       # SQLAlchemy Base
│       │   │   └── seed_*.py     # Data seeds
│       │   ├── models/           # SQLAlchemy ORM models
│       │   ├── schemas/          # Pydantic request/response models
│       │   ├── services/
│       │   │   ├── llm.py        # LLM service (multi-provider)
│       │   │   ├── spectrasherpa.py  # Hybrid cloud integration
│       │   │   ├── sherpa_advisor.py # Cloud advisor
│       │   │   ├── python_export.py  # Workflow → Python script
│       │   │   ├── dag/          # Workflow DAG engine
│       │   │   │   ├── executor.py
│       │   │   │   ├── node_base.py
│       │   │   │   ├── graph_utils.py
│       │   │   │   ├── nodes/    # Preprocessing, modeling, classification
│       │   │   │   └── serialize.py
│       │   │   ├── tools/        # MCP tool system
│       │   │   │   ├── schemas.py
│       │   │   │   ├── registry.py
│       │   │   │   ├── executor.py
│       │   │   │   └── builtin/  # 6 built-in tools
│       │   │   └── ws_handlers.py
│       │   └── lib/              # Scientific libraries
│       │       ├── spectral/     # Spectral analysis
│       │       └── blending/     # Blending algorithms
│       ├── alembic/              # DB migrations
│       └── static/               # Bundled frontend (pip installs)
├── frontend/
│   └── src/
│       ├── api/                  # HTTP client
│       ├── components/           # Vue 3 components
│       ├── stores/               # Pinia state (workflow, llm, sherpa, job)
│       ├── views/                # Page views (workflow-builder, analysis, etc.)
│       ├── utils/                # Utilities (ws.ts, plotLabels.ts)
│       └── main.ts              # Vue entry point
├── tests/                        # 10 test files, 164 passing
├── contracts/                    # Frozen API contracts (OpenAPI, WS, Sherpa)
├── docs/                         # Documentation
├── pyproject.toml               # Package: spectra-sherpa v1.3.3
└── poetry.lock
```

### Entry Points

| Entry | Path | Usage |
|-------|------|-------|
| CLI | `spectra_sherpa.cli:main` | `spectra-sherpa` command |
| Module | `spectra_sherpa.__main__` | `python -m spectra_sherpa` |
| ASGI | `spectra_sherpa.app.main:app` | Uvicorn / Gunicorn |
| Factory | `app.main.create_app()` | Programmatic / Repo 2 |

### Key Architectural Seams

These seams enable Repo 2 to extend Repo 1 without forking:

**`create_app()`** — [main.py:390-450](src/spectra_sherpa/app/main.py#L390-L450)
```python
def create_app(
    *,
    extra_routers: list[RouterMount] | None = None,
    extra_startup: list[Callable[[], Awaitable[None]]] | None = None,
    extra_shutdown: list[Callable[[], Awaitable[None]]] | None = None,
    extra_middleware: list[Callable[[FastAPI], None]] | None = None,
    include_server_routers: bool = True,
) -> FastAPI:
```

**`build_api_router()`** — [api.py:64-114](src/spectra_sherpa/app/api/v1/api.py#L64-L114)
```python
def build_api_router(
    *,
    extra_routers: list[RouterInclude] | None = None,
    include_server_routers: bool = True,
) -> APIRouter:
```

**`get_server_routers()`** — [api.py:40-61](src/spectra_sherpa/app/api/v1/api.py#L40-L61)
```python
def get_server_routers() -> list[RouterInclude]:
    # Returns [] if auth/admin modules don't exist (ImportError guard)
    # Returns [] if mode is not multi-user
```

**`_make_lifespan()`** — [main.py:160-238](src/spectra_sherpa/app/main.py#L160-L238)
```python
def _make_lifespan(
    extra_startup: list[Callable[[], Awaitable[None]]] | None = None,
    extra_shutdown: list[Callable[[], Awaitable[None]]] | None = None,
):
```

**`_AppAliasFinder`** — [__init__.py:12-108](src/spectra_sherpa/__init__.py#L12-L108)
- Import hook on `sys.meta_path` that redirects `import app.*` → `import spectra_sherpa.app.*`
- Only activates when pip-installed (not when running from source tree)
- Enables Repo 2's auth.py/admin.py to use `from app.*` imports unchanged

### What Stays in Repo 1 (and Why)

Everything except `auth.py`, `admin.py`, and `deploy/` stays:

| Module | Reason |
|--------|--------|
| `mode_policy.py` | Central abstraction — works for all modes |
| `security.py` | JWT, passwords, egress — used in all modes |
| `demo_enforcement.py` | Mode-gated (no-op in local) |
| `startup.py` | Server tasks mode-gated (no-op in local) |
| `spectrasherpa.py` | Hybrid cloud integration (optional, single-user) |
| `sherpa_advisor.py` | Cloud advisor (optional) |
| `encryption.py` | API key encryption (BYOK in local/hybrid) |
| All models | User model needed for implicit local user |
| All schemas | Token/User schemas used by multiple consumers |
| `api_keys.py` route | BYOK key management — works in all modes |
| `egress.py` route | Egress settings — works in all modes |
| Frontend | Bundled into static/ for pip installs |

---

## Repo 2: spectrasherpa-server (Commercial Backend)

### Stats

| File | Lines |
|------|-------|
| `pyproject.toml` | 26 |
| `src/spectrasherpa_server/__init__.py` | 3 |
| `src/spectrasherpa_server/app.py` | 25 |
| `src/spectrasherpa_server/routes/__init__.py` | 0 |
| `src/spectrasherpa_server/routes/auth.py` | 141 |
| `src/spectrasherpa_server/routes/admin.py` | 347 |
| `README.md` | 47 |
| **Total** | **589** |

### Directory Structure

```
spectrasherpa-server/
├── pyproject.toml                      # depends on spectra-sherpa[cloud]
├── README.md
└── src/
    └── spectrasherpa_server/
        ├── __init__.py                 # __version__ = "1.3.3"
        ├── app.py                      # create_app() with auth/admin routers
        └── routes/
            ├── __init__.py             # empty
            ├── auth.py                 # login, register, /me
            └── admin.py               # user CRUD, system LLM key management
```

### How It Works

The entire server is 25 lines of glue code in `app.py`:

```python
from app.main import create_app
from spectrasherpa_server.routes import admin, auth

app = create_app(
    extra_routers=[
        (auth.router, {"prefix": "/auth", "tags": ["auth"]}),
        (admin.router, {"prefix": "/admin", "tags": ["admin"]}),
    ],
    include_server_routers=False,
)
```

- `create_app()` builds the full FastAPI app from Repo 1
- `include_server_routers=False` tells Repo 1 not to look for its own auth/admin modules
- The two routers are injected as `extra_routers`, mounted at `/auth` and `/admin`
- `_AppAliasFinder` ensures `from app.*` imports in auth.py and admin.py resolve to Repo 1's installed package

### What auth.py Provides

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | OAuth2 password login → JWT token |
| `/auth/me` | GET | Current user from JWT |
| `/auth/register` | POST | Self-service registration (mode-gated) |

Security: constant-time password verification with dummy hash to prevent timing attacks on username enumeration.

### What admin.py Provides

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/users` | GET | List all users (paginated) |
| `/admin/users` | POST | Create user |
| `/admin/users/{id}` | PATCH | Toggle active status |
| `/admin/users/{id}` | DELETE | Delete user |
| `/admin/users/{id}/rotate-key` | POST | Generate new API key |
| `/admin/system-keys` | GET | List system LLM keys |
| `/admin/system-keys` | POST | Add/update system LLM key |
| `/admin/system-keys/{provider}` | DELETE | Remove system key |

All admin endpoints require superuser role + non-local mode.

### Imports from Repo 1

auth.py and admin.py import from these Repo 1 modules (resolved via `_AppAliasFinder`):

- `app.api.deps` — `get_session`, `get_current_user`, `invalidate_api_key_cache`
- `app.core.security` — password hashing, JWT, gateway cache invalidation
- `app.core.config` — `settings` (token expiry)
- `app.core.mode_policy` — `allows_registration()`, `allows_admin()`
- `app.core.llm_registry` — `PROVIDERS` dict
- `app.models.user` — `User` ORM model
- `app.models.api_key` — `APIKey` ORM model
- `app.models.data_egress` — `UserEgressDefaults` ORM model
- `app.schemas` — `Token`, `User`, `UserCreate`, `UserStatusUpdate`
- `app.services.encryption` — `encrypt_value()`

---

## Repo 3: spectra-ops (Deployment & Operations)

### Stats

| File | Lines |
|------|-------|
| `docker/Dockerfile.backend` | 43 |
| `docker/Dockerfile.frontend` | 23 |
| `docker/docker-compose.prod.yaml` | 86 |
| `proxy/nginx.conf` | 60 |
| `proxy/Caddyfile` | 24 |
| `docs/DIGITAL_OCEAN.md` | 434 |
| `.env.example` | 133 |
| `README.md` | 26 |
| **Total** | **829** |

### Directory Structure

```
spectra-ops/
├── README.md
├── .env.example                        # All env vars documented
├── docker/
│   ├── Dockerfile.backend              # Python 3.11 + Poetry + Gunicorn
│   ├── Dockerfile.frontend             # Node 20 build → nginx
│   └── docker-compose.prod.yaml        # 3-service stack
├── proxy/
│   ├── nginx.conf                      # Internal reverse proxy
│   └── Caddyfile                       # TLS termination + security headers
└── docs/
    └── DIGITAL_OCEAN.md                # Full production deployment guide
```

### Production Stack

```
Internet → Caddy (TLS, HSTS, CSP) → nginx (SPA, gzip) → Backend (Gunicorn/Uvicorn)
                                                       → /api → Backend
                                                       → /ws  → Backend (WebSocket)
```

**docker-compose.prod.yaml** defines three services:

| Service | Image | Ports | Description |
|---------|-------|-------|-------------|
| `backend` | Dockerfile.backend | 8000 (internal) | Gunicorn + Uvicorn, health-checked |
| `frontend` | Dockerfile.frontend | 80 (internal) | nginx serving Vue SPA |
| `caddy` | caddy:2-alpine | 80, 443 (public) | TLS termination, Let's Encrypt |

### Security Features

- Automatic Let's Encrypt TLS via Caddy
- HSTS (2 years, preload), X-Frame-Options: DENY, CSP
- Non-root container user
- 200MB upload limit matching backend MAX_FILE_SIZE_MB
- WebSocket proxy with 86400s timeout
- Rate limiting at app level (file-backed state)
- Proxy trust (TRUSTED_PROXY_CIDRS for Docker bridge)

### Environment Variables (.env.example)

134 lines covering:
- App mode (local / hybrid / demo)
- LLM providers (OpenAI, Anthropic, DeepSeek, Gemini)
- Execution mode (local / hybrid GPU offload)
- Demo settings (rate limits, session expiry, password gate)
- Security (JWT secret, API key, encryption key)
- Hybrid mode (SpectraSherpa server URL, API key)
- CORS, domain, proxy trust
- Resource limits (max spectra, memory, concurrent jobs)

---

## Deployment Modes

| Mode | Repo(s) | Auth | Database | Entry Point |
|------|---------|------|----------|-------------|
| **Local** | 1 only | Implicit user, no login | SQLite | `spectra-sherpa` CLI |
| **Hybrid** | 1 only | Implicit + optional cloud link | SQLite | `spectra-sherpa` CLI |
| **Demo** | 1 + 3 | JWT registration + login | SQLite (or Postgres) | `docker-compose up` |
| **SaaS** | 1 + 2 + 3 | Full multi-user JWT | PostgreSQL | `docker-compose up` |

### Mode Flow

```
Local:   pip install spectra-sherpa → spectra-sherpa → browser at localhost:8000
Hybrid:  Same as local + SPECTRASHERPA_SERVER_URL in .env → cloud offload
Demo:    docker-compose up → Caddy → nginx → backend (APP_MODE=demo)
SaaS:    docker-compose up (with spectrasherpa-server) → full multi-user
```

---

## Critical Implementation Details

### The ImportError Guard

When Repo 1 runs standalone (no auth.py/admin.py), the `get_server_routers()` function in [api.py:40-61](src/spectra_sherpa/app/api/v1/api.py#L40-L61) handles the missing modules gracefully:

```python
def get_server_routers() -> list[RouterInclude]:
    from app.core.mode_policy import is_multi_user
    if not is_multi_user():
        return []
    try:
        from app.api.v1.routes import admin, auth
    except ImportError:
        logger.info("Server routes unavailable in this distribution; skipping auth/admin routers")
        return []
    return [
        (auth.router, {"prefix": "/auth", "tags": ["auth"]}),
        (admin.router, {"prefix": "/admin", "tags": ["admin"]}),
    ]
```

**Critical fix applied during split:** `auth` was removed from the eager import list in [routes/__init__.py](src/spectra_sherpa/app/api/v1/routes/__init__.py). Without this fix, the entire routes package would crash on import before the ImportError guard could activate.

### The _AppAliasFinder Hook

When Repo 1 is pip-installed (e.g., by Repo 2), `import app.xxx` doesn't work because the package is installed as `spectra_sherpa`, not `app`. The `_AppAliasFinder` in [__init__.py:12-108](src/spectra_sherpa/__init__.py#L12-L108) intercepts these imports:

```
from app.core.security import verify_password
  → _AppAliasFinder intercepts "app.core.security"
  → redirects to "spectra_sherpa.app.core.security"
  → import succeeds
```

This means auth.py and admin.py work identically in both repos with **zero import changes**.

### Version Alignment

Both repos pin v1.3.3. Repo 2's `pyproject.toml` declares:

```toml
spectra-sherpa = {version = "^1.3.3", extras = ["cloud"]}
```

The `cloud` extra installs `asyncpg` (PostgreSQL) and `gunicorn` (multi-worker).

---

## Test Results (Post-Split Verification)

```
Repo 1: 164 passed, 4 failed (all pre-existing)
  Pre-existing failures:
  - test_data_loading_golden.py (ERROR — fixture issue)
  - test_experiments.py (assertion — unrelated)
  - test_gateway_user_api_key.py (auth flow — pre-existing)
  - test_modeling_nodes.py::test_pcr_node (numerical — pre-existing)

Smoke tests:
  ✓ from app.main import app           → module singleton works
  ✓ get_server_routers()               → returns [] with info log
  ✓ Repo 2 app.py imports              → creates FastAPI with auth/admin
  ✓ Repo 3 file structure              → all deploy files present
```

Zero regressions from the split.

---

## Refactor Steps Completed

| Step | Description | Status |
|------|-------------|--------|
| 1 | Freeze contracts (OpenAPI, WS, Sherpa, config) | Done |
| 2 | Mode-matrix regression tests (58 tests) | Done |
| 3 | Centralize mode policy (13 functions) | Done |
| 4 | MCP tool foundation (schemas, registry, executor, 6 tools, LLM + WS) | Done |
| 5 | Physical 3-repo split | Done |

### Files Changed in Repo 1 During Split

| File | Change |
|------|--------|
| `src/spectra_sherpa/app/api/v1/routes/__init__.py` | Removed `auth` from eager import |
| `src/spectra_sherpa/app/api/v1/routes/auth.py` | Deleted (→ Repo 2) |
| `src/spectra_sherpa/app/api/v1/routes/admin.py` | Deleted (→ Repo 2) |
| `deploy/` | Deleted (→ Repo 3) |

---

## Future Work

Per the [strategy document](docs/future/REFACTOR_3_REPO_STRATEGY.md):

- **Governance:** Semantic versioning per repo, compatibility matrix
- **CI:** Cross-repo contract tests, mode-matrix in CI, smoke deploy from Repo 3
- **Plugin SDK:** Formalize plugin interface for third-party MCP tools/skills
- **Each directory** is ready for `git init` as an independent repository
