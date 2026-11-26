/** Chemometric names for model methods and run kinds, shared by every page that lists them. */

const MODEL_TYPE_LABELS: Record<string, string> = {
  pls: "PLS", plsda: "PLS-DA", pls_da: "PLS-DA", pca: "PCA", pcr: "PCR", svr: "SVR", knn: "KNN", simca: "SIMCA",
  linear_regression: "Linear regression", mcr_als: "MCR-ALS",
};

export function modelTypeLabel(type: string | null | undefined): string {
  const raw = String(type ?? "");
  return MODEL_TYPE_LABELS[raw.toLowerCase()] ?? raw;
}

/** "9 LV" for latent-variable methods, "3 components" otherwise. */
export function componentCountLabel(type: string | null | undefined, count: number): string {
  return /^(pls|plsda|pls_da)$/i.test(String(type ?? "")) ? `${count} LV` : `${count} component${count === 1 ? "" : "s"}`;
}

/** Method, number of variables and component count, e.g. "PLS · 700 variables · 9 LV". */
export function modelShape(model: { model_type?: string | null; n_features?: number | null; n_components?: number | null }): string[] {
  const parts = [modelTypeLabel(model.model_type)];
  if (model.n_features != null) parts.push(`${model.n_features} variables`);
  if (model.n_components != null) parts.push(componentCountLabel(model.model_type, model.n_components));
  return parts;
}

export function runKindLabel(kind: string | null | undefined): string {
  switch (kind) {
    case "training": return "Model fit";
    case "batch_inference": return "Prediction";
    case "data": return "Data";
    case "other": return "Other";
    default: return kind ? kind.replace(/_/g, " ") : "Run";
  }
}
