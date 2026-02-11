# Session Summary — 2026-02-09

## What Was Accomplished

### 1. Dependency Fix
- Pinned `bcrypt = ">=4.0.1,<4.1"` in `pyproject.toml` to fix passlib 1.7.4 incompatibility

### 2. One-Click Hybrid Activation (commit `c2ea3d0`)
- Rebuilt frontend static assets to include activate/deactivate-hybrid buttons in IntegrationsTab
- Added auto-enable of `allow_spectrasherpa_sync` during hybrid activation (config.py)
- Users no longer need to manually flip egress sync via sqlite3

### 3. DigitalOcean Server Deployment (Path A: Direct Install)
- **Domain:** `https://demo.spectrascientific.ai`
- **Stack:** Caddy (auto-TLS) → uvicorn (127.0.0.1:8000), systemd service
- **Repos:** `/home/spectra/spectra-platform/` (Repo 1 + Repo 2)
- **Venv:** `/home/spectra/venv/`
- **Users:** `guest` (superuser), `hybrid_client` (API key holder)
- **Firewall:** SSH(22), HTTP(80), HTTPS(443) only — port 8000 not exposed

#### systemd Service (`/etc/systemd/system/spectrasherpa.service`)
```ini
[Unit]
Description=SpectraSherpa Server
After=network.target

[Service]
User=spectra
WorkingDirectory=/home/spectra/spectra-platform
EnvironmentFile=/home/spectra/spectra-platform/.env
Environment=PATH=/home/spectra/venv/bin:/usr/bin
ExecStart=/home/spectra/venv/bin/uvicorn spectrasherpa_server.app:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

#### Caddy (`/etc/caddy/Caddyfile`)
```
demo.spectrascientific.ai {
    reverse_proxy 127.0.0.1:8000
}
```

### 4. Remote Access Fixes (commit `ce51f1d`)
- **Auth middleware:** SPA routes (non-API, non-WS) now bypass auth — they only serve index.html
- **Router guard:** Hybrid mode `initHybridUser()` falls through to JWT login for remote clients
- **Issue:** Loopback-exempt hybrid mode was blocking all remote browser access

### 5. Manual Server Patches
These files were manually patched on the DO server via scp/nano (match local commits):
- `security.py` — SPA routes bypass
- `frontend/static/` — rebuilt assets with activate-hybrid UI

---

## Commits Made
1. `2bf36f2` — Pin bcrypt<4.1, CLI port-clearing, deployment lessons
2. `c2ea3d0` — Enable one-click hybrid activation from Settings UI
3. `ce51f1d` — Fix remote access: SPA routes, hybrid router guard

---

## Next: Sherpa Engine Architecture

The user wants a dedicated AI advisor service powered by Anthropic Claude.

### Two Channels
| Channel | Key Source | Context | Purpose |
|---------|-----------|---------|---------|
| **LLM Chat** | User's own BYOK key | None (user provides via chat) | Generic assistant |
| **Sherpa Advisor** | Spectra Scientific's Anthropic key | Auto-injected workflow context | Domain-expert advisor |

### Requirements
- Anthropic Claude as the engine (configurable model via `SHERPA_ENGINE_MODEL`)
- Spectra Scientific pays (server-side `SHERPA_ENGINE_API_KEY`)
- Auto-injects: current workflow nodes, data shape, processing history, spectral technique
- Serves both local hybrid clients AND DO browser users
- The LLM Chat channel remains unchanged (user BYOK, no context injection)

### Architecture
```
Client (local hybrid or DO browser)
  ├── LLM Chat ──→ User's BYOK key ──→ OpenAI/Anthropic (no context)
  └── Sherpa Advisor ──→ DO Server ──→ Anthropic Claude (SS key, context-injected)
```

### Open Questions
- Where does context injection happen? (server-side on DO, or client sends context in WS message?)
- Rate limiting per user for Sherpa Advisor (SS is paying)?
- Should Sherpa Advisor responses be cached/logged for analytics?
- MCP tool access for Sherpa Advisor? (e.g., can it call `suggest_preprocessing`?)
