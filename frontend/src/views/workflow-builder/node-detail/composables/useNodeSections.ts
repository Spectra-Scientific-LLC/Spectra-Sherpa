import { ref } from "vue";

export type TopLevelSection = "input" | "settings" | "output" | "plots" | "log";
export type OutputSubsection =
  | "coordinates"
  | "metadata"
  | "processing"
  | "provenance"
  | "quality"
  | "ports";

const DEFAULT_PLOT_SECTIONS: Record<string, boolean> = {
  pcaScores: false,
  pcaBiplot: false,
  pcaLoadings: false,
  pcaScree: false,
  pcaDiagnostics: false,
  mcrConcentrations: false,
  mcrSpectra: false,
  spectraOverview: false,
  dataOverview: false,
  statsDistribution: false,
  plsScores: false,
  plsLoadings: false,
  classificationScores: false,
  plsdaLoadings: false,
  plsdaVip: false,
  plsdaConfusionTrain: false,
  plsdaConfusionCV: false,
  regressionCorrelation: false,
  classificationAccuracy: false,
  hcaDendrogram: false,
  peakFinding: false,
  plotVisualization: false,
  efaEigenvalues: false,
  evaluationResults: true,
  clusterScatter: true,
  outlierChart: true,
};

export function useNodeSections() {
  const sections = ref<Record<TopLevelSection, boolean>>({
    input: false,
    settings: false,
    output: false,
    plots: false,
    log: false,
  });

  const outputSubsections = ref<Record<OutputSubsection, boolean>>({
    coordinates: false,
    metadata: false,
    processing: false,
    provenance: false,
    quality: false,
    ports: false,
  });

  const plotSections = ref<Record<string, boolean>>({ ...DEFAULT_PLOT_SECTIONS });

  const toggleSection = (section: TopLevelSection) => {
    sections.value[section] = !sections.value[section];
  };

  const toggleOutputSubsection = (section: OutputSubsection) => {
    outputSubsections.value[section] = !outputSubsections.value[section];
  };

  const togglePlot = (plot: string) => {
    plotSections.value[plot] = !plotSections.value[plot];
  };

  return {
    sections,
    outputSubsections,
    plotSections,
    toggleSection,
    toggleOutputSubsection,
    togglePlot,
  };
}
