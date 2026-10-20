# Local OSS and hosted-product boundaries

Local OSS runs on your computer without a hosted account. It includes the
scientific Workbench, Python SDK, local projects, workflows, saved results and
supported exports. Its limits are your installed capabilities, machine resources
and the scientific input contracts—not a hosted demo allowance.

Managed Demo/Pro services are separate offerings. Managed Advisor, hosted
Optimize campaigns, accounts and service usage policies are not supplied by
the OSS package. Consult the hosted service for its current terms and limits;
this manual describes local OSS use.

## Local OSS

Start with [Local onboarding](../onboarding/local-30-minutes.md).
Core analysis works without AI or a cloud connection. Reference acquisition and
remote chat are optional, explicitly configured network operations. Provider
datasets must be acquired under their own terms.

A supported model/package obtained elsewhere may be inspected or applied
locally after its normal compatibility checks. Importing it does not install
the hosted optimization service.

## AI Use and BYOK

Local chat supports OpenAI-compatible endpoints, Anthropic Messages and Ollama.
Select the transport with `CHAT_ENDPOINT_PROVIDER`, then configure the endpoint,
model and required key. The provider's availability, charges and data-handling
terms apply. See [Scientific assistance](../onboarding/scientific-assistance.md).

Private/loopback endpoints are blocked by default. For an intentionally trusted
local model server, `CHAT_ENDPOINT_ALLOW_PRIVATE=true` enables the configured
provider's private destination. It relaxes that destination's network protection;
do not enable it for an untrusted endpoint. The process-wide compatibility
override `SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS=1` is broader.

## Scientific Caution for AI Output

Treat chat text as a draft interpretation, not a measurement. Supply the
observations you want reviewed; do not assume basic chat has inspected a fitted
model or every project artifact. Verify numerical claims, sample populations,
units and validation design against saved results.

See the [privacy statement](../support/privacy.md) for the information sent by
each explicitly enabled feature. An unavailable chat provider does not prevent
local scientific computation.
