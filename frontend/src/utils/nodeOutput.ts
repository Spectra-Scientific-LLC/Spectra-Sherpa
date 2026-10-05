import type { NodePortMetadata, NodePresentationContract } from "@/types";
import type {
  NodeScientificValueDescriptors,
  ScientificValueDescriptor,
} from "@/stores/workflow-types";

type UnknownRecord = Record<string, unknown>;

export interface PortOutput {
  data: unknown[];
  metadata: UnknownRecord;
  plots?: UnknownRecord;
  value?: unknown;
  type?: string;
  descriptor?: ScientificValueDescriptor;
}

export interface NodeOutput {
  data: unknown[];
  metadata: UnknownRecord;
  plots?: UnknownRecord;
  ports?: Record<string, PortOutput>;
  primary_port?: string;
  descriptor?: ScientificValueDescriptor;
  presentation_contract?: NodePresentationContract;
  /**
   * Exact value projected from the presentation contract's named source
   * port(s). Plot and table consumers use this value instead of reaching back
   * into the heterogeneous node-result map or inferring meaning from shape.
   */
  presentation_value?: unknown;
  /**
   * Artifact UID lifted onto the node output by the executor's
   * `_process_model_artifact` hook (executor.py sets `result["model_id"]`).
   * Present only for training-node runs that produced a saved artifact;
   * surfaces as the OutputPanel's "Saved Model Artifact" section. Must
   * be hoisted to the top level here (rather than buried inside `ports`)
   * because consumers like the WorkflowInspector packaging path and the
   * NodeDetailView shell read it directly.
   */
  model_id?: string | null;
}

const isRecord = (value: unknown): value is UnknownRecord => {
  return !!value && typeof value === "object" && !Array.isArray(value);
};

const isDatasetPayload = (value: unknown): value is UnknownRecord => {
  return isRecord(value) && value.type === "SherpaDataset";
};

const isModelPlaceholder = (value: unknown): value is UnknownRecord => {
  return isRecord(value) && "__model_placeholder__" in value;
};

const isExportArtifact = (value: unknown): value is UnknownRecord =>
  isRecord(value) && value.schema_version === "spectrasherpa-export-artifact/1";

interface PersistedPreview {
  data: unknown[];
  metadata: UnknownRecord;
}

const compactedSequencePreview = (value: unknown): unknown[] | null => {
  if (!isRecord(value) || value._truncated_sequence !== true || !Array.isArray(value.preview)) {
    return null;
  }
  return value.preview;
};

/**
 * Restore a display-only numerical preview from the current run-history
 * compaction record.  These values are never fed back into DAG execution;
 * the projection exists so a persisted scientist-facing plot/table remains
 * visibly inspectable and is clearly marked as a preview.
 */
const persistedRunPreview = (value: unknown): PersistedPreview | null => {
  const sequence = compactedSequencePreview(value);
  if (sequence) {
    return {
      data: sequence,
      metadata: {
        persisted_preview: true,
        data_truncated: true,
        original_length: isRecord(value) && typeof value.length === "number" ? value.length : null,
      },
    };
  }

  if (isRecord(value) && value._truncated_matrix === true && Array.isArray(value.preview)) {
    const rows = value.preview.flatMap((row) => {
      if (Array.isArray(row)) return [row];
      const preview = compactedSequencePreview(row);
      return preview ? [preview] : [];
    });
    if (rows.length > 0) {
      return {
        data: rows,
        metadata: {
          persisted_preview: true,
          data_truncated: true,
          original_rows: typeof value.rows === "number" ? value.rows : null,
        },
      };
    }
  }

  if (Array.isArray(value) && value.length > 0) {
    const rows = value.map(compactedSequencePreview);
    if (rows.every((row): row is unknown[] => row !== null)) {
      return {
        data: rows,
        metadata: {
          persisted_preview: true,
          data_truncated: true,
          original_rows: value.length,
        },
      };
    }
  }
  return null;
};

