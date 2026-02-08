# Manual QA Test Procedure — SpectraSherpa v1.3

**Scope**: Local, Hybrid (with spectrasherpa-server on Digital Ocean), Demo
**Estimated total time**: ~2.5 hours
**Prerequisites**: Python 3.11+, Docker, `jq`, a WebSocket client (`websocat` or browser console)

## Conventions

- `$BASE` = backend base URL (e.g., `http://localhost:8000` for local)
- `$TOKEN` = JWT Bearer token from login
- `$API_KEY` = user API key from admin rotate-key
- **PASS** = described response received within 10s, no server tracebacks
- `[UNIVERSAL]` = all modes; `[LOCAL-ONLY]`, `[HYBRID-ONLY]`, `[DEMO-ONLY]` = mode-specific
- `[EXPECTED FAILURE]` = known gap documented in CURRENT_CAPABILITIES.md

---

## Phase 1 — Local Mode (~45 min)

### 1.1 Setup

```bash
cd /Users/fe2val/Documents/Spectra\ Scientific/Component_code/Refactored

# Optional: clean slate
# rm -f ~/.spectra_sherpa/spectra_platform.db

spectra-sherpa --no-browser --port 8000
```

**Verify in console**:
- `Starting SpectraSherpa v<version>` appears
- No `SECURITY ERROR`
- `Using default SECRET_KEY in local mode` warning is OK
- Database tables created (Alembic/init_db log lines)
- `No plugins found` or `Loaded N plugin(s) total`

### 1.2 Smoke Tests (Local)

| # | Test | Command | PASS Criteria |
|---|------|---------|---------------|
| L-S1 | Health | `curl $BASE/api/v1/health` | `{"status":"ok"}` |
| L-S2 | Config | `curl -s $BASE/api/v1/config \| jq .` | `mode:"local"`, `egress_enabled:false`, `features.demoMode:false` |
| L-S3 | No auth | `curl $BASE/api/v1/experiments` | 200 (not 401) |
| L-S4 | Auth routes absent | `curl -X POST $BASE/api/v1/auth/login` | 404 or 405 |
| L-S5 | Admin routes absent | `curl $BASE/api/v1/admin/users` | 404 |
| L-S6 | Create experiment | `curl -X POST $BASE/api/v1/experiments -H "Content-Type: application/json" -d '{"name":"QA","description":"test"}'` | 201 with `id` |
| L-S7 | List workflows | `curl $BASE/api/v1/workflows` | 200 |
| L-S8 | Templates | `curl -s $BASE/api/v1/workflow-templates \| jq '.total'` | `>= 10` |
| L-S9 | WebSocket | Connect to `ws://localhost:8000/ws`, send `{"action":"subscribe","channel":"test"}` | Receive `{"type":"subscribed","channel":"test"}` |
| L-S10 | Frontend | Open `http://localhost:8000` in browser | SPA renders, no JS console errors |

### 1.3 Detailed Tests — Startup & Config [UNIVERSAL]

**TC-L-001: Version flag**
```bash
spectra-sherpa --version
```
PASS: Prints version and exits.

**TC-L-002: Custom port**
```bash
spectra-sherpa --no-browser --port 9999
```
PASS: Binds to 9999. `curl http://localhost:9999/api/v1/health` → OK.

**TC-L-003: Custom data directory**
```bash
spectra-sherpa --no-browser --data-dir /tmp/qa_test_data
```
PASS: Creates `/tmp/qa_test_data/experiments/`, `calibrations/`, `nist_library/downloaded/`, `user/`. SQLite at `/tmp/qa_test_data/spectra_platform.db`.

**TC-L-004: Config details**
```bash
curl -s $BASE/api/v1/config | jq .
```
PASS: `mode:"local"`, `egress_enabled:false`, `features.apiTokenSettings:true`, `features.cloudOffload:false`, `features.demoMode:false`, `features.nistDownloads:false`, `features.pluginSystem:true`, `features.sherpaAdvisor:false`, `limits:null`.

**TC-L-005: Mode endpoint**
```bash
curl -s $BASE/api/v1/config/mode | jq .
```
PASS: `mode:"local"`, `effective_mode:"local"`, `is_degraded:false`.

