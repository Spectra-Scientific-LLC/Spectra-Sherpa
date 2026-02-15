# Codebase Analysis & Strategic Roadmap

## 1. Executive Summary of Current Codebase ("Refactored")

The codebase represents a **web-based visual programming environment (DAG-based)** specifically designed for spectroscopic data analysis.

*   **Architecture**:
    *   **Frontend**: Modern **Vue 3** + **Vite** application using **Vue Flow** for the node-graph interface and **Plotly.js** for scientific visualization.
    *   **Backend**: **FastAPI** (Python 3.10+) application acting as the orchestration engine.
*   **Key Capabilities**:
    *   **Workflow Engine**: Executes Directed Acyclic Graphs (DAGs) of processing steps.
    *   **Specialized Analysis**: Implements advanced chemometric algorithms including **MCR-ALS** (Multivariate Curve Resolution), **SIMCA** (Classification), and **Peak Finding**.
    *   **State of Development**: The system recently underwent a critical refactor (Jan 2026) to standardize node architecture. It now correctly handles **multi-output nodes** (e.g., a single Classification node returning Model, Predictions, and Confusion Matrix separately).
*   **Data Flow**: Data is passed between nodes as standardized dictionaries. Recent fixes ensured strict typing of ports (Spectra, Concentrations, Models).

### Key Data Objects
| Internal Object | Library | Purpose |
| :--- | :--- | :--- |
| **`AnalysisDataset`** | `app/lib/analysis_dataset.py` | **The Core Object**. The canonical DAG runtime container — 2D numpy array with axes, metadata, and provenance. NDDataset-compatible interface (`.data`, `.x`, `.y`, `.shape`, `.copy()`). Processing history stored in `meta["processing_history"]`. SpectroChemPy `NDDataset` used only by SCP-only nodes via adapters. |
| `meta_helpers` | Custom | Provenance helpers: `add_processing_step()`, `copy_processing_history()`, `get_processing_history()` |
| `serialize_for_api()` | Custom | Single API boundary serialization function (called only in routes) |
| `Node` | Custom | The unit of logic. Wraps `fit()`/`transform()` methods into a DAG-compatible step. |

## 2. Competitive Analysis

### vs. SpectroChemPy
*   **What it is**: A Python framework dedicated to spectroscopy, characterized by its `NDDataset` (N-dimensional dataset) which carries coordinates (wavenumbers, time) and units alongside data.
*   **Pros**: Incredible data integrity; you never lose track of your X-axis (wavenumbers).
*   **Cons**: Code-only interface (Jupyter/Script based). High barrier to entry for non-coders.
*   **Gap Analysis**: **RESOLVED**. SpectroChemPy's "Smart Arrays" are its killer feature. Our `AnalysisDataset` provides coordinate-aware slicing, axis tracking, and provenance — filling this gap without requiring SCP as a hard dependency.
*   **Takeaway**: `AnalysisDataset` is our NDDataset-compatible runtime container. SCP nodes convert via adapters when needed.

### vs. Orange Data Mining
*   **What it is**: A general-purpose visual programming tool (GUI) for data analysis.
*   **Pros**: Excellent UI/UX, huge library of generic ML widgets, interactive visualizations.
*   **Cons**: "General purpose" interactions often feel clunky for specific scientific workflows (e.g., viewing hundreds of spectra overlaid is not its default strength).
*   **Gap Analysis**: **User Interface**. Orange sets the bar for "Drag-and-Drop Analysis". Your frontend needs to match its ease of use.
*   **Takeaway**: You have a `NodeInspector.vue`. Improve it to match Orange's interactivity (real-time previews).

### vs. chemtools / chemometrics (Python Packages)
*   **What they are**: Libraries providing algorithms (preprocessing, PLS, PCA) and scikit-learn wrappers.
*   **Pros**: They provide the math.
*   **Cons**: They are just libraries.
*   **Takeaway**: **Don't reinvent the wheel.** Use your internal `libs.project0.preprocess` library (which already has SavGol, etc.) instead of external dependencies.

## 3. Prioritized Feature Roadmap

Based on the analysis, here are the most valuable features to prioritize next, ranked by ROI.

### Priority 1: "Smart" Data Structures (The SpectroChemPy Gap)
**Why**: Currently, nodes like MCR return `C` (Concentration) and `St` (Spectra) as lists. If metadata (Wavenumbers, Sample IDs) is lost or decoupled, the results are scientifically useless.
*   **Feature**: Implement a comprehensive `SpectralDataset` class in the backend that bundles `Data (Y)`, `Wavenumbers (X)`, and `Metadata` together.
*   **Action**: Ensure every node accepts and returns this structure, automatically slicing the X-axis when the data is sliced.

### Priority 2: Preprocessing Node Library
**Why**: Chemometrics is 80% preprocessing. Users cannot build real models without these tools.
*   **Feature**: Add a "Preprocessing" node category.
*   **Nodes to Build**: Wrap existing Project0 functions:
    1.  **Standard Normal Variate (SNV)** / MSC (Scatter correction) - *Already in `nodes/preprocessing.py`*
    2.  **Savitzky-Golay Derivative** - *Already in `libs/project0/preprocess.py`, expose as Node*
    3.  **Cosmic Ray Removal** - *Already in `libs/project0/preprocess.py`, expose as Node*
    4.  **Wavenumber Alignment** ("Golden Grid") - *Already in `libs/project0/preprocess.py`, expose as Node*

### Priority 3: Interactive "Drill-Down" Visualizations
**Why**: Static plots are insufficient. In Simca/MCR, users need to identify *which* sample is the outlier.
*   **Feature**: Linked interactions in the Frontend.
*   **Action**: Clicking a point in a "Scores Plot" (PCA/PLS) should highlight the corresponding spectrum in the "Spectra Plot". This "Brushing and Linking" is a standard feature in high-end chemometric software.

### Priority 4: Model Validation Suite
**Why**: A model without validation numbers is dangerous.
*   **Feature**: Standardize model outputs to include Chemometric metrics, not just ML metrics.
*   **Metrics**: $Q^2$ (Predictive relevance), $R^2Y$, Permutation Tests (to check for overfitting), and RMSECV (Root Mean Square Error of Cross-Validation).

## 4. Updated Gap Analysis (Post-Audit)

**Correction**: High-quality preprocessing algorithms (Savitzky-Golay, Cosmic Ray Removal, Wavenumber Alignment) **already exist** in `backend/libs/project0/preprocess.py`.

**Correction**: A `NodeInspector` component **already exists** in `frontend/src/views/analysis/NodeInspector.vue`.

**Revised Problem**: The gap is not "Missing Features" but **"Disconnected Features"**.
*   The advanced preprocessing math in `project0` is not fully exposed as individual Nodes.
*   The `NodeInspector` is present but needs to be fully integrated with the DAG state to allow real-time parameter tuning (like Orange's widgets).

## Summary Recommendation
You have a strong foundation (Visual Engine + core MCR/SIMCA algorithms) AND a library of unexposed mathematical capabilities.

**Immediate Next Step**: Implementation of the `SpectralDataset` schema to ensure X-axis/metadata integrity, then wrap the *existing* `project0` functions into new Nodes.
