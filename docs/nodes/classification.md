# Classification Nodes

Classification nodes assign spectra or feature rows to classes.

## Nodes

| Node | Scientific use and guidance |
| --- | --- |
| Train KNN Classifier (`classification.knn`) | You need a distance-based classifier after appropriate scaling or dimensionality reduction. Validation is owned by an explicit split plan outside this fit-only node. |
| Apply Fitted KNN (`classification.apply_knn`) | Apply the exact KNN reference set, scaling, distance, and voting state to new rows. Accepts only the KNN serializer. |
| Train PLS-DA Classifier (`classification.plsda`) | You want a latent-variable classifier for exactly-one-class spectral discrimination. Validation is owned by an explicit split plan outside this fit-only node. Uses the native Sherpa SIMPLS authority. |
| PLS-DA Response Permutation (`diagnostics.plsda_permutation`) | Check whether a PLS-DA development result exceeds a random-label null under an exchangeable design. |
| Apply Fitted PLS-DA (`classification.apply_plsda`) | Apply fitted PLS2 coefficients and the declared maximum-response decision rule to new rows. Scores are responses, not probabilities; accepts only the PLS-DA serializer. |
| Train SIMCA Classifier (`classification.simca`) | You want class-specific PCA models that can reject samples outside known classes. Validation is owned by an explicit split plan outside this fit-only node. Uses the native Sherpa SIMCA authority. |
| Apply Fitted SIMCA (`classification.apply_simca`) | Apply explicit class PCA models and their complete T²/Q limits to new rows. Can return `unassigned`; affinity is not probability; accepts only the SIMCA serializer. |

## Calibration and application safeguards

Numerical analysis refuses inputs containing excluded samples or variables.
Materialize the active sample cohort with Filter Samples (source inclusion),
and the active variables with an explicit variable-selection rule, before
fitting. Excluded data cannot silently influence models or reference statistics.

KNN, PLS-DA, and SIMCA application require the fitted feature order, axis units, signal
units, signal quantity, and measurement mode. Missing metadata must also match
what was available at fit time. Convert incompatible signals explicitly before
application. Refit older classifier states or saved artifacts that do not record
this input identity.

PLS-DA application reports per-sample T² and Q, fitted screening limits, and an
out-of-domain warning independently of the argmax class decision. A large class
response is not a membership guarantee. Screening uses aggregate calibration
statistics; it does not establish local support or analytical validation.

SIMCA uses the recorded positive eigenvalues, scaling factors, and acceptance
limits exactly. Calibration, fitted application, and membership reporting share
the same distance calculation, including for very small positive residual limits.

## Key Outputs

Expect predictions, class probabilities, response scores, or affinities where
appropriate, plus confusion matrices and split-aware metrics when validation is
part of the workflow. Application is deliberately family-specific: no node may
guess the model family, invent missing SIMCA limits, or reinterpret a numerical
output as a probability.

KNN fits the exact configured neighbor count, distance rule, weighting rule,
and optional autoscaling state. The node reports calibration-fit diagnostics,
not validation performance. Use an explicit stratified or grouped split plan
and the shared fold executor for validation; preprocessing and the classifier
are then fit only on each training partition. The saved artifact carries
the reference rows, encoded class identities, and fitted scaling vectors needed
to reproduce scikit-learn's exact zero-distance and tie behavior. Scientific
reference: Cover and Hart, *Nearest Neighbor Pattern Classification*, IEEE
Transactions on Information Theory 13 (1967), 21–27,
DOI `10.1109/TIT.1967.1053964`.

PLS-DA fits PLS2 to a 0/1 dummy class table and assigns each sample to the
largest predicted dummy response, following the usual `rchemo::plsrda`
exactly-one-class rule. Its `class_scores` are regression responses, **not
posterior probabilities**. The node performs one fit and carries no hidden
cross-validation setting. The standard PLS-DA analysis template uses an
explicit stratified train/test split; repeated or grouped validation uses the
shared split-plan and fold-executor workflow. This applies to every dataset,
not only grouped instrument studies. Report the class order, split record,
confusion matrices, and fold-local metrics. Scientific reference: Barker and Rayens,
*Partial least squares for discrimination*, Journal of Chemometrics 17 (2003),
166–173, DOI `10.1002/cem.785`.

For a response-permutation check, connect the training partition to both
the PLS-DA fit and the diagnostic node, including the same class labels and
the fitted-state output. The diagnostic recomputes the state and refuses a
different calibration population. It repeats the complete stratified or
grouped fold-local fit and component search for the observed labels and for
every seeded shuffle. Whole specimen groups remain intact; class labels move
only among equal-sized groups in the same optional exchangeability block.
Blocks come from a named column in the verified attached sample table; a
free-standing vector is not accepted because its row identity is unknown.
Insufficient class counts, invalid folds, population-fitted upstream
preprocessing, and incomplete permutations stop the check without a p-value.
For an input supplied as a bare array without provenance, the result records
`caller_declared_raw_array_no_recorded_preprocessing`; it does not claim that
unrecorded preparation was verified or refitted within folds.
The finite-sample value is `(1 + null scores at least as high as observed) /
(1 + completed permutations)`. An identity draw remains in the null sample.
This is development evidence against exchangeable random labels, not an
independent test, an application-domain check, or proof of causation.
CV-ANOVA is explicitly unavailable for this PLS-DA statistic.

