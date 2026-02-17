# Database Schema - SQLite Design

**Version:** 1.3
**Date:** 2026-01-02 (Updated: Added last_heartbeat for crash recovery)

---

## 📋 Schema Overview

Single SQLite database with WAL (Write-Ahead Logging) mode for local-compute-first operation, with PostgreSQL compatibility in mind for future cloud migration.

**Database File:**
- `data/spectra_platform.db` - All application data (experiments, calibrations, users, background jobs)

**Performance:** WAL mode enables concurrent readers + 1 writer, preventing UI freezes during job progress updates

---

## 🗂️ Tables

All tables reside in `data/spectra_platform.db` with WAL mode enabled.

---

### 1. User

Single-user for Phase 1, multi-user ready for Phase 2.

```sql
CREATE TABLE user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_username ON user(username);
```

---

### 2. Experiment

Metadata for experiments. Actual files stored on filesystem.

```sql
CREATE TABLE experiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    metadata_path VARCHAR(500) NOT NULL,  -- Path to metadata.json
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);

CREATE INDEX idx_experiment_user ON experiment(user_id);
CREATE INDEX idx_experiment_created ON experiment(created_at DESC);
```

**Metadata JSON fields** (stored in filesystem `metadata.json`):
- `hardware`: Instrument details, resolution, detector, etc.
- `design_of_experiment`: DOE type, factors, levels, total runs
- `mixtures`: Sample compositions, rack positions
- `acquisition_sequence`: Ordered list of measurements

---

### 3. ExperimentFile

Tracks individual spectral files within an experiment.

```sql
CREATE TABLE experiment_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    file_path VARCHAR(500) NOT NULL,  -- Relative to data/experiments/{exp_id}/
    file_type VARCHAR(50),             -- csv, jdx, json
    stage VARCHAR(50) NOT NULL,        -- raw, preprocessed, synthetic
    file_size_bytes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (experiment_id) REFERENCES experiment(id) ON DELETE CASCADE
);

CREATE INDEX idx_expfile_experiment ON experiment_file(experiment_id);
CREATE INDEX idx_expfile_stage ON experiment_file(stage);
```

**Stage values:**
- `raw`: Original uploaded files
- `preprocessed`: After cosmic ray, smoothing, etc.
- `synthetic`: Generated blends

---

### 4. ExpVersion

Git-like versioning with content-addressable storage (files stored once by hash).

```sql
CREATE TABLE exp_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    version_name VARCHAR(100) NOT NULL,  -- v1_initial, v2_cosmic_ray_removed
    description TEXT,
    manifest_path VARCHAR(500) NOT NULL,  -- Path to manifest.json
    parent_version_id INTEGER,             -- For branching (Git-like)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (experiment_id) REFERENCES experiment(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_version_id) REFERENCES exp_version(id) ON DELETE SET NULL,

    UNIQUE(experiment_id, version_name)
);

CREATE INDEX idx_expver_experiment ON exp_version(experiment_id);
CREATE INDEX idx_expver_created ON exp_version(created_at DESC);
```

**Content-Addressable Storage Structure:**
```
data/experiments/exp_001/
├── objects/                          # Content store (files by SHA-256)
│   ├── a3f9c8d2e1b4f6a8...          # sample_01_original.csv
│   ├── b7e4d1f53c2a8967...          # sample_01_cleaned.csv (unique)
│   └── c2a8f6437e1d9b5a...          # sample_02.csv
└── versions/
    ├── v1_initial/
    │   └── manifest.json             # File references by hash
    └── v2_cosmic_ray_removed/
        └── manifest.json
```

**Manifest JSON format:**
```json
{
  "version_name": "v2_cosmic_ray_removed",
  "parent_version": "v1_initial",
  "created_at": "2026-01-01T12:00:00Z",
  "description": "Removed cosmic rays from all spectra",
  "files": {
    "sample_01.csv": {
      "hash": "b7e4d1f53c2a8967...",
      "size": 524288,
      "modified": "2026-01-01T12:00:00Z"
    },
    "sample_02.csv": {
      "hash": "c2a8f6437e1d9b5a...",
      "size": 524288,
      "modified": "2026-01-01T11:30:00Z"
    }
  }
}
```

