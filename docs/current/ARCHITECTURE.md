# Spectra Scientific Platform - Architecture Document

**Version:** 1.4
**Date:** 2026-01-30
**Status:** Active Development (Unified app/lib/, legacy libs retired)

---

## 🎯 Executive Summary

A **modular monolithic** web application for spectral data analysis, combining experiment management, synthetic data generation, NIST library access, and AI-assisted analysis into a unified platform.

**Key Principles:**
- **Local-compute-first:** All computation defaults to local machine; network only for NIST/LLM
- **File-based storage:** Raw spectra remain as files (scientific tradition)
- **Git-like versioning:** Content-addressable storage for efficient snapshots
- **Three deployment modes:** Local (single-user, no auth), Hybrid (API-key linked identity from server), Enterprise/Cloud (multi-user JWT auth)
- **Performance-focused:** WAL mode, caching, resource limits, crash-safe jobs
- **Exportable:** Scientists live in Excel/Origin/Matlab - export everything
- **Cloud-extensible:** Architecture supports remote compute via spectrasherpa-server

---

## 🔐 Authentication & Data Access

**See detailed documentation:**
- [AUTHENTICATION.md](AUTHENTICATION.md) - Three-mode deployment model, hybrid identity linking, API key architecture
- [DATA_SOURCES.md](DATA_SOURCES.md) - Free databases (NIST, HITRAN, EPA), premium sources, licensing

**Key Points:**
- **Local mode:** Implicit single user, no login, all features except admin/cloud
- **Hybrid mode:** API-key linked identity — `SPECTRASHERPA_API_KEY` validates against spectrasherpa-server at startup, enriches the local user with server-side `username` and `is_admin`. No login page needed. Managed LLM keys flow from server.
- **Enterprise/Cloud mode:** JWT-based multi-user auth (email + password login via spectrasherpa-server)
- **Free Data:** NIST, HITRAN, EPA - no authentication required in any mode
- **BYOK (Bring Your Own Key):** Users can add their own LLM API keys in any mode

---

## 📐 System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Vue.js Frontend (SPA)                        │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐ │
│  │ Experiments  │   Builder    │ NIST Search  │     Chat     │ │
│  │   Manager    │  (Project0)  │  & Download  │     LLM      │ │
│  └──────────────┴──────────────┴──────────────┴──────────────┘ │
│                    Pinia Stores (State Management)              │
│                    Plotly.js + Scientific Components            │
└─────────────────────────────────────────────────────────────────┘
                              ↕
              REST API + WebSocket (localhost:8000)
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI Backend (Modular Monolith)                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ API Layer (routes/, WebSocket handlers)                 │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ Service Layer (services/)                               │   │
│  │  ┌──────────┬──────────┬──────────┬────────┬────────┐  │   │
│  │  │Experiment│ Builder  │   NIST   │Calibra-│  LLM   │  │   │
│  │  │ Service  │ Service  │  Service │tion    │Service │  │   │
│  │  └──────────┴──────────┴──────────┴────────┴────────┘  │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ Core Scientific Libraries (app/lib/)                    │   │
│  │  ┌──────────────┬──────────────┬──────────────────┐    │   │
│  │  │ dag/         │  blending/   │  preprocessing   │    │   │
│  │  │ NDDataset    │ Beer's Law   │  Golden Grid     │    │   │
│  │  │ meta_helpers │  Saturation  │  Cosmic Rays     │    │   │
│  │  │ serialize    │              │                  │    │   │
│  │  └──────────────┴──────────────┴──────────────────┘    │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ Data Access Layer (models/, repositories/)              │   │
│  │  SQLAlchemy ORM + File System Access                    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│                   Data Storage Layer                            │
│  ┌──────────────────┬──────────────────┬──────────────────┐    │
│  │ SQLite (WAL)     │   File System    │   In-Memory      │    │
│  │ - All tables     │  (raw spectra)   │   Cache          │    │
│  │   · User         │ - Raw files      │ - Preprocessed   │    │
│  │   · Experiments  │ - Preprocessed   │   spectra (LRU)  │    │
│  │   · Calibrations │ - Content store  │ - Rate limiters  │    │
│  │   · Jobs         │ - Models         │ - Log buffer     │    │
│  │   · APIKeys      │ - Export cache   │                  │    │
│  └──────────────────┴──────────────────┴──────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↕
                    External Services (Optional)
┌─────────────────────────────────────────────────────────────────┐
│  ┌──────────────────┬──────────────────┬──────────────────┐    │
│  │  LLM APIs        │   NIST WebBook   │ spectrasherpa-   │    │
│  │  (OpenAI, etc.)  │  (Spectral data) │ server (hybrid)  │    │
│  └──────────────────┴──────────────────┴──────────────────┘    │
│  spectrasherpa-server provides: identity linking,              │
│  managed LLM keys, usage quotas (hybrid/enterprise modes)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🗂️ File System Structure

### Data Directory Layout

