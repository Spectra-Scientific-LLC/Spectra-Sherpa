# Enterprise Mode Configuration

**Enterprise Mode** is designed for public, internet-facing deployments. It enforces strict security, user registration, and rate limiting.

> **Naming note:** The runtime mode is `APP_MODE=enterprise`. The legacy value
> `APP_MODE=demo` is accepted as a deprecated alias and behaves identically.
> Separately, `SITE_PROFILE=demo` is a UI-only marketing label that controls
> branding on the login page (e.g., "Try SpectraSherpa" messaging). See the
> [DigitalOcean Guide](../deployment/DIGITAL_OCEAN.md) for `SITE_PROFILE` usage.

## Features
- **User Registration**: Visitors can sign up (optionally gated by a password).
- **Session Management**: JWT tokens with 1-hour expiry.
- **Rate Limiting**: Limits workflows per hour to prevent abuse.
- **Sandboxing**: Runs in a restricted environment (usually Docker).

## Configuration

Enterprise mode **requires** stricter configuration. The server will refuse to start if default secrets are detected.

```bash
# .env
APP_MODE=enterprise        # or APP_MODE=demo (deprecated alias)

# Security (MUST be changed from defaults)
SECRET_KEY=<long-random-string>
APP_API_KEY=<another-long-random-string>

# Networking
DOMAIN=demo.spectrasherpa.org
CORS_ORIGINS=https://demo.spectrasherpa.org

# Rate Limiting
RATE_LIMIT_EXECUTIONS=50  # Workflows per hour per user
SESSION_EXPIRY_HOURS=1

# Registration gate (optional)
ENTERPRISE_PASSWORD=       # If set, required for user registration
                           # (DEMO_PASSWORD is accepted as a deprecated alias)

# Marketing label (optional)
SITE_PROFILE=demo          # Show demo branding on the login page
```

## Middleware

Enterprise mode activates `EnterpriseEnforcementMiddleware` (in
`enterprise_enforcement.py`), which enforces rate limits, session expiry,
and registration gating. The legacy module name `demo_enforcement.py` and
class name `DemoEnforcementMiddleware` are still importable as aliases.

## Docker Deployment (DigitalOcean)
For a production-ready setup using Docker Compose (Nginx + Postgres + SpectraSherpa), refer to the [DigitalOcean Guide](../deployment/DIGITAL_OCEAN.md).
