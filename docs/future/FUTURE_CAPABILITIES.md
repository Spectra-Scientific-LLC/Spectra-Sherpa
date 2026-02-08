# Future Capabilities — SpectraSherpa Lite

Features that are **not needed for v1.0** but require **client-side preparation now**
to avoid breaking changes after release.

---

## 1. Tier Differentiation (Free Local / Sherpa Lite / Sherpa Pro)

### Concept

| Feature | Free Local | Sherpa Lite ($49/mo) | Sherpa Pro ($200/mo) |
|---------|-----------|---------------------|---------------------|
| Workflow Templates | All 10 | All 10 + priority | All + custom AI-gen |
| Model Diagnostics | Full | Full | Full + auto-interpret |
| NIST Downloads | 5/day | 50/day | Unlimited |
| LLM Chat | User keys | Managed keys | Managed + priority |
| Sherpa Advisor | No | Basic | Full + exploration |
| Execution Quota | Unlimited | 200/day | Unlimited |
| Premium Plugins | No | No | Yes |
| What-If Analysis | No | 10/day | Unlimited |
| Team/Sharing | No | No | 5 seats |
| Reproduce This Paper | No | No | Yes |

### Where Tier Lives

- **spectrasherpa-server** owns the user's tier (`SpectraSherpaUser.tier`)
- Lite client receives tier info via `/config` or token claims
- Enforcement is server-side (rate limits, feature gates)
- Client shows/hides UI based on feature flags from `to_client_safe()`

### Client-Side Prep Required Before v1.0

**`AppConfig` extension** — add an optional `tier` field:

```typescript
// types/config.ts
export interface AppConfig {
  mode: AppMode
  apiBaseUrl: string
  features: AppFeatures
  llms: Record<string, LLMConfig>
  limits?: AppLimits          // Already exists
  tier?: 'free' | 'lite' | 'pro'  // ADD: defaults to 'free' if absent
}
```

**`AppLimits` extension** — add quota fields:

```typescript
export interface AppLimits {
  maxExecutions?: number       // Already exists
  maxFileSizeMB: number        // Already exists
  sessionExpiryHours?: number  // Already exists
  nistDownloadsPerDay?: number // ADD
  whatIfPerDay?: number        // ADD
  teamSeats?: number           // ADD
}
```

**`AppFeatures` extension** — add future feature flags:

```typescript
export interface AppFeatures {
  // ... existing flags ...
  premiumPlugins?: boolean     // ADD
  whatIfAnalysis?: boolean     // ADD
  teamSharing?: boolean       // ADD
  reproducePaper?: boolean    // ADD
  autoInterpret?: boolean     // ADD: AI-powered diagnostic interpretation
}
```

**Impact**: All additions are **optional fields** (`?:`), so existing clients
continue working. The `isFeatureEnabled()` helper already returns `false` for
missing keys.

---

## 2. Team/Sharing (Sherpa Pro)

### Concept
- Pro tier includes 5 user seats within an organization
- Shared workspace: team members see shared workflows, datasets
- Owner manages seats via admin panel

### Backend Needed (spectrasherpa-server)
- `Organization` model with `owner_id`, `seat_limit`, `members[]`
- Invitation flow (email-based)
- Shared workflow visibility scoping (org-level vs private)

### Client-Side Prep Required Before v1.0

1. **`AppFeatures.teamSharing`** flag (see above) — gates entire team UI
2. **Router slot**: Reserve `/team` or `/admin/team` route (lazy-loaded)
3. **User model awareness**: The frontend `authStore.user` should tolerate
   an optional `organization` field without breaking:

```typescript
// stores/auth.ts — user shape should accept:
interface User {
  id: number
  email: string
  is_superuser: boolean
  organization?: {            // ADD: optional, absent for free/lite
    id: number
    name: string
    role: 'owner' | 'member'
  }
}
```

4. **Sidebar slot**: `Sidebar.vue` should use feature-flag gating for a
   future "Team" nav item:

```vue
<SidebarItem
  v-if="isFeatureEnabled('teamSharing')"
  icon="pi-users"
  label="Team"
  to="/team"
/>
```

**No implementation needed now** — just ensure the interfaces accept optional
fields and the feature flag pattern is in place (it is).

---

## 3. Reproduce This Paper

### Concept
- User provides a DOI or paper reference
- Sherpa Advisor reads the methods section
- Generates a complete workflow (DAG) matching the paper's protocol
- User reviews, adjusts parameters, runs on their data

### Backend Needed (spectrasherpa-server)
- Paper parsing service (DOI lookup → methods extraction)
- Workflow generation via LLM (produces `WorkflowPatch`)
- Validation against available node catalog

### Client-Side Prep Required Before v1.0

1. **`AppFeatures.reproducePaper`** flag — gates the UI entry point
2. **Sherpa protocol already supports this**: `SherpaRecommendation` carries
   a `WorkflowPatch` (add/remove/update nodes). The "reproduce" flow is
   just a recommendation with a larger patch.
3. **UI entry point**: A button in the template gallery or workspace toolbar:

```vue
<Button
  v-if="isFeatureEnabled('reproducePaper')"
  label="Reproduce a Paper"
  icon="pi pi-file"
  @click="openReproduceDialog"
/>
```

4. **Dialog component**: Not needed now. When implemented, it will be a
   modal with DOI input → loading state → workflow preview → accept/reject.
   The accept action applies the `WorkflowPatch` via existing
   `applyRecommendation()` logic.