**TC-L-006: Network status**
```bash
curl -s $BASE/api/v1/config/network-status | jq .
```
PASS: `is_online:true`, `is_degraded:false`, `mode:"local"`.

**TC-L-007: Unit options**
```bash
curl -s $BASE/api/v1/config/units | jq 'keys'
```
PASS: Contains `concentration`, `pathlength`, `temperature`, `wavenumber`.

### 1.4 Auth Behavior [LOCAL-ONLY]

**TC-L-010: All endpoints accessible without auth**
```bash
curl -s $BASE/api/v1/experiments
curl -s $BASE/api/v1/workflows
curl -s $BASE/api/v1/jobs
```
PASS: All return 200.

**TC-L-011: Registration blocked**
```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"testtest1"}'
```
PASS: 404 (routes not registered) or 403.

### 1.5 Experiment CRUD [UNIVERSAL]

**TC-L-020: Create**
```bash
curl -s -X POST $BASE/api/v1/experiments \
  -H "Content-Type: application/json" \
  -d '{"name":"IR Coffee Beans","description":"FTIR arabica vs robusta"}' | jq .
```
PASS: 201 with `id`, `name`, `user_id`.

**TC-L-021: List**
```bash
curl -s "$BASE/api/v1/experiments?limit=10" | jq 'length'
```
PASS: >= 1.

**TC-L-022: Get detail**
```bash
curl -s $BASE/api/v1/experiments/<id> | jq .
```
PASS: Matching `id` and `name`.

**TC-L-023: Update**
```bash
curl -s -X PUT $BASE/api/v1/experiments/<id> \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Name","description":"Updated"}' | jq .
```
PASS: Updated fields returned.

**TC-L-024: Upload file**
```bash
curl -s -X POST $BASE/api/v1/experiments/<id>/files \
  -F "file=@/path/to/test.csv" -F "stage=raw" | jq .
```
PASS: Returns file metadata with `id`, `filename`, `stage`.

**TC-L-025: List files**
```bash
curl -s $BASE/api/v1/experiments/<id>/files | jq 'length'
```
PASS: >= 1.

**TC-L-026: Delete file**
```bash
curl -s -X DELETE $BASE/api/v1/experiments/<id>/files/<file_id>
```
PASS: 204.

**TC-L-027: Delete experiment**
```bash
curl -s -X DELETE $BASE/api/v1/experiments/<id>
```
PASS: 204. GET returns 404.

### 1.6 Workflow CRUD [UNIVERSAL]

**TC-L-030: Create**
```bash
curl -s -X POST $BASE/api/v1/workflows \
  -H "Content-Type: application/json" \
  -d '{"name":"PCA Exploration","description":"Basic PCA"}' | jq .
```
PASS: 201 with `id`.

**TC-L-031: List**
```bash
curl -s $BASE/api/v1/workflows | jq 'length'
```
PASS: >= 1.

**TC-L-032: Get detail**
```bash
curl -s $BASE/api/v1/workflows/<id> | jq 'keys'
```
PASS: Contains `id`, `name`, `nodes`, `edges`.

**TC-L-033: Update (add nodes/edges)**
```bash
curl -s -X PUT $BASE/api/v1/workflows/<id> \
  -H "Content-Type: application/json" \
  -d '{
    "name":"PCA Exploration",
    "nodes":[
      {"id":"n1","type":"io.load_data","params":{},"position":{"x":0,"y":0}},
      {"id":"n2","type":"analysis.pca","params":{"n_components":3},"position":{"x":200,"y":0}}
    ],
    "edges":[{"source":"n1","target":"n2","source_port":"output","target_port":"input"}]
  }' | jq .
```
PASS: 2 nodes, 1 edge.

**TC-L-034: Delete**
```bash
curl -s -X DELETE $BASE/api/v1/workflows/<id>
```
PASS: 204.

### 1.7 Workflow Templates [UNIVERSAL]

**TC-L-040: List templates** — `GET /api/v1/workflow-templates` → `total >= 10`

**TC-L-041: Get template** — `GET /api/v1/workflow-templates/1` → returns name

**TC-L-042: Instantiate** — `POST /api/v1/workflow-templates/1/instantiate` with `{"workflow_name":"From Template"}` → new workflow with pre-populated nodes/edges

