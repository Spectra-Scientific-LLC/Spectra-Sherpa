# Writing a Plugin Node

Plugin nodes let you turn a working Python chemometrics function into a visible SpectraSherpa workflow node. The goal is not to hide the science. The goal is to make the function reusable, typed, parameterized, testable, and visible in the workflow graph.

This guide uses a simple spectral transform as the example: subtract each spectrum's median intensity. It is intentionally small so you can see the node shape clearly before adding more advanced logic.

## What You Are Building

A workflow node needs five things:

| Part | Why It Matters |
| --- | --- |
| Node type | Stable identifier such as `custom.median_subtract`; saved workflows depend on it. |
| Category and label | Where the node appears in the toolbar and how users recognize it. |
| Parameters | User-editable controls with defaults and limits. |
| Input and output ports | The data contract. Most spectral transforms accept and return a `SpectralDataset` port, carried at runtime as a `SherpaDataset`. |
| Execution logic | The scientific operation, including validation and provenance. |

For ordinary dataset-in/dataset-out chemometric transforms, use `ChemometricsNode`. It handles common details for you:

- coercing inputs into `SherpaDataset`
- declaring a default `SpectralDataset` input and output port
- wrapping NumPy results back into a dataset with the original axes
- recording a processing-history entry
- emitting simple diagnostics such as output shape and intensity range

Use the lower-level `Node` class only when you need multiple named ports, model artifacts, non-dataset outputs, or custom execution behavior.

## Local Plugin Layout

For experimentation, place a plugin package under your user plugin folder:

```text
~/.spectra_sherpa/plugins/
└── median_plugin/
    ├── __init__.py
    └── nodes.py
```

SpectraSherpa loads plugins at startup from:

- `~/.spectra_sherpa/plugins/`
- the app data directory's `plugins/` folder
- installed Python packages that declare the `spectrasherpa.plugins` entry point

Plugin code runs as local Python code on your machine. Install only plugins you trust.

## Step 1: Create the Plugin Package

Create the folder and two files:

```bash
mkdir -p ~/.spectra_sherpa/plugins/median_plugin
touch ~/.spectra_sherpa/plugins/median_plugin/__init__.py
touch ~/.spectra_sherpa/plugins/median_plugin/nodes.py
```

In `__init__.py`, import the module that registers your node:

```python
# ~/.spectra_sherpa/plugins/median_plugin/__init__.py
from . import nodes  # noqa: F401
```

Registration happens when Python imports the module. If `__init__.py` does not import `nodes`, the node class may never be registered.

## Step 2: Write the Node

Add this to `nodes.py`:

```python
# ~/.spectra_sherpa/plugins/median_plugin/nodes.py
from __future__ import annotations

import numpy as np

from spectra_sherpa.sdk import ChemometricsNode, param_bool, register_node


@register_node
class MedianSubtractNode(ChemometricsNode):
    node_type = "custom.median_subtract"
    category = "preprocessing"
    label = "Median Subtract"
    description = "Subtract each spectrum's median intensity."
    parameters = [
        param_bool(
            "per_spectrum",
            default=True,
            label="Per Spectrum",
            description="Subtract each row median. If disabled, subtract one global median.",
        )
    ]

    def process(self, dataset, per_spectrum: bool = True):
        X = np.asarray(dataset.data, dtype=np.float64)

        if X.ndim != 2:
            raise ValueError("Median Subtract expects a 2D matrix: samples by variables.")

        if per_spectrum:
            med = np.nanmedian(X, axis=1, keepdims=True)
        else:
            med = np.nanmedian(X)

        return X - med
```

A few details are important:

- `@register_node` makes the node visible to the registry.
- `node_type` should be stable. Do not rename it casually after users save workflows.
- `category` should match an existing toolbar category such as `preprocessing`, `modeling`, `classification`, `selection`, `diagnostics`, `output`, or `data`.
- `process()` receives a `SherpaDataset`; use `dataset.data` for the numeric matrix.
- Returning a NumPy array is fine for simple transforms. `ChemometricsNode` wraps it back into a `SherpaDataset` with the original axes.

## Step 3: Restart and Find the Node

Restart SpectraSherpa after adding the plugin:

```bash
spectra-sherpa
```

Then open the Workflow Builder and look under the node category you chose. For this example, look under preprocessing for **Median Subtract**.

If the node does not appear:

- confirm the plugin folder contains `__init__.py`;
- confirm `__init__.py` imports `nodes`;
- check the terminal logs for plugin import failures;
- make sure the class is decorated with `@register_node`;
- make sure `node_type`, `category`, and `label` are non-empty strings.

## Step 4: Test the Logic Before Trusting It

Before using a new node in a real analysis, test the scientific operation with a small synthetic dataset. You can do this inside a local checkout or a standalone test script:

