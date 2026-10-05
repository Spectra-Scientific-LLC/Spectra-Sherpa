# SDK Validation Contract

The SDK exposes metric definitions, split-plan identities, uncertainty
records, canonical evidence readers, and managed-confirmation verification.
It does **not** accept an arbitrary estimator and does not own a second
cross-validation engine. Fitting and fold-local validation run through typed
canonical DAG nodes and the canonical fold-lifecycle executor.

## Metric authority

```python
import spectra_sherpa.sdk as ss

metrics = ss.validate.regression_metrics(observed, predicted)
print(metrics.as_dict())
```

Regression metric registry version 2 defines RMSE, MAE, positive
prediction bias, R², SEP, ordinary least-squares slope and intercept of
predicted values on observed values, RER, sample count, tolerances, and
explicit undefined cases. SEP is the sample standard deviation of residuals
after removing their mean bias. RER is the observed reference range divided
by SEP and is explicitly undefined when SEP is zero or unavailable. These
values are never averaged across multiple response variables: PLS2 evaluation
reports one complete metric set per named response. Classification metrics
use their separately versioned registry, require a closed label set, and never
guess the scientifically positive class.

Metric functions describe supplied observations and predictions. They do not
prove those predictions came from held-out rows. That claim requires a
canonical validation graph whose split and fold lifecycle are bound in the
execution evidence.

## Split-plan and uncertainty records

Use the current split-plan constructors in `ss.validate` to bind the exact
fold membership, groups, and seed used by a canonical validation graph.
Uncertainty summaries are derived from completed fold records. They are not a
substitute for carrying the fold-level evidence from which they were computed.

## Evidence statements stay separate

Current canonical reproduction reports distinguish:

1. package integrity,
2. publisher authentication,
3. validation reproduction, and
4. fitted-model application reproduction.

Do not collapse these into a generic `verified` flag. A signature authenticates
the publisher's content root; OSS reproduction recomputes scientific results.
Neither statement implies the other.

See [Canonical Workflows from Python](../onboarding/python-canonical-workflows.md)
for the exact export and reproduction commands, and [Executable Workflow
Capsules](workflow-capsule.md) for the closed execution/evidence identities.

## Removed prototype APIs

The current SDK has no arbitrary-estimator `cross_validate`, nested-CV helper,
cross-validation report object, or local `ConfirmationQuarantine`. Those APIs
could execute science outside the canonical registry and gave a local Python
object a governance meaning it could not enforce. Use canonical validation
nodes for local science and managed confirmation authorities for governed
confirmation.

## v0.6.0 evidence utilities

The public SDK exposes contract and evidence helpers around the canonical
execution path:

- `spectra_sherpa.sdk.validation_independence` records specimen/batch
  populations and classifies evidence as recorded-list comparison, operator
  declaration, or unknown. It does not authenticate an external register or
  prove sampling independence.
- `spectra_sherpa.sdk.validation_reporting` supplies the shared metric and
  claim-limit vocabulary used by saved-run and campaign reports.
- `spectra_sherpa.sdk.analytical_qualification` binds a frozen application,
  policy, intended-use context, validation evidence and explicit decision into
  a qualification dossier. Loading a JSON dossier verifies integrity; it does
  not restore server-computed provenance or promote imported data to an
  accepted decision.

These modules are deliberately evidence and contract surfaces, not a second
estimator engine. Fitting, fold-local preprocessing, nested tuning and
prediction remain owned by typed canonical DAG nodes and the canonical fold
lifecycle executor.

## Numerical invariance and retained evidence

[Computational boundary obligations](scientific-result-surface-contract.md#computational-boundary-obligations)
apply to all metric producers, not only SDK callers. A shared affine unit change
`y' = a*y + b` applied to both observations and predictions preserves validity,
R² and slope. RMSE scales by `abs(a)`, bias by `a`, and the fitted intercept becomes
`a*intercept + b*(1-slope)`. These rules assume nonzero `a`, representable values
and a nonconstant response. Direct and pooled metrics must agree for the same
paired observations/predictions; changing which models are fitted in CV folds is
not such a repartition and need not preserve the predictions.

Unsupported historical mixed-response aggregates remain original evidence, marked
unsuitable for current scientific comparison or qualification. Do not rewrite
historical results under a newer metric definition. Individual prediction intervals
need their own model/sample-bound method and assumptions; aggregate bootstrap
intervals cannot substitute for them.
