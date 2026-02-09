# WebSocket Contract v1.2

**Endpoint:** `ws://<host>/ws`
**Contract version:** 1.2
**Last updated:** 2026-02-09

## Connection

### Authentication

Authentication requirements depend on application mode:

| Mode | Loopback (127.0.0.1) | Remote |
|---|---|---|
| `local` | No auth required | No auth required |
| `hybrid` | No auth required | JWT or API key required |
| `demo` | JWT or API key required | JWT or API key required |

**Credential delivery** (checked in order):

1. Header `Authorization: Bearer <jwt>`
2. Header `X-API-Key: <key>`
3. Query parameter `?token=<jwt>`
4. Query parameter `?api_key=<key>`

**Rejection:** If auth is required and no valid credential is provided, the
server accepts the WebSocket then immediately closes with code `1008`
(Policy Violation).

### Connection lifecycle

1. Client connects to `/ws` with optional credentials.
2. Server validates credentials (mode-dependent).
3. Server accepts connection and enters message loop.
4. Client sends JSON messages with `action` field.
5. Server responds with JSON messages with `type` field.
6. On disconnect, server cleans up subscriptions.

---

## Client-Sent Messages (Actions)

All client messages are JSON objects with a required `action` field.

### `subscribe`

Subscribe to a pub/sub channel for real-time updates (e.g., job progress).

```json
{
  "action": "subscribe",
  "channel": "jobs"
}
```

**Channel resolution:**
- `"jobs"` maps to the caller's own job channel (`jobs:<user_id>`).
- `"jobs:<user_id>"` requires superuser or matching user ID.

**Response:** `{"type": "subscribed", "channel": "<resolved_channel>"}`
**Error:** `{"type": "error", "detail": "Missing or unauthorized channel"}`

---

### `unsubscribe`

Unsubscribe from a previously subscribed channel.

```json
{
  "action": "unsubscribe",
  "channel": "jobs"
}
```

**Response:** `{"type": "unsubscribed", "channel": "<resolved_channel>"}`

---

### `llm_chat`

Send a message to the configured LLM provider. Requires egress permission
`allow_llm_context`.

