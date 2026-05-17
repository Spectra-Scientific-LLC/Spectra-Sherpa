# AI / LLM Integration — OSS Boundary

SpectraSherpa's AI surface is defined as an extension contract. The
OSS repo (`spectra-sherpa`, AGPL-3.0) owns only the *boundary*: type
contracts, a registry seam, a small BYO chat proxy, and the WebSocket
dispatcher that routes `sherpa_*` actions to whatever `AIServiceProvider`
has been registered. Non-trivial LLM behavior — prompts, tools,
conversation state, agentic loops, entitlements — is out of scope for
this repo and is supplied by whichever extension package registers a
concrete provider (if any).

This page describes **only the OSS-side contract**. If no provider is
registered, OSS serves `DisabledAIProvider` responses and the extension
routes 404.

---

## 1. What OSS ships

### 1a. `AIServiceProvider` Protocol — type surface only

Module: `spectra_sherpa.app.contracts.ai_provider`.

A `typing.Protocol` with the full advisor method surface (chat, peak ID,
code-gen, data-story streaming, report, conversations CRUD, etc.). OSS
makes **no behavioral promise** for these methods — it only guarantees
the *shape* of the Protocol. A registered extension provider implements
this Protocol; OSS code consumes it through the registry seam.

OSS ships exactly one concrete implementation: `DisabledAIProvider`
(same module). It returns `is_available=False`, `has_feature(...) →
False`, and raises `FeatureDisabledError` from every streaming or
tool-using method. It is the default advisor when no server is
installed.

### 1b. Registry seam

Module: `spectra_sherpa.app.contracts.ai_provider_registry`.

Three-function surface — stable across OSS minor versions:

```python
def set_sherpa_advisor(advisor: AIServiceProvider) -> None: ...
def reset_sherpa_advisor() -> None: ...
def get_sherpa_advisor() -> AIServiceProvider: ...
```

Extension packages call `set_sherpa_advisor(...)` at startup. OSS
dispatch code calls `get_sherpa_advisor()` at each request. If no one
has called `set_`, the registry returns `DisabledAIProvider`.

Breaking these three signatures breaks any registered AI provider and
requires a superseding ADR.

### 1c. Protocol exception types

Module: `spectra_sherpa.app.contracts.ai_provider_errors`.

```python
class SherpaAuthorizationError(Exception): ...
class SubscriptionRequiredError(Exception): ...
```

These are raised by an extension-side Protocol implementation and
caught by OSS's `ws_handlers.py`. They are part of the stable Protocol
contract — renaming them is a breaking change.

### 1d. Capability vocabulary

Module: `spectra_sherpa.app.contracts.capabilities`.

OSS defines the *names*; any extension config overlay supplies the
*values* at `/api/v1/config` time. Frontend reads
`config.features[CAPABILITY_NAME]` as booleans.

- OSS-gated: `chatAssistant` (enabled whenever `CHAT_ENDPOINT_URL` and
  `CHAT_ENDPOINT_KEY` are configured — see §1e).
- Extension-gated: `sherpaAdvisor`, `sherpaPeakId`, `sherpaCodeGen`,
  `sherpaWriteReport`, `sherpaAgenticTools`, `sherpaDataStory`,
  `sherpaFullContext`. All default to `false` in OSS-only builds.

### 1e. `basic_chat` — OSS-only BYO chat proxy

Module: `spectra_sherpa.app.services.basic_chat` (≤100 lines).
Route: `POST /api/v1/chat/stream` (deliberately not under
`/api/v1/llm/*`; the `llm` prefix is reserved for extension-owned
routes so the boundary is visible by URL prefix).

Configuration (env only):

- `CHAT_ENDPOINT_URL` — base URL of an OpenAI-compatible endpoint
- `CHAT_ENDPOINT_KEY` — API key sent as `Authorization: Bearer <key>`
- `CHAT_ENDPOINT_MODEL` — model ID (default `deepseek-chat`)

No vendor SDKs (no `openai`, `anthropic`, etc.). No tools. No
persistence. No agent loop. SSE shape:

```json
{"type": "chunk", "text": "..."}
{"type": "done"}
{"type": "error", "detail": "..."}
```

503 response when not configured:

```json
{
  "code": "capability_unavailable",
  "capability": "chatAssistant",
  "message": "BYO chat endpoint not configured. Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY."
}
```

### 1f. WebSocket action vocabulary + schema

- Actions: `spectra_sherpa.app.ws_actions` — `LLM_CHAT` (OSS-handled),
  plus the `SHERPA_*` action set (OSS dispatches to advisor).
- Event schema: `src/spectra_sherpa/contracts/sherpa-ws-v1.json` —
  published alongside the package. Any provider implementation must
  validate its events against this file via consumer-driven contract
  tests.

---

## 2. How OSS dispatches a `sherpa_*` WS action

