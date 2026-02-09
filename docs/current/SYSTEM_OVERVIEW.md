# SpectraSherpa — System Overview

**Version:** 1.4.0
**Package:** `spectra-sherpa` (PyPI) / `spectra-sherpa` (CLI)
**Date:** 2026-02-07
**Status:** Production-Ready (Hybrid Identity Linking)

---

## Executive Summary

**SpectraSherpa** is a modern web-based spectral analysis platform built for FTIR spectroscopy and chemometrics. It provides a visual workflow builder for constructing data processing pipelines using a directed acyclic graph (DAG) architecture, enabling researchers to load, analyze, and visualize spectral data through an intuitive drag-and-drop interface.

**Key Differentiators:**
- **Visual Workflow Builder:** No-code interface for building complex analysis pipelines
- **50+ Specialized Nodes:** Pre-built processing blocks for data loading, preprocessing, modeling, and visualization
- **Real-time Execution:** Immediate feedback as workflows are built and modified
- **Full-Stack Python Scientific Computing:** Leverages SpectroChemPy, scikit-learn, NumPy ecosystem
- **Modern Web Architecture:** Vue 3 + FastAPI + SQLite (WAL mode) stack

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (SPA)                         │
│  Vue 3 + TypeScript + PrimeVue + Plotly.js                 │
│  - Workflow Builder (Visual DAG Editor)                     │
│  - Node Inspector (Parameter Configuration)                 │
│  - Result Visualization (Plots, Tables, Exports)            │
└─────────────────┬───────────────────────────────────────────┘
                  │ REST API (JSON)
┌─────────────────▼───────────────────────────────────────────┐
│                   Backend API Layer                         │
│  FastAPI + Pydantic + SQLAlchemy (async)                   │
│  - Workflow Management API                                  │
│  - Node Execution Engine                                    │
│  - Data Serialization                                       │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│              DAG Execution Engine                           │
│  - Topological Sort (execution order)                       │
│  - Dependency Resolution                                    │
│  - Result Caching                                           │
│  - Error Handling & Rollback                                │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│               Node Processing Layer                         │
│  50+ Specialized Nodes:                                     │
│  - Data Loading (SpectroChemPy, Files, Databases)          │
│  - Preprocessing (Baseline, Normalize, Smooth)              │
│  - Modeling (PCA, PLS, MCR-ALS, Classification)            │
│  - Visualization (Plots, Exports, Reports)                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│           Scientific Computing Libraries                    │
│  - SpectroChemPy (FTIR-specific operations)                │
│  - scikit-learn (ML models)                                 │
│  - NumPy/SciPy (numerical computing)                        │
│  - pandas (data manipulation)                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User → Frontend (Workflow Builder) → API → DAG Engine → Nodes → Scientific Libraries
                                                ↓
                                    SQLite (WAL) + File System (persistence)
                                                ↓
                              serialize_for_api(NDDataset) → API → Frontend (Visualization)
