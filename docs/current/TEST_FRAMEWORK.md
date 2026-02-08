# Chemometrics Integration Test Framework

## Overview

Automated test suite for validating workflow execution and chemometrics algorithms across the entire stack (API → Backend → SpectroChemPy).

**Tested algorithms:**
- **PCA** (Principal Component Analysis) - with flexible n_components (mle, variance threshold, integer)
- **MCR-ALS** (Multivariate Curve Resolution - Alternating Least Squares)
- **EFA** (Evolving Factor Analysis)
- **PLS** (Partial Least Squares) - node configuration tested, requires Y target
- **PLS-DA** (PLS Discriminant Analysis) - node configuration tested; labels can be auto-extracted from `X.y` or provided via a target output/port
- **SIMCA** (Soft Independent Modeling of Class Analogy) - node configuration tested; labels can be auto-extracted from `X.y` or provided via a target output/port

**Not implemented:**
- SIMPLISMA (no backend node exists)
- NMF (no backend node exists)

## Test Coverage

### Current Tests (9)

**PCA Tests:**
1. **PCA with n_components="mle"** - Maximum Likelihood Estimation for automatic component selection
2. **PCA with n_components="0.95"** - Variance threshold (95% explained variance)
3. **PCA with n_components="3"** - Integer component specification

**Component Analysis Tests:**
4. **PLS with n_components=3** - Partial Least Squares regression (requires Y target, currently skipped)
5. **MCR-ALS with n_components=3** - Multivariate Curve Resolution decomposition
6. **EFA with n_components=10** - Evolving Factor Analysis for rank determination

**Classification Tests:**
7. **PLS-DA with n_components=2** - Partial Least Squares Discriminant Analysis (uses `target` output or auto-extract)
8. **SIMCA with n_components=3** - Soft Independent Modeling of Class Analogy (uses `target` output or auto-extract)

**Data Source Tests:**
9. **Sklearn data sources** - Multiple dataset loading (wine, breast_cancer datasets have limited support)

### Test Results

```
✓ PCA with n_components='mle' on iris - MLE auto-selection worked
✓ PCA with n_components='0.95' variance threshold - Variance threshold worked
✓ PCA with n_components='3' (integer) - Integer n_components worked
⊘ PLS with n_components=3 - PLS requires Y target dataset
✓ MCR-ALS with n_components=3 - MCR-ALS decomposition worked
✓ EFA with n_components=10 - EFA rank determination worked
✓ PLS-DA with n_components=2 - Sklearn data source exposes target output port
✓ SIMCA with n_components=3 - Sklearn data source exposes target output port
✗ Sklearn data source variety (wine, breast_cancer) - SpectroChemPy 0.8.1 limitation

Total: 9 tests | Passed: 7 | Failed: 1 | Skipped: 1
```

### Algorithms NOT Implemented

The following algorithms from the user's request are **not currently implemented** in the backend:
- **SIMPLISMA** - No node exists for this algorithm
- **NMF** (Non-negative Matrix Factorization) - No node exists for this algorithm

## Prerequisites

- Backend server running at `http://127.0.0.1:8000`
- API key configured (default: `default-local-key`)
- Python 3.10+ with dependencies:
  - `requests`
  - Standard library: `json`, `time`, `sys`

## Running Tests

### Quick Start

```bash
# From the Refactored directory
cd /Users/fe2val/Documents/Spectra\ Scientific/Component_code/Refactored

# Make sure backend is running
# Terminal 1:
cd src/spectra_sherpa
uvicorn app.main:app --reload

# Terminal 2: Run tests
python test_pca_integration.py
```

### Expected Output

