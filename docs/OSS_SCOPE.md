# OSS Distribution Scope

This document defines exactly what the open source repository
(`spectrasherpa`, repo 1) includes and what requires the server distribution
(`spectrasherpa-server`, repo 2).

## Repository Roles

| Repository | License | Contents |
|-----------|---------|----------|
| **spectrasherpa** (OSS) | AGPL-3.0 | Core app, DAG engine, nodes, frontend, MCP tools, Sherpa Engine |
| **spectrasherpa-server** | Proprietary | Multi-user auth (JWT login/register), admin panel, RBAC, quota management |
| **spectra-ops** | Proprietary | Deployment configs, Terraform, CI/CD, monitoring |

## Endpoint Matrix by Distribution

### Auth Endpoints

| Endpoint | OSS | Server | Notes |
|----------|-----|--------|-------|
| `GET /api/v1/auth/me` | Yes | Yes | Returns current user; implicit identity in local/hybrid modes |
| `POST /api/v1/auth/login` | No | Yes | OAuth2 password grant, returns JWT |
| `POST /api/v1/auth/register` | No | Yes | Create new user account |
| `GET /api/v1/admin/*` | No | Yes | User management, system admin |

### Core Endpoints (all in OSS)

| Group | Example Endpoints | Notes |
|-------|-------------------|-------|
| Health | `GET /health` | Always available |
| Experiments | `/api/v1/experiments/*` | CRUD, data upload |
| Workflows | `/api/v1/workflows/*` | Build, execute, templates |
| Projects | `/api/v1/projects/*` | Project management, versioning, scripts |
| Data | `/api/v1/data/*` | Dataset info, download |
| Deploy | `/api/v1/deploy/*` | Prediction endpoints |
| Config | `/api/v1/config` | Client feature flags, mode info |
| Tools | `/api/v1/tools/*` | MCP tool registry |
| LLM | `/api/v1/llm/*` | Sherpa Engine chat |
| WebSocket | `/ws` | Real-time actions (chat, sync, streaming) |

## Feature Matrix by Mode

| Feature | Local | Hybrid | Demo/Cloud |
|---------|-------|--------|------------|
| Auth method | Implicit (first DB user) | API-key linked | JWT (login/register) |
| Login page | Skipped | Skipped | Required |
| Multi-user | No | No | Yes |
| LLM keys | BYOK only | Managed + BYOK | Managed |
| Requires server repo | No | No | Yes |
| DAG execution | In-process | ProcessPoolExecutor | ProcessPoolExecutor |
| Data egress | Disabled by default | Configurable | Configurable |

## Auth Flow by Mode

**Local mode** — No authentication. The app creates a default user on first
start and uses it for all requests. No login page shown.

**Hybrid mode** — The client connects with an API key provisioned by the
server. On startup, `link_hybrid_identity()` calls `GET /auth/me` to sync
identity from the server. Loopback (127.0.0.1) access bypasses auth entirely.
Only the OSS repo is needed.

**Demo/Cloud mode** — Full JWT authentication. Users register and log in
through the web UI. Requires `spectrasherpa-server` for `/auth/login` and
`/auth/register` endpoints.

## OpenAPI Specifications

- **OSS spec**: `contracts/openapi_v1.json` — generated from repo 1 runtime
- **Server spec**: maintained in repo 2 as `contracts/openapi_server_v1.json`

See `contracts/VERSIONING.md` for the distribution variants table.
