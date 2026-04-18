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
├── references/            # App-managed reference assets
└── nist_library/          # Downloaded reference spectra
```

> The OSS chat assistant (see "Optional: BYO Chat Assistant" below) is
> single-turn and holds no server-side transcript; chat history lives only
> in your browser's local storage.

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
| `EGRESS_ENABLED` | Whether external network calls are allowed | Needed for the BYO chat assistant and NIST fetches |
| `CHAT_ENDPOINT_URL` | Base URL of an OpenAI-compatible chat completions endpoint | Enables the OSS BYO chat assistant |
| `CHAT_ENDPOINT_KEY` | API key sent as `Authorization: Bearer <key>` | Paired with `CHAT_ENDPOINT_URL` |
| `CHAT_ENDPOINT_MODEL` | Model identifier for the BYO chat assistant | Default: `deepseek-chat` |

AI features beyond the BYO chat assistant are not part of the OSS
distribution and are not configured through OSS environment variables.

## Exported Workflow Data Paths

Exported Python scripts and notebooks look for source files in a `data/` folder next to the export by default. You can override that location with the `SHERPA_DATA_DIR` environment variable.

Zip exports package the runnable script, notebook, requirements, source data files, and workflow/prepared-data manifests together so the exported workflow can resolve the same input files with relative paths.

## Optional: BYO Chat Assistant

OSS SpectraSherpa ships a minimal "bring your own endpoint" chat assistant.
It is a thin HTTP proxy to any OpenAI-compatible `/chat/completions`
endpoint. It performs no prompt engineering, no tool calls, no persistence,
and no agent loop — it exists so local-mode users have a simple chat box
backed by a provider they control.

To enable it:

1.  Create a `.env` file in the folder where you run `spectra-sherpa`:

    ```bash
    # .env
    EGRESS_ENABLED=true

    CHAT_ENDPOINT_URL=https://api.deepseek.com/v1
    CHAT_ENDPOINT_KEY=sk-...
    CHAT_ENDPOINT_MODEL=deepseek-chat     # optional, shown is the default
    ```

2.  Restart the application.

Any OpenAI-compatible endpoint works (DeepSeek, OpenAI, Groq, Together,
a local vLLM / Ollama OpenAI-compatible server, etc.). The chat UI is
gated by a `chatAssistant` capability flag that `/api/v1/config` sets to
`true` whenever both `CHAT_ENDPOINT_URL` and `CHAT_ENDPOINT_KEY` are
configured.

The endpoint that backs this UI is `POST /api/v1/chat/stream` (OSS-owned,
single-turn, server-sent-events streaming). It is deliberately *not*
under `/api/v1/llm/*`; that prefix is reserved for extension packages
that register an `AIServiceProvider` implementation and is not served by
OSS alone.

> **Privacy note:** In local mode, `CHAT_ENDPOINT_KEY` is read from your
> `.env` (or process environment) and is only sent to the chat endpoint
> you configured, and only when you actively use the chat panel. Your
> spectral data is not attached to chat messages unless you paste it in.