```

---

## Technology Stack

### Frontend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | Vue 3 | 3.x | Reactive UI framework |
| **Language** | TypeScript | 5.x | Type-safe development |
| **UI Library** | PrimeVue | Latest | Enterprise UI components |
| **Visualization** | Plotly.js | 2.x | Interactive scientific plots |
| **State Management** | Pinia | 2.x | Reactive state stores |
| **Build Tool** | Vite | 5.x | Fast dev server & bundler |
| **Routing** | Vue Router | 4.x | SPA navigation |

**Key Features:**
- Server-side rendering support (SSR-ready)
- Hot module replacement (HMR)
- TypeScript strict mode
- Component-based architecture
- Dark theme UI

### Backend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | FastAPI | 0.100+ | Async REST API |
| **Language** | Python | 3.11+ | Core language |
| **ORM** | SQLAlchemy | 2.0+ | Database abstraction (async) |
| **Validation** | Pydantic | 2.x | Request/response validation |
| **Migration** | Alembic | Latest | Database schema management |
| **ASGI Server** | Uvicorn | Latest | Production server |
| **Task Queue** | (Optional) | - | Future: Celery for long jobs |

**Key Features:**
- Async/await throughout
- Automatic OpenAPI docs (Swagger)
- Type hints + runtime validation
- JWT authentication ready
- CORS configured

### Core Data Model (Big Rollback Plan Architecture)

**NDDataset is the SOLE data type** throughout the DAG. No wrapper classes.

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Data Container** | `NDDataset` (SpectroChemPy) | The one and only data type — coordinates, units, slicing, array operations |
| **Provenance** | `meta_helpers.py` (`app/services/dag/`) | Processing history stored in `dataset.meta["processing_history"]` via `add_processing_step()` |
| **Serialization** | `serialize_for_api()` (`app/services/dag/serialize.py`) | Single source of truth for API responses — called ONLY at API boundary |
| **Storage** | Parquet + JSON sidecar | Efficient persistent storage for spectral data via `save_dataset_parquet()` / `load_dataset_parquet()` |

**Node pattern:** `input.copy()` → SCP method → `add_processing_step()` → return NDDataset

### Scientific Stack

| Library | Purpose | Use Cases |
|---------|---------|-----------|
| **SpectroChemPy** | FTIR spectroscopy | Data loading, preprocessing, analysis |
| **scikit-learn** | Machine learning | PCA, PLS, classification, regression |
| **NumPy** | Numerical computing | Array operations, linear algebra |
| **SciPy** | Scientific computing | Signal processing, optimization |
| **pandas** | Data manipulation | Tabular data, CSV export |
| **statsmodels** | Statistical models | Regression, ANOVA |

### Database

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **RDBMS** | SQLite 3 (WAL mode) | Lightweight, local-compute-first |
| **Schema** | Relational | Workflows, experiments, results |
| **Connection** | aiosqlite | Async driver |
| **Pooling** | SQLAlchemy pool | Connection management |

**Schema Overview:**
- `workflows` - Saved workflow definitions
- `workflow_executions` - Execution history
- `experiment_files` - Uploaded spectral data
- `nist_library` - Reference spectra
- `users` - User identity (enriched from server in hybrid mode)
- `user_egress_defaults` - Data egress permissions per user

### DevOps

| Tool | Purpose |
|------|---------|
| **Poetry** | Python dependency management |
| **npm/pnpm** | JavaScript dependency management |
| **Docker** | Containerization (optional) |
| **Git** | Version control |

---

## Core Capabilities

### 1. Visual Workflow Builder

**Drag-and-Drop Interface:**
- 50+ pre-built nodes organized by category
- Visual connection of inputs/outputs
- Real-time validation
- Auto-layout with topological sort
- Zoom, pan, node search

**Node Categories:**
1. **Data Sources** (8 nodes)
   - Load from SpectroChemPy examples
   - Load from database
   - Load from NIST library
   - Load group of files (NEW)
   - Generate synthetic data

2. **Preprocessing** (12 nodes)
   - Baseline correction
   - Normalization (multiple methods)
   - Smoothing (Savitzky-Golay, moving average)
   - Derivative calculation
   - Spectral cropping
   - Peak detection

3. **Modeling** (15 nodes)
   - PCA (Principal Component Analysis)
   - PLS (Partial Least Squares)
   - MCR-ALS (Multivariate Curve Resolution)
   - Classification (SVM, Random Forest, KNN)
   - Regression (Linear, Ridge, Lasso)
   - Clustering (K-means, hierarchical)

4. **Visualization** (10 nodes)
   - Line plots
   - Scatter plots
   - Heatmaps
   - Contour plots
   - 3D surface plots
   - Interactive Plotly charts

5. **Output** (5 nodes)
   - CSV export
   - Report generation
   - Database storage
   - File export

### 2. Data Loading & Management

**Supported Formats:**
- OPUS files (`.0`, `.1`, `.0000`, etc.) ✅
- SPA files (`.spa`, `.SPA`) ✅
- SPG files (`.spg`, `.SPG`) ✅
- CSV files (`.csv`)
- HDF5 files (`.h5`)
- JCAMP-DX (`.jdx`)

**Loading Modes:**
- **Single File:** Load one spectrum
- **Group Loading:** Load multiple files with pattern matching (NEW)
  - Wildcard patterns: `*.spa`, `test_*.0*`
  - Case-insensitive matching ✅
  - Sort options: filename, numeric suffix, modification time
  - X-axis validation
  - Recursive subdirectory scanning

**Data Sources:**
- SpectroChemPy built-in examples (CO₂, H₂O, etc.)
- Local file uploads
- PostgreSQL database
- NIST spectral library
- Synthetic data generation

### 3. Spectral Preprocessing

**Baseline Correction:**
- Polynomial fitting
- Asymmetric Least Squares (ALS)
- Rubberband correction
- Manual baseline subtraction

**Normalization:**
- Min-Max scaling
- Standard Normal Variate (SNV)
- Mean centering
- Vector normalization
- Area normalization

**Signal Processing:**
- Savitzky-Golay smoothing
- Moving average
- Fourier transform filtering
- 1st/2nd derivative calculation

**Spectral Operations:**
- Region selection (crop)
- Peak detection & fitting
- Integration
- Arithmetic operations

### 4. Chemometric Analysis

**Dimensionality Reduction:**
- **PCA:** Principal Component Analysis
  - Variance explained
  - Scores & loadings plots
  - Scree plot
  - Outlier detection

**Decomposition:**
- **MCR-ALS:** Multivariate Curve Resolution
  - Pure component spectra
  - Concentration profiles
  - Constraints (non-negativity, unimodality)

**Regression:**
- **PLS:** Partial Least Squares Regression
  - Calibration models
  - Cross-validation
  - Prediction intervals
  - Variable importance

**Classification:**
- SVM (Support Vector Machine)
- Random Forest
- K-Nearest Neighbors
- Logistic Regression
- Neural Networks

### 5. Visualization & Export

**Interactive Plots:**
- **Quick Plot:** Instant visualization in modal
- **Plotly Integration:** Zoom, pan, hover tooltips
- **Export Options:** PNG, SVG, PDF

**Data Export:**
- **CSV Export:** Full dataset with headers
- **Excel Export:** Multi-sheet workbooks
- **JSON Export:** Structured data
- **PDF Reports:** Automated reporting

**Display Options:**
- Overlay mode (all spectra on same axis)
- Stacked mode (vertically offset)
- Heatmap view (2D intensity)
- 3D surface plots

### 6. Workflow Management

**Workflow Operations:**
- Save/Load workflows
- Duplicate workflows
- Version history
- Export workflow as Python code
- Template library

**Execution Control:**
- Execute entire workflow
- Execute selected nodes
- Step-by-step execution
- Execution history
- Result caching

**Error Handling:**
- Node-level error capture
- Detailed error messages
- Rollback on failure
- Validation before execution

---

## Recent Improvements (2026-01-21)

### Critical Bug Fixes

1. **3D Concatenation Bug** ✅
   - **Issue:** Group loading created 3D arrays breaking downstream nodes
   - **Fix:** Changed from `np.stack()` to `np.concatenate()` with 2D normalization
   - **Impact:** All multi-file loading now produces correct 2D output

2. **Case-Sensitive File Matching** ✅
   - **Issue:** `*.spa` didn't match `.SPA` on Linux/macOS
   - **Fix:** Implemented case-insensitive pattern matching using `fnmatch`
   - **Impact:** Consistent behavior across all platforms

3. **Quick Plot Y-Axis Labels** ✅
   - **Issue:** Only 1 curve displayed instead of multiple
   - **Fix:** Added y-axis label serialization to backend
   - **Impact:** All loaded spectra now visualize correctly with proper labels

4. **OPUS File Label Generation** ✅
   - **Issue:** Files like `test.0000` had labels stripped to just `test`
   - **Fix:** Changed from `Path.stem` to `Path.name` to preserve extensions
   - **Impact:** OPUS files now have unique, correct labels

5. **Dedicated Load Group Enforcement** ✅
   - **Issue:** DataSourceNode and LoadGroupNode had overlapping functionality
   - **Fix:** Enforced clear separation - DataSourceNode = single files only
   - **Impact:** Clear architecture, no confusion, better error messages

### Architectural Improvements

**Clear Separation of Concerns:**
- DataSourceNode: Single file loading
- LoadGroupNode: Multiple file loading (batch operations)
- No duplication, single source of truth

**Enhanced Error Messages:**
- Pattern detection errors guide users to correct node
- Detailed debugging information
- Step-by-step resolution instructions

**Better User Experience:**
- Consistent platform behavior
- Proper file labeling
- All visualization features working correctly

---

## System Capabilities Summary

### What SpectraSherpa Can Do

✅ **Load spectral data** from 7+ file formats
✅ **Group load** multiple files with pattern matching
✅ **Preprocess** spectra (baseline, normalize, smooth, derivative)
✅ **Analyze** with PCA, PLS, MCR-ALS
✅ **Classify** samples using ML models
✅ **Regress** quantitative models
✅ **Visualize** interactively with Plotly
✅ **Export** to CSV, Excel, JSON, PDF
✅ **Build workflows** visually with drag-and-drop
✅ **Save/load workflows** for reproducibility
✅ **Execute** entire pipelines with one click
✅ **Cache results** for fast re-execution
✅ **Handle errors** gracefully with detailed messages

### What SpectraSherpa Does NOT Do (Yet)

❌ Real-time multi-user collaboration (hybrid mode links a single server identity)
❌ 3D spectral data (images, hyperspectral)
❌ Real-time instrument integration
❌ Mobile app

---

## Performance Characteristics

### Scalability

| Metric | Limit | Notes |
|--------|-------|-------|
| **Spectra per dataset** | ~1000 | UI limits to 50 traces in Quick Plot for performance |
| **Data points per spectrum** | ~10,000 | Typical FTIR: 2000-5000 points |
| **Workflow nodes** | 100+ | No hard limit, UI tested up to 50 |
| **Concurrent users** | 10-50 | Depends on server resources |
| **File upload size** | 100 MB | Configurable |

### Optimization Features

- **Virtual scrolling** in data tables
- **Lazy loading** of plots
- **Result caching** in DAG execution
- **Incremental updates** (only re-execute changed nodes)
- **Compressed data transfer** (gzip)

---

## Deployment Options

### Quick Start (pip install)

```bash
pip install -e .
spectra-sherpa
```

Server starts at http://localhost:8000 and opens your browser.
Frontend SPA is bundled inside the package — no Node.js required.

### Development

```bash
# Backend (with auto-reload)
cd src/spectra_sherpa
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

