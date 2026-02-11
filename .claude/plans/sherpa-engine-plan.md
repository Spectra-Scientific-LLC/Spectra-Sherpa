# Plan: BYOK LLM + Sherpa Engine + MCP Intelligence

## Context
- BYOK LLM chat is broken in local mode (global egress check blocks all external providers)
- Sherpa cloud endpoints in Repo 2 (`hybrid_compat.py`) are **placeholders** returning empty results
- MCP tools exist (6 built-in) but aren't wired into the Sherpa intelligence pipeline
- User chose: keep cloud proxy pattern, BYOK bypasses egress, streaming text for analysis

---

## Phase A: Fix BYOK LLM Connections (local + demo)

### A1: Remove global egress gate from LLM chat methods
**File:** `src/spectra_sherpa/app/services/llm.py`

The problem: `chat()`, `stream_chat()`, `chat_with_tools()` all call `is_egress_enabled()` first, which returns `False` in local mode. The user explicitly configured a BYOK key and typed a message — that's consent.

**Change:** Remove the `is_egress_enabled()` check from the 4 LLM chat code paths (lines ~197, ~260, ~365, ~602). Keep the per-user `check_egress_permission("allow_llm_context")` check but modify it to NOT call `is_egress_enabled()` when the permission is `allow_llm_context`.

**Approach:** Add an `ignore_global_flag=True` parameter to `check_egress_permission()` calls from LLM methods. In `security.py`, when `ignore_global_flag=True`, skip the `is_egress_enabled()` call at line 445. This preserves admin-level per-user control while removing the global block for user-initiated LLM chat.

### A2: Enable `chatAssistant` feature flag
**File:** `src/spectra_sherpa/app/core/config.py` (line 332)

Change from `"chatAssistant": False` to dynamic: `True` when any LLM provider is configured (same check as `agenticWorkflow` but without egress requirement).

### A3: Update config endpoint to recalculate chatAssistant
**File:** `src/spectra_sherpa/app/api/v1/routes/config.py`

The config endpoint already recalculates `agenticWorkflow` with real LLM availability. Add same recalculation for `chatAssistant` (LLM configured = true, regardless of egress).

---

## Phase B: Build Sherpa Engine Service (Repo 1)

### B1: Add config settings
**File:** `src/spectra_sherpa/app/core/config.py`

New settings:
- `SHERPA_ENGINE_API_KEY`: Anthropic API key for Sherpa (env var)
- `SHERPA_ENGINE_MODEL`: Model name, default `claude-sonnet-4-5-20250929`

Update `sherpaAdvisor` feature flag:
- `True` when: (a) mode is hybrid/demo AND `SPECTRASHERPA_API_KEY` set (existing cloud proxy), OR (b) `SHERPA_ENGINE_API_KEY` is set (direct engine, for demo mode on DO server)

### B2: Create SherpaEngine service
**New file:** `src/spectra_sherpa/app/services/sherpa_engine.py`

A service that calls Anthropic Claude directly with workflow context and MCP tools:
- `analyze_workflow(sync: WorkflowStateSync) -> AsyncIterator[str]` — streaming analysis
- `chat(message, workflow_context, history) -> AsyncIterator[str]` — streaming follow-up
- `_build_system_prompt(context)` — domain-expert prompt with workflow context
- `_tool_calling_loop(messages, tools)` — multi-turn function-calling (reuse pattern from `llm.py`)
- Uses `anthropic.AsyncAnthropic` client directly with `SHERPA_ENGINE_API_KEY`
- Uses `tool_registry.to_anthropic_tools()` for available MCP tools

### B3: Update WS handlers for dual-path routing
**File:** `src/spectra_sherpa/app/services/ws_handlers.py`

Update `handle_sherpa_sync` and `handle_sherpa_chat`:
- If `SHERPA_ENGINE_API_KEY` is set (server has local engine): call `SherpaEngine` directly
- Else if cloud proxy is available: call `sherpa_advisor.py` (existing behavior)
- Else: send `sherpa_status` with `not_configured`

Change response format for engine path:
- `sherpa_sync` → stream analysis as `sherpa_chat_start/chunk/done` (instead of structured `sherpa_recommendations`)
- This aligns with user's choice of "streaming text"
- Keep `sherpa_recommendations` handling for legacy cloud proxy path