### 1.8 DAG Execution [UNIVERSAL]

**TC-L-050: Execute workflow**
Create experiment with CSV, create workflow with LoadData + preprocessing nodes.
```bash
curl -s -X POST $BASE/api/v1/workflows/<id>/execute | jq .
```
PASS: `status:"completed"` or background job created. Node results contain serialized data.

**TC-L-051: Node error handling**
Workflow with PCA `n_components:0`.
PASS: Affected node shows `status:"error"` with message. Other nodes unaffected.

### 1.9 DOE [UNIVERSAL]

**TC-L-060: Create factor** — POST with `{"name":"Temperature","factor_type":"continuous","levels":[25,50,75]}` → returns `id`

**TC-L-061: List factors** — GET → >= 1

**TC-L-062: Create sample** — POST → returns `id`

**TC-L-063: Create mixture** — POST → returns `id`

**TC-L-064: DOE summary** — GET → contains `factors`, `samples`, `mixtures`

### 1.10 Egress Controls [UNIVERSAL]

**TC-L-080: Get defaults**
```bash
curl -s $BASE/api/v1/egress/defaults | jq .
```
PASS: Returns `allow_llm_context`, `allow_nist_queries`, `allow_export`, `allow_spectrasherpa_sync`.

**TC-L-081: Update defaults**
```bash
curl -s -X PUT $BASE/api/v1/egress/defaults \
  -H "Content-Type: application/json" \
  -d '{"allow_llm_context":false}' | jq .
```
PASS: `allow_llm_context:false`.

**TC-L-082: Data types** — GET `/egress/data-types` → array of strings

**TC-L-083: Destinations** — GET `/egress/destinations` → array of strings

**TC-L-084: Summary** — GET `/egress/summary` → contains `defaults`, `permissions`

**TC-L-085: NIST blocked (egress disabled)**
```bash
curl -s "$BASE/api/v1/nist/search?query=ethanol" | jq .
```
PASS: 403 or error about egress not permitted.

**TC-L-086: LLM blocked (no keys)**
```bash
curl -s -X POST $BASE/api/v1/llm/chat \
  -H "Content-Type: application/json" -d '{"message":"Hello"}' | jq .
```
PASS: Error (400/403) — egress disabled or no provider.

### 1.11 Exports [UNIVERSAL]

**TC-L-095: Workflow markdown** — `GET /workflows/<id>/export/markdown` → plaintext markdown (always allowed in local)

**TC-L-096: DOE CSV** — `GET /experiments/<id>/doe/export/csv` → CSV text

### 1.12 WebSocket [UNIVERSAL]

**TC-L-100: Subscribe/Unsubscribe**
```
> {"action":"subscribe","channel":"jobs"}
< {"type":"subscribed","channel":"jobs"}
> {"action":"unsubscribe","channel":"jobs"}
< {"type":"unsubscribed","channel":"jobs"}
```

**TC-L-101: Unknown action** — `{"action":"foobar"}` → error response

**TC-L-102: LLM chat (no key)** — `{"action":"llm_chat","message":"Hello"}` → error about no provider

**TC-L-103: Sherpa sync (not configured)** — `{"action":"sherpa_sync",...}` → not connected/configured

### 1.13 Jobs [UNIVERSAL]

**TC-L-110: List** — GET `/jobs` → 200

**TC-L-111: Get nonexistent** — GET `/jobs/99999` → 404

### 1.14 Logs [UNIVERSAL]

**TC-L-120: Get logs** — `curl http://127.0.0.1:8000/api/v1/logs` → returns log entries

**TC-L-121: Sync status** — shows `mode:"local"`, `remote_logging_enabled:false`

### 1.15 Plugin Discovery [UNIVERSAL]

**TC-L-130**: Check startup logs for `No plugins found` or `Loaded N plugin(s)` — no crash.

### 1.16 LLM with Egress Enabled [UNIVERSAL, requires LLM key]

Restart:
```bash
EGRESS_ENABLED=true OPENAI_API_KEY=sk-your-key spectra-sherpa --no-browser --port 8000
```

**TC-L-140: Config reflects egress** — `egress_enabled:true`, `nistDownloads:true`

