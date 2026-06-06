import type { NodePortMetadata } from "@/types";

type UnknownRecord = Record<string, unknown>;

export interface PortOutput {
  data: unknown[];
  metadata: UnknownRecord;
  plots?: UnknownRecord;
  value?: unknown;
  type?: string;
}

export interface NodeOutput {
  data: unknown[];
  metadata: UnknownRecord;
  plots?: UnknownRecord;
  ports?: Record<string, PortOutput>;
  primary_port?: string;
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
  return isRecord(value) && (value.type === "NDDataset" || value.type === "SherpaDataset");
};

const isModelPlaceholder = (value: unknown): value is UnknownRecord => {
  return isRecord(value) && "__model_placeholder__" in value;
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
  outputPorts?: NodePortMetadata[]
): string | undefined => {
  if (ports.default) {
    return "default";
  }

  if (outputPorts && outputPorts.length > 0) {
    // Prefer a dataset-category port by inspecting the type_ref URI.
    // Include visualization and validation types so nodes like holdout_evaluation
    // surface their confusion matrix / predicted-vs-actual plot by default.
    const datasetTypeNames = new Set([
      "SpectralDataset", "Spectrum", "ScoreMatrix", "LoadingMatrix",
      "SpectralImage", "TimeSeries", "Array2D", "Array1D",
      "Visualization", "ValidationResult",
      "DecompositionResult", "RegressionModel", "ClassificationModel",
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
      (port) => ports[port.name] && Array.isArray(ports[port.name].data) && ports[port.name].data.length > 0
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

export const buildNodeOutput = (
  result: unknown,
  outputPorts?: NodePortMetadata[]
): NodeOutput => {
  if (
    isDatasetPayload(result) ||
    Array.isArray(result) ||
    isModelPlaceholder(result) ||
    typeof result !== "object" ||
    result === null
  ) {
    const single = normalizePortOutput(result);
    return {
      data: single.data || [],
      metadata: single.metadata || {},
      plots: single.plots,
    };
  }

  const resultRecord = result as UnknownRecord;
  // `model_id` is lifted onto every training-node result by the executor
  // (executor.py:135). Pull it off the result here — both code paths below
  // need to hoist it to the top of NodeOutput so the UI can render the
  // Saved Model Artifact section without spelunking through `ports`.
  const rawModelId = resultRecord.model_id;
  const liftedModelId =
    typeof rawModelId === "string" && rawModelId.length > 0 ? rawModelId : null;

  const outputPortNames = outputPorts ? outputPorts.map((port) => port.name) : [];
  const hasDefault = Object.prototype.hasOwnProperty.call(resultRecord, "default");
  const hasPortKeys = outputPortNames.some((name) =>
    Object.prototype.hasOwnProperty.call(resultRecord, name)
  );
  const isSinglePayloadShape =
    Object.prototype.hasOwnProperty.call(resultRecord, "data") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "metadata") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "plots") ||
    Object.prototype.hasOwnProperty.call(resultRecord, "type");

  const usePortMap =
    hasDefault ||
    (outputPorts && outputPorts.length > 1) ||
    (hasPortKeys && !isSinglePayloadShape);

  if (!usePortMap) {
    const single = normalizePortOutput(resultRecord);
    return {
      data: single.data || [],
      metadata: single.metadata || {},
      plots: single.plots,
      model_id: liftedModelId,
    };
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
    if (key === "model_id") {
      continue;
    }
    if (key.startsWith("__") || key === "_internal") {
      continue;
    }
    if (!hasDefault && outputPorts && outputPorts.length > 0 && !outputPortNames.includes(key)) {
      continue;
    }
    ports[key] = normalizePortOutput(value);
  }

  if (outputPorts && outputPorts.length > 0) {
    for (const port of outputPorts) {
      if (!(port.name in ports) && port.name in resultRecord) {
        ports[port.name] = normalizePortOutput(resultRecord[port.name]);
      }
    }
  }

  const primaryPort = selectPrimaryPort(ports, outputPorts);
  const primary = primaryPort ? ports[primaryPort] : normalizePortOutput(resultRecord);

  return {
    data: primary.data || [],
    metadata: primary.metadata || {},
    plots: primary.plots || topLevelPlots,
    ports: Object.keys(ports).length > 0 ? ports : undefined,
    primary_port: primaryPort,
    model_id: liftedModelId,
  };
};
