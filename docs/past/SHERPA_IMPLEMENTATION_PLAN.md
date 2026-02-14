# Plan: Server-Side Sherpa Agentic Analysis

## Context

The local SpectraSherpa app already has a complete client layer for cloud Sherpa communication:
- [sherpa_advisor.py](src/spectra_sherpa/app/services/sherpa_advisor.py) — HTTP client that sends `WorkflowStateSync` and receives `SherpaRecommendation[]`
- [sherpa.py](src/spectra_sherpa/app/schemas/sherpa.py) — Pydantic models defining the protocol (tiers, patches, decisions)
- Egress permission system — privacy-first filtering before data leaves the machine

**Problem**: The spectrasherpa-server has **zero Sherpa endpoints**. It only handles auth, keys, and health. When the local app calls `POST /api/v1/sherpa/sync`, it gets a 404.

**Goal**: Build the server-side Sherpa brain — receive workflow graphs, load domain knowledge ("skills"), call an LLM via managed keys, return structured `SherpaRecommendation[]`. Scope: **suggest-only** (no auto-execution).

---

## Architecture

```
Local App                         spectrasherpa-server (DO)
─────────                         ──────────────────────
sherpa_advisor.py                  routes/sherpa.py
  POST /sherpa/sync ──────────►     receive WorkflowStateSync
  (tier-filtered)                    │
                                     ▼
                                   services/sherpa_agent.py
                                     load_skills(categories)
                                     build_prompt(workflow + skills)
                                     │
                                     ▼
                                   services/llm_provider.py
                                     resolve managed key (DB)
                                     call Anthropic/OpenAI API
                                     │
                                     ▼
                                   parse LLM response → SherpaRecommendation[]
  ◄──────────────────────────────  return JSON response
```

---

## Step 1: Create Skills Directory

**Path**: `spectrasherpa-server/skills/`

One directory per domain category. Each contains a `SKILL.md` (YAML frontmatter listing which node_types it covers + markdown domain knowledge). The agent loads relevant skills based on node types present in the workflow.

```
spectrasherpa-server/skills/
├── preprocessing/SKILL.md      # 21 nodes: baseline.*, derivative.*, normalize.*, smooth.*, preprocess.*
├── modeling/SKILL.md           # 18 nodes: model.*, analysis.peak_finding, diagnostics.*
├── classification/SKILL.md     # 6 nodes: classification.*
├── data_loading/SKILL.md       # 6 nodes: data.*
├── output/SKILL.md             # 5 nodes: output.*, stats.summary
├── workflow_design/SKILL.md    # General pipeline patterns, technique-specific workflows
├── spectral_techniques/SKILL.md # IR, NIR, Raman, UV-Vis specific guidance
└── _system/SKILL.md            # ALWAYS loaded: response JSON schema, confidence rules, suggest-only constraints
```

**SKILL.md format**:
```yaml
---
name: preprocessing
description: Spectral preprocessing operations
node_types:
  - baseline.als
  - baseline.rubberband
  - normalize.snv
  - normalize.msc
  # ... all 21 preprocessing node types
triggers:
  - any node_type in node_types appears in workflow
---

# Preprocessing Skill

## When to suggest preprocessing
[Domain knowledge...]

## Parameter guidance
[Defaults, ranges, technique-specific recommendations...]

## Common mistakes
[Anti-patterns to detect and flag...]
```

The `_system/SKILL.md` is always loaded — it defines the JSON response schema (matching `SherpaRecommendation`), confidence scoring rubric, and rules (suggest-only, no hallucinated node types, cite reasoning).

**9 SKILL.md files to create.** Content will be based on existing node docstrings/parameter definitions in `src/spectra_sherpa/app/services/dag/nodes/`.

---

## Step 2: Mirror Schemas on Server

**Create**: `spectrasherpa-server/app/schemas/sherpa.py`

Direct copy of models from local [sherpa.py](src/spectra_sherpa/app/schemas/sherpa.py):

| Model | Purpose |
|-------|---------|
| `EgressTier` | Understand data tier |
| `WorkflowContextNode/Edge` | Deserialize incoming graph |
| `WorkflowStateSync` | Request body for `/sherpa/sync` |
| `UserDecision` | Request body for `/sherpa/decide` |
| `SuggestionCategory`, `SuggestionStatus` | Enums |
| `SherpaRecommendation` | What the LLM produces |
| `WorkflowPatch`, `NodePatch`, `EdgePatch` | Structured diffs |

Plus one server-specific wrapper:
```python
class SherpaResponse(BaseModel):
    recommendations: list[SherpaRecommendation]
    model_used: str       # e.g. "claude-sonnet-4-5"
    processing_time_ms: float
```

---

## Step 3: Create LLM Provider Service

**Create**: `spectrasherpa-server/app/services/llm_provider.py`

Resolves which LLM to use from managed keys and makes the API call.

```python
class LLMProvider:
    async def complete(self, system_prompt: str, user_prompt: str, session: AsyncSession, user_id: int) -> tuple[str, str]:
        """Call best available LLM. Returns (response_text, model_name)."""
```

**Key resolution** (checked in order):
1. `ManagedLLMKey` table — active keys, prefer `provider="anthropic"`
2. Fallback to `settings.anthropic_api_key` / `settings.openai_api_key` from config