```
[HH:MM:SS] ============================================================
[HH:MM:SS] PCA Integration Test Suite
[HH:MM:SS] ============================================================
[HH:MM:SS] ✓ Backend connected: 50 nodes registered

[HH:MM:SS] ============================================================
[HH:MM:SS] TEST: PCA with n_components='mle' on iris
[HH:MM:SS] ============================================================
[HH:MM:SS] Created workflow 'Test PCA MLE' (ID: 123) with 2 nodes, 1 edges
[HH:MM:SS] Executing workflow 123...
[HH:MM:SS]   Execution completed with status: completed
[HH:MM:SS] ✓ PCA execution completed successfully
[HH:MM:SS] Cleaned up workflow 123

... (additional tests)

[HH:MM:SS] ============================================================
[HH:MM:SS] TEST RESULTS SUMMARY
[HH:MM:SS] ============================================================
[✓] PCA with n_components='mle' on iris - MLE auto-selection worked
[✓] PCA with n_components='0.95' variance threshold - Variance threshold worked
[✓] PCA with n_components='3' (integer) - Integer n_components worked
[⊘] PLS with n_components=3 - PLS requires Y target dataset
[✗] Sklearn data source variety (wine, breast_cancer) - No datasets could be tested
```

## Configuration

Edit constants at the top of `test_pca_integration.py`:

```python
API_BASE_URL = "http://127.0.0.1:8000/api/v1"  # Backend endpoint
API_KEY = "default-local-key"                   # API authentication key
```

## Test Framework Architecture

### Core Functions

#### `create_workflow_with_nodes(name, description, nodes, edges) -> int`
Creates a workflow with nodes and edges in a single API call.

**Example:**
```python
nodes = [
    {
        "node_id": "data-1",
        "node_type": "data.source",
        "label": "Iris Dataset",
        "parameters": {"source": "sklearn", "sklearn_dataset": "iris"},
        "position_x": 100,
        "position_y": 100
    },
    {
        "node_id": "pca-1",
        "node_type": "model.pca",
        "label": "PCA (MLE)",
        "parameters": {"n_components": "mle", "standardized": False, "scaled": False},
        "position_x": 400,
        "position_y": 100
    }
]

edges = [
    {
        "from_node_id": "data-1",
        "to_node_id": "pca-1",
        "from_output": "default",
        "to_input": "default"
    }
]

wf_id = create_workflow_with_nodes("Test Workflow", "Description", nodes, edges)
```

#### `execute_workflow(workflow_id, timeout=60) -> Dict`
Executes a workflow synchronously and returns results.

**Returns:**
```python
{
    "workflow_id": 123,
    "status": "completed",  # or "failed", "error"
    "results": {
        "node-id": {...}  # Node execution results
    },
    "node_statuses": {
        "node-id": "completed"  # or "failed", "pending"
    },
    "executed_at": "2024-01-15T10:30:00",
    "error": None  # or error message if failed
}
```

**Important:** Execution is synchronous - the API call blocks until workflow completes or times out.

#### `get_node_result(execution_result, node_id) -> Dict`
Extracts a specific node's result from execution response.

```python
result = execute_workflow(wf_id)
pca_node = get_node_result(result, "pca-1")

print(pca_node["status"])  # "completed"
print(pca_node["result"])  # PCA execution results
```

#### `cleanup_workflow(workflow_id)`
Deletes a workflow after test completion.

### Test Result Class

```python
class TestResult:
    def __init__(self, name: str, status: str, message: str = "", details: Any = None):
        self.name = name
        self.status = status  # PASS, FAIL, SKIP
        self.message = message
        self.details = details
```

**Status symbols:**
- ✓ PASS - Test completed successfully
- ✗ FAIL - Test encountered an error
- ⊘ SKIP - Test skipped (expected behavior, not an error)

## Adding New Tests

### Template

