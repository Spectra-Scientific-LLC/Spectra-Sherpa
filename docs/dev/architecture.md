# System Architecture

SpectraSherpa follows a "Clean Architecture" pattern with a strict separation between the core domain logic and the delivery mechanism (FastAPI).

## Overview

```
┌─────────────────────────────────────────────────────┐
│                  Frontend (Vue 3)                    │
│  Workflow Builder ──REST──► FastAPI REST API         │
│  Workflow Builder ──WS────► /ws                      │
└───────────────────────┬─────────────┬───────────────┘
                        │             │
┌───────────────────────▼─────────────▼───────────────┐
│                  Backend (FastAPI)                    │
│                                                      │
│  REST API ──► DAG Executor ──► Node Registry         │
│  WebSocket ──► DAG Executor    ┌──────────────────┐  │
│                 │              │ DataSource        │  │
│                 │ topological  │ Preprocessing     │  │
│                 │ sort         │ Modeling          │  │
│                 ▼              │ Visualization     │  │
│              Results           └──────────────────┘  │
│                                                      │
│  Auth (mode-dependent):                              │
│    local → no auth │ hybrid → JWT+API │ enterprise   │
│                                                      │
│  DB: SQLite (local) or PostgreSQL (enterprise)       │
└──────────────────────────────────────────────────────┘
```

## High-Level Structure

```
src/spectra_sherpa/
├── app/
│   ├── core/           # Configuration, Security, Mode Policy
│   ├── lib/            # Core libraries (AnalysisDataset, scp_compat)
│   ├── models/         # Pydantic models & SQLAlchemy tables
│   ├── schemas/        # API request/response schemas
│   ├── services/       # Business logic (DAG, Metadata, LLM)
│   │   ├── dag/        # Workflow engine & Node definitions
│   │   └── llm/        # AI Service integration
│   └── api/            # FastAPI Routers
└── static/             # Compiled Vue frontend
```

## Core Concepts

### 1. The Mode Contract
The application has two orthogonal configuration axes:

**Runtime mode** (`APP_MODE`): `local` | `hybrid` | `enterprise` — controls auth, egress, and rate limiting.
**Experience profile** (`SITE_PROFILE`): `demo` | `production` | `internal` | unset — controls UI experience and feature gating.

Mode logic is centralized in `spectra_sherpa.app.core.mode_policy`.
- **Local:** No auth, no egress, single-user.
- **Hybrid:** JWT + API key auth for remote clients, loopback exemption, optional cloud offload.
- **Enterprise:** Full auth for all clients, rate limiting, multi-user.

When `SITE_PROFILE=demo`, the **Demo Contract** (`DemoContract` in `config.py`) restricts capabilities (e.g., no data upload) and provides conversion messaging. Enterprise enforcement (password gating, session expiry, CORS validation, SQLite prohibition) lives in `spectra-server` and is injected via `create_app()` hooks.

### 2. The Node Graph
SpectraSherpa is fundamentally a Directed Acyclic Graph (DAG) engine.
- **Nodes** (`spectra_sherpa.app.services.dag.nodes.*`) are self-contained units of logic.
- **Workflows** are serializable JSON structures defining the graph.
- **Execution** is topological. Data flows from `DataSourceNode` -> `PreprocessingNode` -> `ModelingNode`.

### 3. Data Containers

The DAG engine uses two data container types depending on the runtime environment:

**AnalysisDataset** (`spectra_sherpa.app.lib.analysis_dataset`) — The canonical DAG runtime container. All portable nodes produce and consume this type. Fields:
- `X`: 2D numpy array (n_samples, n_features)
- `x_axis` / `y_axis`: `AxisInfo` (values, labels, units, title)
- `target`: Optional target values for supervised learning
- `meta`: Arbitrary metadata dict (includes `processing_history`)
- `provenance`: Processing history list (synced with `meta["processing_history"]`)
- `backend`: Origin tag (`"numpy"`, `"scp"`, `"sklearn"`)

AnalysisDataset provides NDDataset-compatible properties (`.data`, `.x`, `.y`, `.shape`, `.ndim`, `.copy()`) so node code works with either type. The `to_dict()` method emits `type: "NDDataset"` wire format for frontend backward compatibility.

**NDDataset** (SpectroChemPy) — Used by 11 SCP-only nodes that require SpectroChemPy's coordinate-aware algorithms (ALS baseline, MSC, PCA, PLS, MCR, EFA, SIMPLISMA, etc.). Round-trip adapters in `scp_compat.py` convert between the two types.

### 4. SpectroChemPy Optional Dependency

SpectroChemPy is an optional dependency (`pip install spectra-sherpa[scp]`). The `scp_compat.py` module provides:
- `HAS_SCP` boolean flag
- `require_scp()` guard function
- Stub `NDDataset`/`Coord` classes when SCP is absent (safe for `isinstance()`)

Each node declares `requires_scp=True` in its `NodeMetadata` if it needs SCP. Without SCP, ~38 nodes run on pure numpy/scipy/sklearn via AnalysisDataset. With SCP, 11 additional nodes are unlocked.

### 5. Type System

All node ports use typed connections via `TypeRegistry`:
- URIs: `spectrasherpa://types/{TypeName}/{Major.minor}`
- `registry.json` defines all types with subtype relationships
- Connection validator checks type compatibility + version constraints
- `NodeResult` dataclass wraps outputs + diagnostics for type-safe results

### 6. Scientific Integrity
- **Metadata Propagation:** Every node automatically appends its operation to the `processing_history` metadata via `meta_helpers.add_processing_step()`.
- **Unit Awareness:** The system tracks units (wavenumber vs nm, absorbance vs transmittance) to prevent invalid operations.
- **Provenance:** Full processing chain recorded in dataset metadata for audit trails.

### 7. WebSocket Lifecycle

Real-time communication uses a single WebSocket endpoint at `/ws`. Clients send JSON messages with an `"action"` key; the server responds with messages using a `"type"` key.

1. **Connect** — Client opens `/ws` with auth token (if hybrid/enterprise mode)
2. **Subscribe** — Client sends `{"action": "subscribe", "workflow_id": "..."}` to watch a workflow
3. **Unsubscribe** — Client sends `{"action": "unsubscribe", "workflow_id": "..."}`
4. **LLM Chat** — Client sends `{"action": "llm_chat", ...}` → server streams `llm_start`, `llm_chunk`, `llm_done` responses
5. **Sherpa AI** — `{"action": "sherpa_chat" | "sherpa_sync" | "sherpa_decide", ...}`
6. **MCP Tools** — `{"action": "tool_list"}` or `{"action": "tool_invoke", ...}`
7. **Errors** — Server sends `{"type": "error", "detail": "..."}` for unknown actions or failures

The `useJobStore` Pinia store manages WebSocket state on the frontend.

### 8. Database Models

SQLAlchemy models with SQLite backend:
- **Project**: Self-referencing FK (folders), linked workflows + experiments
- **ProjectVersion**: Snapshot JSON with version numbering
- **ProjectScript**: Generated or manual Python scripts linked to projects
- **Workflow**: Node/edge graph JSON with technique/sample_type
- **Experiment**: Execution records with parameters and results
- **ExecutionRun**: Run history with diagnostics and labels
- **FolderWatch**: Automated polling configuration
- **BatchPrediction**: Per-file prediction results

16 linear Alembic migrations manage schema evolution.
