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
├── experiments/                 # Uploaded experiment files
├── calibrations/                # Saved calibration/model artifacts
├── user/                        # User-scoped local state
├── references/                  # App-managed reference assets
│   └── spectrochempy_testdata_reference.pdf
├── exports/
│   ├── python/                  # Saved workflow Python exports
│   └── jupyter/                 # Saved workflow Jupyter exports
├── llm_dialogs/
│   └── conversations.json       # Persisted LLM dialog history
├── rate_limits/
│   ├── execution.json
│   ├── llm.json
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
- LLM dialog persistence
- rate-limit state
- demo quota state
- app-managed reference PDFs and similar generated reference assets

## What does not belong here

Some external tools have their own storage roots. The main example is **SpectroChemPy** test data, which may live under `scp.preferences.datadir` or `~/.spectrochempy/testdata`.

That data is treated as an **external source dataset**, not as SpectraSherpa-owned output.

SpectraSherpa may scan or import from it, and may create app-owned reference metadata or PDFs under `DATA_DIR/references/`, but the raw SpectroChemPy test tree is not the app data directory.

## Operational rule

If SpectraSherpa writes it, cache it, exports it, or manages it across restarts, it should be stored under a named subdirectory inside `DATA_DIR`.
