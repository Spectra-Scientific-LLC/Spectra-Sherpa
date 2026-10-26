import { sherpaResponseTimeoutMs } from "@/lib/sherpaTimeouts";
import { clearRetainedDatasetWorkspace } from "@/utils/retainedInspection";
import { streamLocalDataStory } from "@/lib/localDataStory";
import { buildDataStoryContext } from "@/lib/dataStoryFacts";
import { useAppConfig } from "@/composables/useAppConfig";
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import { experimentFile, experimentSummary, experimentFileAssets, experimentDetail } from "@/api/adapters/datasets";
import { createSherpaRequestId, subscribeSherpaEvents } from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useAdvisorStore } from "@/stores/advisor";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";
import { watch } from "vue";
import { getErrorCode, getErrorMessage } from "@/utils/errors";
import { blobFromResponseData, downloadBlob } from "@/utils/download";
import type {
  ExperimentSummary,
  ExperimentFile,
  ExperimentFileAssets,
  ScientificAsset,
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
  x_quantity?: string | null;
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
  builtin: ReferenceDatasetOption[];
  registered: ReferenceDatasetOption[];
  synthetic: ReferenceDatasetOption[];
  eigenvector: ReferenceDatasetOption[];
  oes: ReferenceDatasetOption[];
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
  assignment_column?: string | null;
  is_time_series?: boolean | null;
  csv_layout?: string | null;
}

export interface CsvLayoutOption {
  value: string;
  label: string;
  description: string;
}

export interface CsvImportColumnRole {
  name: string;
  role: "I" | "W" | "F" | "P" | "M" | "T" | "E" | "?";
  numeric_pct?: number | null;
  reason?: string | null;
}

export interface CsvImportPlan {
  layout: string;
  layout_label: string;
  confidence: "high" | "medium" | "low" | string;
  role_sequence: string;
  shape: {
    rows: number | null;
    columns: number | null;
    samples: number | null;
    features: number | null;
  };
  axis: {
    column?: string | null;
    title?: string | null;
    units?: string | null;
  } | null;
  target: {
    column?: string | null;
    type?: string | null;
    candidates?: string[];
    selectable?: string[];
  };
  assignment?: { column: string; training_label: string; validation_label: string } | null;
  columns: CsvImportColumnRole[];
  warnings: string[];
  recommended_layout?: string | null;
  layout_options?: CsvLayoutOption[];
  requires_confirmation?: boolean;
  delimiter?: string | null;
  decimal?: string | null;
}

export type DataMatrixRef =
  | { kind: "reference"; source: string; name: string; project_id?: number | null; overrides?: PreparedDataOverrides | null }
  | {
      kind: "staged";
      staging_id: string;
      asset_id?: string | null;
      overrides?: PreparedDataOverrides | null;
    }
  | {
      kind: "experiment_file";
      experiment_id: number;
      file_id: number;
      asset_id?: string | null;
      row_start?: number;
      overrides?: PreparedDataOverrides | null;
    };

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
  kind?: "matrix_2d" | "nd_dataset";
  shape: number[];
  rank?: number;
  shape_label: string;
  dimension_roles?: string[];
  projection_required?: boolean;
  projection_message?: string;
  dataset_preview?: Record<string, unknown>;
  x_title: string | null;
  x_units: string | null;
  x_quantity?: string | null;
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
  source_name?: string;
  size_bytes: number;
  csv_import_plan?: CsvImportPlan | null;
  suggested_overrides?: PreparedDataOverrides;
  format_id: string;
  variant: string;
  assets: ScientificAsset[];
}

export interface StagedUploadBatch {
  file_count: number;
  total_size_bytes: number;
  files: StagedUpload[];
  refused_count: number;
  refusals: StagedUploadRefusal[];
}

