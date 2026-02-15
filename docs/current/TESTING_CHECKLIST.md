# Prototype Release - Testing Checklist

**Release Date**: 2026-01-15
**Status**: Pre-Release Hardening Complete

## ✅ Code Quality Checks (PASSED)

### Syntax Validation
- ✅ `data.py` - Python syntax valid
- ✅ `classification.py` - Python syntax valid
- ✅ `models/__init__.py` - Python syntax valid

### Critical Path Analysis
- ✅ 48 nodes registered across 9 node files
- ✅ All Phase 1 models exported in `__init__.py`
- ✅ 4 Alembic migrations created for Phase 1 features
- ✅ No duplicate code (removed 78 lines)
- ✅ No leftover backup files

---

## 🔍 Known Issues Fixed

| Issue | Severity | Status | File | Line |
|-------|----------|--------|------|------|
| FileLoadNode missing stage directory | CRITICAL | ✅ FIXED | data.py | 706 |
| Stage parameter not validated | HIGH | ✅ FIXED | data.py | 692 |
| NIST path construction inconsistency | MEDIUM | ✅ FIXED | data.py | 827 |
| Duplicate `_extract_dataset_from_result` | MEDIUM | ✅ FIXED | data.py | 39-85 |
| 10 nodes missing from NODE_TYPE_MAP | HIGH | ✅ FIXED | workflow.ts | 83-130 |
| Dead code (data_FIXED.py) | HIGH | ✅ FIXED | - | - |

---

## 🧪 Manual Testing Required

### Backend Startup (User Action Required)
```bash
cd src/spectra_sherpa
source venv/bin/activate  # or conda activate <env>
uvicorn app.main:app --reload
```

**Expected**: Server starts on http://localhost:8000
**Check**:
- [ ] No import errors
- [ ] No SQLAlchemy relationship warnings
- [ ] Database connection successful
- [ ] All models registered

### Database Schema Validation
```bash
cd src/spectra_sherpa
alembic current
alembic history
```

**Expected Output**:
- Current revision: `d0f6e1b4cf70` (add_workflow_annotations)
- 4 Phase 1 migrations visible in history

**Check Tables Created**:
```sql
SELECT name FROM sqlite_master WHERE type='table'
ORDER BY name;
```

Expected Phase 1 tables:
- [ ] workflow_folder
- [ ] workflow_tag
- [ ] workflow_tag_association
- [ ] workflow_template
- [ ] workflow_version

### API Endpoint Testing

#### 1. Node Library Endpoint
```bash
curl http://localhost:8000/api/v1/workflows/nodes/library
```

**Expected**: JSON with 48 nodes across categories:
- preprocessing (19 nodes)
- modeling (6 nodes)
- classification (3 nodes)
- diagnostics (2 nodes)
- data (4 nodes)
- output (5 nodes)
- time_series (2 nodes)

**Check**:
- [ ] All 10 newly added nodes present
- [ ] Node types match backend registration
- [ ] Icons/labels are user-friendly

#### 2. Workflow CRUD Operations
```bash
# Create workflow
curl -X POST http://localhost:8000/api/v1/workflows/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Workflow","description":"Testing"}'

# List workflows
curl http://localhost:8000/api/v1/workflows/

# Get by ID
curl http://localhost:8000/api/v1/workflows/1
```

**Check**:
- [ ] Create returns workflow with ID
- [ ] List includes created workflow
- [ ] Get by ID returns full details
- [ ] Timestamps are present

#### 3. Version History
```bash
# Update workflow to create version
curl -X PUT http://localhost:8000/api/v1/workflows/1 \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Workflow","nodes":[],"edges":[]}'

# Get versions
curl http://localhost:8000/api/v1/workflows/1/versions
```

**Check**:
- [ ] Version created automatically
- [ ] Snapshot contains full state
- [ ] Version number increments
- [ ] created_at timestamp present

#### 4. Tags & Folders
```bash
# Create folder
curl -X POST http://localhost:8000/api/v1/workflows/folders \
  -H "Content-Type: application/json" \
  -d '{"name":"My Folder"}'

# Create tag
curl -X POST http://localhost:8000/api/v1/workflows/tags \
  -H "Content-Type: application/json" \
  -d '{"name":"classification","color":"#3B82F6"}'

# Assign folder
curl -X PATCH http://localhost:8000/api/v1/workflows/1 \
  -H "Content-Type: application/json" \
  -d '{"folder_id":1}'

# Assign tags
curl -X PUT http://localhost:8000/api/v1/workflows/1/tags \
  -H "Content-Type: application/json" \
  -d '{"tag_ids":[1]}'
```

**Check**:
- [ ] Folder created with ID
- [ ] Tag created with color
- [ ] Workflow moved to folder
- [ ] Tag assigned to workflow

#### 5. Templates
```bash
# Get templates
curl http://localhost:8000/api/v1/workflows/templates

# Create from template
curl -X POST http://localhost:8000/api/v1/workflows/from-template/pca_basic \
  -H "Content-Type: application/json" \
  -d '{"name":"From Template"}'
```

**Check**:
- [ ] 10 templates returned
- [ ] Templates have workflow_json
- [ ] Create from template works
- [ ] New workflow has nodes/edges from template

---

## 🎨 Frontend Testing

### Node Library Loading
1. Open frontend in browser
2. Navigate to workflow builder
3. Check Node Library panel

