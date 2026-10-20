# Regression Nodes

Regression nodes predict quantitative targets from spectra or features.

## Training and Prediction Nodes

| Node | Scientific use and guidance |
| --- | --- |
| Fit PLS1 / PLS2 Regression (SIMPLS) (`model.fitted_pls`) | Fit a quantitative calibration while making the reusable numerical state and VIP evidence explicit. Choose components under an explicit validation design rather than calibration fit alone. |
| Apply PLS1 / PLS2 Model (SIMPLS) (`model.apply_fitted_pls`) | Apply either a verified upstream fitted state or a verified imported artifact through the same numerical core. Local state is connected by a typed edge; imported mode requires the complete artifact binding and cannot be mixed with local custody. |
| Train PCR Regression (`model.pcr`) | Regress targets on PCA scores when you want explicit PCA compression before regression. |
| Train SVR Regression (`model.svr`) | Nonlinear calibration with support vector regression. Scaling is usually important for SVR. |
| Train Linear Regression (`model.linear_regression`) | Simple baseline calibration or already-selected low-dimensional features. |
| Apply Saved Model Artifact (`model.load_apply`) | Load a saved model artifact and apply it to inference data. |

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

Canonical PLS exposes training predictions, a closed fitted-state envelope, and producer-owned combined VIP scores. A local regression evaluator scores the arrays supplied to it without independently verifying their cohort. Call its metrics validation only when retained run and split lineage establish out-of-fold or held-out predictions; the fitted node does not relabel training fit as validation evidence.

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

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/regression.md", "node_types": ["model.apply_fitted_linear_regression", "model.apply_fitted_pcr", "model.apply_fitted_pls", "model.apply_fitted_svr", "model.fitted_linear_regression", "model.fitted_pcr", "model.fitted_pls", "model.fitted_svr", "model.linear_regression", "model.load_apply", "model.pcr", "model.predict_regression", "model.svr"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

### Apply Linear Regression (`model.apply_fitted_linear_regression`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply PCR (`model.apply_fitted_pcr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply PLS1 / PLS2 Model (SIMPLS) (`model.apply_fitted_pls`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>prediction_intervals</code> | <code>spectrasherpa://types/PredictionIntervals/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>applicability</code> | <code>spectrasherpa://types/ApplicabilityScreening/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>prediction_identity</code> | <code>spectrasherpa://types/PredictionIdentity/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Canonical artifact-custody binding populated by import; not a scientist-set parameter. |

### Apply SVR (`model.apply_fitted_svr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Fit Linear Regression (`model.fitted_linear_regression`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>fit_intercept</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Calculate intercept (if False, force through origin) |

### Fit PCR (`model.fitted_pcr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of PCA components for regression |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Scale each predictor to unit variance before the PCA centering step. |

