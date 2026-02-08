# Deployment Milestones Roadmap

**Created:** 2026-02-05
**Status:** Planning

---

## Deployment Tiers Overview

| Tier | Auth | Compute | LLM | Data Egress | Logs |
|------|------|---------|-----|-------------|------|
| **Local** | None; single user | All local CPU | BYOK only; keys stored locally | None by default | Local only |
| **Hybrid** | SpectraSherpa API key | Local only; agent orchestrates | BYOK + platform-managed | User-controlled checkboxes | Mirrored to SpectraSherpa |
| **Demo** | Full user management | Cloud-hosted | Platform-managed + BYOK | Managed | Cloud + local |

---

## 🟢 LOCAL - ~95% Complete

**Target:** Single-user, offline-capable spectral analysis workstation.

### What Exists ✅

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| Auth: none; single user | ✅ Done | Auto-creates "local" user, auth bypass in local mode |
| Compute: all local CPU | ✅ Done | DAG engine runs locally, no cloud calls |
| LLM: BYOK only | ✅ Done | Encrypted key storage in SQLite, 4 providers (DeepSeek, OpenAI, Anthropic, Gemini) |
| Keys stored locally | ✅ Done | Fernet-encrypted in SQLite `api_keys` table |
| No cloud dependency | ✅ Done | All compute local, NIST optional |
| Data egress: none | ✅ Done | No network calls by default |
| Logs/audit: local only | ⚠️ 90% | In-memory buffer with redaction, **not persisted to disk** |

### Remaining Work (~2-4 hours)

| Task | Effort | Priority |
|------|--------|----------|
| Add persistent local audit log file option | 1-2 hours | Medium |
| Add explicit "egress disabled" config flag | 30 min | Low |
| Verify all network calls are gated by config | 1 hour | High |

### Key Files
- Config: `app/core/config.py`
- Auth bypass: `app/api/deps.py` (`get_current_user()`)
- Encryption: `app/services/encryption.py`
- Logging: `app/core/logging.py`

---

## 🟡 HYBRID - ~60% Complete

**Target:** Local compute with cloud account sync, managed LLM keys, and advisory agent.

### What Exists ✅

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| JWT auth infrastructure | ✅ Done | `core/security.py`, 8-day token expiry |
| Multi-user database model | ✅ Done | User table with relationships |
| API key encryption | ✅ Done | Fernet-based, per-user-per-service |
| LLM BYOK support | ✅ Done | 4 providers supported |
| Cloud offload node | ✅ Done | `services/dag/nodes/cloud.py` (placeholder) |
| Mode detection | ✅ Done | `config.mode` in `local`/`hybrid`/`demo` |

### What's Missing ❌

| Requirement | Status | Notes |
|-------------|--------|-------|
| SpectraSherpa auth integration | ❌ Missing | Need OAuth2/API key exchange with SpectraSherpa |
| Multi-device sync | ❌ Missing | No workflow/settings synchronization |
| LLM managed key fetch | ❌ Missing | Can't retrieve keys from SpectraSherpa yet |
| Agent web search | ❌ Missing | LLM service exists but no web search tool |
| Data egress checkboxes | ❌ Missing | No per-data-type permission model |
| Graceful degradation | ⚠️ Partial | Mode exists, fallback logic incomplete |
| Log mirroring | ❌ Missing | Logs are local-only |

### Implementation Tasks (~2-3 weeks)

| Task | Effort | Priority | Dependencies |
|------|--------|----------|--------------|
| **SpectraSherpa Auth Service** | 3-4 days | 🔴 High | None |
| - OAuth2 client for SpectraSherpa | | | |
| - API key validation endpoint | | | |
| - User account linking | | | |
| **Data Egress Permission Model** | 2-3 days | 🔴 High | None |
| - Database model for permissions | | | |
| - Per-data-type checkboxes (spectra, models, metadata) | | | |
| - Frontend settings UI | | | |
| **LLM Managed Key Fetch** | 1-2 days | 🔴 High | SpectraSherpa Auth |
| - Fetch keys from SpectraSherpa on login | | | |
| - Cache with TTL | | | |
| - Fallback to BYOK | | | |
| **Log Mirroring** | 1-2 days | 🟡 Medium | SpectraSherpa Auth |
| - Async log shipping | | | |
| - Batch uploads | | | |
| - Offline queue | | | |
| **Web Search Tool for Agent** | 2-3 days | 🟡 Medium | None |
| - Search API integration (DuckDuckGo/Brave) | | | |
| - LLM tool definition | | | |
| - Citation formatting | | | |
| **Multi-Device Sync** | 4-5 days | 🟡 Medium | SpectraSherpa Auth |
| - Workflow sync (upload/download) | | | |
| - Settings sync | | | |
| - Conflict resolution | | | |
| **Graceful Degradation** | 1-2 days | 🟡 Medium | All above |
| - Network health check | | | |
| - Auto-switch to local mode | | | |
| - UI notification | | | |

### Critical Path
```
SpectraSherpa Auth → LLM Managed Keys → Data Egress Permissions → Log Mirroring → Sync
```

### Hybrid-Specific Behaviors

| Aspect | Behavior |
|--------|----------|
| **Authentication** | SpectraSherpa API key required |
| **LLM Keys** | Check SpectraSherpa first, then local BYOK |
| **Agent** | Advisory mode only; no external compute execution |
| **Data Egress** | Explicit user checkboxes per data type |
| **Offline** | Degrades to Local mode automatically |

---

## 🔴 DEMO - ~40% Complete