**Key Benefits:**
- Each unique file stored exactly once (deduplication)
- Fast version creation (write manifest, not files)
- SHA-256 hash verification prevents corruption
- Easy restore: copy files from `objects/` based on manifest

---

### 5. Calibration

Calibration datasets for compound quantification.

```sql
CREATE TABLE calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    compound_name VARCHAR(100) NOT NULL,
    concentration_mode VARCHAR(50) NOT NULL,  -- product (ppm·m) or concentration (ppm)
    x_unit VARCHAR(50) NOT NULL,              -- ppm·m, ppm
    pathlength_m REAL,                        -- Meters (for product mode)
    metadata_path VARCHAR(500) NOT NULL,      -- Path to metadata.json
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);

CREATE INDEX idx_calibration_user ON calibration(user_id);
CREATE INDEX idx_calibration_compound ON calibration(compound_name);
```

---

### 6. CalibrationFile

Raw measurement files at various concentrations.

```sql
CREATE TABLE calibration_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calibration_id INTEGER NOT NULL,
    file_path VARCHAR(500) NOT NULL,  -- Relative to data/calibrations/{cal_id}/raw_measurements/
    concentration REAL NOT NULL,      -- In x_unit (ppm or ppm·m)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (calibration_id) REFERENCES calibration(id) ON DELETE CASCADE
);

CREATE INDEX idx_calfile_calibration ON calibration_file(calibration_id);
```

---

### 7. CalModel

Fitted calibration models (versioned).

```sql
CREATE TABLE cal_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calibration_id INTEGER NOT NULL,
    version_name VARCHAR(100) NOT NULL,  -- v1_linear, v2_saturation
    model_type VARCHAR(50) NOT NULL,      -- linear, saturation, hybrid
    model_path VARCHAR(500) NOT NULL,     -- Path to JSON model file
    r_squared REAL,                       -- Fit quality (0-1)
    rmse REAL,                            -- Root mean squared error
    is_active BOOLEAN DEFAULT 0,          -- Current production model
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (calibration_id) REFERENCES calibration(id) ON DELETE CASCADE,

    UNIQUE(calibration_id, version_name)
);

CREATE INDEX idx_calmodel_calibration ON cal_model(calibration_id);
CREATE INDEX idx_calmodel_active ON cal_model(is_active);
```

**Model JSON format** (stored in filesystem):
```json
{
  "label": "CF4",
  "model_type": "saturation",
  "concentration_mode": "product",
  "x_unit": "ppm·m",
  "pathlength_m": 1.0,
  "reference_concentration": 1000.0,
  "wavenumbers": [400.0, 401.0, ...],
  "s": [0.50, 0.55, ...],
  "p": [1.0, 1.0, ...],
  "c": [0.001, 0.002, ...]
}
```

---

### 8. NISTLibrary

Downloaded NIST spectra catalog.

```sql
CREATE TABLE nist_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cas_number VARCHAR(50) NOT NULL,
    compound_name VARCHAR(255) NOT NULL,
    resolution VARCHAR(20) NOT NULL,      -- 2, 1, 0.5, 0.25, 0.125 cm-1
    file_path VARCHAR(500) NOT NULL,      -- Relative to data/nist_library/downloaded/
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(cas_number, resolution)
);

CREATE INDEX idx_nist_cas ON nist_library(cas_number);
CREATE INDEX idx_nist_compound ON nist_library(compound_name);
```

---

### 9. BackgroundJob

Track long-running tasks (MCR-ALS, NIST downloads, blending).

