# Analysis Canvas Wireframe

**Date:** 2026-01-04
**Version:** 1.0
**Component:** Analysis Section (DAG Workflow Editor)

---

## Overview

The Analysis section provides a **KNIME-style visual programming interface** for building spectral analysis workflows using drag-and-drop nodes. Users can create, execute, and export reproducible analysis pipelines without writing code.

---

## Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Analysis Workflow                [New] [Save] [Export Python ↓]         │
│  Build visual workflows for spectral analysis using drag-and-drop nodes  │
├──────────────┬──────────────────────────────────────────┬────────────────┤
│              │                                          │                │
│  NODE        │         WORKFLOW CANVAS                  │  INSPECTOR     │
│  LIBRARY     │                                          │                │
│              │  ┌──────┐                                │  ┌──────────┐  │
│ 🔍 Search    │  │Input │                                │  │ Selected │  │
│              │  │ Data │──┐                             │  │   Node   │  │
│ Preprocessing│  └──────┘  │                             │  ├──────────┤  │
│  ○ Baseline  │             │    ┌──────────┐            │  │Parameters│  │
│  ○ Smooth    │             └───→│Baseline  │            │  │ λ: 10000│  │
│  ○ Normalize │                  │  (ALS)   │──┐         │  │ p: 0.001│  │
│  ○ Derivative│                  └──────────┘  │         │  │          │  │
│              │                                 │         │  │ [Execute]│  │
│ Modeling     │                    ┌──────────┐│         │  └──────────┘  │
│  ○ PCA       │                    │   PCA    ││         │                │
│  ○ PLS       │              ┌────→│  Model   │├──┐      │  RESULTS       │
│  ○ MCR-ALS   │              │     └──────────┘│  │      │                │
│              │              │                  │  │      │ 📊 Plot        │
│ Diagnostics  │   ┌────────┐ │                  │  │      │ 📈 Metrics     │
│  ○ Outliers  │   │Smooth  │ │     ┌────────┐  │  │      │ 📋 Data        │
│  ○ Metrics   │   │  (SG)  │─┴────→│Outlier │  │  │      │                │
│  ○ Residuals │   └────────┘       │Detect  │  │  │      │ [Spectra plot] │
│              │                     └────────┘  │  │      │                │
│ Export       │                                 │  │      │ Mean: 0.542   │
│  ○ CSV       │                      ┌────────┐ │  │      │ StDev: 0.082  │
│  ○ Plot      │                      │Export  │ │  │      │                │
│  ○ Model     │                      │  CSV   │←┴──┘      │ [Clear ×]     │
│              │                      └────────┘           │                │
│              │  [Zoom] [Fit] [MiniMap]                   │                │
└──────────────┴──────────────────────────────────────────┴────────────────┘
     250px                   ~60%                              350px
```

---

## Component Breakdown

### 1. Header Actions (Top Bar)

```
┌─────────────────────────────────────────────────────────────┐
│  Analysis Workflow            [+ New] [💾 Save] [⬇ Export] │
│  Build visual workflows...                                  │
└─────────────────────────────────────────────────────────────┘
```

**Buttons:**
- **New Workflow** - Clear canvas, start fresh
- **Save** - Save current workflow to database
- **Export Python** - Download executable Python script

---

### 2. Node Library (Left Panel, 250px)

**Purpose:** Draggable palette of available operations

```
┌───────────────────────┐
│ Node Library          │
│ ┌─────────────────┐   │
│ │ 🔍 Search nodes │   │
│ └─────────────────┘   │
│                       │
│ 🔧 Preprocessing      │
│  ─────────────────    │
│  ○ Baseline (ALS)     │
│  ○ Baseline (Rubber)  │
│  ○ Smooth (SG)        │
│  ○ Normalize (SNV)    │
│  ○ Normalize (MSC)    │
│  ○ 1st Derivative     │
│  ○ 2nd Derivative     │
│                       │
│ 📊 Modeling           │
│  ─────────────────    │
│  ○ PCA                │
│  ○ PLS                │
│  ○ MCR-ALS            │
│  ○ Linear Regression  │
│                       │
│ ✅ Diagnostics        │
│  ─────────────────    │
│  ○ Outlier Detection  │
│  ○ Model Metrics      │
│  ○ Residuals Plot     │
│                       │
│ 💾 Export             │
│  ─────────────────    │
│  ○ Export CSV         │
│  ○ Save Plot          │
│  ○ Save Model         │
└───────────────────────┘
```

**Interaction:**
- Click to add node at default position
- Drag-and-drop onto canvas (future enhancement)
- Search filter narrows visible nodes

---

### 3. Workflow Canvas (Center, ~60%)

**Purpose:** Visual DAG editor with Vue Flow

```
┌──────────────────────────────────────────────────┐
│                                                  │
│   ┌──────────┐          ┌──────────┐            │
│   │  Input   │          │ Baseline │            │
│   │   Data   │─────────→│  (ALS)   │──────┐     │
│   └──────────┘          └──────────┘      │     │
│                                            ↓     │
│                                      ┌──────────┐│
│   ┌──────────┐          ┌──────────┐│   PCA    ││
│   │  Smooth  │─────────→│ Outlier  ││  Model   ││
│   │   (SG)   │          │  Detect  │└──────────┘│
│   └──────────┘          └──────────┘      │     │
│                                            ↓     │
│                                      ┌──────────┐│
│                                      │  Export  ││
│                                      │   CSV    ││
│                                      └──────────┘│
│                                                  │
│  [Zoom -] [Zoom +] [Fit View] [MiniMap]         │
└──────────────────────────────────────────────────┘
```

**Node Appearance:**
```
┌────────────────────┐
│ 🔧 Baseline (ALS) │  ← Header (color-coded by category)
├────────────────────┤
│  ⏳ Status icon   │  ← Body (shows execution status)
└────────────────────┘
  ●                ●   ← Input/output handles (left/right)