```
data/
├── experiments/
│   └── exp_001_methanol_study/
│       ├── metadata.json              # Experiment config, DOE, hardware
│       ├── raw/                       # Original uploaded files
│       │   ├── sample_01.csv
│       │   └── sample_02.csv
│       ├── preprocessed/              # After preprocessing pipeline
│       │   ├── sample_01_cleaned.csv
│       │   └── sample_02_cleaned.csv
│       ├── synthetic/                 # Generated synthetic data
│       │   └── blend_001.csv
│       ├── objects/                   # Content-addressable store (Git-like)
│       │   ├── a3f9c8d2...            # File stored by SHA-256 hash
│       │   ├── b7e4d1f5...            # Each unique file stored once
│       │   └── c2a8f643...
│       └── versions/                  # Version manifests
│           ├── v1_initial/
│           │   └── manifest.json      # {"sample_01.csv": "a3f9c8...", ...}
│           ├── v2_cosmic_ray_removed/
│           │   └── manifest.json
│           └── v3_smoothed/
│               └── manifest.json
├── calibrations/
│   └── CF4_calibration/
│       ├── metadata.json              # Calibration info
│       ├── raw_measurements/          # Input data at various concentrations
│       │   ├── CF4_100ppm.csv
│       │   ├── CF4_500ppm.csv
│       │   └── CF4_1000ppm.csv
│       ├── models/                    # Fitted calibration models (OUTPUT)
│       │   └── versions/
│       │       ├── v1_linear/
│       │       │   └── CF4_linear.json
│       │       └── v2_saturation/
│       │           └── CF4_saturation.json
│       └── plots/                     # Fit quality visualizations
│           └── calibration_curve.html
├── nist_library/
│   └── downloaded/
│       ├── C7732185_Water_1cm_boxcar.csv
│       └── metadata.json              # Download history
└── user/
    ├── config.json                    # User preferences
    └── api_keys.json                  # Encrypted API keys (DeepSeek, etc.)
```

### Hardware & Design-of-Experiment (DOE) Integration

Based on Exp_loader structure:

**Experiment Metadata (`metadata.json`):**
```json
{
  "experiment_id": "exp_001",
  "name": "Methanol-Ethanol Mixture Study",
  "created_at": "2026-01-01T10:00:00Z",
  "hardware": {
    "instrument": "Bruker Tensor 27",
    "detector": "DTGS",
    "resolution": "4 cm-1",
    "scans": 32,
    "pathlength_m": 1.0,
    "cell_type": "gas_cell"
  },
  "design_of_experiment": {
    "type": "full_factorial",
    "sample_factors": [
      {
        "factor_name": "Temperature",
        "levels": ["25C", "50C", "75C"]
      },
      {
        "factor_name": "Pressure",
        "levels": ["1atm", "2atm"]
      }
    ],
    "method_factors": [
      {
        "factor_name": "Scan_Type",
        "levels": ["transmission", "ATR"]
      }
    ],
    "total_runs": 12
  },
  "mixtures": [
    {
      "mixture_id": "mix_01",
      "rack_position": "A1",
      "components": [
        {"sample_id": "1", "sample_name": "Methanol", "volume_ml": 5.0},
        {"sample_id": "2", "sample_name": "Ethanol", "volume_ml": 5.0}
      ]
    }
  ],
  "acquisition_sequence": [
    {
      "step_number": 1,
      "sample_id": "mix_01",
      "rack_position": "A1",
      "method": "transmission",
      "temperature": "25C",
      "pressure": "1atm",
      "batch": "batch1",
      "file": "raw/sample_01.csv"
    }
  ]
}
```

**Calibration Metadata (`metadata.json`):**
```json
{
  "calibration_id": "cal_001",
  "compound": "CF4",
  "concentration_mode": "product",
  "x_unit": "ppm·m",
  "pathlength_m": 1.0,
  "concentrations": [100, 500, 1000, 2000, 5000],
  "measurements": [
    {"concentration": 100, "file": "raw_measurements/CF4_100ppm.csv"},
    {"concentration": 500, "file": "raw_measurements/CF4_500ppm.csv"}
  ],
  "models": [
    {
      "version": "v1_linear",
      "model_type": "linear",
      "created_at": "2026-01-01T11:00:00Z",
      "file": "models/versions/v1_linear/CF4_linear.json",
      "r_squared": 0.985
    },
    {
      "version": "v2_saturation",
      "model_type": "saturation",
      "created_at": "2026-01-01T12:00:00Z",
      "file": "models/versions/v2_saturation/CF4_saturation.json",
      "r_squared": 0.998,
      "active": true
    }
  ]
}
```

---

## 🗄️ Database Schema (SQLite)

### Entity Relationship Diagram

```
┌─────────────────┐
│      User       │
├─────────────────┤
│ id (PK)         │
│ username        │
│ password_hash   │
│ created_at      │
└─────────────────┘
         │
         │ 1:N
         ↓
┌─────────────────┐       ┌─────────────────┐
│   Experiment    │──────>│ ExperimentFile  │
├─────────────────┤  1:N  ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ user_id (FK)    │       │ experiment_id FK│
│ name            │       │ file_path       │
│ metadata_path   │       │ file_type       │
│ created_at      │       │ stage           │
│ updated_at      │       │ created_at      │
└─────────────────┘       └─────────────────┘
         │
         │ 1:N
         ↓
┌─────────────────┐
│ ExpVersion      │
├─────────────────┤
│ id (PK)         │
│ experiment_id FK│
│ version_name    │
│ description     │
│ snapshot_path   │
│ parent_ver_id FK│  (for branching)
│ created_at      │
└─────────────────┘

┌─────────────────┐       ┌─────────────────┐
│  Calibration    │──────>│ CalibrationFile │
├─────────────────┤  1:N  ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ user_id (FK)    │       │ calibration_id  │
│ compound_name   │       │ file_path       │
│ metadata_path   │       │ concentration   │
│ created_at      │       │ created_at      │
│ updated_at      │       └─────────────────┘
└─────────────────┘
         │
         │ 1:N
         ↓
┌─────────────────┐
│   CalModel      │  (Calibration Model Versions)
├─────────────────┤
│ id (PK)         │
│ calibration_id  │
│ version_name    │
│ model_type      │  (linear, saturation, hybrid)
│ model_path      │  (path to JSON file)
│ r_squared       │
│ is_active       │  (current active model)
│ created_at      │
└─────────────────┘

┌─────────────────┐
│   NISTLibrary   │
├─────────────────┤
│ id (PK)         │
│ cas_number      │
│ compound_name   │
│ resolution      │
│ file_path       │
│ downloaded_at   │
└─────────────────┘

┌─────────────────┐
│   BackgroundJob │
├─────────────────┤
│ id (PK)         │
│ user_id (FK)    │
│ job_type        │  (mcr_als, nist_download, blend)
│ status          │  (pending, running, completed, failed)
│ progress        │  (0-100)
│ result_path     │
│ error_message   │
│ created_at      │
│ started_at      │
│ completed_at    │
└─────────────────┘

┌─────────────────┐
│   APIKey        │
├─────────────────┤
│ id (PK)         │
│ user_id (FK)    │
│ service_name    │  (deepseek, openai, etc.)
│ key_encrypted   │  (AES-256 encrypted)
│ created_at      │
│ last_used_at    │
└─────────────────┘
```

