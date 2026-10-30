# Scientific assistance during an analysis

!!! abstract "Summary"
    What the optional AI assistant does and does not do: workflows calculate
    results from your data; the assistant helps you interpret them. In Local OSS
    it is basic chat through a provider you configure. Its suggestions are
    advisory; check them against your measurements.

Scientific calculations and AI assistance have different roles. Workflows
calculate results from your data and recorded settings. Sherpa helps you ask
questions, interpret those results and decide what to examine next. Review its
suggestions against the measurements and your experimental design.

## Local basic chat

In local OSS, configure your own provider in Settings, then ask a question.
OpenAI-compatible providers, Anthropic and Ollama are supported. This is basic
scientific chat: include the observations or values you want to discuss in your
question. Do not assume the assistant has inspected your spectra or fitted model.
The provider receives the information you send; its data-handling terms apply.
If the provider is unavailable, scientific analysis still works.

Open **Logs → Local AI exchanges** to inspect a basic chat request, the actual
instructions sent, the provider's response and any reported token usage. Save
an individual redacted exchange when troubleshooting. Failed or interrupted
responses are labelled; a truncated record is not the complete exchange.
History is kept only in this backend session, up to 20 requests, and can be
cleared. It is not uploaded or restored after restarting. Saved copies may
contain scientific information you typed, so share them deliberately.

## Optional Data Story

When you explicitly request a local Data Story, the configured provider receives
a bounded summary of the parsed dataset and your supplied context. This differs
from typing a basic chat message; review [privacy](../support/privacy.md) before
sharing scientific metadata. The generated narrative does not replace the data
table or its recorded units.

For a source package such as Corn or Metal Etch, Data Story inspects every source
view separately. The story can describe different instruments, feature spaces and
acquisition settings without concatenating their matrices. Row counts stay per view:
multiple views can measure the same specimens, so their counts are not a total
number of independent samples. The selected modeling view remains unchanged.

Generate is enabled only when the complete source inspection is available. A partial
plot preview is not enough. The inspected source summary survives navigation within
the same account and project; changes to the source inventory invalidate it.
Generation remains on demand, with bounded metadata and explicit omissions when
secondary details do not fit the input limit.

Managed project-aware Advisor is a separate hosted feature, not local basic chat.

## Ask a question tied to the evidence

Prefer “What could explain this residual pattern in the held-out samples?” to
“Is my model good?” Identify the selected result if several runs are open.
If the response refers to a different run or missing information, correct it
before proceeding. A plausible explanation is a hypothesis to investigate.

## Prompt patterns by experience

### For senior chemometrics users

State the claim boundary you want reviewed: calibration, cross-validation,
held-out, external, or application. Include the target units, grouping or
split design, preprocessing fit scope and the decision you are considering.
Ask for competing explanations and discriminating checks, not only a preferred
method. For example:

> Compare these two preprocessing pipelines using the cross-validation
> evidence I supplied. Report which population each metric uses, whether preprocessing was
> fitted inside the folds, and what residual or sample-group check should decide
> between them. Do not infer external validity.

### For junior users

Ask the assistant to identify the object before asking for advice:

- “What does this node take as input and produce as output?”
- “Which samples and units are represented in this plot?”
- “What should I inspect before I interpret this calibration result?”
- “Explain calibration error versus cross-validation error in this report.”

Then verify the answer against the node detail, data table, saved run and
validation design. AI can help translate a result; it cannot supply missing
metadata, choose a defensible claim boundary, or certify a method.

For local versus managed availability, see
[Local OSS and hosted boundaries](../introduction/cloud-vs-local.md). For experimental design,
see [Validation and Model Application](../chemometrics/validation-application.md).
