# Classification Nodes

Classification nodes assign spectra or feature rows to classes.

## Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Train KNN Classifier (`classification.knn`) | You need a distance-based classifier after appropriate scaling or dimensionality reduction. Validation is owned by an explicit split plan outside this fit-only node. | `X: Array2D`; `y: Categorical?` | `fitted_state`; calibration `predictions`; `probabilities`; `metrics`; `distances`; `neighbor_indices`; `train_accuracy`; `plots` | `n_neighbors`; `weights`; `metric`; `scale`. |
| Apply Fitted KNN (`classification.apply_knn`) | Apply the exact KNN reference set, scaling, distance, and voting state to new rows. | `X_new: Array2D`; `fitted_state: ClassificationModel` | `y_pred: Categorical`; `y_prob: Array2D` | no parameters. Accepts only the KNN serializer. |
| Train PLS-DA Classifier (`classification.plsda`) | You want a latent-variable classifier for exactly-one-class spectral discrimination. Validation is owned by an explicit split plan outside this fit-only node. | `X: Array2D`; `y: Categorical?` | `fitted_state`; calibration `predictions`; raw response `class_scores`; `X_scores`; `X_loadings`; calibration `metrics`; `plots` | `n_components`; `scale`. Uses the native Sherpa SIMPLS authority. |
| Apply Fitted PLS-DA (`classification.apply_plsda`) | Apply fitted PLS2 coefficients and the declared maximum-response decision rule to new rows. | `X_new: Array2D`; `fitted_state: ClassificationModel` | `y_pred: Categorical`; `class_scores: Array2D` | no parameters. Scores are responses, not probabilities; accepts only the PLS-DA serializer. |
| Train SIMCA Classifier (`classification.simca`) | You want class-specific PCA models that can reject samples outside known classes. Validation is owned by an explicit split plan outside this fit-only node. | `X: Array2D`; `y: Categorical?` | `fitted_state`; calibration `predictions`; `class_assignment`; `distances`; `class_distance_matrix`; `confusion_matrix`; `plots`; metrics | `n_components`; `confidence_level`; `critical_limits_method`. Uses the native Sherpa SIMCA authority. |
| Apply Fitted SIMCA (`classification.apply_simca`) | Apply explicit class PCA models and their complete T²/Q limits to new rows. | `X_new: Array2D`; `fitted_state: ClassificationModel` | `y_pred: Categorical`; `class_affinity: Array2D` | no parameters. Can return `unassigned`; affinity is not probability; accepts only the SIMCA serializer. |

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

## SIMCA Note

SIMCA is not just nearest-class classification. It can reject samples that do
not fit any class model, which is important for QC workflows. Its training node
performs one fit and reports calibration diagnostics only. Validation belongs
to an explicit split plan and the shared fold executor; an `unassigned` result
is a scientific rejection, not a fabricated class prediction.
