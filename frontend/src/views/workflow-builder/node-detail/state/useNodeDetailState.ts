/**
 * Canonical state boundary for NodeDetailView.
 *
 * Replaces the previous pattern (26 props on OutputPanel, `state: any` on
 * PlotsPanel, 60-field `plotState` aggregate in the shell) with a single
 * typed object that the shell `provide`s and panels `inject`.
 *
 * Scope of this first step (issue #24a): typed boundary + provide/inject
 * wiring only. The reactive refs and computeds themselves still live in
 * NodeDetailView.vue; this composable just bundles them into one object.
 * Moving the ref/computed definitions into dedicated composables
 * (`useNodePlotData`, `useNodeOutputData`) is a follow-up — the goal here
 * is eliminating the untyped contract and long prop lists, not shrinking
 * the shell file yet.
 */

import type { InjectionKey, Ref } from "vue";
import type { NodeOutput } from "@/utils/nodeOutput";
import type { OutputSubsection } from "../composables/useNodeSections";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Readonly slices ─────────────────────────────────────────────────────

export interface OutputStats {
  rows?: number;
  cols?: number;
  type?: string;
  range?: number[] | null;
}

export interface DatasetInfo {
  title?: string;
  isSpectra?: boolean;
  spectralTechnique?: string;
  dataQuantity?: string;
  valueUnits?: string;
  xAxis?: {
    title: string;
    units?: string;
    points?: number;
    range?: [number, number];
  };
  yAxis?: {
    title: string;
    units?: string;
    nSamples?: number;
    labels?: string[];
  };
}

export interface ProcessingStep {
  op_id?: string;
  operation?: string;
  parameters?: Record<string, any>;
  input_shape?: number[];
  output_shape?: number[];
  timestamp?: string;
  node_id?: string;
}

export interface ProvenanceInfo {
  source_type?: string;
  operations?: string[];
  last_modified?: string;
  /** Catch-all for backend-supplied keys not covered above. */
  extras?: Record<string, unknown>;
}

export interface QualitySummary {
  latest_model_type?: string;
  latest_r2?: number;
  latest_rmse?: number;
  n_evaluations?: number;
  /** Catch-all for backend-supplied keys not covered above. */
  extras?: Record<string, unknown>;
}

export interface PortSummary {
  name: string;
  type?: string;
  shape?: number[];
  title?: string;
  xTitle?: string;
  xUnits?: string;
  xPoints?: number;
  yTitle?: string;
  nLabels?: number;
}

export interface PreviewTable {
  rows: any[];
  columns: { field: string; header: string }[];
  summary: string;
}

export interface OutputSlice {
  summary: Ref<string>;
  hasOutput: Ref<boolean>;
  data: Ref<OutputStats | null | undefined>;
  metadata: Ref<Record<string, any>>;
  subsections: Ref<Record<OutputSubsection, boolean>>;
  datasetInfo: Ref<DatasetInfo | null>;
  datasetLabelTable: Ref<{ headers: string[]; rows: string[][] }>;
  labelPreviewLimit: number;
  processingHistory: Ref<ProcessingStep[] | null>;
  provenance: Ref<ProvenanceInfo | null>;
  quality: Ref<QualitySummary | null>;
  portSummaries: Ref<PortSummary[]>;
  preview: Ref<PreviewTable>;
  pcaDiagnostics: Ref<PreviewTable>;
  isRegressionNode: Ref<boolean>;
  regressionTargetOptions: Ref<{ label: string; value: number }[]>;
  selectedRegressionR2: Ref<number | null>;
  selectedRegressionRmse: Ref<number | null>;
  getMetaTooltip: (key: string) => string;
  formatMetaValue: (value: any) => string;
}

// ── Plot data bag: per-family slices ──────────────────────────────────
//
// Runtime shape is still flat (panels read `state.plots.value.pcaScoresData`)
// so the consumer contract is unchanged, but the type is now an intersection
// of per-family slices so editors can autocomplete within a family and
// unrelated keys no longer resolve to `any`. Plotly trace/layout payloads
// remain typed as `any` — tightening those is out of scope for this PR and
// would require a plotly type dependency.
//
// When adding a new plot family, add its slice interface here and include
// it in the intersection at the bottom.

export interface PlotMetaSlice {
  hasOutput: boolean;
  availablePlots: string[];
  nodeTypeKey: string;
  isPCAOutput: boolean;
  isPreprocessingNode: boolean;
  isDataNode: boolean;
  isSpectraData: boolean;
  isGenericDataNode: boolean;
  nodeOutput: NodeOutput | null;
  contourClickPoint:
    | { sampleIdx: number; wavenumberIdx: number; wavenumber: number }
    | null;
  pcaAxisOptions: { label: string; value: number }[];
  regressionTargetOptions: { label: string; value: number }[];
  spectraDisplayOptions: { label: string; value: string }[];
  genericDisplayOptions: { label: string; value: string }[];
  featureOptions: { label: string; value: number }[];
  holdoutVisualization: Record<string, any> | null;
}

