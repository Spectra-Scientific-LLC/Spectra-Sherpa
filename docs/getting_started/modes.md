# Modes & Configuration

SpectraSherpa supports three deployment modes. Each mode is designed for a
specific use case and controls authentication, network access, and resource
limits.

Set the mode with the `APP_MODE` environment variable (default: `local`).

---

## Local Mode (Default)

**For:** Individual researchers running SpectraSherpa on their own computer.

```bash
# No configuration needed — this is the default
spectra-sherpa
```

### Characteristics

| Setting | Value |
|---------|-------|
| Authentication | None — no login required |
| Database | SQLite (auto-created) |
| Network egress | Disabled by default |
| Token lifetime | 8 days (convenience) |
| Bind address | `127.0.0.1` (localhost only) |

### What it does

- Creates a single implicit user (`local`) on first startup.
- All data stays on your machine — no network calls unless you enable them.
- The frontend loads directly into the workspace, no login page.

### Enabling LLM / NIST features

By default, all network access is off. To use AI features or NIST downloads:

```bash
# .env in your working directory
EGRESS_ENABLED=true
OPENAI_API_KEY=sk-...   # or any other provider
```

Restart SpectraSherpa after editing `.env`.

---

## Hybrid Mode

**For:** Researchers who want local-first privacy with optional cloud
identity linking, managed LLM keys, and GPU offload.

```bash
# .env
APP_MODE=hybrid
SPECTRASHERPA_API_KEY=sk-your-key-from-server
```

### Characteristics

| Setting | Value |
|---------|-------|
| Authentication | None for localhost; JWT/API key required for remote clients |
| Database | SQLite (local) |
| Network egress | Enabled by default |
| Token lifetime | 60 minutes (configurable) |
| Bind address | `127.0.0.1` by default |

### How identity linking works

On startup, SpectraSherpa calls the spectrasherpa-server's `GET /auth/me`
endpoint with your API key. The server returns your profile (username, admin
status, LLM quota), which is stored locally. This gives you:

- Your real username instead of "local"
- Admin features if your server account has `is_admin=true`
- LLM quota enforcement from the server

**Offline behavior:** If the server is unreachable, the last-synced identity
persists. First-ever offline startup uses a generic "local" user.

### Security model

- **Loopback clients** (browser on the same machine) bypass authentication
  automatically — no login needed.
- **Remote clients** (if you bind to `0.0.0.0` or expose via proxy) must
  provide a valid JWT token or API key. This is enforced automatically.

### Behind a reverse proxy

If you put hybrid mode behind nginx or Caddy, enable proxy trust so rate
limiting and loopback detection see the real client IP:

```bash
# .env
TRUST_PROXY=true
TRUSTED_PROXY_CIDRS=172.18.0.0/16   # Docker bridge network
```

Without this, all requests appear to come from the proxy's IP.

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_MODE` | Yes | Set to `hybrid` |
| `SPECTRASHERPA_API_KEY` | Recommended | API key for identity linking |
| `CLOUD_COMPUTE_URL` | Optional | GPU offload endpoint URL |
| `CLOUD_API_KEY` | Optional | Authentication for GPU offload |
| `EGRESS_ENABLED` | No (default: `true`) | Network access for LLM/NIST |
| `TRUST_PROXY` | No | Trust X-Forwarded-For from proxy |
| `TRUSTED_PROXY_CIDRS` | No | Comma-separated CIDR ranges of trusted proxies |

---

## Demo Mode

**For:** Cloud-hosted evaluation deployments where multiple users register,
log in, and try the platform.

Demo mode is designed for internet-facing servers. It requires Docker — see
the full [DigitalOcean Deployment Guide](../deployment/DIGITAL_OCEAN.md) for
step-by-step setup.

### Characteristics

| Setting | Value |
|---------|-------|
| Authentication | JWT required on all endpoints |
| Database | SQLite (small demos) or PostgreSQL (production) |
| Network egress | Enabled by default |
| Token lifetime | 60 minutes (configurable) |
| Rate limiting | 100 executions/user/hour (configurable) |
| Session expiry | 24 hours (configurable) |
| Registration | Open (or gated with `DEMO_PASSWORD`) |

### Security enforcement at startup

Demo mode validates security settings before the app starts. It will
**refuse to boot** if:

- `SECRET_KEY` is still the default value
- `APP_API_KEY` is default **and** `ALLOW_SYSTEM_API_KEY_AUTH` is enabled

This prevents accidentally exposing a demo server with known credentials.

### User flow

1. User visits `https://your-domain.com` — sees the login page.
2. Registers with username + password (8 character minimum).
3. Logs in — receives a JWT token (stored in browser localStorage).
4. Accesses the workspace — all API calls include the JWT.
5. After `SESSION_EXPIRY_HOURS`, must log in again.

### Rate limiting

| Endpoint | Limit | Window |
|----------|-------|--------|
| Login (`POST /auth/login`) | 10 attempts | 15 minutes |
| Registration (`POST /auth/register`) | 5 registrations | 1 hour |
| Workflow/job execution | Configurable (default 100) | 1 hour |

Rate limits are per-IP for auth endpoints and per-user for execution.

### Required environment variables

```bash
# .env (in deploy/ directory)
APP_MODE=demo
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
APP_API_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
CORS_ORIGINS=https://your-domain.com
DOMAIN=your-domain.com
```

### Optional configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_EXECUTIONS` | `100` | Max workflow executions per user per hour |
| `SESSION_EXPIRY_HOURS` | `24` | Force re-login after this many hours |
| `DEMO_PASSWORD` | (none) | If set, required for registration |
| `DATABASE_URL` | SQLite | PostgreSQL connection string |
| `LOG_FILE_PATH` | (none) | Persist audit logs (e.g., `/app/data/audit.log`) |
| `MASTER_ENCRYPTION_KEY` | Auto-generated | Stable key for API key encryption across restarts |
| `WEB_CONCURRENCY` | `1` | Gunicorn worker count (keep at 1 unless using shared pub/sub) |
| `TRUST_PROXY` | `false` | Trust X-Forwarded-For from reverse proxy |
| `TRUSTED_PROXY_CIDRS` | loopback only | CIDR ranges of trusted proxy peers |

---

## Mode Comparison

| Feature | Local | Hybrid | Demo |
|---------|-------|--------|------|
| Auth required | No | Loopback: no; remote: yes | Always |
| Database | SQLite | SQLite | SQLite or PostgreSQL |
| Default egress | Off | On | On |
| LLM / NIST | If `EGRESS_ENABLED=true` | If keys configured | If keys configured |
| Rate limiting | None | Auth endpoints only | Full (auth + execution) |
| Session expiry | None | None | 24 hours default |
| Admin panel | Hidden | If server user is admin | If user is superuser |
| GPU offload | No | If `CLOUD_COMPUTE_URL` set | Via managed infra |
| Identity | Implicit "local" user | Linked from server | Self-registered |
| Deployment | `pip install` + CLI | `pip install` + `.env` | Docker Compose |
| Startup validation | Relaxed | Warns on weak config | Strict (fails on defaults) |