**No new types needed** — the existing Sherpa protocol handles this.

---

## 4. Premium Plugins

### Concept
- Some plugins require a Pro tier subscription
- Plugin registry (on spectrasherpa-server) marks plugins as `premium: true`
- Lite client checks tier before loading premium plugins

### Backend Needed (spectrasherpa-server)
- Plugin metadata endpoint: `/plugins/catalog` returning availability per tier
- License validation (signed tokens or server-side check)

### Client-Side Prep Required Before v1.0

1. **`AppFeatures.premiumPlugins`** flag
2. **Plugin metadata in node registry**: The existing `NodeMetadata` could
   carry an optional `premium` field:

```python
# Already in sdk.py NodeMetadata:
class NodeMetadata(BaseModel):
    # ... existing fields ...
    premium: bool = False      # ADD: defaults to False for all current nodes
```

3. **Frontend node palette**: When rendering available nodes, gray out or
   badge premium nodes if `!isFeatureEnabled('premiumPlugins')`:

```vue
<NodeCard
  :node="node"
  :locked="node.premium && !isFeatureEnabled('premiumPlugins')"
/>
```

4. **Plugin loader already handles this**: `plugin_loader.py` uses
   best-effort loading. A premium plugin that fails license check simply
   doesn't register its nodes — no crash, no special handling needed.

---

## 5. What-If Analysis

### Concept
- User selects a node, adjusts parameters, sees preview results
- Does not persist changes until confirmed
- Rate-limited in non-Pro tiers

### Current State (80% Ready)

The backend already has:
- `TrialExecuteRequest` / `TrialExecuteResponse` in `schemas/workflow.py`
- `trial_execute` endpoint in `workflows.py`
- Runs a single node with trial parameters, returns result without persisting

### What's Missing

1. **Frontend UI**: A "What-If" button on the node config panel that opens
   a split view (current result vs trial result)
2. **Rate limiting**: The `RateLimiter` infrastructure exists but isn't
   applied to `trial_execute` yet
3. **Quota display**: Show remaining what-if executions in the UI

### Client-Side Prep Required Before v1.0

1. **`AppFeatures.whatIfAnalysis`** flag
2. **`AppLimits.whatIfPerDay`** quota field (see above)
3. **Rate limit headers**: The frontend should read `X-RateLimit-Remaining`
   from trial execute responses and display remaining quota. Pattern:

```typescript
// After trial execute API call:
const remaining = response.headers['x-ratelimit-remaining']
if (remaining !== undefined) {
  whatIfRemaining.value = parseInt(remaining)
}
```

4. **Node config panel slot**: Reserve a "Try It" / "What-If" button area
   in the node configuration sidebar, gated by feature flag.

---

## 6. Auto-Interpret Diagnostics (Sherpa Pro)

### Concept
- After running diagnostics (outliers, cross-validation, PCA), Sherpa
  automatically generates a plain-English interpretation
- Uses LLM to explain what the numbers mean for the user's specific data

### Client-Side Prep Required Before v1.0

1. **`AppFeatures.autoInterpret`** flag
2. **Diagnostics result schema**: Add an optional `interpretation` field
   to diagnostic result types:

```typescript
interface DiagnosticResult {
  // ... existing fields (scores, thresholds, etc.) ...
  interpretation?: string    // ADD: AI-generated explanation
}
```

3. **UI slot**: Below diagnostic charts/tables, show interpretation text
   when present:

```vue
<div v-if="result.interpretation" class="ai-interpretation">
  <i class="pi pi-sparkles"></i>
  {{ result.interpretation }}
</div>
```

---

## Client-Side Readiness Checklist

Summary of all TypeScript changes needed **before v1.0 release** to keep
the door open for future tiers without breaking changes:

| Change | File | Type | Risk if Skipped |
|--------|------|------|-----------------|
| Add `tier?` to `AppConfig` | `types/config.ts` | Optional field | Would need schema version bump |
| Add quota fields to `AppLimits` | `types/config.ts` | Optional fields | Would need schema version bump |
| Add 5 feature flags to `AppFeatures` | `types/config.ts` | Optional fields | Would need schema version bump |
| Accept `organization?` on user | `stores/auth.ts` | Optional field | Would break team feature |
| Read `X-RateLimit-Remaining` headers | API layer | Response handling | Quotas invisible to user |

**All changes are additive (optional fields)** — they won't affect current
behavior and cost zero runtime overhead when the fields are absent.

### What Does NOT Need to Change

- **Router**: Lazy-loaded routes can be added anytime without affecting
  existing routes
- **WebSocket protocol**: String-based action dispatch supports new actions
  without version bumps
- **EgressTier enum**: String enum, new values are additive
- **Plugin SDK**: semver policy allows additive minor releases
- **Sidebar/Topbar**: Feature-flag gating pattern is already established
- **`isFeatureEnabled()`**: Returns `false` for any unknown key

---

## Implementation Priority (When Ready)

1. **What-If Analysis** — 80% backend done, highest user value
2. **Tier Differentiation** — enables monetization, mostly server-side
3. **Premium Plugins** — simple flag on existing infrastructure
4. **Auto-Interpret** — incremental Sherpa feature
5. **Reproduce This Paper** — largest new feature, depends on Sherpa maturity
6. **Team/Sharing** — lowest short-term priority, most server-side work