```

**Node Color Coding:**
- **Preprocessing** - Blue (#eff6ff)
- **Modeling** - Green (#f0fdf4)
- **Diagnostics** - Yellow (#fef3c7)
- **Export** - Purple (#f3e8ff)

**Status Icons:**
- 🕐 Pending (gray)
- ⏳ Running (blue, spinning)
- ✅ Completed (green)
- ❌ Error (red)

**Interactions:**
- **Click** - Select node (highlights in Inspector)
- **Double-click** - Execute node
- **Drag** - Reposition node
- **Connect** - Drag from output handle to input handle

**Controls:**
- **Zoom** - Mouse wheel or buttons
- **Pan** - Click-drag on background
- **Fit View** - Auto-zoom to fit all nodes
- **MiniMap** - Bird's-eye view navigator (bottom-right overlay)

---

### 4. Node Inspector (Top-Right, 350px, ~50% height)

**Purpose:** Edit parameters of selected node

```
┌───────────────────────────┐
│ Node Inspector            │
├───────────────────────────┤
│ Baseline (ALS)            │
│ Asymmetric Least Squares  │
│                           │
│ Parameters                │
│ ─────────────────────     │
│ Lambda                    │
│ [10000    ] (1-1M)       │
│ Smoothness parameter      │
│                           │
│ Asymmetry (p)             │
│ [0.001    ] (0.001-0.1)  │
│ Lower = more asymmetric   │
│                           │
│ ┌─────────────────────┐   │
│ │   ▶ Execute Node    │   │
│ └─────────────────────┘   │
└───────────────────────────┘
```

**Empty State:**
```
┌───────────────────────────┐
│ Node Inspector            │
├───────────────────────────┤
│                           │
│       ℹ️                  │
│                           │
│  Select a node to view    │
│  and edit its parameters  │
│                           │
└───────────────────────────┘
```

**Parameter Types:**
- **Number** - Slider or input with min/max/step
- **Boolean** - Toggle switch
- **Select** - Dropdown menu
- **Text** - Text input

---

### 5. Results Panel (Bottom-Right, 350px, ~50% height)

**Purpose:** Display live analysis results

```
┌───────────────────────────┐
│ Results            [×]    │
├───────────────────────────┤
│ [Plot] [Metrics] [Data]   │  ← Tabs
├───────────────────────────┤
│                           │
│   📊 Spectrum Plot        │
│                           │
│   [Interactive Plotly]    │
│   ┌─────────────────────┐ │
│   │                     │ │
│   │  ─────────╱─╲─────  │ │
│   │ ╱            ╲╱     │ │
│   │                     │ │
│   └─────────────────────┘ │
│                           │
└───────────────────────────┘
```

**Tabs:**

1. **Plot Tab** - Plotly interactive chart
   - Zoom, pan, hover tooltips
   - Multiple traces for comparison
   - Export plot as PNG/SVG

2. **Metrics Tab** - Key statistics
   ```
   Samples       │ 150
   Wavelengths   │ 1024
   Mean Intensity│ 0.5421
   Std Dev       │ 0.0823
   R²            │ 0.9876
   RMSE          │ 0.0145
   ```

3. **Data Tab** - Table preview
   ```
   ┌──────────┬──────────┬────────┐
   │ Sample   │ Wavenum  │ Absorp │
   ├──────────┼──────────┼────────┤
   │ S001     │ 400.0    │ 0.123  │
   │ S001     │ 400.5    │ 0.124  │
   │ ...      │ ...      │ ...    │
   └──────────┴──────────┴────────┘
   ```

**Empty State:**
```
┌───────────────────────────┐
│ Results                   │
├───────────────────────────┤
│                           │
│       📊                  │
│                           │
│  Execute nodes to see     │
│  results here             │
│                           │
└───────────────────────────┘
```

---

## User Workflow Example

### Scenario: Baseline Correction + PCA

1. **Add Input Data Node**
   - Click "Input Data" in Node Library
   - Node appears on canvas

2. **Add Baseline Correction**
   - Click "Baseline (ALS)" in Node Library
   - Node appears on canvas
   - Connect Input → Baseline

3. **Configure Parameters**
   - Click Baseline node
   - Inspector shows Lambda and p parameters
   - Adjust Lambda slider to 10000
   - Click "Execute Node"

4. **View Results**
   - Results panel shows corrected spectrum
   - Metrics tab shows mean intensity

5. **Add PCA**
   - Click "PCA" in Node Library
   - Connect Baseline → PCA
   - Set n_components = 5
   - Execute

6. **Export**
   - Click "Export Python" button
   - Download workflow_20260104.py
   - Script recreates entire pipeline

---

## Technical Implementation

### Data Flow (DAG Execution)

```
User clicks "Execute Node"
       ↓