```python
def test_your_feature():
    """Test description."""
    test_name = "Your Feature Test Name"
    log(f"\n{'='*60}")
    log(f"TEST: {test_name}")
    log(f"{'='*60}")

    try:
        # 1. Define nodes
        nodes = [
            {
                "node_id": "unique-id",
                "node_type": "node.type",
                "label": "Display Label",
                "parameters": {...},
                "position_x": 100,
                "position_y": 100
            }
        ]

        # 2. Define edges
        edges = [
            {
                "from_node_id": "source-node",
                "to_node_id": "target-node",
                "from_output": "default",
                "to_input": "default"
            }
        ]

        # 3. Create workflow
        wf_id = create_workflow_with_nodes(
            "Workflow Name",
            "Description",
            nodes,
            edges
        )

        # 4. Execute
        result = execute_workflow(wf_id, timeout=120)

        # 5. Verify
        if result["status"] != "completed":
            raise AssertionError(f"Workflow failed: {result.get('error')}")

        node_result = get_node_result(result, "node-id")
        if node_result["status"] != "completed":
            raise AssertionError(f"Node failed: {node_result['status']}")

        log(f"✓ Test passed")
        test_results.append(TestResult(test_name, "PASS", "Success message"))

        # 6. Cleanup
        cleanup_workflow(wf_id)

    except Exception as e:
        log(f"✗ Test failed: {e}")
        test_results.append(TestResult(test_name, "FAIL", str(e)))
        if 'wf_id' in locals():
            cleanup_workflow(wf_id)
```

### Add to Main Runner

```python
def main():
    # ... existing setup ...

    # Add your test
    test_your_feature()

    # ... print summary ...
```

## Node Types and Parameters

### Available via `/workflows/nodes/library`

Query the backend for the full list:
```bash
curl -H "X-API-Key: default-local-key" http://127.0.0.1:8000/api/v1/workflows/nodes/library
```

### Common Node Types

**Data Source:**
```python
{
    "node_type": "data.source",
    "parameters": {
        "source": "sklearn",  # or "spectrochempy", "experiment"
        "sklearn_dataset": "iris"  # or "wine", "breast_cancer", "digits"
    }
}
```

**PCA:**
```python
{
    "node_type": "model.pca",
    "parameters": {
        "n_components": "mle",  # or "0.95", "3", etc.
        "standardized": False,
        "scaled": False
    }
}
```

**PLS:**
```python
{
    "node_type": "model.pls",
    "parameters": {
        "n_components": 3,
        "scale": True
    }
}
```

**MCR-ALS:**
```python
{
    "node_type": "model.mcr_als",
    "parameters": {
        "n_components": 3,
        "non_negative_C": True,  # Non-negative concentrations
        "non_negative_St": True,  # Non-negative spectra
        "max_iter": 50,
        "tol": 0.1
    }
}
```

**EFA:**
```python
{
    "node_type": "model.efa",
    "parameters": {
        "n_components": 10
    }
}
```

**PLS-DA:**
```python
{
    "node_type": "classification.plsda",
    "parameters": {
        "n_components": 2,
        "scale": True,
        "cv_folds": 5
    }
}
```
Note: Requires two inputs - X (spectra) and y (class labels)

**SIMCA:**
```python
{
    "node_type": "classification.simca",
    "parameters": {
        "n_components": 3,
        "confidence_level": 0.95
    }
}
```
Note: Requires two inputs - X (features) and y (class labels)

## Known Limitations

1. **SpectroChemPy Dataset Support**: Only `iris` dataset works with SpectroChemPy 0.8.1. The `wine` and `breast_cancer` datasets fail because SpectroChemPy doesn't provide `load_wine()` or `load_breast_cancer()` wrappers.

2. **Classification Node Testing**: Classification nodes (PLS-DA, SIMCA) and PLS regression require **separate X and y inputs**. The sklearn data source now exposes a `target` output port (and classifiers can auto-extract labels from `X.y`), so PLS-DA/SIMCA tests can run. PLS regression still requires an explicit target dataset or labels.

3. **Missing Algorithms**: The following algorithms are NOT implemented in the backend:
   - **SIMPLISMA** (Self Modeling Mixture Analysis)
   - **NMF** (Non-negative Matrix Factorization)

4. **Workflow Status Field**: The `workflow.status` field in the database is NOT updated during execution. The execute endpoint runs synchronously and returns results in the response, but leaves the workflow record in "draft" status.

