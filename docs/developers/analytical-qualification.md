# Analytical qualification evidence

A deploy-ready application is operationally usable. It is not thereby validated
for a laboratory's intended use. Qualification records keep three authorities
separate: computed validation evidence, operator declarations, and an explicit
human decision. No ASTM or regulatory compliance is asserted.

## Supported path

In **Runs → Analytical qualification of imported applications**, select the
exact imported canonical application. The same panel appears for a selected
local Deploy application. These records are available independently of
folder-watch entitlement. Execution currently supports a frozen canonical PLS
application; legacy saved models retain their existing execution behavior and
do not acquire a qualification claim.

1. Freeze the model, acceptance policy and intended-use context before examining
   validation outcomes. Choose laboratory limits appropriate to that use.
2. Select a separate validation dataset and file with explicit specimen IDs,
   response identities and units. Each row must represent one independent
   specimen. Retain sampling and domain-coverage evidence outside the software.
3. Supply the policy and context below, adapted and approved by your laboratory.
   An optional interval record must describe the same reference method and
   population. Its calibration specimens must be separate from validation.
4. Execute the frozen application. Inspect every criterion, original population,
   exclusions, per-response statistics, screening availability and interval
   coverage. Missing evidence is reported; it is not silently filled.
5. Review the exact dossier, acknowledge its assumptions and record a reason.
   Only a server-computed `criteria_met` assessment can be accepted under its
   declared policy. An incomplete or failed assessment can be left pending or
   rejected. No automatic acceptance occurs.
6. Export the complete history. Reopening preserves each original policy,
   assessment and decision. Reassessment appends evidence rather than replacing
   an earlier result. Exported actor identities and decisions are historical
   assertions, not authenticated certification on another installation.

### Example policy — illustrative limits, not recommendations

These arbitrary limits demonstrate the schema. They are not E1655 thresholds,
scientific recommendations, or a policy to copy into production without review.

```json
{
  "schema_version": "spectrasherpa.declared-qualification-policy/1",
  "policy_name": "Example laboratory response policy",
  "policy_version": "1",
  "minimum_independent_specimens": 30,
  "minimum_specimens_per_component": 5,
  "response_identity": {"names": ["concentration"], "units": ["mass%"]},
  "responses": [{
    "max_rmsep": 0.5,
    "max_absolute_bias": 0.2,
    "intended_minimum": 1,
    "intended_maximum": 10
  }],
  "require_reference_precision": false,
  "minimum_screening_available_fraction": 1,
  "minimum_interval_available_fraction": null,
  "minimum_observed_interval_coverage": null,
  "bias_confidence_level": 0.95,
  "bootstrap_resamples": 2000,
  "random_seed": 928
}
```

### Example context

Use the actual instrument identity and SHA-256 digests of the retained
acquisition configuration and domain-coverage evidence. The repeated characters
below are placeholders, not evidence. The declaration booleans must be true only
when supported by the laboratory's records. Missing instrument or coverage
information produces an incomplete assessment.

```json
{
  "intended_use": "Example concentration measurement",
  "intended_population": "Declared specimen population and operating conditions",
  "specimen_namespace": "laboratory-specimen-register",
  "reference_method": {
    "method_id": "laboratory-reference-method",
    "version": "1",
    "response_identity": {"names": ["concentration"], "units": ["mass%"]},
    "measurement_basis": "single_measurement",
    "measurements_per_label": 1,
    "precision": null
  },
  "instrument_id": "instrument-serial",
  "acquisition_configuration_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "domain_coverage_evidence_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "policy_frozen_before_validation": true,
  "model_frozen_before_validation": true,
  "specimens_not_used_for_fit_selection_or_interval_calibration": true,
  "independent_specimen_sampling_declared": true,
  "sampling_design": "Describe independently selected validation specimens",
  "evaluation_role": "external_validation"
}
```

## Interpretation and refusal

- Bias acceptance requires the **entire** declared percentile-bootstrap interval
  to lie inside the practical bias tolerance. An interval containing zero alone
  is insufficient. The seed, confidence level and resample count are retained.
- Specimens per fitted component is a declared policy heuristic, not statistical
  degrees of freedom. Minimum specimen counts do not establish independence.
- Observed response minima/maxima are extrema only. They do not prove coverage
  throughout the multivariate domain; separate coverage evidence is required.
- Interval availability and empirical coverage are separate. Coverage among rows
  receiving intervals does not establish coverage for the entire population.
- Optional explicit missing-reference exclusion retains original row indices,
  specimen IDs, missing response columns, reason and original cohort digest.
  Nonfinite predictors and infinite references are refused, not excluded.
