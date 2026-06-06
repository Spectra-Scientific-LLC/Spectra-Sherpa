# Cloud vs Local OSS

SpectraSherpa is one scientific workbench with two practical entry points. The workflow concepts are shared; account policy, demo limits, and centrally managed AI behavior belong to hosted deployments.

| Question | SpectraSherpa Cloud | Local OSS |
| --- | --- | --- |
| Best first use | Fast browser evaluation, managed users, hosted demo workflows | Local data evaluation, source inspection, plugin development |
| Install | None for the user | `pip install spectra-sherpa` |
| Data limits | Demo and enterprise policy may limit uploads, runs, or AI use | No hosted demo limits; constrained by your machine and local policy |
| AI setup | Centrally configured by the deployment; demo users do not bring keys | Optional bring-your-own-key OpenAI-compatible chat endpoint |
| Extension | User-facing cloud docs only | Full source, node plugins, exports, providers, and tests |

## SpectraSherpa Cloud

Use Cloud when you want a browser-first managed environment with accounts, demo access, centrally configured AI features, and no local Python setup. It is the right first path for an enterprise evaluator who wants to try FTIR, NIR, Raman, or UV-VIS workflows quickly.

The public demo is free to try at [demo.spectrascientific.ai](https://demo.spectrascientific.ai). Create an account with access code `welcome_to_spectra_sherpa`. Public demo policy is documented on the hosted site at [Demo Access and Limits](https://docs.spectrascientific.ai/cloud/demo-access/).

Cloud documentation is written for users. It explains how to run workflows, understand demo limits, use Advisor and Guidance, and review outputs. It does not teach service development or deployment internals.

!!! note "Hosted feature policy"
    Cloud profiles can differ. The public demo, enterprise trial, and paid enterprise deployment may have different upload limits, AI configuration, retention policy, HITRAN key handling, and sharing behavior.

## Local OSS

Use local OSS when you want to run SpectraSherpa on your own computer, inspect or modify the source, build plugins, or work without a hosted account.

Local OSS provides:

- local FastAPI/Vue application
- local SQLite-backed app data
- workflow builder and node execution
- core numpy/scipy/scikit-learn chemometrics
- bring-your-own-key chat configuration through an OpenAI-compatible chat endpoint
- optional `spectra-sherpa[scp]` support for SpectroChemPy-backed readers and nodes
- optional `spectra-sherpa[hitran]` support for HITRAN/HAPI synthesis

Start with [30 Minutes to Local Compute](../onboarding/local-30-minutes.md), then check [Supported File Types](file-types.md) before importing instrument files.

## AI Use and BYOK

SpectraSherpa separates scientific computation from AI assistance. PCA, PLS, SIMCA, KNN, MCR, preprocessing, and most plots run as deterministic application code. LLM features are optional assistance layers around interpretation, writing, workflow guidance, and selected suggestion tasks.

Local OSS can use a bring-your-own-key chat endpoint configured by environment variables or the app's local BYO Chat settings when enabled. The built-in local chat path expects an OpenAI-compatible `/chat/completions` endpoint, which can be supplied by OpenAI, compatible hosted providers, or a local server that implements the same API shape. Anthropic/Claude access depends on the configured deployment path: Cloud deployments can be centrally configured for Claude, while local deployments need an OpenAI-compatible bridge or another operator-supported provider path.

Cloud can be configured by Spectra Scientific for managed LLM access, BYOK access, or both, depending on the enterprise/demo profile. BYOK means your organization is also depending on the LLM supplier for model availability, usage limits, pricing, data-handling terms, and service reliability.

## Scientific Caution for AI Output

Treat AI output as a labeled draft or suggestion, not a measurement. LLMs can be plausible and wrong, can miss sample-ID or validation-design problems, can overstate weak evidence, and can change behavior when an upstream provider updates a model.

AI-generated or AI-assisted artifacts in SpectraSherpa are labeled in the product. The main impacted features are:

- Sherpa Advisor chat responses
- Ambient Guidance suggestions
- AI report narratives and data stories
- peak-identification or vibrational-assignment suggestions when enabled
- workflow or code-generation suggestions when enabled

Review AI output against spectra, metadata, file provenance, validation splits, plots, metrics, lab records, and domain knowledge before using it in scientific or customer-facing decisions.