### Key Design Decisions

1. **Metadata in DB, Files on Disk:** Database stores paths and metadata, actual spectral data stays as files
2. **Content-Addressable Versioning:** Files stored once by SHA-256 hash, versions reference via manifests (prevents storage explosion)
3. **SQLite WAL Mode:** Write-Ahead Logging allows concurrent readers + 1 writer (no UI freezes during job updates)
4. **Mode-Dependent Auth:** Local = implicit user; Hybrid = API-key linked identity from spectrasherpa-server; Enterprise/Cloud = JWT auth
5. **Local-Compute-First:** All scientific compute runs locally; network only for auxiliary services (NIST, LLM)
6. **Crash-Safe Jobs:** BackgroundTasks with cleanup handlers mark jobs as failed on server crash
7. **Compute Provenance:** Track whether job ran locally or via API (compute_location field)
8. **Export Everything:** CSV/Excel/JSON/ZIP exports for all data (scientists live in Excel)
9. **In-memory caching:** LRU cache for preprocessed spectra (prevents re-processing)
10. **Resource limits:** Guardrails for memory, CPU, API rate limiting (prevents crashes)

---

## 🔌 API Specification

### REST Endpoints

**Base URL:** `http://localhost:8000/api/v1`

#### Experiments

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/experiments` | List all experiments |
| POST | `/experiments` | Create new experiment |
| GET | `/experiments/{id}` | Get experiment details |
| PUT | `/experiments/{id}` | Update experiment |
| DELETE | `/experiments/{id}` | Delete experiment |
| POST | `/experiments/{id}/files` | Upload spectral file |
| GET | `/experiments/{id}/versions` | List versions |
| POST | `/experiments/{id}/versions` | Create snapshot |
| POST | `/experiments/{id}/versions/{ver}/restore` | Restore to version |

#### Spectra Builder (Project0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/builder/preprocess` | Preprocess spectra |
| POST | `/builder/blend` | Blend multiple species |
| GET | `/builder/curves/default` | Get default curve config |
| POST | `/builder/curves/generate` | Generate curve points |

#### Calibration (Project1)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/calibrations` | List all calibrations |
| POST | `/calibrations` | Create new calibration |
| POST | `/calibrations/{id}/fit` | Fit calibration model |
| GET | `/calibrations/{id}/models` | List model versions |
| PUT | `/calibrations/{id}/models/{ver}/activate` | Set active model |

#### NIST Library

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nist/search?query={compound}` | Search NIST database |
| POST | `/nist/download` | Download spectrum (background job) |
| GET | `/nist/library` | List downloaded spectra |

#### LLM Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/llm/chat` | Send message (returns job_id) |
| GET | `/llm/conversation/{id}` | Get conversation history |
| DELETE | `/llm/conversation/{id}` | Clear conversation |

#### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/jobs` | List all jobs |
| GET | `/jobs/{id}` | Get job status |
| DELETE | `/jobs/{id}` | Cancel job |

#### Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/experiments/{id}/export?format=csv` | Export experiment as CSV/Excel/JSON/ZIP |
| GET | `/calibrations/{id}/export?format=csv` | Export calibration data |
| GET | `/nist/library/export?format=csv` | Bulk export NIST library |
| GET | `/jobs/{id}/results/export` | Export job results |

#### User/Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/me` | Get current user (enriched in hybrid mode) |
| POST | `/auth/login` | Login with credentials (enterprise/cloud mode) |
| GET | `/user/profile` | Get user profile |
| PUT | `/user/api-keys` | Update API keys (encrypted) |
| GET | `/logs` | Get recent log entries (for debugging) |

**Auth by mode:**
- **Local:** No auth required — implicit user resolved from DB
- **Hybrid:** No login needed — identity linked from server via `SPECTRASHERPA_API_KEY` at startup. `GET /auth/me` returns enriched local user.
- **Enterprise/Cloud:** JWT auth via `Authorization: Bearer <token>` header

### WebSocket Events

**Endpoint:** `ws://localhost:8000/ws`

#### Client → Server

```json
{"type": "subscribe", "channel": "jobs/{job_id}"}
{"type": "subscribe", "channel": "llm/chat/{conversation_id}"}
{"type": "unsubscribe", "channel": "jobs/{job_id}"}
```

#### Server → Client

**Job Progress:**
```json
{
  "type": "job_progress",
  "job_id": "job_123",
  "progress": 45,
  "status": "running",
  "message": "Processing spectrum 45/100"
}
```

**LLM Streaming:**
```json
{
  "type": "llm_chunk",
  "conversation_id": "conv_456",
  "chunk": "The MCR-ALS algorithm works by...",
  "done": false
}
```

**Job Completed:**
```json
{
  "type": "job_completed",
  "job_id": "job_123",
  "status": "completed",
  "result_path": "data/experiments/exp_001/results/mcr_output.csv"
}
```

---

## 📦 Module Breakdown

### Backend Services

#### 1. **Experiment Service** (`services/experiment.py`)
**Responsibilities:**
- Create/read/update/delete experiments
- Manage experiment files (upload, organize)
- Create/restore versions (snapshot management)
- Integrate hardware metadata and DOE configurations

