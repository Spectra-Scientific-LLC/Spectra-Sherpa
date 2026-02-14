# Demo Mode Configuration

**Demo Mode** is designed for public, internet-facing deployments. It enforces strict security, user registration, and rate limiting.

## Features
- **User Registration**: Visitors can sign up (optionally gated by a password).
- **Session Management**: JWT tokens with 1-hour expiry.
- **Rate Limiting**: Limits workflows per hour to prevent abuse.
- **Sandboxing**: Runs in a restricted environment (usually Docker).

## Configuration

Demo mode **requires** stricter configuration. The server will refuse to start if default secrets are detected.

```bash
# .env
APP_MODE=demo

# Security (MUST be changed from defaults)
SECRET_KEY=<long-random-string>
APP_API_KEY=<another-long-random-string>

# Networking
DOMAIN=demo.spectrasherpa.org
CORS_ORIGINS=https://demo.spectrasherpa.org

# Rate Limiting
RATE_LIMIT_EXECUTIONS=50  # Workflows per hour per user
SESSION_EXPIRY_HOURS=1
```

## Docker Deployment (DigitalOcean)
For a production-ready setup using Docker Compose (Nginx + Postgres + SpectraSherpa), refer to the [DigitalOcean Guide](../deployment/DIGITAL_OCEAN.md).