```sql
CREATE TABLE background_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    job_type VARCHAR(50) NOT NULL,        -- mcr_als, nist_download, blend, preprocess
    status VARCHAR(50) DEFAULT 'pending', -- pending, running, completed, failed, cancelled
    progress INTEGER DEFAULT 0,           -- 0-100
    progress_message TEXT,                -- Current step description
    result_path VARCHAR(500),             -- Path to output file/directory
    error_message TEXT,
    compute_location VARCHAR(20) DEFAULT 'local',  -- local, nist_api, deepseek_api
    compute_node VARCHAR(100),            -- Hostname or API endpoint
    last_heartbeat TIMESTAMP,             -- Updated every 30s during execution (for stale job detection)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);

CREATE INDEX idx_job_user ON background_job(user_id);
CREATE INDEX idx_job_status ON background_job(status);
CREATE INDEX idx_job_created ON background_job(created_at DESC);
CREATE INDEX idx_job_compute_location ON background_job(compute_location);
CREATE INDEX idx_job_heartbeat ON background_job(last_heartbeat);
```

**Job Types:**
- `mcr_als`: MCR-ALS decomposition (Phase 2)
- `nist_download`: Download spectrum from NIST
- `blend`: Multi-species blending (if long-running)
- `preprocess`: Batch preprocessing
- `calibration_fit`: Fit calibration model

**Compute Location Values:**
- `local`: Scientific computation on local machine (default)
- `nist_api`: NIST database download
- `deepseek_api`: LLM query (auxiliary service)

**Performance Note:** WAL mode prevents UI freezes from frequent job progress updates (1/sec write rate). Multiple readers can access UI data concurrently while jobs update.

---

### 10. APIKey

Encrypted storage for external API keys (DeepSeek, etc.).

```sql
CREATE TABLE api_key (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_name VARCHAR(100) NOT NULL,  -- deepseek, openai, etc.
    key_encrypted TEXT NOT NULL,         -- AES-256 encrypted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,

    UNIQUE(user_id, service_name)
);

CREATE INDEX idx_apikey_user ON api_key(user_id);
```

**Encryption Details:**
- **Algorithm:** AES-256-CBC
- **Key Derivation:** PBKDF2 from user password (100,000 iterations)
- **Salt:** Stored alongside encrypted key
- **Format:** `{salt}:{iv}:{ciphertext}` (all base64-encoded)

---

## 🔗 Relationships

### Entity Relationship Diagram

```
User (1) ─────────── (N) Experiment
                          │
                          ├── (N) ExperimentFile
                          └── (N) ExpVersion ──┐
                                    │          │
                                    └──────────┘
                                  (parent_version_id)

User (1) ─────────── (N) Calibration
                          │
                          ├── (N) CalibrationFile
                          └── (N) CalModel

User (1) ─────────── (N) BackgroundJob

User (1) ─────────── (N) APIKey

(No FK) ─────────── NISTLibrary (shared across users)
```

---

## 🔄 Version Branching Example

**Git-like workflow:**

```
Experiment: "Methanol Study"
│
├── v1_initial (parent: NULL)
│   └── files: raw/sample_01.csv, raw/sample_02.csv
│
├── v2_cosmic_ray_removed (parent: v1)
│   └── files: preprocessed/sample_01_cleaned.csv
│
├── v3_smoothed (parent: v2)
│   └── files: preprocessed/sample_01_smoothed.csv
│
└── v2b_alternative_method (parent: v1) ← Branch!
    └── files: preprocessed/sample_01_alt.csv
```

**SQL Representation:**

```sql
| id | version_name           | parent_version_id |
|----|------------------------|-------------------|
| 1  | v1_initial             | NULL              |
| 2  | v2_cosmic_ray_removed  | 1                 |
| 3  | v3_smoothed            | 2                 |
| 4  | v2b_alternative_method | 1                 | ← Branch
```

---

## 🚀 Migration to PostgreSQL (Future)

SQLite-compatible design for easy migration:

1. **Auto-increment → SERIAL:** `AUTOINCREMENT` → `SERIAL` in PostgreSQL
2. **TIMESTAMP:** Compatible in both (use UTC)
3. **Boolean:** SQLite uses `INTEGER 0/1`, PostgreSQL has native `BOOLEAN`
4. **JSON:** Future use of PostgreSQL `JSONB` for metadata (instead of file-based)

