/* eslint-disable @typescript-eslint/no-explicit-any -- Plotly trace and layout payloads. */
import type { NodeOutput } from "@/utils/nodeOutput";

export interface PlotMetaSlice {
  hasOutput: boolean;
  availablePlots: string[];
  nodeTypeKey: string;
  isRegressionComparison: boolean;
  isPCAOutput: boolean;
  isPreprocessingNode: boolean;
  isDataNode: boolean;
  isSpectraData: boolean;
  isGenericDataNode: boolean;
  nodeOutput: NodeOutput | null;
  contourClickPoint: { sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null;
  pcaAxisOptions: { label: string; value: number }[];
  regressionTargetOptions: { label: string; value: number }[];
  spectraDisplayOptions: { label: string; value: string }[];
  genericDisplayOptions: { label: string; value: string }[];
  featureOptions: { label: string; value: number }[];
  holdoutVisualization: Record<string, any> | null;
  scoreColorOptions: { label: string; value: string }[];
  spectraOverlayNotice: string;
  metadataGroupingError: string;
  sampleColorFieldOptions: { label: string; value: string }[];
  sampleSymbolFieldOptions: { label: string; value: string }[];
  featureScaleOptions: { label: string; value: string }[];
  featureLabelSetOptions: { label: string; value: string }[];
  featureTitleSetOptions: { label: string; value: string }[];
  sampleLabelSetOptions: { label: string; value: string }[];
  axisSetError: string;
}

export interface PcaPlotSlice {
  pcaScoresData: any[];
  pcaScoresLayout: Record<string, any>;
  pcaScoresConfig: Record<string, any>;
  pcaBiplotData: any[];
  pcaBiplotLayout: Record<string, any>;
  pcaLoadingsData: any[];
  pcaLoadingsLayout: Record<string, any>;
  pcaLoadingsConfig: Record<string, any>;
  pcaScreeData: any[];
  pcaScreeLayout: Record<string, any>;
  pcaDiagnosticsData: any[];
  pcaDiagnosticsLayout: Record<string, any>;
}

export interface McrPlotSlice {
  mcrConcentrationData: any[];
  mcrConcentrationLayout: Record<string, any>;
  mcrConcentrationHeatmapData: any[];
  mcrConcentrationHeatmapLayout: Record<string, any>;
  mcrSpectraData: any[];
  mcrSpectraLayout: Record<string, any>;
  mcrValidationScatterData: any[];
  mcrValidationScatterLayout: Record<string, any>;
  mcrValidationSpectrumData: any[];
  mcrValidationSpectrumLayout: Record<string, any>;
  mcrOriginalContourData: any[];
  mcrOriginalContourLayout: Record<string, any>;
  mcrReconstructedContourData: any[];
  mcrReconstructedContourLayout: Record<string, any>;
  mcrResidualContourData: any[];
  mcrResidualContourLayout: Record<string, any>;
}

export interface EfaPlotSlice {
  efaEigenvalueData: any[];
  efaEigenvalueLayout: Record<string, any>;
}

export interface ClassificationPlotSlice {
  classificationScoresData: any[];
  classificationScoresLayout: Record<string, any>;
  plsdaLoadingsData: any[];
  plsdaLoadingsLayout: Record<string, any>;
  plsdaVipData: any[];
  plsdaVipLayout: Record<string, any>;
  plsdaConfusionTrainData: any[];
  plsdaConfusionTrainLayout: Record<string, any>;
  plsdaConfusionCVData: any[];
  plsdaConfusionCVLayout: Record<string, any>;
  classificationAccuracyData: any[];
  classificationAccuracyLayout: Record<string, any>;
}

export interface RegressionPlotSlice {
  regressionCorrelationData: any[];
  regressionCorrelationLayout: Record<string, any>;
  plsVipData: any[];
  plsVipLayout: Record<string, any>;
  plsExplainedVarianceData: any[];
  plsExplainedVarianceLayout: Record<string, any>;
}

export interface OverviewPlotSlice {
  hcaDendrogramData: any[];
  hcaDendrogramLayout: Record<string, any>;
  peakFindingPlotData: any[];
  peakFindingPlotLayout: Record<string, any>;
  peakFindingPlotLabel: string;
  libraryComparePlotData: any[];
  libraryComparePlotLayout: Record<string, any>;
  plotNodeData: any[];
  plotNodeLayout: Record<string, any>;
  plotNodeWarning: string;
}

export interface SpectraPlotSlice {
  spectraOverlayData: any[];
  spectraOverlayLayout: Record<string, any>;
  spectraContourData: any[];
  spectraContourLayout: Record<string, any>;
  horizontalSliceData: any[];
  horizontalSliceLayout: Record<string, any>;
  verticalSliceData: any[];
  verticalSliceLayout: Record<string, any>;
}

export interface GenericPlotSlice {
  genericBoxPlotData: any[];
  genericBoxPlotLayout: Record<string, any>;
  genericScatterData: any[];
  genericScatterLayout: Record<string, any>;
}

export interface DiagnosticsPlotSlice {
  clusterScatterData: any[];
  clusterScatterLayout: Record<string, any>;
  outlierChartData: any[];
  outlierChartLayout: Record<string, any>;
  holdoutConfusionData: any[];
  holdoutConfusionLayout: Record<string, any>;
  holdoutRegressionData: any[];
  holdoutRegressionLayout: Record<string, any>;
  statsPlotData: any[];
  statsPlotLayout: Record<string, any>;
}

export type PlotDataBag = PlotMetaSlice &
  PcaPlotSlice &
  McrPlotSlice &
  EfaPlotSlice &
  ClassificationPlotSlice &
  RegressionPlotSlice &
  OverviewPlotSlice &
  SpectraPlotSlice &
  GenericPlotSlice &
  DiagnosticsPlotSlice;

// ── Writable refs (edited via v-model emit pairs from panels) ───────────