const normalizePortOutput = (value: unknown): PortOutput => {
  if (isDatasetPayload(value)) {
    return {
      data: Array.isArray(value.data) ? value.data : [],
      metadata: isRecord(value.metadata) ? value.metadata : {},
      plots: isRecord(value.plots) ? value.plots : undefined,
      value,
      type: "dataset",
    };
  }

  const persistedPreview = persistedRunPreview(value);
  if (persistedPreview) {
    return {
      data: persistedPreview.data,
      metadata: persistedPreview.metadata,
      value,
      type: "persisted-preview",
    };
  }

  if (Array.isArray(value)) {
    return {
      data: value,
      metadata: {},
      value,
      type: "array",
    };
  }

  if (isModelPlaceholder(value)) {
    return {
      data: [],
      metadata: value,
      value,
      type: "model",
    };
  }

  if (isExportArtifact(value)) {
    const { content: _content, ...metadata } = value;
    return {
      data: [],
      metadata,
      value,
      type: "export-artifact",
    };
  }

  if (isRecord(value)) {
    const data = Array.isArray(value.data) ? value.data : [];
    const metadata = isRecord(value.metadata) ? value.metadata : value;
    return {
      data,
      metadata,
      plots: isRecord(value.plots) ? value.plots : undefined,
      value,
      type: typeof value.type === "string" ? value.type : "object",
    };
  }

  return {
    data: [],
    metadata: { value },
    value,
    type: typeof value,
  };
};

const selectPrimaryPort = (
  ports: Record<string, PortOutput>,
  outputPorts?: NodePortMetadata[],
): string | undefined => {
  const declaredOrder = outputPorts?.map((port) => port.name) ?? Object.keys(ports);
  const viewablePort = declaredOrder.find((portName) => {
    const port = ports[portName];
    return !!port?.descriptor?.shape && port.descriptor.shape_valid;
  });
  if (ports.default?.descriptor?.shape && ports.default.descriptor.shape_valid) return "default";
  if (viewablePort) return viewablePort;
  if (ports.default) return "default";

  if (outputPorts && outputPorts.length > 0) {
    // Prefer a dataset-category port by inspecting the type_ref URI.
    // Include visualization and validation types so nodes like holdout_evaluation
    // surface their confusion matrix / predicted-vs-actual plot by default.
    const datasetTypeNames = new Set([
      "SpectralDataset",
      "Spectrum",
      "ScoreMatrix",
      "LoadingMatrix",
      "SpectralImage",
      "TimeSeries",
      "Array2D",
      "Array1D",
      "Visualization",
      "ValidationResult",
      "DecompositionResult",
      "RegressionModel",
      "ClassificationModel",
    ]);
    const datasetPort = outputPorts.find((port) => {
      const nameMatch = port.type_ref?.match(/\/([A-Za-z0-9_]+)\/\d+\.\d+$/);
      return nameMatch && datasetTypeNames.has(nameMatch[1]) && ports[port.name];
    });
    if (datasetPort) {
      return datasetPort.name;
    }

    // Prefer a port whose data array is non-empty over one that is empty.
    const firstWithData = outputPorts.find(
      (port) =>
        ports[port.name] &&
        Array.isArray(ports[port.name].data) &&
        ports[port.name].data.length > 0,
    );
    if (firstWithData) {
      return firstWithData.name;
    }

    const firstDefined = outputPorts.find((port) => ports[port.name]);
    if (firstDefined) {
      return firstDefined.name;
    }
  }

  const keys = Object.keys(ports);
  return keys.length > 0 ? keys[0] : undefined;
};

const attachDiagnostics = (output: NodeOutput, diagnostics?: UnknownRecord | null): NodeOutput => {
  if (!diagnostics || Object.keys(diagnostics).length === 0) {
    return output;
  }
  return {
    ...output,
    metadata: {
      ...output.metadata,
      diagnostics,
    },
  };
};

const nonEmptyStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean)
    : [];