**Migration Script (when ready):**
```bash
# Export from SQLite
sqlite3 data/spectra_platform.db .dump > dump.sql

# Convert to PostgreSQL syntax
sed -i 's/AUTOINCREMENT/SERIAL/g' dump.sql

# Import to PostgreSQL
psql -U postgres -d spectra_platform < dump.sql
```

---

## 📝 Sample Queries

### Get all experiments with latest version

```sql
SELECT
    e.id,
    e.name,
    e.created_at,
    v.version_name,
    v.created_at AS version_created_at
FROM experiment e
LEFT JOIN exp_version v ON e.id = v.experiment_id
WHERE v.id = (
    SELECT MAX(id)
    FROM exp_version
    WHERE experiment_id = e.id
)
ORDER BY e.created_at DESC;
```

### Get active calibration model for compound

```sql
SELECT
    c.compound_name,
    m.model_type,
    m.model_path,
    m.r_squared
FROM calibration c
JOIN cal_model m ON c.id = m.calibration_id
WHERE c.compound_name = 'CF4'
  AND m.is_active = 1;
```

### Get running jobs

```sql
SELECT
    id,
    job_type,
    progress,
    started_at,
    (strftime('%s', 'now') - strftime('%s', started_at)) AS seconds_elapsed
FROM background_job
WHERE status = 'running'
ORDER BY started_at ASC;
```

### Version history tree

```sql
WITH RECURSIVE version_tree AS (
    SELECT id, version_name, parent_version_id, 0 AS depth
    FROM exp_version
    WHERE experiment_id = 1 AND parent_version_id IS NULL

    UNION ALL

    SELECT v.id, v.version_name, v.parent_version_id, t.depth + 1
    FROM exp_version v
    JOIN version_tree t ON v.parent_version_id = t.id
)
SELECT
    PRINTF('%*s%s', depth * 2, '', version_name) AS tree
FROM version_tree
ORDER BY id;
```

**Output:**
```
v1_initial
  v2_cosmic_ray_removed
    v3_smoothed
  v2b_alternative_method
```

---

## 🛠️ Database Initialization

**Location:** `app/core/database.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event

# Single database with WAL mode for concurrent access
DB_URL = "sqlite+aiosqlite:///data/spectra_platform.db"
engine = create_async_engine(DB_URL, echo=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Enable WAL mode for concurrent readers + 1 writer
@event.listens_for(engine.sync_engine, "connect")
def set_wal_mode(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")          # Write-Ahead Logging
    cursor.execute("PRAGMA synchronous=NORMAL")        # Faster writes (safe with WAL)
    cursor.execute("PRAGMA busy_timeout=5000")         # Wait 5s on lock contention
    cursor.execute("PRAGMA cache_size=-64000")         # 64MB cache
    cursor.execute("PRAGMA wal_autocheckpoint=1000")   # Checkpoint after 1000 pages (~4 MB)
    cursor.close()

async def get_db():
    """Database dependency for all API endpoints"""
    async with SessionLocal() as session:
        yield session
```

**Usage in API:**
```python
from spectra_sherpa.app.core.database import get_db

@router.get("/experiments")
async def list_experiments(db: AsyncSession = Depends(get_db)):
    return await db.execute(select(Experiment))

@router.post("/jobs/{id}/progress")
async def update_job_progress(
    id: int,
    progress: int,
    db: AsyncSession = Depends(get_db)
):
    # WAL mode prevents blocking UI reads during job updates
    await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == id)
        .values(progress=progress)
    )
```

**Schema Creation:** Automatic at startup via `Base.metadata.create_all`.

**Migration Tool (production only):** Alembic — for incremental schema changes
on existing databases with live data.

```bash
# Create a new migration after changing models
poetry run alembic revision --autogenerate -m "Describe the change"

# Apply to an existing production database
poetry run alembic upgrade heads
```

---

**Document Version:** 1.2
**Last Updated:** 2026-01-02
