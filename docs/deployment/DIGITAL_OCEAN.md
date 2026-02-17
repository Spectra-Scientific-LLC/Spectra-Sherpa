# DigitalOcean Deployment Guide

**Last Updated:** 2026-02-08

This guide walks through deploying SpectraSherpa to DigitalOcean (or any
Docker-capable VPS) as a demo evaluation server.

## Prerequisites

-   A DigitalOcean Droplet (recommended: 4 GB RAM, 2 vCPUs, Ubuntu 22.04+).
-   `docker` and `docker compose` installed on the server.
-   A domain name with DNS pointing to your droplet's IP (required for HTTPS).

---

## 1. Transfer Code to the Server

```bash
scp -r ./Refactored root@your-droplet-ip:/opt/spectra-platform
```

Or clone from your repository:

```bash
ssh root@your-droplet-ip
git clone https://your-repo-url.git /opt/spectra-platform
```

---

## 2. Generate Secrets

Generate the required secrets on the server:

```bash
ssh root@your-droplet-ip

# Generate SECRET_KEY (signs JWT tokens)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate APP_API_KEY (machine authentication key)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate MASTER_ENCRYPTION_KEY (encrypts stored API keys)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save these values — you'll need them in the next step.

---

## 3. Configure Environment

Create a `.env` file in `/opt/spectra-platform/deploy/`:

```bash
# /opt/spectra-platform/deploy/.env

# === REQUIRED ===
APP_MODE=enterprise          # (APP_MODE=demo is accepted as a deprecated alias)
SECRET_KEY=<paste your generated secret key>
APP_API_KEY=<paste your generated API key>
CORS_ORIGINS=https://your-domain.com
DOMAIN=your-domain.com

# === RECOMMENDED ===
MASTER_ENCRYPTION_KEY=<paste your generated encryption key>

# === ENTERPRISE CONTROLS (defaults shown) ===
# RATE_LIMIT_EXECUTIONS=100        # Max workflow executions per user per hour
# SESSION_EXPIRY_HOURS=24          # Force re-login after this many hours
# ENTERPRISE_PASSWORD=             # If set, required for user registration
#                                  # (DEMO_PASSWORD is accepted as a deprecated alias)

# === SITE PROFILE (optional) ===
# SITE_PROFILE=demo                # Show demo branding on login page

# === PROXY TRUST (required — Caddy sits in front of the backend) ===
TRUST_PROXY=true
TRUSTED_PROXY_CIDRS=172.18.0.0/16  # Docker bridge network CIDR

# === WORKER COUNT ===
# Default: 1 worker. WebSocket state is in-memory, so multi-worker
# deployments lose cross-worker realtime events. Keep at 1 unless you
# add a shared pub/sub backend (Redis, etc.).
# WEB_CONCURRENCY=1

# === LLM API KEYS (optional — enables AI assistant) ===
# DEEPSEEK_API_KEY=sk-...
# OPENAI_API_KEY=sk-...

# === DATABASE (required for enterprise mode) ===
# Enterprise mode hard-fails at startup with SQLite.
# SQLite is only acceptable for local/hybrid single-user mode.
DATABASE_URL=postgresql+asyncpg://spectra:secretpassword@db:5432/spectra

# === AUDIT LOGGING (optional) ===
# LOG_FILE_PATH=/app/data/audit.log
```

### Startup Validation

Enterprise mode validates security settings before booting. The app will **refuse
to start** if:

- `SECRET_KEY` is still the default `"your-super-secret-key-change-in-production"`
- `APP_API_KEY` is default **and** `ALLOW_SYSTEM_API_KEY_AUTH` is enabled
- `CORS_ORIGINS` is not set
- `DATABASE_URL` points to SQLite (enterprise requires PostgreSQL)

These checks prevent accidentally exposing a server with known credentials.

---

## 4. Build and Run

```bash
cd /opt/spectra-platform/deploy
docker compose -f docker-compose.prod.yaml up -d --build
```

First build takes 3-5 minutes (downloads Python dependencies, compiles
frontend). Subsequent restarts are fast.

---

## 5. Verify Deployment

### All Distributions

```bash
# Health check
curl https://your-domain.com/api/v1/health
# Expected: {"status": "ok"}

# Current user (works in all modes — returns implicit user in local/hybrid)
curl https://your-domain.com/api/v1/auth/me
```

### Server Distribution Only

The following endpoints require `spectrasherpa-server`. They are not available
in the OSS distribution. See [OSS_SCOPE.md](../OSS_SCOPE.md) for the full
endpoint matrix.

```bash
# Register a user
curl -X POST https://your-domain.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "securepassword123"}'

# Login and get JWT
curl -X POST https://your-domain.com/api/v1/auth/login \
  -d "username=alice&password=securepassword123"
# Returns: {"access_token": "eyJ...", "token_type": "bearer"}

