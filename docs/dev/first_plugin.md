# Your First Plugin Node

Generate a custom data-ingestion plugin for SpectraSherpa using an LLM,
register it, and validate the result with PCA — all in under 10 minutes.

> **Case study:** Loading 120 UV-Vis spectra from a raw CSV, then running
> PCA to get explained variance per principal component.

This guide uses an external LLM coding tool (Claude Code in VS Code) to
generate the plugin. Any workspace-aware LLM tool with access to the
repository will work; the steps below use Claude Code as a concrete
example.

---

## Prerequisites

1. **SpectraSherpa** cloned and installed with SpectroChemPy extras:
   ```bash
   git clone <repo-url> sherpa && cd sherpa/spectra-sherpa
   pip install -e ".[scp]"
   ```

2. **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** VS Code
   extension installed from the marketplace. Claude Code manages its own
   Anthropic credentials — no separate API key setup is needed if you
   already have the extension working.

3. **A data file** to ingest. This tutorial uses `UVSpectra10.csv`
   (headerless CSV: column 0 = wavelength in nm, columns 1+ = sample
   detector counts, 2038 rows).

---

## Key Concepts

<details>
<summary><strong>SherpaDataset</strong> — the universal data container</summary>

```python
SherpaDataset(
    X=spectra,                           # 2D numpy array (n_samples, n_features)
    feature_axis=SpectralAxis(...),       # wavelength/wavenumber axis
    sample_axis=SampleAxis(...),          # sample labels
    domain=DomainContext(technique=...),  # technique metadata
    title="...",
    units="...",
)
```

The LLM learns this constructor by reading the codebase — you don't need
to memorize it.
</details>

<details>
<summary><strong>Plugin nodes</strong> — how custom nodes get loaded</summary>

A plugin is a `.py` file placed in `~/.spectra_sherpa/plugins/`. It must
contain a class decorated with `@register_node`. When SpectraSherpa
starts, it imports every `.py` in that directory, which triggers
registration. Your node then appears in the Workflow Builder toolbar.

Plugins use a `custom.*` namespace (e.g., `custom.uv_csv_load`) to avoid
colliding with built-in types like `data.source` or `model.pca`.
</details>

<details>
<summary><strong>PCA node</strong> — the built-in analysis node we will connect to</summary>

`model.pca` accepts a `SherpaDataset` on its input port and returns
scores, loadings, and explained variance ratios. It lives in the
**Exploratory** toolbar section.
</details>

---

## Generate the plugin with an LLM coding tool

### Step 1 — Open the workspace

Open the `sherpa/` folder in VS Code. This gives Claude Code full
visibility into the SpectraSherpa source — it will read node definitions,
dataset classes, and the plugin loader to learn the framework on its own.

### Step 2 — Place your data file

Put `UVSpectra10.csv` (or your own CSV) in the `sherpa/` root so Claude
can inspect it.

### Step 3 — Prompt: generate the plugin

Open Claude Code (Cmd+Shift+P > "Claude Code: Open") and describe your
data. Be specific about the file name pattern and location:

> *Generate a customized data ingestion node for me to use. I need to
> read UVSpectra\*.csv in my sherpa folder. Make this a python file to import.*

<details>
<summary>Prompts for other data types</summary>

| Your situation | Example prompt |
|---------------|----------------|
| Raman .spc files | *"Create a plugin node that loads Raman .spc files from my data/ folder into SherpaDataset."* |
| FTIR with header row | *"I have FTIR CSV files with a header row (wavenumber, sample1, sample2, ...). Make a loader plugin."* |
| Fluorescence EEM | *"I need to load excitation-emission matrix CSVs as 3D SherpaDatasets."* |
</details>

Claude will inspect your CSV, read the framework source, generate
`load_uv_spectra.py`, and test it:

```
UVSpectra10: 120 samples x 2038 wavelengths (190.5–415.8 nm)
```

### Step 4 — Prompt: register as a plugin

> *Install this as a plugin so Sherpa discovers it at startup.*

Claude will run:

```bash
mkdir -p ~/.spectra_sherpa/plugins
cp load_uv_spectra.py ~/.spectra_sherpa/plugins/
```

### Step 5 — Validate on the Workflow Builder

Restart SpectraSherpa so it discovers the new plugin, then:

