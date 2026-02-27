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
│                 │              │ Data / Synthesis  │  │
│                 │ topological  │ Preprocessing     │  │
│                 │ sort         │ Exploratory       │  │
│                 ▼              │ Regression        │  │
│              Results           │ Classification    │  │
│                │               │ Clustering        │  │
│                │               │ Validation        │  │
│                │               │ Output / Deploy   │  │
│                │               └──────────────────┘  │
│                ▼                                      │
│          ModelStore (disk)                            │
│          manifest.json + arrays.npz                  │
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
│   ├── lib/            # Core libraries (SherpaDataset, adapters)
│   │   ├── adapters/   # Format converters (SCP, sklearn, numpy)
│   │   └── sherpa_dataset.py  # Canonical data container
│   ├── models/         # SQLAlchemy ORM models
│   ├── schemas/        # Pydantic request/response schemas
│   ├── services/       # Business logic
│   │   ├── dag/        # Workflow engine & node definitions
│   │   │   ├── nodes/
│   │   │   │   ├── modeling/        # PCA, PLS, MCR, EFA, etc.
│   │   │   │   ├── classification/  # PLSDA, KNN, SIMCA
│   │   │   │   ├── preprocessing.py
│   │   │   │   ├── data.py
│   │   │   │   └── ...
│   │   │   ├── executor.py    # DAG execution engine
│   │   │   └── node_base.py   # Node, NodeMetadata, registry
│   │   ├── model_store.py     # Model artifact persistence
│   │   └── llm/               # AI service integration
│   ├── types/          # Type registry (registry.json + schemas)
│   └── api/            # FastAPI routers
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
- **Nodes** (`spectra_sherpa.app.services.dag.nodes.*`) are self-contained units of logic organized into 11 categories: `data`, `synthesis`, `preprocessing`, `exploratory`, `regression`, `classification`, `clustering`, `validation`, `custom_algo`, `output`, `deploy`.
- **Workflows** are serializable JSON structures defining the graph.
- **Execution** is topological. Data flows from `DataSourceNode` -> `PreprocessingNode` -> modeling/classification/clustering nodes -> output/deploy nodes.
- **Consolidated nodes** merge related algorithms behind a `method` dropdown (e.g., `preprocess.smooth` supports Savitzky-Golay, Whittaker, and Gaussian).
- **Conditional visibility** (`NodeParameter.visible_when`) hides irrelevant parameters in the Inspector based on the selected method.

### 3. Data Containers

The DAG engine uses two data container types depending on the runtime environment:

**SherpaDataset** (`spectra_sherpa.app.lib.sherpa_dataset`) — The canonical DAG runtime container. Pydantic-backed, AI-native, with typed fields and zero external dependencies. Key components:
- `X`: nD numpy array (dim 0 = samples, dim -1 = features; inner dimensions for hyperspectral/time-resolved data) with shape invariants enforced at construction
- `feature_axis` / `sample_axis`: Typed axis metadata (`SpectralAxis`, `SampleAxis`, `TimeAxis`, `MZAxis`, etc.)
- `target`: Optional target values for supervised learning
- `domain`: `DomainContext` — technique, sample type, measurement mode (asserted + inferred)
- `provenance`: Append-only `Provenance` log with `state_effects` per entry
- `quality`: `QualityMetrics` with scoped `EvaluationResult` entries
- `backend`: Origin tag (`"numpy"`, `"scp"`, `"sklearn"`)

Edge adapters in `app/lib/adapters/` handle all external format conversions (numpy, sklearn, SpectroChemPy).

**NDDataset** (SpectroChemPy) — Used by SCP-only nodes that require SpectroChemPy's coordinate-aware algorithms (rubberband baseline, PCA, PLS, MCR, EFA, SIMPLISMA, etc.). Round-trip adapters (`from_nddataset`, `to_nddataset`) in `adapters/scp_adapter.py` convert at SCP boundaries.

### 4. SpectroChemPy Optional Dependency