**Frontend dev:** http://localhost:5173 (proxies to backend at :8000)

### Production (Docker)

```bash
cd deploy
docker compose -f docker-compose.prod.yaml up -d --build
```

See [DigitalOcean Deployment Guide](../deployment/DIGITAL_OCEAN.md) for cloud setup.

---

## Security Considerations

### Current Security Features

✅ **Input validation** (Pydantic models)
✅ **SQL injection protection** (SQLAlchemy ORM)
✅ **CORS configuration**
✅ **Path traversal protection** (symlink validation)
✅ **File type validation**
✅ **Error message sanitization**
✅ **Mode-dependent auth** (local: implicit, hybrid: API-key identity, demo: JWT)
✅ **API key encryption** (AES-256 for stored LLM keys)
✅ **Egress controls** (per-user data egress defaults)

### Deployment Mode Auth Summary

| Mode | Auth Method | Login Page | Admin Access |
|------|-------------|------------|--------------|
| **Local** | None (implicit user) | Skipped | Hidden |
| **Hybrid** | `SPECTRASHERPA_API_KEY` → server identity | Skipped | Enabled if server user is admin |
| **Demo/Cloud** | JWT (email + password) | Required | Enabled if user is admin |

### Future Security Enhancements

🔲 Role-based access control (beyond admin/user)
🔲 Audit logging
🔲 HTTPS enforcement (production)
🔲 OAuth providers (Google, GitHub, ORCID)

