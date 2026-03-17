# LLM Feature Integration Contract

**Every Sherpa LLM feature must follow this exact pattern across all three layers.**
Deviating from this contract (e.g., calling `/llm/chat` directly from the frontend)
bypasses entitlement enforcement, server-side prompt engineering, and template selection.

---

## Layer 1: spectra-server

### 1a. Route (`sherpa_llm.py`)

```python
class MyFeatureRequest(BaseModel):
    dataset_info: dict[str, Any] = Field(...)

@router.post("/sherpa/my-feature", response_model=LLMResponse)
async def my_feature(
    request: MyFeatureRequest,
    _ent: None = Depends(entitlement_required("my_feature")),  # entitlement gate
    engine=Depends(_require_engine),                            # engine availability
) -> Any:
    text = await engine.call_llm(MY_FEATURE_PROMPT, user_message)
    return LLMResponse(response=text)
```

Three dependencies in order: entitlement check, engine check, request validation.

### 1b. Entitlement (`entitlements.py`)

Add the capability string to **every plan** in `PLAN_ENTITLEMENTS`:

```python
"none": { "my_feature": False, ... },
"pro":  { "my_feature": True,  ... },
"team": { "my_feature": True,  ... },
"demo": { "my_feature": True,  ... },
```

### 1c. System prompt (`sherpa_engine.py`)

Define as a module-level constant. The server owns all prompts — never build prompts
on the frontend.

```python
MY_FEATURE_PROMPT = """\
You are Sherpa, a specialist in ...
"""
```

Use `engine.call_llm(prompt, message)` for single-shot, `engine.chat_with_tools_sse()`
for agentic/streaming.

---

## Layer 2: spectra-sherpa backend (OSS)

### 2a. Proxy method (`sherpa_advisor.py`)

```python
async def my_feature(self, *, dataset_info: dict[str, Any]) -> dict[str, Any]:
    """Proxy my-feature to the Sherpa server."""
    payload = await self._request_json(
        "POST", "/sherpa/my-feature",
        json_body={"dataset_info": dataset_info},
    )
    return {"response": payload.get("response", "")}
```

- Single-shot: use `_request_json()`, return dict with `"response"` key
- Streaming: use `_stream_sse()`, yield dicts
- Both raise `SubscriptionRequiredError` on 401/402/403

### 2b. WS handler (`ws_handlers.py`)

```python
async def handle_sherpa_my_feature(
    ws: WebSocket, payload: dict, user: Any, rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _sherpa_proxy_preamble(ws, user):
            return
        from spectra_sherpa.app.services.sherpa_advisor import (
            SubscriptionRequiredError, get_sherpa_advisor,
        )
        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.my_feature(dataset_info=data.get("dataset_info", {}))
        await ws.send_json({"type": "sherpa_my_feature_result", **result})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_my_feature failed: %s", exc)
        await ws.send_json({"type": "sherpa_my_feature_error", "detail": "Failed."})
```

Every handler: preamble check, try/except with SubscriptionRequiredError, generic fallback.

### 2c. Dispatcher (`main.py`)

Import the handler and add to the elif chain:

```python
from spectra_sherpa.app.services.ws_handlers import handle_sherpa_my_feature
# ...
elif action == "sherpa_my_feature":
    await handle_sherpa_my_feature(websocket, payload, ws_user, _llm_rate_limiter)
```

---

## Layer 3: spectra-sherpa frontend

### 3a. Feature flag (`types/config.ts`)

```typescript
export interface AppFeatures {
  // ...
  sherpaMyFeature?: boolean
}
```

Loaded from `/api/v1/config` at startup. Maps to server entitlement.

### 3b. WS send + listen pattern

```typescript
// Gate the feature first
const { isFeatureEnabled } = useAppConfig()
if (!isFeatureEnabled("sherpaMyFeature")) {
  // show upgrade prompt or return
  return
}

// Connect and send
const llm = useLlmStore()
await llm.connect()
const ws = llm.wsRef
if (!ws || ws.readyState !== WebSocket.OPEN) return

const result = await new Promise<string>((resolve, reject) => {
  const timeout = setTimeout(() => { cleanup(); reject(new Error("Timed out")); }, 60_000);
  const handler = (event: Event) => {
    const p = (event as CustomEvent).detail;
    if (p.type === "sherpa_my_feature_result") { cleanup(); resolve(p.response); }
    else if (p.type === "sherpa_my_feature_error") { cleanup(); reject(new Error(p.detail)); }
    else if (p.type === "sherpa_subscription_required") { cleanup(); reject(new Error("Subscription required")); }
  };
  const cleanup = () => { clearTimeout(timeout); window.removeEventListener("sherpa-ws-message", handler); };
  window.addEventListener("sherpa-ws-message", handler);
  ws.send(JSON.stringify({ action: "sherpa_my_feature", payload: { dataset_info } }));
});
```

Register listener **before** sending to avoid race conditions.

---

## Anti-patterns

| Do NOT | Why | Do instead |
|--------|-----|------------|
| `api.post("/llm/chat", { message: prompt })` | Bypasses entitlements, server prompts, template selection | Use WS `sherpa_*` action |
| Build prompts on frontend | Server owns all prompt engineering | Send raw data, let server build prompt |
| Skip `isFeatureEnabled` check | UI shows button user can't use | Gate with feature flag before action |
| Forget `SubscriptionRequiredError` handling | User gets generic error | Catch and show upgrade prompt |
| Add server endpoint without entitlement | Feature is ungated | Always add to `PLAN_ENTITLEMENTS` |

---

## Checklist for new LLM features

- [ ] Server: request schema in `sherpa_llm.py`
- [ ] Server: route with `entitlement_required()` + `_require_engine`
- [ ] Server: system prompt constant in `sherpa_engine.py`
- [ ] Server: capability in all plans in `entitlements.py`
- [ ] Backend: proxy method in `sherpa_advisor.py`
- [ ] Backend: WS handler in `ws_handlers.py`
- [ ] Backend: import + dispatch in `main.py`
- [ ] Frontend: feature flag in `AppFeatures` interface
- [ ] Frontend: WS send/listen pattern (not HTTP POST)
- [ ] Frontend: `isFeatureEnabled()` gate before showing UI
- [ ] Tests: entitlement enforcement, request validation, response contract