export interface StagedUploadRefusal {
  source_name: string;
  reason: string;
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


export function summarizeDatasetForSherpaContext(
  datasetInfo: StoryObject | null | undefined,
): SherpaDatasetContext | null {
  if (!datasetInfo) {
    return null;
  }

  const metadata = asObject(datasetInfo.metadata);
  const xAxis = asObject(datasetInfo.x_axis);
  const fileMetadata = asObject(datasetInfo.file_metadata);
  const xData = Array.isArray(xAxis.data)
    ? xAxis.data.filter(
        (value): value is number => typeof value === "number" && Number.isFinite(value),
      )
    : [];
  const source = datasetInfo.source ?? datasetInfo.name ?? fileMetadata.name ?? null;
  const technique =
    datasetInfo.technique ?? metadata.spectral_technique ?? metadata.domain_technique ?? null;
  const xTitle =
    datasetInfo.x_title ?? xAxis.title ?? metadata.x_title ?? metadata.spectral_x_title ?? null;
  const xUnits =
    datasetInfo.x_units ?? xAxis.units ?? metadata.x_units ?? metadata.spectral_x_units ?? null;
  const dataQuantity =
    datasetInfo.data_quantity ??
    datasetInfo.units ??
    metadata.data_quantity ??
    metadata.y_title ??
    null;
  const valueUnits = metadata.value_units ?? metadata.y_units ?? null;
  const datasetName =
    typeof datasetInfo.name === "string"
      ? datasetInfo.name
      : typeof metadata["sklearn.dataset_name"] === "string"
        ? metadata["sklearn.dataset_name"]
        : typeof metadata["catalog.dataset_name"] === "string"
          ? metadata["catalog.dataset_name"]
          : null;
  const featureNames =
    asStringList(datasetInfo.feature_names) ?? asStringList(metadata.feature_names);
  const targetNames =
    asStringList(datasetInfo.target_names) ??
    asStringList(metadata.target_names) ??
    asStringList(metadata.prop_names);

  return {
    dataset_id: typeof datasetInfo.dataset_id === "string" ? datasetInfo.dataset_id : null,
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
    description: typeof datasetInfo.description === "string" ? datasetInfo.description : null,
    n_samples: typeof datasetInfo.n_samples === "number" ? datasetInfo.n_samples : null,
    n_features: typeof datasetInfo.n_features === "number" ? datasetInfo.n_features : null,
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
      data_type: typeof metadata.data_type === "string" ? metadata.data_type : null,
      spectral_technique:
        typeof metadata.spectral_technique === "string" ? metadata.spectral_technique : null,
      file_name: typeof fileMetadata.name === "string" ? fileMetadata.name : null,
      has_wavenumber_axis: xData.length > 0,
    },
  };
}

