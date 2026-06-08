# License

The open-source SpectraSherpa package is licensed under **AGPLv3.0**. In plain language, SpectraSherpa OSS is free open-source software: you can download it, run it, study the source, modify it, and share it under the license terms.

This page is a practical orientation, not legal advice. For binding language, read the official [GNU AGPLv3.0 license text](https://www.gnu.org/licenses/agpl-3.0.html).

## What You Can Do

Under AGPLv3.0, you can generally:

- run SpectraSherpa OSS for your own research, teaching, or internal evaluation
- inspect and modify the source code
- build plugins or local extensions
- redistribute the software under AGPLv3.0 terms
- publish analyses produced with SpectraSherpa, subject to the licenses and citation expectations of any scientific data or third-party tools you used

## What You Need To Be Careful About

AGPLv3.0 matters because SpectraSherpa is a network-capable application. If you modify the OSS application and let other users interact with that modified version over a network, AGPLv3.0 generally requires that those users can receive the corresponding source code for your modified version.

You generally should not:

- remove copyright, license, citation, or attribution notices
- redistribute modified SpectraSherpa code under a closed-source license
- run a modified network service for users while hiding the corresponding source
- treat NIST, HITRAN, SpectroChemPy, or other third-party resources as owned by SpectraSherpa
- assume SpectraSherpa Cloud service terms are the same thing as the OSS license

## Optional Dependencies

SpectroChemPy is intentionally optional. Install it with:

```bash
pip install "spectra-sherpa[scp]"
```

The optional design keeps the base package smaller and preserves a clear license boundary. The docs should describe what the extra enables, but the OSS package must not require SpectroChemPy as a core dependency.

SpectroChemPy has its own license and citation expectations. The current supported range is [SpectroChemPy](https://www.spectrochempy.fr/) `>=0.8.1,<0.9.0`, with the lockfile pinned to [0.8.1](https://www.spectrochempy.fr/0.8.1/). If your analysis depends on SpectroChemPy readers, algorithms, or datasets, consult the current SpectroChemPy project documentation and cite it appropriately.

HITRAN/HAPI support is also optional:

```bash
pip install "spectra-sherpa[hitran]"
```

HITRAN live synthesis requires a HITRAN API key. The current supported ranges are [hitran-api](https://pypi.org/project/hitran-api/) `>=1.3.0.0,<2` and [hitran-api2](https://pypi.org/project/hitran-api2/) `>=0.2.2,<1`. Users are responsible for obtaining their own key, following HITRAN terms, and citing the database release and source data used in the analysis. HITRAN publishes current citation guidance on its [citation policy page](https://hitran.org/citepolicy/).

NIST reference data also carries scientific citation expectations. See [Attributions](../attributions/index.md).

## LLM Providers and BYOK

Bring-your-own-key access means you are using an account with an external LLM supplier. That supplier controls API key issuance, model availability, pricing, rate limits, usage policies, data-handling terms, and outages.

For example:

- **Claude / Anthropic**: create an [Anthropic Console](https://console.anthropic.com/) account, configure billing or credits as required by Anthropic, create an API key in the Console, and keep the key private. Anthropic's help center describes the Console as the place to create API keys, manage users, set up billing, and test Claude.
- **OpenAI**: create and manage API keys from OpenAI's [API key page](https://platform.openai.com/api-keys). OpenAI recommends loading keys securely from environment variables or key-management services rather than embedding them in code.

Do not commit API keys to Git, paste them into shared screenshots, or place them in documentation examples. Rotate a key immediately if it may have been exposed.

## Hosted Service

SpectraSherpa Cloud is a hosted enterprise/demo service built around the SpectraSherpa platform. Cloud documentation describes user-facing service behavior. It is not a substitute for the OSS license, service terms, or any legal agreement with Spectra Scientific.
