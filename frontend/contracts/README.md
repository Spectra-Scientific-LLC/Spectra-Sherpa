# Public API contracts (OSS-canonical)

This directory holds the **OSS-canonical** OpenAPI spec for routes that
OSS clients (the bundled Vue frontend, third-party API consumers) read.
Per the governance model, public contract surfaces are owned by the OSS
package; the commercial server validates its implementations against
what lives here.

| File | Owner | Consumer | Stability |
|------|-------|----------|-----------|
| `openapi-llm-v1.json` | `spectra-sherpa` (this repo) | `frontend/src/types/api-generated.ts` (generated); third-party API clients; commercial server conformance tests | Versioned by the `/api/v1` prefix |
| `openapi-v1.json` | Generated from OSS route and response schemas by `scripts/dump_openapi.py` | `frontend/src/types/api/v1.ts`; explicit API adapters | `/api/v1` transport projection; review schema changes at their source |

## Regenerating `api-generated.ts` from this spec

```bash
cd frontend
npm run generate:types
# → writes both src/types/api-generated.ts and src/types/api/v1.ts
npm run check:types
# → compares both projections without rewriting them
```

From the package root, `make generate` also refreshes the full public OpenAPI
snapshot and node reference tables. `make generate-check` checks all three
projections. The full snapshot is generated from the OSS app alone; private
registrations and private endpoints never belong in it.

## Server conformance

The commercial server's test suite includes a conformance check for the
LLM contract, `openapi-llm-v1.json`. If the
server diverges, either:

1. The server implementation is wrong — fix the server route, OR
2. The spec needs to evolve — regenerate the spec from the server
   (which writes back into this file), then update `api-generated.ts`
   in the same PR.

Conflicts resolve by boundary ownership (governance §6): divergences
on the public surface default to "OSS spec is canonical; server
adapts," but a coordinated spec + implementation update is fine when
the change originates on the server side.
