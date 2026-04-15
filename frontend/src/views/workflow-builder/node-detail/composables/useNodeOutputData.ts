/**
 * Output-panel computeds + helpers extracted from NodeDetailView.vue.
 *
 * Scope (issue #26, phase 2a): self-contained output metadata and summary
 * logic — hasInput/hasOutput, outputData/outputMetadata, dataset identity,
 * processing history / provenance / quality summary, port summaries, and
 * the fullMetadataJson JSON dump for the inspector modal.
 *
 * Deferred to a follow-up slice: preview-table computeds (outputPreview /
 * outputPreviewColumns / pcaDiagnosticsPreview) and regression target
 * options — those depend on sample-label utilities and the PCA
 * primary-port payload, and are easier to migrate alongside useNodePlotData.
 */

import { computed, type Ref } from "vue";
import { buildLabelTable } from "@/utils/sampleLabels";
import type { NodeOutput } from "@/utils/nodeOutput";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL_PREVIEW_LIMIT = 6;

const META_TOOLTIPS: Record<string, string> = {
  t2_mean: "Hotelling's T² mean across samples (distance in PCA score space).",
  t2_p95: "95th percentile of Hotelling's T²; common control limit for outliers.",
  spe_mean: "Mean Squared Prediction Error (SPE/Q residuals) across samples.",
  spe_p95: "95th percentile of SPE; common control limit for residual outliers.",
};

interface UseNodeOutputDataDeps {
  nodeOutput: Ref<NodeOutput | null>;
  nodeData: Ref<any>;
  nodeTypeKey: Ref<string>;
}

