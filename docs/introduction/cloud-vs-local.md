# Cloud vs Local OSS

SpectraSherpa is one scientific workbench with two practical entry points. The workflow concepts are shared; account policy, demo limits, and centrally managed AI behavior belong to hosted deployments.

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

| Question | SpectraSherpa Cloud | Local OSS |
| --- | --- | --- |
| Best first use | Fast browser evaluation, managed users, hosted demo workflows | Local data evaluation, source inspection, and offline work |
| Install | None for the user | After 0.6 publication: `pip install "spectra-sherpa==0.6.0"` |
| Data limits | Demo and enterprise policy may limit uploads, runs, or AI use | No hosted demo limits; constrained by your machine and local policy |
| AI setup | Centrally configured by the deployment; demo users do not bring keys | Optional BYO OpenAI-compatible, Anthropic, or Ollama chat provider |
| Extension | User-facing cloud docs only | Full source, exports, configured providers, and tests |

## SpectraSherpa Cloud

Use Cloud when you want a browser-first managed environment with accounts, demo access, centrally configured AI features, and no local Python setup. It is the right first path for an enterprise evaluator who wants to try FTIR, NIR, Raman, or UV-VIS workflows quickly.

The 0.6 hosted trial is available for evaluation with its supplied starter
projects and qualified registered-reference path. The active policy is
documented on the hosted site at
[Demo Access and Limits](https://docs.spectrascientific.ai/cloud/demo-access/).

Cloud documentation is written for users. It explains how to run workflows, understand demo limits, use Advisor and Guidance, and review outputs. It does not teach service development or deployment internals.

!!! note "Hosted feature policy"
    Cloud profiles can differ. The public demo, enterprise trial, and paid enterprise deployment may have different upload limits, AI configuration, retention policy, HITRAN key handling, and sharing behavior.

## Local OSS

Use local OSS when you want to run SpectraSherpa on your own computer, inspect or modify the source, contribute reviewed canonical nodes, or work without a hosted account. The installed application does not load runtime plugins or third-party executable packages.

Local OSS provides:

- local FastAPI/Vue application
- local SQLite-backed app data
- workflow builder and node execution
- core numpy/scipy/scikit-learn chemometrics
- bring-your-own-provider chat configuration for OpenAI-compatible, native Anthropic Messages, or Ollama endpoints
- optional `spectra-sherpa[scp]` support only for EFA, MCR-ALS, and SIMPLISMA through a private matrix adapter
- optional `spectra-sherpa[hitran]` support for HITRAN/HAPI synthesis

Start with [10 Minutes to Local Compute](../onboarding/local-30-minutes.md), then check [Supported File Types](file-types.md) before importing instrument files.

## AI Use and BYOK

SpectraSherpa separates scientific computation from AI assistance. PCA, PLS, SIMCA, KNN, MCR, preprocessing, and most plots run as local scientific application code. Reproducibility depends on the recorded workflow, data, environment, seed, and documented numerical tolerances. LLM features are optional assistance layers around interpretation, writing, workflow guidance, and selected suggestion tasks.

Local OSS can use a bring-your-own-provider chat endpoint configured by environment variables or the app's local BYO Chat settings when enabled. The built-in local transport supports OpenAI-compatible `/chat/completions` APIs (including OpenAI and compatible hosted providers), Anthropic's native Messages API, and Ollama's local OpenAI-compatible endpoint. Select the provider explicitly with `CHAT_ENDPOINT_PROVIDER`; OpenAI-compatible and Anthropic providers require a key, while Ollama does not.

Private and loopback model endpoints are blocked by default. An operator who intentionally runs a trusted local model server can enable them for the configured provider with `CHAT_ENDPOINT_ALLOW_PRIVATE=true`; review the endpoint carefully because this relaxes the SSRF protection for that chat destination. `SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS=1` remains a process-wide compatibility override and is broader than the per-provider setting.

Cloud profiles use deployment-managed LLM access. Hosted Pro does not accept user-supplied LLM keys. Other enterprise deployments may expose a separately qualified BYOK capability only when their profile and operator policy say so. BYOK means your organization also depends on the LLM supplier for model availability, usage limits, pricing, data-handling terms, and service reliability.

## Scientific Caution for AI Output

Treat AI output as a labeled draft or suggestion, not a measurement. LLMs can be plausible and wrong, can miss sample-ID or validation-design problems, can overstate weak evidence, and can change behavior when an upstream provider updates a model.

AI-generated or AI-assisted artifacts in SpectraSherpa are labeled in the product. The main impacted features are:

- Sherpa Advisor chat responses
- Ambient Guidance suggestions
- AI report narratives and data stories
- peak-identification or vibrational-assignment suggestions when enabled
- workflow or code-generation suggestions when enabled

Review AI output against spectra, metadata, file provenance, validation splits, plots, metrics, lab records, and domain knowledge before using it in scientific or customer-facing decisions.
