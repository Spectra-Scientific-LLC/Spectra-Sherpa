import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import { createSherpaRequestId, subscribeSherpaEvents } from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useAdvisorStore } from "@/stores/advisor";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { getErrorMessage } from "@/utils/errors";
import type {
  ExperimentSummary,
  ExperimentFile,
  SherpaDatasetDict,
} from "@/types";
import type {
  AvailableDatasets,
  LibraryDataset,
  ExperimentDataset,
  ReferenceDatasetOption,
} from "@/stores/workflow";

type StoryObject = Record<string, unknown>;
const LAST_ACTIVE_EXPERIMENT_PREFIX = "spectra_sherpa_last_experiment";

const lastActiveExperimentKey = (): string => {
  const userId = useAuthStore().user?.id ?? "local";
  const projectId = useProjectStore().currentProjectId ?? "no-project";
  return `${LAST_ACTIVE_EXPERIMENT_PREFIX}_${userId}_${projectId}`;
};

const readLastActiveExperimentId = (): number | null => {
  try {
    const raw = localStorage.getItem(lastActiveExperimentKey());
    const parsed = raw === null ? NaN : Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  } catch {
    return null;
  }
};

const writeLastActiveExperimentId = (id: number | null): void => {
  try {
    const key = lastActiveExperimentKey();
    if (id === null) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, String(id));
    }
  } catch {
    /* localStorage may be unavailable in hardened browsers/tests. */
  }
};

export interface DataStoryPropertyStat {
  name: string;
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  nan_pct?: number | null;
}

export interface DataStoryFileMetadata {
  name?: string | null;
  author?: string | null;
  date?: string | null;
}

export interface CatalogDatasetInfo {
  label?: string | null;
  title?: string | null;
  source?: string | null;
  technique?: string | null;
  description?: string | null;
  n_samples?: number | null;
  n_features?: number | null;
  task_type?: string | null;
  x_title?: string | null;
  x_units?: string | null;
  data_quantity?: string | null;
  wavelength_min?: number | null;
  wavelength_max?: number | null;
  is_time_series?: boolean;
  name?: string;
  feature_names?: string[];
  target_names?: string[];
  property_stats?: DataStoryPropertyStat[];
  file_metadata?: DataStoryFileMetadata;
  metadata?: StoryObject;
  // Preview payload powering the Inspect-tab chart on the catalog
  // branch. Spectral catalogs ship row-per-spectrum arrays in
  // `preview_spectra` plus the matching `wavelengths` axis; tabular
  // (sklearn) catalogs ship one row per sample plus `feature_labels`
  // so the frontend can render a box plot.
  preview_spectra?: (number | null)[][];
  wavelengths?: number[];
  feature_labels?: string[];
}

export interface ReferenceCatalog {
  synthetic: ReferenceDatasetOption[];
  eigenvector: ReferenceDatasetOption[];
  oes: ReferenceDatasetOption[];
  spectrochempy: ReferenceDatasetOption[];
  sklearn: ReferenceDatasetOption[];
}

export interface PreparedDataOverrides {
  title?: string | null;
  x_title?: string | null;
  x_units?: string | null;
  y_title?: string | null;
  data_role?: string | null;
  target_column?: string | null;
  target_type?: string | null;
  is_time_series?: boolean | null;
}

export type DataMatrixRef =
  | { kind: "reference"; source: string; name: string; overrides?: PreparedDataOverrides | null }
  | { kind: "staged"; staging_id: string; overrides?: PreparedDataOverrides | null }
  | { kind: "experiment_file"; experiment_id: number; file_id: number; overrides?: PreparedDataOverrides | null };

export interface DataMatrixColumnStat {
  label: string;
  count: number;
  missing: number;
  missing_pct: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  std: number | null;
}

export interface DataMatrixTargetClass {
  value: number | string | null;
  label: string;
  count: number;
  pct: number;
}

export interface DataMatrixTargetSummary {
  has_target: boolean;
  target_type: string | null;
  target_name: string | null;
  target_names?: string[] | null;
  target_units?: string | null;
  n_targets: number;
  count: number;
  missing: number;
  missing_pct: number;
  class_names?: string[] | null;
  n_classes?: number | null;
  classes?: DataMatrixTargetClass[];
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  std?: number | null;
}

