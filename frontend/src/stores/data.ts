import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type {
  ExperimentSummary,
  ExperimentFile,
  SherpaDatasetDict,
} from "@/types";
import type {
  AvailableDatasets,
  LibraryDataset,
  ExperimentDataset,
} from "@/stores/workflow";

/* eslint-disable @typescript-eslint/no-explicit-any */
function summarizeForDataStory(datasetInfo: Record<string, any>): Record<string, any> {
  const metadata = (datasetInfo.metadata as Record<string, any> | undefined) ?? {};
  const xAxis = (datasetInfo.x_axis as Record<string, any> | undefined) ?? {};
  const fileMetadata = (datasetInfo.file_metadata as Record<string, any> | undefined) ?? {};
  const propertyStats = Array.isArray(datasetInfo.property_stats)
    ? datasetInfo.property_stats.slice(0, 12)
    : undefined;
  const featureNames = Array.isArray(datasetInfo.feature_names)
    ? datasetInfo.feature_names.slice(0, 20)
    : undefined;
  const targetNames = Array.isArray(datasetInfo.target_names)
    ? datasetInfo.target_names.slice(0, 20)
    : undefined;
  const propNames = Array.isArray(metadata.prop_names)
    ? metadata.prop_names.slice(0, 20)
    : undefined;
  const labels = Array.isArray(metadata.labels) ? metadata.labels.slice(0, 10) : undefined;
  const xData = Array.isArray(xAxis.data) ? xAxis.data : [];

  return {
    label: datasetInfo.label ?? datasetInfo.title ?? fileMetadata.name ?? null,
    source: datasetInfo.source ?? null,
    technique: datasetInfo.technique ?? metadata.spectral_technique ?? null,
    description: datasetInfo.description ?? null,
    n_samples: datasetInfo.n_samples ?? null,
    n_features: datasetInfo.n_features ?? null,
    task_type: datasetInfo.task_type ?? null,
    x_axis: {
      title: xAxis.title ?? metadata.x_title ?? null,
      units: xAxis.units ?? metadata.x_units ?? null,
      min: xData.length ? xData[0] : datasetInfo.wavelength_min ?? null,
      max: xData.length ? xData[xData.length - 1] : datasetInfo.wavelength_max ?? null,
    },
    y_axis: {
      title: metadata.data_quantity ?? null,
      units: metadata.value_units ?? null,
    },
    file_metadata: {
      name: fileMetadata.name ?? datasetInfo.title ?? null,
      author: fileMetadata.author ?? null,
      date: fileMetadata.date ?? null,
    },
    feature_names: featureNames,
    target_names: targetNames,
    property_stats: propertyStats,
    metadata_summary: {
      spectral_technique: metadata.spectral_technique ?? null,
      data_quantity: metadata.data_quantity ?? null,
      value_units: metadata.value_units ?? null,
      prop_names: propNames,
      sample_labels: labels,
    },
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export const useDataStore = defineStore("data", () => {
  // Dataset catalog (from /datasets/available)
  const availableDatasets = ref<AvailableDatasets | null>(null);
  const catalogLoading = ref(false);

  // Experiment list (from /experiments)
  const experiments = ref<ExperimentSummary[]>([]);
  const experimentsLoading = ref(false);

  // Selected experiment files
  const activeExperimentId = ref<number | null>(null);
  const experimentFiles = ref<ExperimentFile[]>([]);
  const experimentFilesLoading = ref(false);

  // File inspection
  const activeFileId = ref<number | null>(null);
  const activeFilePath = ref<string | null>(null);
  const fileInfo = ref<SherpaDatasetDict | null>(null);
  const fileInfoLoading = ref(false);
  const fileInfoError = ref<string | null>(null);

  // Reference dataset catalog + exploration
  const referenceCatalog = ref<Record<string, any[]> | null>(null);
  const referenceCatalogLoading = ref(false);
  const referenceCatalogError = ref<string | null>(null);
  const catalogDatasetInfo = ref<Record<string, any> | null>(null);
  const catalogDatasetLoading = ref(false);
  const catalogDatasetError = ref<string | null>(null);
  const dataStoryText = ref<string | null>(null);
  const dataStoryLoading = ref(false);
  const dataStoryContext = ref("");

  // Computed
  const experimentDatasets = computed<ExperimentDataset[]>(
    () => availableDatasets.value?.experiments ?? []
  );
  const libraryDatasets = computed<LibraryDataset[]>(
    () => availableDatasets.value?.library ?? []
  );

  // --- Actions ---

  const fetchCatalog = async () => {
    catalogLoading.value = true;
    try {
      const response = await api.get<AvailableDatasets>("/datasets/available");
      availableDatasets.value = response.data;
    } catch (error) {
      console.error("Failed to fetch dataset catalog:", error);
    } finally {
      catalogLoading.value = false;
    }
  };

  const fetchExperiments = async () => {
    experimentsLoading.value = true;
    try {
      const response = await api.get<ExperimentSummary[]>("/experiments");
      experiments.value = response.data;
    } catch (error) {
      console.error("Failed to fetch experiments:", error);
    } finally {
      experimentsLoading.value = false;
    }
  };

  const selectExperiment = async (experimentId: number) => {
    activeExperimentId.value = experimentId;
    experimentFilesLoading.value = true;
    try {
      const response = await api.get<ExperimentFile[]>(
        `/experiments/${experimentId}/files`
      );
      experimentFiles.value = response.data;
    } catch (error) {
      console.error("Failed to fetch experiment files:", error);
      experimentFiles.value = [];
    } finally {
      experimentFilesLoading.value = false;
    }
  };

  const createExperiment = async (name: string, description?: string, projectId?: number | null) => {
    const response = await api.post("/experiments", {
      name,
      description: description || null,
      metadata: {},
      project_id: projectId ?? null,
    });
    // Refresh both lists
    await Promise.all([fetchExperiments(), fetchCatalog()]);
    return response.data;
  };

  const deleteExperiment = async (experimentId: number) => {
    const deletingActiveExperiment = activeExperimentId.value === experimentId;
    let fallbackExperimentId: number | null = null;

    if (deletingActiveExperiment) {
      const currentIndex = experiments.value.findIndex((experiment) => experiment.id === experimentId);
      if (currentIndex >= 0) {
        fallbackExperimentId =
          experiments.value[currentIndex + 1]?.id ??
          experiments.value[currentIndex - 1]?.id ??
          null;
      }
    }

    await api.delete(`/experiments/${experimentId}`);
    await Promise.all([fetchExperiments(), fetchCatalog()]);

    if (deletingActiveExperiment) {
      clearInspection();

      const fallbackStillExists =
        fallbackExperimentId != null &&
        experiments.value.some((experiment) => experiment.id === fallbackExperimentId);

      if (fallbackStillExists && fallbackExperimentId != null) {
        await selectExperiment(fallbackExperimentId);
      } else {
        activeExperimentId.value = null;
        experimentFiles.value = [];
      }
    }
  };

  const uploadFile = async (
    experimentId: number,
    file: File,
    stage: string
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("stage", stage);
    await api.post(`/experiments/${experimentId}/files`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    // Refresh file list and catalog
    await Promise.all([selectExperiment(experimentId), fetchCatalog()]);
  };

  const deleteFile = async (experimentId: number, fileId: number) => {
    await api.delete(`/experiments/${experimentId}/files/${fileId}`);
    // Refresh file list and catalog
    await Promise.all([selectExperiment(experimentId), fetchCatalog()]);
    // Clear inspection if deleted file was being inspected
    if (activeFileId.value === fileId) {
      clearInspection();
    }
  };

  const inspectFile = async (fileId: number, filePath: string, experimentId?: number) => {
    activeFileId.value = fileId;
    activeFilePath.value = filePath;
    fileInfoLoading.value = true;
    fileInfo.value = null;
    fileInfoError.value = null;
    try {
      const body: Record<string, unknown> = { file_path: filePath };
      if (experimentId != null) body.experiment_id = experimentId;
      const response = await api.post<SherpaDatasetDict>("/builder/file-info", body);
      fileInfo.value = response.data;
      return response.data;
    } catch (error: any) {
      fileInfo.value = null;
      fileInfoError.value = error?.message || "Failed to inspect file";
      throw error;
    } finally {
      fileInfoLoading.value = false;
    }
  };

  const downloadFile = async (fileId: number, fileName: string) => {
    const response = await api.get(`/datasets/download/${fileId}`, {
      responseType: "blob",
    });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", fileName);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const clearInspection = () => {
    activeFileId.value = null;
    activeFilePath.value = null;
    fileInfo.value = null;
    fileInfoError.value = null;
  };

  // --- Reference dataset catalog actions ---

  const fetchReferenceCatalog = async () => {
    referenceCatalogLoading.value = true;
    referenceCatalogError.value = null;
    try {
      const response = await api.get<Record<string, any[]>>(
        "/builder/reference-datasets"
      );
      referenceCatalog.value = response.data;
    } catch (error: any) {
      console.error("Failed to fetch reference catalog:", error);
      referenceCatalogError.value =
        error?.response?.data?.detail || error?.message || "Failed to load reference catalog";
    } finally {
      referenceCatalogLoading.value = false;
    }
  };

  const importReferenceDatasets = async (
    experimentId: number,
    datasets: Array<{ source: string; name: string }>
  ) => {
    const response = await api.post(
      `/experiments/${experimentId}/import-reference`,
      { datasets }
    );
    // Refresh file list and experiment list to reflect new files
    await Promise.all([selectExperiment(experimentId), fetchExperiments(), fetchCatalog()]);
    return response.data;
  };

  const exploreCatalogDataset = async (source: string, name: string) => {
    catalogDatasetLoading.value = true;
    catalogDatasetInfo.value = null;
    catalogDatasetError.value = null;
    // Clear file inspection so Explore tab shows catalog card
    clearInspection();
    try {
      const response = await api.get<Record<string, any>>(
        `/builder/reference-datasets/${source}/${name}`
      );
      catalogDatasetInfo.value = response.data;
    } catch (error: any) {
      catalogDatasetError.value =
        error?.response?.data?.detail || error?.message || "Failed to load dataset info";
    } finally {
      catalogDatasetLoading.value = false;
    }
  };

  const generateDataStory = async () => {
    const datasetInfo = catalogDatasetInfo.value || fileInfo.value;
    if (!datasetInfo) return;
    try {
      const { useSherpaStore } = await import("@/stores/sherpa");
      const sherpa = useSherpaStore();
      if (sherpa.state === "syncing" || sherpa.state === "chatting") {
        return;
      }
      dataStoryLoading.value = true;

      // Use the Sherpa WS proxy path: entitlement-gated, server-side prompt/template
      const { useLlmStore } = await import("@/stores/llm");
      const llm = useLlmStore();
      await llm.connect();
      const ws = llm.wsRef;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        throw new Error("WebSocket not connected. Try again in a moment.");
      }

      const summarized = summarizeForDataStory(datasetInfo as Record<string, any>);
      const result = await new Promise<string>((resolve, reject) => {
        const timeout = window.setTimeout(() => {
          cleanup();
          reject(new Error("Data story generation timed out"));
        }, 60_000);

        const handler = (event: Event) => {
          const payload = (event as CustomEvent).detail;
          if (payload.type === "sherpa_data_story_result") {
            cleanup();
            resolve(payload.response || "");
          } else if (payload.type === "sherpa_data_story_error") {
            cleanup();
            reject(new Error(payload.detail || "Data story generation failed"));
          } else if (payload.type === "sherpa_subscription_required") {
            cleanup();
            reject(new Error("Subscription required for Data Story generation."));
          }
        };

        const cleanup = () => {
          clearTimeout(timeout);
          window.removeEventListener("sherpa-ws-message", handler);
        };

        window.addEventListener("sherpa-ws-message", handler);
        ws.send(
          JSON.stringify({
            action: "sherpa_data_story",
            payload: {
              dataset_info: summarized,
              additional_context: dataStoryContext.value.trim() || null,
            },
          })
        );
      });

      dataStoryText.value = result;
    } catch (error: any) {
      console.error("Failed to generate data story:", error);
      dataStoryText.value =
        error?.response?.data?.detail ||
        error?.message ||
        "Unable to generate data story. Check your LLM configuration.";
    } finally {
      dataStoryLoading.value = false;
    }
  };

  const clearCatalogExploration = () => {
    catalogDatasetInfo.value = null;
    catalogDatasetError.value = null;
    dataStoryText.value = null;
  };

  return {
    // State
    availableDatasets,
    catalogLoading,
    experiments,
    experimentsLoading,
    activeExperimentId,
    experimentFiles,
    experimentFilesLoading,
    activeFileId,
    activeFilePath,
    fileInfo,
    fileInfoLoading,
    fileInfoError,

    // Reference catalog state
    referenceCatalog,
    referenceCatalogLoading,
    referenceCatalogError,
    catalogDatasetInfo,
    catalogDatasetLoading,
    catalogDatasetError,
    dataStoryText,
    dataStoryLoading,
    dataStoryContext,
    experimentDatasets,
    libraryDatasets,

    // Actions
    fetchCatalog,
    fetchExperiments,
    selectExperiment,
    createExperiment,
    deleteExperiment,
    uploadFile,
    deleteFile,
    inspectFile,
    downloadFile,
    clearInspection,
    fetchReferenceCatalog,
    importReferenceDatasets,
    exploreCatalogDataset,
    generateDataStory,
    clearCatalogExploration,
  };
});