const enrichSampleIdentityMetadata = (
  result: UnknownRecord,
  ports: Record<string, PortOutput>,
): void => {
  const sampleLabels = nonEmptyStringArray(result.sample_labels);
  if (sampleLabels.length === 0) return;

  for (const port of Object.values(ports)) {
    const rowCount = port.descriptor?.shape?.[0] ??
      (Array.isArray(port.data) ? port.data.length : null);
    if (rowCount !== sampleLabels.length) continue;
    const existingLabels = nonEmptyStringArray(port.metadata.sample_labels);
    if (existingLabels.length === sampleLabels.length) continue;
    port.metadata = { ...port.metadata, sample_labels: sampleLabels };
  }
};

const enrichTargetPortMetadata = (ports: Record<string, PortOutput>): void => {
  const dataset = Object.values(ports)
    .map((port) => port.value)
    .find(isDatasetPayload);
  if (!dataset) return;

  const targetContext = isRecord(dataset.target_context) ? dataset.target_context : {};
  const declaredNames = nonEmptyStringArray(targetContext.target_names);
  const fallbackName = [targetContext.selected_target, targetContext.target_name].find(
    (value): value is string => typeof value === "string" && value.trim().length > 0,
  );
  const targetNames = declaredNames.length > 0 ? declaredNames : fallbackName ? [fallbackName] : [];
  const datasetMetadata = isRecord(dataset.metadata) ? dataset.metadata : {};
  const sampleAxis = isRecord(dataset.y_axis) ? dataset.y_axis : {};
  const metadataSampleLabels = nonEmptyStringArray(datasetMetadata.sample_labels);
  const sampleLabels =
    metadataSampleLabels.length > 0 ? metadataSampleLabels : nonEmptyStringArray(sampleAxis.labels);

  for (const port of Object.values(ports)) {
    if (port.descriptor?.scientific_kind !== "target_matrix") continue;
    const sampleCount = port.descriptor.shape?.[0] ?? 0;
    const targetCount = port.descriptor.shape?.[1] ?? 0;
    const exactSampleLabels = sampleLabels.length === sampleCount ? sampleLabels : [];
    const exactTargetNames =
      targetNames.length === targetCount
        ? targetNames
        : targetCount === 1 && fallbackName
          ? [fallbackName]
          : [];
    port.metadata = {
      ...port.metadata,
      ...(exactSampleLabels.length > 0 ? { sample_labels: exactSampleLabels } : {}),
      ...(exactTargetNames.length > 0
        ? { target_names: exactTargetNames, column_names: exactTargetNames }
        : {}),
      ...(targetContext.target_units != null ? { target_units: targetContext.target_units } : {}),
    };
  }
};

const enrichStatisticsSummaryMetadata = (ports: Record<string, PortOutput>): void => {
  for (const port of Object.values(ports)) {
    if (port.descriptor?.scientific_kind !== "statistics_summary" || !isRecord(port.value)) {
      continue;
    }
    const summary = isRecord(port.value.summary) ? port.value.summary : null;
    const inputType =
      typeof port.value.input_type === "string" && port.value.input_type.trim().length > 0
        ? port.value.input_type
        : null;
    port.metadata = {
      ...port.metadata,
      ...(summary ? { summary } : {}),
      ...(inputType ? { input_type: inputType } : {}),
    };
  }
};

