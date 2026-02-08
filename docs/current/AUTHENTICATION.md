# Authentication & API Key Architecture

**Version:** 1.0
**Date:** 2026-01-03
**Status:** Phase 1 Implementation

---

## 🎯 **Overview**

The platform uses a **three-tier deployment model** designed for flexible adoption and monetization:

1. **Free Local Tier** - Students, researchers, trial users (fully functional core features)
2. **BYOK Local Tier** - Power users with their own LLM API budgets (unlock AI features)
3. **Paid Cloud Tier** - Enterprise subscribers with managed infrastructure (Phase 2)

This architecture allows users to start free, upgrade to BYOK when ready for AI features, then migrate to cloud when they need team collaboration and advanced agents.

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

### **Phase 1 (Current) - Local Deployment** ✅

- [x] Simple API key authentication (shared key)
- [x] External API key storage (AES-256 encrypted)
- [x] System keyring integration
- [x] Settings UI for key management
- [x] Feature gating (LLM disabled without key)
- [ ] User documentation (this file)

### **Phase 2 - Cloud Deployment** 🔜

- [ ] User registration endpoint (`POST /auth/register`)
- [ ] Login endpoint with JWT issuance (`POST /auth/login`)
- [ ] Refresh token rotation (`POST /auth/refresh`)
- [ ] Password reset flow (email verification)
- [ ] JWT verification middleware
- [ ] Role-based access control (RBAC)
- [ ] OAuth providers (Google, GitHub, ORCID)
- [ ] Admin dashboard for user management
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
- Update when launching Phase 2