**TC-L-141: LLM debug config** — GET `/llm/debug/config` → shows provider/model

**TC-L-142: LLM chat (HTTP)** — POST `/llm/chat` with `{"message":"What is PCA?"}` → returns response

**TC-L-143: LLM chat (WebSocket streaming)**
```
> {"action":"llm_chat","message":"Explain baseline correction"}
< {"type":"llm_start",...}
< {"type":"llm_chunk",...}  (multiple)
< {"type":"llm_done",...}
```

**TC-L-144: NIST search** — `GET /nist/search?query=ethanol` → results with length > 0

---

## Phase 2 — spectrasherpa-server on Digital Ocean (~30 min)

### 2.1 Setup

```bash
cd spectrasherpa-server/
```

Create `.env`:
```env
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
ADMIN_API_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
POSTGRES_PASSWORD=<strong password>
ANTHROPIC_API_KEY=<your key, optional>
CORS_ORIGINS=https://spectrascientific.ai,http://localhost:3000,http://localhost:8000
```

```bash
docker compose up -d --build
```

**Verify**: `docker compose ps` — both containers healthy. `curl http://localhost:8000/health` → OK.

### 2.2 Smoke Tests (spectrasherpa-server)

| # | Test | Command | PASS Criteria |
|---|------|---------|---------------|
| SS-S1 | Health | `curl http://localhost:8000/health` | `{"status":"healthy"}` |
| SS-S2 | Root | `curl http://localhost:8000/` | Contains `"service":"SpectraSherpa"` |
| SS-S3 | Bootstrap | POST `/api/v1/admin/bootstrap` with ADMIN_API_KEY | 201, `is_admin:true` |
| SS-S4 | Admin login | POST `/api/v1/auth/login` | Returns JWT |
| SS-S5 | List users | GET `/api/v1/admin/users` with Bearer | Returns user list |
| SS-S6 | Register | POST `/api/v1/auth/register` | 201 |
| SS-S7 | User login | POST `/api/v1/auth/login` as new user | Returns JWT |
| SS-S8 | Managed keys | GET `/api/v1/keys/llm` with auth | Returns `[]` or key list |
| SS-S9 | Client key | POST `/api/v1/keys/me` with auth | Returns `api_key` (ss_xxx) |
| SS-S10 | Swagger | Open `http://localhost:8000/docs` | UI renders |

### 2.3 Bootstrap

**TC-SS-001: First bootstrap**
```bash
curl -s -X POST http://localhost:8000/api/v1/admin/bootstrap \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","username":"admin","password":"SecurePass123!"}' | jq .
```
PASS: 201, `is_admin:true`.

**TC-SS-002: Second bootstrap fails** — 400 "Admin already exists"

**TC-SS-003: Wrong ADMIN_API_KEY** — 401/403

### 2.4 Authentication