**Key Methods:**
```python
class ExperimentService:
    async def create_experiment(metadata: ExperimentCreate) -> Experiment
    async def upload_file(exp_id: int, file: UploadFile, stage: str) -> ExperimentFile
    async def create_version(exp_id: int, description: str) -> ExpVersion
    async def restore_version(exp_id: int, version_id: int) -> None
    async def list_versions(exp_id: int) -> List[ExpVersion]
```

#### 2. **Builder Service** (`services/builder.py`)
**Responsibilities:**
- Wrap Project0 blending engine
- Preprocessing pipeline (cosmic ray, Savitzky-Golay, alignment)
- Curve generation for interactive UI

**Key Methods:**
```python
class BuilderService:
    async def preprocess(spectra: List[SpectrumData], settings: PreprocessSettings) -> List[SpectrumData]
    async def blend(species: List[SpectrumData], concentrations: Dict, settings: BlendSettings) -> BlendResult
    async def generate_curves(count: int) -> CurvePoints
```

#### 3. **Calibration Service** (`services/calibration.py`)
**Responsibilities:**
- Manage calibration datasets
- Fit linear/saturation/hybrid models (Project1)
- Version calibration models
- Activate/deactivate models

**Key Methods:**
```python
class CalibrationService:
    async def create_calibration(metadata: CalibrationCreate) -> Calibration
    async def fit_model(cal_id: int, model_type: str, settings: FitSettings) -> CalModel
    async def activate_model(cal_id: int, model_version_id: int) -> None
    async def get_active_model(cal_id: int) -> CalModel
```

#### 4. **NIST Service** (`services/nist.py`)
**Responsibilities:**
- Search NIST Chemistry WebBook
- Download JCAMP-DX files (background job)
- Convert to CSV and store in library
- Manage download queue and rate-limiting

**Key Methods:**
```python
class NISTService:
    async def search(query: str) -> List[NISTCompound]
    async def download(cas: str, resolution: str) -> BackgroundJob
    async def list_library() -> List[NISTLibrary]
```

#### 5. **LLM Service** (`services/llm.py`)
**Responsibilities:**
- Manage DeepSeek API integration
- Handle chat conversations
- Stream responses via WebSocket
- Features: auto-suggest, peak ID, code gen, report writing

**Key Methods:**
```python
class LLMService:
    async def chat(message: str, conversation_id: str, metadata: dict) -> str
    async def stream_chat(message: str, conversation_id: str) -> AsyncGenerator
    async def auto_suggest_name(components: List[str]) -> str
    async def identify_peaks(spectrum: np.ndarray, wavenumbers: np.ndarray) -> List[Peak]
    async def generate_code(task_description: str) -> str
    async def write_report(experiment: Experiment) -> str
```

#### 6. **Job Service** (`services/job.py`)
**Responsibilities:**
- Create and track background jobs
- Update job progress via WebSocket
- Handle job cancellation
- Clean up completed jobs

**Key Methods:**
```python
class JobService:
    async def create_job(user_id: int, job_type: str) -> BackgroundJob
    async def update_progress(job_id: int, progress: int, message: str) -> None
    async def complete_job(job_id: int, result_path: str) -> None
    async def fail_job(job_id: int, error: str) -> None
```

---

### Frontend Components (Vue.js)

#### Navigation Structure

```
App.vue
└── Sidebar Navigation
    ├── Experiments → ExperimentsView.vue
    ├── Builder → BuilderView.vue
    ├── NIST Search → NISTView.vue
    ├── Analysis → AnalysisView.vue
    └── Chat → ChatView.vue
```

#### Pinia Stores (State Management)

**1. Experiment Store** (`stores/experiment.ts`)
```typescript
export const useExperimentStore = defineStore('experiment', {
  state: () => ({
    experiments: [] as Experiment[],
    currentExperiment: null as Experiment | null,
    versions: [] as ExpVersion[],
  }),
  actions: {
    async fetchExperiments(),
    async createExperiment(metadata: ExperimentCreate),
    async uploadFile(file: File, stage: string),
    async createSnapshot(description: string),
    async restoreVersion(versionId: number),
  }
})
```

**2. Builder Store** (`stores/builder.ts`)
```typescript
export const useBuilderStore = defineStore('builder', {
  state: () => ({
    spectra: [] as SpectrumData[],
    preprocessSettings: {} as PreprocessSettings,
    blendSettings: {} as BlendSettings,
    curvePoints: [] as CurvePoint[],
  }),
  actions: {
    async preprocess(),
    async blend(concentrations: Dict),
    async generateCurves(count: number),
  }
})
```

**3. NIST Store** (`stores/nist.ts`)
```typescript
export const useNISTStore = defineStore('nist', {
  state: () => ({
    searchResults: [] as NISTCompound[],
    library: [] as NISTLibrary[],
    downloadJobs: [] as BackgroundJob[],
  }),
  actions: {
    async search(query: string),
    async download(cas: string, resolution: string),
    async refreshLibrary(),
  }
})
```

**4. LLM Store** (`stores/llm.ts`)
```typescript
export const useLLMStore = defineStore('llm', {
  state: () => ({
    conversations: [] as Conversation[],
    currentConversation: null as Conversation | null,
    streaming: false,
  }),
  actions: {
    async sendMessage(message: string),
    async createConversation(),
    async deleteConversation(id: string),
  }
})
```

**5. Job Store** (`stores/job.ts`)
```typescript
export const useJobStore = defineStore('job', {
  state: () => ({
    jobs: [] as BackgroundJob[],
  }),
  actions: {
    async fetchJobs(),
    async cancelJob(id: number),
    subscribeToJob(id: number), // WebSocket subscription
  }
})
```

#### Key Vue Components

**ExperimentsView.vue:**
- Experiment list (table with PrimeVue DataTable)
- Create experiment modal (hardware, DOE, mixtures)
- File upload drag-and-drop
- Version history tree view

