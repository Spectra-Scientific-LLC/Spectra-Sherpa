# Workflow Builder

The **Workflow Builder** is a Directed Acyclic Graph (DAG) execution engine for spectral analysis. It allows you to chain processing steps (`Nodes`) together to create reproducible pipelines.

## Architecture

*   **Node Registry**: All nodes are registered in a central system (`app/services/dag/node_base.py`). This allows dynamic discovery of capabilities.
*   **Execution Engine**: The backend uses an asynchronous topological sort to execute nodes in the correct order. Independent branches run in parallel where possible.
*   **Data Flow**: Data is passed between nodes as `SherpaDataset` objects — the DAG's canonical runtime container (`app/lib/sherpa_dataset.py`). Processing history is tracked via typed `Provenance` entries with `state_effects`. SpectroChemPy `NDDataset` is used only by SCP-only nodes via round-trip adapters in `adapters/scp_adapter.py`. At API boundaries, results are serialized via `serialize_for_api()`, which includes spectral technique detection, data quantity identification, and the full processing chain.

## Toolbar Sections

The left toolbar organizes nodes into 11 sections following the standard chemometrics workflow:

| Section | Purpose |
|---------|---------|
| **Data** | Load spectra from files, experiments, sklearn, or NIST library |
| **Synthesis** | Create synthetic mixtures and blend spectra |
| **Preprocessing** | Smooth, differentiate, normalize, scale, baseline correct |
| **Exploratory** | PCA, MCR-ALS, SIMPLISMA, EFA, NMF, ICA, Peak Finding |
| **Regression** | PLS, PCR, SVR, Linear Regression, Load & Apply Model |
| **Classification** | PLS-DA, KNN, SIMCA training + Apply Classifier |
| **Clustering** | K-Means, DBSCAN, HCA |
| **Validation** | Cross-Validation, Outlier Detection, Statistics |
| **Custom** | User-defined algorithm nodes (plugins) |
| **Output** | Scatter Plot, Contour Plot, Data Table, Export |
| **Deployment** | Deploy Input/Output for headless prediction pipelines |

Preprocessing nodes use **consolidated method dropdowns** — for example, the Smooth node offers Savitzky-Golay, Whittaker, and Gaussian methods in a single dropdown. The Inspector panel hides irrelevant parameters automatically based on the selected method.

## Building a Workflow

1.  **Add Nodes**: Hover over a toolbar section to expand it, then click a node to add it to the canvas.
2.  **Connect**: Output → Input. The system validates connections (e.g., you cannot connect a `Model` output to a `Preprocessing` input if the types don't match).
3.  **Configure**: Set parameters in the Inspector. Parameters are typed (number, boolean, select) and validated. Consolidated nodes show only the parameters relevant to the selected method.

## Execution

When you click **Execute**:
1.  The graph is serialized and sent to the backend.
2.  The backend builds the execution order.
3.  **DataSource** nodes load or generate data.
4.  Data flows through processing nodes.
5.  Results are cached in memory.

### Status Indicators
*   **Pending** (Gray): Waiting for upstream data.
*   **Running** (Yellow): Currently executing (async).
*   **Completed** (Green): Successfully finished.
*   **Error** (Red): Failed. Check the error log for details.

## Exporting Code

The **Export Python** feature generates a standalone script.
*   It imports `spectrochempy` and `numpy`.
*   It instantiates the exact classes used in the backend (e.g., `scp.PCA`).
*   It reproduces the parameter settings exactly.
*   This ensures that your GUI workflow is perfectly reproducible in code.