```json
{
  "action": "llm_chat",
  "message": "What preprocessing should I apply to this IR spectrum?",
  "conversation_id": "conv_abc123",
  "metadata": {},
  "use_tools": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | string | Yes | User message text |
| `conversation_id` | string | No | Continue existing conversation (omit for new) |
| `metadata` | object | No | Arbitrary metadata passed to LLM service |
| `use_tools` | boolean | No | Enable MCP tool-calling loop (requires `agenticWorkflow` feature flag; default `false`) |

**Response sequence:**
1. `{"type": "llm_start", "conversation_id": "<id>"}`
2. `{"type": "llm_chunk", "conversation_id": "<id>", "chunk": "<text>"}` (repeated)
3. `{"type": "llm_done", "conversation_id": "<id>", "tool_calls": [...]}`

When `use_tools` is enabled and the LLM invokes tools, the `llm_done` message
includes a `tool_calls` array documenting each tool invocation:

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Name of the tool invoked |
| `invocation_id` | string | Tracking ID |
| `arguments` | object | Arguments passed to the tool |
| `success` | boolean | Whether the tool call succeeded |
| `result` | any | Tool return value (on success) |
| `error` | string \| null | Error message (on failure) |

When `use_tools` is `false` or the `agenticWorkflow` flag is off, `tool_calls`
is omitted and the response uses standard streaming.

**Error:** `{"type": "error", "detail": "<reason>"}`

Possible error reasons:
- `"Missing message"`
- `"LLM access is disabled for this user or mode"`
- `"LLM rate limit exceeded. Try again later."`
- `"LLM request failed. Check server logs for details."` (sanitized internal error)

---

### `sherpa_sync`

Synchronize current workflow state to the cloud Sherpa advisor. Requires
egress permission `allow_spectrasherpa_sync`. Only available when Sherpa is
configured (hybrid/demo mode + `SPECTRASHERPA_API_KEY` set).

```json
{
  "action": "sherpa_sync",
  "payload": {
    "workflow_id": 42,
    "workflow_name": "FTIR Analysis",
    "tier": "structure",
    "nodes": [
      {
        "node_id": "node_1",
        "node_type": "preprocess.smooth",
        "label": "Savitzky-Golay",
        "parameters": {"window_length": 15, "polyorder": 2},
        "result_shape": null,
        "result_statistics": null,
        "explained_variance": null
      }
    ],
    "edges": [
      {
        "from_node_id": "node_1",
        "to_node_id": "node_2",
        "from_output": "default",
        "to_input": "default"
      }
    ],
    "spectral_technique": "IR",
    "n_samples": 50,
    "n_features": 1000
  }
}
```

**Payload fields** (see `app/schemas/sherpa.py: WorkflowStateSync`):

| Field | Type | Required | Description |
|---|---|---|---|
| `workflow_id` | int | Yes | Workflow database ID |
| `workflow_name` | string | No | Human-readable name |
| `tier` | enum | No | Egress tier: `"structure"`, `"summaries"`, `"full"` (default: `"structure"`) |
| `nodes` | array | Yes | Array of `WorkflowContextNode` |
| `edges` | array | Yes | Array of `WorkflowContextEdge` |
| `spectral_technique` | string | No | `"IR"`, `"NIR"`, `"Raman"`, `"UV-Vis"` |
| `n_samples` | int | No | Number of samples in dataset |
| `n_features` | int | No | Number of spectral features |
| `raw_data` | object | No | Raw spectral data (tier `"full"` only) |

**Egress tiers control data sharing:**
- `structure`: Node types, connections, parameters only.
- `summaries`: + result shapes, statistics, explained variance, scores.
- `full`: + raw spectral arrays.

**Response:**

```json
{
  "type": "sherpa_recommendations",
  "payload": [
    {
      "suggestion_id": "sug_abc123",
      "workflow_id": 42,
      "category": "preprocessing",
      "title": "Consider baseline correction before PCA",
      "explanation": "Baseline drift in IR spectra can dominate...",
      "patch": {
        "nodes": [
          {
            "node_id": "node_new_1",
            "action": "add",
            "node_type": "preprocess.baseline",
            "label": "Baseline Correction",
            "parameters": {"method": "snip"}
          }
        ],
        "edges": [
          {
            "action": "add",
            "from_node_id": "node_1",
            "to_node_id": "node_new_1"
          }
        ]
      },
      "confidence": 0.85,
      "status": "pending",
      "created_at": "2026-02-09T12:00:00Z"
    }
  ]
}
```

**Not-configured response:**

```json
{"type": "sherpa_status", "payload": {"connected": false, "reason": "not_configured"}}
```

**Error:** `{"type": "sherpa_error", "detail": "<reason>"}`

Note: Sherpa errors use the `sherpa_error` type prefix (not `error`) so the
frontend event bus routes them to the Sherpa store.

---

### `sherpa_decide`

Report user acceptance or rejection of a Sherpa suggestion.

```json
{
  "action": "sherpa_decide",
  "payload": {
    "workflow_id": 42,
    "suggestion_id": "sug_abc123",
    "accepted": true,
    "feedback": "Applied the baseline correction, good suggestion."
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `workflow_id` | int | Yes | Workflow database ID |
| `suggestion_id` | string | Yes | Suggestion being decided |
| `accepted` | bool | Yes | Whether user applied the patch |
| `feedback` | string | No | Optional free-text feedback |

**Response:**

```json
{
  "type": "sherpa_decision_ack",
  "payload": {"delivered": true, "suggestion_id": "sug_abc123"}
}
```

---

### `sherpa_chat`

Follow-up question to the Sherpa advisor about the current workflow. Requires
egress permission `allow_spectrasherpa_sync`.

```json
{
  "action": "sherpa_chat",
  "payload": {
    "message": "Why did you recommend baseline correction?",
    "workflow_id": 42,
    "history": [
      {"role": "assistant", "content": "Consider baseline correction..."},
      {"role": "user", "content": "Why?"}
    ]
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | string | Yes | User question |
| `workflow_id` | int | No | Workflow context |
| `history` | array | No | Previous conversation turns |

**Response sequence:**
1. `{"type": "sherpa_chat_start"}`
2. `{"type": "sherpa_chat_chunk", "chunk": "<text>"}` (repeated)
3. `{"type": "sherpa_chat_done"}`

**Error:** `{"type": "sherpa_error", "detail": "<reason>"}`

---

## Server-Sent Messages (Types)

All server messages are JSON objects with a required `type` field.

### Summary Table

| Type | Source Action | Description |
|---|---|---|
| `subscribed` | `subscribe` | Channel subscription confirmed |
| `unsubscribed` | `unsubscribe` | Channel unsubscription confirmed |
| `error` | any | General error (not routed to Sherpa store) |
| `llm_start` | `llm_chat` | LLM streaming started |
| `llm_chunk` | `llm_chat` | LLM streaming text chunk |
| `llm_done` | `llm_chat` | LLM streaming complete |
| `sherpa_recommendations` | `sherpa_sync` | Sherpa suggestions received |
| `sherpa_status` | `sherpa_sync` | Sherpa availability status |
| `sherpa_error` | `sherpa_*` | Sherpa-specific error (routed to Sherpa store) |
| `sherpa_decision_ack` | `sherpa_decide` | Decision delivery confirmed |
| `sherpa_chat_start` | `sherpa_chat` | Sherpa chat streaming started |
| `sherpa_chat_chunk` | `sherpa_chat` | Sherpa chat text chunk |
| `sherpa_chat_done` | `sherpa_chat` | Sherpa chat streaming complete |
| `job_update` | pub/sub push | Background job progress (via subscription) |
| `tool_list` | `tool_list` | Available tool definitions |
| `tool_result` | `tool_invoke` | Tool execution result |
| `tool_error` | `tool_*` | Tool-specific error |

### Frontend Routing

The frontend dispatches incoming messages by type prefix:

- Types starting with `sherpa_` are forwarded to the Sherpa store via
  `window.dispatchEvent(new CustomEvent("sherpa-ws-message", {detail: msg}))`.
- Types starting with `llm_` are handled directly in the LLM store.
- Type `error` is handled in the LLM store (general errors).
- Type `job_update` is handled in the Job store (via subscription).

---

## MCP Tool Actions (v1.1, enhanced v1.2)

### `tool_list`

Discover available MCP tools, optionally filtered by category.

```json
{
  "action": "tool_list",
  "category": "spectral"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `category` | string | No | Filter by category: `spectral`, `workflow`, `data`, `system` |

**Scope filtering (v1.2):**
- Tools with `scope: "internal"` are **never** returned to WS callers (reserved for LLM function-calling only).
- Tools with `scope: "admin"` are hidden from non-superusers.
- Tools with `scope: "public"` are always visible.

**Response:**

```json
{
  "type": "tool_list",
  "payload": [
    {
      "name": "list_node_types",
      "description": "List available DAG node types",
      "category": "spectral",
      "parameters": {"type": "object", "properties": {...}},
      "scope": "public",
      "origin": "builtin",
      "requires_session": false,
      "requires_user": false,
      "requires_egress": false
    }
  ]
}
```

**Error:** `{"type": "tool_error", "detail": "<reason>"}`

---

### `tool_invoke`

Execute an MCP tool and return the result. Rate-limited per user (shares the
LLM rate limiter).

```json
{
  "action": "tool_invoke",
  "tool_name": "describe_node",
  "arguments": {"node_type": "model.pca"},
  "invocation_id": "inv_abc123"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tool_name` | string | Yes | Registered tool identifier |
| `arguments` | object | No | Arguments matching the tool's parameter schema |
| `invocation_id` | string | No | Client-provided tracking ID (auto-generated if omitted) |

**Scope enforcement (v1.2):**
- Tools with `scope: "internal"` **cannot** be invoked via `tool_invoke` (returns error).
  They are only callable by the LLM function-calling loop.
- Tools with `scope: "admin"` require superuser context.
- Arguments are validated against the tool's JSON Schema before execution.

**Response:**

```json
{
  "type": "tool_result",
  "payload": {
    "invocation_id": "inv_abc123",
    "tool_name": "describe_node",
    "success": true,
    "result": {...},
    "error": null
  }
}
```

**Error:** `{"type": "tool_error", "detail": "<reason>"}`

Possible error reasons:
- `"Missing tool_name"`
- `"Tool rate limit exceeded. Try again later."`
- `"Tool execution failed. Check server logs for details."` (sanitized internal error)

---

### Reserved (Future)

| Namespace | Direction | Purpose |
|---|---|---|
| `tool_cancel` | client action | Cancel running tool |
| `tool_progress` | server type | Streaming tool output |

---

## Built-in Tools

| Tool | Category | Description |
|---|---|---|
| `list_node_types` | spectral | List available DAG node types by category |
| `describe_node` | spectral | Detailed node type info (parameters, ports) |
| `suggest_preprocessing` | spectral | Recommend preprocessing pipeline |
| `get_workflow_summary` | workflow | Load saved workflow structure |
| `validate_workflow` | workflow | Check workflow for structural issues |
| `list_workflows` | workflow | List user's saved workflows |

Tools are also available to the LLM via function calling (OpenAI tools /
Anthropic tool_use). The `LLMService.chat_with_tools()` method handles
the multi-turn tool-calling loop transparently.

---

## Pydantic Source Models

The canonical source for all Sherpa protocol types is
`src/spectra_sherpa/app/schemas/sherpa.py`. Key models:

- `WorkflowStateSync` — sync payload (local to cloud)
- `WorkflowContextNode` — tier-aware node serialization
- `WorkflowContextEdge` — edge serialization
- `SherpaRecommendation` — suggestion from cloud
- `WorkflowPatch` / `NodePatch` / `EdgePatch` — structured diff
- `UserDecision` — acceptance/rejection
- `EgressTier` — data sharing level enum
- `SuggestionCategory` — advice category enum
- `SuggestionStatus` — suggestion lifecycle enum

The canonical source for all tool system types is
`src/spectra_sherpa/app/services/tools/schemas.py`. Key models:

- `ToolDefinition` — tool metadata and parameter schema
- `ToolInvocation` — request to invoke a tool
- `ToolResult` — tool execution result
- `ToolScope` — access scope enum (`public`, `admin`, `internal`)
- `ToolOrigin` — registration origin enum (`builtin`, `plugin`)
- `ToolCategory` — category enum (`spectral`, `workflow`, `data`, `system`)

---

## Tool Placement (Repo Boundary)

All 6 current built-in tools are **Repo 1** (local-first, no egress required):

| Tool | Category | Egress | Repo |
|------|----------|--------|------|
| `list_node_types` | spectral | No | 1 (local) |
| `describe_node` | spectral | No | 1 (local) |
| `suggest_preprocessing` | spectral | No | 1 (local) |
| `get_workflow_summary` | workflow | No | 1 (local) |
| `validate_workflow` | workflow | No | 1 (local) |
| `list_workflows` | workflow | No | 1 (local) |

**Rules:**
- Repo 2 inherits all Repo 1 tools (superset model).
- Repo 2 may register additional cloud-only tools via the plugin system or
  direct `tool_registry.register()` in its startup hooks.
- Plugin discovery runs in both repos; `plugin_context()` enforces trust
  boundaries (forced `origin=plugin`, no `scope=internal`, forced
  `requires_user=True`).
