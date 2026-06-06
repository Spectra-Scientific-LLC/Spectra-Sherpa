# Classification Nodes

Classification nodes assign spectra or feature rows to classes.

## Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Train KNN Classifier (`classification.knn`) | You need a distance-based classifier after appropriate scaling or dimensionality reduction. | `X: Array2D`; `y: Categorical?` | `model`; `predictions`; `probabilities`; `metrics`; `distances`; `neighbor_indices`; `train_accuracy`; `cv_accuracy`; `plots` | `n_neighbors`; `weights`; `metric`; `scale`; `cv_folds`. |
| Train PLS-DA Classifier (`classification.plsda`) | You want a latent-variable classifier for spectral class separation. | `X: Array2D`; `y: Categorical?` | `model`; `predictions`; `probabilities`; `X_scores`; `X_loadings`; `metrics` | `n_components`; `scale`; `cv_folds`; `calibrate_probabilities`; `probability_method`. Requires SpectroChemPy. |
| Train SIMCA Classifier (`classification.simca`) | You want class-specific PCA models that can reject samples outside known classes. | `X: Array2D`; `y: Categorical?` | `model`; `predictions`; `class_assignment`; `distances`; `class_distance_matrix`; `confusion_matrix`; `plots`; metrics | `n_components`; `confidence_level`; `critical_limits_method`; `cv_folds`. Requires SpectroChemPy. |
| Apply Classification Model (`classification.predict`) | Apply a fitted classifier to new spectra. | `X_new: SpectralDataset`; `model: ClassificationModel` | `y_pred: Categorical`; `y_prob: Array2D` | no parameters. Keep preprocessing identical to training. |

## Key Outputs

Expect predictions, class probabilities or distances where appropriate, confusion matrices, and split-aware metrics when validation is part of the workflow.

PLS-DA probability outputs are derived from model scores/regression outputs unless explicitly calibrated; treat them as relative confidence unless calibrated probability estimation is part of the workflow.

## SIMCA Note

SIMCA is not just nearest-class classification. It can reject samples that do not fit any class model, which is important for QC workflows.
