# Development Roadmap - Phase 1

**Version:** 1.3
**Date:** 2026-01-02
**Target Completion:** 6-8 weeks
**Updates:** Security hardening (path traversal, log scrubbing), reliable crash recovery (startup reconciliation), storage management (GC, export streaming)

---

## 🎯 Phase 1 Scope

**Goal:** Launch MVP with core functionality for single-user local operation.

**Included Modules:**
- ✅ Experiment Manager
- ✅ Spectra Builder (Project0)
- ✅ Calibration Fitter (Project1)
- ✅ NIST Search & Download
- ✅ LLM Chat

**Deferred to Phase 2:**
- MCR-ALS Analysis (SpectroChem-Py integration)
- Cloud deployment
- Multi-user support
- Advanced job queue (Celery)

---

## 📅 Timeline Overview

```
Week 1-2: Project Setup & Backend Foundation
Week 3-4: Core Services Implementation
Week 5-6: Frontend Development
Week 7: Integration & Testing
Week 8: Documentation & Polish
```

---

## 🗓️ Week-by-Week Breakdown

### **Week 1: Project Scaffolding & Database**

#### Tasks

**Backend Setup**
- [ ] Create `Refactored/src/spectra_sherpa/` directory structure
- [ ] Initialize Poetry project (`pyproject.toml`)
- [ ] Configure SQLAlchemy with single SQLite database
  - [ ] `data/spectra_platform.db` - All application data
  - [ ] Enable WAL mode (Write-Ahead Logging) for concurrent access
  - [ ] Add `PRAGMA wal_autocheckpoint=1000` to prevent WAL file growth
  - [ ] Create `get_db()` dependency with WAL pragma settings
- [ ] Set up Alembic for migrations
- [ ] Create database models (User, Experiment, Calibration, BackgroundJob, etc.)
- [ ] Generate initial migration
- [ ] Create FastAPI app skeleton (`app/main.py`)
- [ ] Create shell wrapper script (`start.sh`) with BLAS thread limiting
  - [ ] `export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4`
  - [ ] `uvicorn app.main:app --reload`
- [ ] Implement resource limits configuration (`app/core/config.py`)
  - [ ] MAX_SPECTRA_PER_JOB, MAX_WAVENUMBERS, MAX_MEMORY_MB
  - [ ] MAX_CONCURRENT_JOBS, MAX_NIST_DOWNLOADS_PER_HOUR
  - [ ] MAX_FILE_SIZE_MB, MAX_JOB_DURATION_SEC, MAX_EXPORT_SIZE_MB=1024

**Frontend Setup**
- [ ] Create `Refactored/frontend/` directory with Vite + Vue 3 + TypeScript
- [ ] Install PrimeVue + dependencies
- [ ] Set up Vue Router (basic routes)
- [ ] Set up Pinia stores (skeleton)
- [ ] Configure Axios for API calls
- [ ] Create layout with sidebar navigation

**Development Tools**
- [ ] Configure ESLint, Prettier (frontend)
- [ ] Configure Ruff, Black (backend)
- [ ] Set up `.gitignore` for both projects
- [ ] Create `docker-compose.yml` (optional, for future Redis)

**Deliverable:** Empty app runs (`npm run dev` + `uvicorn app.main:app`)

---

### **Week 2: Authentication & File Management**

#### Tasks

**Authentication (Simple for Phase 1)**
- [ ] Implement User model (basic fields only)
- [ ] Create simple API key authentication middleware
  - [ ] Check `X-API-Key` header matches `APP_API_KEY` env var
  - [ ] Default to "default-local-key" for local-only use
- [ ] Frontend: Store API key in localStorage
- [ ] **Note:** Defer JWT/bcrypt to Phase 2 (multi-user cloud deployment)

**External API Key Encryption**
- [ ] Implement AES-256 encryption for external API keys (NIST, DeepSeek)
  - [ ] Use system keyring for master encryption key (Windows Credential Manager, macOS Keychain, Linux Secret Service)
  - [ ] Fallback: Generate random master key, store in `.env` file with secure permissions (600)
