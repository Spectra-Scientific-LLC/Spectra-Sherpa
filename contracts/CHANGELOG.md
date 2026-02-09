# Contract Changelog

## v1.3 (2026-02-09) - Pre-Split Hardening

### WebSocket Contract Doc
- Bumped contract version header to v1.2 (was v1.0 despite v1.2 features being implemented)
- Added `use_tools` field to `llm_chat` action schema with detailed description
- Added `tool_calls` array schema to `llm_done` response (field-level documentation)
- Added scope filtering section to `tool_list` (internal hidden, admin per-user)
- Added scope enforcement section to `tool_invoke` (internal blocked, admin requires superuser)
- Added error reasons list to `tool_invoke`
- Added `scope` and `origin` fields to `tool_list` response example
- Added Tool Placement (Repo Boundary) section — all 6 built-in tools documented as Repo 1
- Added `ToolDefinition`, `ToolInvocation`, `ToolResult`, `ToolScope`, `ToolOrigin`,
  `ToolCategory` to Pydantic Source Models section

### HTTP API
- `POST /llm/chat` now accepts `use_tools: boolean` field (mirrors WS `llm_chat`)
- `LLMChatResponse` now includes optional `tool_calls` array
- OpenAPI spec re-exported

### Test Coverage
- 11 WS MCP integration tests added (`tool_list` scope/category filtering,
  `tool_invoke` success/error/rate-limit/scope paths)
- 3 mode-matrix MCP tests (feature flag, tool availability, egress gating)

---

## v1.2 (2026-02-09) - MCP Security Hardening

### WebSocket
- `tool_list` now filters by scope: `internal` tools hidden from WS callers;
  `admin` tools hidden from non-superusers
- `tool_invoke` rate-limited (shares LLM per-user rate limiter)
- `llm_chat` accepts optional `use_tools: true` — routes to `chat_with_tools()`
  behind `agenticWorkflow` feature flag
- `llm_done` may include `tool_calls` array when tools were invoked

### Tool System
- `ToolScope` enum: `public`, `admin`, `internal` — controls discovery and execution
- Per-user egress permission via `egress_permission` field on `ToolDefinition`
- JSON Schema argument validation before handler execution (uses `jsonschema` or fallback)
- Admin scope enforcement in executor (superuser check)
- Internal scope enforcement in executor (`allow_internal` flag, default `False`)
- Plugin trust boundaries: `plugin_context()` forces `origin=plugin` during loading

### Frontend
- `llm.ts` handles `tool_list`, `tool_result`, `tool_error` message types
- `sendMessageWithTools()` action for tool-augmented chat
- `requestToolList()` action to discover available tools
- `lastToolCalls` / `availableTools` reactive state

---

## v1.1 (2026-02-09) - MCP Tool Foundation

### WebSocket
- Added `tool_list` action — discover registered MCP tools by category
- Added `tool_invoke` action — execute a tool and return result
- Added `tool_result`, `tool_list`, `tool_error` server-sent message types
- Reserved `tool_cancel` and `tool_progress` for future streaming support

### Tool System
- 6 built-in tools: `list_node_types`, `describe_node`, `suggest_preprocessing`,
  `get_workflow_summary`, `validate_workflow`, `list_workflows`
- Tool definitions export to OpenAI function-calling and Anthropic tool-use formats
- LLM function-calling integration via `LLMService.chat_with_tools()` (multi-turn loop)
- Plugin-extensible: third-party tools registered via `@register_tool` decorator

---

## v1.0 (2026-02-09) - Initial Freeze

Initial contract documentation from existing codebase at version 1.3.3.

### HTTP API
- Documented all 26 route modules under `/api/v1/`
- Froze OpenAPI spec (see `openapi_v1.json`)
- Auth and admin routes conditionally registered (non-local modes only)

### WebSocket
- Documented 6 action types: `subscribe`, `unsubscribe`, `llm_chat`,
  `sherpa_sync`, `sherpa_decide`, `sherpa_chat`
- Documented 14 server-sent message types
- Documented auth requirements per mode

### Sherpa Protocol
- Documented egress tiers: `structure`, `summaries`, `full`
- Documented recommendation, decision, and chat message schemas
- Documented workflow patch format (node/edge add/modify/remove)

### Client Config
- Documented `/api/v1/config` response shape
- Documented feature flags, LLM provider status, and mode-dependent limits
