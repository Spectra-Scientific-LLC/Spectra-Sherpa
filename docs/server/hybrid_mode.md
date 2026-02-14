# Hybrid Mode Configuration

**Hybrid Mode** allows local instances of SpectraSherpa to offload heavy computation (like training large models) to a central server while keeping data local.

## Features
- **GPU Offload**: Local clients send data -> Server computes -> Server returns results.
- **Identity Linking**: Local clients "adopt" the user identity from the server.
- **Shared Licensing**: Centralized management of LLM quotas/keys.

## Configuration

To run a server in Hybrid Mode:

```bash
# .env
APP_MODE=hybrid
HOST=0.0.0.0  # Listen on all interfaces
PORT=8000

# Security (Required for remote clients)
SPECTRASHERPA_API_KEY=sk-your-secret-key
```

### Server Side
Start the server:
```bash
spectra-sherpa
```
The server will now accept connections from any client that presents the correct `SPECTRASHERPA_API_KEY`.

### Client Side
The local user configures their instance to talk to your server:
```bash
# Local .env
APP_MODE=hybrid
CLOUD_COMPUTE_URL=http://your-server-ip:8000
CLOUD_API_KEY=sk-your-secret-key
```

## Security Model
- **Localhost connections**: Bypass authentication (assumed trusted admin/developer).
- **Remote connections**: MUST provide `Authorization: Bearer <API_KEY>` or the `X-API-Key` header.