**BuilderView.vue:**
- Spectrum list (loaded from experiment)
- Preprocessing settings panel
- Interactive Plotly chart
- Blending controls (concentration sliders)
- Catmull-Rom curve editor (drag-and-drop control points)

**NISTView.vue:**
- Search bar
- Results table (compound name, CAS, resolution options)
- Download queue (job progress bars via WebSocket)
- Downloaded library table (with preview)

**AnalysisView.vue:**
- Placeholder for Phase 2 (MCR-ALS, ICA, EFA)
- Will integrate SpectroChem-Py fork

**ChatView.vue:**
- LLM chat interface (messages, streaming responses)
- Sidebar with conversation history
- Auto-suggest, peak ID, code gen, report writing buttons
- Metadata context toggle (include experiment info in prompt)

---

## 🔧 Technology Stack

### Backend
- **Framework:** FastAPI 0.109+
- **ORM:** SQLAlchemy 2.0+ (async)
- **Database:** SQLite 3 (aiosqlite for async)
- **Validation:** Pydantic v2
- **Background Tasks:** FastAPI BackgroundTasks (Phase 1)
- **WebSocket:** FastAPI WebSocket support (built-in)
- **Scientific:** NumPy, SciPy, Matplotlib, Plotly
- **Chemometric:** SpectroChem-Py (forked), pyMCR, scikit-learn
- **LLM:** OpenAI SDK (compatible with DeepSeek)
- **Authentication:** JWT tokens (python-jose)
- **Encryption:** cryptography (for API keys)

### Frontend
- **Framework:** Vue 3 (Composition API)
- **Language:** TypeScript
- **State:** Pinia 2.x
- **Router:** Vue Router 4
- **UI Library:** PrimeVue 3.x (recommended)
- **Charts:** Plotly.js
- **HTTP:** Axios + WebSocket (native)
- **Build:** Vite

### Development
- **Package Manager (Backend):** Poetry
- **Package Manager (Frontend):** npm
- **Linting:** ESLint (frontend), Ruff (backend)
- **Formatting:** Prettier (frontend), Black (backend)
- **Type Checking:** TypeScript (frontend), mypy (backend)

### Deployment (Local)
- **Container:** Docker + Docker Compose (optional, for Redis in future)
- **Process Manager:** Uvicorn (backend), Vite dev server (frontend)

---

## 🔐 Security Considerations

### API Key Storage
- **Encryption:** AES-256-CBC with user password as key derivation
- **Storage:** Encrypted in SQLite `APIKey` table
- **Access:** Decrypted only when needed for API calls

### Authentication
- **Method:** JWT tokens (httpOnly cookies for web, localStorage for dev)
- **Password:** Hashed with bcrypt (12 rounds)
- **Session:** 24-hour token expiry, refresh token support (Phase 2)

### File Access
- **Validation:** Check file paths to prevent directory traversal
- **Size Limits:** Max upload 100 MB per file
- **Allowed Types:** .csv, .jdx, .json, .txt

---

## 🚀 Development Workflow

### Quick Start (pip install)

```bash
cd "Spectra Scientific/Component_code/Refactored"
pip install -e .
spectra-sherpa          # Opens browser → http://127.0.0.1:8000
```

### Development Setup (hot-reload)

```bash
# Backend (from repo root)
cd src/spectra_sherpa
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
# Vite dev server at http://localhost:5173 → proxies API to :8000
```

### Development Flow

1. **Start backend:** `uvicorn app.main:app --reload` (from `src/spectra_sherpa/`)
2. **Start frontend:** `npm run dev` (from `frontend/`)
3. **Access app:** http://localhost:5173 (proxies to backend at :8000)
4. **API Docs:** http://localhost:8000/docs (Swagger UI)

### Production Build (Local Deployment)

```bash
# Build frontend into static/ for SPA serving
scripts/build_frontend.sh

# Run via CLI
spectra-sherpa --port 8000
# Backend serves frontend static files at http://localhost:8000
```

### Docker Deployment

```bash
cd deploy
docker compose -f docker-compose.prod.yaml up -d --build
```

---

## 🧪 Testing Strategy

### Backend Tests
- **Unit:** pytest for services, models
- **Integration:** TestClient for API endpoints
- **Scientific:** Validate blending/calibration against known results

### Frontend Tests
- **Unit:** Vitest for stores, composables
- **Component:** Vue Test Utils for components
- **E2E:** Playwright (Phase 2)

---

## 📈 Performance Considerations

### Core Optimizations (Phase 1)

#### 1. **Content-Addressable Storage (Versioning)**

**Problem:** Full file snapshots cause storage explosion (10 versions × 250 MB = 2.5 GB per experiment)

**Solution:** Git-like content-addressable storage
```python
# app/services/version_storage.py
from abc import ABC, abstractmethod
import hashlib
from pathlib import Path

class VersionStorage(ABC):
    """Abstraction layer for version storage (swappable implementation)"""

    @abstractmethod
    async def create_version(self, files: List[Path]) -> Version:
        pass

    @abstractmethod
    async def restore_version(self, version: Version) -> List[Path]:
        pass

class ContentAddressableStorage(VersionStorage):
    """Hash-based deduplication - each file stored once"""

    async def store_file(self, file_path: Path) -> str:
        """Store file and return SHA-256 hash"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)

        file_hash = sha256.hexdigest()
        object_path = self.objects_dir / file_hash

        if not object_path.exists():  # Only copy if not already stored
            shutil.copy2(file_path, object_path)

        return file_hash

    async def create_version(self, files: List[Path]) -> Version:
        """Create manifest referencing file hashes"""
        manifest = {}
        for file in files:
            file_hash = await self.store_file(file)
            manifest[file.name] = file_hash

        # Save manifest.json
        version_path = self.versions_dir / version_name / "manifest.json"
        with open(version_path, 'w') as f:
            json.dump(manifest, f)

        return Version(path=version_path, manifest=manifest)
```