export interface DataMatrixResponse {
  shape: [number, number];
  shape_label: string;
  x_title: string | null;
  x_units: string | null;
  y_title: string | null;
  data_role: string;
  data_modality: string;
  is_spectra: boolean;
  row_start: number;
  col_start: number;
  rows_shown: number;
  cols_shown: number;
  total_rows: number;
  total_cols: number;
  truncated: boolean;
  row_labels: string[];
  col_labels: string[];
  matrix: (number | string | null)[][];
  target: DataMatrixTargetSummary | null;
  stats: {
    per_column: DataMatrixColumnStat[];
    summary: {
      n_samples: number;
      n_features: number;
      global_min: number | null;
      global_max: number | null;
      global_mean: number | null;
      total_missing_pct: number;
    };
  };
}

export interface StagedUpload {
  staging_id: string;
  filename: string;
  size_bytes: number;
}

export interface SherpaDatasetContext {
  dataset_id: string | null;
  label: string | null;
  source: string | null;
  dataset_name: string | null;
  description: string | null;
  n_samples: number | null;
  n_features: number | null;
  is_time_series: boolean | null;
  is_spectra: boolean | null;
  technique: string | null;
  x_title: string | null;
  x_units: string | null;
  x_min: number | null;
  x_max: number | null;
  data_quantity: string | null;
  value_units: string | null;
  feature_names: string[] | null;
  target_names: string[] | null;
  metadata_summary: StoryObject | null;
}

function asObject(value: unknown): StoryObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as StoryObject)
    : {};
}

function asStringList(value: unknown, limit = 20): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const items = value
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .slice(0, limit);
  return items.length > 0 ? items : null;
}

function summarizeForDataStory(datasetInfo: StoryObject): StoryObject {
  const metadata = asObject(datasetInfo.metadata);
  const xAxis = asObject(datasetInfo.x_axis);
  const fileMetadata = asObject(datasetInfo.file_metadata);
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
    // Dataset type flags — critical for template selection
    is_time_series: datasetInfo.is_time_series ?? metadata.is_time_series ?? null,
    is_spectra: datasetInfo.is_spectra ?? datasetInfo.is_spectroscopic ?? metadata.is_spectra ?? null,
    x_axis: {
      title: datasetInfo.x_title ?? xAxis.title ?? metadata.x_title ?? null,
      units: datasetInfo.x_units ?? xAxis.units ?? metadata.x_units ?? null,
      min: xData.length ? xData[0] : datasetInfo.wavelength_min ?? null,
      max: xData.length ? xData[xData.length - 1] : datasetInfo.wavelength_max ?? null,
    },
    y_axis: {
      title: datasetInfo.data_quantity ?? metadata.data_quantity ?? null,
      units: metadata.value_units ?? null,
    },
    file_metadata: {
      name: fileMetadata.name ?? datasetInfo.title ?? null,
      author: fileMetadata.author ?? null,
      date: fileMetadata.date ?? null,
      // Pass through all user-edited metadata fields
      ...fileMetadata,
    },
    // Warnings (e.g., non-spectroscopic data notice)
    warning: datasetInfo.warning ?? null,
    warnings: Array.isArray(datasetInfo.warnings) ? datasetInfo.warnings : null,
    feature_names: featureNames,
    target_names: targetNames,
    property_stats: propertyStats,
    metadata_summary: {
      data_type: metadata.data_type ?? null,
      spectral_technique: metadata.spectral_technique ?? null,
      data_quantity: metadata.data_quantity ?? null,
      value_units: metadata.value_units ?? null,
      prop_names: propNames,
      sample_labels: labels,
    },
  };
}