**TC-SS-010: Login**
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"SecurePass123!"}' | jq .
```
PASS: Returns `access_token`.

**TC-SS-011: Wrong password** — 401

**TC-SS-012: Get current user** — GET `/auth/me` with Bearer → user info

**TC-SS-013: Register normal user** — 201, `is_admin:false`

**TC-SS-014: Duplicate email** — 400

### 2.5 Admin Management

**TC-SS-020: List users** — GET `/admin/users` → >= 2

**TC-SS-021: Create user** — POST with `llm_quota:50` → 201

**TC-SS-022: Deactivate user** — PATCH `{"is_active":false}` → updated

**TC-SS-023: Disabled user login fails** — 403 "Account disabled"

**TC-SS-024: Non-admin blocked from admin routes** — 403

### 2.6 Client API Keys

**TC-SS-030: Generate key**
```bash
curl -s -X POST http://localhost:8000/api/v1/keys/me \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Laptop"}' | jq .
```
PASS: Returns `api_key` starting with `ss_`.

**TC-SS-031: Auth with X-API-Key** — GET `/auth/me` with `X-API-Key: ss_xxx` → user info

**TC-SS-032: Revoke key** — DELETE → 204. Old key stops working.

**TC-SS-033: Max 10 keys** — 11th attempt → 400

### 2.7 Managed LLM Keys

**TC-SS-040: Add managed key (admin)**
```bash
curl -s -X POST http://localhost:8000/api/v1/admin/llm-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider":"anthropic","display_name":"Claude","model":"claude-sonnet-4-20250514","api_key":"sk-ant-test","rate_limit":100}' | jq .
```
PASS: 201.

**TC-SS-041: Admin list (no key values)** — GET `/admin/llm-keys` → list without `api_key` field

**TC-SS-042: User get keys (values returned)** — GET `/keys/llm` with auth → list with `api_key` and `expires_at`

**TC-SS-043: Delete managed key** — DELETE `/admin/llm-keys/anthropic` → 204

---

## Phase 3 — Hybrid Mode (~45 min)

### 3.1 Setup

Create `.env` in project root or `deploy/`:
```env
APP_MODE=hybrid
EXECUTION_MODE=hybrid
SECRET_KEY=<strong key>
CORS_ORIGINS=https://app.spectrascientific.ai,http://localhost:3000
DATABASE_URL=sqlite+aiosqlite:////app/data/spectra_platform.db
SPECTRASHERPA_API_URL=http://<server-ip>:8000/api/v1
SPECTRASHERPA_API_KEY=<client-api-key-from-phase-2>
# Optional
SPECTRASHERPA_LOG_URL=http://<server-ip>:8000/api/v1/logs
OPENAI_API_KEY=<optional>
```

```bash
cd deploy/
DOMAIN=localhost docker compose -f docker-compose.prod.yaml up -d --build
```

**Verify**: All 3 containers healthy. Backend health OK. No `SECURITY ERROR`.

### 3.2 Smoke Tests (Hybrid)

| # | Test | Command | PASS Criteria |
|---|------|---------|---------------|
| H-S1 | Health | `curl $BASE/api/v1/health` | `{"status":"ok"}` |
| H-S2 | Config | `curl -s $BASE/api/v1/config \| jq .` | `mode:"hybrid"`, `egress_enabled:true` |
| H-S3 | Auth required | `curl $BASE/api/v1/experiments` | 401 |
| H-S4 | Register | POST `/auth/register` | 201 |
| H-S5 | Login | POST `/auth/login` | Returns JWT |
| H-S6 | Auth me | GET `/auth/me` with Bearer | Returns user |
| H-S7 | Admin routes | GET `/admin/users` with superuser | Returns list |
| H-S8 | Experiments | GET `/experiments` with Bearer | 200 |
| H-S9 | Network status | GET `/config/network-status` | Shows spectrasherpa_status |
| H-S10 | WS unauthenticated | Connect `ws://.../ws` without token | Closed with 1008 |

### 3.3 Auth Enforcement [HYBRID-ONLY]

**TC-H-001: Unauthenticated blocked** — `curl $BASE/api/v1/experiments` → 401

**TC-H-002: Register and login**
```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"hybrid_user","password":"TestPass123!"}'

curl -s -X POST $BASE/api/v1/auth/login \
  -d "username=hybrid_user&password=TestPass123!"
```
PASS: Register 201, login returns `access_token`.

**TC-H-003: Bearer token works** — GET `/experiments` with Bearer → 200

**TC-H-004: API key works** — GET `/experiments` with `X-API-Key` → 200

**TC-H-005: Invalid token rejected** — 401

**TC-H-006: WebSocket auth required** — connect without creds → closed 1008

**TC-H-007: WebSocket with token** — connect with `?api_key=$TOKEN` → stays open, subscribe works

### 3.4 Admin Panel [HYBRID-ONLY]

**TC-H-010: List users** — superuser GET `/admin/users` → list

**TC-H-011: Create user** — POST → 200

**TC-H-012: Rotate API key** — POST `/admin/users/<id>/rotate-key` → returns key

**TC-H-013: Toggle active** — PATCH `{"is_active":false}` → user deactivated

**TC-H-014: System LLM keys CRUD** — create (201), list (masked), delete (204)

**TC-H-015: Non-admin blocked** — 403

### 3.5 Network Health & Graceful Degradation [HYBRID-ONLY]

**TC-H-020: Online status**
```bash
curl -s $BASE/api/v1/config/network-status | jq .
```
PASS: `is_online:true`, `is_degraded:false`.