- Missing units, instrument evidence, domain evidence, or required reference
  precision cannot produce an accepted assessment. Unknown response names remain
  explicitly unknown; predictor units are never substituted for response units.
- Calibration, cross-validation and surrogate evidence cannot pass the independent
  validation criterion. Declarations cannot prove laboratory independence.
- Changing the model, application plan, reference method, population or instrument
  context requires reassessment. A historical acceptance is not a current-use
  certificate. The SDK's `assert_application` checks this binding explicitly.
- Bootstrap work above 20,000,000 response-row resamples is explicitly refused.
  The system never silently reduces resampling or truncates the population.
  Computation runs outside the request event loop; cancellation cannot forcibly
  stop an already running Python worker thread.

## Developer contract

`qualify_application` executes the verified application with runtime custody,
then assesses its retained predictions. `QualificationDossier.load` verifies
integrity but does not restore server-computed provenance. Imported JSON cannot
be promoted to an accepted decision; re-execute it through the server-owned
assessment path. The API has no assessment-import write route. Owner and workflow
scope are required on history and decisions, including identical scientific
records used in different workflows.

`render_qualification_report` produces a self-contained Markdown report. The GUI
exports JSON containing the entire assessment and decision history. Both preserve
limitations. Retained policy versions and human decisions remain immutable
through these APIs; deleting the owning application/project deletes its history
under the normal deletion policy, so export records needed for external retention.

Test dissimilar cases: valid independent validation, inadequate or biased data,
missing references, missing units/instrument/domain evidence, surrogate cohorts,
interval/reference mismatch, altered context or model, forged imported provenance,
cross-owner access, duplicate science in separate workflows, and save/reopen/export.
Tests must verify populations, denominators, effective parameters and claim scope,
not merely chart rendering. Operational execution remains available without a
qualification claim.

## Recorded independence evidence

Qualification accepts optional `independence_evidence` through the SDK, API and
qualification panel. It is retained in the existing dossier calculation and
history export; older dossiers keep their original schema and digest.

```json
{
  "schema_version": "spectrasherpa.recorded-independence/1",
  "populations": [{
    "role": "fit",
    "namespace": "laboratory-specimen-register-v1",
    "specimen_ids": ["calibration-001", "calibration-002"],
    "batch_ids": ["batch-a", "batch-b"],
    "source_description": "Calibration register for the frozen model"
  }],
  "validation_batches": {"validation-001": "batch-c", "validation-002": "batch-d"},
  "model_frozen_at": "2026-01-01T12:00:00Z",
  "policy_frozen_at": "2026-01-01T12:00:00Z",
  "validation_acquired_from": "2026-02-01T12:00:00Z",
  "chronology_source": "Laboratory acquisition and approval register"
}
```

Use roles `fit`, `selection`, and `interval_calibration` for the populations that
actually exist. The namespace must match the qualification context for identity
comparison. Differing namespaces are unknown, not proof of separation. Batch
maps use specimen IDs so exclusions cannot shift their row association.

`compared_against_recorded_lists` means the software compared the supplied recorded IDs in a
matching namespace. It does not authenticate the operator-supplied register or
prove it complete. The dossier lists verified and unverified roles separately.
Known specimen or batch overlap cannot satisfy the recorded-separation criterion.
No records yields `operator_declared` or `unknown`, depending on the existing
explicit declaration. Sampling independence and entered timestamps remain
operator declarations; they never inherit recorded-comparison status from ID equality.
Chronology relative to acquisition is reported, not used as an automatic refusal:
a legitimately independent sealed dataset may predate model freezing.

## Reporting existing evidence

Saved-run HTML and Markdown exports contain summaries by default. Explicit opt-in adds figures and their underlying reference, prediction and residual values
built from exact retained out-of-fold evidence. Consent resets when changing workflows; export consent does not authorize disclosure of these figures to AI. Axis units use retained upstream target authority, with an explicit unavailable notice when missing or ambiguous. Each repeat has its own panel,
seed and denominator. Plots include predictions versus reference and residuals
(prediction minus reference); formulas and undefined cases are reported alongside
metrics. Oversized plots are explicitly unavailable above 5,000 rows, without
subsampling. Markdown uses inline SVG; viewers that suppress SVG can use HTML.

The existing campaign verification JSON report adds the same interpretation
vocabulary, recorded development results, selection history and confirmation
history. It stays data-free: row-level plots require local reproduction with the
bound dataset. Neither report substitutes current canvas settings or invents
missing exclusions, units, independent sampling, or fresh reproduction outcomes.
