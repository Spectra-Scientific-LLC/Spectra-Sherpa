# Tutorial: Creating Your First Analysis Node

This guide walks you through adding a custom workflow node to SpectraSherpa. We'll create a **"Signal-to-Noise Ratio (SNR)"** node that calculates the SNR for each spectrum in a dataset.

By the end, your node will appear in the Workflow Builder under the "Diagnostics" category and be usable in any pipeline.

## Prerequisites

- A working development environment (see [Developer Setup](setup.md))
- Basic knowledge of Python and NumPy

## How Nodes Work

Every node in SpectraSherpa:

1. **Extends `Node`** — the abstract base class in `services/dag/node_base.py`
2. **Declares `metadata`** — a `NodeMetadata` dataclass that defines the node's type, category, parameters, and ports
3. **Implements `execute()`** — an async method that receives input data and returns results
4. **Registers via `@register_node`** — a decorator that adds the node to the global registry at import time

## Step 1: Choose Where to Put Your Node

There are two paths depending on whether you're contributing to the core project or building an external plugin:

| Approach | Location | Registration |
|----------|----------|--------------|
| **Core contribution** | `src/spectra_sherpa/app/services/dag/nodes/` | Add to existing module or create new one |
| **External plugin** | `~/.spectra_sherpa/plugins/my_plugin/` | Auto-discovered at startup |

This tutorial shows the **core contribution** path. For the plugin approach, see [Plugin Loading](#as-an-external-plugin) at the end.

## Step 2: Define the Node

Open `src/spectra_sherpa/app/services/dag/nodes/diagnostics.py` and add the following at the bottom of the file:

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

        # Get the data matrix (works with both NDDataset and AnalysisDataset)
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

**Key things to notice:**

- **`node_type`** uses dot notation (`diagnostics.snr`) — the prefix matches the category
- **`@register_node`** is already imported at the top of `diagnostics.py` (from `..node_base`)
- **`execute()`** is `async` — all node execution is async even if your logic is synchronous
- **`NodeResult`** wraps both `outputs` (data passed to downstream nodes) and `diagnostics` (ephemeral metrics shown in the UI)
- **`PortMetadata`** declares typed output ports using URIs from the type registry

## Step 3: Verify Registration

The `@register_node` decorator handles registration automatically when the module is imported. The `diagnostics` module is already imported in `src/spectra_sherpa/app/services/dag/nodes/__init__.py`, so your new node will be discovered at startup — no additional wiring needed.

## Step 4: Test It

```bash
# Start the dev server
make dev

# Or directly:
poetry run spectra-sherpa
```

1. Open the Workflow Builder
2. Look in the node palette — "Signal-to-Noise Ratio" should appear under **Diagnostics**
3. Connect a Data Source node → your SNR node
4. Run the workflow and check the diagnostics panel for mean/min/max SNR

## Next Steps

- **Add a noise region selector**: Let users pick a wavenumber range instead of a fixed point count. Add a `"select"` parameter with options like `"first_n"`, `"last_n"`, `"min_region"`.
- **Return a visualization**: Add an output port with `type_ref="spectrasherpa://types/PlotData/1.0"` and return a bar chart of per-spectrum SNR values.
- **Add processing history**: Call `add_processing_step()` from `..meta_helpers` so the SNR calculation appears in the dataset's provenance chain.
- **Write a test**: Add a test in `tests/` that creates an `SNRNode`, feeds it synthetic data, and asserts the output shape and values.

## As an External Plugin

If you want to distribute your node as a standalone package instead of a core contribution, use the plugin system:

```
~/.spectra_sherpa/plugins/
└── snr_plugin/
    ├── __init__.py      # imports nodes.py
    └── nodes.py         # @register_node classes
```

**`nodes.py`:**

```python
import numpy as np
from spectra_sherpa.app.services.dag.node_base import (
    Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node,
)

@register_node
class SNRNode(Node):
    # ... same class definition as above ...
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
