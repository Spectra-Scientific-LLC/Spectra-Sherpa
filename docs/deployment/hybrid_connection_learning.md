# Hybrid Connection & Deployment Lessons

**Snapshot date:** 2026-02-09

This document captures hard-won lessons from the first DigitalOcean server
deployment and hybrid mode activation testing. Keep it updated as new issues
surface.

---

## Deployment Lessons (DO Server Testing)

### passlib / bcrypt incompatibility
- passlib 1.7.4 breaks with bcrypt >= 4.1
- Error: `AttributeError: module 'bcrypt' has no attribute '__about__'`
- **FIX:** Pin `bcrypt = ">=4.0.1,<4.1"` in `pyproject.toml`

### Silent startup crash
- If `seed_data()` in `ensure_database_ready()` fails (e.g. missing tables),
  the process exits silently — no traceback in uvicorn logs
- Starlette swallows lifespan exceptions
- **FIX:** Wrap in try/except with explicit traceback logging

### DB corruption on incomplete first run
- If the first startup doesn't complete `create_all()`, Alembic migration
  history exists but base tables (experiment, etc.) don't
- Subsequent startups fail in `seed_data()` with
  `OperationalError: no such table: experiment`
- **FIX:** Delete the SQLite database file and restart

### Enterprise mode rejects SQLite
- `APP_MODE=enterprise` requires PostgreSQL — the app refuses to start with SQLite
  (note: `APP_MODE=demo` is accepted as a deprecated alias for `enterprise`)
- **Use `APP_MODE=hybrid`** for single-server SQLite deployments

### DO Firewall
- Port 8000 must be explicitly added as a Custom TCP inbound rule
- Default DO firewall only allows SSH (22), HTTP (80), HTTPS (443)

---

## Hybrid Mode Activation

### Required `.env` variables
```bash
APP_MODE=hybrid
SECRET_KEY=<generate: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
SPECTRASHERPA_API_URL=http://<server-ip>:8000
SPECTRASHERPA_API_KEY=sk_<key-from-server>
```

### SECRET_KEY is mandatory
- `validate_security_settings()` rejects the default key in hybrid mode
- Must generate a unique key and add to `.env`

### Egress sync defaults to OFF
- `allow_spectrasherpa_sync=False` by default in `UserEgressDefaults`
- Must enable via DB for Sherpa Advisor to work:
  ```bash
  sqlite3 ~/.spectra_sherpa/spectra_platform.db \
    "UPDATE user_egress_defaults SET allow_spectrasherpa_sync=1;"
  ```
- Future: add UI toggle in Data & Privacy tab

### IntegrationsTab UI gap
- The activate-hybrid UI (Server URL / API Key inputs) exists in the dev
  codebase but is **NOT** in the pip-built static assets
- Users must use the manual `.env` method for now

### Admin user creation
- No CLI flag exists yet for admin promotion
- After registration, use sqlite3:
  ```bash
  sqlite3 /path/to/spectra_platform.db \
    "UPDATE users SET is_superuser=1 WHERE username='youruser';"
  ```

---

## DO Server State (as of 2026-02-09)

| Item | Value |
|------|-------|
| IP | `146.190.48.1` |
| Port | 8000 |
| Mode | hybrid |
| Repos | `/opt/spectra-platform/` (Repo 1 + Repo 2) |
| Users | `guest` (superuser), `hybrid_client` (API key holder) |
| Python | system + `spectra` user venv at `/opt/spectra-platform/venv` |
| bcrypt | pinned to 4.0.1 on server |

---

## Key Architecture Notes

### 3-Repo Split
- **Repo 1** (`Refactored/`): OSS local-first app — auth.py/admin.py removed
- **Repo 2** (`spectrasherpa-server/`): Commercial backend — `create_app()` +
  auth/admin routes via `extra_routers`
- **Repo 3** (`spectra-ops/`): Docker, compose, nginx, Caddy, deploy configs

### WebSocket Debugging
- `ws_user` loaded in auth session; action handlers open new sessions —
  lazy-loaded relationships fail with `DetachedInstanceError`
- WS handlers need try/except per action (only `WebSocketDisconnect` is caught
  at outer level)
- Backend must use `sherpa_error` (not `error`) for messages to reach the
  Sherpa store via event bus dispatch
- Always add `logger.info` to WS handlers — unlike HTTP, they don't auto-log

### Testing Notes
- httpx `Response.json()` / `.raise_for_status()` are **synchronous** — use
  `MagicMock()` not `AsyncMock()` for response objects
- httpx `client.post()` / `client.stream()` are **async** — use `AsyncMock()`
- conftest.py imports `from spectra_sherpa.app.db.base import Base` and `from spectra_sherpa.app.main import
  app` — needs full app context

---

## Codebase Fixes Still Needed

- [ ] Add error logging for silent startup crashes (wrap `seed_data()` in
      try/except with traceback in `startup.py`)
- [ ] Add Data & Privacy tab to frontend OR auto-enable sync on hybrid
      activation
- [ ] Add `--create-admin` CLI flag for first user setup
- [ ] Build activate-hybrid UI into pip-distributed static assets
- [ ] Update `modes.md` — mark `SECRET_KEY` as required for hybrid
- [ ] Update `DIGITAL_OCEAN.md` — add Path A (direct install), bcrypt fix,
      firewall, admin user sections