---

## API Overview

### REST Endpoints

**Workflows:**
- `GET /api/v1/workflows` - List all workflows
- `POST /api/v1/workflows` - Create workflow
- `GET /api/v1/workflows/{id}` - Get workflow
- `PUT /api/v1/workflows/{id}` - Update workflow
- `DELETE /api/v1/workflows/{id}` - Delete workflow
- `POST /api/v1/workflows/{id}/execute` - Execute workflow

**Nodes:**
- `GET /api/v1/workflows/node-types` - List available node types
- `GET /api/v1/workflows/spectrochempy-examples` - List example datasets

**Data:**
- `GET /api/v1/experiments` - List experiment files
- `POST /api/v1/experiments/upload` - Upload file
- `GET /api/v1/nist` - Search NIST library

**Auto-Generated Docs:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## File Structure

```
Refactored/
├── pyproject.toml                      # Root package definition (pip install -e .)
├── src/spectra_sherpa/             # The pip-installable package
│   ├── __init__.py                     # Version + meta-path finder (app.* alias)
│   ├── cli.py                          # `spectra-sherpa` CLI entry point
│   ├── _paths.py                       # Dual-mode path resolution (dev/pip)
│   ├── app/
│   │   ├── api/v1/routes/              # API endpoints
│   │   ├── models/                     # SQLAlchemy models
│   │   ├── services/
│   │   │   └── dag/
│   │   │       ├── executor.py         # DAG engine
│   │   │       ├── node_base.py        # Base node class (thread-pool offload)
│   │   │       └── nodes/              # 60+ node implementations
│   │   │           ├── data.py         # Data loading nodes
│   │   │           ├── preprocessing.py
│   │   │           ├── modeling.py
│   │   │           └── output.py
│   │   ├── core/                       # Config, database
│   │   └── main.py                     # FastAPI app + SPA mount
│   ├── libs/                           # NIST scraper
│   ├── alembic/                        # Database migrations
│   └── static/                         # Pre-built Vue frontend (committed)
│
├── frontend/                           # Vue 3 source (dev only)
│   ├── src/
│   │   ├── views/
│   │   │   └── workflow-builder/
│   │   │       ├── WorkflowBuilderContent.vue
│   │   │       ├── NodeDetailView.vue
│   │   │       ├── WorkflowInspector.vue
│   │   │       └── modals/
│   │   ├── stores/                     # Pinia state
│   │   ├── components/                 # Reusable components
│   │   └── utils/                      # Helpers
│   ├── package.json
│   └── vite.config.ts
│
├── deploy/                             # Docker / cloud infrastructure
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── docker-compose.prod.yaml
│   ├── Caddyfile
│   └── nginx.conf
│
├── tests/                              # Backend tests
├── scripts/                            # Build & migration scripts
├── docs/                               # Documentation (mkdocs)
└── spectrasherpa-server/               # Paid cloud service (separate)
```

