# Scientist Contributor Guide

**You already know the algorithms.** This guide gets you from an idea to a
working contribution without requiring any background in web development,
deployment, or software infrastructure.

---

## Who this is for

- Analytical chemists, spectroscopists, and physical scientists who write Python
- Data analysts and researchers who use scikit-learn, NumPy, SciPy, or pandas
- Anyone with a working algorithm in a script or notebook who wants to share it
- AI/ML researchers who want to extend SpectraSherpa's analysis capabilities

If you are instead focused on improving the software infrastructure, UI, or
tooling, see the [Developer Contributor Guide](developer-guide.md).

---

## Start here: try it on your data (5 minutes)

```bash
pip install spectra-sherpa
spectra-sherpa
```

This opens `http://localhost:8000` in your browser. No login, no configuration.

To use SpectroChemPy example datasets (FTIR, Raman, NIR):

```bash
pip install spectra-sherpa[scp]
```

To load your own data: drag a CSV file (samples as rows, wavenumbers as
columns) onto the Data page. The app detects the format automatically.

---

## How SpectraSherpa relates to what you already use

If you have written something like this in a notebook:

```python
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import numpy as np

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

pca = PCA(n_components=5)
scores = pca.fit_transform(X_scaled)
loadings = pca.components_
explained_var = pca.explained_variance_ratio_
```

SpectraSherpa runs the same computation. The `model.pca` node uses the same
underlying mathematics. Results are validated side-by-side against scikit-learn
reference outputs. See the
[PCA reproduction study](../user/case_study_pca.md) for a concrete numerical
comparison using a published spectral dataset — same parameters, same results,
verified to five decimal places.

**The goal is not to replace your scripts.** It is to let you build and
explore visually, track every processing decision with provenance, and then
export the result as a standalone Python script or Jupyter notebook that
runs anywhere without SpectraSherpa.

### The data format

SpectraSherpa's data container is a thin layer over NumPy. Your existing
array operations work without modification:

```python
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis, SampleAxis

# Wrap your existing array
ds = SherpaDataset(
    X=your_array,                                      # (n_samples, n_features)
    feature_axis=SpectralAxis(values=wavenumbers, units="cm-1"),
    sample_axis=SampleAxis(values=sample_ids),
    title="My dataset",
)

# Get the raw array back at any time
X = ds.data          # NumPy array, shape (n_samples, n_features)
y = ds.target        # labels or reference values, if any
wn = ds.feature_axis.values   # wavenumber or wavelength axis
```

---

## Contributing your own algorithm

If you have a working function in a script or Jupyter notebook, you can turn
it into a processing step in the Workflow Builder. Once added, it:

- Appears as a drag-and-drop node in the toolbar
- Can be connected to any other processing step
- Is included in Python and notebook exports
- Can be shared with other users

### Step 1 — Install the development version

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa/spectra-sherpa
pip install poetry
poetry install --with dev
```

Verify the test suite passes before you start:

```bash
make test
```

### Step 2 — Generate the node file

```bash
make node-scaffold
```

The interactive prompt asks for:

| Question | Example answer |
|----------|---------------|
| Node name | `AsymmetricLeastSquaresNode` |
| Category | `preprocessing` |
| Description | `Asymmetric least squares baseline correction` |
| Type | `chemometrics` (recommended default for most scientific algorithms) |

It generates three files:

```
src/spectra_sherpa/app/services/dag/nodes/asymmetric_least_squares_node.py  ← your implementation
tests/nodes/test_asymmetric_least_squares_node.py                           ← your tests
docs/nodes/asymmetric_least_squares_node.md                                 ← documentation template
```

For a guided walkthrough of loading external data and connecting it to a
PCA node, see [Your First Plugin Node](../dev/first_plugin.md).

### Step 3 — Put your algorithm in the execute method

Open the generated node file. Find the `execute()` method and replace the
placeholder with your function. The input is a `SherpaDataset`; return a
new one with the transformed data:

```python
async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
    ds = coerce_to_sherpa(input_data)   # SherpaDataset coming in
    lam = self.parameters.get("lam", 1e5)
    p   = self.parameters.get("p", 0.001)

    # ds.data is a plain NumPy array — call your function directly
    corrected = asymmetric_least_squares(ds.data, lam=lam, p=p)

    # Return a new SherpaDataset with the same axes and metadata
    return build_dataset_like(corrected, ds)