export interface PcaPlotSlice {
  pcaScoresData: any[]; pcaScoresLayout: Record<string, any>; pcaScoresConfig: Record<string, any>;
  pcaBiplotData: any[]; pcaBiplotLayout: Record<string, any>;
  pcaLoadingsData: any[]; pcaLoadingsLayout: Record<string, any>; pcaLoadingsConfig: Record<string, any>;
  pcaScreeData: any[]; pcaScreeLayout: Record<string, any>;
  pcaDiagnosticsData: any[]; pcaDiagnosticsLayout: Record<string, any>;
}

export interface McrPlotSlice {
  mcrConcentrationData: any[]; mcrConcentrationLayout: Record<string, any>;
  mcrSpectraData: any[]; mcrSpectraLayout: Record<string, any>;
}

export interface EfaPlotSlice {
  efaEigenvalueData: any[]; efaEigenvalueLayout: Record<string, any>;
}

export interface PlsPlotSlice {
  plsScoresData: any[]; plsScoresLayout: Record<string, any>;
  plsLoadingsData: any[]; plsLoadingsLayout: Record<string, any>;
}

export interface ClassificationPlotSlice {
  classificationScoresData: any[]; classificationScoresLayout: Record<string, any>;
  plsdaLoadingsData: any[]; plsdaLoadingsLayout: Record<string, any>;
  plsdaVipData: any[]; plsdaVipLayout: Record<string, any>;
  plsdaConfusionTrainData: any[]; plsdaConfusionTrainLayout: Record<string, any>;
  plsdaConfusionCVData: any[]; plsdaConfusionCVLayout: Record<string, any>;
  classificationAccuracyData: any[]; classificationAccuracyLayout: Record<string, any>;
}

export interface RegressionPlotSlice {
  regressionCorrelationData: any[]; regressionCorrelationLayout: Record<string, any>;
}

export interface OverviewPlotSlice {
  hcaDendrogramData: any[]; hcaDendrogramLayout: Record<string, any>;
  peakFindingPlotData: any[]; peakFindingPlotLayout: Record<string, any>;
  plotNodeData: any[]; plotNodeLayout: Record<string, any>;
}

export interface SpectraPlotSlice {
  spectraOverlayData: any[]; spectraOverlayLayout: Record<string, any>;
  spectraContourData: any[]; spectraContourLayout: Record<string, any>;
  horizontalSliceData: any[]; horizontalSliceLayout: Record<string, any>;
  verticalSliceData: any[]; verticalSliceLayout: Record<string, any>;
}

export interface GenericPlotSlice {
  genericBoxPlotData: any[]; genericBoxPlotLayout: Record<string, any>;
  genericScatterData: any[]; genericScatterLayout: Record<string, any>;
}

export interface DiagnosticsPlotSlice {
  clusterScatterData: any[]; clusterScatterLayout: Record<string, any>;
  outlierChartData: any[]; outlierChartLayout: Record<string, any>;
  holdoutConfusionData: any[]; holdoutConfusionLayout: Record<string, any>;
  holdoutRegressionData: any[]; holdoutRegressionLayout: Record<string, any>;
  statsPlotData: any[]; statsPlotLayout: Record<string, any>;
}

export type PlotDataBag = PlotMetaSlice &
  PcaPlotSlice &
  McrPlotSlice &
  EfaPlotSlice &
  PlsPlotSlice &
  ClassificationPlotSlice &
  RegressionPlotSlice &
  OverviewPlotSlice &
  SpectraPlotSlice &
  GenericPlotSlice &
  DiagnosticsPlotSlice;

// ── Writable refs (edited via v-model emit pairs from panels) ───────────

export interface WritableSlice {
  pcaXAxis: Ref<number>;
  pcaYAxis: Ref<number>;
  plsdaLoadingsViewMode: Ref<"lines" | "biplot">;
  regressionTargetIdx: Ref<number>;
  spectraDisplayMode: Ref<"overlay" | "contour">;
  genericDisplayMode: Ref<"boxplot" | "scatter">;
  featureXAxis: Ref<number>;
  featureYAxis: Ref<number>;
  contourClickPoint: Ref<
    { sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null
  >;
}

// ── Top-level state boundary ────────────────────────────────────────────

export interface NodeDetailState {
  output: OutputSlice;
  plots: Ref<PlotDataBag>;
  writable: WritableSlice;
  plotSections: Ref<Record<string, boolean>>;
}

export const NODE_DETAIL_STATE_KEY: InjectionKey<NodeDetailState> = Symbol(
  "NodeDetailState",
);
