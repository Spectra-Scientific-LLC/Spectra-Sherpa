# DAG Analysis Workflow System - Quickstart Guide

## 🚀 Getting Started

This guide walks you through using the new DAG-based Analysis workflow system for spectral data analysis.

---

## 📋 Prerequisites

- Python 3.11+ with `poetry` installed
- Node.js 18+ with `npm` installed
- SpectroChemPy environment (`scpy` conda env)

---

## 🔧 Backend Setup

### 1. Install Dependencies

```bash
cd src/spectra_sherpa
/Users/fe2val/miniforge3/envs/scpy/bin/poetry install
```

### 2. Start Backend Server

> **Note:** The database is created automatically on first startup.
> No manual migration step is needed.

```bash
/Users/fe2val/miniforge3/envs/scpy/bin/poetry run uvicorn app.main:app --reload --port 8000
```

**Verify**: Visit http://localhost:8000/docs to see the API documentation

---

## 🎨 Frontend Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

**Verify**: Visit http://localhost:5173 and navigate to the Analysis tab

---

## 🎯 Using the Analysis Workflow System

### Navigation

1. Click on **Analysis** in the left sidebar (icon: `pi pi-sitemap`)
2. You'll see a 3-panel layout:
   - **Left**: Node Library (palette of available nodes)
   - **Center**: Workflow Canvas (drag-and-drop area)
   - **Right**: Node Inspector + Results Panel

---

## 📝 Creating Your First Workflow

### Example: Smooth → PCA Pipeline

#### Step 1: Add Nodes to Canvas

1. **Add a Smoothing Node**:
   - In the Node Library, expand "Preprocessing"
   - Drag "Smooth (Savitzky-Golay)" to the canvas
   - Node ID: `smooth_001`

2. **Add a PCA Node**:
   - In Node Library, expand "Modeling"
   - Drag "PCA" to the canvas
   - Node ID: `pca_001`

#### Step 2: Connect Nodes

1. Click on the output port of `smooth_001`
2. Drag to the input port of `pca_001`
3. Release to create the connection

#### Step 3: Configure Parameters

1. **Click on `smooth_001`** (node becomes selected)
2. In the **Node Inspector** (right panel):
   - Window Size: `11`
   - Polynomial Order: `2`

3. **Click on `pca_001`**:
   - Number of Components: `3`
   - Standardize Data: `false`
   - Scale Data: `false`

#### Step 4: Save Workflow

1. Click **Save** button (top of canvas)
2. Name: `"FTIR Smoothing + PCA"`
3. Description: `"Denoise FTIR spectra and extract principal components"`
4. Click **Create**

---

## 🔬 Executing Workflows

### Option A: Via UI (Coming Soon - Backend Ready)

The frontend execution UI is ready to be connected. The backend `/workflows/{id}/execute` endpoint is fully functional.

### Option B: Via API (Available Now)

```bash
# 1. Create a test workflow
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test PCA Workflow",
    "description": "Simple PCA analysis",
    "status": "active",
    "nodes": [
      {
        "node_id": "data_source",
        "node_type": "smooth.savitzky_golay",
        "parameters": {},
        "position_x": 100,
        "position_y": 100
      },
      {
        "node_id": "smooth_001",
        "node_type": "smooth.savitzky_golay",
        "parameters": {"size": 11, "order": 2},
        "position_x": 300,
        "position_y": 100
      },
      {
        "node_id": "pca_001",
        "node_type": "model.pca",
        "parameters": {"n_components": 3, "standardized": false, "scaled": false},
        "position_x": 500,
        "position_y": 100
      }
    ],
    "edges": [
      {
        "from_node_id": "data_source",
        "to_node_id": "smooth_001"
      },
      {
        "from_node_id": "smooth_001",
        "to_node_id": "pca_001"
      }
    ]
  }'

# 2. Execute workflow (you'll need to provide actual AnalysisDataset data)
# See test_workflow_executor.py for a working example
```

### Option C: Via Python Test Script (Immediate)

