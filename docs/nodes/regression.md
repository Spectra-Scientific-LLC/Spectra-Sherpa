# Regression Nodes

Regression nodes predict quantitative targets from spectra or features.

## Training and Prediction Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Fit PLS1 / PLS2 Regression (SIMPLS) (`model.fitted_pls`) | Fit a quantitative calibration while making the reusable numerical state and VIP evidence explicit. | `default: SpectralDataset`; `y: TargetMatrix?` | training predictions; typed `fitted_state`; `vip_scores` | `n_components`; `scale`. Choose components under an explicit validation design rather than calibration fit alone. |
| Apply PLS1 / PLS2 Model (SIMPLS) (`model.apply_fitted_pls`) | Apply either a verified upstream fitted state or a verified imported artifact through the same numerical core. | `default: SpectralDataset`; optional upstream `fitted_state` | predicted targets | Local state is connected by a typed edge; imported mode requires the complete artifact binding and cannot be mixed with local custody. |
| Train PCR Regression (`model.pcr`) | Regress targets on PCA scores when you want explicit PCA compression before regression. | `X: Array2D`; `y: TargetMatrix?` | `model`; `scores`; `loadings` | `n_components`; `scale`. |
| Train SVR Regression (`model.svr`) | Nonlinear calibration with support vector regression. | `X: Array2D`; `y: TargetMatrix?` | `model`; `predictions`; `residuals` | `kernel`; `C`; `epsilon`; `gamma`; `degree`; `coef0`; `scale`. Scaling is usually important for SVR. |
| Train Linear Regression (`model.linear_regression`) | Simple baseline calibration or already-selected low-dimensional features. | `X: Array2D`; `y: TargetMatrix?` | `model`; `predictions`; `residuals` | `fit_intercept`. |
| Apply Saved Model Artifact (`model.load_apply`) | Load a saved model artifact and apply it to inference data. | `X_new: SpectralDataset`; `model_ref: ModelReference?` | `result`; `labels`; `model_id` | `model_id`. |

## Key Outputs

### Changing the regression algorithm

Use **Predict Regression** (`model.predict_regression`) when comparing PLS,
PCR, SVR, or linear regression in a held-out workflow. Connect the trainer's
**Fitted State** output and the split's **Test Data** to this node. Its
**Predicted Targets** output goes to Test Evaluation together with the matching
test references and held-out sample context. It applies retained training state;
it does not fit on test rows or replay preprocessing already applied upstream.

**Train PCR Regression**, **Train SVR Regression**, and **Train Linear Regression**
now provide a portable **Fitted State** output in addition to their legacy Model
output. Use Fitted State for prediction. The explicit Fit variants are supported
too. Prediction identity retains response names/units when the training state
contains them; bare response arrays and older states remain explicitly unnamed.

**Junior-user note:** in older templates, “Predict Test Set” was only a label for
a PLS-specific node. For an existing workflow, replace that node with **Predict
Regression**, reconnect Fitted State and Test Data, and reconnect Predicted
Targets to the evaluator. Historical runs are not changed. A PLS application
node cannot apply PCR state even though both connections say RegressionModel.

Use the explicitly PLS-specific application node when you need PLS prediction
intervals or applicability screening. The general predictor does not manufacture
equivalent diagnostics for other algorithms. Algorithm-specific application and
PCA diagnostic nodes reject incompatible producer ports during graph validation.

### Fold-safe PCR, SVR and linear regression

For a workflow you intend to optimize, use **Fit PCR** (`model.fitted_pcr`),
**Fit SVR** (`model.fitted_svr`) or **Fit Linear Regression**
(`model.fitted_linear_regression`) and the matching **Apply** node
(`model.apply_fitted_pcr`, `model.apply_fitted_svr`, or
`model.apply_fitted_linear_regression`). The older single-step Train nodes remain
available, but their saved runs are not substituted with a different recipe.

Connect the split's `X_train` and `y_train` to Fit, its `X_test` to Apply, and
Fit's `fitted_state` to Apply. Connect predictions and `y_test` to a held-out
regression evaluator. During optimization, fitting is repeated using only each
fold's training rows. PCR compression and any model-internal scaling are fitted
there too. These explicit nodes reject missing/nonfinite training values rather
than silently changing the scored population.

**Junior-user note:** the Fit node's predictions describe the training fit, not
predictive performance. Compare the held-out evaluator or campaign's common
cross-validation scores. Do not fit scaling or select variables on the complete
dataset before splitting. Additional learned-preprocessing and branched-workflow
support are not part of this expansion.

Canonical PLS exposes training predictions, a closed fitted-state envelope, and producer-owned combined VIP scores. Validation metrics belong to explicit evaluator nodes supplied with out-of-fold or held-out predictions; the fitted node does not relabel training fit as validation evidence.