### Fit PLS1 / PLS2 Regression (SIMPLS) (`model.fitted_pls`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>vip_scores</code> | <code>spectrasherpa://types/VariableImportance/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>calibration_comparison</code> | <code>spectrasherpa://types/RegressionComparison/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>x_scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>x_loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>explained_variance</code> | <code>spectrasherpa://types/ExplainedVarianceMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>regression_coefficients</code> | <code>spectrasherpa://types/RegressionCoefficientMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>component_curve</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Requested maximum; the fit reports the effective predictive rank and stops before an unidentifiable direction. Must not exceed min(training samples - 1, input features). This choice is saved; the component CV curve is tuning evidence and must not use the locked test cohort. |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>component_selection_rule</code> | <code>select</code> | <code>false</code> | <code>&quot;manual_parameter&quot;</code> | <code>[&quot;manual_parameter&quot;, &quot;minimum_mean_fold_rmse&quot;, &quot;one_standard_error&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Choose and save the basis after inspecting the curve, then set Latent Variables to the desired count and refit. For a multiresponse model, use manual because each response has its own suggestion. |
| <code>component_curve_max</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Automatically includes the selected LV up to 20; a larger selected model is marked outside the bounded curve. Bounds the additional calibration/CV fits and retained per-component evidence. |
| <code>component_cv_folds</code> | <code>number</code> | <code>false</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 10, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Uses group K-fold when sample groups are bound, otherwise row K-fold. Scaling is fitted within each training fold. Population-fitted upstream preprocessing makes this curve unavailable. Bounds repeated fold fitting and retained fold evidence. |
| <code>target_names</code> | <code>string_list</code> | <code>false</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Fit SVR (`model.fitted_svr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>kernel</code> | <code>select</code> | <code>true</code> | <code>&quot;rbf&quot;</code> | <code>[&quot;rbf&quot;, &quot;linear&quot;, &quot;poly&quot;, &quot;sigmoid&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Kernel type for SVR |
| <code>C</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.01, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Regularization parameter |
| <code>epsilon</code> | <code>number</code> | <code>false</code> | <code>0.1</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Epsilon-tube width |
| <code>gamma</code> | <code>select</code> | <code>false</code> | <code>&quot;scale&quot;</code> | <code>[&quot;scale&quot;, &quot;auto&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Kernel coefficient for RBF/poly/sigmoid |
| <code>degree</code> | <code>number</code> | <code>false</code> | <code>3</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Degree for polynomial kernel |
| <code>coef0</code> | <code>number</code> | <code>false</code> | <code>0.0</code> | — | <code>{&quot;min_value&quot;: -1.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Independent term for poly/sigmoid kernels |
| <code>target_index</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | 1-based target/property column to model when the dataset contains multiple reference properties |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Apply mean centering and scaling |

### Train Linear Regression (`model.linear_regression`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>population</code> | <code>spectrasherpa://types/RegressionPopulation/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>residuals</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>effect_summary</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>fit_intercept</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Calculate intercept (if False, force through origin) |

### Apply Saved Model Artifact (`model.load_apply`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X_new</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>model_ref</code> | <code>spectrasherpa://types/ModelReference/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>result</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>labels</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>model_id</code> | <code>spectrasherpa://types/ModelReference/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>model_id</code> | <code>model_select</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Saved model artifact to load and apply |
| <code>acknowledge_legacy_input_uncertainty</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | I acknowledge that a pre-0.6.2 model lacks fitted signal identity. Use only when the retained feature axis matches; refit for verified application. |

### Train PCR Regression (`model.pcr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>population</code> | <code>spectrasherpa://types/RegressionPopulation/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_pred</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_true</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of PCA components for regression |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Scale each predictor to unit variance before the PCA centering step. |

### Predict Regression (`model.predict_regression`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>prediction_identity</code> | <code>spectrasherpa://types/PredictionIdentity/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Train SVR Regression (`model.svr`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>population</code> | <code>spectrasherpa://types/RegressionPopulation/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>residuals</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/RegressionModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>kernel</code> | <code>select</code> | <code>true</code> | <code>&quot;rbf&quot;</code> | <code>[&quot;rbf&quot;, &quot;linear&quot;, &quot;poly&quot;, &quot;sigmoid&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Kernel type for SVR |
| <code>C</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.01, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Regularization parameter |
| <code>epsilon</code> | <code>number</code> | <code>false</code> | <code>0.1</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Epsilon-tube width |
| <code>gamma</code> | <code>select</code> | <code>false</code> | <code>&quot;scale&quot;</code> | <code>[&quot;scale&quot;, &quot;auto&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Kernel coefficient for RBF/poly/sigmoid |
| <code>degree</code> | <code>number</code> | <code>false</code> | <code>3</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Degree for polynomial kernel |
| <code>coef0</code> | <code>number</code> | <code>false</code> | <code>0.0</code> | — | <code>{&quot;min_value&quot;: -1.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Independent term for poly/sigmoid kernels |
| <code>target_index</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | 1-based target/property column to model when the dataset contains multiple reference properties |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Apply mean centering and scaling |

<!-- END GENERATED NODE REFERENCE -->