export const useDataStore = defineStore("data", () => {
  // Dataset catalog (from /datasets/available)
  const availableDatasets = ref<AvailableDatasets | null>(null);
  const catalogLoading = ref(false);
  const catalogError = ref<string | null>(null);

  // Experiment list (from /experiments)
  const experiments = ref<ExperimentSummary[]>([]);
  const experimentsLoading = ref(false);
  const experimentsError = ref<string | null>(null);
  // Only a successful list response for the current project can justify an
  // inferred focus. A retained list from a failed project switch cannot.
  let experimentsProjectId: number | null = null;

  // Selected experiment files
  const activeExperimentId = ref<number | null>(null);
  const experimentFiles = ref<ExperimentFile[]>([]);
  const experimentFilesLoading = ref(false);
  // Set when the files request is refused (e.g. a superseded trial authority on
  // the managed demo server) so the UI can say so instead of showing "No files".
  const experimentFilesRefusal = ref<{ code: string | null; message: string } | null>(null);

  // File inspection
  const activeFileId = ref<number | null>(null);
  const activeFilePath = ref<string | null>(null);
  const fileInfo = ref<SherpaDatasetDict | null>(null);
  let advisorDatasetProvider: (() => Record<string, unknown>) | null = null;
  let advisorDatasetScope = "";
  const advisorScope = () => `${useAuthStore().user?.id}:${useProjectStore().currentProjectId}`;
  function registerAdvisorDatasetContext(provider: () => Record<string, unknown>): () => void {
    advisorDatasetProvider = provider;
    advisorDatasetScope = advisorScope();
    return () => {
      if (advisorDatasetProvider !== provider) return;
      const snapshot = captureAdvisorDatasetContext();
      advisorDatasetProvider = snapshot ? () => snapshot : null;
    };
  }
  function captureAdvisorDatasetContext(): Record<string, unknown> | null {
    if (advisorDatasetScope !== advisorScope()) return null;
    return advisorDatasetProvider ? JSON.parse(JSON.stringify(advisorDatasetProvider())) : null;
  }
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
  const dataStoryCache = new Map<string, string>();
  const rememberDataStory = (key: string | null | undefined, story: string) => {
    if (!key || !story.trim()) return;
    dataStoryCache.delete(key);
    dataStoryCache.set(key, story);
    if (dataStoryCache.size > 20) dataStoryCache.delete(dataStoryCache.keys().next().value!);
  };

  // Computed
  const experimentDatasets = computed<ExperimentDataset[]>(
    () => availableDatasets.value?.experiments ?? [],
  );
  const libraryDatasets = computed<LibraryDataset[]>(() => availableDatasets.value?.library ?? []);

  const currentProjectId = () => useProjectStore().currentProjectId;
  const identity = () => [useAuthStore().user?.id, useAuthStore().sessionRevision, currentProjectId()];
  const dataStoryScope = useScopedRequest(() => [...identity(), activeExperimentId.value], () => { dataStoryLoading.value = false; });
  const catalogScope = useScopedRequest(identity, () => { catalogLoading.value = false; });
  const experimentsScope = useScopedRequest(identity, () => { experimentsLoading.value = false; });
  const selectionScope = useScopedRequest(
    () => [...identity(), activeExperimentId.value],
    () => { experimentFilesLoading.value = false; },
  );
  const inspectionScope = useScopedRequest(
    () => [...identity(), activeExperimentId.value, activeFileId.value, activeFilePath.value],
    () => { fileInfoLoading.value = false; },
  );
  const assetsScope = useScopedRequest(() => [...identity(), activeExperimentId.value, activeFileId.value]);
  let assetsTicket: ScopedRequestTicket | undefined;
  const explorationScope = useScopedRequest(identity, () => { catalogDatasetLoading.value = false; });
  const referenceScope = useScopedRequest(identity, () => { referenceCatalogLoading.value = false; });
  const mutationScope = useScopedRequest(() => [...identity(), activeExperimentId.value]);
  const captureMutationScope = mutationScope.capture;
  const accountMutation = useScopedRequest(() => [useAuthStore().user?.id, useAuthStore().sessionRevision]);
  async function refreshWrittenInventories(account: ScopedRequestTicket): Promise<void> {
    if (!account.isCurrent()) return;
    // Refresh the current inventory even if the user left the written dataset.
    // Each read guards its own destination; none changes selection.
    await Promise.allSettled([fetchExperiments(), fetchCatalog(), useProjectStore().fetchProjects()]);
  }

  function resetProjectScope(): void {
    clearRetainedDatasetWorkspace(useDataStore());
    catalogScope.invalidate();
    experimentsScope.invalidate();
    selectionScope.invalidate();
    assetsScope.invalidate();
    referenceScope.invalidate();
    mutationScope.invalidate();
    clearActiveExperimentSelection();
    availableDatasets.value = null;
    experiments.value = [];
    experimentsProjectId = null;
    catalogError.value = null;
    experimentsError.value = null;
    experimentFilesRefusal.value = null;
    referenceCatalog.value = null;
    referenceCatalogError.value = null;
    advisorDatasetProvider = null;
    advisorDatasetScope = "";
    invalidateDataStory();
    dataStoryCache.clear();
    dataStoryContext.value = "";
  }
  registerProjectScopeReset(resetProjectScope);
  // Reset even without a mounted Data page (or a selectProject() caller).
  watch([() => useAuthStore().user?.id, () => useAuthStore().sessionRevision, currentProjectId], resetProjectScope, { flush: "sync" });

  // --- Actions ---

  const fetchCatalog = async (projectId: number | null = currentProjectId()) => {
    const request = catalogScope.begin();
    catalogLoading.value = true;
    catalogError.value = null;
    try {
      if (projectId == null) {
        if (request.isCurrent()) {
          availableDatasets.value = { experiments: [], library: [], builder: [] };
        }
        return;
      }
      const response = await api.get<AvailableDatasets>("/datasets/available", {
        params: { project_id: projectId },
        signal: request.signal,
      });
      const activeProjectId = currentProjectId();
      if (
        !request.isCurrent() ||
        (activeProjectId != null && projectId !== activeProjectId)
      )
        return;
      availableDatasets.value = response.data;
    } catch (error) {
      if (request.isCurrent() && projectId === currentProjectId()) {
        catalogError.value = "Dataset catalog could not be loaded.";
        console.error("Failed to fetch dataset catalog:", error);
      }
    } finally {
      if (request.isCurrent()) {
        catalogLoading.value = false;
      }
    }
  };

  const fetchExperiments = async (projectId: number | null = currentProjectId()) => {
    const request = experimentsScope.begin();
    experimentsProjectId = null;
    experimentsLoading.value = true;
    experimentsError.value = null;
    try {
      if (projectId == null) {
        if (request.isCurrent()) {
          experiments.value = [];
        }
        return;
      }
      const response = await api.get<components["schemas"]["ExperimentSummary"][]>("/experiments", {
        params: { project_id: projectId },
        signal: request.signal,
      });
      const activeProjectId = currentProjectId();
      if (
        !request.isCurrent() ||
        (activeProjectId != null && projectId !== activeProjectId)
      )
        return;
      experiments.value = response.data.map(experimentSummary);
      experimentsProjectId = projectId;
    } catch (error) {
      if (request.isCurrent() && projectId === currentProjectId()) {
        experimentsError.value = "Project datasets could not be loaded.";
        console.error("Failed to fetch experiments:", error);
      }
    } finally {
      if (request.isCurrent()) {
        experimentsLoading.value = false;
      }
    }
  };

  const selectExperiment = async (experimentId: number) => {
    clearInspection();
    clearCatalogExploration();
    activeExperimentId.value = experimentId;
    const request = selectionScope.begin();
    experimentFiles.value = [];
    experimentFilesRefusal.value = null;
    writeLastActiveExperimentId(experimentId);
    experimentFilesLoading.value = true;
    try {
      const response = await api.get<components["schemas"]["ExperimentFileOut"][]>(`/experiments/${experimentId}/files`, { signal: request.signal });
      if (!request.isCurrent())
        return;
      experimentFiles.value = response.data.map(experimentFile);
    } catch (error) {
      if (
        request.isCurrent() &&
        activeExperimentId.value === experimentId
      ) {
        console.error("Failed to fetch experiment files:", error);
        experimentFiles.value = [];
        experimentFilesRefusal.value = {
          code: getErrorCode(error),
          message: getErrorMessage(error, "The dataset's files could not be loaded."),
        };
      }
    } finally {
      if (request.isCurrent()) {
        experimentFilesLoading.value = false;
      }
    }
  };

  const createExperiment = async (
    name: string,
    description?: string,
    projectId?: number | null,
    metadata?: Record<string, unknown>,
  ) => {
    const account = accountMutation.capture();
    const payload = {
      name,
      description: description || null,
      metadata: metadata ?? {},
      project_id: projectId ?? null,
    } satisfies components["schemas"]["ExperimentCreate"];
    const response = await api.post<components["schemas"]["ExperimentDetail"]>("/experiments", payload);
    // Refresh both lists
    await refreshWrittenInventories(account);
    return experimentDetail(response.data);
  };

  const updateExperiment = async (
    experimentId: number,
    payload: components["schemas"]["ExperimentUpdate"],
  ) => {
    const account = accountMutation.capture();
    const response = await api.put<components["schemas"]["ExperimentDetail"]>(`/experiments/${experimentId}`, payload);
    await refreshWrittenInventories(account);
    return experimentDetail(response.data);
  };

  const deleteExperiment = async (experimentId: number) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    const deletingActiveExperiment = activeExperimentId.value === experimentId;
    let fallbackExperimentId: number | null = null;

    if (deletingActiveExperiment) {
      const currentIndex = experiments.value.findIndex(
        (experiment) => experiment.id === experimentId,
      );
      if (currentIndex >= 0) {
        fallbackExperimentId =
          experiments.value[currentIndex + 1]?.id ??
          experiments.value[currentIndex - 1]?.id ??
          null;
      }
    }

    await api.delete(`/experiments/${experimentId}`);
    await refreshWrittenInventories(account);
    if (!request.isCurrent()) return;

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
    const request = captureMutationScope();
    if (
      activeExperimentId.value !== null &&
      experiments.value.some((experiment) => experiment.id === activeExperimentId.value)
    ) {
      return;
    }
    if (experiments.value.length === 0 && !experimentsError.value) {
      await fetchExperiments();
    }
    if (!request.isCurrent()) return;
    if (
      activeExperimentId.value !== null &&
      !experiments.value.some((experiment) => experiment.id === activeExperimentId.value)
    ) {
      clearActiveExperimentSelection();
    }
    const remembered = readLastActiveExperimentId();
    if (
      remembered !== null &&
      experiments.value.some((experiment) => experiment.id === remembered)
    ) {
      await selectExperiment(remembered);
    } else if (
      currentProjectId() != null &&
      experimentsProjectId === currentProjectId() &&
      experiments.value.length === 1
    ) {
      // A new browser has no remembered focus. The sole dataset is unambiguous;
      // multiple datasets still require the user's choice.
      await selectExperiment(experiments.value[0].id);
    }
  };

  const clearActiveExperimentSelection = () => {
    selectionScope.invalidate();
    clearInspection();
    clearCatalogExploration();
    activeExperimentId.value = null;
    experimentFiles.value = [];
    experimentFilesLoading.value = false;
  };

  const uploadFile = async (
    experimentId: number,
    file: File,
    stage: string,
    options?: {
      dataRole?: string | null;
      targetColumn?: string | null;
      targetType?: string | null;
      /** Refresh the selected detail; durable catalogue writes always refresh inventories. */
      refresh?: boolean;
    },
  ) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
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
    const response = await api.post<components["schemas"]["ExperimentFileOut"]>(`/experiments/${experimentId}/files`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    await refreshWrittenInventories(account);
    if (options?.refresh !== false) {
      if (request.isCurrent()) await selectExperiment(experimentId);
    }
    return experimentFile(response.data);
  };

  const fetchDataMatrix = async (ref: DataMatrixRef): Promise<DataMatrixResponse> => {
    const response = await api.post<DataMatrixResponse>("/builder/data-matrix", ref);
    return response.data;
  };

  const stageUploadFile = async (file: File): Promise<StagedUpload> => {
    const form = new FormData();
    form.append("file", file);
    if (currentProjectId() != null) form.append("project_id", String(currentProjectId()));
    const response = await api.post<StagedUpload>("/builder/upload/stage", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  };

  const stageUploadBatch = async (files: File[]): Promise<StagedUploadBatch> => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    if (currentProjectId() != null) form.append("project_id", String(currentProjectId()));
    const response = await api.post<StagedUploadBatch>("/builder/upload/stage-batch", form, {
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
    boschProcessStagingId: string | null = null,
  ) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    const response = await api.post("/builder/upload/commit", {
      experiment_id: experimentId,
      stage,
      files,
      ...(boschProcessStagingId ? { bosch_process_staging_id: boschProcessStagingId } : {}),
    });
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await selectExperiment(experimentId);
    return response.data;
  };

  const deleteFile = async (experimentId: number, fileId: number) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    await api.delete(`/experiments/${experimentId}/files/${fileId}`);
    await refreshWrittenInventories(account);
    if (!request.isCurrent()) return;
    // Refresh file list and catalog
    await selectExperiment(experimentId);
    // Clear inspection if deleted file was being inspected
    if (activeFileId.value === fileId) {
      clearInspection();
    }
  };

  const fetchFileAssets = async (
    experimentId: number,
    fileId: number,
  ): Promise<ExperimentFileAssets> => {
    // A collection reads sibling file inventories concurrently. They share the
    // selection lease; starting one read must not cancel another file's read.
    if (!assetsTicket?.isCurrent()) assetsTicket = assetsScope.begin();
    const request = assetsTicket;
    fileInfoError.value = null;
    try {
      const response = await api.get<components["schemas"]["ExperimentFileAssetsOut"]>(
        `/experiments/${experimentId}/files/${fileId}/scientific-assets`,
        { signal: request.signal },
      );
      return experimentFileAssets(response.data);
    } catch (error: unknown) {
      if (request.isCurrent()) fileInfoError.value = getErrorMessage(error, "Failed to inspect scientific results");
      throw error;
    }
  };

  const inspectFile = async (
    fileId: number,
    filePath: string,
    experimentId?: number,
    assetId?: string | null,
  ) => {
    clearCatalogExploration();
    activeFileId.value = fileId;
    activeFilePath.value = filePath;
    const request = inspectionScope.begin();
    fileInfoLoading.value = true;
    fileInfoError.value = null;
    try {
      // A project file is an exact one-member collection. Use the same loader
      // as curation/workflow admission, rather than the loose-file preview.
      const body: Record<string, unknown> = experimentId != null
        ? { experiment_id: experimentId, file_ids: [fileId] }
        : { file_path: filePath };
      if (assetId) body.asset_id = assetId;
      const response = await api.post<SherpaDatasetDict>("/builder/file-info", body, {
        signal: request.signal,
      });
      if (request.isCurrent()) fileInfo.value = response.data;
      return response.data;
    } catch (error: unknown) {
      if (request.isCurrent()) {
        fileInfoError.value = getErrorMessage(error, "Failed to inspect file");
      }
      throw error;
    } finally {
      if (request.isCurrent()) {
        fileInfoLoading.value = false;
      }
    }
  };

  /** Change the curve/file focus without replacing the admitted collection preview. */
  const activateFile = (fileId: number, filePath: string) => {
    activeFileId.value = fileId;
    activeFilePath.value = filePath;
  };

  const bindDatasetAnalysisCsv = async (payload: {
    sourceFileId: number;
    sampleTableFileId: number;
    expectedRevision: string | null;
    selectedTarget: string;
    targetType: "continuous" | "categorical";
    referenceDeclaration?: import("@/types").ReferenceDeclarationDraft | null;
  }) => {
    const response = await api.post("/builder/analysis-binding", {
      source_file_id: payload.sourceFileId,
      sample_table_file_id: payload.sampleTableFileId,
      expected_revision: payload.expectedRevision,
      selected_target: payload.selectedTarget,
      target_type: payload.targetType,
      reference_declaration: payload.referenceDeclaration ?? null,
    });
    return response.data;
  };

  const unbindDatasetAnalysisCsv = async (
    sourceFileId: number,
    expectedRevision: string,
  ) => {
    const response = await api.delete(`/builder/analysis-binding/${sourceFileId}`, {
      params: { expected_revision: expectedRevision },
    });
    return response.data;
  };

  const inspectExperimentRawFiles = async (
    experimentId: number,
    assetId?: string | null,
    fileIds?: number[] | null,
  ) => {
    activeFileId.value = null;
    activeFilePath.value = null;
    const request = inspectionScope.begin();
    fileInfoLoading.value = true;
    fileInfoError.value = null;
    clearCatalogExploration();
    try {
      const response = await api.post<SherpaDatasetDict>(
        "/builder/file-info",
        {
          experiment_id: experimentId,
          ...(assetId ? { asset_id: assetId } : {}),
          ...(fileIds?.length ? { file_ids: fileIds } : {}),
        },
        { signal: request.signal },
      );
      if (request.isCurrent()) {
        fileInfoLoading.value = false;
        fileInfo.value = response.data;
        // A one-file selection is still an inspectable source file. Preserve
        // that identity so dependent panels can retrieve the full matrix and
        // other file-scoped metadata instead of treating the response as a
        // multi-file aggregate with no active source.
        const stage = response.data.metadata?.contents_stage ?? "raw";
        const sourceFiles = experimentFiles.value.filter((file) =>
          fileIds?.length ? fileIds.includes(file.id) : file.stage === stage,
        );
        const soleFileId = fileIds?.length === 1
          ? fileIds[0]
          : !fileIds?.length && activeExperimentId.value === experimentId && sourceFiles.length === 1
            ? sourceFiles[0].id
            : null;
        activeFileId.value = soleFileId;
        activeFilePath.value = sourceFiles.find((file) => file.id === soleFileId)?.file_path ?? null;
      }
      return response.data;
    } catch (error: unknown) {
      if (request.isCurrent()) {
        fileInfoError.value = getErrorMessage(error, "Failed to inspect dataset contents");
      }
      throw error;
    } finally {
      if (request.isCurrent()) {
        fileInfoLoading.value = false;
      }
    }
  };

  const downloadFile = async (fileId: number, fileName: string) => {
    const response = await api.get(`/datasets/download/${fileId}`, {
      responseType: "blob",
    });
    downloadBlob(blobFromResponseData(response.data), fileName);
  };

  const clearInspection = () => {
    inspectionScope.invalidate();
    fileInfoLoading.value = false;
    activeFileId.value = null;
    activeFilePath.value = null;
    fileInfo.value = null;
    fileInfoError.value = null;
  };

  // --- Reference dataset catalog actions ---

  const fetchReferenceCatalog = async () => {
    const request = referenceScope.begin();
    referenceCatalogLoading.value = true;
    referenceCatalogError.value = null;
    try {
      const response = await api.get<ReferenceCatalog>("/builder/reference-datasets", { signal: request.signal });
      if (request.isCurrent()) referenceCatalog.value = response.data;
    } catch (error: unknown) {
      if (!request.isCurrent()) return;
      console.error("Failed to fetch reference catalog:", error);
      referenceCatalogError.value = getErrorMessage(error, "Failed to load reference catalog");
    } finally {
      if (request.isCurrent()) referenceCatalogLoading.value = false;
    }
  };

  const importReferenceDatasets = async (
    experimentId: number,
    datasets: Array<{ source: string; name: string; overrides?: PreparedDataOverrides | null }>,
  ) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    const response = await api.post(`/experiments/${experimentId}/import-reference`, { datasets });
    const admittedExperimentId = response.data.experiment_id ?? experimentId;
    // Refresh file list and experiment list to reflect new files
    // The server has committed. A display refresh must not turn this into an
    // import refusal and cause the caller to delete the admitted dataset.
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await Promise.allSettled([selectExperiment(admittedExperimentId)]);
    return response.data as {
      imported: number;
      files: ExperimentFile[];
      experiment_id?: number | null;
      reused_existing?: boolean;
      initial_file_ids?: number[];
    };
  };

  const importRegisteredReference = async (
    experimentId: number,
    authority: { projectionId?: string; packageId?: string },
    files: File | File[],
  ) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    const form = new FormData();
    if (authority.packageId) form.append("package_id", authority.packageId);
    else if (authority.projectionId) form.append("projection_id", authority.projectionId);
    else throw new Error("Registered reference import requires a projection or package identity");
    for (const file of Array.isArray(files) ? files : [files]) {
      form.append("file", file, file.name);
    }
    const response = await api.post(
      `/experiments/${experimentId}/import-registered-reference`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    const admittedExperimentId = response.data.experiment_id ?? experimentId;
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await Promise.allSettled([selectExperiment(admittedExperimentId)]);
    return response.data as {
      imported: number;
      files: ExperimentFile[];
      experiment_id?: number | null;
      reused_existing?: boolean;
      initial_file_ids: number[];
    };
  };

  const importLibraryDatasets = async (
    experimentId: number,
    payload:
      | {
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
            y_quantity?: string | null;
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
        }
      | number[],
  ) => {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    const requestPayload = Array.isArray(payload)
      ? { experiment_id: experimentId, library_ids: payload }
      : { experiment_id: experimentId, ...payload };
    const response = await api.post("/datasets/library/import", {
      ...requestPayload,
    });
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await selectExperiment(experimentId);
    return response.data;
  };

  const exploreCatalogDataset = async (source: string, name: string) => {
    const request = explorationScope.begin();
    catalogDatasetLoading.value = true;
    catalogDatasetInfo.value = null;
    catalogDatasetError.value = null;
    // Capture the project for this request; a late reply cannot populate a
    // different project's source preview after the user switches context.
    const projectId = currentProjectId();
    // Clear file inspection so Explore tab shows catalog card
    clearInspection();
    try {
      const response = await api.get<CatalogDatasetInfo>(
        `/builder/reference-datasets/${source}/${name}`,
        { params: { project_id: projectId }, signal: request.signal },
      );
      if (!request.isCurrent()) return;
      catalogDatasetInfo.value = response.data;
    } catch (error: unknown) {
      if (request.isCurrent()) catalogDatasetError.value = getErrorMessage(error, "Failed to load dataset info");
    } finally {
      if (request.isCurrent()) catalogDatasetLoading.value = false;
    }
  };

  const invalidateDataStory = () => {
    dataStoryScope.invalidate();
    dataStoryText.value = null;
    dataStoryMemoryScopes.value = [];
    dataStoryLoading.value = false;
  };

  const generateDataStory = async (
    inspectedSource?: SherpaDatasetDict | null,
    options?: { cacheKey?: string | null; force?: boolean },
  ) => {
    const cacheKey = options?.cacheKey;
    if (cacheKey && !options?.force && dataStoryCache.has(cacheKey)) {
      dataStoryScope.invalidate();
      dataStoryText.value = dataStoryCache.get(cacheKey)!;
      dataStoryMemoryScopes.value = [];
      dataStoryLoading.value = false;
      return;
    }
    if (cacheKey && options?.force) dataStoryCache.delete(cacheKey);
    const request = dataStoryScope.begin();
    dataStoryLoading.value = true;
    try {
      // The caller supplies the already-parsed, unfiltered source inspection.
      // Never start a separate file-info request for Data Story.
      const datasetInfo = inspectedSource ?? catalogDatasetInfo.value ?? fileInfo.value;
      if (!request.isCurrent() || !datasetInfo) return;

      const { appMode, isFeatureEnabled } = useAppConfig();
      if (appMode.value === "local") {
        if (!isFeatureEnabled("chatAssistant")) {
          throw new Error("Configure a local chat endpoint in Settings to generate a Data Story.");
        }
        dataStoryText.value = "";
        dataStoryMemoryScopes.value = [];
        const result = await streamLocalDataStory(
          datasetInfo as StoryObject,
          dataStoryContext.value,
          (chunk) => {
            if (request.isCurrent()) {
              dataStoryText.value = `${dataStoryText.value ?? ""}${chunk}`;
            }
          },
          request.signal,
        );
        if (request.isCurrent()) {
          dataStoryText.value = result;
          rememberDataStory(cacheKey, result);
        }
        return;
      }

      const { useSherpaStore } = await import("@/stores/sherpa");
      const sherpa = useSherpaStore();
      if (sherpa.isSyncing || sherpa.isChatting) return;

      // Use the Sherpa WS proxy path: entitlement-gated, server-side prompt/template
      const { useLlmStore } = await import("@/stores/llm");
      const llm = useLlmStore();
      const advisorStore = useAdvisorStore();
      const projectStore = useProjectStore();
      await llm.connect();
      if (!request.isCurrent()) return;
      const ws = llm.wsRef;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        throw new Error("WebSocket not connected. Try again in a moment.");
      }

      const summarized = buildDataStoryContext(datasetInfo as StoryObject);
      dataStoryText.value = ""; // Show progressive text as chunks arrive
      dataStoryMemoryScopes.value = [];

      const result = await new Promise<string>((resolve, reject) => {
        const requestId = createSherpaRequestId();
        const timeout = window.setTimeout(() => {
          cleanup();
          const partial = dataStoryText.value;
          if (partial) {
            // Got partial text — resolve with what we have
            console.warn(
              `Data story timeout after 180s, returning ${partial.length} chars of partial text`,
            );
            resolve(partial);
          } else {
            reject(
              new Error(
                "Data story generation timed out (180s, 0 chunks received). " +
                  "Check server logs: docker compose logs backend | grep data_story",
              ),
            );
          }
        }, sherpaResponseTimeoutMs());

        const unsubscribe = subscribeSherpaEvents(
          (payload) => {
            if (!request.isCurrent()) {
              cleanup();
              resolve("");
              return;
            }
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
                  : (dataStoryText.value ?? ""),
              );
            } else if (payload.type === SHERPA_WS_EVENT.dataStoryError) {
              cleanup();
              const diag = payload.diagnostics;
              const detail = payload.detail || "Data story generation failed";
              const diagRecord = diag && typeof diag === "object" ? diag : null;
              const diagSummary = diag
                ? ` [stage=${String(diagRecord?.stage ?? "?")}, elapsed=${String(diagRecord?.elapsed_s ?? "?")}s, provider=${String(diagRecord?.provider ?? "?")}]`
                : "";
              console.error("Data story error:", detail, diag);
              reject(new Error(detail + diagSummary));
            } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
              cleanup();
              reject(new Error("Subscription required for Data Story generation."));
            }
          },
          {
            requestId,
            types: [
              SHERPA_WS_EVENT.dataStoryChunk,
              SHERPA_WS_EVENT.dataStoryResult,
              SHERPA_WS_EVENT.dataStoryError,
              SHERPA_WS_EVENT.subscriptionRequired,
            ],
          },
        );

        const onAbort = () => {
          cleanup();
          resolve("");
        };
        const cleanup = () => {
          clearTimeout(timeout);
          unsubscribe();
          request.signal.removeEventListener("abort", onAbort);
        };
        request.signal.addEventListener("abort", onAbort, { once: true });
        if (!request.isCurrent()) { onAbort(); return; }

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
          }),
        );
      });

      if (request.isCurrent()) {
        dataStoryText.value = result;
        rememberDataStory(cacheKey, result);
      }
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (request.isCurrent()) {
        console.error("Failed to generate data story:", error);
        dataStoryMemoryScopes.value = [];
        dataStoryText.value = getErrorMessage(
          error,
          "Unable to generate data story. Check your LLM configuration.",
        );
      }
    } finally {
      if (request.isCurrent()) {
        dataStoryLoading.value = false;
      }
    }
  };

  const clearCatalogExploration = () => {
    explorationScope.invalidate();
    dataStoryScope.invalidate();
    catalogDatasetInfo.value = null;
    catalogDatasetError.value = null;
    dataStoryText.value = null;
    dataStoryMemoryScopes.value = [];
    dataStoryLoading.value = false;
    dataStoryContext.value = "";
  };

  return {
    // State
    registerAdvisorDatasetContext,
    captureAdvisorDatasetContext,
    availableDatasets,
    catalogLoading,
    catalogError,
    experiments,
    experimentsLoading,
    experimentsError,
    activeExperimentId,
    experimentFiles,
    experimentFilesLoading,
    experimentFilesRefusal,
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
    invalidateDataStory,
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
    stageUploadBatch,
    deleteStagedUpload,
    commitStagedUploads,
    deleteFile,
    inspectFile,
    activateFile,
    unbindDatasetAnalysisCsv,
    bindDatasetAnalysisCsv,
    inspectExperimentRawFiles,
    fetchFileAssets,
    downloadFile,
    clearInspection,
    fetchReferenceCatalog,
    importRegisteredReference,
    importReferenceDatasets,
    importLibraryDatasets,
    exploreCatalogDataset,
    generateDataStory,
    clearCatalogExploration,
  };
});
