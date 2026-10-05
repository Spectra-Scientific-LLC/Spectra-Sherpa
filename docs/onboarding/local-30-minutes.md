# 10 Minutes to Local Compute

Use this path when you want SpectraSherpa running on your own machine. You will install the app, add optional extras only if you need them, run a starter PCA workflow, and then point that workflow at your own data.

## Install

!!! warning "0.6.0 release lifecycle"
    Install 0.6.0 from PyPI only after the public index reports that exact
    version. Before the public tag exists, use only the exact monorepo commit
    named by the qualification record. After the tag exists but before PyPI
    reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source tag. Source
    version text alone is not publication evidence.

### Choose optional capabilities up front

Pip itself does not ask interactive feature questions. The supported
`scripts/install_local.py` helper in the source checkout asks about **SpectroChemPy
(EFA, MCR-ALS, SIMPLISMA)**, **HITRAN/HAPI2**, and **NIST** before starting pip.
Each is optional and defaults to no. Run it with Python 3.11 or 3.12 in the
virtual environment where you will run SpectraSherpa.

For an exact qualification checkout, from its monorepo root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
npm --prefix packages/spectra-sherpa/frontend ci
npm --prefix packages/spectra-sherpa/frontend run build  # Node.js 22
python packages/spectra-sherpa/scripts/install_local.py --source packages/spectra-sherpa
spectra-sherpa
```

`--source` installs that local package directory, including the frontend you
just built; it does not fetch the candidate from PyPI. Pin the checkout to the
qualification record's commit first. A Git source checkout or GitHub source
archive needs the frontend build; release wheels and prepared Python source
distributions include the built Workbench. A GitHub source archive is not the
same artifact as a Python source distribution (`sdist`).

Use the same helper with `--wheel /absolute/path/to/spectra_sherpa-0.6.0-py3-none-any.whl`
for an exact wheel, or `--version 0.6.0` only after that version is published on
your pip index. These targets are mutually exclusive. The helper is a source
checkout script, not a command installed by the wheel. Add `--extras scp,hitran,nist`
or `--base` for automation without prompts, and `--dry-run` to inspect the command.
It invokes the same Python's pip and propagates installation failures.

Optional dependencies retain their upstream licenses. HITRAN still requires
your own API key in Settings > API Keys and enabled HITRAN/HAPI Queries in
Settings > Integrations; installing its client does not grant database access.
These Python environment choices do not modify a frozen desktop installer.

### Direct installation

After the public index reports 0.6.0:

```bash
python -m pip install "spectra-sherpa==0.6.0"
spectra-sherpa
```

For direct pip installation, choose extras in that first command, for example
`python -m pip install "spectra-sherpa[scp,hitran,nist]==0.6.0"` after publication.
For a local wheel use `python -m pip install "/absolute/path/to/package.whl[scp,hitran]"`;
for a prepared source directory use `python -m pip install "./packages/spectra-sherpa[scp,hitran]"`
from the monorepo root. Extras are optional dependencies, not separate wheels.

For a pre-publication qualification candidate, begin inside the exact checkout
named by the qualification record. Choose all desired extras up front in one
install command; the example selects SCP, HITRAN/HAPI2, and NIST:

```bash
cd packages/spectra-sherpa
python -m pip install poetry
poetry env use python3.11
poetry install --extras "scp hitran nist"  # choose the extras you want
# Base-only alternative: poetry install
npm --prefix frontend ci          # requires Node.js 22
npm --prefix frontend run build
poetry run spectra-sherpa
```

Open the local URL printed in the terminal, usually `http://localhost:8000`. Local OSS needs no account and no cloud connection for normal analysis.

If the port is occupied, startup stops and leaves the existing service running.
Choose another port with `spectra-sherpa --port 8001`, or stop the service you
own before retrying. Startup never terminates a process discovered on a port.
The old `KILL_PORT_ON_START`, `KILL_PORT_FORCE`, and `KILL_PORT_GRACE_SECONDS`
settings no longer enable process termination; remove them from older `.env`
files. Desktop launches retain their ephemeral-port behavior.

## Add Optional Extras Only If Needed

Include **all extras you want to keep** in every `poetry install` invocation:
Poetry can remove previously installed extras that are omitted. The commands
below illustrate individual choices, not cumulative installation steps. For
example, to retain SCP while adding HITRAN and NIST, use one command:
`poetry install --extras "scp hitran nist"`. Use `poetry install` alone only
when you want the base installation without optional extras.

