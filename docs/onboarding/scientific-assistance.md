# Scientific assistance during an analysis

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

## Project-aware assistance in Demo and Pro

Managed Sherpa Advisor can use relevant, permitted project work and the active
window or plot to help with an ongoing analysis. This reduces how much you need
to repeat when moving from data review to workflow design, model evaluation and
reporting. Keep the relevant project and result open when asking for help.

State corrections explicitly. For example: “The band I called an analyte signal
is an interference; use that correction when discussing this model.” Ask Sherpa
to restate the corrected interpretation and check that it has done so before
using the next suggestion. Project continuity is assistance, not proof that
every earlier statement is correct or that every correction changed a saved
workflow. Saved parameters and results change only through their normal editing
and execution steps.

### Example: from spectra to model review

1. Inspect spectra and sample metadata. Identify the region or observations you
   want to discuss; include axis units in your question.
2. Record your interpretation and explicitly correct it if later evidence
   changes it. Check the response reflects the correction.
3. When discussing a workflow, ask why each preprocessing step is appropriate
   for your measurement and target. Review a proposed draft before running it.
4. Open the resulting validation plot and ask about its held-out population,
   residuals and limitations. Check the answer against the saved result.
5. When drafting a report, ask Sherpa to distinguish measurements, your
   interpretation and unresolved questions. Verify all numerical claims.

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

> Compare the two preprocessing pipelines using the retained cross-validation
> evidence. Report which population each metric uses, whether preprocessing was
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
[Cloud vs Local OSS](../introduction/cloud-vs-local.md). For experimental design,
see [Validation and Model Application](../chemometrics/validation-application.md).
