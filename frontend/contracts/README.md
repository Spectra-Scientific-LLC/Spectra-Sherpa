# Public API contracts (OSS-canonical)

This directory holds the **OSS-canonical** OpenAPI spec for routes that
OSS clients (the bundled Vue frontend, third-party API consumers) read.
Per the governance model, public contract surfaces are owned by the OSS
package; the commercial server validates its implementations against
what lives here.

| File | Owner | Consumer | Stability |
|------|-------|----------|-----------|
| `openapi-llm-v1.json` | `spectra-sherpa` (this repo) | `frontend/src/types/api-generated.ts` (generated); third-party API clients; `spectra-server` conformance tests | Versioned by the `/api/v1` prefix |

See [governance.md](../../docs/dev/governance.md) for the full
ownership model.

## Regenerating `api-generated.ts` from this spec

```bash
cd frontend
npm run generate:types
# → writes to src/types/api-generated.ts
```

## Server conformance

The commercial server's test suite includes a snapshot check that
exports the server's live OpenAPI and diffs against this file. If the
server diverges, either:

1. The server implementation is wrong — fix the server route, OR
2. The spec needs to evolve — regenerate the spec from the server
   (which writes back into this file), then update `api-generated.ts`
   in the same PR.

Conflicts resolve by boundary ownership (governance §6): divergences
on the public surface default to "OSS spec is canonical; server
adapts," but a coordinated spec + implementation update is fine when
the change originates on the server side.
