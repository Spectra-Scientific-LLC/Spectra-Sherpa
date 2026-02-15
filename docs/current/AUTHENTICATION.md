# Authentication & API Key Architecture

**Version:** 2.0
**Date:** 2026-02-07
**Status:** Hybrid Mode Identity Implemented

---

## 🎯 **Overview**

The platform uses a **three-mode deployment model** designed for flexible adoption and monetization:

1. **Local Mode** (`APP_MODE=local`) — Single-user, no auth, SQLite. Students, researchers, trial users.
2. **Hybrid Mode** (`APP_MODE=hybrid`) — Local app + cloud identity via `SPECTRASHERPA_API_KEY`. Power users who want managed LLM keys, admin features, and server-linked identity without a login page.
3. **Enterprise/Cloud Mode** (`APP_MODE=enterprise`) — Multi-user JWT auth, rate-limited. Enterprise subscribers with managed infrastructure.

This architecture allows users to start free locally, upgrade to hybrid when ready for managed LLM keys and cloud identity, then migrate to full cloud for team collaboration and advanced agents.

### Deployment Mode Comparison

| Property | Local | Hybrid | Enterprise/Cloud |
|----------|-------|--------|------------|
| **Auth method** | None (implicit user) | API-key linked identity | JWT (email + password) |
| **User resolution** | First DB user | First DB user, enriched from server | JWT → user lookup |
| **Login page** | Skipped | Skipped | Required |
| **Admin features** | Hidden | Visible (if server user is admin) | Visible (if user is admin) |
| **LLM keys** | BYOK only | Managed (from server) + BYOK | Managed (from server) |
| **Data egress** | Unrestricted | Configurable (egress defaults) | Configurable |

---

## 🔑 **API Key Types**

### **1. Application Authentication Key**

**Current Implementation (Phase 1):**

| Property | Value |
|----------|-------|
| **Type** | Simple shared API key |
| **Default** | `"default-local-key"` |
| **Storage** | Backend: `.env` file as `APP_API_KEY`<br>Frontend: `localStorage` |
| **Transmission** | Auto-injected in `X-API-Key` HTTP header |
| **Validation** | Backend middleware checks header matches env var |

**Purpose:**
Prevent accidental unauthorized access on local machine. This is NOT secure authentication - just a basic barrier.

**Security Level:** ⚠️ **Low** (intentionally simple for Phase 1)

**Files:**
- Backend: [app/core/config.py](app/core/config.py) - Settings
- Backend: [app/api/v1/dependencies.py](app/api/v1/dependencies.py) - Validation
- Frontend: [src/stores/index.ts](frontend/src/stores/index.ts) - Storage
- Frontend: [src/api/client.ts](frontend/src/api/client.ts) - Injection

---

**Phase 2 Migration (Paid Cloud):**

| Property | Value |
|----------|-------|
| **Type** | JWT-based per-user authentication |
| **Storage** | Database with bcrypt password hashing |
| **Transmission** | `Authorization: Bearer <token>` header |
| **Validation** | JWT signature verification + expiration |
| **Features** | Role-based permissions, refresh tokens, OAuth integration |

**Security Level:** 🔒 **High** (industry standard)

**Migration Path:**
1. Add User model with password field
2. Implement login/register endpoints
3. Generate JWT on successful login
4. Replace API key middleware with JWT verification
5. Add role-based access control (admin, user, viewer)

---

### **2. External Service API Keys** (User-Provided, Encrypted)

**Purpose:**
Securely store third-party service credentials for:
- LLM providers (OpenAI, Anthropic, DeepSeek, local models)
- Future premium databases (SciFinder, Wiley)

**Storage Architecture:**

