# OSS Scope — SpectraSherpa

This document defines what the open-source SpectraSherpa repository owns
and lists the extension points it exposes for external packages.

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
- **Auth primitives** — Local users, sessions, API keys

## Extension points

OSS defines the following extension seams; a concrete implementation may
be provided by a separate package.

- `AIServiceProvider` Protocol at `contracts/ai_provider.py` —
  non-trivial LLM behavior (prompts, tool selection, conversation
  persistence, entitlement enforcement) is not part of this repo and is
  supplied by whichever extension package registers a provider.
- `/api/v1/llm/*` and `/api/v1/llm-config` route prefixes — reserved for
  extension packages; OSS itself returns 404 for these paths.

## Boundary enforcement

The boundary is mechanically enforced by:

1. **Python injection seam** — `contracts/ai_provider_registry.py` (3 functions)
2. **WS event contract** — `sherpa-ws-v1.json` (JSON Schema)
3. **OpenAPI contract** — `openapi-llm-v1.json` (snapshot-tested)

## What OSS does NOT include

- No `import anthropic` or `import openai` anywhere in `src/`
- No LLM orchestration, prompt templates, or conversation store
- No agentic tool execution
- No vendor LLM SDK dependencies
- No `/api/v1/llm/*` route handlers (these return 404 in OSS-only builds)

The `[sherpa]` extras group has been removed from `pyproject.toml`.
`pip install spectra-sherpa` does not install any LLM vendor SDKs.
