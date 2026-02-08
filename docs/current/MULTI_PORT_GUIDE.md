# Multi-Input/Multi-Output Node Guide

## Overview

The workflow system supports nodes with multiple named input/output ports, enabling complex data routing patterns like train/test splits, model training/testing, and multi-output predictions.

## Multi-Output Nodes

### Train/Test Split Example

The `Train/Test Split` node has **4 output ports**:
- `X_train` (dataset) - Training feature data
- `X_test` (dataset) - Test feature data
- `y_train` (target) - Training targets (optional)
- `y_test` (target) - Test targets (optional)

**Usage Pattern:**
```
Data Source → Train/Test Split → X_train → PCA Train
                               → X_test → PCA Transform
                               → y_train → PLS Train (y input)
                               → y_test → Evaluate Model
```

### How to Connect from Multi-Output Nodes

1. **Click Connect** on the source node
2. **Select output port** from the button list (e.g., "Training Data", "Test Data")
3. **Click target node** or select its input port

## Multi-Input Nodes

### PLS Training Example

The `PLS` node has **2 input ports**:
- `X` (dataset) - Spectral data matrix
- `y` (target) - Concentration/target values

### Apply PLS Predict Example

The `Apply PLS Predict` node has **2 input ports**:
- `X_new` (dataset) - New spectra to predict
- `model` (model) - Trained PLS model

**Usage Pattern:**
```
Train/Test Split → X_train ──→ X ──┐
                              │    PLS Train → model → Apply PLS → predictions
Data Source → y values ───────→ y ──┘            ↑
                                                 │
Train/Test Split → X_test ───────────────────────┘ (X_new input)
```

### How to Connect to Multi-Input Nodes

1. **Click Connect** on source node
2. **Click target node** with multiple inputs
3. **Select input port** from the button list (e.g., "Spectra (X)", "Model")

## Port Types

The system uses 6 port types with color coding:

| Type | Color | Description | Example |
|------|-------|-------------|---------|
| `dataset` | 🔵 Blue | Spectral data (NDDataset) | Raw spectra, preprocessed data |
| `array` | 🟢 Green | Numeric arrays, matrices | PCA scores, predictions, peak lists |
| `target` | 🟠 Orange | y values, labels, concentrations | Class labels, concentrations |
| `model` | 🟣 Purple | Trained model objects | PCA model, PLS model, SIMCA models |
| `number` | ⚪ Gray | Scalar values, metrics | Accuracy, R², component counts |
| `visualization` | 🔷 Cyan | Plot data, charts | Scatter plots, heatmaps |

## Port Type Validation

**Valid Connections:**
- ✅ dataset → dataset (Preprocessing output → PCA input)
- ✅ array → array (PCA scores → Plot input)
- ✅ model → model (PLS Train output → Apply PLS model input)
- ✅ target → target (Split y_train → PLS y input)

**Invalid Connections:**
- ❌ dataset → model (Type mismatch error)
- ❌ target → dataset (Type mismatch error)
- ❌ array → model (Type mismatch error)

## Backend Implementation

### Defining Multi-Output Nodes

```python
from ..node_base import Node, NodeMetadata, PortMetadata

metadata = NodeMetadata(
    node_type="data.train_test_split",
    category="data",
    label="Train/Test Split",
    description="Split data into training and test sets",
    output_ports=[
        PortMetadata(
            name="X_train",
            port_type="dataset",
            required=True,
            label="Training Data",
            description="Training subset of input data",
        ),
        PortMetadata(
            name="X_test",
            port_type="dataset",
            required=True,
            label="Test Data",
            description="Test subset of input data",
        ),
    ],
)

async def execute(self, X, y=None):
    # ... splitting logic ...

    return {
        "X_train": X_train_data,
        "X_test": X_test_data,
        "y_train": y_train_data,  # Optional
        "y_test": y_test_data,    # Optional
    }
```

