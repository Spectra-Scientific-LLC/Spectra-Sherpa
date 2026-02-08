# Quickstart Guide

Get from zero to your first analysis in under 2 minutes.

## 1. Install & Launch

```bash
pip install -e .
spectrasherpa
```

Your browser opens automatically to `http://localhost:8000`. No login required — SpectraSherpa Lite runs as a local tool (like Jupyter). You're immediately on the Workspace page, ready to work.

> **Tip:** Use `spectrasherpa --port 9000` to pick a different port, or `--no-browser` if you prefer to open the URL yourself.

---

## 2. Load Example Data

SpectraSherpa Lite ships with access to SpectroChemPy's bundled example datasets. No downloads needed if SpectroChemPy is installed.

| Dataset | Location | Description |
|---------|----------|-------------|
| `irdata` | `~/.spectrochempy/data/irdata/` | FTIR spectra (e.g., NH4Y zeolite activation) |
| `ramandata` | `~/.spectrochempy/data/ramandata/` | Raman concentration series |
| `nmrdata` | `~/.spectrochempy/data/nmrdata/` | 1D NMR spectra |

To load data:

1. Navigate to the **Analysis** tab (sidebar icon).
2. Add a **Data Source** node to the canvas.
3. Set **Source Type** to `SpectroChemPy Example`.
4. Choose an **Example Dataset** (e.g., `irdata`).
5. Pick a specific file from the **Example File** dropdown (e.g., `nh4y-activation.spg`). Leave empty to load the dataset default.

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

## 4. Configure LLM API Keys (Optional)

SpectraSherpa Lite can use LLMs for AI-assisted workflow generation and a chat assistant. This is optional — all core spectroscopy features work without it.

### Option A: Environment Variables

Create a `.env` file in your project root (or wherever you run `spectrasherpa`):

```bash
# Copy the template
cp .env.example .env
```

Add your API key(s) — only the provider(s) you want to use:

```bash
# OpenAI (GPT-4o)
OPENAI_API_KEY=sk-...

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-...

# DeepSeek (most cost-effective)
DEEPSEEK_API_KEY=sk-...

# Google Gemini
GEMINI_API_KEY=AI...
```

Restart SpectraSherpa after editing `.env`. The configured provider(s) will appear in Settings.

### Option B: In-App Settings

1. Open SpectraSherpa in your browser.
2. Go to **Settings** > **API Keys** (or **Integrations**).
3. Enter your API key for the provider you want.
4. Click **Save** then **Test Connection** to verify.

> **Security note:** In local mode, API keys are stored encrypted on your machine. They never leave your computer unless you explicitly use an LLM feature (which sends your prompt to the LLM provider).

### Supported Providers

| Provider | Model | Env Variable | Use Case |
|----------|-------|-------------|----------|
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` | Best overall quality |
| Anthropic | `claude-sonnet-4-5-20250929` | `ANTHROPIC_API_KEY` | Strong reasoning |
| DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` | Most cost-effective |
| Google | `gemini-1.5-pro` | `GEMINI_API_KEY` | Good multimodal |

---

## 5. What's Next

- **Experiment Management**: Organize spectra with version tracking — see the [User Guide](../user_guide/experiments.md).
- **NIST Search**: Download reference spectra from NIST WebBook directly in the app.
- **Calibration**: Build quantitative models from multi-concentration measurements.
- **Export**: Send results to CSV, Excel, or Parquet for use in Origin/MATLAB.

For the full node catalog, see the [Node Reference](../reference/nodes.md).
