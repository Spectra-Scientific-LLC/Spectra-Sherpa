# App Data Directory

SpectraSherpa has a single **app data directory** for app-owned state and generated outputs.

Defaults:

- Source checkout: `<repo>/data`
- Installed app: `~/.spectra_sherpa`
- Override: `DATA_DIR=/path/to/data` or `spectra-sherpa --data-dir /path/to/data`

This directory is the canonical home for anything SpectraSherpa creates itself:

```text
DATA_DIR/
├── spectra_platform.db          # Application database
├── .secret_key                  # Local secret for JWT/session stability
├── .startup.lock                # One-time startup leader lock
├── .metadata_overrides/         # Data/Explore override sidecars
├── experiments/                 # Uploaded experiment files
├── calibrations/                # Saved calibration/model artifacts
├── user/                        # User-scoped local state
├── references/                  # App-managed reference assets
│   └── spectrochempy_testdata_reference.pdf
├── exports/
│   ├── python/                  # Saved workflow Python exports
│   └── jupyter/                 # Saved workflow Jupyter exports
├── llm_dialogs/                 # Reserved directory name; OSS itself
│                                # writes nothing here. May be used by
│                                # an extension package that registers
│                                # an AIServiceProvider.
├── rate_limits/
│   ├── execution.json
│   ├── llm.json                 # Reserved filename; OSS itself writes
│   │                            # nothing here. May be populated by an
│   │                            # AI-provider extension.
│   ├── auth_login.json
│   └── auth_register.json
├── demo/
│   └── limits.json
└── nist_library/
    └── downloaded/
```

## What belongs here

These artifacts should always live under `DATA_DIR`:

- workflow Python exports
- workflow Jupyter exports
- Data/Explore override sidecars for names, units, quantity, and time-series flags
- rate-limit state
- demo quota state
- app-managed reference PDFs and similar generated reference assets

The OSS BYO chat assistant (`POST /api/v1/chat/stream`) does not persist
transcripts on the server — chat messages flow straight through to your
configured `CHAT_ENDPOINT_URL`, and the UI keeps any local summary in
browser storage only. The `llm_dialogs/` directory is a reserved path
for AI-provider extensions; OSS itself writes nothing there.

## What does not belong here

Some external tools have their own storage roots. The main example is **SpectroChemPy** test data, which may live under `scp.preferences.datadir` or `~/.spectrochempy/testdata`.

That data is treated as an **external source dataset**, not as SpectraSherpa-owned output.

SpectraSherpa may scan or import from it, and may create app-owned reference metadata or PDFs under `DATA_DIR/references/`, but the raw SpectroChemPy test tree is not the app data directory.

Experiment-backed workflows, template materialization, and exported workflow bundling resolve files against the active `DATA_DIR` at runtime. This avoids stale path capture when the app is launched under a different mode, test harness, or packaged deployment.

## Exported bundle convention

When you export a workflow as Python or Jupyter only, the generated code expects a sibling `data/` directory by default. When you export as a zip bundle, SpectraSherpa writes the source files into that `data/` folder and includes manifests describing the workflow graph and prepared-data overrides.

You can override the runtime data location for exported code with `SHERPA_DATA_DIR`.

## Operational rule

If SpectraSherpa writes it, cache it, exports it, or manages it across restarts, it should be stored under a named subdirectory inside `DATA_DIR`.