---

## Phase C: Real Sherpa Endpoints in Repo 2

### C1: Replace placeholder endpoints
**File:** `spectrasherpa-server/src/spectrasherpa_server/routes/hybrid_compat.py`

Replace the placeholder `sherpa_sync` and `sherpa_chat` endpoints with real implementations:
- `POST /sherpa/sync`: Parse `WorkflowStateSync`, call `SherpaEngine.analyze_workflow()`, stream response
- `POST /sherpa/chat`: Parse chat request, call `SherpaEngine.chat()`, stream response
- Both endpoints use the server's `SHERPA_ENGINE_API_KEY`

### C2: Add Anthropic dependency to Repo 2
**File:** `spectrasherpa-server/pyproject.toml`

Add `anthropic` as a dependency (if not already present via Repo 1's deps).

---

## Phase D: MCP Intelligence (Domain System Prompt + Tools)

### D1: Domain system prompt
**In `sherpa_engine.py`**

Build a rich system prompt that includes:
- Role: "You are Sherpa, a spectral analysis advisor for SpectraSherpa."
- Domain expertise: spectroscopy (IR, NIR, Raman, UV-Vis), chemometrics, preprocessing pipelines
- Current workflow context (injected from `WorkflowStateSync`): node types, parameters, data shape, technique
- Available tools and when to use them
- Guidelines: ask clarifying questions, explain reasoning, suggest concrete workflow changes

### D2: Wire MCP tools into SherpaEngine
**In `sherpa_engine.py`**

The engine's tool-calling loop:
1. Get tool definitions: `tool_registry.to_anthropic_tools()`
2. On workflow sync: Include tool specs in the Anthropic API call
3. Multi-turn loop (max 5 rounds): if Claude calls a tool, execute via `execute_tool()`, append result, call again
4. Stream final text response back to client
5. Tools available to Sherpa: `list_node_types`, `describe_node`, `suggest_preprocessing`, `validate_workflow`, `get_workflow_summary`, `list_workflows`

### D3: Frontend updates for streaming Sherpa analysis
**File:** `frontend/src/stores/sherpa.ts`

Update `handleWsMessage`:
- On `sherpa_sync`, the response now comes as `sherpa_chat_start/chunk/done` (streaming text) instead of `sherpa_recommendations`
- Add an initial system message like "Analyzing your workflow..." before streaming begins
- Keep `sherpa_recommendations` handler for backward compatibility

---

## File Change Summary

### Repo 1 (Refactored/)
| File | Change |
|------|--------|
| `app/core/security.py` | Add `ignore_global_flag` param to `check_egress_permission()` |
| `app/services/llm.py` | Remove `is_egress_enabled()` calls, use `ignore_global_flag=True` |
| `app/core/config.py` | Add `SHERPA_ENGINE_*` settings, fix `chatAssistant` flag |
| `app/api/v1/routes/config.py` | Recalculate `chatAssistant` based on real LLM availability |
| `app/services/sherpa_engine.py` | **NEW** — Direct Anthropic Claude integration with MCP tools |
| `app/services/ws_handlers.py` | Dual-path routing (engine direct vs cloud proxy) |
| `frontend/src/stores/sherpa.ts` | Handle streaming analysis from sync |

### Repo 2 (spectrasherpa-server/)
| File | Change |
|------|--------|
| `routes/hybrid_compat.py` | Replace placeholder Sherpa endpoints with real Claude-powered ones |

---

## Execution Order
1. A1 → A2 → A3 (BYOK fix — can verify immediately in local mode)
2. B1 → B2 (Engine service — core logic)
3. D1 → D2 (MCP intelligence — wired into engine)
4. B3 (WS handler routing — connects everything)
5. D3 (Frontend streaming)
6. C1 → C2 (Repo 2 endpoints — enables hybrid proxy path)

## Testing
- Local mode: Configure BYOK key → LLM chat works → verify no egress error
- Demo mode: Engine key set → Sherpa sync streams analysis → follow-up chat works
- MCP tools: Sherpa uses `suggest_preprocessing` and `describe_node` in responses
