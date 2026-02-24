# Tutorial: Creating Your First Analysis Node

This guide walks you through adding a custom workflow node to SpectraSherpa. Two approaches are available:

1. **Declarative (preferred)** — Use `TransformSpecNode` or `EstimatorSpecNode` for standard patterns. Less code, automatic Python export.
2. **Imperative (advanced)** — Extend `Node` directly for custom logic. Full control, but you must implement `execute()` and optionally `generate_python()` yourself.

By the end, your node will appear in the Workflow Builder and be usable in any pipeline.

## Prerequisites

- A working development environment (see [Developer Setup](setup.md))
- Basic knowledge of Python and NumPy

---

## Approach 1: Declarative Node (Preferred)

For preprocessing transforms and sklearn-style estimators, declare a `spec` object and let the base class handle execution and export.

### Example: Clip Floor Transform

This node clips all values below a threshold. It's a real production node in SpectraSherpa:

```python
import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    NodeMetadata, NodeParameter, register_node,
)
from spectra_sherpa.app.services.dag.spec_nodes import TransformSpec, TransformSpecNode


@register_node
class ClipFloorNode(TransformSpecNode):
    """Clip values below a specified floor (e.g., remove negative values)."""

    metadata = NodeMetadata(
        node_type="preprocess.clip_floor",
        category="preprocessing",
        label="Clip Floor",
        description="Clip values below a specified floor",
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor Value",
                param_type="number",
                default=0.0,
                min_value=-10.0,
                max_value=10.0,
                step=0.001,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=lambda data, floor: np.maximum(data, floor),
        numpy_expr="np.maximum(_data, {floor})",
        extra_imports=["import numpy as np"],
    )
```

**What the spec provides automatically:**

| Feature | How |
|---------|-----|
| `execute()` | Extracts numpy data from the dataset, calls `transform_fn`, wraps result with metadata |
| `generate_python()` | Substitutes parameters into `numpy_expr` for Python export |
| `supports_python_export()` | Returns `True` because `numpy_expr` is set |
| Processing history | Recorded automatically in `dataset.meta["processing_history"]` |

**Key points:**

- `transform_fn` receives an `np.float64` array (dim 0 = samples, dim -1 = features) and keyword arguments matching parameter names
- `numpy_expr` is a format string where `{param_name}` is replaced with the resolved value. `_data` refers to the extracted numpy array.
- `extra_imports` are collected by the export system automatically
- Prefer `dataset.data`, `dataset.feature_axis`, and `dataset.meta` in plugin code. Compatibility aliases (`dataset.X`, `get_observation_axis()`, etc.) remain available for legacy plugins.

### When to use `export_lines_fn` instead of `numpy_expr`

If your export code needs branching logic (e.g., conditional centering), provide an `export_lines_fn` callback:

```python
from spectra_sherpa.app.services.dag.export_helpers import (
    extract_data_lines, header_line, wrap_result_lines,
)

def _my_export(params, inp, node_id, indent, use_scp):
    lines = [header_line("My Transform", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    if params.get("center", True):
        lines.append(f"{indent}_data = _data - np.mean(_data, axis=0)")
    lines += wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines
```

### Estimator Example

For sklearn-style nodes, use `EstimatorSpecNode`:

```python
from sklearn.linear_model import LinearRegression

from spectra_sherpa.app.services.dag.spec_nodes import EstimatorSpec, EstimatorSpecNode


@register_node
class LinearRegressionNode(EstimatorSpecNode):
    metadata = NodeMetadata(
        node_type="model.linear_regression",
        category="modeling",
        label="Linear Regression",
        description="Simple linear regression for calibration",
        parameters=[
            NodeParameter(name="fit_intercept", label="Fit Intercept",
                          param_type="boolean", default=True),
        ],
        input_ports=[...],   # X and y ports
        output_ports=[...],  # model, predictions, residuals ports
    )

    spec = EstimatorSpec(
        estimator_class=LinearRegression,
        estimator_import="from sklearn.linear_model import LinearRegression",
    )
```

The base class handles `bind_X`, `bind_y`, fitting, predicting, metrics (R², RMSE), and auto-generates Python export from `estimator_import`.

### Generate a scaffold

Use the template generator:

```bash
python scripts/node_template.py transform preprocess.my_op MyOpNode
python scripts/node_template.py estimator model.my_model MyModelNode
```

---

## Approach 2: Imperative Node (Advanced)

For nodes that don't fit the transform/estimator pattern (diagnostics, visualization, custom algorithms), extend `Node` directly.

### Example: Signal-to-Noise Ratio

```python
@register_node
class SNRNode(Node):
    """
    Signal-to-Noise Ratio estimation.

    Calculates SNR for each spectrum using peak signal divided by
    baseline noise (standard deviation of the first N points).
    """

    metadata = NodeMetadata(
        node_type="diagnostics.snr",
        category="diagnostics",
        label="Signal-to-Noise Ratio",
        description="Estimate SNR from peak signal vs. baseline noise",
        parameters=[
            NodeParameter(
                name="noise_points",
                label="Noise Region Size",
                param_type="number",
                default=20,
                min_value=5,
                max_value=200,
                step=1,
                description="Number of points from the start of the spectrum to use as noise estimate",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="snr_values",
                type_ref="spectrasherpa://types/Array1D/1.0",
                label="SNR Values",
                description="SNR value for each spectrum",
            ),
        ],
    )

    async def execute(self, data: Any) -> NodeResult:
        noise_points = self.parameters.get("noise_points", 20)

        X = np.array(data.data) if hasattr(data, "data") else np.array(data)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        snr_values = []
        for spectrum in X:
            signal = float(np.max(np.abs(spectrum)))
            noise_region = spectrum[:noise_points]
            noise = float(np.std(noise_region))
            snr = signal / noise if noise > 0 else 0.0
            snr_values.append(snr)

        snr_array = np.array(snr_values)

        return NodeResult(
            outputs={"snr_values": snr_array},
            diagnostics={
                "mean_snr": float(np.mean(snr_array)),
                "min_snr": float(np.min(snr_array)),
                "max_snr": float(np.max(snr_array)),
            },
        )
```

**Key points:**

- `execute()` is `async` — all node execution is async even if your logic is synchronous
- `NodeResult` wraps both `outputs` (data for downstream) and `diagnostics` (ephemeral metrics for UI)
- For Python export support, override `generate_python()` or set `scp_method`

### Generate a scaffold

```bash
python scripts/node_template.py custom diagnostics.snr SNRNode diagnostics
```

---

## Where to Put Your Node

| Approach | Location | Registration |
|----------|----------|--------------|
| **Core contribution** | `src/spectra_sherpa/app/services/dag/nodes/` | Add to existing module or create new one |
| **External plugin** | `~/.spectra_sherpa/plugins/my_plugin/` | Auto-discovered at startup |

## Verify Registration

The `@register_node` decorator handles registration automatically when the module is imported. Core node modules are already imported in `nodes/__init__.py`.

## As an External Plugin

```
~/.spectra_sherpa/plugins/
└── snr_plugin/
    ├── __init__.py      # imports nodes.py
    └── nodes.py         # @register_node classes
```

**`__init__.py`:**

```python
from . import nodes  # triggers @register_node on import
```

The plugin loader discovers this directory at startup and imports it automatically. You can also distribute plugins as installable packages using entry points:

```toml
# In your plugin's pyproject.toml
[project.entry-points."spectrasherpa.plugins"]
snr_plugin = "snr_plugin"
```

See `src/spectra_sherpa/app/services/plugin_loader.py` for the full discovery mechanism.