```bash
cd src/spectra_sherpa
/Users/fe2val/miniforge3/envs/scpy/bin/python test_workflow_executor.py
```

**Expected Output**:
```
============================================================
DAG Workflow Executor Test
============================================================

1. Creating synthetic FTIR dataset...
   Created dataset: 50 samples × 400 features

2. Building workflow...
   Added nodes:
     • data_source: Raw spectral data
     • smooth_001: Savitzky-Golay Smoothing
     • pca_001: PCA (3 components)
   Added edges:
     • data_source → smooth_001 → pca_001

3. Executing workflow...
Executing node: smooth_001 (Smooth (Savitzky-Golay))
  ✓ Completed: smooth_001 (status: completed)
Executing node: pca_001 (PCA)
  ✓ Completed: pca_001 (status: completed)

4. Workflow Results:
   Workflow status: completed
   ...
```

---

## 📦 Available Nodes

### Preprocessing (7 Nodes)

| Node Type | Label | Purpose |
|-----------|-------|---------|
| `baseline.als` | Baseline (ALS) | Asymmetric Least Squares baseline correction |
| `baseline.rubberband` | Baseline (Rubberband) | Convex hull baseline correction |
| `smooth.savitzky_golay` | Smooth (Savitzky-Golay) | Polynomial smoothing filter |
| `normalize.snv` | Normalize (SNV) | Standard Normal Variate normalization |
| `normalize.msc` | Normalize (MSC) | Multiplicative Scatter Correction |
| `derivative.first` | 1st Derivative | First derivative using SG filter |
| `derivative.second` | 2nd Derivative | Second derivative using SG filter |

### Modeling (3 Nodes)

| Node Type | Label | Purpose |
|-----------|-------|---------|
| `model.pca` | PCA | Principal Component Analysis |
| `model.pls` | PLS | Partial Least Squares Regression |
| `model.linear_regression` | Linear Regression | Simple linear regression |

---

## 🐍 Exporting to Python

### Via API

```bash
# Export workflow ID 1 to Python code
curl http://localhost:8000/api/v1/workflows/1/export/python
```

**Response**:
```json
{
  "workflow_id": 1,
  "workflow_name": "FTIR Smoothing + PCA",
  "python_code": "...",
  "filename": "ftir_smoothing_+_pca_workflow.py"
}
```

### Generated Python Script Structure

```python
"""
Generated workflow: FTIR Smoothing + PCA

Denoise FTIR spectra and extract principal components
"""

import asyncio
import numpy as np
import spectrochempy as scp
from spectrochempy import NDDataset


async def run_workflow():
    """Execute the workflow."""
    results = {}

    # Node: smooth_001 (smooth.savitzky_golay)
    data = results['data_source'].copy()
    data.smooth(size=11, order=2)
    results['smooth_001'] = data

    # Node: pca_001 (model.pca)
    # Perform PCA
    pca = scp.PCA(n_components=3, standardized=False, scaled=False)
    pca.fit(results['smooth_001'])

    # Store PCA results
    pca_result = {
        'model': pca,
        'scores': pca.transform(),
        'loadings': pca.components,
        'explained_variance': pca.explained_variance,
        'explained_variance_ratio': pca.explained_variance_ratio,
        'n_components': 3,
    }
    results['pca_001'] = pca_result

    return results


if __name__ == "__main__":
    results = asyncio.run(run_workflow())
    print("\n\nWorkflow completed successfully!")
```

---

## 🔍 Viewing Node Library

### Via API

```bash
curl http://localhost:8000/api/v1/workflows/nodes/library
```

**Response** (excerpt):
```json
{
  "nodes": [
    {
      "node_type": "model.pca",
      "category": "modeling",
      "label": "PCA",
      "description": "Principal Component Analysis for dimensionality reduction",
      "parameters": [
        {
          "name": "n_components",
          "label": "Number of Components",
          "param_type": "number",
          "default": 5,
          "min_value": 1,
          "max_value": 50,
          "step": 1,
          "required": true
        },
        ...
      ],
      "input_types": ["NDDataset"],
      "output_type": "PCAModel"
    },
    ...
  ],
  "total": 10
}
```