**Benefits:**
- Each unique file stored exactly once (deduplication)
- Fast version creation (write manifest, not files)
- Hash verification prevents corruption
- Easy migration path: start simple, upgrade later

**File Structure:**
```
exp_001/
├── objects/           # Content store
│   ├── a3f9c8...     # SHA-256: sample_01_original.csv
│   ├── b7e4d1...     # SHA-256: sample_01_cleaned.csv
│   └── c2a8f6...     # SHA-256: sample_02.csv
└── versions/
    ├── v1_initial/
    │   └── manifest.json    # {"sample_01.csv": "a3f9c8...", ...}
    └── v2_cleaned/
        └── manifest.json    # {"sample_01.csv": "b7e4d1...", ...}
```

---

#### 2. **SQLite WAL Mode (Write Concurrency)**

**Problem:** SQLite default mode allows multiple readers OR one writer. Job progress updates (1/sec) block UI reads → freezes

**Solution:** Enable Write-Ahead Logging (WAL) mode
```python
# app/core/database.py
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

DATABASE_URL = "sqlite+aiosqlite:///data/spectra_platform.db"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True
)

# Enable WAL mode for concurrent reads + writes
@event.listens_for(engine.sync_engine, "connect")
def set_wal_mode(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")     # Faster writes (safe with WAL)
    cursor.execute("PRAGMA busy_timeout=5000")      # Wait 5s on lock contention
    cursor.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint after 1000 pages (~4 MB)
    cursor.close()

async def get_db():
    async with AsyncSession(engine) as session:
        yield session
```

**Benefits:**
- Job progress updates (1/sec) never block UI reads
- Simpler architecture (one database file)
- Better for backups (single .db + .wal + .shm files)
- Same performance as dual-database approach
- Easy migration to PostgreSQL later (same code)

---

#### 3. **In-Memory Caching (Preprocessing)**

**Problem:** Re-processing 50 spectra on every UI interaction = 65 seconds wait

**Solution:** LRU cache with settings-based invalidation
```python
# app/services/cache.py
from functools import lru_cache
import hashlib
import json
import os

@lru_cache(maxsize=128)  # Cache up to 128 spectra (~2 GB RAM)
def load_preprocessed_spectrum(
    file_path: str,
    file_mtime: float,  # CRITICAL: Include mtime to prevent stale cached data
    settings_hash: str
) -> np.ndarray:
    """Load and preprocess spectrum (cached by file mtime + settings)"""
    settings = json.loads(settings_hash)

    # Read CSV
    spectrum = np.loadtxt(file_path)

    # Apply preprocessing pipeline
    if settings['cosmic_ray_removal']:
        spectrum = remove_cosmic_rays(spectrum)
    if settings['savgol_smoothing']:
        spectrum = savgol_filter(spectrum, ...)

    return spectrum

# In API endpoint
def preprocess_spectra(files: List[str], settings: dict):
    settings_hash = hashlib.md5(
        json.dumps(settings, sort_keys=True).encode()
    ).hexdigest()

    results = []
    for file in files:
        # Include file modification time in cache key
        file_mtime = os.path.getmtime(file)

        # Cache hit = instant, Cache miss = process once
        # If file changes, mtime changes → new cache key → re-process
        spectrum = load_preprocessed_spectrum(file, file_mtime, settings_hash)
        results.append(spectrum)

    return results
```

**Benefits:**
- First load: 65 sec (unavoidable)
- Adjust plot settings: instant (cache hit)
- Change Savgol window: 65 sec (new cache)
- Configurable memory limit

**Optional:** Disk cache with `.npz` files (survives restart)
```python
cache_path = exp_dir / ".cache" / f"preprocessed_{settings_hash}.npz"
if cache_path.exists():
    return np.load(cache_path)['spectrum']
```

---

#### 4. **Resource Limits & Rate Limiting**

**Problem:** No limits = server crashes (10k spectra MCR-ALS allocates 2.4 GB, NIST "Download All" = IP ban)

**Solution:** Validation and rate limiting
```python
# app/core/config.py
class Settings(BaseSettings):
    # Compute limits
    MAX_SPECTRA_PER_JOB: int = 1000
    MAX_WAVENUMBERS: int = 20000
    MAX_JOB_DURATION_SEC: int = 3600  # 1 hour
    MAX_MEMORY_MB: int = 4096

    # Concurrency limits
    MAX_CONCURRENT_JOBS: int = 3
    MAX_NIST_DOWNLOADS_PER_HOUR: int = 50
    MAX_FILE_SIZE_MB: int = 100

# app/services/mcr_als.py
def run_mcr_als(data: np.ndarray):
    n_spectra, n_wavenumbers = data.shape

    # Validate input size
    if n_spectra > settings.MAX_SPECTRA_PER_JOB:
        raise ValidationError(
            f"Too many spectra: {n_spectra}. "
            f"Maximum: {settings.MAX_SPECTRA_PER_JOB}"
        )

    # Estimate memory usage
    estimated_mb = (n_spectra * n_wavenumbers * 8 * 3) / 1e6
    if estimated_mb > settings.MAX_MEMORY_MB:
        raise ValidationError(
            f"Estimated memory {estimated_mb:.0f} MB "
            f"exceeds limit {settings.MAX_MEMORY_MB} MB"
        )

    # Run with timeout
    with timeout(settings.MAX_JOB_DURATION_SEC):
        result = mcr.fit(data)

    return result

# app/services/rate_limiter.py
from collections import deque
from datetime import datetime, timedelta

class RateLimiter:
    """In-memory rate limiter (no Redis needed for Phase 1)"""

    def __init__(self, max_requests: int, window_sec: int):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_sec)
        self.requests = deque()

    def allow(self) -> bool:
        now = datetime.now()

        # Remove old requests outside window
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()

        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True

        return False

# In NIST service
nist_limiter = RateLimiter(max_requests=50, window_sec=3600)

@router.post("/nist/download")
async def download_spectrum(cas: str):
    if not nist_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again in 1 hour."
        )

    # Proceed with download...
```

