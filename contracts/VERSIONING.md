# Contract Versioning Policy

## Purpose

This directory is the single source of truth for all inter-component contracts
in SpectraSherpa. Contracts define the stable interfaces between:

- **Backend HTTP API** (FastAPI routes) and **Frontend** (Vue 3 SPA)
- **Backend WebSocket endpoint** (`/ws`) and **Frontend stores** (Pinia)
- **Local client** and **Cloud server** (Sherpa advisor protocol)
- **Frontend** and **Backend config endpoint** (feature flags, mode, limits)

## Contract Types

| Contract | Source of Truth | Format | Location |
|---|---|---|---|
| HTTP API | Pydantic schemas + FastAPI routes | OpenAPI 3.1 JSON | `openapi_v1.json` |
| WebSocket Messages | `app/main.py` action handlers | Documented schema | `websocket_v1.md` |
| Sherpa Protocol | `app/schemas/sherpa.py` | Documented schema | `websocket_v1.md` (Sherpa section) |
| Client Config | `AppConfig.to_client_safe()` | Documented schema | `config_response_v1.md` |

## Version Numbering

Contracts use **major.minor** semantic versions:

- **Major** bump: Breaking change (field removed, type changed, behavior altered).
  Requires coordinated release of backend + frontend.
- **Minor** bump: Additive change (new optional field, new action type, new
  endpoint). Backend can deploy before frontend.

Current version: **v1.0** (initial freeze, 2026-02-09).

## Compatibility Policy

- The backend MUST support the current contract version and the previous minor
  version (N and N-1).
- The frontend MUST gracefully handle unknown fields (ignore, don't crash).
- WebSocket message types not recognized by the frontend MUST be silently
  ignored (not treated as errors).
- New WebSocket actions MUST use a distinct `action` string that does not
  collide with existing actions.

## Change Process

1. Propose the contract change in a PR description.
2. Update the relevant contract document in `contracts/`.
3. Add an entry to `CHANGELOG.md` in this directory.
4. Bump the version number in the contract document header.
5. Implement backend changes (must remain backward-compatible for minor bumps).
6. Implement frontend changes.
7. Update `openapi_v1.json` by running the export script (see below).

## Distribution Variants

The `openapi_v1.json` in this repository reflects the **OSS distribution**
(repo 1). The **server distribution** (spectrasherpa-server, repo 2) extends
the OSS spec with additional endpoints:

| Endpoint Group | OSS | Server |
|----------------|-----|--------|
| `/auth/me` | Yes | Yes |
| `/auth/login`, `/auth/register` | No | Yes |
| `/admin/*` | No | Yes |

When regenerating the spec, always run the export from the OSS runtime to
keep this file accurate for the open source release. The server distribution
should maintain its own `openapi_server_v1.json` in repo 2.

## Exporting the OpenAPI Spec

```bash
PYTHONPATH=src/spectra_sherpa python -c "
import json
from spectra_sherpa.app.main import app
spec = app.openapi()
with open('contracts/openapi_v1.json', 'w') as f:
    json.dump(spec, f, indent=2, default=str)
print(f'Exported {len(spec[\"paths\"])} paths')
"
```

Run this after any route or schema change to keep the frozen spec current.

## Reserved Namespaces

To prevent collisions when MCP tools and skills are added:

- WebSocket actions: `tool_*` reserved for MCP tool invocation
- WebSocket types: `tool_*` reserved for MCP tool responses
- HTTP route prefix: `/api/v1/tools/` reserved for tool endpoints
- Config features: `mcpTools`, `skills` reserved for future feature flags