export function useNodeOutputData({
  nodeOutput,
  nodeData,
  nodeTypeKey,
}: UseNodeOutputDataDeps) {
  const hasInput = computed(() => {
    return !!(nodeData.value?.inputData || nodeData.value?.inputConnections?.length);
  });

  const hasOutput = computed(() => {
    if (!nodeOutput.value) return false;
    const hasData =
      nodeOutput.value.data &&
      (Array.isArray(nodeOutput.value.data)
        ? nodeOutput.value.data.length > 0
        : true);
    const hasPlots =
      nodeOutput.value.plots &&
      Object.keys(nodeOutput.value.plots).length > 0;
    // Visualization nodes may have layout in metadata even when trace data was
    // stripped for sessionStorage transfer (large spectral plots).
    const hasMeta =
      nodeOutput.value.metadata &&
      Object.keys(nodeOutput.value.metadata).length > 0;
    return !!hasData || !!hasPlots || !!hasMeta;
  });

  const inputSummary = computed(() => {
    if (!hasInput.value) return "";
    const conns = nodeData.value?.inputConnections?.length || 0;
    return conns > 0 ? `${conns} connection${conns > 1 ? "s" : ""}` : "";
  });

  const outputSummary = computed(() => {
    if (!hasOutput.value) return "";
    const data = nodeOutput.value?.data;
    if (Array.isArray(data)) {
      const rows = data.length;
      const cols = Array.isArray(data[0]) ? data[0].length : 1;
      return `${rows} x ${cols}`;
    }
    return "Available";
  });

  const inputConnections = computed(() => nodeData.value?.inputConnections || []);
  const inputData = computed(() => nodeData.value?.inputData || null);

  const outputData = computed(() => {
    if (!hasOutput.value) return null;
    const data = nodeOutput.value!.data;
    const metadata: Record<string, any> = nodeOutput.value!.metadata || {};

    if (!Array.isArray(data)) return { type: typeof data as string };

    const rows = data.length;
    const cols = Array.isArray(data[0]) ? data[0].length : 1;

    let min = Infinity;
    let max = -Infinity;
    for (const row of data) {
      if (Array.isArray(row)) {
        for (const val of row) {
          if (typeof val === "number" && !isNaN(val)) {
            min = Math.min(min, val);
            max = Math.max(max, val);
          }
        }
      } else if (typeof row === "number") {
        min = Math.min(min, row);
        max = Math.max(max, row);
      }
    }

    return {
      rows,
      cols,
      type: metadata.type || metadata.output_type || "dataset",
      range: min !== Infinity ? [min, max] : null,
    };
  });

  const outputMetadata = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const filtered: Record<string, any> = {};

    const structuredKeys = [
      "data", "wavenumbers", "x_axis", "sample_labels", "labels",
      "processing_history", "provenance", "quality_summary",
      "x_title", "x_units", "y_title", "y_units",
      "data_type", "is_spectra", "spectral_technique", "data_quantity",
      "value_units", "value_units_label",
    ];

    for (const [key, value] of Object.entries(metadata)) {
      if (structuredKeys.includes(key)) continue;
      if (Array.isArray(value) && value.length > 20) {
        filtered[key] = `[${value.length} values]`;
        continue;
      }
      if (typeof value === "object" && value !== null && !Array.isArray(value)) {
        const keys = Object.keys(value);
        if (keys.length > 10) {
          filtered[key] = `{${keys.length} fields}`;
          continue;
        }
      }
      filtered[key] = value;
    }

    return filtered;
  });

  const datasetInfo = computed(() => {
    if (!hasOutput.value || !nodeOutput.value) return null;
    const primaryPort = nodeOutput.value.primary_port;
    const portValue: any =
      (primaryPort && (nodeOutput.value.ports?.[primaryPort] as any)?.value) || null;
    const metadata: Record<string, any> = nodeOutput.value.metadata || {};
    const info: Record<string, any> = {};

    const xAxis = portValue?.x_axis;
    if (xAxis?.data?.length) {
      const nums = xAxis.data.filter(
        (v: any) => typeof v === "number" && isFinite(v),
      );
      info.xAxis = {
        title: xAxis.title || metadata.x_title || "Feature",
        units: xAxis.units || metadata.x_units || "",
        points: xAxis.data.length,
        range: nums.length ? [Math.min(...nums), Math.max(...nums)] : null,
      };
    } else if (metadata.x_title || metadata.wavenumbers?.length) {
      info.xAxis = {
        title: metadata.x_title || "Feature",
        units: metadata.x_units || "",
        points: metadata.wavenumbers?.length || metadata.n_features,
      };
    }

    const defaultSampleTitle = metadata.is_time_series
      ? "Scan / Time Index"
      : "Sample";
    const yAxis = portValue?.y_axis;
    if (yAxis) {
      info.yAxis = {
        title: yAxis.title || metadata.y_title || defaultSampleTitle,
        units: yAxis.units || metadata.y_units || "",
        labels: yAxis.labels,
        nSamples: yAxis.data?.length,
      };
    } else if (metadata.sample_labels?.length) {
      info.yAxis = {
        title: metadata.y_title || defaultSampleTitle,
        units: metadata.y_units || "",
        labels: metadata.sample_labels,
        nSamples: metadata.sample_labels.length,
      };
    }

    if (metadata.spectral_technique) info.spectralTechnique = metadata.spectral_technique;
    if (metadata.data_quantity) info.dataQuantity = metadata.data_quantity;
    if (metadata.is_spectra) info.isSpectra = true;
    if (metadata.value_units || metadata.value_units_label) {
      info.valueUnits = metadata.value_units || metadata.value_units_label;
    }
    if (portValue?.title) info.title = portValue.title;
    if (metadata.domain_technique) info.domainTechnique = metadata.domain_technique;
    if (metadata.domain_data_quantity) info.domainDataQuantity = metadata.domain_data_quantity;

    return Object.keys(info).length > 0 ? info : null;
  });

  const datasetLabelTable = computed<{ headers: string[]; rows: string[][] }>(() => {
    const labels = datasetInfo.value?.yAxis?.labels;
    if (!Array.isArray(labels) || labels.length === 0) {
      return { headers: ["Label"], rows: [] };
    }
    const table = buildLabelTable(labels, {
      limit: LABEL_PREVIEW_LIMIT,
      columnHeaderPrefix: "Field",
    });
    return { headers: table.headers, rows: table.rows };
  });

  const processingHistory = computed(() => {
    const hist = nodeOutput.value?.metadata?.processing_history;
    return Array.isArray(hist) && hist.length > 0 ? hist : null;
  });

  const provenanceInfo = computed(() => {
    const prov = nodeOutput.value?.metadata?.provenance;
    return prov && typeof prov === "object" ? prov : null;
  });

  const qualitySummary = computed(() => {
    const qs = nodeOutput.value?.metadata?.quality_summary;
    return qs && typeof qs === "object" ? (qs as Record<string, unknown>) : null;
  });

  const isRegressionNode = computed(() =>
    ["model.pls", "model.pcr", "model.svr"].includes(nodeTypeKey.value),
  );

  const portSummaries = computed(() => {
    if (!nodeOutput.value?.ports) return [];
    const summaries: Array<{
      name: string;
      type?: string;
      shape?: number[];
      title?: string;
      xTitle?: string;
      xUnits?: string;
      xPoints?: number;
      yTitle?: string;
      nLabels?: number;
    }> = [];
    for (const [name, port] of Object.entries(nodeOutput.value.ports)) {
      if (name === nodeOutput.value.primary_port) continue;
      const raw = (port as any).value;
      summaries.push({
        name,
        type: (port as any).type,
        shape: raw?.shape,
        title: raw?.title,
        xTitle: raw?.x_axis?.title,
        xUnits: raw?.x_axis?.units,
        xPoints: raw?.x_axis?.data?.length,
        yTitle: raw?.y_axis?.title,
        nLabels: raw?.y_axis?.labels?.length,
      });
    }
    return summaries;
  });

  const fullMetadataJson = computed(() => {
    if (!nodeOutput.value) return "{}";
    const full: Record<string, any> = { metadata: nodeOutput.value.metadata };
    if (nodeOutput.value.ports) {
      full.ports = {};
      for (const [name, port] of Object.entries(nodeOutput.value.ports)) {
        const raw = (port as any).value;
        full.ports[name] = {
          type: (port as any).type,
          shape: raw?.shape,
          title: raw?.title,
          x_axis: raw?.x_axis
            ? {
                title: raw.x_axis.title,
                units: raw.x_axis.units,
                points: raw.x_axis.data?.length,
              }
            : undefined,
          y_axis: raw?.y_axis
            ? { title: raw.y_axis.title, labels_count: raw.y_axis.labels?.length }
            : undefined,
          metadata: (port as any).metadata,
        };
      }
    }
    return JSON.stringify(full, null, 2);
  });

  const getMetaTooltip = (key: string): string => META_TOOLTIPS[key] || "";

  const formatMetaValue = (value: any): string => {
    if (value === null || value === undefined) return "\u2014";
    if (Array.isArray(value)) {
      if (value.length === 0) return "[]";
      const preview = value.slice(0, 5).map((v: any) => {
        if (typeof v === "number") {
          return Number.isInteger(v) ? String(v) : v.toFixed(4);
        }
        if (v && typeof v === "object") {
          try {
            return JSON.stringify(v);
          } catch {
            return String(v);
          }
        }
        return String(v);
      });
      return `[${preview.join(", ")}${value.length > 5 ? `, \u2026 (${value.length})` : ""}]`;
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (keys.length === 0) return "{}";
      const preview = keys.slice(0, 4).map((k) => {
        const v = (value as Record<string, any>)[k];
        const short =
          typeof v === "number"
            ? Number.isInteger(v)
              ? String(v)
              : v.toFixed(2)
            : typeof v === "string"
              ? v.length > 20
                ? v.slice(0, 20) + "\u2026"
                : v
              : String(v);
        return `${k}: ${short}`;
      });
      return `{${preview.join(", ")}${keys.length > 4 ? ", \u2026" : ""}}`;
    }
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (typeof value === "number") {
      return Number.isInteger(value) ? String(value) : value.toFixed(4);
    }
    return String(value);
  };

  return {
    hasInput,
    hasOutput,
    inputSummary,
    outputSummary,
    inputConnections,
    inputData,
    outputData,
    outputMetadata,
    datasetInfo,
    datasetLabelTable,
    labelPreviewLimit: LABEL_PREVIEW_LIMIT,
    processingHistory,
    provenanceInfo,
    qualitySummary,
    isRegressionNode,
    portSummaries,
    fullMetadataJson,
    getMetaTooltip,
    formatMetaValue,
  };
}
