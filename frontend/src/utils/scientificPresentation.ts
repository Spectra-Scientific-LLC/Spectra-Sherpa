import type {
  NodePresentationContract,
  NodeTypeMetadata,
  ScientificPresentation,
  ScientificPresentationMode,
} from "@/types";
import type { NodeOutput, PortOutput } from "@/utils/nodeOutput";
import rendererAuthority from "@/utils/scientific-presentation-renderers.json";
import { t2QDiagnosticRows } from "@/utils/scientificPlots";

export interface ResolvedScientificPresentation {
  contractDigest: string;
  presentation: ScientificPresentation;
  sourcePort: string;
  sourcePorts: string[];
  portOutput: PortOutput;
  portOutputs: Record<string, PortOutput>;
}

export interface ScientificPlotOption {
  key: string;
  label: string;
}

export interface ProjectedPresentationIdentity {
  schema_version: "spectrasherpa-node-presentation/1";
  contract_digest: string;
  presentation_id: string;
  label: string;
  kind: string;
  source_port: string;
  source_ports: string[];
  modes: ScientificPresentationMode[];
  description: string;
}

export interface ScientificEvidenceShape {
  rows: number;
  cols: number;
  rowLabel: string;
  colLabel: string;
}

type RendererAuthority = {
  schema_version: "spectrasherpa-scientific-presentation-renderers/1";
  plot_kinds: Record<
    string,
    { strategy: string; plots: Array<{ key: string; label: string }> }
  >;
  record_views: Record<
    string,
    { strategy: string; plots: Array<{ key: string; label: string }> }
  >;
};

const renderers = rendererAuthority as RendererAuthority;

export class ScientificPresentationError extends Error {}

const populatedMetadata = (metadata: Record<string, unknown> | null | undefined) =>
  Object.fromEntries(
    Object.entries(metadata ?? {}).filter(([, value]) => {
      if (value === null || value === undefined) return false;
      if (typeof value === "string" && value.trim().length === 0) return false;
      if (Array.isArray(value) && value.length === 0) return false;
      if (
        typeof value === "object" &&
        !Array.isArray(value) &&
        Object.keys(value).length === 0
      ) {
        return false;
      }
      return true;
    }),
  );

const contractPayload = (
  metadata: NodeTypeMetadata | null | undefined,
  output?: NodeOutput | null,
): NodePresentationContract | null =>
  output?.presentation_contract ?? metadata?.presentation_contract ?? null;

export const availableScientificPresentations = (
  metadata: NodeTypeMetadata | null | undefined,
  output: NodeOutput | null | undefined,
): ResolvedScientificPresentation[] => {
  const contract = contractPayload(metadata, output);
  if (!contract || !output?.ports) return [];
  return contract.payload.presentations.flatMap((presentation) => {
    const portOutputs = Object.fromEntries(
      presentation.source_ports.flatMap((sourcePort) => {
        const portOutput = output.ports?.[sourcePort];
        return portOutput ? [[sourcePort, portOutput] as const] : [];
      }),
    );
    const sourcePort = presentation.source_ports[0];
    const portOutput = sourcePort ? portOutputs[sourcePort] : undefined;
    return sourcePort &&
      portOutput &&
      Object.keys(portOutputs).length === presentation.source_ports.length
      ? [
          {
            contractDigest: contract.digest,
            presentation,
            sourcePort,
            sourcePorts: [...presentation.source_ports],
            portOutput,
            portOutputs,
          },
        ]
      : [];
  });
};

export const resolveScientificPresentation = (
  metadata: NodeTypeMetadata | null | undefined,
  output: NodeOutput | null | undefined,
  presentationId?: string | null,
): ResolvedScientificPresentation | null => {
  const available = availableScientificPresentations(metadata, output);
  if (available.length === 0) return null;
  const contract = contractPayload(metadata, output);
  const requested = presentationId || contract?.payload.default_presentation;
  return available.find((item) => item.presentation.presentation_id === requested) ?? null;
};

export const presentationSupports = (
  resolved: ResolvedScientificPresentation | null | undefined,
  mode: ScientificPresentationMode,
): boolean => !!resolved && (
  resolved.presentation.modes.includes(mode) ||
  // The retained PLS curve was originally declared as a record. Plotting
  // that same exact record is a client-side view, not a fitted-state or
  // execution-contract change (which would invalidate saved models).
  (mode === "plot" && !!renderers.record_views[`${resolved.presentation.kind}:${resolved.presentation.presentation_id}:${resolved.sourcePort}`]
    && resolved.presentation.modes.includes("record"))
);

