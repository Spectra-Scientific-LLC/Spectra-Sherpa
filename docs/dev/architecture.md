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

### Mode System

SpectraSherpa supports multiple deployment modes (`local`, `hybrid`, `enterprise`). Mode-checking hooks in `create_app()` lifespan callbacks allow extension packages to add middleware. Without extensions, non-local code paths fall through to safe defaults.

## High-Level Structure

```
src/spectra_sherpa/
├── app/
│   ├── core/           # Configuration, Security, Mode Policy
│   ├── lib/            # Core libraries (SherpaDataset, scp_compat, adapters)
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

**Runtime mode** (`APP_MODE`): `local` | `hybrid` | `enterprise` — controls auth, egress, and rate limiting.

Mode logic is centralized in `spectra_sherpa.app.core.mode_policy`.
- **Local:** No auth, single-user, desktop convenience.
- **Hybrid:** JWT + API key auth for remote clients, loopback exemption.
- **Enterprise:** Full auth for all clients, rate limiting, multi-user.

### 2. The Node Graph
SpectraSherpa is fundamentally a Directed Acyclic Graph (DAG) engine.
- **Nodes** (`spectra_sherpa.app.services.dag.nodes.*`) are self-contained units of logic.
- **Workflows** are serializable JSON structures defining the graph.
- **Execution** is topological. Data flows from `DataSourceNode` -> `PreprocessingNode` -> `ModelingNode`.

### 3. Data Containers

The DAG engine uses two data container types depending on the runtime environment:

**SherpaDataset** (`spectra_sherpa.app.lib.sherpa_dataset`) — The canonical DAG runtime container. Pydantic-backed, AI-native, with typed fields and zero external dependencies. Key components:
- `X`: 2D numpy array (n_samples, n_features) with shape invariants enforced at construction
- `spectral_axis` / `sample_axis`: Typed axis metadata (`SpectralAxis`, `SampleAxis`)
- `target`: Optional target values for supervised learning
- `domain`: `DomainContext` — technique, sample type, measurement mode (asserted + inferred)
- `provenance`: Append-only `Provenance` log with `state_effects` per entry
- `quality`: `QualityMetrics` with scoped `EvaluationResult` entries
- `backend`: Origin tag (`"numpy"`, `"scp"`, `"sklearn"`)

Edge adapters in `app/lib/adapters/` handle all external format conversions (numpy, sklearn, SpectroChemPy).

**NDDataset** (SpectroChemPy) — Used by 11 SCP-only nodes that require SpectroChemPy's coordinate-aware algorithms (ALS baseline, MSC, PCA, PLS, MCR, EFA, SIMPLISMA, etc.). Round-trip adapters (`from_nddataset`, `to_nddataset`) in `adapters/scp_adapter.py` convert at SCP boundaries.

### 4. SpectroChemPy Optional Dependency

SpectroChemPy is an optional dependency (`pip install spectra-sherpa[scp]`). The `scp_compat.py` module provides:
- `HAS_SCP` boolean flag
- `require_scp()` guard function
- Stub `NDDataset`/`Coord` classes when SCP is absent (safe for `isinstance()`)

Each node declares `requires_scp=True` in its `NodeMetadata` if it needs SCP. Without SCP, ~38 nodes run on pure numpy/scipy/sklearn via SherpaDataset. With SCP, 11 additional nodes are unlocked.

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

17 linear Alembic migrations manage schema evolution.