**Rate limiting**: Count `UsageLog` entries for user in last hour. If ≥ `settings.rate_limit_llm_requests_per_hour` (default 100), raise `HTTPException(429)`.

**Usage logging**: Insert `UsageLog(user_id, endpoint="sherpa/sync", provider="anthropic")` after each call.

**Dependencies to add**: `anthropic>=0.40.0`, `openai>=1.50.0`, `pyyaml>=6.0`, `python-frontmatter`

**Reuses existing models**:
- [managed_llm_key.py](spectrasherpa-server/app/models/managed_llm_key.py) — key storage with `provider`, `api_key_encrypted`, `is_active`, `rate_limit`
- [usage_log.py](spectrasherpa-server/app/models/usage_log.py) — `user_id`, `endpoint`, `provider`, `created_at`

---

## Step 4: Create Sherpa Agent Service

**Create**: `spectrasherpa-server/app/services/sherpa_agent.py`

The core brain — loads skills, builds prompts, parses LLM output.

```python
class SherpaAgent:
    def __init__(self, skills_dir: Path):
        self._skills: dict[str, SkillDefinition] = {}
        self._load_skills(skills_dir)

    def _load_skills(self, skills_dir: Path):
        """Parse SKILL.md files (YAML frontmatter + markdown body)."""

    def _select_skills(self, sync: WorkflowStateSync) -> list[SkillDefinition]:
        """Pick relevant skills based on node_types in workflow."""
        # Always include _system
        # Match node_types → skill's node_types list
        # Include workflow_design if >3 nodes
        # Include spectral_techniques if technique is specified

    def _build_prompt(self, sync: WorkflowStateSync, skills: list[SkillDefinition]) -> tuple[str, str]:
        """Return (system_prompt, user_prompt)."""
        # system = _system content + concatenated skill contents
        # user = JSON-serialized workflow state

    async def analyze(self, sync: WorkflowStateSync, llm: LLMProvider, session: AsyncSession, user_id: int) -> tuple[list[SherpaRecommendation], str]:
        """Full pipeline: select skills → prompt → LLM → parse. Returns (recommendations, model_name)."""

    def _parse_recommendations(self, llm_output: str, workflow_id: int) -> list[SherpaRecommendation]:
        """Parse LLM JSON output into typed recommendations."""
        # Validate against schema, assign uuid4 suggestion_ids, clamp confidence
```

Singleton pattern with `get_sherpa_agent()` (consistent with local app patterns).

---

## Step 5: Create Sherpa Routes

**Create**: `spectrasherpa-server/app/api/routes/sherpa.py`

Three endpoints matching [sherpa_advisor.py](src/spectra_sherpa/app/services/sherpa_advisor.py) client expectations:

| Endpoint | Method | Auth | Body | Response |
|----------|--------|------|------|----------|
| `/api/v1/sherpa/sync` | POST | `get_current_user` | `WorkflowStateSync` | `SherpaResponse` |
| `/api/v1/sherpa/decide` | POST | `get_current_user` | `UserDecision` | `{"status": "recorded"}` |
| `/api/v1/sherpa/health` | GET | `get_current_user` | — | `{"status": "ok", "skills_loaded": 8, "llm_available": true}` |

**Reuses**: [deps.py](spectrasherpa-server/app/api/deps.py) `get_current_user` dependency (authenticates via API key from local client).

---

## Step 6: Wire Up Server Startup

**Modify**: [main.py](spectrasherpa-server/app/main.py)

1. Register sherpa router: `app.include_router(sherpa.router, prefix="/api/v1")`
2. Load skills in lifespan: `get_sherpa_agent()` during startup (triggers SKILL.md parsing)

---

## Step 7: Update Dependencies

**Modify**: [pyproject.toml](spectrasherpa-server/pyproject.toml)

Add to dependencies:
```toml
"anthropic>=0.40.0",
"openai>=1.50.0",
"pyyaml>=6.0",
"python-frontmatter>=1.0.0",
```

---

## File Summary

| File | Action |
|------|--------|
| `spectrasherpa-server/skills/*/SKILL.md` (×9) | **Create** |
| `spectrasherpa-server/app/schemas/sherpa.py` | **Create** |
| `spectrasherpa-server/app/services/llm_provider.py` | **Create** |
| `spectrasherpa-server/app/services/sherpa_agent.py` | **Create** |
| `spectrasherpa-server/app/api/routes/sherpa.py` | **Create** |
| `spectrasherpa-server/app/main.py` | **Modify** (add router + lifespan) |
| `spectrasherpa-server/pyproject.toml` | **Modify** (add deps) |

**No changes needed** on the local app — `sherpa_advisor.py` already calls the right endpoints.

---

## Verification

1. **Server starts**: `cd spectrasherpa-server && python -m app.main` — no errors
2. **Skills loaded**: `GET /api/v1/sherpa/health` → `{"status": "ok", "skills_loaded": 8, "llm_available": true}`
3. **Round-trip**: Local app in hybrid mode → load file → build workflow (File Load → SNV → PCA) → trigger Sherpa sync → verify `SherpaRecommendation[]` response with valid suggestion_ids, categories, explanations
4. **Rate limiting**: >100 requests/hour → 429 response
5. **Decide endpoint**: `POST /api/v1/sherpa/decide` with `accepted=true` → 200 + UsageLog entry
6. **Egress tiers**: Send `tier=structure` → verify result summaries absent in server-received payload
