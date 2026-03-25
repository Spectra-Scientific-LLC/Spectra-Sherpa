# Configuration

SpectraSherpa works out-of-the-box with zero configuration. However, you can customize data storage and enable optional AI features.

## Data Storage
By default, all your data is stored in your home directory:
```
~/.spectra_sherpa/
├── spectra_platform.db    # Your local database
├── experiments/           # Uploaded files and results
├── calibrations/          # Saved models
├── exports/               # Saved Python and Jupyter workflow exports
├── llm_dialogs/           # Saved LLM dialog state
├── references/            # App-managed reference assets
└── nist_library/          # Downloaded reference spectra
```

See [App Data Directory](data-directory.md) for the complete layout and the distinction between app-owned output and external source data such as SpectroChemPy testdata.

To use a different location (e.g., an external drive), use the `--data-dir` flag:
```bash
spectra-sherpa --data-dir /Volumes/ExternalDrive/SherpaData
```

Uploaded experiment files, materialized template/example data, and saved Data/Explore overrides are all resolved relative to the active data directory. That means the same workflow can follow different storage roots cleanly across local, hybrid, enterprise, test, and packaged environments.

## Deployment Modes

SpectraSherpa supports three runtime modes:

- `local`: single-user desktop mode with no login requirement
- `hybrid`: mixed local/remote deployment with authenticated remote access
- `enterprise`: fully authenticated multi-user deployment

The frontend reads the active mode from the backend configuration response. If that config request fails, SpectraSherpa does not fall back to local mode. Public pages may still render, but protected routes stay unavailable until the backend config is reachable again.

## Common Environment Variables

These are the highest-signal settings for most deployments:

| Variable | What it controls | Notes |
|----------|------------------|-------|
| `APP_MODE` | Runtime mode | `local`, `hybrid`, or `enterprise` |
| `CORS_ORIGINS` | Browser origins allowed to call the backend | Required for non-local deployments |
| `EGRESS_ENABLED` | Whether external network calls are allowed | Needed for BYOK LLM features and NIST fetches |
| `MAX_LLM_REQUESTS_PER_HOUR` | Per-user hourly limit for paid Sherpa/LLM usage | Superusers bypass this limit |
| `SHERPA_ENGINE_API_KEY` | Deployment key for server-backed Sherpa features | Used in hybrid/enterprise/demo |
| `SHERPA_ENGINE_MODEL` | Server-side model name for Sherpa | Used in hybrid/enterprise/demo |

`RATE_LIMIT_EXECUTIONS` is no longer the primary user-facing quota for normal hybrid or enterprise use. Paid AI usage is governed by `MAX_LLM_REQUESTS_PER_HOUR`. Demo-profile execution quotas still exist separately under the demo contract.

## Exported Workflow Data Paths

Exported Python scripts and notebooks look for source files in a `data/` folder next to the export by default. You can override that location with the `SHERPA_DATA_DIR` environment variable.

Zip exports package the runnable script, notebook, requirements, source data files, and workflow/prepared-data manifests together so the exported workflow can resolve the same input files with relative paths.

## Enabling AI Features (Optional)
To use the BYOK LLM chat or **NIST Library Search**, you need to enable network access and provide API keys.

1.  Create a `.env` file in the folder where you run `spectra-sherpa`:

    ```bash
    # .env
    EGRESS_ENABLED=true
    
    # Add your LLM key (only one provider needed)
    DEEPSEEK_API_KEY=sk-...
    ```

2.  Restart the application.

3.  Alternatively, you can add keys directly in the UI under **Settings > API Keys**.

> **Privacy Note:** In Local Mode, your API keys are stored encrypted on your machine. Data is only sent to the AI provider when you explicitly use an AI feature such as the BYOK chat assistant.

## Sherpa Advisor in Hybrid / Enterprise / Demo

In `hybrid`, `enterprise`, and `demo` deployments, Sherpa Advisor and Data Story are typically backed by a server-side Sherpa deployment rather than local BYOK settings.

- Configure the deployment with `SHERPA_ENGINE_API_KEY` and related server settings.
- In the UI, use **Settings > Integrations** to verify the connection.
- When the deployment is already configured, the button is **Validate Connection** rather than **Test Connection**.
- In enterprise/demo mode, this integration check stays available even when the deployment is already connected.

## Rate Limiting

For multi-user deployments, the main auditable user quota is:

```bash
MAX_LLM_REQUESTS_PER_HOUR=100
```

This limit applies to Sherpa Advisor, Data Story, and other paid LLM-backed features. Superusers bypass it. If you run with `SITE_PROFILE=demo`, the separate demo contract quotas still apply in addition to this hourly limit.