- [ ] Create `APIKey` CRUD endpoints (for storing third-party keys)
- [ ] Frontend settings page for API key management

**File Storage Foundation (Security Hardening)**
- [ ] Create `data/` directory structure (experiments, calibrations, nist_library)
- [ ] Implement file upload handler (multipart/form-data)
- [ ] **SECURITY:** File validation with path traversal protection
  - [ ] Reject filenames containing `..`, `/`, `\`, null bytes
  - [ ] Use `os.path.basename()` to strip path components
  - [ ] Validate file extensions against whitelist (`.csv`, `.jdx`, `.json`)
  - [ ] Sanitize filenames: `secure_filename()` from werkzeug
- [ ] File size validation (MAX_FILE_SIZE_MB) with resource limits
- [ ] Utility functions for file operations
- [ ] Implement rate limiter class (`app/services/rate_limiter.py`)
  - [ ] In-memory deque-based rate limiting
  - [ ] Instantiate NIST rate limiter (50 requests/hour)
  - [ ] Optional: Persist rate limit state to `data/rate_limits.json`

**Log Viewer (Security Hardening)**
- [ ] Implement in-memory log buffer (`collections.deque(maxlen=1000)`)
- [ ] Create custom `BufferHandler` for logging with scrubbing
  - [ ] **SECURITY:** Regex-based log sanitization (redact API keys, passwords, tokens)
  - [ ] Pattern: `sk-[a-zA-Z0-9]{20,}`, `Bearer [a-zA-Z0-9]+`, `password.*=.*`
  - [ ] Replace matches with `[REDACTED]`
- [ ] Create `GET /api/v1/logs` endpoint (returns recent log entries)
  - [ ] **SECURITY:** Require localhost-only access or admin role (Phase 2)
- [ ] Frontend: Add log viewer panel in developer tools section

**Deliverable:** User can authenticate with simple API key, manage external API keys, and view application logs

---

### **Week 3: Experiment Manager (Backend)**

#### Tasks

**Experiment Service**
- [ ] Implement `ExperimentService` class
  - [ ] `create_experiment(metadata)` - Create with hardware/DOE info
  - [ ] `get_experiment(id)` - Fetch with metadata
  - [ ] `list_experiments()` - Paginated list
  - [ ] `update_experiment(id, metadata)` - Edit metadata
  - [ ] `delete_experiment(id)` - Soft/hard delete

**File Management**
- [ ] `upload_file(exp_id, file, stage)` - Upload raw/preprocessed files
- [ ] `list_files(exp_id, stage)` - Get files by stage
- [ ] `delete_file(file_id)` - Remove file

**Versioning (Content-Addressable Storage with Garbage Collection)**
- [ ] Implement `VersionStorage` abstraction layer (`app/services/version_storage.py`)
  - [ ] Abstract base class with `create_version()` and `restore_version()`
- [ ] Implement `ContentAddressableStorage` class
  - [ ] `store_file(file_path)` - Hash file (SHA-256) and store in `objects/`
  - [ ] `create_version(files, description)` - Create manifest.json
  - [ ] `restore_version(manifest)` - Copy files from `objects/` to working dir
  - [ ] Deduplication: only copy file if hash doesn't exist
- [ ] Create `objects/` directory structure per experiment
- [ ] `list_versions(exp_id)` - Get version history from manifests
- [ ] **CRITICAL:** Implement garbage collection for orphaned objects
  - [ ] `get_all_referenced_hashes(exp_id)` - Scan all manifests, collect hashes
  - [ ] `find_orphaned_objects(exp_id)` - Compare `objects/` dir against referenced hashes
  - [ ] `garbage_collect(exp_id, grace_period_days=7)` - Delete orphans older than grace period
  - [ ] Manual cleanup script: `scripts/gc_storage.py --experiment-id=123 --dry-run`
  - [ ] Phase 2: Automatic GC task (run weekly via cron or background scheduler)

**API Endpoints**
- [ ] `GET /api/v1/experiments`
- [ ] `POST /api/v1/experiments`
- [ ] `GET /api/v1/experiments/{id}`
- [ ] `PUT /api/v1/experiments/{id}`
- [ ] `DELETE /api/v1/experiments/{id}`
- [ ] `POST /api/v1/experiments/{id}/files`
- [ ] `GET /api/v1/experiments/{id}/versions`
- [ ] `POST /api/v1/experiments/{id}/versions`
- [ ] `POST /api/v1/experiments/{id}/versions/{ver}/restore`

**Deliverable:** Full CRUD for experiments with versioning

---

### **Week 4: Builder & Calibration Services (Backend)**

#### Tasks

**Builder Service (Project0 Integration)**
- [ ] Copy `Original/Synthetic_Spectra_Builder_py/Project0/` to `libs/project0/`
- [ ] Refactor as library (remove FastAPI routes)
- [ ] **CRITICAL:** Implement preprocessing cache with mtime tracking (`app/services/cache.py`)
  - [ ] Cache key: `(file_path, file_mtime, settings_hash)` to prevent stale data
  - [ ] `@lru_cache(maxsize=128)` decorator for `load_preprocessed_spectrum()`
  - [ ] Settings-based cache invalidation (hash of settings dict)
  - [ ] File modification time check: `os.path.getmtime(file_path)`
  - [ ] Optional: Disk cache with `.npz` files (include mtime in filename)
- [ ] Implement `BuilderService` wrapper
  - [ ] `preprocess(spectra, settings)` - Preprocessing pipeline with caching
  - [ ] `blend(species, concentrations, settings)` - Multi-species blending
  - [ ] `generate_curves(count)` - Curve generation
  - [ ] Add resource validation (max spectra, max wavenumbers)
- [ ] Create API endpoints:
  - [ ] `POST /api/v1/builder/preprocess` (with caching)
  - [ ] `POST /api/v1/builder/blend` (with resource limits)
  - [ ] `GET /api/v1/builder/curves/default`
  - [ ] `POST /api/v1/builder/curves/generate`

**Calibration Service (Project1 Integration)**
- [ ] Copy `Original/Synthetic_Spectra_Builder_py/Project1/` to `libs/project1/`
- [ ] Implement `CalibrationService` wrapper
  - [ ] `create_calibration(metadata)` - Initialize calibration
  - [ ] `upload_measurement(cal_id, file, concentration)` - Add data point
  - [ ] `fit_model(cal_id, model_type, settings)` - Fit linear/saturation/hybrid
    - [ ] Add resource validation (max measurement points, timeout)
  - [ ] `activate_model(cal_id, model_id)` - Set production model
  - [ ] `get_active_model(cal_id)` - Retrieve current model
- [ ] Create API endpoints:
  - [ ] `GET /api/v1/calibrations`
  - [ ] `POST /api/v1/calibrations`
  - [ ] `POST /api/v1/calibrations/{id}/measurements`
  - [ ] `POST /api/v1/calibrations/{id}/fit` (with timeout protection)
  - [ ] `GET /api/v1/calibrations/{id}/models`
  - [ ] `PUT /api/v1/calibrations/{id}/models/{ver}/activate`

**Deliverable:** Backend can preprocess, blend, and fit calibrations

---

### **Week 5: NIST & LLM Services (Backend)**

#### Tasks

**NIST Service** (No API Key Required - Public Domain Data)
- [ ] Copy `Original/Pull_FTIR_from_NIST/` to `libs/nist_scraper/`
- [ ] Refactor as library (remove CLI interface)
- [ ] Implement `NISTService` wrapper
  - [ ] `search(query)` - Search NIST database via HTTP (no auth)
  - [ ] `download(cas, resolution)` - Download spectrum (background task)
    - [ ] Apply rate limiter (50 downloads/hour, self-imposed for politeness)
    - [ ] Validate file size before download
  - [ ] `list_library()` - Get downloaded spectra
- [ ] Create API endpoints:
  - [ ] `GET /api/v1/nist/search?query={compound}` (direct NIST WebBook access)
  - [ ] `POST /api/v1/nist/download` (with rate limiting)
  - [ ] `GET /api/v1/nist/library`
- [ ] Bundle top 100 NIST spectra with app distribution (in `data/bundled/nist_samples/`)

**HITRAN Service** (Free Academic Data - Bundle Core Set)
- [ ] Download top 50 atmospheric molecules from HITRAN
- [ ] Convert to SQLite database (`data/bundled/hitran_core.db`)
- [ ] Implement `HITRANService` for local queries
  - [ ] `search_molecule(formula)` - Find in bundled database
  - [ ] `get_spectrum(molecule_id, wavenumber_range)` - Extract line data
- [ ] Create API endpoints:
  - [ ] `GET /api/v1/hitran/molecules` - List bundled molecules
  - [ ] `GET /api/v1/hitran/spectrum?molecule={H2O}&wn_min={500}&wn_max={5000}`
- [ ] Phase 2: Optional user account linking for live API access

**LLM Service**
- [ ] Copy `Original/llm/api_call.py` logic to `app/services/llm.py`
- [ ] Implement `LLMService` wrapper
  - [ ] `chat(message, conversation_id, metadata)` - Send message
  - [ ] `stream_chat(message, conversation_id)` - Streaming response
  - [ ] `auto_suggest_name(components)` - Generate experiment name
  - [ ] `identify_peaks(spectrum, wavenumbers)` - Peak identification
  - [ ] `generate_code(task_description)` - Code generation
  - [ ] `write_report(experiment)` - Report writing
- [ ] Create API endpoints:
  - [ ] `POST /api/v1/llm/chat`
  - [ ] `GET /api/v1/llm/conversation/{id}`
  - [ ] `DELETE /api/v1/llm/conversation/{id}`
  - [ ] `POST /api/v1/llm/suggest-name`
  - [ ] `POST /api/v1/llm/identify-peaks`
  - [ ] `POST /api/v1/llm/generate-code`
  - [ ] `POST /api/v1/llm/write-report`

**Background Jobs (Crash-Safe with Startup Reconciliation)**
- [ ] **CRITICAL:** Implement startup job reconciliation (handles hard kills, power loss)
  - [ ] On app startup (FastAPI `@app.on_event("startup")`):
    - [ ] Query all jobs with `status='running'`
    - [ ] Mark them as `failed` with error "Server crashed (stale job from previous session)"
    - [ ] Log reconciliation: "Reconciled 3 stale jobs on startup"
  - [ ] Add `last_heartbeat` timestamp to BackgroundJob model
    - [ ] Update heartbeat every 30 seconds during job execution
    - [ ] Reconcile jobs with `last_heartbeat` older than 5 minutes (stale)
- [ ] Implement `JobManager` class with graceful shutdown (best-effort only)
  - [ ] Register signal handlers (SIGINT, SIGTERM) for graceful shutdown
  - [ ] Register `atexit` handler for cleanup
  - [ ] Track running jobs in `self.running_jobs` dict
  - [ ] **NOTE:** These handlers WON'T run on SIGKILL/power loss - startup reconciliation handles those cases
  - [ ] On graceful shutdown: mark running jobs as `cancelled` with error "Server shutting down"
- [ ] Implement `JobService` using FastAPI BackgroundTasks
  - [ ] `create_job(user_id, job_type, compute_location)` - Initialize job with provenance
  - [ ] `update_progress(job_id, progress, message)` - Update status + heartbeat (WAL mode prevents UI freezes)
  - [ ] `complete_job(job_id, result_path)` - Mark done
  - [ ] `fail_job(job_id, error)` - Mark failed
  - [ ] Enforce `MAX_CONCURRENT_JOBS` limit
  - [ ] Add job timeout monitoring (cancel after `MAX_JOB_DURATION_SEC`)
  - [ ] Track `compute_location` (local, nist_api, deepseek_api) and `compute_node` (hostname/endpoint)
- [ ] Create API endpoints:
  - [ ] `GET /api/v1/jobs`
  - [ ] `GET /api/v1/jobs/{id}`
  - [ ] `DELETE /api/v1/jobs/{id}` (cancel job)

**WebSocket**
- [ ] Implement WebSocket handler (`/ws`)
- [ ] Subscribe/unsubscribe to job channels
- [ ] Broadcast job progress updates (with batching - max 1 update/100ms)
- [ ] Stream LLM responses
- [ ] Handle reconnection logic (client-side)

**Deliverable:** NIST search, LLM chat, crash-safe job tracking, and compute provenance work

---

### **Week 6: Frontend Development**

#### Tasks

**Experiments View**
- [ ] Create `ExperimentsView.vue`
- [ ] Implement experiment list (PrimeVue DataTable)
- [ ] Create experiment modal (hardware, DOE, mixtures input)
- [ ] File upload drag-and-drop zone
- [ ] Version history tree view (with restore button)
- [ ] **Export button:** Download experiment as CSV/Excel/JSON/ZIP
  - [ ] **CRITICAL:** Validate export size before starting (MAX_EXPORT_SIZE_MB=1024)
  - [ ] Show size warning if export >500 MB
  - [ ] Use streaming ZIP generation (`zipstream-ng` library) to avoid memory exhaustion
- [ ] Integrate with `useExperimentStore()`

**Builder View**
- [ ] Create `BuilderView.vue`
- [ ] Spectrum list panel (from loaded experiment)
- [ ] Preprocessing settings form
- [ ] Plotly.js interactive chart
- [ ] Blending controls (concentration sliders for each species)
- [ ] Catmull-Rom curve editor (drag-and-drop control points)
- [ ] **Export button:** Download blended spectra as CSV/Excel
- [ ] Integrate with `useBuilderStore()`

**Calibration View (nested under Builder or separate)**
- [ ] Create `CalibrationView.vue`
- [ ] Calibration list (DataTable)
- [ ] Create calibration modal (compound, mode, measurements)
- [ ] Upload measurements at various concentrations
- [ ] Fit model button (linear/saturation/hybrid selector)
- [ ] Model version list with activate toggle
- [ ] Plotly.js calibration curve plot (data points + fitted curve)
- [ ] **Export button:** Download calibration data and model as CSV/JSON
- [ ] Integrate with `useCalibrationStore()` (create if not exists)

**NIST View**
- [ ] Create `NISTView.vue`
- [ ] Search bar with autocomplete
- [ ] Results table (compound name, CAS, resolution options)
- [ ] Download button (triggers background job)
- [ ] Download queue panel (job progress bars via WebSocket)
- [ ] Downloaded library table (with preview and load-to-builder button)
- [ ] **Export button:** Export NIST library to CSV/Excel
- [ ] Integrate with `useNISTStore()`

**Chat View**
- [ ] Create `ChatView.vue`
- [ ] Chat interface (message list + input box)
- [ ] Streaming responses (WebSocket)
- [ ] Conversation history sidebar
- [ ] Feature buttons: auto-suggest, peak ID, code gen, report writing
- [ ] Metadata context toggle (include experiment info in prompt)
- [ ] Integrate with `useLLMStore()`

**Pinia Stores**
- [ ] Complete `stores/experiment.ts` with all actions
- [ ] Complete `stores/builder.ts` with all actions
- [ ] Create `stores/calibration.ts` (if separate from builder)
- [ ] Complete `stores/nist.ts` with all actions
- [ ] Complete `stores/llm.ts` with all actions
- [ ] Create `stores/job.ts` with WebSocket subscription logic

**Common Components**
- [ ] Create `JobProgressBar.vue` (reusable progress bar)
- [ ] Create `PlotlyChart.vue` (wrapper for Plotly.js)
- [ ] Create `FileUploader.vue` (drag-and-drop uploader)
- [ ] Create `VersionTree.vue` (version history tree)

**Deliverable:** Full frontend with all views operational

---

### **Week 7: Integration & Testing**

#### Tasks

**End-to-End Testing**
- [ ] Test experiment creation → file upload → versioning → restore
  - [ ] Verify content-addressable storage (check `objects/` deduplication)
  - [ ] Test version restore from manifest
- [ ] Test builder: load experiment → preprocess → blend → export
  - [ ] Verify caching (second load should be instant)
  - [ ] Test resource limits (try uploading >1000 spectra)
  - [ ] **Plotly performance:** Test 50k+ point spectrum rendering with `scattergl` mode
  - [ ] Verify export functionality (CSV, Excel, JSON formats)
- [ ] Test calibration: create → upload measurements → fit → activate model
  - [ ] Test timeout handling for long-running fits
  - [ ] Verify export functionality (calibration data + models)
- [ ] Test NIST: search → download (background job) → load to library
  - [ ] Verify rate limiting (try 51 downloads in 1 hour)
  - [ ] Verify NIST library export
- [ ] Test LLM: chat → streaming → auto-suggest → peak ID → code gen
- [ ] Test database WAL mode
  - [ ] Verify concurrent reads work during job progress writes
  - [ ] Monitor for UI freezes during background jobs (should be none)
- [ ] Test log viewer
  - [ ] Verify recent logs appear in `/api/v1/logs` endpoint
  - [ ] Test log buffer rotation (max 1000 entries)

**WebSocket Integration**
- [ ] Verify job progress updates in real-time (NIST download)
- [ ] Verify LLM streaming works correctly
- [ ] Test reconnection logic

**Data Migration**
- [ ] Implement `migrate_experiments.py` (import from Original/Exp_loader)
- [ ] Implement `migrate_calibrations.py` (import from Original/Synthetic_Spectra_Builder_py)
- [ ] Implement `migrate_nist.py` (import from Original/Pull_FTIR_from_NIST)
- [ ] Test migration scripts with sample data

**Bug Fixes & Polish**
- [ ] Fix any integration issues
- [ ] Add loading states (skeletons, spinners)
- [ ] Add error handling (toasts, error messages)
  - [ ] Display helpful messages for resource limit violations
  - [ ] Show rate limit countdown (e.g., "Rate limit exceeded. Try again in 45 minutes")
- [ ] Improve UX (keyboard shortcuts, tooltips)
- [ ] Add cache statistics to debug panel (optional)

**Unit Tests**
- [ ] Write pytest tests for core services (experiment, builder, calibration)
  - [ ] Test `ContentAddressableStorage` (deduplication, restore)
  - [ ] Test rate limiter (window sliding, request counting)
  - [ ] Test resource validators (memory estimation, size limits)
  - [ ] Test cache invalidation (settings hash changes)
- [ ] Write Vitest tests for Pinia stores
- [ ] Aim for >70% coverage on critical paths

**Deliverable:** Stable MVP ready for alpha testing

---

### **Week 8: Documentation & Deployment**

#### Tasks

**Documentation**
- [ ] Write `README.md` (how to install and run)
- [ ] Write `QUICKSTART.md` (5-minute tutorial)
- [ ] Write `API.md` (REST endpoints reference)
- [ ] Write `MIGRATION.md` (import old data)
- [ ] Write `DEPLOYMENT.md` (local installation)
- [ ] Write `PERFORMANCE.md` (optimizations, troubleshooting, debugging)
  - [ ] Document SQLite WAL mode configuration and benefits
  - [ ] Document cache configuration (LRU size, invalidation)
  - [ ] Document resource limit configuration (memory, CPU, file size)
  - [ ] Explain content-addressable storage benefits (deduplication)
  - [ ] Document BLAS thread limiting (why cap at 4 threads)
  - [ ] Document crash-safe job manager (cleanup handlers)
  - [ ] Document compute provenance tracking
  - [ ] Document log viewer usage
  - [ ] Troubleshooting: UI freezes, storage explosion, job crashes
  - [ ] Plotly performance tips (scattergl for 50k+ points)
- [ ] Document all Pinia stores (comments + README)
- [ ] Document all Vue components (comments)

**User Guide**
- [ ] Create user guide with screenshots:
  - [ ] Login and API key setup
  - [ ] Creating an experiment
  - [ ] Uploading and preprocessing spectra
  - [ ] Generating synthetic blends
  - [ ] Fitting calibration models
  - [ ] Downloading NIST spectra
  - [ ] Using LLM chat

**Production Build**
- [ ] Test frontend build (`npm run build`)
- [ ] Serve frontend static files from backend
- [ ] Create startup script (`start.sh` or `start.bat`)
- [ ] Test on fresh machine (install from scratch)

**Release**
- [ ] Tag version `v1.0.0-alpha`
- [ ] Create GitHub release with binaries (optional)
- [ ] Announce to users

**Deliverable:** Documented, tested, production-ready MVP

---

## 📦 Deliverables Summary

By the end of Phase 1, you will have:

### **Backend**
✅ FastAPI monolith with:
- Simple API key authentication (local-first, defer JWT to Phase 2)
- Experiment CRUD with content-addressable versioning
- Spectra preprocessing and blending (Project0) with LRU caching
- Calibration fitting (Project1) with timeout protection
- NIST search and download with rate limiting
- LLM chat with streaming
- WebSocket for real-time updates (batched progress)
- Single SQLite database with WAL mode for concurrent access
- Crash-safe job manager with cleanup handlers
- Compute provenance tracking (local vs API)
- In-memory log viewer (last 1000 entries)
- Resource limits and validation (memory, CPU, file size)
- BLAS thread limiting (cap at 4 threads)
- Export endpoints (CSV, Excel, JSON, ZIP)

### **Frontend**
✅ Vue.js SPA with:
- Login page (simple API key, stored in localStorage)
- Experiment manager (list, create, upload, version, export)
- Builder (preprocess, blend, curve editor, export)
- Calibration fitter (create, fit, version, export)
- NIST search and library (with export)
- LLM chat (streaming, features)
- Real-time job progress via WebSocket
- Log viewer panel (developer tools)

### **Documentation**
✅ Complete guides for:
- Installation and setup
- Quickstart tutorial
- API reference
- Migration from Original code
- User manual

---

## 🎯 Success Metrics (Phase 1)

- [ ] User can authenticate with simple API key and manage external API keys
- [ ] User can create experiment with hardware/DOE metadata
- [ ] User can upload spectra and create versions (with deduplication)
- [ ] User can preprocess and blend spectra (with caching - second load instant)
- [ ] User can fit calibration models and manage versions
- [ ] User can search and download NIST spectra (rate limited, no server crashes)
- [ ] User can chat with LLM and use auto-suggest/peak ID features
- [ ] All background jobs show real-time progress (UI never freezes with WAL mode)
- [ ] User can export all data (experiments, calibrations, NIST library) to CSV/Excel/JSON
- [ ] User can view application logs in browser (debug panel)
- [ ] Old data can be migrated successfully
- [ ] System handles resource limits gracefully (helpful error messages)
- [ ] System handles crashes gracefully (running jobs marked as failed on restart)
- [ ] Plotly handles 50k+ point spectra smoothly (scattergl mode)
- [ ] 10 versions of 50-file experiment uses <500 MB storage (not 12.5 GB)
- [ ] BLAS operations use ≤4 threads (prevents CPU saturation)

---

## 🚀 Phase 2 Preview (Future)

**Planned for Phase 2 (Weeks 9-16):**

- MCR-ALS Analysis (SpectroChem-Py fork integration)
- Advanced job queue (Celery + Redis)
- Multi-user support (permissions, sharing)
- Cloud deployment (AWS/Azure/GCP)
- Advanced plotting (3D, heatmaps)
- Export to PDF reports
- Database migration to PostgreSQL
- Performance optimizations (caching, lazy loading)

---

## 🛠️ Development Workflow (Phase 1)

### Daily Workflow
```bash
# Terminal 1: Backend
cd src/spectra_sherpa
poetry run uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Testing
cd src/spectra_sherpa
poetry run pytest -v

