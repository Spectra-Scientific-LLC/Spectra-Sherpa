# 30 Minutes to Local Compute

Use this path when you want SpectraSherpa running on your own machine. You will install the app, add optional extras only if you need them, run a starter PCA workflow, and then point that workflow at your own data.

## Install

```bash
pip install spectra-sherpa
spectra-sherpa
```

Open the local URL printed in the terminal, usually `http://localhost:8000`. Local OSS needs no account and no cloud connection for normal analysis.

## Add Optional Extras Only If Needed

The base install reads `.csv`, JCAMP-DX (`.jdx`, `.dx`), NumPy (`.npy`, `.npz`), and `.mat`. To read vendor and spectroscopy-native files, add the SpectroChemPy extra:

```bash
pip install "spectra-sherpa[scp]"
spectra-sherpa
```

This unlocks SpectroChemPy-backed readers for Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw WiRE `.wdf`, and vendor `.txt`/`.dat`. Newer Thermo containers such as `.srsx`, `.session`, `.map`, and `.mapx` are not read directly today; export them to `.spa`, `.spg`, or legacy `.srs` first.

For HITRAN line-by-line synthesis, add the HITRAN/HAPI extra:

```bash
pip install "spectra-sherpa[hitran]"
spectra-sherpa
```

You still need a HITRAN API key and egress enabled in application settings. For exact versions and format notes, use [Supported File Types](../introduction/file-types.md).

For Eigenvector Research example datasets, enable the local runtime downloader:

```bash
export SPECTRASHERPA_EIGENVECTOR_DOWNLOADS=true
spectra-sherpa
```

These datasets are highly recommended for learning NIR/OES chemometrics in SpectraSherpa. They include corn instrument-transfer data, diesel NIR calibration data, IDRC shootout data, CGL NIR data, and metal-etch OES/process examples. SpectraSherpa catalogs them but does not redistribute the raw files; downloads come from [Eigenvector Research](https://eigenvector.com/resources/data-sets/) and are cached on your machine.

## Optional: Add a Chat Endpoint for Advisor

Local Advisor is optional. Scientific workflows still run without AI. To enable Advisor, configure a bring-your-own-key, OpenAI-compatible `/chat/completions` endpoint before launching. For OpenAI:

```bash
export CHAT_ENDPOINT_URL="https://api.openai.com/v1"
export CHAT_ENDPOINT_KEY="sk-..."          # your OpenAI key
export CHAT_ENDPOINT_MODEL="gpt-4o-mini"   # any OpenAI chat model
spectra-sherpa
```

`CHAT_ENDPOINT_URL` is the provider base URL, `CHAT_ENDPOINT_KEY` is sent as `Authorization: Bearer <key>`, and `CHAT_ENDPOINT_MODEL` selects the model. Some builds also expose local BYO Chat settings in the app. Review [AI Use and BYOK](../introduction/cloud-vs-local.md#ai-use-and-byok) before relying on AI-assisted text.

## Run an Example PCA with New Analysis

Open **New Analysis** and choose a **PCA** starter. If you choose an Eigenvector-backed starter, keep `SPECTRASHERPA_EIGENVECTOR_DOWNLOADS=true` enabled for the first run so the upstream example files can be cached locally. Review the scores, loadings, explained variance, and Node Detail view.

!!! tip "Ask Advisor along the way"
    With a chat endpoint configured, Advisor can answer questions at any step: "What does this score plot suggest?", "Which preprocessing should I try next?", "Are these samples outliers?". Use it as an interpretation aid, not a replacement for scientific judgment.

## Import Your Data into My Dataset

Open **Data > Upload** and add a small representative file. Confirm **Files**, **Metadata**, and **Data Matrix**: file names, extensions, spectral axis, sample count, and target metadata. Then save it into **My Dataset** so a workflow can use it. See [Import Your First Dataset](import-first-dataset.md) for the checklist.

## Build a PCA for Your Own Data

Duplicate the example PCA sheet, open its data node, and select your **My Dataset** entry as the input. Run it. You now have the same PCA workflow pointed at your data. Adjust preprocessing and components as needed, and use the Node Detail view to review the result.

## Report or Extend

Open **Report** for a shareable record of the run, or export figures, tables, workflows, and generated Python where available. Developers can continue with [Developer Setup](../developers/setup.md), [Writing a Plugin Node](../developers/plugin-node.md), or [Export Design](../architecture/export.md).