# Use the token
curl https://your-domain.com/api/v1/experiments \
  -H "Authorization: Bearer eyJ..."
```

---

## Enterprise Mode Security Features

### Authentication

All non-public endpoints require a JWT token. Users register and log in
through the web UI. Tokens expire after `SESSION_EXPIRY_HOURS` (default 24).

| Feature | Default | Env var |
|---------|---------|---------|
| JWT auth | Required on all endpoints | Always on |
| Token lifetime | 60 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Session expiry | 24 hours | `SESSION_EXPIRY_HOURS` |
| Registration gate | Open | `ENTERPRISE_PASSWORD` (or `DEMO_PASSWORD`) |

### Rate Limiting

Rate limits are enforced per-IP for auth endpoints and per-user for execution.

| Endpoint | Limit | Window |
|----------|-------|--------|
| `POST /auth/login` | 10 attempts | 15 minutes |
| `POST /auth/register` | 5 registrations | 1 hour |
| Workflow/job execution | 100 (configurable) | 1 hour |

Rate limit state is file-backed and survives container restarts (stored in
the `app-data` Docker volume).

### Timing Attack Protection

The login endpoint always runs bcrypt verification regardless of whether the
username exists. This prevents username enumeration through response time
differences.

### Container Security

The backend runs as a non-root `app` user inside the container. The data
directory (`/app/data`) is owned by this user.

---

## Database: PostgreSQL (Required for Enterprise)

Enterprise mode **requires PostgreSQL** — the app hard-fails at startup if
`DATABASE_URL` points to SQLite. The `docker-compose.prod.yaml` enforces this
via `${DATABASE_URL:?DATABASE_URL is required (PostgreSQL)}`.

SQLite is only acceptable for **local** and **hybrid** single-user desktop mode.

### When SQLite is OK

- Single user running `pip install spectra-sherpa` on their own machine
- Local/hybrid mode with no concurrent access

### PostgreSQL setup

Add a Postgres service to `docker-compose.prod.yaml` or use DigitalOcean
Managed Databases:

```bash
# In .env:
DATABASE_URL=postgresql+asyncpg://spectra:secretpassword@db:5432/spectra
```

If using a container, add to `docker-compose.prod.yaml`:

```yaml
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: spectra
      POSTGRES_USER: spectra
      POSTGRES_PASSWORD: secretpassword
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - spectra-network
    restart: always
```

And add `postgres-data:` to the `volumes:` section.

### Schema Migrations

In enterprise mode, Alembic migrations run automatically on startup. If migrations
fail, the app refuses to start (fail-fast). The migration runs in a worker
thread to avoid event loop conflicts.

---

## Infrastructure Overview

### Docker Stack

```
Internet → Caddy (443/80) → nginx/frontend (80) → backend (8000)
                                                  ↕
                                              SQLite / PostgreSQL
