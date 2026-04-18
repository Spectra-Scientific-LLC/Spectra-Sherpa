# Start from Zero: Full Setup Guide

Complete procedure for setting up SpectraSherpa from scratch using GitHub Desktop and Visual Studio Code, with an optional bring-your-own-endpoint chat assistant. Written for chemists and spectroscopists — no prior coding experience required.

## Prerequisites checklist

Before you start, you need three free tools installed. If you already have any of them, skip that step.

---

## Step 1 — Install Python 3.11+

SpectraSherpa requires Python 3.11 or newer.

**Windows:**
1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download the latest Python 3.12 or 3.13 installer
3. Run the installer — **check "Add python.exe to PATH"** at the bottom of the first screen (this is critical)
4. Click "Install Now"
5. Verify: open a Command Prompt and type:
   ```
   python --version
   ```
   You should see `Python 3.12.x` or `Python 3.13.x`

**macOS:**
1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the macOS installer, or use Homebrew:
   ```
   brew install python@3.12
   ```
2. Verify:
   ```
   python3 --version
   ```

---

## Step 2 — Install GitHub Desktop

1. Go to [desktop.github.com](https://desktop.github.com/)
2. Download and install for your OS
3. Open GitHub Desktop and sign in with your GitHub account (free account is fine)

---

## Step 3 — Install Visual Studio Code

1. Go to [code.visualstudio.com](https://code.visualstudio.com/)
2. Download and install for your OS
3. Open VS Code and install the **Python** extension:
   - Click the Extensions icon in the left sidebar (or press `Ctrl+Shift+X`)
   - Search for "Python" (by Microsoft)
   - Click **Install**

---

## Step 4 — Clone SpectraSherpa with GitHub Desktop

1. Open **GitHub Desktop**
2. Go to **File > Clone Repository...**
3. Click the **URL** tab
4. Paste this URL:
   ```
   https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
   ```
5. Choose a local path (e.g. `C:\Users\YourName\Documents\Spectra-Sherpa` on Windows or `~/Documents/Spectra-Sherpa` on Mac)
6. Click **Clone**
7. Wait for the download to finish — this is the full source code

---

## Step 5 — Open the project in VS Code

From GitHub Desktop:

1. After the clone finishes, click **"Open in Visual Studio Code"** (button in the center of GitHub Desktop)
   - If you don't see this button, go to **Repository > Open in Visual Studio Code** in the menu bar

This opens VS Code with the project folder loaded.

---

## Step 6 — Create a virtual environment

Open the VS Code **integrated terminal**: press `` Ctrl+` `` (backtick) or go to **Terminal > New Terminal** from the menu.

You should see the terminal at the bottom of VS Code, already in the project folder (e.g., `C:\Users\YourName\Documents\Spectra-Sherpa`).

**Windows (Command Prompt or PowerShell):**
```
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` appear at the beginning of your terminal prompt. This means the virtual environment is active.

> **VS Code auto-detection:** VS Code will likely show a notification asking "We noticed a new virtual environment..." — click **Yes** to select it as the workspace interpreter. If you miss the notification, press `Ctrl+Shift+P`, type "Python: Select Interpreter", and pick the `.venv` one.

---

## Step 7 — Install SpectraSherpa and its dependencies

Still in the VS Code terminal (with `.venv` active):

**Option A — Full install with SpectroChemPy (recommended for chemometricians):**
```
pip install -e ".[scp]"
```

This installs SpectraSherpa in editable mode plus the SpectroChemPy algorithms (PCA, PLS, MCR-ALS, EFA, SIMPLISMA, and advanced file readers for JCAMP, SPC, OPUS formats).

**Option B — Minimal install (no SpectroChemPy):**
```
pip install -e .
```

This gives you the built-in algorithms (PCR, SVR, KNN, clustering, all preprocessing) but not the SpectroChemPy-powered nodes.

> **Note:** The install may take 2-5 minutes depending on your internet speed. NumPy, SciPy, and scikit-learn are large packages.

If you use **Poetry** (the project's native build tool) instead of pip:
```
pip install poetry
poetry install --extras scp
```

---

## Step 8 — Launch SpectraSherpa

In the same terminal:

```
spectra-sherpa
```

You'll see output like:
```
Starting SpectraSherpa v0.1.6
  Mode:   local
  URL:    http://127.0.0.1:8000
  Press Ctrl+C to stop.
```

Your default browser automatically opens to `http://localhost:8000`. No login required — you're in.

> **Tip:** If port 8000 is busy, use `spectra-sherpa --port 9000` instead.

---

## Step 9 — Enable the BYO chat assistant (optional)

OSS SpectraSherpa ships a minimal "bring your own endpoint" chat
assistant. It is a thin HTTP proxy: you give it a URL and an API key for
any OpenAI-compatible `/chat/completions` endpoint, and the chat panel
in the UI will stream single-turn replies from it. There are no tools,
no server-side conversation store, and no agent loop — just a plain
chat box backed by a provider you control.

**Cheapest option: DeepSeek** (~$0.14/million tokens — practically free for lab use)

1. Go to [platform.deepseek.com](https://platform.deepseek.com/) and create an account
2. Generate an API key
3. In the SpectraSherpa project folder, create a file called `.env` (note the leading dot). In VS Code: **File > New File**, save as `.env` in the project root, with these contents:

```
EGRESS_ENABLED=true
CHAT_ENDPOINT_URL=https://api.deepseek.com/v1
CHAT_ENDPOINT_KEY=sk-your-key-here
CHAT_ENDPOINT_MODEL=deepseek-chat
```

4. Stop SpectraSherpa in the terminal (`Ctrl+C`) and restart it:
```
spectra-sherpa
```

5. Open the chat panel from the sidebar and send a test message. If the
   panel doesn't appear, check that `/api/v1/config` reports
   `chatAssistant: true` (both `CHAT_ENDPOINT_URL` and
   `CHAT_ENDPOINT_KEY` must be set).

**Other OpenAI-compatible endpoints** (same `.env` pattern, just
different `CHAT_ENDPOINT_URL` / `CHAT_ENDPOINT_MODEL` values):

```
# OpenAI
CHAT_ENDPOINT_URL=https://api.openai.com/v1
CHAT_ENDPOINT_KEY=sk-...
CHAT_ENDPOINT_MODEL=gpt-4o-mini

# A local OpenAI-compatible server (vLLM, Ollama, llama.cpp, ...)
CHAT_ENDPOINT_URL=http://localhost:8080/v1
CHAT_ENDPOINT_KEY=anything
CHAT_ENDPOINT_MODEL=llama-3.1-8b-instruct
```

> **Privacy:** Your spectral data is never sent to the chat endpoint
> unless you paste it into a chat message. The `EGRESS_ENABLED=true`
> flag only unlocks the *option* — it doesn't auto-transmit anything.

---

## Step 10 — Your first data analysis

Now you're running. Here's what to do in the browser:

### A. Load example data

1. Click the **Analysis** tab in the sidebar
2. You land on the **Workflow Builder** — a blank canvas
3. From the node library on the left, drag a **Data Source** node onto the canvas
4. Click the node to configure it in the right panel:
   - **Source Type:** `SpectroChemPy Example`
   - **Example Dataset:** `irdata`
   - **Example File:** `nh4y-activation.spg`

### B. Build a preprocessing + PCA pipeline

Drag these additional nodes onto the canvas and connect them left to right:

```
Data Source  →  Smooth  →  PCA
```

- Click **Smooth**: set Window Size = `11`, Polynomial Order = `2`
- Click **PCA**: set Number of Components = `3`

Connect them by dragging from each node's output port (right side) to the next node's input port (left side).

### C. Execute

Click **Execute Workflow** (play button in the toolbar). Watch the nodes turn yellow (processing) then green (done).

Click the **PCA** node — the results panel shows your score plot and explained variance.

### D. Ask the BYO chat assistant (optional)

If you configured a `CHAT_ENDPOINT_*` in Step 9, click the **chat icon**
in the sidebar. Try single-turn questions like:
- "What does a PCA score plot typically show?"
- "When would I choose Savitzky-Golay smoothing over Whittaker?"
- "How do I add a PLS regression with concentration data?"

> The OSS chat assistant is single-turn and has no access to your
> workflow or data. It cannot answer workflow-aware questions such as
> "is my PCA good?" or "what preprocessing should I try for this FTIR
> dataset?".

### E. Export to Python

When you're happy with a workflow, use the **Export** button to generate a Python script, Jupyter notebook, or zip bundle. The exported code requires `spectra-sherpa` to be installed (`pip install spectra-sherpa`) and expects a sibling `data/` folder by default — zip export writes the needed source files there automatically.

---

## Step 11 — Using your own data

1. Go to the **Experiments** page (sidebar)
2. Click **New Experiment**, give it a name (e.g., "FTIR Olive Oil Study")
3. Click **Upload Files** and select your spectral files (`.csv`, `.jdx`, `.spc`, `.spa`, `.opus`, `.mat`, `.txt`)
4. Go back to the **Analysis** tab
5. In your Data Source node, change **Source Type** to `Experiment File`
6. Select your experiment and file from the dropdowns
7. Re-execute the workflow — same pipeline, your data

---

## Quick reference: daily workflow

Once set up, your daily routine is just:

**Windows:**
```
# Open VS Code (or GitHub Desktop → "Open in VS Code")
# Open the terminal (Ctrl+`)
.venv\Scripts\activate
spectra-sherpa
```

**macOS:**
```
# Open VS Code (or GitHub Desktop → "Open in VS Code")
# Open the terminal (Ctrl+`)
source .venv/bin/activate
spectra-sherpa
```

Then work in your browser at `http://localhost:8000`.

---

## Staying up to date

When the SpectraSherpa team releases updates:

1. Open **GitHub Desktop** — it will show available updates for the repo
2. Click **Pull origin** to download the latest code
3. In VS Code terminal (with `.venv` active):
   ```
   pip install -e ".[scp]"
   ```
4. Restart `spectra-sherpa`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found (Windows) | Reinstall Python and check "Add to PATH" |
| `python3` not found (Mac) | Run `brew install python@3.12` |
| `spectra-sherpa` command not found | Make sure `.venv` is activated (you see `(.venv)` in the prompt) |
| Port 8000 already in use | Use `spectra-sherpa --port 9000` or add `KILL_PORT_ON_START=true` to `.env` |
| SpectroChemPy import errors | Make sure you installed with `pip install -e ".[scp]"` not just `pip install -e .` |
| Browser doesn't open | Navigate manually to `http://localhost:8000` |
| BYO chat assistant not appearing | Check that `.env` has `EGRESS_ENABLED=true`, `CHAT_ENDPOINT_URL`, and `CHAT_ENDPOINT_KEY`, then restart |
