# Reference measurements and prediction intervals

Prediction intervals are an optional, separate calibration product for a frozen
canonical PLS application pipeline. A fitted model alone produces **point
predictions only**. An interval record never changes the model or its signed
application package.

This method currently applies only through a verified canonical application plan.
Legacy saved-model application and standalone generated-node execution do not
consume the sidecar and remain point-only.

## Scientific contract

Use a separate calibration cohort with one row per distinct specimen and complete
reference responses. Freeze the entire preprocessing and model pipeline before
calibration. Do not use these specimens for fitting, tuning or model selection.
Declare the specimen-ID namespace, reference method/version, response names and
units, measurements averaged per label, and intended population. These declarations
are retained; software cannot establish laboratory independence or exchangeability.
Optional supplied training IDs must be nonempty and disjoint. A successful ID check
only establishes disjointness of those supplied IDs in the declared namespace.

For each response, calculate absolute errors from the frozen pipeline, sort them,
and retain the order statistic at rank `ceil((m + 1) * (1 - alpha))`, counting from
one. This is split conformal calibration, without interpolation or an estimated
residual degrees of freedom. If the rank exceeds the number of independent
specimens, refuse calibration. Prediction intervals are `prediction ± width`.

The claim is **per-response marginal coverage of future measured reference values**
under declared exchangeability. It is not simultaneous multiresponse coverage,
coverage conditional on the predicted concentration or screening status, or
uncertainty in the latent true concentration. A biased predictor is not silently
recentered. Bootstrap uncertainty in an aggregate validation metric remains a
different quantity.

Reference precision, when supplied from repeat measurements, is pooled within-
specimen sample standard deviation, with `specimens * (replicates - 1)` degrees of
freedom. A shifted and scaled calculation preserves small and large representable
scatter. Unrepresentable scatter is refused. Missing replicate evidence stays
unavailable; precision is never inferred from model residuals or added again to
conformal widths.

## Application and refusal

The record binds the exact artifact, complete application plan and terminal fitted
state. Its digest checks integrity, **not publisher authenticity or laboratory
qualification**. Full calibration rows are not stored in the record.

Application requires an explicit declaration accepting the selected record's
intended population. Outputs identify compatibility as declared by the operator,
not verified. Folder watches persist this declaration with the record and recheck
both when resolving execution after restart. Replacing evidence requires a fresh
explicit declaration; changing models requires clearing or replacing evidence.

A selected malformed, mismatched or damaged record fails explicitly. It never
silently falls back to point predictions. Explicitly clearing both record and
population declaration returns to point-only output. Historical point-only models
remain point-only.

Rows outside the retained global screening limits, or with unavailable screening,
have unavailable interval endpoints. The screening subset does not acquire a
conditional coverage guarantee. Each interval output retains the prediction receipt,
row index, method, alpha, record digest, reference basis and unavailable status.
The complete validated aggregate record is retained with the result so later
watch edits or clearing cannot erase the authority for an earlier run.

## Workflow

1. Use `calibrate_prediction_intervals` on an independently selected reference
   dataset and verified canonical application plan. This executes the actual frozen
   DAG; it does not refit or approximate preprocessing.
2. Save `record.canonical_bytes()` as a separate JSON file. The signed application
   package remains unchanged.
3. Load it with `UncertaintyRecord.load` and pass it to
   `execute_canonical_application(..., uncertainty_record=record.model_dump(),
   uncertainty_population=record.intended_population)` only after explicitly
   accepting that population for the incoming observations.
4. In a local folder watch, select a canonical application, import the record and
   acknowledge its population and reference basis. Alternatively calibrate from a
   separate reference dataset with retained sample IDs and target authority.
5. Export the sidecar separately when transferring the application. The receiving
   operator must accept the population again. Exporting a record does not transfer
   that operator's acceptance.

## Required regression evidence

Check independent order statistics, insufficient calibration count, bias, replicate
precision, extreme numerical magnitudes, missing reference values, mismatched units,
model/plan tampering, explicit population acceptance, save/reopen/clear behavior,
and coverage on an untouched synthetic cohort. Real data without reference replicate
evidence cannot establish reference precision or laboratory qualification.

Method background: Angelopoulos and Bates,
[A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification](https://arxiv.org/abs/2107.07511).
The marginal guarantee depends on exchangeability; screening, selection and
population shift require their own justification.