## SIMCA Note

SIMCA is not just nearest-class classification. It can reject samples that do
not fit any class model, which is important for QC workflows. Its training node
performs one fit and reports calibration diagnostics only. Validation belongs
to an explicit split plan and the shared fold executor; an `unassigned` result
is a scientific rejection, not a fabricated class prediction.

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/classification.md", "node_types": ["classification.apply_knn", "classification.apply_plsda", "classification.apply_simca", "classification.knn", "classification.plsda", "classification.simca", "diagnostics.plsda_permutation"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

### Apply Fitted KNN (`classification.apply_knn`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>X_new</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_pred</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_prob</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply Fitted PLS-DA (`classification.apply_plsda`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_pred</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_scores</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply Fitted SIMCA (`classification.apply_simca`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>X_new</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_pred</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_affinity</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Train KNN Classifier (`classification.knn`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>probabilities</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_probabilities</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metrics</code> | <code>spectrasherpa://types/StatisticsSummary/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>distances</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>neighbor_indices</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>train_accuracy</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>confusion_visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_neighbors</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of neighbors to consider Caps per-sample vote cardinality and returned neighbor-output width; the scientific fit also requires k not to exceed the supplied training rows. |
| <code>weights</code> | <code>select</code> | <code>false</code> | <code>&quot;uniform&quot;</code> | <code>[&quot;uniform&quot;, &quot;distance&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Weight function: uniform (all equal) or distance (closer = more weight) |
| <code>metric</code> | <code>select</code> | <code>false</code> | <code>&quot;euclidean&quot;</code> | <code>[&quot;euclidean&quot;, &quot;manhattan&quot;, &quot;chebyshev&quot;, &quot;minkowski&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Distance metric for nearest neighbor calculation |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Standardize variables before distance calculations. Disable only when upstream scores or features are already on the intended scale. |

### Train PLS-DA Classifier (`classification.plsda`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>explained_variance</code> | <code>spectrasherpa://types/ExplainedVarianceMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_coefficients</code> | <code>spectrasherpa://types/RegressionCoefficientMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_scores</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>vip_scores</code> | <code>spectrasherpa://types/VariableImportance/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>confusion_matrix_train</code> | <code>spectrasherpa://types/ConfusionMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metrics</code> | <code>spectrasherpa://types/StatisticsSummary/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>component_curve</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>sample_diagnostics</code> | <code>spectrasherpa://types/PLSDASampleDiagnostics/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of PLS2 latent variables Bounds latent-variable fitting and artifact size; runtime further limits components to the smallest fold-local calibration rank. |
| <code>scale</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Fit scaling inside every calibration or validation fold |

### Train SIMCA Classifier (`classification.simca`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_assignment</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>distances</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>class_distance_matrix</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metrics</code> | <code>spectrasherpa://types/StatisticsSummary/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>train_accuracy</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>confusion_matrix</code> | <code>spectrasherpa://types/ConfusionMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>acceptance_visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>confusion_visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of PCs for each class model Bounds per-class PCA fit and cross-validation cost in the interactive runtime. |
| <code>confidence_level</code> | <code>number</code> | <code>false</code> | <code>0.95</code> | — | <code>{&quot;min_value&quot;: 0.8, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Confidence level for class boundaries |
| <code>critical_limits_method</code> | <code>select</code> | <code>false</code> | <code>&quot;ddmoments&quot;</code> | <code>[&quot;ddmoments&quot;, &quot;classical&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | How T² and Q critical limits are computed for class membership. &#x27;ddmoments&#x27; (default in v0.4.3+): Pomerantsev data-driven moments (J. Chemom. 2008) — estimates effective degrees of freedom from the calibration distribution; more robust on heavy-tailed Q and small classes. &#x27;classical&#x27;: F-distribution T² + χ² Q (Nomikos &amp; MacGregor 1995, Jackson &amp; Mudholkar 1979) — the pre-v0.4.3 behaviour, kept for reproducibility with legacy reports. |

### PLS-DA Response Permutation (`diagnostics.plsda_permutation`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/ClassificationModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>permutations</code> | <code>number</code> | <code>true</code> | <code>19</code> | — | <code>{&quot;max_value&quot;: 199, &quot;min_value&quot;: 19, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds repeated fold-local model fits. |
| <code>folds</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 5, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Preserves classes in bounded grouped folds. |
| <code>maximum_components</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 10, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds full component search per shuffle. |
| <code>seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Uses an exact unsigned 32-bit reproducibility seed. |
| <code>block_column</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Optional column from the verified attached sample table; never a free-standing vector. |

<!-- END GENERATED NODE REFERENCE -->
