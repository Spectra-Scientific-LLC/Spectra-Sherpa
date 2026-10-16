/**
 * Readable names for metric keys shown in detail views. Display only: the
 * stored key is unchanged and unknown keys fall back to their own words.
 */
const NAMES: Record<string, string> = {
  rmse: "RMSE",
  rmsec: "RMSEC",
  rmsecv: "RMSECV",
  rmsep: "RMSEP",
  rmse_cv: "RMSE (CV)",
  rmse_cal: "RMSE (calibration)",
  rmse_test: "RMSE (test)",
  r2: "R²",
  r2cv: "R² (CV)",
  r2_cv: "R² (CV)",
  r2_cal: "R² (calibration)",
  r2_test: "R² (test)",
  q2: "Q²",
  mae: "MAE",
  bias: "Bias",
  sep: "SEP",
  rpd: "RPD",
  n_samples: "Samples",
  n_classes: "Classes",
  n_components: "Components",
  accuracy: "Accuracy",
  accuracy_test: "Accuracy (test)",
  balanced_accuracy: "Balanced accuracy",
  train_balanced_accuracy: "Balanced accuracy (training)",
  cv_accuracy: "Accuracy (CV)",
  cv_balanced_accuracy: "Balanced accuracy (CV)",
  cv_f1_macro: "F1 macro (CV)",
  cv_sensitivity_macro: "Sensitivity (CV)",
  cv_specificity_macro: "Specificity (CV)",
  f1: "F1",
  f1_macro: "F1 (macro)",
  silhouette: "Silhouette",
};

export function metricDisplayName(key: string): string {
  const known = NAMES[key.toLowerCase()];
  if (known) return known;
  const words = key.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}
