export const NODE_CATEGORY_LABELS: Readonly<Record<string, string>> = {
  data: "Data",
  synthesis: "Simulation & Synthesis",
  preprocessing: "Preprocessing",
  transfer: "Calibration Transfer",
  time_series: "Time Series",
  selection: "Feature Selection & Design",
  exploratory: "Exploration & Decomposition",
  regression: "Regression",
  classification: "Classification",
  clustering: "Clustering",
  validation: "Validation & Diagnostics",
  output: "Results & Export",
  deploy: "Deployment & Model Application",
};

export const NODE_CATEGORY_ORDER: readonly string[] = [
  "data",
  "synthesis",
  "preprocessing",
  "transfer",
  "time_series",
  "selection",
  "exploratory",
  "regression",
  "classification",
  "clustering",
  "validation",
  "output",
  "deploy",
];

export const nodeCategoryLabel = (category: string): string =>
  NODE_CATEGORY_LABELS[category] ||
  category.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());

export const sortNodeCategories = (categories: string[]): string[] => {
  const positions = new Map(NODE_CATEGORY_ORDER.map((category, index) => [category, index]));
  return [...new Set(categories)].sort((left, right) => {
    const leftPosition = positions.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightPosition = positions.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftPosition - rightPosition || left.localeCompare(right);
  });
};