1. **Drag "UV CSV Load"** from the **Data** toolbar onto the canvas.
2. Set **CSV File Path** to your file (e.g., `/Users/you/sherpa/UVSpectra10.csv`).
3. **Drag "PCA"** from the **Exploratory** toolbar onto the canvas.
4. **Connect** the UV CSV Load output to the PCA input.
5. Set **Number of Components** to `5`.
6. **Execute** (play button).

**Expected result:**

```
PC1    99.84%
PC2     0.08%
PC3     0.01%
PC4     0.00%
PC5     0.00%
```

> PC1 at 99.84% is expected for raw detector counts — the baseline offset
> dominates. Insert a **Mean Center** or **SNV** node before PCA to reveal
> more structure.

You can also ask Claude to validate programmatically before opening the
browser:

> *Verify that this plugin can read the spectra as SherpaDataset and
> conduct a PCA using existing nodes. Report the % variance for the
> first PC.*

<details>
<summary>What Claude Opus 4.6 figured out on its own</summary>

The LLM was not given a template or told the API. By reading the
SpectraSherpa codebase as workspace context, it discovered:

| What | How |
|------|-----|
| CSV is wavelength-major, SherpaDataset is sample-major | Inspected the CSV vs. `SherpaDataset.__init__` expecting `X=(n_samples, n_features)` |
| `SpectralAxis(units="nm")` for UV wavelengths | Read `axes.py` and matched 190–416 nm to UV-Vis |
| `@register_node` + `custom.*` namespace | Read `node_base.py` and existing `custom.py` nodes |
| `input_ports=[]` for source nodes | Studied `SyntheticCurveNode` pattern |
| `add_processing_step()` for provenance | Observed every existing node calling it |
| Plugin goes in `~/.spectra_sherpa/plugins/` | Read `plugin_loader.py` |
| `.venv` path for running tests | Discovered the project virtual environment |

This is the value of workspace-aware LLM coding: the model reads
**actual framework code** rather than relying on potentially stale
documentation.
</details>

---

## Reference

<details>
<summary><strong>Plugin file structure</strong></summary>

A plugin is a single `.py` file (or a package with `__init__.py`) in:

```
~/.spectra_sherpa/plugins/
```

The file must contain at least one `@register_node`-decorated class.
On startup, SpectraSherpa imports every `.py` file in this directory.
</details>

<details>
<summary><strong>Node type naming</strong> — what to use, what to avoid</summary>

Built-in types are frozen — plugins cannot overwrite them. Use a
`custom.*` or `<vendor>.*` prefix:

| Your data | Good `node_type` | Bad (will collide) |
|-----------|------------------|--------------------|
| UV-Vis CSV loader | `custom.uv_csv_load` | `data.source` (built-in) |
| Raman .spc importer | `custom.raman_spc_load` | `data.file_load` (built-in) |
| Your company's format | `acme.proprietary_loader` | `preprocessing.snv` (built-in) |
</details>

<details>
<summary><strong>Plugin file naming</strong> — keep it descriptive</summary>

The filename becomes the Python module name. Use snake_case:

| Data you are loading | Good filename | Avoid |
|----------------------|---------------|-------|
| UV spectra CSVs | `load_uv_spectra.py` | `plugin.py`, `my_node.py` |
| Raman .spc files | `load_raman_spc.py` | `test.py`, `utils.py` |
| FTIR JCAMP-DX | `load_ftir_jdx.py` | `node1.py` |
</details>

<details>
<summary><strong>Available categories</strong></summary>

The `category` field controls which toolbar section the node appears in:

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

Unrecognized categories automatically create new toolbar sections.
For most custom loaders, use `data`.
</details>

<details>
<summary><strong>Key source files for LLM context</strong> — if prompting outside the workspace</summary>

If you are using an LLM without workspace access (e.g., a web chat),
pointing it at these files provides sufficient context:

| File | What it teaches the LLM |
|------|------------------------|
| `app/services/dag/node_base.py` | `Node`, `NodeMetadata`, `@register_node`, `NodeParameter`, `PortMetadata` |
| `app/lib/sherpa_dataset.py` | `SherpaDataset` constructor (`X`, `feature_axis`, `sample_axis`, `domain`) |
| `app/lib/axes.py` | `SpectralAxis`, `SampleAxis`, `TimeAxis`, and other axis types |
| `app/services/dag/nodes/data/synthetic.py` | Simple source node example (no inputs, dataset output) |
| `app/services/plugin_loader.py` | Plugin discovery directories and loading mechanism |
</details>