```
┌─────────────────────────────────────────┐
│ User Input (Settings Page)              │
│ "sk-abc123..."                          │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Backend: AES-256 Encryption              │
│ encrypt(plaintext, master_key)           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Database: api_keys table                 │
│ id | service  | encrypted_value | user_id│
│ 1  | openai   | Xu8#nF... | 1            │
└──────────────┬──────────────────────────┘
               │
               ▼ (when needed)
┌─────────────────────────────────────────┐
│ decrypt(encrypted_value, master_key)     │
│ Use for API calls                        │
└─────────────────────────────────────────┘
```

**Master Key Storage:**

Priority order:
1. **System Keyring** (Best) - OS-managed secure storage
   - macOS: Keychain
   - Windows: Credential Manager
   - Linux: Secret Service (libsecret)
2. **Environment Variable** (Fallback) - `.env` file with 600 permissions
   - Auto-generated on first run if keyring unavailable
   - `MASTER_ENCRYPTION_KEY=<random-256-bit-hex>`

**Security Level:** 🔒 **High** (AES-256 with secure key management)

**Implementation Files:**
- Backend: [app/models/api_key.py](app/models/api_key.py) - Database model
- Backend: [app/services/encryption.py](app/services/encryption.py) - AES encryption
- Frontend: Settings view - UI for CRUD operations

**Supported Services:**

| Service | Purpose | Config in UI |
|---------|---------|--------------|
| OpenAI | GPT-3.5/4 chat & embeddings | ✅ |
| Anthropic | Claude models | ✅ |
| DeepSeek | Cost-effective LLM | ✅ |
| Local (Ollama) | Self-hosted models | ✅ (endpoint URL) |
| SciFinder | Premium spectral DB | 🔜 Phase 2 |
| Wiley | Premium spectral DB | 🔜 Phase 2 |

---

## 🔗 **Hybrid Mode: API-Key Linked Identity**

In hybrid mode, the `SPECTRASHERPA_API_KEY` environment variable serves as **both** the authentication credential and the identity source. No login page is needed — the API key IS the credential.

### How It Works

```
Startup (hybrid mode):
  1. ensure_default_user()           → creates "local" user in DB (if no users exist)
  2. ensure_egress_defaults()        → creates default egress permissions
  3. link_hybrid_identity() [NEW]    → calls server GET /auth/me with API key
     Server returns:                   {id: 42, username: "alice", is_admin: true, llm_quota: 100}
  4. Update local DB user:             username="alice", is_superuser=true
  5. First HTTP request arrives      → _resolve_user() reads enriched user from DB

Frontend (hybrid mode):
  1. Router guard: skip login (no password needed — API key is the credential)
  2. initHybridUser(): call GET /api/v1/auth/me → backend returns enriched local user
  3. authStore.user populated        → admin button shows, username displays
```

### Key Design Decisions

- **API key = identity**: The `SPECTRASHERPA_API_KEY` maps to a `ClientKey` on the server, which maps to a `User`. On startup, `link_hybrid_identity()` calls server `GET /auth/me` and enriches the local DB user with the server identity.
- **No duplicate users**: `_get_or_create_local_user()` looks up users by `order_by(User.id).limit(1)` (not `username == "local"`), so username changes from identity linking don't create duplicates on restart.
- **Offline degradation**: If the server is unreachable, the last-synced identity persists in the local DB. First-ever offline startup uses the generic "local" user with `is_superuser=false`.
- **Admin route protection**: `_ensure_mutable_standard_user(user, current_user)` checks `user.id == current_user.id` (self-modification guard), not username sentinel.

### Implementation Files

| File | Purpose |
|------|---------|
| `app/services/spectrasherpa.py` | `SpectraSherpaUser` dataclass, `validate_api_key()` |
| `app/core/startup.py` | `link_hybrid_identity()` function |
| `app/main.py` | Startup sequence wiring |
| `app/api/deps.py` | `_get_or_create_local_user()` (ID-order lookup) |
| `app/api/v1/routes/admin.py` | `_ensure_mutable_standard_user()` (self-ID check) |
| `frontend/src/stores/auth.ts` | `initHybridUser()`, `isAuthenticated` computed |
| `frontend/src/router/index.ts` | Separate local/hybrid navigation guards |