---

## Integration Points

### External Systems

**Database:**
- SQLite (WAL mode) for persistence — local-compute-first, no separate DB server
- SQLAlchemy async ORM (aiosqlite driver)
- Alembic migrations

**File Storage:**
- Local filesystem (default)
- S3-compatible storage (future)
- Database BLOBs (small files)

**Libraries:**
- SpectroChemPy (FTIR operations)
- scikit-learn (ML models)
- Plotly (visualization)

### Extension Points

**Custom Nodes:**
```python
@register_node
class CustomNode(Node):
    metadata = NodeMetadata(
        node_type="custom.mynode",
        category="custom",
        label="My Node",
        # ...
    )

    async def execute(self, input_data):
        # Your processing logic
        return output_data
```

**Custom API Endpoints:**
```python
@router.get("/custom-endpoint")
async def custom_endpoint():
    return {"message": "Hello"}
```

---

## Browser Support

| Browser | Minimum Version | Notes |
|---------|----------------|-------|
| Chrome | 90+ | ✅ Recommended |
| Firefox | 88+ | ✅ Fully supported |
| Safari | 14+ | ✅ Fully supported |
| Edge | 90+ | ✅ Chromium-based |
| IE | ❌ | Not supported |

**Requirements:**
- JavaScript enabled
- WebGL for advanced visualizations
- Modern CSS support (Grid, Flexbox)