---

## 📚 Example Workflows

### 1. Basic Preprocessing

**Nodes**: Raw Data → Baseline (ALS) → Smooth (SG) → Normalize (SNV)

**Use Case**: Clean noisy FTIR spectra

### 2. PCA Exploration

**Nodes**: Raw Data → Smooth → PCA

**Use Case**: Visualize variance in spectral dataset

### 3. Calibration Workflow

**Nodes**: Raw Data → Baseline → Normalize → PLS

**Use Case**: Build quantitative calibration model

### 4. Derivative Analysis

**Nodes**: Raw Data → Smooth → 2nd Derivative → PCA

**Use Case**: Enhance spectral features, remove baseline

---

## 🧪 Running Tests

### Test Individual Node

```bash
cd src/spectra_sherpa
/Users/fe2val/miniforge3/envs/scpy/bin/python test_pca_node.py
```

### Test Node Registry

```bash
/Users/fe2val/miniforge3/envs/scpy/bin/python test_node_registry.py
```

### Test Full Workflow

```bash
/Users/fe2val/miniforge3/envs/scpy/bin/python test_workflow_executor.py
```

---

## 🛠️ Troubleshooting

### Backend won't start

```bash
# Check if port 8000 is in use
lsof -i :8000

# Use different port
/Users/fe2val/miniforge3/envs/scpy/bin/poetry run uvicorn app.main:app --reload --port 8001
```

### SpectroChemPy errors

```bash
# Verify SpectroChemPy is installed
/Users/fe2val/miniforge3/envs/scpy/bin/python -c "import spectrochempy as scp; print(scp.__version__)"

# Should output: 0.8.1
```

### Database errors

```bash
# Reset database (CAUTION: Deletes all data)
# Delete the .db file and restart the server — tables are recreated automatically.
rm -f data/spectra_platform.db*
```

---

## 📖 API Documentation

Once the backend is running, visit:

**Swagger UI**: http://localhost:8000/docs

**ReDoc**: http://localhost:8000/redoc

**Key Endpoints**:
- `GET /api/v1/workflows` - List workflows
- `POST /api/v1/workflows` - Create workflow
- `POST /api/v1/workflows/{id}/execute` - Execute workflow
- `GET /api/v1/workflows/{id}/export/python` - Export to Python
- `GET /api/v1/workflows/nodes/library` - Get node library

---

## 🎓 Next Steps

1. **Connect Frontend Execution**: Wire up the Execute button in AnalysisContent.vue to call the API
2. **Add More Nodes**: Create new nodes in `app/services/dag/nodes/`
3. **File Upload**: Add data source nodes that load from uploaded files
4. **Plotting Integration**: Connect ResultsPanel.vue to display Plotly charts from node results
5. **Real-time Updates**: Use WebSockets for live execution status

---

## 📝 Notes

- All workflows use **AnalysisDataset** objects for data flow (NDDataset-compatible; SpectroChemPy optional)
- Nodes are **automatically registered** via `@register_node` decorator
- **Topological sorting** ensures correct execution order
- **Python export** generates standalone, executable scripts
- **Database persistence** allows saving/loading workflows

---

## 🤝 Contributing

To add a new node type:

1. Create node class in `app/services/dag/nodes/`
2. Decorate with `@register_node`
3. Define `metadata` (NodeMetadata)
4. Implement `async execute()` method
5. Add to frontend NodeLibrary.vue palette
6. Test with test script

**Example**:
```python
@register_node
class MyCustomNode(Node):
    metadata = NodeMetadata(
        node_type="custom.my_node",
        category="preprocessing",
        label="My Custom Node",
        description="Does something cool",
        parameters=[...],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: AnalysisDataset) -> Any:
        # Your logic here
        result = input_data.copy()
        # ... process result ...
        return result
```

---

**Happy Analyzing! 🎉**