**TC-H-021: Mode endpoint** — `mode:"hybrid"`, `effective_mode:"hybrid"`

**TC-H-022: Degradation — stop spectrasherpa-server**
Stop server. Wait 60-120s.
```bash
curl -s $BASE/api/v1/config/network-status | jq .
```
PASS: `is_degraded:true` after 2-3 check intervals.

**TC-H-023: Recovery — restart server**
Restart server. Wait for health check recovery.
PASS: `is_degraded:false`.

### 3.6 SpectraSherpa Integration [HYBRID-ONLY]

**TC-H-030: Config shows configured** — GET `/config/spectrasherpa` → `configured:true`, key masked

**TC-H-031: User info from server** — GET `/config/spectrasherpa/user` → user info or error

**TC-H-032: Managed keys from server** — GET `/config/spectrasherpa/keys` → key list or empty

**TC-H-033: Connection test**
```bash
curl -s -X POST $BASE/api/v1/config/spectrasherpa/test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"server_url":"http://<server-ip>:8000","api_key":"<key>"}' | jq .
```
PASS: `success:true`.

**TC-H-034: SSRF protection** — test with `http://evil.com` → `success:false`

**TC-H-035: Save config deprecated** — POST `/config/spectrasherpa` → 403

### 3.7 Remote Audit [HYBRID-ONLY]

**TC-H-040: Log sync status** — GET `/logs/sync-status` → `mode:"hybrid"`, shows remote handler info if LOG_URL set

**TC-H-041: RemoteAuditHandler in logs** — check `docker logs` for handler initialization

### 3.8 Re-run UNIVERSAL Tests

Run all UNIVERSAL tests from Phase 1 (TC-L-020 through TC-L-130) with `-H "Authorization: Bearer $TOKEN"` on every request.

Key differences to verify:
- `egress_enabled:true` by default
- NIST search/download works
- LLM chat works (if keys configured)
- Export checks `check_export_allowed()` per user

---

## Phase 4 — Demo Mode (~30 min)

### 4.1 Setup

Update `.env`:
```env
APP_MODE=demo
SECRET_KEY=<strong key>
CORS_ORIGINS=https://demo.spectrascientific.ai,http://localhost:3000
DEMO_PASSWORD=DemoAccess2025
RATE_LIMIT_EXECUTIONS=20
SESSION_EXPIRY_HOURS=4
```

```bash
cd deploy/
DOMAIN=localhost docker compose -f docker-compose.prod.yaml up -d --build
```

### 4.2 Smoke Tests (Demo)

| # | Test | Command | PASS Criteria |
|---|------|---------|---------------|
| D-S1 | Health | `curl $BASE/api/v1/health` | `{"status":"ok"}` |
| D-S2 | Config | `curl -s $BASE/api/v1/config \| jq .` | `mode:"demo"`, `demoMode:true`, `limits` populated |
| D-S3 | Auth required | `curl $BASE/api/v1/experiments` | 401 |
| D-S4 | No demo pass | POST register without `X-Demo-Password` | 401 |
| D-S5 | With demo pass | POST register with `X-Demo-Password: DemoAccess2025` | 201 |
| D-S6 | Login | POST login (no demo pass needed) | Returns JWT |
| D-S7 | Rate limit | POST workflow execute 21 times | 21st returns 429 |
| D-S8 | Admin routes | GET `/admin/users` with superuser | Returns list |
| D-S9 | Egress | `curl -s $BASE/api/v1/config \| jq '.egress_enabled'` | `true` |
| D-S10 | Limits | `curl -s $BASE/api/v1/config \| jq '.limits'` | `{maxExecutions:20, maxFileSizeMB:200, sessionExpiryHours:4}` |

### 4.3 Demo Password [DEMO-ONLY]

**TC-D-001: Registration requires demo password**
```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_user","password":"TestPass123!"}'
```
PASS: 401 "Demo password required".

**TC-D-002: Correct demo password**
```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Demo-Password: DemoAccess2025" \
  -d '{"username":"demo_user","password":"TestPass123!"}'
```
PASS: 201.

**TC-D-003: Wrong demo password** — 401

**TC-D-004: Login does NOT require demo password** — returns token

