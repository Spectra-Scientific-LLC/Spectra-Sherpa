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
  operation?: string;
  parameters?: Record<string, any>;
  input_shape?: number[];
  output_shape?: number[];
}

export interface ProvenanceInfo {
  source_type?: string;
  operations?: string[];
  last_modified?: string;
  [key: string]: any;
}

export interface QualitySummary {
  latest_model_type?: string;
  latest_r2?: number;
  latest_rmse?: number;
  n_evaluations?: number;
  [key: string]: any;
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

// ── Plot data bag (untyped for now; tightening to per-family slices is
//    follow-up #24b; this still beats the old `state: any`) ──────────────

export interface PlotDataBag {
  hasOutput: boolean;
  availablePlots: any[];
  nodeTypeKey: string;
  isPCAOutput: boolean;
  isPreprocessingNode: boolean;
  isDataNode: boolean;
  isSpectraData: boolean;
  isGenericDataNode: boolean;
  nodeOutput: NodeOutput | null;
  contourClickPoint: { sampleIdx: number; wavenumber: number } | null;
  pcaAxisOptions: { label: string; value: number }[];
  regressionTargetOptions: { label: string; value: number }[];
  spectraDisplayOptions: { label: string; value: string }[];
  genericDisplayOptions: { label: string; value: string }[];
  featureOptions: { label: string; value: number }[];
  holdoutVisualization: Record<string, any> | null;
  // Plot data + layout pairs. Typed as any — the individual plotly shapes
  // vary too widely to tighten meaningfully in this commit.
  [key: string]: any;
}

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