### SpectraSherpaUser ↔ Server UserResponse Mapping

The local `SpectraSherpaUser` dataclass must match the server's `UserResponse` schema:

| SpectraSherpaUser (local) | UserResponse (server) |
|---------------------------|----------------------|
| `id: int` | `id: int` |
| `email: str` | `email: str` |
| `username: str` | `username: str` |
| `is_admin: bool` | `is_admin: bool` |
| `is_active: bool` | `is_active: bool` |
| `llm_quota: int` | `llm_quota: int` |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_MODE` | Yes | `local` | Deployment mode: `local`, `hybrid`, `enterprise` |
| `SPECTRASHERPA_API_KEY` | Hybrid only | — | API key from spectrasherpa-server account |
| `SPECTRASHERPA_SERVER_URL` | Hybrid only | — | URL of the spectrasherpa-server instance |

---

## 🎭 **Feature Gating by Tier**

### **Feature Comparison Table**

| Feature | Free Local | BYOK Local | Paid Cloud |
|---------|------------|------------|------------|
| **Core Scientific Features** |
| Experiment Management | ✅ Full | ✅ Full | ✅ Full |
| Spectra Preprocessing | ✅ Full | ✅ Full | ✅ Full |
| Spectra Blending (Beer's Law) | ✅ Full | ✅ Full | ✅ Full |
| Calibration Fitting | ✅ Full | ✅ Full | ✅ Full |
| Version Control | ✅ Full | ✅ Full | ✅ Full |
| Data Export (CSV/JSON/ZIP) | ✅ Full | ✅ Full | ✅ Full |
| **Free Data Sources** |
| NIST Spectra (16k compounds) | ✅ Full | ✅ Full | ✅ Full |
| HITRAN Database (bundled) | ✅ Full | ✅ Full | ✅ Full |
| EPA Spectral Library | ✅ Full | ✅ Full | ✅ Full |
| **Basic LLM Features** (User's API key) |
| LLM Chat | ❌ | ✅ User pays | ✅ Included |
| Auto-Suggest Names | ❌ | ✅ User pays | ✅ Included |
| Peak Identification | ❌ | ✅ User pays | ✅ Included |
| Code Generation | ❌ | ✅ User pays | ✅ Included |
| Report Writing | ❌ | ✅ User pays | ✅ Included |
| **Advanced LLM Agents** (Extensible Skills) |
| MCR-ALS Assistant | ❌ | ❌ | ✅ Exclusive |
| Experimental Design Agent | ❌ | ❌ | ✅ Exclusive |
| Anomaly Detection Agent | ❌ | ❌ | ✅ Exclusive |
| Literature Search Agent | ❌ | ❌ | ✅ Exclusive |
| Regulatory Compliance Agent | ❌ | ❌ | ✅ Exclusive |
| Custom Domain Agents | ❌ | ❌ | ✅ Exclusive |
| **Cloud Features** |
| Cloud Storage & Sync | ❌ | ❌ | ✅ Included |
| Team Collaboration | ❌ | ❌ | ✅ Included |
| Shared Workspaces | ❌ | ❌ | ✅ Included |
| Access Control (RBAC) | ❌ | ❌ | ✅ Included |
| Audit Logs | ❌ | ❌ | ✅ Included |
| **Premium Data** |
| Wiley Spectral DB | ❌ | ❌ | ✅ Included |
| SciFinder Integration | ❌ | ❌ | ✅ Included |
| **Support** |
| Community Support | ✅ Forum | ✅ Forum | ✅ Priority Email |
| Updates | ✅ Manual | ✅ Manual | ✅ Auto-updates |

---

## 💡 **LLM Advanced Agents Explained**

**What are Advanced Agents?**

Advanced Agents are specialized AI assistants with:
- **Domain expertise** - Trained on specific scientific workflows
- **Tool access** - Can execute code, query databases, generate reports
- **Multi-step reasoning** - Plan and execute complex tasks autonomously
- **Context awareness** - Remember conversation history and experiment state

**Example Agent: MCR-ALS Assistant**

```
User: "Analyze this blend for 3 components using MCR-ALS"