```python
# services/ws_handlers.py (OSS, paraphrased)
from spectra_sherpa.app.contracts.ai_provider_registry import get_sherpa_advisor
from spectra_sherpa.app.contracts.ai_provider_errors import (
    SherpaAuthorizationError, SubscriptionRequiredError,
)

async def handle_sherpa_chat(ws, payload, user, rate_limiter):
    try:
        advisor = get_sherpa_advisor()        # extension impl or DisabledAIProvider
        async for event in advisor.chat(...): # Protocol method
            await ws.send_json(event)
    except SherpaAuthorizationError as exc:
        await ws.send_json({"type": "sherpa_error", "detail": exc.detail})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required",
                            "detail": exc.detail})
```

OSS does **not** know about prompts, tool selection, model choice,
entitlement tiers, conversation IDs, or any feature semantics. It only
knows:

1. Which WS actions exist (`ws_actions.py`).
2. How to reach the advisor (`get_sherpa_advisor()`).
3. Which Protocol errors to convert into which WS event shapes
   (per `sherpa-ws-v1.json`).

---

## 3. Frontend contract

The frontend gates every `sherpa_*` feature on `isFeatureEnabled(...)`
against a capability flag from `/api/v1/config`. When the flag is
`false` (OSS-only build, or no provider registered, or a provider
rejects the caller), the UI hides or disables the corresponding
control.

The OSS BYO chat UI is gated separately on `features.chatAssistant`.

Canonical frontend constants:

- `frontend/src/lib/sherpaWs.ts` → `SHERPA_WS_ACTION`, `SHERPA_WS_EVENT`
  (source-of-truth for the TS side of the WS vocabulary).
- `frontend/src/types/api-generated.ts` — generated from the extension
  provider's published OpenAPI contract via `openapi-typescript`.
  Regenerate with `npm run generate:types`. CI fails if this file is
  stale.

---

## 4. Implement and register your own provider

The provider seam is open: **anyone** can supply the AI behavior — an
in-house model gateway, a local model, a rules engine, a research
prototype. OSS ships none, so whatever you register *is* the advisor.
This section is a complete, generic recipe; it does not assume any
particular backend.

### 4a. Minimal provider

`AIServiceProvider` is a structural `Protocol`, so you only implement
the capabilities you choose to advertise. Advertise them through
`has_feature`; OSS and the frontend gate every `sherpa_*` action on the
matching capability flag, so methods you do not implement are simply
never called. Signal "cannot serve this" with the contract error types
from `spectra_sherpa.app.contracts.ai_provider_errors` — never a bare
`Exception`, or OSS will treat it as an unexpected backend failure.

```python
# myprovider/provider.py
from spectra_sherpa.app.contracts.ai_provider_errors import (
    SherpaAdvisorUnavailable,
)


class MyProvider:
    """A provider that enables only code generation. Everything else
    stays disabled and the UI hides it automatically."""

    @property
    def is_available(self) -> bool:
        return True

    def has_feature(self, feature: str) -> bool:
        return feature == "sherpaCodeGen"

    async def generate_code(
        self, *, task_description: str, context=None, memory_messages=None
    ) -> dict:
        # Call your model / gateway / template engine here. Keep the
        # return shape aligned with contracts/sherpa-ws-v1.json.
        code = f"# generated stub for: {task_description}\n"
        return {"code": code, "language": "python"}

    # Any capability you do NOT advertise can fail fast and generically:
    async def identify_peaks(self, **_kw) -> dict:
        raise SherpaAdvisorUnavailable("peak ID not provided by MyProvider")
```

### 4b. Register it at startup

`set_sherpa_advisor()` is process-global and idempotent; call it once
while your package imports, or from an app/startup hook:

```python
# myprovider/__init__.py
from spectra_sherpa.app.contracts.ai_provider_registry import (
    set_sherpa_advisor,
)
from .provider import MyProvider

set_sherpa_advisor(MyProvider())
```

Make it load without patching OSS by shipping a tiny separate package
and importing it where your deployment is composed (a site
`conftest`/bootstrap, a WSGI/ASGI factory, or a `[project.entry-points]`
group your launcher iterates). OSS never imports your package — the
dependency arrow points one way, into OSS.

### 4c. Stay in contract

- Stream/return shapes for `sherpa_*` events **must** validate against
  `src/spectra_sherpa/contracts/sherpa-ws-v1.json`. Add a
  consumer-driven contract test that exercises your provider and
  asserts each emitted event against that schema — the same schema OSS
  publishes, so your provider and the host can evolve independently.
- Treat the three-function registry signature and the error types as a
  stable ABI. If they ever change, OSS bumps a minor version and records
  a superseding ADR.
- You do not need OSS's permission, a fork, or any code change in this
  repo to add functionality — the seam is the whole point.

---