---

## Known Limitations

### Current Limitations

1. **No real-time collaboration:** Multiple users can't edit same workflow simultaneously
2. **No undo/redo:** Workflow changes are immediate
3. **Limited 3D visualization:** Basic 3D plots only, no advanced volume rendering
4. **No mobile optimization:** Desktop browsers only
5. **File size limits:** Large files (>100MB) may cause performance issues
6. **Memory constraints:** Large datasets (10,000+ spectra) may exceed browser memory

### Planned Improvements

- WebSocket support for real-time updates
- Command history for undo/redo
- Progressive data loading for large files
- Mobile-responsive UI
- Distributed execution for large jobs

---

## Documentation

**User Documentation:**
- `USER_MANUAL.md` - End-user guide
- `docs/examples/` - Tutorial notebooks
- In-app tooltips and help text

**Developer Documentation:**
- `ARCHITECTURE.md` - System architecture
- `../future/ROADMAP.md` - Future plans
- `SESSION_SUMMARY_*.md` - Development sessions
- API docs (auto-generated Swagger)

**Specialized Docs:**
- `DEDICATED_LOAD_GROUP_ENFORCEMENT.md` - Group loading architecture
- `3D_CONCATENATION_FIX.md` - Concatenation bug fix
- `QUICK_PLOT_Y_AXIS_LABELS_FIX.md` - Visualization fix

---

## Version History

**v1.4.0 (2026-02-07)** - Current
- ✅ Hybrid mode API-key linked identity (`link_hybrid_identity()`)
- ✅ `SpectraSherpaUser` aligned with server `UserResponse` schema
- ✅ User lookup stability (ID-order instead of username match)
- ✅ Admin route protection via self-ID check
- ✅ Frontend `initHybridUser()` + separate local/hybrid router guards
- ✅ Offline identity degradation

**v1.3.3 (2026-01-21)**
- ✅ Fixed 3D concatenation bug
- ✅ Fixed case-sensitive file matching
- ✅ Fixed Quick Plot y-axis labels
- ✅ Fixed OPUS file label generation
- ✅ Enforced dedicated load group architecture

**v1.3.0**
- Added LoadGroupNode for batch file loading
- Improved error messages
- Enhanced visualization options

**v1.2.0**
- Added MCR-ALS decomposition
- Improved PCA visualization
- Database schema updates

**v1.1.0**
- Initial workflow builder
- Basic data loading
- Core preprocessing nodes

---

## Support & Maintenance

**Bug Reports:**
- GitHub Issues (if applicable)
- Internal tracking system

**Feature Requests:**
- User feedback form
- Roadmap planning sessions

**Maintenance:**
- Weekly dependency updates
- Monthly security audits
- Quarterly feature releases

---

## Summary

**SpectraSherpa** is a production-ready, full-stack spectral analysis platform offering:

✅ **50+ specialized processing nodes**
✅ **Visual workflow builder**
✅ **Real-time execution engine**
✅ **Modern Vue 3 + FastAPI stack**
✅ **Comprehensive FTIR analysis capabilities**
✅ **Interactive Plotly visualizations**
✅ **Flexible data import/export**
✅ **Extensible architecture**

**Recent critical bug fixes ensure:**
- Correct 2D data handling
- Platform-consistent file matching
- Proper multi-spectrum visualization
- Clear architectural separation

**Status:** ✅ **READY FOR PRODUCTION DEPLOYMENT**

---

**Last Updated:** 2026-02-07
**Document Version:** 1.2
