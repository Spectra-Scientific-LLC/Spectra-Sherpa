# Quickstart Guide

Get from zero to your first analysis in under 2 minutes.

## 1. Install & Launch

```bash
pip install spectra-sherpa
spectra-sherpa
```

Your browser opens automatically to `http://localhost:8000`. No login required — SpectraSherpa runs as a local tool (like Jupyter). You're immediately on the Workspace page, ready to work.

> **Tip:** Use `spectra-sherpa --port 9000` to pick a different port, or `--no-browser` if you prefer to open the URL yourself.  
> If you frequently hit port conflicts, set `KILL_PORT_ON_START=true` in `.env` to auto-clear the selected port.

---

## 2. Load Your First Dataset

You have two options: use bundled example data or upload your own files.

### Option A: Upload Your Own Spectra

1. Go to the **Experiments** page (sidebar).
2. Click **New Experiment** — give it a name (e.g., "My FTIR Data").
3. Click **Upload Files** and select your spectral files.

**Supported formats:** `.csv`, `.jdx`, `.dx`, `.spc`, `.spa`, `.spg`, `.txt`, `.wdf`, `.mat`, `.opus`

### Option B: Use Bundled Example Data

SpectraSherpa ships with access to SpectroChemPy's bundled example datasets. No downloads needed.

| Dataset | Description |
|---------|-------------|
| `irdata` | FTIR spectra (e.g., NH4Y zeolite activation) |
| `ramandata` | Raman concentration series |
| `nmrdata` | 1D NMR spectra |

To use example data in a workflow:

1. Navigate to the **Analysis** tab (sidebar icon).
2. Add a **Data Source** node to the canvas.
3. Set **Source Type** to `SpectroChemPy Example`.
4. Choose an **Example Dataset** (e.g., `irdata`).
5. Pick a specific file from the **Example File** dropdown (e.g., `nh4y-activation.spg`).

---

## 3. Your First Workflow: Smoothing + PCA

Build a simple pipeline: load data, smooth it, then run PCA.

### Add Nodes

Drag these from the Node Library onto the canvas:

- **Data** > `Data Source` (if not already added)
- **Preprocessing** > `Smooth (Savitzky-Golay)`
- **Modeling** > `PCA`

### Connect Them

Click and drag from each node's output port to the next node's input port:

```
Data Source  →  Smooth  →  PCA
```

### Configure Parameters

Click a node to edit it in the Inspector panel:

| Node | Parameter | Value |
|------|-----------|-------|
| **Smooth** | Window Size | `11` |
| **Smooth** | Polynomial Order | `2` |
| **PCA** | Number of Components | `3` |
| **PCA** | Standardize | `False` |

### Execute

Click **Execute Workflow**. Watch the status indicators:

- Gray = Pending
- Yellow = Processing
- Green = Complete

### View Results

Select the **PCA** node — the Results panel shows the Score Plot and Explained Variance chart.

---

## 4. Upload Your Own Data into a Workflow

Once you've tried the example, load your own spectra:

1. Change the **Data Source** node's **Source Type** to `Experiment File`.
2. Select your experiment and file from the dropdowns.
3. Re-execute the workflow.

The workflow remembers your parameter settings — only the data changes.

---

## 5. Export Results

After running a workflow, export your results:

1. Select the output node (e.g., PCA).
2. Click **Export** in the Results panel.
3. Choose format: **CSV** or **Excel**.
4. The file downloads to your browser.

---

## 6. Configure LLM API Keys (Optional)

SpectraSherpa can use LLMs for AI-assisted workflow generation and a chat assistant. This is optional — all core spectroscopy features work without it.

### Option A: Environment Variables

Create a `.env` file in your working directory:

```bash
EGRESS_ENABLED=true

# Add your LLM API key (configure in Settings > API Keys instead if you prefer):
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

Restart SpectraSherpa after editing `.env`. The configured provider(s) will appear in Settings.

### Option B: In-App Settings

1. Open SpectraSherpa in your browser.
2. Go to **Settings** > **API Keys**.
3. Enter your API key for the provider you want.
4. Click **Save** then **Test Connection** to verify.

> **Security note:** In local mode, API keys are stored encrypted on your machine. They never leave your computer unless you explicitly use an LLM feature (which sends your prompt to the LLM provider).

### Supported Providers

Configure your preferred LLM provider in **Settings > API Keys**. Any OpenAI-compatible provider is supported, including DeepSeek, OpenAI, Google Gemini, and custom endpoints.

---

## 7. Enterprise Features

Enterprise features including advanced analytics and commercial support are available via licensing. Contact Spectra Scientific LLC for more information.

---

## 8. What's Next

- **Experiment Management**: Organize spectra with version tracking — see the [User Guide](experiments.md).
- **NIST Search**: Download reference spectra from NIST WebBook directly in the app (requires `EGRESS_ENABLED=true`).
- **Calibration**: Build quantitative models from multi-concentration measurements.
- **Export**: Send results to CSV or Excel.

For the full node catalog, see the [Node Reference](reference/nodes.md).