export const presentationResolutionError = (
  metadata: NodeTypeMetadata | null | undefined,
  output: NodeOutput | null | undefined,
  presentationId?: string | null,
): string | null => {
  const contract = contractPayload(metadata, output);
  if (!contract) return "Scientific presentation contract is unavailable.";
  if (!output?.ports) return "Executed result does not contain typed output ports.";
  const requested =
    contract.payload.presentations.find(
      (item) => item.presentation_id === (presentationId || contract.payload.default_presentation),
    ) ?? null;
  if (!requested) return "Requested scientific presentation is not declared by the node contract.";
  const missing = requested.source_ports.filter((sourcePort) => !output.ports?.[sourcePort]);
  return missing.length
    ? `Scientific presentation is missing declared source port${missing.length === 1 ? "" : "s"}: ${missing.join(", ")}.`
    : null;
};

export const projectedPresentationIdentity = (
  output: NodeOutput | null | undefined,
): ProjectedPresentationIdentity | null => {
  const identity = output?.metadata?.scientific_presentation;
  if (!identity || typeof identity !== "object" || Array.isArray(identity)) return null;
  const candidate = identity as Partial<ProjectedPresentationIdentity>;
  if (
    candidate.schema_version !== "spectrasherpa-node-presentation/1" ||
    typeof candidate.contract_digest !== "string" ||
    typeof candidate.presentation_id !== "string" ||
    typeof candidate.kind !== "string" ||
    typeof candidate.source_port !== "string" ||
    !Array.isArray(candidate.source_ports) ||
    !Array.isArray(candidate.modes)
  ) {
    return null;
  }
  return candidate as ProjectedPresentationIdentity;
};

/**
 * Test scientist-facing behavior against the selected persisted presentation.
 *
 * Operation identifiers deliberately do not participate in this decision: a
 * newly registered operation inherits the same behavior by publishing the
 * same closed scientific kind.
 */
export const isProjectedScientificKind = (
  output: NodeOutput | null | undefined,
  kind: string,
): boolean => projectedPresentationIdentity(output)?.kind === kind;

export const scientificPlotOptions = (
  output: NodeOutput | null | undefined,
): ScientificPlotOption[] => {
  const identity = projectedPresentationIdentity(output);
  if (!identity || (!identity.modes.includes("plot")
    && !(renderers.record_views[`${identity.kind}:${identity.presentation_id}:${identity.source_port}`]
      && identity.modes.includes("record")))) return [];
  // A retained PLS component record has a narrowly scoped client-side chart;
  // it is not a live plot kind in the execution/presentation contract.
  const renderer = identity.modes.includes("plot")
    ? renderers.plot_kinds[identity.kind]
    : renderers.record_views[`${identity.kind}:${identity.presentation_id}:${identity.source_port}`];
  if (!renderer) {
    throw new ScientificPresentationError(
      `No renderer is declared for scientific presentation kind ${identity.kind}.`,
    );
  }
  if (renderer.strategy !== "declared_visualization") {
    if (
      identity.kind === "pca_scores" &&
      output?.ports?.variable_correlations &&
      output.ports.explained_variance
    ) {
      return [
        ...(Number(output.metadata?.n_components) > 1 ||
          (Array.isArray(output.data?.[0]) && output.data[0].length > 1) ||
          (Array.isArray(output.metadata?.pc_labels) && output.metadata.pc_labels.length > 1)
          ? [{ key: "scientific_pca_summary", label: "PCA Summary" }]
          : []),
        ...renderer.plots.map((item) => ({ ...item })),
        { key: "scientific_pca_variable_correlations", label: "Variable Correlations" },
      ];
    }
    if (
      identity.kind === "spectral_dataset" &&
      output?.metadata?.scientific_matrix_role === "component_concentrations"
    ) {
      return renderer.plots.map((item) => ({
        ...item,
        label:
          item.key === "scientific_spectral_overlay"
            ? "Concentration Profiles"
            : "Concentration Heatmap",
      }));
    }
    if (
      identity.kind === "spectral_dataset" &&
      output?.metadata?.scientific_matrix_role === "component_spectra"
    ) {
      return renderer.plots.map((item) => ({
        ...item,
        label:
          item.key === "scientific_spectral_overlay"
            ? "Component Spectra"
            : "Component Spectra Heatmap",
      }));
    }
    if (identity.kind === "spectral_dataset" && output?.metadata?.data_role === "X_features") {
      return renderer.plots.map((item) => ({
        ...item,
        label: item.key === "scientific_spectral_overlay" ? "Feature Distributions" : "Feature Heatmap",
      }));
    }
    return renderer.plots.map((item) => ({ ...item }));
  }

  const value = output?.presentation_value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return renderer.plots.map((item) => ({ ...item }));
  const record = value as Record<string, unknown>;
  if (Array.isArray(record.data) && record.layout && typeof record.layout === "object") {
    return renderer.plots.map((item) => ({ ...item }));
  }
  const nested = Object.entries(record).flatMap(([key, candidate]) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return [];
    const plot = candidate as Record<string, unknown>;
    if (!Array.isArray(plot.data)) return [];
    const label = key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (character) => character.toUpperCase());
    return [{ key: `scientific_visualization:${key}`, label }];
  });
  if (nested.length === 1) {
    nested[0].label = identity.label;
  }
  return nested.length > 0 ? nested : renderer.plots.map((item) => ({ ...item }));
};

