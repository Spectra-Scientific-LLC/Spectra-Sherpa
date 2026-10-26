/** Shared documentation destinations. Topic paths are source-checked in tests. */
export const DOCS_BASE_URL = "https://docs.spectrascientific.ai";
export const METHOD_TOPICS = {
  workflow: "workflows/build-a-workflow/#your-first-workflow-step-by-step",
  comparison: "chemometrics/validation-application/#compare-saved-models-in-a-project",
  componentSelection: "chemometrics/validation-design/#component-selection",
  qualification: "chemometrics/validation-application/#qualification-and-prediction-intervals",
  diagnostics: "chemometrics/validation-application/#diagnostic-review",
  instrumentQC: "chemometrics/validation-application/#instrument-qc",
  folderWatches: "chemometrics/validation-application/#local-folder-watches",
  referenceValues: "chemometrics/validation-application/#reference-values",
  displayExports: "workflows/reports-exports/#display-and-table-exports",
  workflowExclusions: "workflows/build-a-workflow/#workflow-wide-observation-exclusions",
  shortSummary: "workflows/reports-exports/#short-summary-default",
  batch: "workflows/projects-datasets-runs/#batch-execution",
  availability: "workflows/projects-datasets-runs/#availability-lights",
  previewSelection: "workflows/data-import/#preview-and-workflow-selection",
  localChat: "onboarding/scientific-assistance/#local-basic-chat",
  hitran: "workflows/references-synthesis/#hitranhapi-synthesis",
  referenceLibrary: "workflows/references-synthesis/#nist-library",
  applicationAccess: "onboarding/local-30-minutes/#application-access",
} as const;
export type MethodTopic = keyof typeof METHOD_TOPICS;
export function resolveMethodHelpUrl(topic: unknown): string | null {
  return typeof topic === "string" && Object.prototype.hasOwnProperty.call(METHOD_TOPICS, topic)
    ? `${DOCS_BASE_URL}/${METHOD_TOPICS[topic as MethodTopic]}` : null;
}