```

If your algorithm follows the scikit-learn pattern (`fit` then `transform`
or `predict`), the scaffold generator can create an `EstimatorSpecNode`
instead — it handles the fit/predict split, model serialization, and
deployment for you automatically.

### Step 4 — Write a test that verifies correctness

Open the generated test file. Add one test that checks your algorithm
against a known reference — a published result, a hand-calculated value,
or scikit-learn output:

```python
import asyncio
import numpy as np
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis


def test_als_baseline_removes_offset():
    # Flat spectrum with a known linear baseline added
    X = np.ones((5, 100))
    X += np.linspace(0, 1, 100)    # add a ramp baseline

    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.arange(100, dtype=float)),
    )
    node = AsymmetricLeastSquaresNode("test_node", {"lam": 1e5, "p": 0.001})
    result = asyncio.run(node.run(ds))

    # After correction the baseline should be near zero
    out = result.outputs["default"] if hasattr(result, "outputs") else result
    baseline_residual = np.abs(out.data).mean()
    assert baseline_residual < 0.05, f"Residual too large: {baseline_residual:.4f}"
```

Run your test:

```bash
poetry run pytest tests/nodes/test_asymmetric_least_squares_node.py -v
```

### Step 5 — Submit a pull request

```bash
git checkout -b add-als-baseline
git add src/ tests/ docs/
git commit -m "add: Asymmetric Least Squares baseline correction node"
# then open a pull request on GitHub
```

What to include in the pull request description:

- **What the algorithm does** — one paragraph, plain language
- **A reference** — paper, textbook section, or well-known package that
  implements the same method
- **How you verified it** — a comparison to a known result, a figure, or
  a link to the test output
- **An example** — dataset name and expected output from your test

You do not need to modify anything related to the web interface, CI
configuration, or deployment setup. A pull request that touches only
`src/`, `tests/`, and `docs/` is complete.

---

## What reviewers look for

Reviewers are domain scientists and engineers. The review order is:

1. **Does the algorithm do what it claims?**
   Show a reference or a numerical comparison.

2. **Does it handle common edge cases?**
   Single-sample input, all-zero spectra, very short or very long wavelength
   axes, missing target values.

3. **Are the parameters documented?**
   A user should understand what each parameter controls and what reasonable
   values look like.

4. **Does the test cover the core behavior?**
   One or two well-chosen tests are sufficient. Coverage for its own sake is
   not a goal.

Code formatting is applied automatically when you run `make fmt`. You will
not be asked to fix style issues manually.

---

## Useful reference points in the codebase

| What you want to understand | Where to look |
|-----------------------------|---------------|
| How a preprocessing node is structured | `src/spectra_sherpa/app/services/dag/nodes/preprocessing.py` |
| How a fit/predict model node works | `src/spectra_sherpa/app/services/dag/nodes/modeling/pca_nodes.py` |
| The SherpaDataset API | `src/spectra_sherpa/app/lib/sherpa_dataset.py` |
| Axis types: spectral, sample, time | `src/spectra_sherpa/app/lib/axes.py` |
| The base Node class | `src/spectra_sherpa/app/services/dag/node_base.py` |
| PCA vs scikit-learn side-by-side | `docs/user/case_study_pca.md` |
| Full node scaffold walkthrough | `docs/dev/node_scaffold_generator.md` |
| Plugin node from scratch with LLM assistance | `docs/dev/first_plugin.md` |

---

## Questions?

Open a GitHub issue with the label `question`. You do not need a finished
implementation to ask whether an algorithm would be a good fit for the project.