**Target:** Fully cloud-hosted SaaS deployment.

### What Exists ✅

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| All Hybrid features | ⚠️ Partial | See Hybrid section |
| Demo password config | ✅ Done | `config.demo_password` |
| Rate limit config | ✅ Done | `config.rate_limit_executions` |
| Session expiry config | ✅ Done | `config.session_expiry_hours` |
| User model | ✅ Done | Superuser flag, relationships |

### What's Missing ❌

| Requirement | Status | Notes |
|-------------|--------|-------|
| User registration UI | ❌ Missing | No frontend for signup |
| Admin dashboard | ❌ Missing | No user management UI |
| Rate limiting enforcement | ❌ Missing | Config exists, middleware doesn't |
| Session expiry middleware | ❌ Missing | Config exists, not enforced |
| Cloud deployment config | ❌ Missing | No Docker/K8s manifests |
| PostgreSQL migration | ❌ Missing | SQLite only currently |
| S3/cloud storage | ❌ Missing | Local filesystem only |
| Platform LLM key management | ❌ Missing | Admin can't provision keys |
| Cost tracking | ❌ Missing | No usage metering |

### Implementation Tasks (~4-6 weeks)

| Task | Effort | Priority | Dependencies |
|------|--------|----------|--------------|
| **Complete Hybrid Features** | 2-3 weeks | 🔴 High | See Hybrid |
| **User Registration Flow** | 3-4 days | 🔴 High | None |
| - Registration endpoint | | | |
| - Email verification (optional) | | | |
| - Frontend signup page | | | |
| **Admin Dashboard** | 4-5 days | 🔴 High | User Registration |
| - User list/search | | | |
| - User enable/disable | | | |
| - Usage statistics | | | |
| **Rate Limiting Middleware** | 2-3 days | 🔴 High | None |
| - Per-user rate tracking | | | |
| - Endpoint-specific limits | | | |
| - 429 response handling | | | |
| **Session Expiry Middleware** | 1-2 days | 🔴 High | None |
| - Token refresh flow | | | |
| - Auto-logout on expiry | | | |
| **Cloud Deployment** | 3-4 days | 🔴 High | PostgreSQL |
| - Dockerfile optimization | | | |
| - docker-compose.yml for prod | | | |
| - Kubernetes manifests (optional) | | | |
| - CI/CD pipeline | | | |
| **PostgreSQL Migration** | 2-3 days | 🔴 High | None |
| - Alembic migration scripts | | | |
| - Connection pool config | | | |
| - Test with existing data | | | |
| **S3/Cloud Storage** | 3-4 days | 🟡 Medium | Cloud Deployment |
| - Abstract storage interface | | | |
| - S3 implementation | | | |
| - Migration tooling | | | |
| **Platform LLM Key Management** | 2-3 days | 🟡 Medium | Admin Dashboard |
| - Admin key provisioning | | | |
| - Per-user key assignment | | | |
| - Usage tracking | | | |
| **Cost/Usage Tracking** | 3-4 days | 🟡 Medium | All above |
| - LLM token counting | | | |
| - Compute time tracking | | | |
| - Storage usage | | | |
| - Dashboard display | | | |

### Critical Path
```
Hybrid Complete → PostgreSQL → Cloud Deployment → User Registration → Admin Dashboard → Rate Limiting
```

---

## Summary

| Milestone | Current | Effort | Target Date |
|-----------|---------|--------|-------------|
| **Local** | 95% ✅ | 2-4 hours | This week |
| **Hybrid** | 60% 🟡 | 2-3 weeks | End of February |
| **Demo** | 40% 🔴 | 4-6 weeks | Mid-March |

### Recommended Sequence

1. **This Week:** Finish Local (persistent logs, egress flag)
2. **Week 2-3:** SpectraSherpa Auth + Data Egress Permissions
3. **Week 3-4:** LLM Managed Keys + Log Mirroring + Web Search
4. **Week 4-5:** Multi-Device Sync + Graceful Degradation
5. **Week 5-6:** PostgreSQL + Cloud Deployment
6. **Week 6-8:** User Management + Admin Dashboard + Rate Limiting

---

## Architecture Notes

### SpectraSherpa Integration Points

```
┌─────────────────┐     ┌─────────────────┐
│  Local App      │     │  SpectraSherpa  │
│  (This Repo)    │────▶│  Cloud Service  │
└─────────────────┘     └─────────────────┘
        │                       │
        │  • Auth (API key)     │
        │  • LLM keys (managed) │
        │  • Log mirroring      │
        │  • Workflow sync      │
        │  • Settings sync      │
        └───────────────────────┘
```

### Data Egress Permission Model (Proposed)

```python
class DataEgressPermission(Base):
    user_id: int
    data_type: str  # "spectra", "models", "metadata", "workflows"
    allowed: bool
    destination: str  # "spectrasherpa", "llm", "export"
    created_at: datetime
    updated_at: datetime
```

### Graceful Degradation Flow

```
Hybrid Mode
    │
    ├─ Check SpectraSherpa connectivity
    │   │
    │   ├─ Connected → Full Hybrid features
    │   │
    │   └─ Disconnected → Degrade to Local
    │       │
    │       ├─ Use cached LLM keys (if available)
    │       ├─ Queue logs for later sync
    │       ├─ Show "Offline Mode" banner
    │       └─ Disable cloud-dependent features
    │
    └─ Retry connection every 60s
```

---

**Next Action:** Complete Local tier this week, then begin SpectraSherpa Auth integration.