export const scientificEvidenceShape = (
  output: NodeOutput | null | undefined,
): ScientificEvidenceShape | null => {
  const identity = projectedPresentationIdentity(output);
  if (identity?.kind === "peak_table") {
    const value = output?.presentation_value as {data?: unknown} | undefined;
    if (Array.isArray(value?.data)) return {rows: value.data.length, cols: 0, rowLabel: "peaks", colLabel: ""};
  }
  if (identity?.kind === "t2_q_diagnostics") {
    const rows = t2QDiagnosticRows(output?.presentation_value, output?.metadata || {});
    return { rows: rows.length, cols: rows.length > 0 ? 2 : 0,
      rowLabel: rows.length === 1 ? "sample" : "samples", colLabel: "statistics" };
  }
  if (identity?.kind === "validation_result" && identity.presentation_id === "component_selection"
    && identity.source_port === "component_curve") {
    const curve = output?.presentation_value as Record<string, unknown> | undefined;
    if (Array.isArray(curve?.calibration) && Array.isArray(curve?.response_names)) {
      return { rows: curve.calibration.length, cols: curve.response_names.length,
        rowLabel: "component choices", colLabel: "responses" };
    }
    if (Array.isArray(curve?.calibration) && [
      "spectrasherpa-pca-component-curve/1", "spectrasherpa-plsda-component-curve/1",
    ].includes(String(curve.schema_version))) {
      return { rows: curve.calibration.length, cols: 1,
        rowLabel: "component choices", colLabel: "metric" };
    }
  }
  if (identity?.kind === "out_of_fold_evidence") {
    const value = output?.presentation_value as Record<string, unknown> | undefined;
    if (Array.isArray(value?.observations) && Array.isArray(value?.predictions)
      && value.observations.length === value.predictions.length) {
      return { rows: value.observations.length, cols: 1, rowLabel: "held-out samples", colLabel: "target" };
    }
    return null;
  }
  if (identity?.kind === "salient_features") {
    const value = output?.presentation_value as Record<string, unknown> | undefined;
    const rows = Array.isArray(value?.features) ? value.features.length : 0;
    const cols = Number(value?.n_total_variables);
    if (Number.isInteger(cols) && cols >= 0) {
      return { rows, cols, rowLabel: "features", colLabel: "source variables" };
    }
  }
  if (identity?.presentation_id !== "peak_overlay") return null;

  const diagnostics =
    output?.metadata?.diagnostics &&
    typeof output.metadata.diagnostics === "object" &&
    !Array.isArray(output.metadata.diagnostics)
      ? (output.metadata.diagnostics as Record<string, unknown>)
      : {};
  const nSamples = Number(output?.metadata?.n_samples ?? diagnostics.n_samples);
  const nPeaks = Number(output?.metadata?.n_peaks ?? diagnostics.n_peaks);
  if (!Number.isInteger(nSamples) || nSamples < 0 || !Number.isInteger(nPeaks) || nPeaks < 0) {
    return null;
  }
  return {
    rows: nSamples,
    cols: nPeaks,
    rowLabel: nSamples === 1 ? "spectrum" : "spectra",
    colLabel: nPeaks === 1 ? "peak detection" : "peak detections",
  };
};