### 4.4 Rate Limiting [DEMO-ONLY]

**TC-D-010: Hit rate limit**
```bash
for i in $(seq 1 25); do
  echo -n "$i: "
  curl -s -o /dev/null -w "%{http_code}" \
    -X POST $BASE/api/v1/workflows/<id>/execute \
    -H "Authorization: Bearer $TOKEN"
  echo
done
```
PASS: First 20 return 200 (or other success). 21+ return 429.

**TC-D-011: GET not rate-limited**
```bash
for i in $(seq 1 30); do
  curl -s -o /dev/null -w "%{http_code}" \
    $BASE/api/v1/experiments \
    -H "Authorization: Bearer $TOKEN"
done
```
PASS: All 30 return 200.

**TC-D-012: Per-user isolation** — two users, each has own counter

**TC-D-013: Rate limit headers**
```bash
curl -s -v -X POST $BASE/api/v1/workflows/<id>/execute \
  -H "Authorization: Bearer $TOKEN" 2>&1 | grep -i ratelimit
```
PASS: `X-RateLimit-Limit: 20`, `X-RateLimit-Remaining: <n>`.

### 4.5 Session Expiry [DEMO-ONLY]

**TC-D-020: Fresh token works** — all endpoints return 200

**TC-D-021: Expired session**
(Set `SESSION_EXPIRY_HOURS=0` temporarily, or craft expired JWT.)
PASS: 401 with `"Demo session expired"`, `max_session_hours`.

**TC-D-022: Re-login after expiry** — new token works

### 4.6 Expected Failures [DEMO-ONLY]

**TC-D-040: No graceful degradation** [EXPECTED FAILURE]
```bash
curl -s $BASE/api/v1/config/network-status | jq .
```
Network health monitoring does not start in demo mode. No auto-degradation.

**TC-D-041: No remote audit** [EXPECTED FAILURE]
`RemoteAuditHandler` only activates in hybrid mode. Log sync status returns `remote_logging_enabled:false`.

### 4.7 Re-run UNIVERSAL Tests

Run all UNIVERSAL tests with demo auth, staying within rate limits.

---

## Cross-Mode Regression Matrix

| Behavior | Local | Hybrid | Demo |
|----------|-------|--------|------|
| Auth middleware | Bypassed | Required | Required |
| Auth/Admin routes | 404 | Registered | Registered |
| Registration | Blocked | Open | Needs demo password |
| Default user | "local" auto-created | Must register | Must register |
| Egress default | `false` | `true` | `true` |
| CORS | `*` | Configured only | Configured only |
| Rate limiting | Inactive | Optional | Active |
| Network health | Not started | Auto-degrade | Not started |
| Remote audit | N/A | Active (if URL) | N/A |
| SECRET_KEY | Warning | Fatal if default | Fatal if default |
| `features.demoMode` | `false` | `false` | `true` |
| `features.cloudOffload` | `false` | `true` | `false` |
| `config.limits` | `null` | `null` | Populated |

**TC-X-001: Mode switch** — start local, check config; start hybrid, verify config differs

**TC-X-002: SECRET_KEY enforcement** — `APP_MODE=hybrid spectra-sherpa` with default key → exits with `SECURITY ERROR`

**TC-X-003: CORS** — local returns `Access-Control-Allow-Origin: *`; hybrid/demo restrict to CORS_ORIGINS

---

## Known Expected Failures

| ID | Issue | Mode | Reference |
|----|-------|------|-----------|
| KEF-1 | No graceful degradation | Demo | network_health.py only starts in hybrid |
| KEF-2 | No remote audit logging | Demo | logging.py:277 hybrid-only check |
| KEF-3 | No `/sherpa/sync` or `/sherpa/decide` on server | Hybrid | spectrasherpa-server not yet implemented |
| KEF-4 | Zero automated tests for demo mode | Demo | CURRENT_CAPABILITIES.md testing status |
| KEF-5 | No CI/CD pipeline | All | No GitHub Actions or tox.ini |
| KEF-6 | LLM managed key stored as plaintext on server | Hybrid | Code comment: "encrypt this!" |
| KEF-7 | Backend/frontend template mismatch | All | 10 backend vs 12 frontend |