Agent:
1. Validates input data dimensions
2. Suggests initial estimates (PCA or known spectra)
3. Configures MCR-ALS parameters (constraints, max iterations)
4. Runs optimization
5. Evaluates fit quality (R², residuals)
6. Generates publication-ready plots
7. Writes interpretation summary
```

**Why Paid Cloud Only?**

Advanced Agents require:
- **High compute costs** - Long-running model inference
- **Specialized infrastructure** - Agent orchestration, tool sandboxing
- **Ongoing maintenance** - New skills, model updates, bug fixes
- **Data security** - Enterprise-grade guardrails

This justifies subscription pricing while keeping core features free.

---

## 💰 **Business Model**

### **Free Local Tier**

**Target Users:** Students, academics, small labs, hobbyists

**Value Proposition:**
- Full scientific functionality
- No limitations on data processing
- Access to free public databases (NIST, HITRAN, EPA)
- Local data ownership (never leaves your machine)

**Limitations:**
- No LLM features (manual workflow only)
- No cloud sync
- Manual software updates

**Monetization:** None (community growth, brand awareness)

**Expected User Journey:**
```
Download → Use for thesis/project → Graduate →
Recommend to employer → BYOK for work → Cloud for team
```

---

### **BYOK Local Tier** (Bring Your Own Key)

**Target Users:** Power users, researchers with grant funding, consultants

**Value Proposition:**
- Unlock all basic LLM features
- Still runs locally (data privacy)
- Pay only for what you use (LLM API costs)
- No vendor lock-in (swap providers anytime)

**Cost Structure:**
- **Software:** Free (same as Free Tier)
- **LLM API:** $10-$100/month (user pays OpenAI/Anthropic directly)
  - GPT-3.5-turbo: ~$0.002/1k tokens (~$15/month light use)
  - Claude Sonnet: ~$0.003/1k tokens (~$25/month moderate use)
  - GPT-4: ~$0.06/1k tokens (~$100/month heavy use)

**Limitations:**
- No Advanced Agents
- No cloud features
- No premium databases

**Monetization:** None directly (builds loyalty for cloud upgrade)

**Expected User Journey:**
```
Start Free → Need AI → Add OpenAI key → Use for 6-12 months →
Team grows → Need collaboration → Upgrade to Paid Cloud
```

---

### **Paid Cloud Tier** (Phase 2)

**Target Users:** Enterprise labs, pharma R&D, contract testing labs

**Value Proposition:**
- **Managed LLM** - No need to manage API keys, billing, or rate limits
- **Advanced Agents** - Specialized assistants for complex workflows
- **Team collaboration** - Shared experiments, comments, annotations
- **Premium data** - Wiley, SciFinder, proprietary databases
- **Enterprise support** - Priority email, onboarding, training
- **Compliance** - Audit logs, data retention, SOC 2 (future)

**Pricing (TBD):**
- **Starter:** $49/user/month - 5 users max, 100 GB storage
- **Professional:** $99/user/month - Unlimited users, 1 TB storage, all agents
- **Enterprise:** Custom pricing - SSO, dedicated support, SLA

**Includes:**
- LLM API usage (up to generous quota, then throttled)
- All Advanced Agents
- Cloud storage
- Automatic updates
- Priority support

**Monetization:** Direct subscription revenue

---

## 🔐 **Security Considerations**

### **Phase 1 (Current) - Local Deployment**

**Threat Model:**
- **In Scope:** Protect external API keys from local malware
- **Out of Scope:** Multi-user attacks (single user only)
- **Attack Surface:** Local file system, process memory

**Mitigations:**
1. ✅ API keys encrypted at rest (AES-256)
2. ✅ Master key in OS keyring (secure storage)
3. ✅ File permissions (600 on .env)
4. ❌ Not protected: Memory dumps, debugger access (acceptable for local use)

**Compliance:** Not applicable (single-user local deployment)

---

### **Phase 2 (Future) - Cloud Deployment**

**Threat Model:**
- **In Scope:** Multi-tenant data isolation, credential theft, API abuse
- **Attack Surface:** Public internet, database, cloud storage

**Required Mitigations:**
1. 🔜 JWT with HTTPS only
2. 🔜 bcrypt password hashing (cost factor 12)
3. 🔜 Rate limiting (per user + per IP)
4. 🔜 CSRF tokens
5. 🔜 SQL injection protection (parameterized queries)
6. 🔜 XSS protection (CSP headers)
7. 🔜 Database encryption at rest
8. 🔜 Audit logging (GDPR compliance)

**Compliance Targets:**
- GDPR (EU users)
- SOC 2 Type II (enterprise customers)
- HIPAA (if handling patient samples - future)

---

## 🚀 **Migration Path (Phase 1 → Phase 2)**

### **User Data Migration**

**Local to Cloud:**
1. User creates cloud account (email + password)
2. Installs cloud sync client
3. Selects local experiments to upload
4. Client encrypts + uploads to S3/Azure Blob
5. Local app continues working (dual mode)

**Data Preservation:**
- Local database remains intact
- Cloud becomes source of truth for shared experiments
- Conflicts resolved manually (show diff, choose version)

---

### **Authentication Migration**

**Backward Compatibility:**
1. Cloud API supports both methods:
   - `X-API-Key: <old-key>` → Read-only access (view experiments)
   - `Authorization: Bearer <jwt>` → Full access
2. Force upgrade after 6 months (disable API key auth)

**Admin Tools:**
```bash
# Generate migration report
python manage.py audit_api_keys

