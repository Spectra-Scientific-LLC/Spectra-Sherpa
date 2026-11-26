/**
 * One icon per node, shared by the palette, the canvas and node details. Nodes
 * without their own icon take their category's icon, so no node shows a
 * placeholder.
 */
const NODE_ICONS: Record<string, string> = {
  "analysis.compare_library": "📚",
  "analysis.peak_finding": "⛰️",
  "baseline.penalized_ls": "📉",
  "baseline.rubberband": "📉",
  "classification.apply_knn": "🔮",
  "classification.apply_plsda": "🔮",
  "classification.apply_simca": "🔮",
  "classification.knn": "👥",
  "classification.plsda": "🎯",
  "classification.simca": "🎲",
  "data.attach_target": "🎯",
  "data.file_load": "📂",
  "data.filter_samples": "🔎",
  "data.load_group": "🗂️",
  "data.nist_library": "📚",
  "data.synthetic_curve": "📈",
  "data.train_test_split": "✂️",
  "deploy.input": "📥",
  "deploy.output": "📤",
  "diagnostics.cross_validation": "🔄",
  "diagnostics.outliers": "🚨",
  "model.apply_fitted_pls": "🎯",
  "model.dbscan": "🫧",
  "model.efa": "🔬",
  "model.fitted_pls": "📈",
  "model.hca": "🌳",
  "model.ica": "⚡",
  "model.kmeans": "🧭",
  "model.linear_regression": "📉",
  "model.mcr_als": "🧩",
  "model.nmf": "📊",
  "model.pca": "🔀",
  "model.pca_transform": "⚙️",
  "model.pcr": "🧮",
  "model.simplisma": "🔎",
  "model.svr": "🧲",
  "output.contour": "🗺️",
  "output.data_table": "📋",
  "output.export": "💾",
  "output.plot": "📈",
  "preprocess.clip_floor": "⬆️",
  "preprocess.clip_range": "✂️",
  "preprocess.cosmic_ray": "✨",
  "preprocess.derivative": "∂",
  "preprocess.emsc": "📐",
  "preprocess.normalize": "⚖️",
  "preprocess.osc": "⊥",
  "preprocess.scale": "📏",
  "preprocess.smooth": "〰️",
  "preprocess.wavenumber_align": "⚙️",
  "selection.audit": "📋",
  "selection.cars": "🏎️",
  "selection.compare": "⚖️",
  "selection.ipls": "📊",
  "selection.mcuve": "🧹",
  "selection.nested_cv": "🔄",
  "selection.spa": "📐",
  "selection.stability": "🔒",
  "selection.variable_select": "🔬",
  "stats.summary": "📊",
  "synthesis.blend": "🔀",
  "synthesis.merge": "📚",
  "synthesis.species": "🧬",
  "time_series.moving_window": "🕒",
  "time_series.trend_removal": "📉",
  "transfer.apply_fitted": "🧰",
  "transfer.ds": "🔁",
  "transfer.pds": "🔄",
  "transfer.sws": "📐",
};

const CATEGORY_ICONS: Record<string, string> = {
  data: "🗂️", synthesis: "🧪", preprocessing: "〰️", selection: "🔬", exploratory: "🧭", modeling: "📈",
  regression: "📈", classification: "🎯", clustering: "🫧", validation: "✅", diagnostics: "✅", output: "📊",
  deploy: "🚀", custom: "🧩",
};

const PREFIX_ICONS: Record<string, string> = {
  data: "🗂️", synthesis: "🧪", preprocess: "〰️", baseline: "📉", transfer: "🔁", time_series: "🕒",
  selection: "🔬", analysis: "🧭", model: "📈", classification: "🎯", diagnostics: "✅", stats: "📊",
  output: "📊", deploy: "🚀", custom: "🧩",
};

export function nodeIcon(nodeType: string, category?: string | null): string {
  return NODE_ICONS[nodeType]
    ?? (category ? CATEGORY_ICONS[category] : undefined)
    ?? PREFIX_ICONS[nodeType.split(".")[0]]
    ?? "⚙️";
}

/**
 * The palette name without an internal version tag or a citation; the citation
 * stays in the node's help text, and saved workflows keep their recorded label.
 * "Reference Regression Evaluator (v2)" → "Reference Regression Evaluator";
 * "SPA-MLR Variable Selection (Araújo 2001)" → "SPA-MLR Variable Selection".
 */
export function paletteLabel(label: string): string {
  return label.replace(/\s+\(v\d+\)$/, "").replace(/\s+\([^()]*\b(1[89]|20)\d{2}\)$/, "").trim() || label;
}
