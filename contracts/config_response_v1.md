# Client Config Response Contract v1.0

**Endpoint:** `GET /api/v1/config`
**Contract version:** 1.0
**Last updated:** 2026-02-09

## Purpose

The config endpoint provides the frontend with runtime configuration, feature
flags, LLM provider availability, and mode-dependent limits. It is the
frontend's primary mechanism for adapting behavior to the current deployment
mode.

This endpoint is publicly readable (no auth required) so the frontend can
bootstrap before login.

## Response Shape

```json
{
  "mode": "local",
  "egress_enabled": false,
  "api_base_url": "http://localhost:8000",
  "features": {
    "apiTokenSettings": true,
    "cloudOffload": false,
    "demoMode": false,
    "agenticWorkflow": true,
    "chatAssistant": false,
    "nistDownloads": false,
    "sherpaAdvisor": false,
    "pluginSystem": true
  },
  "llms": {
    "openai": {"provider": "openai", "model": "gpt-4o", "enabled": true},
    "anthropic": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929", "enabled": false},
    "deepseek": {"provider": "deepseek", "model": "deepseek-chat", "enabled": false},
    "gemini": {"provider": "gemini", "model": "gemini-2.0-flash", "enabled": false},
    "custom_llm": {"provider": "custom_llm", "model": "custom", "enabled": false}
  },
  "limits": null
}
```

## Field Reference

### Top-Level Fields

| Field | Type | Description |
|---|---|---|
| `mode` | `"local" \| "hybrid" \| "demo"` | Current application mode |
| `egress_enabled` | bool | Whether outbound network access is enabled |
| `api_base_url` | string | Backend base URL |
| `features` | object | Feature flag map (see below) |
| `llms` | object | LLM provider availability map |
| `limits` | object \| null | Rate limits (non-null only in demo mode) |

### Feature Flags

| Flag | Type | Mode Behavior | Description |
|---|---|---|---|
| `apiTokenSettings` | bool | local/hybrid: true, demo: false | Show BYOK API key settings |
| `cloudOffload` | bool | true when execution mode is `hybrid` | Enable cloud compute offload |
| `demoMode` | bool | true only in `demo` | Enable demo-specific UI (login gate, limits) |
| `agenticWorkflow` | bool | true when LLM configured + egress enabled | Enable LLM chat assistant |
| `chatAssistant` | bool | Reserved (currently `false`) | Future chat assistant feature |
| `nistDownloads` | bool | true when egress enabled | Enable NIST WebBook downloads |
| `sherpaAdvisor` | bool | true in hybrid/demo when `SPECTRASHERPA_API_KEY` set | Enable Sherpa advisor tab |
| `pluginSystem` | bool | Always `true` | Enable plugin discovery |

### LLM Provider Entry

| Field | Type | Description |
|---|---|---|
| `provider` | string | Provider identifier (`openai`, `anthropic`, `deepseek`, `gemini`, `custom_llm`) |
| `model` | string | Default model name |
| `enabled` | bool | Whether an API key is available (env var or database) |

The `enabled` field is computed at request time by checking both environment
variables and the database `api_keys` table for the authenticated user.

### Limits (Demo Mode Only)

When `mode == "demo"`, `limits` is non-null:

| Field | Type | Default | Description |
|---|---|---|---|
| `maxExecutions` | int \| null | 100 | Max workflow executions per session |
| `maxFileSizeMB` | int | (from settings) | Max upload file size |
| `sessionExpiryHours` | int \| null | 24 | Session TTL |

When `mode != "demo"`, `limits` is `null`.

## Additional Config Endpoints

### `GET /api/v1/config/mode`

Returns effective mode (accounting for network degradation in hybrid):

```json
{
  "mode": "hybrid",
  "effective_mode": "local",
  "is_degraded": true
}
```

### `GET /api/v1/config/network-status`

Returns network health for hybrid mode:

```json
{
  "mode": "hybrid",
  "effective_mode": "hybrid",
  "is_online": true,
  "is_degraded": false,
  "network_state": {
    "spectrasherpa_reachable": true,
    "last_check": "2026-02-09T12:00:00Z",
    "consecutive_failures": 0
  }
}
```

### `GET /api/v1/config/llms`

Returns only enabled LLM providers with metadata:

```json
{
  "providers": [
    {
      "id": "openai",
      "name": "OpenAI",
      "model": "gpt-4o",
      "cost_input": 2.50,
      "cost_output": 10.00,
      "supports_streaming": true,
      "supports_vision": true
    }
  ],
  "count": 1
}
```

### `GET /api/v1/config/units`

Returns unit dropdown options for forms (concentration, pathlength,
temperature, pressure, wavenumber, measurement type, reference type).
This response is static and mode-independent.

### `GET /api/v1/config/spectrasherpa`

Returns masked Sherpa configuration:

```json
{
  "serverUrl": "https://endpoint.spectrascientific.ai/api/v1",
  "apiKey": "sk-s...4x2f",
  "configured": true,
  "source": "environment"
}
```

### `POST /api/v1/config/spectrasherpa/test`

Tests a Sherpa server connection. Blocked if egress disabled. SSRF-protected
by host allowlist.

### `GET /api/v1/config/spectrasherpa/user`

Returns current user from cloud Sherpa (if configured).

### `GET /api/v1/config/spectrasherpa/keys`

Returns available managed LLM keys from cloud Sherpa.

## Frontend TypeScript Types

The frontend counterpart of this contract is defined in
`frontend/src/types/config.ts`:

- `AppMode` — `"local" | "hybrid" | "demo"`
- `AppFeatures` — feature flag interface
- `AppLimits` — limits interface
- `AppConfig` — complete config response interface
- `LLMConfig` — per-provider LLM entry