# Invalidate old API keys (after migration deadline)
python manage.py revoke_api_keys --before=2027-01-01
```

---

## 📋 **Implementation Checklist**

### **Phase 1 (Complete) - Local Deployment** ✅

- [x] Simple API key authentication (shared key)
- [x] External API key storage (AES-256 encrypted)
- [x] System keyring integration
- [x] Settings UI for key management
- [x] Feature gating (LLM disabled without key)
- [x] User documentation (this file)

### **Phase 1.5 (Complete) - Hybrid Mode Identity** ✅

- [x] `link_hybrid_identity()` startup function
- [x] `SpectraSherpaUser` dataclass aligned with server `UserResponse`
- [x] `_get_or_create_local_user()` ID-order lookup (survives username changes)
- [x] Admin route protection via self-ID check (not username sentinel)
- [x] Frontend `initHybridUser()` + router guard split
- [x] `isAuthenticated` computed supports token-free hybrid auth
- [x] Offline degradation (last-synced identity persists)

### **Phase 2 - Cloud Deployment (spectrasherpa-server)** ✅ Partial

- [x] User registration endpoint (`POST /auth/register`)
- [x] Login endpoint with JWT issuance (`POST /auth/login`)
- [x] JWT verification middleware
- [x] Admin dashboard for user management (basic)
- [x] API key client authentication (`X-API-Key` header)
- [ ] Refresh token rotation (`POST /auth/refresh`)
- [ ] Password reset flow (email verification)
- [ ] Role-based access control (RBAC, beyond admin/user)
- [ ] OAuth providers (Google, GitHub, ORCID)
- [ ] Audit log table (track all user actions)
- [ ] Data migration tool (local → cloud)

---

## 📚 **References**

- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)
- [NIST Digital Identity Guidelines](https://pages.nist.gov/800-63-3/)
- [PCI DSS Key Management](https://www.pcisecuritystandards.org/)

---

**Document Maintenance:**
- Review quarterly
- Update when adding new LLM providers
- Update when changing hybrid identity flow
- Last updated: 2026-02-07 (added hybrid mode identity linking)
