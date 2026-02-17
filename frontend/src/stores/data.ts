import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type {
  ExperimentSummary,
  ExperimentFile,
  FileInfoResponse,
} from "@/types";
import type {
  AvailableDatasets,
  LibraryDataset,
  ExperimentDataset,
} from "@/stores/workflow";

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
  const fileInfo = ref<FileInfoResponse | null>(null);
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

  const createExperiment = async (name: string, description?: string) => {
    const response = await api.post("/experiments", {
      name,
      description: description || null,
      metadata: {},
    });
    // Refresh both lists
    await Promise.all([fetchExperiments(), fetchCatalog()]);
    return response.data;
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
      const response = await api.post<FileInfoResponse>("/builder/file-info", body);
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
    dataStoryText.value = null;
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
    if (!catalogDatasetInfo.value) return;
    dataStoryLoading.value = true;
    try {
      const response = await api.post<{ response: string }>("/llm/data-story", {
        dataset_info: catalogDatasetInfo.value,
      });
      dataStoryText.value = response.data.response;
    } catch (error: any) {
      console.error("Failed to generate data story:", error);
      dataStoryText.value =
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

    // Computed
    experimentDatasets,
    libraryDatasets,

    // Actions
    fetchCatalog,
    fetchExperiments,
    selectExperiment,
    createExperiment,
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