The base install reads `.csv`, JCAMP-DX (`.jdx`, `.dx`, `.jcamp`), NumPy (`.npy`, `.npz`), MATLAB v4/v5 and v7.3/HDF5 `.mat`, and the qualified Eigenvector PLS_Toolbox DSO contract. Add the SpectroChemPy extra only when you need EFA, MCR-ALS, or SIMPLISMA:

```bash
poetry install --extras "scp"
poetry run spectra-sherpa
```

Installing this extra does not add file readers. One-dimensional Bruker OPUS, qualified Galactic SPC, qualified legacy Thermo OMNIC SPA/SPG/SRS, and qualified Renishaw WiRE WDF are read natively. Thermo Paradigm/OMNICxi containers still require export to an admitted open format. The Workbench reports the same remediation before upload.

For HITRAN line-by-line synthesis, add the HITRAN/HAPI extra:

```bash
poetry install --extras "hitran"
poetry run spectra-sherpa
```

You still need a HITRAN API key and egress enabled in application settings. For exact versions and format notes, use [Supported File Types](../introduction/file-types.md).

For live NIST WebBook search and acquisition, add the independent NIST extra:

```bash
poetry install --extras "nist"
poetry run spectra-sherpa
```

Reference spectra already acquired into the managed local catalog remain
usable without this extra. The extra grants acquisition support; it does not
own the stored scientific data.

For a registered Eigenvector Research example, open **Data > My Dataset >
Reference Datasets**. Use **Browse all Eigenvector datasets** so your browser
opens the provider's complete catalog. Download there, then choose **Import
downloaded file**.
SpectraSherpa verifies the registered size and SHA-256 before using the local
copy. The same native readers accept ordinary supported files through the
normal local upload path without a registry match.

## Optional: Add a Chat Endpoint for Local AI Chat

Local AI chat is optional. Scientific workflows still run without AI. To enable
it, configure a bring-your-own-provider endpoint before launching. Local chat
does not automatically inspect the active workflow or saved results; include the
observations and context you want reviewed. The local transport supports
OpenAI-compatible `/chat/completions` APIs, Anthropic's native Messages API,
and Ollama. For OpenAI:

```bash
export CHAT_ENDPOINT_PROVIDER="openai_compatible"
export CHAT_ENDPOINT_URL="https://api.openai.com/v1"
export CHAT_ENDPOINT_KEY="sk-..."          # your OpenAI key
export CHAT_ENDPOINT_MODEL="gpt-4o-mini"   # any OpenAI chat model
poetry run spectra-sherpa
```

`CHAT_ENDPOINT_PROVIDER` selects the transport, `CHAT_ENDPOINT_URL` is its base URL, and `CHAT_ENDPOINT_MODEL` selects the model. `CHAT_ENDPOINT_KEY` is required for OpenAI-compatible and Anthropic providers but not Ollama. For an Ollama loopback URL, set `CHAT_ENDPOINT_ALLOW_PRIVATE=true` explicitly. Some builds also expose local BYO Chat settings in the app. Review [AI Use and BYOK](../introduction/cloud-vs-local.md#ai-use-and-byok) before relying on AI-assisted text.

## Run an Example PCA with New Analysis

Open **New Analysis** and choose a **PCA** starter. For an Eigenvector-backed
starter, first admit the independently downloaded file through **Reference
Datasets**, then choose **Use My Dataset**. Review the scores, loadings,
explained variance, and Node Detail view.

!!! tip "Ask local AI chat along the way"
    With a chat endpoint configured, ask: "What does this score plot suggest?",
    "Which preprocessing should I compare next?", or "What checks should I
    make before calling these samples outliers?" Include the plot values or
    report excerpt you want reviewed. Use the response as an interpretation aid,
    not a replacement for scientific judgment.

## Import Your Data into My Dataset

Open **Data > Upload** and add a small representative file. Confirm **Files**, **Metadata**, and **Data Matrix**: file names, extensions, spectral axis, sample count, and target metadata. Then save it into **My Dataset** so a workflow can use it. See [Import Your First Dataset](import-first-dataset.md) for the checklist.

## Build a PCA for Your Own Data

Duplicate the example PCA sheet, open its data node, and select your **My Dataset** entry as the input. Run it. You now have the same PCA workflow pointed at your data. Adjust preprocessing and components as needed, and use the Node Detail view to review the result.

## Report or Extend

Open **Report** for a shareable record of the run, or export figures, tables, workflows, and generated Python where available. Developers can continue with [Developer Setup](../developers/setup.md), [Contributing](../developers/contributing.md), or [Export Design](../architecture/export.md).