export function summarizeDatasetForSherpaContext(
  datasetInfo: StoryObject | null | undefined
): SherpaDatasetContext | null {
  if (!datasetInfo) {
    return null;
  }

  const metadata = asObject(datasetInfo.metadata);
  const xAxis = asObject(datasetInfo.x_axis);
  const fileMetadata = asObject(datasetInfo.file_metadata);
  const xData = Array.isArray(xAxis.data)
    ? xAxis.data.filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    : [];
  const source =
    datasetInfo.source ??
    datasetInfo.name ??
    fileMetadata.name ??
    null;
  const technique =
    datasetInfo.technique ??
    metadata.spectral_technique ??
    metadata.domain_technique ??
    null;
  const xTitle =
    datasetInfo.x_title ??
    xAxis.title ??
    metadata.x_title ??
    metadata.spectral_x_title ??
    null;
  const xUnits =
    datasetInfo.x_units ??
    xAxis.units ??
    metadata.x_units ??
    metadata.spectral_x_units ??
    null;
  const dataQuantity =
    datasetInfo.data_quantity ??
    datasetInfo.units ??
    metadata.data_quantity ??
    metadata.y_title ??
    null;
  const valueUnits =
    metadata.value_units ??
    metadata.y_units ??
    null;
  const datasetName =
    typeof datasetInfo.name === "string"
      ? datasetInfo.name
      : typeof metadata["sklearn.dataset_name"] === "string"
        ? metadata["sklearn.dataset_name"]
        : typeof metadata["catalog.dataset_name"] === "string"
          ? metadata["catalog.dataset_name"]
          : null;
  const featureNames =
    asStringList(datasetInfo.feature_names) ??
    asStringList(metadata.feature_names);
  const targetNames =
    asStringList(datasetInfo.target_names) ??
    asStringList(metadata.target_names) ??
    asStringList(metadata.prop_names);

  return {
    dataset_id:
      typeof datasetInfo.dataset_id === "string" ? datasetInfo.dataset_id : null,
    label:
      typeof datasetInfo.label === "string"
        ? datasetInfo.label
        : typeof datasetInfo.title === "string"
          ? datasetInfo.title
          : typeof fileMetadata.name === "string"
            ? fileMetadata.name
            : null,
    source: typeof source === "string" ? source : null,
    dataset_name: datasetName,
    description:
      typeof datasetInfo.description === "string" ? datasetInfo.description : null,
    n_samples:
      typeof datasetInfo.n_samples === "number" ? datasetInfo.n_samples : null,
    n_features:
      typeof datasetInfo.n_features === "number" ? datasetInfo.n_features : null,
    is_time_series:
      typeof datasetInfo.is_time_series === "boolean"
        ? datasetInfo.is_time_series
        : typeof metadata.is_time_series === "boolean"
          ? (metadata.is_time_series as boolean)
          : null,
    is_spectra:
      typeof datasetInfo.is_spectra === "boolean"
        ? datasetInfo.is_spectra
        : typeof datasetInfo.is_spectroscopic === "boolean"
          ? (datasetInfo.is_spectroscopic as boolean)
          : typeof metadata.is_spectra === "boolean"
            ? (metadata.is_spectra as boolean)
            : null,
    technique: typeof technique === "string" ? technique : null,
    x_title: typeof xTitle === "string" ? xTitle : null,
    x_units: typeof xUnits === "string" ? xUnits : null,
    x_min:
      xData.length > 0
        ? xData[0]
        : typeof datasetInfo.wavelength_min === "number"
          ? datasetInfo.wavelength_min
          : null,
    x_max:
      xData.length > 0
        ? xData[xData.length - 1]
        : typeof datasetInfo.wavelength_max === "number"
          ? datasetInfo.wavelength_max
          : null,
    data_quantity: typeof dataQuantity === "string" ? dataQuantity : null,
    value_units: typeof valueUnits === "string" ? valueUnits : null,
    feature_names: featureNames,
    target_names: targetNames,
    metadata_summary: {
      data_type:
        typeof metadata.data_type === "string" ? metadata.data_type : null,
      spectral_technique:
        typeof metadata.spectral_technique === "string"
          ? metadata.spectral_technique
          : null,
      file_name:
        typeof fileMetadata.name === "string" ? fileMetadata.name : null,
      has_wavenumber_axis: xData.length > 0,
    },
  };
}

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
  const referenceCatalog = ref<ReferenceCatalog | null>(null);
  const referenceCatalogLoading = ref(false);
  const referenceCatalogError = ref<string | null>(null);
  const catalogDatasetInfo = ref<CatalogDatasetInfo | null>(null);
  const catalogDatasetLoading = ref(false);
  const catalogDatasetError = ref<string | null>(null);
  const dataStoryText = ref<string | null>(null);
  const dataStoryMemoryScopes = ref<string[]>([]);
  const dataStoryLoading = ref(false);
  const dataStoryContext = ref("");

  // Computed
  const experimentDatasets = computed<ExperimentDataset[]>(
    () => availableDatasets.value?.experiments ?? []
  );
  const libraryDatasets = computed<LibraryDataset[]>(
    () => availableDatasets.value?.library ?? []
  );

  const currentProjectId = () => useProjectStore().currentProjectId;

  // --- Actions ---

  const fetchCatalog = async (projectId: number | null = currentProjectId()) => {
    catalogLoading.value = true;
    try {
      if (projectId == null) {
        availableDatasets.value = { experiments: [], library: [], builder: [] };
        return;
      }
      const response = await api.get<AvailableDatasets>("/datasets/available", {
        params: { project_id: projectId },
      });
      availableDatasets.value = response.data;
    } catch (error) {
      console.error("Failed to fetch dataset catalog:", error);
    } finally {
      catalogLoading.value = false;
    }
  };

  const fetchExperiments = async (projectId: number | null = currentProjectId()) => {
    experimentsLoading.value = true;
    try {
      if (projectId == null) {
        experiments.value = [];
        return;
      }
      const response = await api.get<ExperimentSummary[]>("/experiments", {
        params: { project_id: projectId },
      });
      experiments.value = response.data;
    } catch (error) {
      console.error("Failed to fetch experiments:", error);
    } finally {
      experimentsLoading.value = false;
    }
  };

  const selectExperiment = async (experimentId: number) => {
    activeExperimentId.value = experimentId;
    writeLastActiveExperimentId(experimentId);
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

  const createExperiment = async (
    name: string,
    description?: string,
    projectId?: number | null,
    metadata?: Record<string, unknown>,
  ) => {
    const response = await api.post("/experiments", {
      name,
      description: description || null,
      metadata: metadata ?? {},
      project_id: projectId ?? null,
    });
    // Refresh both lists
    await Promise.all([fetchExperiments(), fetchCatalog()]);
    return response.data;
  };

  const updateExperiment = async (
    experimentId: number,
    payload: { name?: string; description?: string | null; metadata?: Record<string, unknown> }
  ) => {
    const response = await api.put(`/experiments/${experimentId}`, payload);
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
        writeLastActiveExperimentId(null);
      }
    }
  };

  const restoreActiveExperimentForCurrentProject = async () => {
    if (activeExperimentId.value !== null) {
      return;
    }
    if (experiments.value.length === 0) {
      await fetchExperiments();
    }
    const remembered = readLastActiveExperimentId();
    if (
      remembered !== null &&
      experiments.value.some((experiment) => experiment.id === remembered)
    ) {
      await selectExperiment(remembered);
    }
  };

  const clearActiveExperimentSelection = () => {
    activeExperimentId.value = null;
    experimentFiles.value = [];
  };

  const uploadFile = async (
    experimentId: number,
    file: File,
    stage: string,
    options?: {
      dataRole?: string | null;
      targetColumn?: string | null;
      targetType?: string | null;
    }
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("stage", stage);
    if (options?.dataRole) {
      form.append("data_role", options.dataRole);
    }
    if (options?.targetColumn) {
      form.append("target_column", options.targetColumn);
    }
    if (options?.targetType && options.targetType !== "auto") {
      form.append("target_type", options.targetType);
    }
    await api.post(`/experiments/${experimentId}/files`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    // Refresh file list and catalog
    await Promise.all([selectExperiment(experimentId), fetchCatalog()]);
  };

  const fetchDataMatrix = async (ref: DataMatrixRef): Promise<DataMatrixResponse> => {
    const response = await api.post<DataMatrixResponse>("/builder/data-matrix", ref);
    return response.data;
  };

  const stageUploadFile = async (file: File): Promise<StagedUpload> => {
    const form = new FormData();
    form.append("file", file);
    const response = await api.post<StagedUpload>("/builder/upload/stage", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  };

  const deleteStagedUpload = async (stagingId: string): Promise<void> => {
    await api.delete(`/builder/upload/stage/${stagingId}`);
  };

  const commitStagedUploads = async (
    experimentId: number,
    stage: string,
    files: Array<{ staging_id: string; overrides?: PreparedDataOverrides | null }>,
  ) => {
    const response = await api.post("/builder/upload/commit", {
      experiment_id: experimentId,
      stage,
      files,
    });
    await Promise.all([selectExperiment(experimentId), fetchExperiments(), fetchCatalog()]);
    return response.data;
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
    } catch (error: unknown) {
      fileInfo.value = null;
      fileInfoError.value = getErrorMessage(error, "Failed to inspect file");
      throw error;
    } finally {
      fileInfoLoading.value = false;
    }
  };

  const inspectExperimentRawFiles = async (experimentId: number) => {
    activeFileId.value = null;
    activeFilePath.value = null;
    fileInfoLoading.value = true;
    fileInfo.value = null;
    fileInfoError.value = null;
    clearCatalogExploration();
    try {
      const response = await api.post<SherpaDatasetDict>("/builder/file-info", {
        experiment_id: experimentId,
      });
      fileInfo.value = response.data;
      return response.data;
    } catch (error: unknown) {
      fileInfo.value = null;
      fileInfoError.value = getErrorMessage(error, "Failed to inspect dataset contents");
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
      const response = await api.get<ReferenceCatalog>(
        "/builder/reference-datasets"
      );
      referenceCatalog.value = response.data;
    } catch (error: unknown) {
      console.error("Failed to fetch reference catalog:", error);
      referenceCatalogError.value = getErrorMessage(error, "Failed to load reference catalog");
    } finally {
      referenceCatalogLoading.value = false;
    }
  };

  const importReferenceDatasets = async (
    experimentId: number,
    datasets: Array<{ source: string; name: string; overrides?: PreparedDataOverrides | null }>
  ) => {
    const response = await api.post(
      `/experiments/${experimentId}/import-reference`,
      { datasets }
    );
    // Refresh file list and experiment list to reflect new files
    await Promise.all([selectExperiment(experimentId), fetchExperiments(), fetchCatalog()]);
    return response.data;
  };

  const importLibraryDatasets = async (
    experimentId: number,
    payload: {
      source?: "nist" | "hitran" | "hitran_xsec";
      library_ids?: number[];
      component_ids?: string[];
      component_specs?: Array<{
        component_id: string;
        resolution_cm1?: number | null;
        wavenumber_min?: number | null;
        wavenumber_max?: number | null;
        temperature_k?: number | null;
        pressure_atm?: number | null;
      }>;
      spectra?: Array<{
        component_id: string;
        name: string;
        source: string;
        wavenumber: number[];
        intensity: number[];
        y_quantity: string;
        y_units?: string | null;
        resolution_cm1?: number | null;
        apodization?: string | null;
      }>;
      range_mode?: "common" | "widest";
      resolution_cm1?: number | null;
      wavenumber_min?: number | null;
      wavenumber_max?: number | null;
      temperature_k?: number | null;
      pressure_atm?: number | null;
    } | number[]
  ) => {
    const requestPayload = Array.isArray(payload)
      ? { experiment_id: experimentId, library_ids: payload }
      : { experiment_id: experimentId, ...payload };
    const response = await api.post("/datasets/library/import", {
      ...requestPayload,
    });
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
      const response = await api.get<CatalogDatasetInfo>(
        `/builder/reference-datasets/${source}/${name}`
      );
      catalogDatasetInfo.value = response.data;
    } catch (error: unknown) {
      catalogDatasetError.value = getErrorMessage(error, "Failed to load dataset info");
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
      if (sherpa.isSyncing || sherpa.isChatting) {
        return;
      }
      dataStoryLoading.value = true;

      // Use the Sherpa WS proxy path: entitlement-gated, server-side prompt/template
      const { useLlmStore } = await import("@/stores/llm");
      const llm = useLlmStore();
      const advisorStore = useAdvisorStore();
      const projectStore = useProjectStore();
      await llm.connect();
      const ws = llm.wsRef;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        throw new Error("WebSocket not connected. Try again in a moment.");
      }

      const summarized = summarizeForDataStory(datasetInfo as StoryObject);
      dataStoryText.value = "";  // Show progressive text as chunks arrive
      dataStoryMemoryScopes.value = [];

      const result = await new Promise<string>((resolve, reject) => {
        const requestId = createSherpaRequestId();
        const timeout = window.setTimeout(() => {
          cleanup();
          const partial = dataStoryText.value;
          if (partial) {
            // Got partial text — resolve with what we have
            console.warn(`Data story timeout after 180s, returning ${partial.length} chars of partial text`);
            resolve(partial);
          } else {
            reject(new Error(
              "Data story generation timed out (180s, 0 chunks received). " +
              "Check server logs: docker compose logs backend | grep data_story"
            ));
          }
        }, 180_000);

        const unsubscribe = subscribeSherpaEvents((payload) => {
          if (payload.type === SHERPA_WS_EVENT.dataStoryChunk) {
            // Stream chunks progressively into the UI
            dataStoryText.value = `${dataStoryText.value ?? ""}${typeof payload.text === "string" ? payload.text : ""}`;
          } else if (payload.type === SHERPA_WS_EVENT.dataStoryResult) {
            cleanup();
            dataStoryMemoryScopes.value = Array.isArray(payload.memory_scopes)
              ? payload.memory_scopes.map((scope) => String(scope)).filter(Boolean)
              : [];
            resolve(
              typeof payload.response === "string"
                ? payload.response
                : (dataStoryText.value ?? "")
            );
          } else if (payload.type === SHERPA_WS_EVENT.dataStoryError) {
            cleanup();
            const diag = payload.diagnostics;
            const detail = payload.detail || "Data story generation failed";
            const diagRecord =
              diag && typeof diag === "object" ? diag : null;
            const diagSummary = diag
              ? ` [stage=${String(diagRecord?.stage ?? "?")}, elapsed=${String(diagRecord?.elapsed_s ?? "?")}s, provider=${String(diagRecord?.provider ?? "?")}]`
              : "";
            console.error("Data story error:", detail, diag);
            reject(new Error(detail + diagSummary));
          } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
            cleanup();
            reject(new Error("Subscription required for Data Story generation."));
          }
        }, {
          requestId,
          types: [
            SHERPA_WS_EVENT.dataStoryChunk,
            SHERPA_WS_EVENT.dataStoryResult,
            SHERPA_WS_EVENT.dataStoryError,
            SHERPA_WS_EVENT.subscriptionRequired,
          ],
        });

        const cleanup = () => {
          clearTimeout(timeout);
          unsubscribe();
        };

        ws.send(
          JSON.stringify({
            action: SHERPA_WS_ACTION.dataStory,
            payload: {
              request_id: requestId,
              dataset_info: summarized,
              additional_context: dataStoryContext.value.trim() || null,
              advisor_node_id: advisorStore.activeNodeId,
              project_id: projectStore.currentProjectId,
            },
          })
        );
      });

      dataStoryText.value = result;
    } catch (error: unknown) {
      console.error("Failed to generate data story:", error);
      dataStoryMemoryScopes.value = [];
      dataStoryText.value = getErrorMessage(
        error,
        "Unable to generate data story. Check your LLM configuration."
      );
    } finally {
      dataStoryLoading.value = false;
    }
  };

  const clearCatalogExploration = () => {
    catalogDatasetInfo.value = null;
    catalogDatasetError.value = null;
    dataStoryText.value = null;
    dataStoryMemoryScopes.value = [];
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
    dataStoryMemoryScopes,
    dataStoryLoading,
    dataStoryContext,
    experimentDatasets,
    libraryDatasets,

    // Actions
    fetchCatalog,
    fetchExperiments,
    selectExperiment,
    restoreActiveExperimentForCurrentProject,
    clearActiveExperimentSelection,
    createExperiment,
    updateExperiment,
    deleteExperiment,
    uploadFile,
    fetchDataMatrix,
    stageUploadFile,
    deleteStagedUpload,
    commitStagedUploads,
    deleteFile,
    inspectFile,
    inspectExperimentRawFiles,
    downloadFile,
    clearInspection,
    fetchReferenceCatalog,
    importReferenceDatasets,
    importLibraryDatasets,
    exploreCatalogDataset,
    generateDataStory,
    clearCatalogExploration,
  };
});
