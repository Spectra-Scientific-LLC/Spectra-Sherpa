# Workflow Builder

The **Workflow Builder** is a Directed Acyclic Graph (DAG) execution engine for spectral analysis. It allows you to chain processing steps (`Nodes`) together to create reproducible pipelines.

## Architecture

*   **Node Registry**: All nodes are registered in a central system (`app/services/dag/node_base.py`). This allows dynamic discovery of capabilities.
*   **Execution Engine**: The backend uses an asynchronous topological sort to execute nodes in the correct order. Independent branches run in parallel where possible.
*   **Data Flow**: Data is passed between nodes as `SherpaDataset` objects — the DAG's canonical runtime container (`app/lib/sherpa_dataset.py`). Processing history is tracked via typed `Provenance` entries with `state_effects`. SpectroChemPy `NDDataset` is used only by SCP-only nodes via round-trip adapters in `adapters/scp_adapter.py`. At API boundaries, results are serialized via `serialize_for_api()`, which includes spectral technique detection, data quantity identification, and the full processing chain.

## Building a Workflow

1.  **Add Nodes**: Drag from the library.
2.  **Connect**: Output → Input. The system validates connections (e.g., you cannot connect a `Model` output to a `Preprocessing` input if the types don't match).
3.  **Configure**: Set parameters in the Inspector. Parameters are typed (number, boolean, select) and validated.

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