**Benefits:**
- Prevents server crashes from oversized jobs
- Helpful error messages guide users
- Protects against accidental DOS
- No external dependencies (Redis) needed

---

### Additional Optimizations

5. **BLAS Thread Limiting:** Cap NumPy/SciPy to 4 threads (prevents CPU saturation)
```python
# app/main.py (top of file, before imports)
import os
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"
```

6. **Memory-Mapped Files:** Use `np.load(mmap_mode='r')` for large spectra
7. **Crash-Safe Jobs:** Startup reconciliation handles hard kills, power loss, SIGKILL
```python
# app/main.py
from fastapi import FastAPI
from datetime import datetime, timedelta
from sqlalchemy import select, update

app = FastAPI()

@app.on_event("startup")
async def reconcile_stale_jobs():
    """
    CRITICAL: Handles jobs that were running when server crashed (SIGKILL, power loss, kernel panic).
    Signal handlers (SIGINT/SIGTERM/atexit) are unreliable - they don't run on hard kills.
    This runs on EVERY app startup and cleans up stale jobs from previous session.
    """
    async with get_db() as db:
        # Find all jobs stuck in 'running' state
        stale_jobs = await db.execute(
            select(BackgroundJob).where(BackgroundJob.status == 'running')
        )
        stale_jobs = stale_jobs.scalars().all()

        for job in stale_jobs:
            # Check if job is truly stale (heartbeat >5 minutes old)
            if job.last_heartbeat and datetime.now() - job.last_heartbeat < timedelta(minutes=5):
                continue  # Job might still be running (race condition during startup)

            # Mark as failed
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(
                    status='failed',
                    error_message='Server crashed (stale job from previous session)',
                    completed_at=datetime.now()
                )
            )

        await db.commit()
        logger.info(f"Reconciled {len(stale_jobs)} stale jobs on startup")

# In job execution loop
async def execute_job(job_id: int):
    while job_running:
        # ... do work ...

        # Update heartbeat every 30 seconds to prove job is alive
        await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(last_heartbeat=datetime.now())
        )
```

8. **Compute Provenance:** Track local vs remote execution
```python
# Add to BackgroundJob model
compute_location = Column(String(50))  # 'local', 'nist_api', 'deepseek_api'
compute_node = Column(String(100))     # hostname or API endpoint
```

9. **Simple Authentication:** API key check (no JWT overhead)
```python
# app/middleware/auth.py
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/api"):
        key = request.headers.get("X-API-Key")
        if key != os.getenv("APP_API_KEY", "default-local-key"):
            return JSONResponse({"error": "Unauthorized"}, 401)
    return await call_next(request)
```

10. **Log Viewer:** In-memory log buffer with security scrubbing
```python
# app/services/logger.py
from collections import deque
import logging
import re

log_buffer = deque(maxlen=1000)

# SECURITY: Patterns to redact from logs
REDACT_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'Bearer [a-zA-Z0-9]+'), 'Bearer [REDACTED]'),
    (re.compile(r'password["\s:=]+[^"\s]+', re.I), 'password=[REDACTED]'),
    (re.compile(r'api[_-]?key["\s:=]+[^"\s]+', re.I), 'api_key=[REDACTED]'),
]

class BufferHandler(logging.Handler):
    def emit(self, record):
        message = self.format(record)

        # Scrub sensitive data
        for pattern, replacement in REDACT_PATTERNS:
            message = pattern.sub(replacement, message)

        log_buffer.append({
            "timestamp": record.created,
            "level": record.levelname,
            "message": message
        })
```

11. **Path Traversal Protection:** Secure file uploads
```python
# app/services/file_upload.py
from werkzeug.utils import secure_filename
import os

ALLOWED_EXTENSIONS = {'.csv', '.jdx', '.json', '.txt'}

def validate_upload(filename: str, content: bytes):
    # Strip directory components
    safe_name = os.path.basename(filename)

    # Check for path traversal attempts
    if '..' in filename or '/' in filename or '\\' in filename or '\0' in filename:
        raise ValidationError(f"Invalid filename: {filename}")

    # Validate extension
    _, ext = os.path.splitext(safe_name)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type not allowed: {ext}")

    # Validate size
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"File too large: {len(content) / 1024 / 1024:.1f} MB")

    # Sanitize filename
    return secure_filename(safe_name)
```

12. **Content-Addressable Garbage Collection:** Prevent storage bloat
```python
# app/services/version_storage.py
def garbage_collect(exp_id: int, grace_period_days: int = 7):
    """Delete orphaned files from objects/ that aren't referenced by any version"""
    # Get all hashes referenced by manifests
    referenced = set()
    for manifest in get_all_manifests(exp_id):
        referenced.update(manifest['files'].values())

    # Find orphaned objects
    objects_dir = Path(f"data/experiments/exp_{exp_id}/objects")
    orphaned = []
    for obj_file in objects_dir.iterdir():
        if obj_file.name not in referenced:
            # Check grace period (don't delete recent files)
            if time.time() - obj_file.stat().st_mtime > grace_period_days * 86400:
                orphaned.append(obj_file)

    # Delete orphans
    for obj in orphaned:
        obj.unlink()
        logger.info(f"GC: Deleted orphaned object {obj.name}")

    return len(orphaned)
```