Traverse DAG backwards to find input dependencies
       ↓
Execute nodes in topological order
       ↓
Each node:
  - Reads NDDataset from previous node
  - Applies transformation
  - Stores result in cache (Map<nodeId, NDDataset>)
       ↓
Update Results Panel with final output
```

### State Management (Pinia Store)

```typescript
interface AnalysisState {
  workflows: Workflow[]
  activeWorkflow: Workflow | null
  nodes: Node[]
  edges: Edge[]
  executionResults: Map<nodeId, NDDataset>
  selectedNode: Node | null
}
```

### Backend API Endpoints

```
POST /api/v1/workflows          - Create new workflow
GET  /api/v1/workflows          - List workflows
GET  /api/v1/workflows/{id}     - Get workflow
PUT  /api/v1/workflows/{id}     - Update workflow
DELETE /api/v1/workflows/{id}   - Delete workflow

POST /api/v1/workflows/{id}/execute/{nodeId}  - Execute single node
POST /api/v1/workflows/{id}/execute/all       - Execute entire workflow
GET  /api/v1/workflows/{id}/export/python     - Export to .py script
GET  /api/v1/workflows/{id}/export/jupyter    - Export to .ipynb notebook
```

---

## Future Enhancements (Phase 2)

1. **Subworkflows** - Group nodes into reusable subgraphs
2. **Branching** - A/B test different preprocessing methods
3. **Loop Nodes** - Iterate over parameter grid
4. **Conditional Nodes** - If/else logic
5. **LLM Integration** - "Add baseline correction" → LLM suggests node + parameters
6. **Side-by-side Comparison** - Compare two workflows
7. **Undo/Redo** - History stack for canvas edits
8. **Templates** - Pre-built workflows (e.g., "FTIR Preprocessing Pipeline")
9. **Collaboration** - Share workflows via URL

---

## Accessibility & UX

- **Keyboard Navigation** - Arrow keys to select nodes, Tab to cycle
- **Tooltips** - Hover on node for description
- **Validation** - Prevent invalid connections (type mismatch)
- **Auto-layout** - Organize nodes in clean rows/columns
- **Save Prompts** - Warn before discarding unsaved changes
- **Error Handling** - Show node-level error messages

---

## Design Inspiration

- **KNIME** - Node-based workflow editor
- **Orange Data Mining** - Visual programming for data science
- **Node-RED** - Flow-based programming for IoT
- **Unreal Engine Blueprints** - Visual scripting

---

**Version History:**
- v1.0 (2026-01-04) - Initial wireframe