```

| Container | Role |
|-----------|------|
| **Caddy** | Reverse proxy, automatic HTTPS (Let's Encrypt), security headers |
| **Frontend** | nginx serving the Vue SPA, proxying API/WebSocket to backend |
| **Backend** | Gunicorn + Uvicorn worker, FastAPI application |

### Worker Model

The backend defaults to **1 Gunicorn worker**. This is intentional —
WebSocket channel state is in-memory, so multiple workers would lose
cross-worker realtime events (e.g., job status updates not reaching the
browser that submitted them).

To use multiple workers, add a shared pub/sub backend (Redis) and set
`WEB_CONCURRENCY=3` in `.env`. The app logs a warning at startup if
`WEB_CONCURRENCY > 1` without shared pub/sub.

### Startup Phases

The first worker to start (the "leader") runs one-time tasks:

1. Apply database migrations (Alembic)
2. Create default user
3. Seed sample data and workflow templates
4. Reconcile stale jobs from previous runs

Subsequent workers wait for the leader to finish DB setup (up to 5 minutes),
then start serving requests.

### Reverse Proxy Trust

Because Caddy sits in front of the backend in Docker, the backend sees
Caddy's container IP (e.g., `172.18.0.3`) instead of the real client IP.
Setting `TRUST_PROXY=true` and `TRUSTED_PROXY_CIDRS=172.18.0.0/16` tells the
backend to read `X-Forwarded-For` for the real client IP.

This affects:

- **Rate limiting** (per-IP limits work correctly)
- **Loopback detection** (hybrid mode auth bypass)
- **Audit logging** (real client IPs in logs)

Without proxy trust, all requests appear to come from the proxy's IP, which
breaks per-IP rate limiting.

### Caddy Configuration

The Caddyfile uses `{$DOMAIN:localhost}`:

```bash
DOMAIN=app.spectrascientific.ai docker compose -f docker-compose.prod.yaml up -d
```

Without `DOMAIN`, Caddy serves on `localhost` with a self-signed cert (dev only).

### Persistent Volumes

| Volume | Purpose | Survives restart? |
|--------|---------|-------------------|
| `app-data` | SQLite DB, experiments, audit logs, rate limit state | Yes |
| `caddy-data` | TLS certificates | Yes |
| `caddy-config` | Caddy runtime config | Yes |

---

## Hybrid Mode (for Local Desktop Users)

Hybrid mode is for users running SpectraSherpa on their own machines — not
for DO deployment. It connects a local instance to a spectrasherpa-server
for identity linking, managed LLM keys, and GPU offload.

For hybrid configuration, see [Modes & Configuration](../getting_started/modes.md#hybrid-mode).

### Server-Side Setup (on DigitalOcean)

If you run a spectrasherpa-server for hybrid identity linking:

1. Deploy spectrasherpa-server to the droplet (separate Docker stack).
2. Create a user account and generate a `ClientKey` (API key) for each user.
3. Ensure `GET /auth/me` is accessible from the user's machine.

### What the User Does (on Their Machine)

```bash
pip install spectra-sherpa
```

Create a `.env` file:

```bash
APP_MODE=hybrid
SPECTRASHERPA_API_KEY=sk-key-from-server
```

Run:

```bash
spectra-sherpa
```

On startup, SpectraSherpa links the local user to the server identity. The
user sees their real username and admin status. If the server is unreachable,
the last-synced identity persists.

---

## Updating the Deployment

```bash
cd /opt/spectra-platform
git pull origin main
cd deploy
docker compose -f docker-compose.prod.yaml up -d --build
```

Database migrations run automatically on startup. The `app-data` volume
persists across rebuilds.

---

## Troubleshooting

### View Logs

```bash
docker compose -f docker-compose.prod.yaml logs -f
docker compose -f docker-compose.prod.yaml logs backend  # backend only
```

### Compose Won't Start — Missing Variable

```
ERROR: SECRET_KEY is required
```

Add the missing variable to your `.env` file. Required variables:
`SECRET_KEY`, `APP_API_KEY`, `CORS_ORIGINS`.

### HTTPS Not Working

- Ensure `DOMAIN` env var is set to your actual domain.
- Ensure DNS A-record points to the droplet's IP.
- Check Caddy logs: `docker compose logs caddy`.
- Caddy needs ports 80 and 443 open for ACME challenge.

### Login Returns 429 (Too Many Requests)

Auth rate limiting is enforced: 10 login attempts per 15 minutes per IP.
Wait 15 minutes or check the rate limit state file in the `app-data` volume.

### WebSocket Not Connecting

- Check that Caddy/nginx proxy WebSocket connections (`/ws` path).
- The frontend sends JWT tokens as query params (`?token=...`).
- Check backend logs for `WS_1008_POLICY_VIOLATION` (invalid credentials).

### Admin Button Not Showing

- Admin requires `is_superuser=true` on the user record.
- In enterprise mode, the first user created or manually promoted in the DB is admin.
- Check: `curl /api/v1/auth/me -H "Authorization: Bearer <token>"`.

### Rate Limiting Reset After Restart

- Rate limit state is in `/app/data/execution_rate_limits.json`.
- This is inside the `app-data` Docker volume, so it survives restarts.
- Full volume deletion (`docker volume rm`) resets it.

---

## Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_MODE` | Yes | `local` | Set to `enterprise` for DO deployment (`demo` accepted as alias) |
| `SECRET_KEY` | Yes | (fails) | JWT signing key — generate a random value |
| `APP_API_KEY` | Yes | (fails) | Machine auth key — generate a random value |
| `CORS_ORIGINS` | Yes | (fails) | Allowed origins, comma-separated |
| `DOMAIN` | Yes | `localhost` | Domain for Caddy HTTPS provisioning |
| `MASTER_ENCRYPTION_KEY` | Required* | Auto-generated | Encryption key for stored API keys. *Auto-generates if unset but stored keys are lost on container restart. |
| `DATABASE_URL` | Yes (enterprise) | — | PostgreSQL connection string (SQLite OK for local/hybrid only) |
| `RATE_LIMIT_EXECUTIONS` | No | `100` | Execution rate limit per user per hour |
| `SESSION_EXPIRY_HOURS` | No | `24` | Force re-login after N hours |
| `ENTERPRISE_PASSWORD` | No | (none) | Registration gate password (`DEMO_PASSWORD` accepted as alias) |
| `WEB_CONCURRENCY` | No | `1` | Gunicorn worker count |
| `TRUST_PROXY` | No | `false` | Trust X-Forwarded-For headers |
| `TRUSTED_PROXY_CIDRS` | No | Loopback | Trusted proxy CIDR ranges |
| `LOG_FILE_PATH` | No | (none) | Audit log file path |
| `DEEPSEEK_API_KEY` | No | (none) | LLM API key (any OpenAI-compatible provider) |
