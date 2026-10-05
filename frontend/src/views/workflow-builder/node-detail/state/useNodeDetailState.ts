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
  rowLabel?: string;
  colLabel?: string;
  type?: string;
  range?: number[] | null;
}

export interface DatasetInfo {
  title?: string;
  isSpectra?: boolean;
  isFeatureTable?: boolean;
  dataRole?: string;
  dataRoleLabel?: string;
  target?: {
    type: string;
    names?: string[];
  };
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
  qualification?: string | null;
  latest_model_type?: string;
  latest_r2?: number;
  latest_rmse?: number;
  n_evaluations?: number;
  /** Catch-all for backend-supplied keys not covered above. */
  extras?: Record<string, unknown>;
}

export interface PortSummary {
  name: string;
  label?: string;
  displayLabel: string;
  type?: string;
  shape?: number[];
  dimensions?: Array<{ role: string; size: number; labels?: string[] }>;
  title?: string;
  xTitle?: string;
  xUnits?: string;
  xPoints?: number;
  yTitle?: string;
  yCount?: number;
  yCountLabel?: string;
  /** @deprecated use yCount/yCountLabel. Retained for older tests/state. */
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
  presentationOptions: Ref<Array<{ label: string; value: string }>>;
  presentationError: Ref<string | null>;
  portSummaries: Ref<PortSummary[]>;
  preview: Ref<PreviewTable>;
  pcaDiagnostics: Ref<PreviewTable>;
  isRegressionComparison: Ref<boolean>;
  regressionTargetOptions: Ref<{ label: string; value: number }[]>;
  selectedRegressionR2: Ref<number | null>;
  selectedRegressionRmse: Ref<number | null>;
  /**
   * Artifact UID emitted by the executor when this node produced a saved
   * model (training nodes only). `null` for every other node.
   */
  modelId: Ref<string | null>;
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

export type * from "@/types/scientificPlotProjection";
import type { PlotDataBag } from "@/types/scientificPlotProjection";

export interface WritableSlice {
  selectedPresentationId: Ref<string | null>;
  pcaXAxis: Ref<number>;
  pcaYAxis: Ref<number>;
  scoreColorMode: Ref<string>;
  sampleColorField: Ref<string>;
  sampleSymbolField: Ref<string>;
  selectedFeatureScale: Ref<string>;
  selectedFeatureLabels: Ref<string>;
  selectedFeatureTitle: Ref<string>;
  selectedSampleLabels: Ref<string>;
  plsdaLoadingsViewMode: Ref<"lines" | "biplot">;
  regressionTargetIdx: Ref<number>;
  spectraDisplayMode: Ref<"overlay" | "contour">;
  genericDisplayMode: Ref<"boxplot" | "scatter">;
  featureXAxis: Ref<number>;
  featureYAxis: Ref<number>;
  contourClickPoint: Ref<{ sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null>;
}

// ── Top-level state boundary ────────────────────────────────────────────

export interface NodeDetailState {
  output: OutputSlice;
  plots: Ref<PlotDataBag>;
  writable: WritableSlice;
  plotSections: Ref<Record<string, boolean>>;
}

export const NODE_DETAIL_STATE_KEY: InjectionKey<NodeDetailState> = Symbol("NodeDetailState");