**Expected**:
- [ ] "Loading nodes..." appears briefly
- [ ] Nodes grouped by category
- [ ] All categories visible: Preprocessing, Modeling, Classification, Diagnostics, Data, Output
- [ ] Search bar filters nodes
- [ ] Icons display correctly

### Node Addition
1. Click a node in library
2. Verify it appears on canvas

**Test Nodes**:
- [ ] PLS-DA (classification)
- [ ] Outlier Detection (diagnostics)
- [ ] Data Table (output)
- [ ] Pareto Scaling (preprocessing)
- [ ] Moving Window (time_series)

### Data Node Configuration
1. Add "Data Source" node
2. Open node inspector

**Expected Parameters**:
- [ ] source (dropdown: spectrochempy/experiment/library/file/synthetic)
- [ ] experiment_id (number)
- [ ] file_id (number)
- [ ] stage (dropdown: raw/preprocessed/synthetic)
- [ ] library_id (number)

**Test Cases**:
- [ ] Selecting experiment shows experiment_id
- [ ] Selecting library shows library_id
- [ ] Stage parameter has 3 options

---

## 🔐 Data Integrity Checks

### Path Construction Validation

All file loading paths should follow these patterns:

#### Experiment Files
```python
# Pattern
settings.data_dir / "experiments" / "exp_001" / stage / file_path

# Examples
.../experiments/exp_001/raw/sample.csv
.../experiments/exp_001/preprocessed/sample_baseline.csv
.../experiments/exp_001/synthetic/synthetic_001.csv
```

**Check**:
- [ ] DataSourceNode._load_from_experiment uses pattern (line 443)
- [ ] FileLoadNode.execute uses pattern (line 706)
- [ ] Stage directory is included

#### NIST Library Files
```python
# Pattern
settings.data_dir / "nist_library" / file_path

# Examples
.../nist_library/methanol_1000.jdx
.../nist_library/ethanol_4000.jdx
```

**Check**:
- [ ] DataSourceNode._load_from_library uses pattern (line 534)
- [ ] NISTLibraryNode.execute uses pattern (line 827)
- [ ] Both nodes consistent

### Database Relationship Integrity

Run SQL to verify cascading deletes:

```sql
-- Test workflow deletion cascades to nodes/edges
DELETE FROM workflow WHERE id = 1;

-- Check orphaned records
SELECT COUNT(*) FROM workflow_node WHERE workflow_id = 1;  -- Should be 0
SELECT COUNT(*) FROM workflow_edge WHERE workflow_id = 1;  -- Should be 0
SELECT COUNT(*) FROM workflow_version WHERE workflow_id = 1;  -- Should be 0
```

**Check**:
- [ ] Nodes deleted when workflow deleted
- [ ] Edges deleted when workflow deleted
- [ ] Versions deleted when workflow deleted
- [ ] No orphaned records

---

## ⚠️ Known Limitations (Not Bugs)

These are features NOT YET IMPLEMENTED - not issues with current code:

1. **Multi-input port validation** - Frontend may need adjustment for diagnostics nodes
2. **Template coverage** - Only 10 templates exist (not all node types covered)
3. **PARAM_NAME_MAP completeness** - May not cover all 48 nodes
4. **Workflow execution** - Trial execution not tested
5. **Authentication** - User system not implemented
6. **File upload** - Experiment file upload not implemented
7. **NIST database** - No NIST entries populated
8. **Error boundaries** - Frontend may not handle all error states

---

## 📋 Pre-Deployment Checklist

Before deploying to production/staging:

- [ ] All API tests passed
- [ ] Frontend connects to backend
- [ ] Database migrations run cleanly
- [ ] No console errors in browser
- [ ] No Python exceptions on startup
- [ ] Node library loads completely
- [ ] Version history creates snapshots
- [ ] Tags and folders functional
- [ ] Templates create workflows

---

## 🚀 Deployment Notes

### Environment Variables Required
```bash
DATABASE_URL=sqlite+aiosqlite:///./app.db
DATA_DIR=/path/to/data
CORS_ORIGINS=http://localhost:5173
```

### First-Time Setup
```bash
# 1. Install dependencies
cd backend && pip install -r requirements.txt

# 2. Start server (database is created automatically on first run)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Health Check Endpoint
```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

---

## 📝 Test Results Log

| Test | Date | Tester | Result | Notes |
|------|------|--------|--------|-------|
| Backend startup | | | ⏳ Pending | |
| Database schema | | | ⏳ Pending | |
| Node library API | | | ⏳ Pending | |
| Workflow CRUD | | | ⏳ Pending | |
| Version history | | | ⏳ Pending | |
| Tags & folders | | | ⏳ Pending | |
| Frontend loading | | | ⏳ Pending | |
| Node addition | | | ⏳ Pending | |
| Data paths | | | ⏳ Pending | |

---

## 🎯 Success Criteria

Prototype is ready for user testing when:

1. ✅ All critical bugs fixed
2. ✅ Syntax validation passed
3. ⏳ Backend starts without errors
4. ⏳ API endpoints return valid JSON
5. ⏳ Frontend displays all 48 nodes
6. ⏳ Workflow CRUD operations work
7. ⏳ Version history creates snapshots
8. ⏳ File paths construct correctly

---

**Last Updated**: 2026-01-15
**Reviewed By**: Claude Code (Senior Engineer Mode)