[SpectroChemPy](https://www.spectrochempy.fr/) is an optional dependency (`pip install spectra-sherpa[scp]`) developed by A. Travert & C. Fernandez at LCS (ENSICAEN/CNRS), licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) (BSD-compatible).

The `scp_compat.py` module provides:
- `HAS_SCP` boolean flag
- `require_scp()` guard function
- Stub `NDDataset`/`Coord` classes when SCP is absent (safe for `isinstance()`)

Each node declares `requires_scp=True` in its `NodeMetadata` if it needs SCP. Consolidated nodes that mix SCP and non-SCP code paths (e.g., `classification.predict`) gate SCP at the method level instead. Without SCP, ~40 nodes run on pure numpy/scipy/sklearn via SherpaDataset. With SCP, 12 additional nodes are unlocked.

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

SQLAlchemy models with SQLite (local) or PostgreSQL (enterprise) backend:

```
User
├── Project                      # Container for related work
│   ├── Experiment               # Raw spectral data collection
│   │   └── ExperimentFile       # Individual data files (.csv, .jdx, .spc, ...)
│   │       └── ExpVersion       # File version snapshots
│   ├── Workflow                 # DAG-based analysis pipeline
│   │   ├── WorkflowNode         # Computation units in the graph
│   │   ├── WorkflowEdge         # Connections between nodes
│   │   ├── WorkflowVersion      # Immutable snapshots on each save
│   │   └── ExecutionRun         # Saved workflow execution results
│   │       └── BatchPrediction  # Per-file results (batch/deploy)
│   ├── ModelArtifact            # Trained model (PCA, PLS, MCR, ...)
│   │   ├── manifest.json        # Metadata + metrics (on disk)
│   │   └── arrays.npz           # Numpy arrays (on disk)
│   ├── ProjectScript            # Python exports
│   └── ProjectVersion           # Immutable project snapshots
├── WorkflowFolder               # UI organization
└── FolderWatch                  # Automated file polling
```

**Key relationships:**

| Entity | Belongs To | Cascade |
|--------|-----------|---------|
| Experiment | Project (optional) | SET NULL on project delete |
| Workflow | User + Project (optional) | CASCADE on user delete |
| WorkflowVersion | Workflow | CASCADE |
| ExecutionRun | Workflow + WorkflowVersion | CASCADE / SET NULL |
| BatchPrediction | ExecutionRun | CASCADE |
| ModelArtifact | User + Project (optional) + Workflow (optional) | CASCADE on user, SET NULL on project/workflow |
| ProjectScript | Project | CASCADE |
| ProjectVersion | Project | CASCADE |

**Cross-entity references:**

- `ExecutionRun.model_ids` — JSON array of `artifact_uid` strings (models produced or used)
- `BatchPrediction.model_id` — String `artifact_uid` (primary model for this prediction)
- `ProjectScript.source_workflow_id` — Tracks auto-generated scripts from workflows

Alembic migrations manage schema evolution. See `alembic/versions/` for the full migration history.

### 9. Model Artifact System

Training nodes (PCA, PLS, MCR, PLSDA, KNN, SIMCA, etc.) emit a `_model_artifact` key in their results. The executor intercepts this and persists the model:

```
Training Node ──► _model_artifact ──► Executor._process_model_artifact()
                                           │
                                           ▼
                                      ModelStore.save()
                                           │
                                    ┌──────┴──────┐
                                    │             │
                              manifest.json   arrays.npz
                              (metadata)      (numpy data)
                                    │
                                    ▼
                              ModelArtifact DB record
                              (artifact_uid, metrics, provenance)
```

**Extract classes** in `lib/adapters/scp_extractors.py` normalize version-specific SpectroChemPy model outputs:
- `PCAExtract`, `PLSExtract`, `MCRExtract`, `EFAExtract`, `SIMPLISMAExtract`
- `PLSDAExtract`, `KNNExtract`, `SIMCAExtract`

Each implements `from_scp()` (extract from SCP model), `to_artifact()` (serialize), `from_artifact()` (deserialize), and `predict()`/`transform()` (inference).

The **Load & Apply Model** node (`model.load_apply`) loads any saved artifact and dispatches to the correct Extract class for inference on new data.
