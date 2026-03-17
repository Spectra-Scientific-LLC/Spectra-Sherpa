# Quickstart Guide

Get from zero to your first analysis in under 2 minutes.

## 1. Install & Launch

```bash
pip install spectra-sherpa
spectra-sherpa
```

Your browser opens automatically to `http://localhost:8000`. In local mode, no login is required and SpectraSherpa behaves like a desktop tool. In hybrid or enterprise deployments, protected pages require the backend config to load successfully and then enforce normal authentication. The default route opens the **Projects** page, which is the current starting point for template-first onboarding.

If you want the SpectroChemPy-backed example datasets and workflows, install the optional extra:

```bash
pip install "spectra-sherpa[scp]"
```

> **Tip:** Use `spectra-sherpa --port 9000` to pick a different port, or `--no-browser` if you prefer to open the URL yourself.  
> If you frequently hit port conflicts, set `KILL_PORT_ON_START=true` in `.env` to auto-clear the selected port.

---

## 2. Create a Project

Projects are now the main entry point for starting work.

1. On the **Projects** page, click **New Project**.
2. Enter a name such as `My First Analysis`.
3. Save the project.

You can also stay on the same page and launch a validated workflow from the **Workflow Templates** gallery.

---

## 3. Launch Your First Workflow

The fastest path is to start from a validated template rather than building the first workflow from scratch.

### Option A: Start from a Project Template

1. Stay on **Projects**.
2. In **Workflow Templates**, pick a template such as PCA or preprocessing.
3. Launch it into the active project.
4. If the template uses example data, accept the default example binding or choose another supported example dataset.
5. Open the generated workflow in the **Workflow** page.

### Option B: Build One Manually

If you prefer to build the workflow yourself:

1. Open the **Workflow** page.
2. Add a `Data Source` node.
3. Add `Smooth (Savitzky-Golay)` and `PCA`.
4. Connect them as:

```text
Data Source -> Smooth -> PCA
```

5. Set a smoothing window such as `11`, polynomial order `2`, and PCA components `3`.

---

## 4. Load Your Own Data

You can work either from uploaded experiment files or from bundled example sources.

### Upload your own spectra

1. Open **Experiments**.
2. Create a new experiment.
3. Upload your spectral files.
4. Open the data preview flow and review the inferred names, units, quantity, and time-series status.
5. Apply any overrides you want to keep.

Supported formats include `.csv`, `.jdx`, `.dx`, `.spc`, `.spa`, `.spg`, `.txt`, `.wdf`, `.mat`, and `.opus`.

### Bind the workflow to your experiment

1. Return to **Workflow**.
2. Select the `Data Source` node.
3. Change the source to your experiment-backed data selection.
4. Pick the experiment and file, then re-execute the workflow.

Those Data/Explore overrides persist to the backend and are replayed when the workflow runs, so the workflow uses the same prepared dataset state you reviewed earlier.

---

## 5. Execute and Review Results

Click **Execute Workflow** from the workflow toolbar. After the run completes, select the output node to inspect plots, tables, and diagnostics in the results area.

Typical first checks:

- `PCA`: score plot and explained variance
- `Output Plot`: processed spectra preview
- `Export`: generated CSV artifact

---

## 6. Export Results

You can export from the workflow toolbar or from export-oriented output nodes in the graph.

- Python export writes a runnable script that replays your workflow and includes explicit prepared-data override assignments.
- Notebook export writes the same workflow as an executable Jupyter notebook.
- Zip export bundles the script, notebook, requirements, source data files, and workflow/prepared-data manifests under a relative `data/` folder.

Python and notebook exports look for source files in a `data/` folder next to the export by default. Set `SHERPA_DATA_DIR` if you want the exported code to read from a different location.

## 7. Configure LLM API Keys (Optional)

SpectraSherpa can use LLMs for the BYOK chat assistant. This is optional and separate from the core spectroscopy workflow features.

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

## 8. Enterprise Features

Enterprise features including advanced analytics and commercial support are available via licensing. Contact Spectra Scientific LLC for more information.

---

## 9. What's Next

- **Experiment Management**: Organize spectra with version tracking — see the [User Guide](experiments.md).
- **NIST Search**: Download reference spectra from NIST WebBook directly in the app (requires `EGRESS_ENABLED=true`).
- **Calibration**: Build quantitative models from multi-concentration measurements.
- **Export**: Send results to CSV or Excel.

For the full node catalog, see the [Node Reference](reference/nodes.md).