The implementation follows de Jong's SIMPLS algorithm: S. de Jong,
*SIMPLS: an alternative approach to partial least squares regression*,
Chemometrics and Intelligent Laboratory Systems 18 (1993) 251–263,
<https://doi.org/10.1016/0169-7439(93)85002-X>.

### PLS1, PLS2, and solver names

PLS1 means one response variable and PLS2 means multiple response variables.
Those terms do not select the numerical solver. SIMPLS and NIPALS are distinct
algorithms that can be used for PLS regression. The canonical node uses de
Jong SIMPLS for both its single-response PLS1 and multi-response PLS2 cases.
There is no separate canonical NIPALS regression node in this release.

## Decision Notes

- Use PLS when spectra are collinear and the target is quantitative.
- Use PCR when you want PCA compression to be explicit and separately inspected.
- Use SVR only after careful scaling and validation; nonlinear models can overfit small spectral datasets.
- Use linear regression mainly for selected variables, peak areas, or low-dimensional features.
- Keep sample-target alignment explicit. If targets arrive separately, use Data/Attach Target or a workflow that preserves row identity.

## Good Practice

Confirm sample-target alignment before training. For spectroscopy calibration, this is as important as model choice.

### Portable PLS response identity

New fitted PLS states use serializer 9 and retain ordered response names and
units. Missing scientific metadata is explicitly unknown; predictor channel
names and application-input targets cannot fill it in. Separate labeled X/Y
datasets must have the same unique sample identities in the same order.
Reorder or join explicitly before fitting. Raw arrays remain positional.

Apply PLS1 / PLS2 Model (SIMPLS) emits **Prediction Identity** alongside its numeric
prediction matrix. This record binds response names/units, row labels or values,
shape, a digest of prediction values and the verified model-state identity.
Result exports retain the record beside the prediction CSV, including when
only the application result is exported. A bare numerical array or CSV without
that record is positional and does not by itself establish response authority.

Older PLS states without retained response identity require refitting for
current application. Their historical results remain evidence of the original
run; current labels are never substituted into them.

### Fitted input compatibility

Fitted PLS retains ordered feature identity and the signal units, declared
signal quantity and measurement mode used at fit time. Application must match
that authority before prediction. Spelling aliases such as `Abs` and
`absorbance` are equivalent; absorbance and transmittance are not. Convert
physical quantities explicitly before fitting/application.

Unknown metadata remains unknown and must match on replay. It does not imply
interchangeability or instrument qualification. Declare missing units or
measurement mode before fitting a model intended for deployment. Folder-watch
inputs must retain those declarations (for example, in portable CSV metadata);
missing or conflicting declarations produce a visible failed run.

### Missing references and training population

PCR, SVR and linear regression emit a **Training population** record. It
identifies the original predictor dataset by its scientific digest, the bound
response by its shape and value digest, response names/units, and the admitted
and excluded zero-based input rows. Labels and sample coordinates are retained
when available; row positions are explicitly relative to that input digest.
SVR also records the selected input response column independently of the
one-column matrix fitted by the estimator.

Missing selected reference values exclude the corresponding rows from fitting.
An incomplete unselected multi-response table requires explicit target selection.
Infinity is invalid rather than missing. Nonfinite predictors and an
unmaterialized sample exclusion mask refuse with an actionable error. Other
missing ancillary properties do not exclude a measured selected response.

The record is a declared result output and is retained in model artifact
metadata and generated Python results. It describes calibration fit, not
held-out validation. The mathematical fitted-state serializer alone does not
carry the training population; retain the result or model artifact when that
evidence is required. Older artifacts lacking the record have unknown original
population accounting; current metadata must not be substituted into them.

### Per-response regression metrics

PCR, SVR and linear regression use the SDK metric authority for training
statistics. R² is unavailable for exactly constant references or a singleton;
small but represented variation remains measurable regardless of display
rounding. Direct and pooled calculations share scaled, centered moments. SEP
is the sample standard deviation of prediction-minus-reference residuals,
including when those residuals have a large nonzero bias. Unrepresentable
numeric differences or metrics produce an explicit refusal.

Multi-response PCR and linear regression retain named per-response R² and
RMSE. Their summaries omit scalar R²/RMSE/score aggregates and state
`per_response_only`. Errors from different physical quantities must not be
combined into an unnamed scalar. Select the response when comparing models.
Single-response summaries remain available. A true-constant response has null
R², never an invented perfect fit.

This corrects numerical implementation of the existing metric definitions.
Historical records are not recalculated or upgraded in place. Previously
retained multi-response scalar errors are legacy unqualified summaries; use a
new calculation from retained observations and predictions for corrected
per-response evidence. A historical registry version alone is not proof that
a result used the corrected implementation; retain run/source identity.