export const buildNodeOutput = (
  result: unknown,
  outputPorts?: NodePortMetadata[],
  diagnostics?: UnknownRecord | null,
  descriptors?: NodeScientificValueDescriptors | null,
  presentationContract?: NodePresentationContract | null,
): NodeOutput => {
  if (
    isDatasetPayload(result) ||
    Array.isArray(result) ||
    isModelPlaceholder(result) ||
    typeof result !== "object" ||
    result === null
  ) {
    const single = normalizePortOutput(result);
    const descriptor = descriptors?.default ?? Object.values(descriptors ?? {})[0];
    return attachDiagnostics(
      {
        data: single.data || [],
        metadata: {
          ...(single.metadata || {}),
          ...(descriptor ? { scientific_value: descriptor } : {}),
        },
        plots: single.plots,
        descriptor,
        presentation_contract: presentationContract ?? undefined,
      },
      diagnostics,
    );
  }

  const resultRecord = result as UnknownRecord;
  // `model_id` is lifted onto every training-node result by the executor
  // (executor.py:135). Pull it off the result here — both code paths below
  // need to hoist it to the top of NodeOutput so the UI can render the
  // Saved Model Artifact section without spelunking through `ports`.
  const rawModelId = resultRecord.model_id;
  const liftedModelId = typeof rawModelId === "string" && rawModelId.length > 0 ? rawModelId : null;

  const outputPortNames = outputPorts
    ? outputPorts.map((port) => port.name)
    : [...new Set(presentationContract?.payload.presentations.flatMap(item => item.source_ports) ?? Object.keys(descriptors ?? {}))];
  const hasDefault = Object.prototype.hasOwnProperty.call(resultRecord, "default");
  const hasPortKeys = outputPortNames.some((name) =>
    Object.prototype.hasOwnProperty.call(resultRecord, name),
  );
  const isSinglePayloadShape =
    Object.prototype.hasOwnProperty.call(resultRecord, "data") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "metadata") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "plots") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "type");

  const usePortMap =
    hasDefault || (outputPorts && outputPorts.length > 1) ||
    (hasPortKeys && (!!presentationContract || !!descriptors || !isSinglePayloadShape));

  if (!usePortMap) {
    const single = normalizePortOutput(resultRecord);
    return attachDiagnostics(
      {
        data: single.data || [],
        metadata: single.metadata || {},
        plots: single.plots,
        model_id: liftedModelId,
        presentation_contract: presentationContract ?? undefined,
      },
      diagnostics,
    );
  }

  const ports: Record<string, PortOutput> = {};
  let topLevelPlots: UnknownRecord | undefined;

  for (const [key, value] of Object.entries(resultRecord)) {
    if (key === "plots" && !outputPortNames.includes(key)) {
      if (isRecord(value)) {
        topLevelPlots = value;
      }
      continue;
    }
    // `model_id` is a lift-key from the executor (already hoisted above),
    // not a port — don't include it in the port map or it'll show up as a
    // junk "model_id" port in the Output Ports section.
    if (key === "model_id" && !outputPortNames.includes(key)) {
      continue;
    }
    if (key.startsWith("__") || key === "_internal") {
      continue;
    }
    if (!hasDefault && outputPorts && outputPorts.length > 0 && !outputPortNames.includes(key)) {
      continue;
    }
    ports[key] = {
      ...normalizePortOutput(value),
      descriptor: descriptors?.[key],
    };
  }

  if (outputPorts && outputPorts.length > 0) {
    for (const port of outputPorts) {
      if (!(port.name in ports) && port.name in resultRecord) {
        ports[port.name] = {
          ...normalizePortOutput(resultRecord[port.name]),
          descriptor: descriptors?.[port.name],
        };
      }
    }
  }

  enrichTargetPortMetadata(ports);
  enrichSampleIdentityMetadata(resultRecord, ports);
  enrichStatisticsSummaryMetadata(ports);

  const primaryPort = selectPrimaryPort(ports, outputPorts);
  const primary = primaryPort ? ports[primaryPort] : normalizePortOutput(resultRecord);

  return attachDiagnostics(
    {
      data: primary.data || [],
      metadata: {
        ...(isRecord(resultRecord.metadata) ? resultRecord.metadata : {}),
        ...(primary.metadata || {}),
        ...(primary.descriptor ? { scientific_value: primary.descriptor } : {}),
      },
      plots: primary.plots || topLevelPlots,
      ports: Object.keys(ports).length > 0 ? ports : undefined,
      primary_port: primaryPort,
      descriptor: primary.descriptor,
      model_id: liftedModelId,
      presentation_contract: presentationContract ?? undefined,
    },
    diagnostics,
  );
};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function resolvePortPayload(port: any): any {
  if (!port || typeof port !== "object") return port;
  return "value" in port ? port.value : port;
}
