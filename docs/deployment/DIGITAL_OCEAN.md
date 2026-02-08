# Digital Ocean Deployment Guide

This guide describes how to deploy the Spectra Scientific Platform to Digital Ocean (or any Docker-capable VPS) using the production Docker configuration.

## Prerequisites

-   A Digital Ocean Droplet (recommended: 4GB RAM, 2 vCPUs for Hybrid/Cloud workloads).
-   `docker` and `docker-compose` installed on the server.
-   A domain name pointed to your droplet's IP (optional but recommended for SSL).

## Deployment Steps

### 1. Transfer Code
Clone the repository or transfer the files to your server:
```bash
scp -r ./Refactored root@your-droplet-ip:/opt/spectra-platform
```

### 2. Configure Environment
Create a `.env` file in `/opt/spectra-platform` (or rely on default defaults if safe, but setting a secret key is critical):

```bash
# /opt/spectra-platform/.env
SECRET_KEY=generate-a-secure-random-string
APP_MODE=demo  # Valid values: 'local', 'hybrid', or 'demo'
CLOUD_COMPUTE_URL=  # Leave empty if this IS the cloud node
```

### 3. Build and Run
Navigate to the deploy directory and start the stack:

```bash
cd /opt/spectra-platform/deploy
docker compose -f docker-compose.prod.yaml up -d --build
```

### 4. Verify Deployment
-   Open your browser to `http://your-droplet-ip`.
-   **Frontend**: Nginx services the Vue app on port 80.
-   **Backend**: Proxied via `/api`.

## Hybrid Mode Configuration

To use this Cloud instance as a compute offloader for a Local instance:

1.  **On Cloud Instance**: Ensure it is running and accessible (e.g., `http://203.0.113.1`).
2.  **On Local Instance**:
    -   Open `Settings`.
    -   Set **Execution Mode** to `Hybrid`.
    -   Set **Cloud Compute URL** to `http://203.0.113.1`.
    -   (Optional) If you implemented Auth on the compute endpoint, add the API Key.

## Troubleshooting

**View Logs:**
```bash
docker compose -f docker-compose.prod.yaml logs -f
```

**Restart Services:**
```bash
docker compose -f docker-compose.prod.yaml restart
```