export const projectScientificPresentation = (
  output: NodeOutput | null | undefined,
  resolved: ResolvedScientificPresentation | null | undefined,
): NodeOutput | null => {
  if (!output || !resolved) return null;
  const { portOutput, portOutputs, presentation, sourcePort, sourcePorts, contractDigest } = resolved;
  let presentationValue =
    sourcePorts.length === 1
      ? portOutput.value
      : Object.fromEntries(sourcePorts.map((port) => [port, portOutputs[port].value]));
  const parentMetadata = { ...output.metadata };
  if (sourcePort !== output.primary_port) {
    // The primary output's axes do not describe another result merely because
    // it shares a node (e.g. held-out targets, centroids, or pure spectra).
    for (const key of ["sample_labels", "source_labels", "labels", "sample_table", "include_mask",
      "wavenumbers", "x_axis", "y_axis", "feature_names", "x_title", "x_units", "y_title", "y_units", "scientific_matrix_role"]) {
      delete parentMetadata[key];
    }
  }
  const projectedMetadata: Record<string, unknown> = {
    ...parentMetadata,
    ...populatedMetadata(portOutput.metadata),
  };
  if (presentation.kind === "regression_comparison" && presentationValue && typeof presentationValue === "object" && !Array.isArray(presentationValue)) {
    const record = presentationValue as Record<string, unknown>;
    const metadata = record.metadata && typeof record.metadata === "object" ? record.metadata as Record<string, unknown> : {};
    const diagnostics = output.metadata.diagnostics as Record<string, unknown> | undefined;
    const identity = diagnostics?.response_identity as { names?: unknown; units?: unknown } | undefined;
    // The exact model/evaluator's own response identity may qualify its comparison;
    // never borrow the source X's signal units or another response's declaration.
    if (Array.isArray(metadata.target_names) && Array.isArray(identity?.names)
      && JSON.stringify(metadata.target_names) === JSON.stringify(identity.names)
      && Array.isArray(identity.units) && identity.units.length === identity.names.length) {
      presentationValue = { ...record, metadata: { ...metadata, response_identity: identity, target_units: identity.units } };
      projectedMetadata.response_identity = identity;
      projectedMetadata.target_units = identity.units;
    }
  }
  if (sourcePort === "train_indices" || sourcePort === "test_indices") {
    // Parent metadata describes the primary (usually training) dataset, not
    // this index vector. Never borrow its row identities for another split.
    for (const key of ["sample_labels", "source_labels", "labels", "diagnostics"]) delete projectedMetadata[key];
    const indices = portOutput.data;
    const subset = output.ports?.[sourcePort === "train_indices" ? "X_train" : "X_test"];
    const value = subset?.value as Record<string, any> | undefined;
    const labels = value?.y_axis?.labels ?? value?.sample_axis?.labels;
    if (Array.isArray(indices) && indices.every((index): index is number => typeof index === "number" && Number.isSafeInteger(index) && index >= 0)) {
      projectedMetadata.sample_labels = Array.isArray(labels) && labels.length === indices.length
        ? labels : indices.map(index => `Source row ${index + 1}`);
    }
  }
  if (presentation.kind === "target_matrix") {
    for (const key of [
      "wavenumbers",
      "x_axis",
      "feature_names",
      "x_title",
      "x_units",
      "spectral_technique",
      "data_quantity",
      "value_units",
      "data_role",
      "data_modality",
      "sherpa.data_role",
      "sherpa.data_modality",
    ]) {
      delete projectedMetadata[key];
    }
    // X's measurement units do not describe Y. Only response authority may
    // supply response units (categorical references often have none).
    if (projectedMetadata.target_units != null) {
      projectedMetadata.value_units = projectedMetadata.target_units;
    }
    projectedMetadata.data_type = "targets";
    projectedMetadata.is_spectra = false;
  }
  let data = portOutput.data;
  if (presentation.kind === "classification_responses") {
    // Response columns are classes, not the parent model's latent variables.
    for (const key of ["pc_labels", "component_labels", "feature_names", "x_axis", "wavenumbers", "x_units"]) {
      delete projectedMetadata[key];
    }
    const width = Array.isArray(data) && Array.isArray(data[0]) ? data[0].length : 0;
    const classes = projectedMetadata.label_categories ?? projectedMetadata.classes;
    projectedMetadata.feature_names = Array.isArray(classes) && classes.length === width
      ? classes.map(String)
      : Array.from({ length: width }, (_, index) => `Class ${index + 1}`);
    projectedMetadata.x_title = "Response class";
  }
  if (presentation.kind === "out_of_fold_evidence" && presentationValue && typeof presentationValue === "object") {
    const evidence = presentationValue as Record<string, unknown>;
    const { observations, predictions, fold_assignments: folds } = evidence;
    data = Array.isArray(observations) && Array.isArray(predictions) && Array.isArray(folds)
      && observations.length === predictions.length && observations.length === folds.length
      ? observations.map((observation, index) => ({ observation, prediction: predictions[index], fold_index: folds[index] }))
      : [];
  }
  return {
    ...output,
    data: presentation.kind === "salient_features"
      && presentationValue && typeof presentationValue === "object"
      && "features" in presentationValue && Array.isArray(presentationValue.features)
      ? presentationValue.features
      : data,
    metadata: {
      ...projectedMetadata,
      ...(portOutput.descriptor ? { scientific_value: portOutput.descriptor } : {}),
      scientific_presentation: {
        schema_version: "spectrasherpa-node-presentation/1",
        contract_digest: contractDigest,
        presentation_id: presentation.presentation_id,
        label: presentation.label,
        kind: presentation.kind,
        source_port: sourcePort,
        source_ports: sourcePorts,
        modes: presentation.modes,
        description: presentation.description,
      },
    },
    plots: portOutput.plots,
    descriptor: portOutput.descriptor,
    primary_port: sourcePort,
    presentation_value: presentationValue,
  };
};