**Key Points:**
- Return dict keys must match `output_ports` names
- Executor extracts specific outputs using `edge.from_output`
- Optional ports (like `y_train`) can be omitted from result dict

### Defining Multi-Input Nodes

```python
metadata = NodeMetadata(
    node_type="modeling.pls",
    category="modeling",
    label="PLS Regression",
    description="Partial Least Squares regression",
    input_ports=[
        PortMetadata(
            name="X",
            port_type="dataset",
            required=True,
            label="Spectra (X)",
            description="Spectral data matrix",
        ),
        PortMetadata(
            name="y",
            port_type="target",
            required=True,
            label="Concentrations (y)",
            description="Target concentration values",
        ),
    ],
)

async def execute(self, X=None, y=None, **kwargs):
    # Inputs passed as kwargs by port name
    # ... training logic ...
    return {"model": trained_pls_model, "scores": pls_scores}
```

## Frontend Implementation

### Dynamic Port Discovery

The frontend automatically:
- Fetches node metadata from backend on mount
- Renders port indicators with correct colors
- Shows port selection UI for multi-input/output nodes
- Validates connections based on port types

### WorkflowCanvas.vue Port Rendering

```vue
<!-- Output ports (right side) -->
<div class="output-ports">
  <div
    v-for="(port, idx) in getNodeOutputPorts(node.type)"
    :key="`output-${port.name}`"
    class="port port-output"
    :style="{
      top: `${30 + idx * 20}px`,
      backgroundColor: getPortColor(port.port_type)
    }"
    :title="`${port.label} (${port.port_type})`"
  >
    <!-- Tooltip with port info -->
  </div>
</div>
```

## Troubleshooting

### "Port type mismatch" Error

**Cause:** Trying to connect incompatible port types (e.g., `dataset` → `model`)

**Solution:** Check port colors and types. Only connect matching types:
- Blue (dataset) → Blue (dataset)
- Green (array) → Green (array)
- Purple (model) → Purple (model)
- Orange (target) → Orange (target)
- Gray (number) → Gray (number)
- Cyan (visualization) → Cyan (visualization)

### "Must specify input port" Error

**Cause:** Connecting to multi-input node without selecting which port

**Solution:** When connecting to a node with multiple inputs, click the specific port button (e.g., "Spectra (X)" or "Model")

### "Output port not found" Error

**Cause:** Backend node returned dict missing expected output port

**Solution:** Check that node's `execute()` returns dict with all declared `output_ports` names (or mark ports as `required=False`)

## Example Workflows

### Complete Train/Test Classification

```
1. Data Source
   ↓
2. Train/Test Split
   ├─ X_train → PLS-DA Train (X)
   ├─ y_train → PLS-DA Train (y)
   ├─ X_test → Apply PLS-DA (X_new)
   └─ model (from PLS-DA Train) → Apply PLS-DA (model)
                                    ↓
                            Predicted Classes
```

### Multi-Stage Model Pipeline

```
1. Data Source
   ↓
2. Train/Test Split
   ├─ X_train → PCA Train → model ─┐
   ├─ X_test ─────────────────────┐ │
   │                              ↓ ↓
   └─────────────────────→ PCA Transform → PLS Train
                                             ↓
                                        PLS Model
```

## Best Practices

1. **Use Port Labels** - Port labels are more readable than port names in UI
2. **Color Consistency** - Keep port type colors consistent across all nodes
3. **Optional Ports** - Mark truly optional ports as `required=False`
4. **Descriptive Names** - Use clear port names like "X_train" not "output1"
5. **Type Safety** - Always validate port types in backend `execute()` method

## Migration from Legacy Single-Port Nodes

### Before (Single Output)
```python
async def execute(self, input_data):
    result = process(input_data)
    return result  # Single NDDataset returned
```

### After (Multi-Output)
```python
async def execute(self, input_data):
    result1, result2 = process(input_data)
    return {
        "output1": result1,  # Named output
        "output2": result2,  # Named output
    }
```

Add `output_ports` to metadata and return dict instead of single value.
