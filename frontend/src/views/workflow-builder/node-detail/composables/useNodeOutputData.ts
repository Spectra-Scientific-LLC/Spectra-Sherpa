/**
 * Output-panel computeds + helpers extracted from NodeDetailView.vue.
 *
 * Scope: self-contained output-panel logic — hasInput/hasOutput,
 * outputData/outputMetadata, dataset identity, processing history /
 * provenance / quality summary, port summaries, the fullMetadataJson JSON
 * dump, the preview-table computeds (input/output/PCA diagnostics), and
 * the regression target selector (options, selected R²/RMSE). These all
 * end up fed into the OutputPanel via useNodeDetailState — keeping them in
 * one composable avoids a second file with the same dep graph.
 */

import { computed, watch, type Ref } from "vue";
import {
  buildLabelTable,
  compactSampleLabel,
  detectLabelDelimiter,
  normalizeSampleLabel,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";
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
  /** Primary port payload resolver from useNodeOutput. Used for regression
   *  target-name lookup. */
  resolvePortPayload: (port: any) => any;
  /** Writable target selector — composable clamps it to a valid option when
   *  the list changes. */
  regressionTargetIdx: Ref<number>;
  /** Max rows in preview tables. Caller owns the constant. */
  previewRowLimit: number;
}

export function useNodeOutputData({
  nodeOutput,
  nodeData,
  nodeTypeKey,
  resolvePortPayload,
  regressionTargetIdx,
  previewRowLimit,
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

  // ── Preview tables (input / output / PCA diagnostics) ─────────────────

  const isPCAOutput = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    return (
      nodeTypeKey.value === "model.pca" ||
      metadata.type === "model.pca" ||
      metadata.isPCA === true
    );
  });

  const inputPreview = computed(() => {
    const data = nodeData.value?.inputData?.data;
    if (!data || !Array.isArray(data)) return [];
    return data.slice(0, previewRowLimit).map((row: any, i: number) => {
      const obj: any = { _index: i + 1 };
      if (Array.isArray(row)) {
        row.slice(0, 10).forEach((val: any, j: number) => {
          obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
        });
      } else {
        obj.value = typeof row === "number" ? row.toFixed(4) : row;
      }
      return obj;
    });
  });

  const inputDataSummary = computed(() => {
    const data = nodeData.value?.inputData?.data;
    if (!data || !Array.isArray(data)) return "";
    const totalRows = data.length;
    const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
    const shownRows = Math.min(totalRows, previewRowLimit);
    const shownCols = Math.min(totalCols, 10);
    let summary = `${shownRows} of ${totalRows} rows`;
    if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
    return summary;
  });

  const inputPreviewColumns = computed(() => {
    if (!inputPreview.value.length) return [];
    const first = inputPreview.value[0];
    const metadata = nodeData.value?.inputData?.metadata || {};
    const featureNames = metadata.feature_names || [];
    const xTitle = metadata.x_title || "";

    return Object.keys(first).map((key) => {
      let header = key;
      if (key === "_index") {
        header = "#";
      } else if (key.startsWith("col_")) {
        const colIdx = parseInt(key.replace("col_", ""));
        if (featureNames.length > colIdx) {
          header = featureNames[colIdx];
        } else if (xTitle && xTitle !== "Feature") {
          header = `${xTitle} ${colIdx + 1}`;
        } else {
          header = `Col ${colIdx + 1}`;
        }
      }
      return { field: key, header };
    });
  });

  const outputPreview = computed(() => {
    const data = nodeOutput.value?.data;
    if (!data || !Array.isArray(data)) return [];
    const metadata = nodeOutput.value?.metadata || {};
    const labelsRaw = metadata.sample_labels || metadata.labels || [];
    const labels = Array.isArray(labelsRaw)
      ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
      : [];
    const labelDelimiter = detectLabelDelimiter(labels);
    const splitLabels = labelDelimiter
      ? labels.map((label: string) => splitLabelByDelimiter(label, labelDelimiter))
      : [];
    const maxLabelParts =
      splitLabels.length > 0
        ? Math.max(...splitLabels.map((parts: string[]) => parts.length))
        : 0;
    const useSplitLabelColumns = !!labelDelimiter && maxLabelParts > 1;

    return data.slice(0, previewRowLimit).map((row: any, i: number) => {
      const obj: any = { _index: i + 1 };
      const fullLabel = labels[i] || "";
      obj._label_full = fullLabel;

      if (labels.length > 0) {
        if (useSplitLabelColumns) {
          const parts = splitLabels[i] || [];
          for (let labelIdx = 0; labelIdx < maxLabelParts; labelIdx += 1) {
            const value = parts[labelIdx] || "";
            obj[`_label_${labelIdx}`] = compactSampleLabel(value, {
              maxLength: 42,
              headLength: 28,
              tailLength: 12,
            });
          }
        } else {
          obj._label = compactSampleLabel(fullLabel, {
            maxLength: 52,
            headLength: 34,
            tailLength: 14,
          });
        }
      }

      if (Array.isArray(row)) {
        row.slice(0, 10).forEach((val: any, j: number) => {
          obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
        });
      } else if (typeof row === "object" && row !== null) {
        // Dict rows (e.g. PeakFinding stats output)
        for (const [k, v] of Object.entries(row)) {
          obj[k] = typeof v === "number" ? Number(v).toFixed(4) : v;
        }
      } else {
        obj.value = typeof row === "number" ? row.toFixed(4) : row;
      }
      return obj;
    });
  });

  const outputPreviewColumns = computed(() => {
    if (!outputPreview.value.length) return [];
    const first = outputPreview.value[0] as Record<string, any>;
    const metadata: Record<string, any> = nodeOutput.value?.metadata || {};
    const pcLabels: any[] = metadata.pc_labels || [];
    const mcrLabels: any[] = metadata.labels || [];
    const featureNames: any[] = metadata.feature_names || [];
    const columnNames: string[] = Array.isArray(metadata.column_names)
      ? metadata.column_names
      : [];
    const xTitle = metadata.x_title || "";
    const isPCA = metadata.type === "model.pca" || metadata.isPCA;
    const isMCR = metadata.type === "model.mcr_als";

    return Object.keys(first)
      .filter((key) => key !== "_label_full")
      .map((key) => {
        let header = key;
        if (key === "_index") {
          header = "#";
        } else if (key === "_label") {
          header = "Label";
        } else if (key.startsWith("_label_")) {
          const labelIdx = Number.parseInt(key.replace("_label_", ""), 10);
          header = Number.isNaN(labelIdx) ? "Label" : `Field ${labelIdx + 1}`;
        } else if (key.startsWith("col_")) {
          const colIdx = parseInt(key.replace("col_", ""));
          if (columnNames.length > colIdx) {
            header = columnNames[colIdx];
          } else if (isPCA && pcLabels[colIdx]) {
            header = pcLabels[colIdx];
          } else if (isMCR && mcrLabels[colIdx]) {
            header = mcrLabels[colIdx];
          } else if (featureNames.length > colIdx) {
            header = featureNames[colIdx];
          } else if (xTitle && xTitle !== "Feature") {
            header = `${xTitle} ${colIdx + 1}`;
          } else {
            header = `Col ${colIdx + 1}`;
          }
        }
        return { field: key, header };
      });
  });

  const outputDataSummary = computed(() => {
    const data = nodeOutput.value?.data;
    if (!data || !Array.isArray(data)) return "";
    const totalRows = data.length;
    const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
    const shownRows = Math.min(totalRows, previewRowLimit);
    const shownCols = Math.min(totalCols, 10);
    let summary = `${shownRows} of ${totalRows} rows`;
    if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
    return summary;
  });

  const pcaDiagnosticsPreview = computed(() => {
    if (!isPCAOutput.value || !hasOutput.value) return [];
    const metadata: Record<string, any> = nodeOutput.value?.metadata || {};
    const t2: any[] = Array.isArray(metadata.t2) ? metadata.t2 : [];
    const spe: any[] = Array.isArray(metadata.spe) ? metadata.spe : [];
    const rowCount = Math.max(t2.length, spe.length);
    if (rowCount === 0) return [];

    const rows = [];
    const limit = Math.min(rowCount, previewRowLimit);
    for (let i = 0; i < limit; i += 1) {
      rows.push({
        sample: i + 1,
        t2: typeof t2[i] === "number" ? t2[i].toFixed(4) : "",
        spe: typeof spe[i] === "number" ? spe[i].toFixed(6) : "",
      });
    }
    return rows;
  });

  const pcaDiagSummary = computed(() => {
    if (!isPCAOutput.value || !hasOutput.value) return "";
    const metadata: Record<string, any> = nodeOutput.value?.metadata || {};
    const t2: any[] = Array.isArray(metadata.t2) ? metadata.t2 : [];
    const spe: any[] = Array.isArray(metadata.spe) ? metadata.spe : [];
    const totalRows = Math.max(t2.length, spe.length);
    const shownRows = Math.min(totalRows, previewRowLimit);
    return `${shownRows} of ${totalRows} rows`;
  });

  const pcaDiagnosticsColumns = computed(() => [
    { field: "sample", header: "Sample" },
    { field: "t2", header: "T²" },
    { field: "spe", header: "SPE (Q)" },
  ]);

  // ── Regression target selector ────────────────────────────────────────

  const regressionTargetNames = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const yLoadings = resolvePortPayload(nodeOutput.value?.ports?.Y_loadings);
    const targetPort = resolvePortPayload(nodeOutput.value?.ports?.target);
    const candidates = [
      metadata.target_names,
      yLoadings?.y_axis?.labels,
      targetPort?.y_axis?.labels,
      targetPort?.metadata?.target_names,
    ];

    for (const raw of candidates) {
      if (Array.isArray(raw) && raw.length > 0) {
        return raw.map((name: unknown) => normalizeSampleLabel(name));
      }
    }

    return [];
  });

  const regressionTargetOptions = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const yTrue = metadata.y_true;
    if (!Array.isArray(yTrue) || yTrue.length === 0) return [];
    const nTargets = Array.isArray(yTrue[0]) ? yTrue[0].length : 1;
    const names = regressionTargetNames.value;
    return Array.from({ length: nTargets }, (_, i) => ({
      label: names[i] || `Target ${i + 1}`,
      value: i,
    }));
  });

  watch(
    regressionTargetOptions,
    (options) => {
      if (options.length === 0) {
        regressionTargetIdx.value = 0;
        return;
      }
      if (!options.some((option) => option.value === regressionTargetIdx.value)) {
        regressionTargetIdx.value = options[0].value;
      }
    },
    { immediate: true },
  );

  const selectedRegressionR2 = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const r2List = metadata.r2_per_target;
    if (!Array.isArray(r2List)) return null;
    const value = r2List[regressionTargetIdx.value];
    return typeof value === "number" ? value : null;
  });

  const selectedRegressionRmse = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const rmseList = metadata.rmse_per_target;
    if (!Array.isArray(rmseList)) return null;
    const value = rmseList[regressionTargetIdx.value];
    return typeof value === "number" ? value : null;
  });

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
    isPCAOutput,
    portSummaries,
    fullMetadataJson,
    getMetaTooltip,
    formatMetaValue,
    // Preview tables
    inputPreview,
    inputPreviewColumns,
    inputDataSummary,
    outputPreview,
    outputPreviewColumns,
    outputDataSummary,
    pcaDiagnosticsPreview,
    pcaDiagnosticsColumns,
    pcaDiagSummary,
    // Regression selector
    regressionTargetNames,
    regressionTargetOptions,
    selectedRegressionR2,
    selectedRegressionRmse,
  };
}