# Access app at http://localhost:5173
```

### Git Workflow
```bash
# Feature branches
git checkout -b feature/experiment-versioning
git commit -m "feat: implement experiment versioning"
git push origin feature/experiment-versioning

# Merge to main after testing
git checkout main
git merge feature/experiment-versioning
```

---

## 📞 Support & Questions

For questions or blockers during Phase 1 development, refer to:
- [ARCHITECTURE.md](../current/ARCHITECTURE.md) - System design
- [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) - Database structure
- Original code in `Original/` folder for reference

---

**Roadmap Version:** 1.3
**Last Updated:** 2026-01-02
**Target Completion:** End of Week 8
**Next Review:** End of Week 4 (Mid-Phase 1 Checkpoint)

---

## 🔧 Key Performance & Security Optimizations Integrated

### Performance Optimizations
1. **Content-Addressable Storage with GC:** Files stored once by SHA-256 hash with automatic garbage collection
2. **SQLite WAL Mode with Auto-Checkpoint:** Write-Ahead Logging + periodic checkpointing prevents WAL file bloat
3. **LRU Caching with mtime:** Preprocessed spectra cached in memory, invalidated on file changes
4. **Resource Limits:** Validation for memory, CPU, file size, concurrent jobs, export size
5. **Rate Limiting with Persistence:** In-memory rate limiter (optional persistence to survive restarts)
6. **BLAS Thread Limiting:** Shell wrapper sets env vars before NumPy import (prevents import order issues)
7. **Compute Provenance:** Track whether compute happened locally or via API
8. **Export Streaming:** ZIP streaming with size validation (prevents memory exhaustion)
9. **Plotly Performance:** Use `scattergl` mode for 50k+ point spectra

### Security Hardening
10. **Crash Recovery:** Startup job reconciliation handles SIGKILL/power loss (not just graceful shutdown)
11. **Path Traversal Protection:** Filename sanitization, extension whitelist, path component stripping
12. **Log Scrubbing:** Regex-based redaction of API keys, passwords, tokens from log viewer
13. **External API Key Storage:** System keyring (Windows/macOS/Linux) with .env fallback
14. **Localhost-Only Log Access:** Log viewer restricted to localhost (Phase 1) or admin (Phase 2)

### Reliability Improvements
15. **Job Heartbeat Monitoring:** 30-second heartbeats detect stale jobs (>5 min old)
16. **Startup Reconciliation:** On app start, mark all "running" jobs as failed (handles crashes)
17. **Idempotent Crash Cleanup:** Graceful shutdown uses `UPDATE WHERE status='running'` (safe to run twice)

**Expected Benefits:**
- 95% reduction in version storage (deduplication + GC)
- UI remains responsive during background jobs (WAL mode with checkpointing)
- Instant re-processing when adjusting plot settings (cache hits with mtime validation)
- No stale cached data (mtime tracking)
- No server crashes from oversized jobs (validation + helpful errors)
- No NIST IP bans (rate limiting)
- No CPU saturation from BLAS operations (shell wrapper)
- **Reliable crash recovery** (startup reconciliation handles ALL crash types)
- **No path traversal attacks** (filename sanitization)
- **No API key leaks in logs** (regex scrubbing)
- **No unbounded storage growth** (GC removes orphaned objects)
- **No memory exhaustion on export** (streaming ZIP generation)
- Easy debugging (log viewer in browser)
- Data portability (export to Excel/Origin/Matlab)