5. **Timeout Handling**: Long-running workflows may timeout. Adjust `timeout` parameter in `execute_workflow()` if needed (max 600s recommended).

## Troubleshooting

### Backend Not Reachable
```
✗ Cannot connect to backend: Connection refused
```
**Solution:** Start the backend server:
```bash
cd src/spectra_sherpa
uvicorn app.main:app --reload
```

### API Key Invalid
```
403 Forbidden - Invalid API key
```
**Solution:** Check `API_KEY` constant matches backend configuration.

### Unknown Node Type
```
Unknown node type: 'your.node.type'
```
**Solution:** Query `/workflows/nodes/library` to verify correct node_type and parameters.

### Workflow Execution Timeout
```
Workflow execution timed out after 60s
```
**Solution:** Increase timeout in test:
```python
result = execute_workflow(wf_id, timeout=120)  # 2 minutes
```

### Node Failed Status
```
AssertionError: Node failed with status: failed
```
**Solution:** Check execution result for error details:
```python
result = execute_workflow(wf_id)
print(result.get("error"))  # Print error message
```

## Future Extensions

### Recommended Additions

1. **Component Analysis Algorithms** (Partially Complete)
   - ✅ MCR-ALS (Multivariate Curve Resolution) - **Now tested**
   - ✅ EFA (Evolving Factor Analysis) - **Now tested**
   - ⬜ SIMPLISMA - **Not implemented in backend**
   - ⬜ NMF (Non-negative Matrix Factorization) - **Not implemented in backend**

2. **Classification Nodes** (Partially Complete)
   - ✅ PLS-DA (Discriminant Analysis) - **Tests added; runs with `target` output or `X.y` labels**
   - ✅ SIMCA (Soft Independent Modeling of Class Analogy) - **Tests added; runs with `target` output or `X.y` labels**
   - ✅ KNN (K-Nearest Neighbors) - **Available but not yet tested**

3. **Data Preprocessing**
   - Baseline correction
   - Normalization
   - Smoothing
   - Derivative calculations

4. **Multi-Node Workflows**
   - Data → Preprocess → PCA → Visualization
   - Data → Split → Train/Test → Validate

5. **Result Validation**
   - Check explained variance ratios
   - Verify component counts
   - Compare with expected outputs

### Future Directions (Effectiveness Improvements)

1. **Deterministic Assertions (Beyond "completed")**
   - Validate output shapes (scores/loadings) and `metadata.n_components`.
   - Assert variance threshold behavior for `"0.95"` and component count for `"mle"`.

2. **PLS Test Without Skips**
   - Add a simple synthetic `Y` (e.g., linear combination of features) so PLS can run.
   - Verify predicted shape and coefficient dimensions.

3. **Stable Data Fixtures**
   - Use a local CSV/JSON fixture or a generated synthetic dataset for PCA/PLS tests.
   - Avoid reliance on SpectroChemPy dataset wrappers that may be version-limited.

4. **Negative Tests**
   - Validate error messages for invalid `n_components` values (e.g., `"-1"`, `"abc"`, `"1.5"`).
   - Check MLE constraint errors when `n_observations < n_features`.

5. **Reduce Timing Flakiness**
   - Replace fixed `sleep` in CI with a health check loop (e.g., `/docs` or `/nodes/library`).
   - If possible, poll node statuses instead of relying solely on synchronous calls.

6. **Test Isolation**
   - Use a test-specific API key and name prefix for workflows.
   - Verify cleanup and/or run against a temp DB in CI to avoid state bleed.

### CI/CD Integration

```yaml
# .github/workflows/integration-tests.yml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Start backend
        run: |
          cd src/spectra_sherpa
          uvicorn app.main:app &
          sleep 10
      - name: Run integration tests
        run: python test_pca_integration.py
```

## Contact

For issues or questions about the test framework, refer to the main project documentation or check the backend API documentation at `http://127.0.0.1:8000/docs` when the server is running.