13. **Export Streaming:** Avoid memory exhaustion on large exports
```python
# app/api/export.py
from zipstream import ZipStream
from fastapi.responses import StreamingResponse

@router.get("/experiments/{id}/export")
async def export_experiment(id: int, format: str = 'zip'):
    # Validate export size
    total_size = calculate_export_size(id)
    if total_size > settings.MAX_EXPORT_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Export too large: {total_size / 1024 / 1024:.0f} MB (max: {settings.MAX_EXPORT_SIZE_MB} MB)"
        )

    # Stream ZIP without loading into memory
    def generate():
        zs = ZipStream()
        for file_path in get_experiment_files(id):
            zs.add_path(file_path, arcname=file_path.name)
        yield from zs

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=experiment_{id}.zip"}
    )
```

14. **External API Key Management:** Secure master key storage
```python
# app/services/encryption.py
import keyring
from cryptography.fernet import Fernet

def get_master_key():
    """Get master encryption key from system keyring"""
    try:
        # Try system keyring first
        key = keyring.get_password("spectra_platform", "master_key")
        if not key:
            # Generate new key
            key = Fernet.generate_key().decode()
            keyring.set_password("spectra_platform", "master_key", key)
    except keyring.errors.NoKeyringError:
        # Fallback: Use .env file with secure permissions
        key = os.getenv("MASTER_ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key().decode()
            with open(".env", "a") as f:
                f.write(f"\nMASTER_ENCRYPTION_KEY={key}\n")
            os.chmod(".env", 0o600)  # Secure permissions

    return key.encode()
```

15. **BLAS Thread Limiting:** Shell wrapper instead of Python code
```bash
#!/bin/bash
# start.sh - Set env vars BEFORE Python imports NumPy

export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export MKL_NUM_THREADS=4
export NUMEXPR_NUM_THREADS=4

uvicorn app.main:app --reload
```

16. **Lazy Loading:** Load experiments/spectra on-demand
17. **Pagination:** DataTable pagination for large lists
18. **WebSocket Batching:** Send progress updates every 100ms max
19. **Plotly Performance:** Use `scattergl` for >10k points (verified in Week 7)

### Scalability Path (Future)

1. **Database:** Migrate from SQLite to PostgreSQL
2. **Background Jobs:** Replace FastAPI tasks with Celery + Redis
3. **Caching:** Add Redis for session/API response caching
4. **Cloud Compute:** Offload MCR-ALS to cloud workers (optional)

---

## 🔄 Migration from Original Code

### Backwards Compatibility

**Supported:**
- ✅ Import old experiment XML files (Exp_loader format)
- ✅ Import old calibration JSON signatures (Project1 format)
- ✅ Load old session files (standalone builder)

**Not Supported:**
- ❌ Old API endpoints (new REST API only)

### Migration Scripts

Location: `scripts/migrate_*.py`

1. **migrate_experiments.py:** Import XML experiments from `Original/Exp_loader/experiments/`
2. **migrate_calibrations.py:** Import JSON signatures from `Original/Synthetic_Spectra_Builder_py/signatures/`
3. **migrate_nist.py:** Import downloaded NIST library from `Original/Pull_FTIR_from_NIST/nist_csv/`

---

## 📝 Next Steps

See [ROADMAP.md](../future/ROADMAP.md) for detailed Phase 1 implementation plan.

---

## 📦 Library Migration & Data Architecture (Updated 2026-02-05)

The legacy `libs/project0/` and `libs/project1/` directories have been retired. All scientific code now lives in `app/lib/`:

| Old Location | New Location |
|-------------|--------------|
| `libs/project0/blend.py` | `app/lib/blending/blend.py` |
| `libs/project0/preprocess.py` | `app/lib/preprocessing.py` |
| `libs/project0/curves.py` | `app/lib/curves.py` |
| `libs/project1/` | `app/lib/visualization.py`, `app/lib/io.py` |

### Data Architecture (Big Rollback Plan - BRB)

**AnalysisDataset is the SOLE data type** throughout the DAG. NDDataset (SpectroChemPy) is used only by ~11 SCP-only nodes via round-trip adapters in `scp_compat.py`.

| Component | Location | Purpose |
|-----------|----------|---------|
| **AnalysisDataset** | `app/lib/analysis_dataset.py` | Canonical DAG runtime container — 2D numpy array with axes, metadata, provenance |
| **NDDataset** | SpectroChemPy (optional) | Used by SCP-only nodes; converted to/from AnalysisDataset at boundaries |
| **meta_helpers.py** | `app/services/dag/` | Provenance tracking via `add_processing_step()`, sample management |
| **serialize.py** | `app/services/dag/` | Single API boundary serialization via `serialize_for_api()` |

**Key architectural principles:**
- **Single data type:** AnalysisDataset flows through all DAG nodes — NDDataset-compatible properties (`.data`, `.x`, `.y`, `.shape`, `.ndim`, `.copy()`) allow node code to work with either type
- **Provenance in meta:** Processing history stored in `dataset.meta["processing_history"]` as structured dicts
- **API boundary serialization:** `serialize_for_api(dataset)` called ONLY in routes/workflows.py
- **Wire-format compatibility:** `AnalysisDataset.to_dict()` emits `type: "NDDataset"` so the frontend works without changes
- **Parquet + JSON sidecar** serialization for efficient persistent caching

**Node pattern (minimal):**
```python
async def execute(self, input_data: AnalysisDataset) -> AnalysisDataset:
    result = input_data.copy()
    # process using numpy/scipy directly
    add_processing_step(result, "baseline.als", {"lam": lam, "p": p})
    return result
```

**Provenance helpers (meta_helpers.py):**
- `add_processing_step(dataset, operation, params)` - Record processing step
- `copy_processing_history(source, target)` - Copy history to new dataset
- `get_processing_history(dataset)` - Retrieve history list

See [BIG_ROLLBACK_PLAN.md](../../BIG_ROLLBACK_PLAN.md) for full migration details.

---

**Document Version:** 1.6
**Last Updated:** 2026-02-07
**Authors:** Spectra Scientific Team