```python
import numpy as np

from median_plugin.nodes import MedianSubtractNode
from spectra_sherpa.sdk import SherpaDataset, SpectralAxis


def test_median_subtract_per_spectrum():
    axis = SpectralAxis(values=np.array([1000.0, 1001.0, 1002.0]), units="cm-1")
    ds = SherpaDataset(
        X=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]),
        feature_axis=axis,
        data_role="X_spectra",
    )

    node = MedianSubtractNode("test_node", {"per_spectrum": True})
    result = node.process(ds, per_spectrum=True)

    np.testing.assert_allclose(result, [[-1.0, 0.0, 1.0], [-10.0, 0.0, 10.0]])
```

This kind of test checks the core math without needing the browser. Add more tests for edge cases:

- one spectrum versus many spectra;
- NaN handling;
- empty or one-column matrices;
- spectra with negative intensities;
- feature-table inputs if the node should or should not accept them.

## Step 5: Be Honest About the Data Contract

Do not make a node look more general than it is. A spectral preprocessing node should reject data when it needs an ordered physical spectral axis.

For simple `ChemometricsNode` plugins, document this expectation in the description and tests. For lower-level nodes, declare ports with `accepted_data_roles=["X_spectra"]` when the node truly requires spectra rather than an unordered feature table.

Good examples:

- baseline correction requires spectra with an ordered physical axis;
- PCA can usually accept spectra or generic feature tables;
- library comparison requires spectra for both sample and library inputs;
- a classifier prediction node may accept feature tables if the trained model was built on feature tables.

## Step 6: Add Parameters Carefully

Use the SDK helpers for common controls:

```python
from spectra_sherpa.sdk import param_bool, param_number, param_select, param_text

parameters = [
    param_number("window", default=11, min_value=3, step=2, description="Odd smoothing window length."),
    param_select("method", options=["median", "mean"], default="median"),
    param_bool("center", default=True),
    param_text("label", default="custom"),
]
```

Parameter defaults should be scientifically conservative. If a parameter can produce misleading output outside a certain range, set `min_value`, `max_value`, `step`, and a clear description. Prefer explicit method names over hidden behavior.

## Step 7: Preserve Axes and Provenance

For simple transforms, returning a NumPy array is enough because `ChemometricsNode` builds a dataset like the input and records a processing step.

Return a full `SherpaDataset` when you intentionally change the feature axis, sample axis, data role, or metadata. For example, a node that crops wavenumbers should return a dataset with a shortened spectral axis, not just a shortened array.

The rule of thumb:

- same samples and same variables: returning an array is usually fine;
- changed variables, changed samples, new target values, or new data role: return a `SherpaDataset`;
- model objects, metrics, plots, or tables: use the lower-level `Node` API with explicit output ports.

## Step 8: Add Export Support When Possible

If the operation can be represented as a simple NumPy expression, set `numpy_expr` so exported Python workflows can reproduce it:

```python
@register_node
class ScaleIntensityNode(ChemometricsNode):
    node_type = "custom.scale_intensity"
    category = "preprocessing"
    label = "Scale Intensity"
    description = "Multiply every intensity by a scalar."
    parameters = [param_number("factor", default=1.0)]
    numpy_expr = "_data * {factor}"

    def process(self, dataset, factor: float = 1.0):
        return np.asarray(dataset.data, dtype=np.float64) * factor
```

Skip `numpy_expr` if the operation is complex, depends on external state, or needs several intermediate outputs. It is better to export a clear `NotImplementedError` than an incomplete scientific recipe.

## Step 9: Contribute a Node to the Repo

If you are contributing a built-in node rather than a local plugin, start with the scaffold:

```bash
cd packages/spectra-sherpa
python scripts/scaffold_node.py --name MedianSubtractNode --type chemometrics --category preprocessing
```

Then edit the generated node, tests, and documentation. The scaffold gives you the right file locations and a working shape, but you still need to:

- replace placeholder math with your real method;
- tighten parameter defaults and descriptions;
- add tests for valid input and invalid input;
- document expected inputs, outputs, and scientific limitations;
- run the relevant tests and docs build.

## Review Checklist

Before opening a pull request or sharing a plugin, check:

- The node type is stable and namespaced, for example `custom.median_subtract` or `vendor.method_name`.
- The label and description tell a scientist what the node actually does.
- Inputs and outputs are clear: spectra, target matrix, model, visualization, table, or metrics.
- The node rejects invalid shapes or unsupported data roles.
- The method does not silently introduce target leakage.
- Parameters have conservative defaults and useful ranges.
- The output preserves axes and sample labels.
- Processing history records the operation.
- Tests cover successful execution and at least one invalid input.
- Documentation states when the method is appropriate and when it is not.
