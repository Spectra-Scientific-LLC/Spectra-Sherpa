# Regression Nodes

Regression nodes predict quantitative targets from spectra or features.

## Training and Prediction Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Train PLS Regression (`model.pls`) | Standard multivariate calibration for concentrations or quantitative properties. | `X: Array2D`; `y: TargetMatrix?` | `model`; `X_scores`; `Y_scores`; `X_loadings`; `Y_loadings`; `y_pred`; `y_true`; `y_pred_cv`; `vip`; `coefficients` | `n_components`; `scale`; `cv_method`; `cv_folds`. Requires SpectroChemPy. Choose components by CV error and residual diagnostics, not calibration R² alone. |
| Apply PLS Regression Model (`model.pls_predict`) | Apply a fitted PLS model to new spectra. | `X_new: SpectralDataset`; `model: RegressionModel` | `y_pred: TargetMatrix` | no parameters. New spectra must receive the same preprocessing as training spectra. |
| Train PCR Regression (`model.pcr`) | Regress targets on PCA scores when you want explicit PCA compression before regression. | `X: Array2D`; `y: TargetMatrix?` | `model`; `scores`; `loadings` | `n_components`; `scale`. |
| Train SVR Regression (`model.svr`) | Nonlinear calibration with support vector regression. | `X: Array2D`; `y: TargetMatrix?` | `model`; `predictions`; `residuals` | `kernel`; `C`; `epsilon`; `gamma`; `degree`; `coef0`; `scale`. Scaling is usually important for SVR. |
| Train Linear Regression (`model.linear_regression`) | Simple baseline calibration or already-selected low-dimensional features. | `X: Array2D`; `y: TargetMatrix?` | `model`; `predictions`; `residuals` | `fit_intercept`. |
| Apply Saved Model Artifact (`model.load_apply`) | Load a saved model artifact and apply it to inference data. | `X_new: SpectralDataset`; `model_ref: ModelReference?` | `result`; `labels`; `model_id` | `model_id`. |

## Key Outputs

PLS regression exposes interpretation-oriented outputs such as scores, loadings, training predictions, cross-validated predictions, VIP scores, and regression coefficients. For calibration review, prefer `y_pred_cv` and holdout predictions over the optimistic fitted `y_pred`.

scikit-learn documents the core PLSRegression parameters, including `n_components` and `scale`, here: <https://scikit-learn.org/stable/modules/generated/sklearn.cross_decomposition.PLSRegression.html>.

## Decision Notes

- Use PLS when spectra are collinear and the target is quantitative.
- Use PCR when you want PCA compression to be explicit and separately inspected.
- Use SVR only after careful scaling and validation; nonlinear models can overfit small spectral datasets.
- Use linear regression mainly for selected variables, peak areas, or low-dimensional features.
- Keep sample-target alignment explicit. If targets arrive separately, use Data/Attach Target or a workflow that preserves row identity.

## Good Practice

Confirm sample-target alignment before training. For spectroscopy calibration, this is as important as model choice.
