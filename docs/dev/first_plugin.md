# Tutorial: Creating Your First Analysis Node

This guide walks you through adding a custom workflow node to SpectraSherpa.

## Choose an authoring style

1. **ChemometricsNode (default, recommended)**
- Dataset-in / Dataset-out transforms with minimal framework code.
2. **TransformSpecNode / EstimatorSpecNode (advanced)**
- Declarative patterns for transform specs and sklearn fit/predict nodes.
3. **Raw Node (advanced)**
- Full control when you need custom ports or non-standard behavior.

## Approach 1: ChemometricsNode (Preferred)

For most OSS contributors, this is the fastest path.

```python
import numpy as np

from spectra_sherpa.sdk import ChemometricsNode, register_node, param_number


@register_node
class MySNVNode(ChemometricsNode):
    node_type = "preprocessing.my_snv"
    category = "preprocessing"
    label = "My SNV"
    description = "Standard normal variate normalization"
    parameters = [param_number("eps", default=1e-12, min_value=0.0)]

    def process(self, dataset, eps: float = 1e-12):
        X = np.asarray(dataset.data, dtype=np.float64)
        mu = X.mean(axis=1, keepdims=True)
        sd = X.std(axis=1, keepdims=True)
        return (X - mu) / np.maximum(sd, eps)
```

What you get automatically:
- Input coercion to `SherpaDataset`
- Output wrapping for ndarray-like returns
- Processing provenance (`add_processing_step`)
- Basic diagnostics (`shape`, `min`, `max`, `mean`, `std`)

## Scaffold a new node

Use the scaffold generator (defaults to `ChemometricsNode`):

```bash
python scripts/scaffold_node.py --name MySNVNode --type chemometrics --category preprocessing
```

Interactive mode:

```bash
python scripts/scaffold_node.py
```

## Approach 2: Transform/Estimator spec nodes (Advanced)

Use this when you want richer declarative behavior and built-in export patterns.

```python
from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodeParameter
from spectra_sherpa.app.services.dag.spec_nodes import TransformSpec, TransformSpecNode
from spectra_sherpa.sdk import register_node


@register_node
class ClipFloorNode(TransformSpecNode):
    metadata = NodeMetadata(
        node_type="preprocess.clip_floor",
        category="preprocessing",
        label="Clip Floor",
        description="Clip values below a floor",
        parameters=[
            NodeParameter(name="floor", label="Floor", param_type="number", default=0.0),
        ],
    )
    spec = TransformSpec(
        transform_fn=lambda data, floor: np.maximum(data, floor),
        numpy_expr="np.maximum(_data, {floor})",
        extra_imports=["import numpy as np"],
    )
```

## Approach 3: Raw Node (Advanced)

Use raw `Node` only when you need full control over ports, outputs, or execution flow.

## Available categories

The `category` field determines which toolbar section your node appears in:

| Category | Toolbar Section |
|----------|----------------|
| `data` | Data |
| `synthesis` | Synthesis |
| `preprocessing` | Preprocessing |
| `exploratory` | Exploratory |
| `regression` | Regression |
| `classification` | Classification |
| `clustering` | Clustering |
| `validation` | Validation |
| `output` | Output |
| `deploy` | Deployment |

Any unrecognized category automatically creates a new dynamic section in the toolbar.

## Where to put your node

- Core contribution: `src/spectra_sherpa/app/services/dag/nodes/`
- External plugin: `~/.spectra_sherpa/plugins/<plugin_name>/`

Example plugin layout:

```text
~/.spectra_sherpa/plugins/
└── my_plugin/
    ├── __init__.py
    └── nodes.py
```

`__init__.py` should import your node module so `@register_node` runs at import time.

## Verify registration

`@register_node` performs registration when the module imports. If your module is discoverable and imports cleanly, the node appears in the workflow node library.

## Advanced metadata features

### Conditional parameter visibility

Use `visible_when` to hide parameters that are irrelevant for a given method:

```python
NodeParameter(
    name="lam",
    label="Smoothness",
    param_type="number",
    default=1000,
    visible_when={"method": ["whittaker"]},  # Only shown when method=whittaker
)
```

