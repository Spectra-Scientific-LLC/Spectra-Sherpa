import { computed, ref, watch } from "vue";
import { selectionSeriesColor } from "@/theme/plotTheme";
import { seriesPalette } from "@/utils/colors";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import type { DatasetPlotSource, SherpaDatasetDict, ExperimentFile } from "@/types";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import { getErrorMessage } from "@/utils/errors";
export type StepSelection = components["schemas"]["StepSelection"];
export type StepPortfolio = components["schemas"]["PortfolioOut"];
export type StepEntry = {
  experimentId: number;
  file: ExperimentFile;
  catalog: components["schemas"]["BoschStepsOut"];
};

export function stepSelectionKey(s: Pick<StepSelection, "experiment_id" | "file_id" | "asset_id" | "step_id">): string {
  const step = ["etch", "passivation"].includes(s.step_id) ? "production" : s.step_id;
  return `${s.experiment_id}:${s.file_id}:${s.asset_id}:${step}`;
}

/** Application adapter for retained segmentation. Never uploads, segments or averages. */
export function useProcessingStepSelection(
  identity: () => readonly ScopeIdentity[],
  project: () => number | null,
) {
  const colorSlots = ref<Record<string, number>>({});
  const groupColors = computed(() => Object.fromEntries(Object.entries(colorSlots.value).map(([key, index]) => [key, selectionSeriesColor(seriesPalette("overlay"), index)])));
  const entries = ref<StepEntry[]>([]),
    selections = ref<StepSelection[]>([]);
  const sourceExperimentIds = ref<number[]>([]);
  const portfolios = ref<StepPortfolio[]>([]),
    selectedPortfolio = ref<StepPortfolio | null>(null);
  const loading = ref(false),
    busy = ref(false),
    error = ref<string | null>(null);
  const preview = ref<DatasetPlotSource[]>([]),
    previewLoading = ref(false),
    previewError = ref<string | null>(null);
  const listing = useScopedRequest(identity, () => {
    entries.value = [];
    sourceExperimentIds.value = [];
    selections.value = [];
    portfolios.value = [];
    selectedPortfolio.value = null;
    loading.value = false;
    error.value = null;
  });
  const writes = useScopedRequest(
    () => [...identity(), JSON.stringify(selections.value)],
    () => {
      busy.value = false;
    },
  );
  const plotting = useScopedRequest(
    () => [...identity(), JSON.stringify(selections.value)],
    () => {
      preview.value = [];
      previewLoading.value = false;
      previewError.value = null;
    },
  );
  watch(selections, () => {
    selectedPortfolio.value = null;
    for (const s of selections.value) {
      const key = stepSelectionKey(s);
      if (!(key in colorSlots.value)) colorSlots.value[key] = Object.keys(colorSlots.value).length;
    }
  }, { flush: "sync" });
  const active = computed(() => selections.value.length > 0 || selectedPortfolio.value != null);
  let pendingLoad: Promise<void> = Promise.resolve();
  function load(experimentIds: number[], filesForActive: StepEntry["file"][], activeId: number, fileSelections?: Record<number, readonly {id: number}[] | null>) {
    pendingLoad = loadCatalogs(experimentIds, filesForActive, activeId, fileSelections);
    return pendingLoad;
  }
  async function loadCatalogs(
    experimentIds: number[],
    filesForActive: StepEntry["file"][],
    activeId: number,
    fileSelections?: Record<number, readonly {id: number}[] | null>,
  ) {
    const ticket = listing.begin();
    entries.value = [];
    sourceExperimentIds.value = [];
    selections.value = [];
    selectedPortfolio.value = null;
    error.value = null;
    const projectId = project();
    if (projectId == null) return;
    loading.value = true;
    try {
      const savedPortfolios = (
        await api.get<StepPortfolio[]>(`/projects/${projectId}/time-series-portfolios`, {
          signal: ticket.signal,
        })
      ).data;
      if (!ticket.isCurrent()) return;
      portfolios.value = savedPortfolios;
      for (const experimentId of experimentIds) {
        if (!ticket.isCurrent()) return;
        const files =
          experimentId === activeId
            ? filesForActive
            : (
                await api.get<StepEntry["file"][]>(`/experiments/${experimentId}/files`, {
                  signal: ticket.signal,
                })
              ).data;
        for (const file of files.filter((f) => (!fileSelections || fileSelections[experimentId] === null || fileSelections[experimentId]?.some(selected => selected.id === f.id)) && /Day_\d{4}_\d{2}_\d{2}.*\.nc$/i.test(f.file_path))) {
          if (!ticket.isCurrent()) return;
          if (!sourceExperimentIds.value.includes(experimentId))
            sourceExperimentIds.value.push(experimentId);
          try {
            const catalog = (
              await api.get<StepEntry["catalog"]>(
                `/experiments/${experimentId}/files/${file.id}/bosch-steps`,
                { signal: ticket.signal },
              )
            ).data;
            if (ticket.isCurrent()) entries.value.push({ experimentId, file, catalog });
          } catch (e) {
            if (ticket.isCurrent())
              error.value = `${file.file_path.split("/").pop()}: prepare processing steps in Upload. ${getErrorMessage(e, "Saved alignment unavailable")}`;
          }
        }
      }
    } catch (e) {
      if (ticket.isCurrent()) error.value = getErrorMessage(e, "Processing steps unavailable");
    } finally {
      if (ticket.isCurrent()) loading.value = false;
    }
  }
  async function save(name: string) {
    const projectId = project();
    if (projectId == null || !selections.value.length || busy.value) return;
    const ticket = writes.begin();
    busy.value = true;
    error.value = null;
    const payload = { name, selections: selections.value.map((s) => ({ ...s })) };
    try {
      const saved = (
        await api.post<StepPortfolio>(`/projects/${projectId}/time-series-portfolios`, payload, {
          signal: ticket.signal,
        })
      ).data;
      if (!ticket.isCurrent()) return;
      portfolios.value.push(saved);
      selectedPortfolio.value = saved;
      return saved;
    } catch (e) {
      if (ticket.isCurrent()) error.value = getErrorMessage(e, "Portfolio could not be saved");
    } finally {
      if (ticket.isCurrent()) busy.value = false;
    }
  }
  async function show(saved: StepPortfolio) {
    const unavailable = saved.selection.partitions.some(
      (p) =>
        !entries.value.some(
          (e) =>
            e.experimentId === p.experiment_id &&
            e.file.id === p.file_id &&
            e.catalog.source_sha256 === p.source_sha256 &&
            e.catalog.process_sha256 === p.process_sha256,
        ),
    );
    if (unavailable) {
      error.value =
        "Saved portfolio sources differ from the prepared Upload data or are unavailable. Restore the exact source files before using this portfolio.";
      clear();
      return;
    }
    // Restore exact source selectors; canonical Load always binds the immutable receipt hash.
    selections.value = saved.selection.partitions.map((p) => ({
      experiment_id: p.experiment_id,
      file_id: p.file_id,
      process_file_id: p.process_file_id,
      asset_id: p.asset_id,
      step_id: p.step_id as StepSelection["step_id"],
    }));
    selectedPortfolio.value = saved;
  }
  function clear() {
    selections.value = [];
    selectedPortfolio.value = null;
  }
  async function compare() {
    const ticket = plotting.begin();
    previewLoading.value = true;
    previewError.value = null;
    preview.value = [];
    const sources = new Map<number, DatasetPlotSource>();
    try {
      if (selections.value.length > 50)
        throw new Error(
          "Preview at most 50 wafer / step selections at once. Saved portfolios retain the full selection.",
        );
      for (const selection of selections.value.map((s) => ({ ...s }))) {
        const entry = entries.value.find(
          (e) => e.experimentId === selection.experiment_id && e.file.id === selection.file_id,
        );
        const wafer = entry?.catalog.wafers.find((w) => w.asset_id === selection.asset_id);
        if (!entry || !wafer)
          throw new Error("Selected source is unavailable in the current dataset scope.");
        const phases =
          selection.step_id === "production"
            ? ["etch", "passivation"]
            : ["etch", "passivation"].includes(selection.step_id)
              ? [selection.step_id]
            : selection.step_id === "gas1"
              ? ["gas1_plasma"]
              : ["mixed_plasma"];
        for (const phase of wafer.steps.filter((s) => phases.includes(s.step_id))) {
          const response = await api.post<components["schemas"]["BoschStepPreviewOut"]>(
            `/experiments/${entry.experimentId}/files/${entry.file.id}/bosch-step-preview`,
            {
              process_file_id: selection.process_file_id,
              asset_id: selection.asset_id,
              step_id: phase.step_id,
              source_sha256: entry.catalog.source_sha256,
              process_sha256: entry.catalog.process_sha256,
              max_rows: 4,
            },
            { signal: ticket.signal },
          );
          if (!ticket.isCurrent()) return;
          let source = sources.get(entry.experimentId);
          if (!source) {
            source = {
              experimentId: entry.experimentId,
              name: `Selected processing steps · ${entry.experimentId}`,
              members: [],
              selectedFileCount: 0,
              totalFileCount: entries.value.filter((e) => e.experimentId === entry.experimentId)
                .length,
            };
            sources.set(entry.experimentId, source);
          }
          source.members.push({
            fileId: entry.file.id,
            fileName: entry.file.file_path,
            curveGroupColor: groupColors.value[stepSelectionKey(selection)],
            curveGroupLabel: `${entry.catalog.date} · ${wafer.asset_id} · ${phase.label}`,
            dataset: response.data.dataset as unknown as SherpaDatasetDict,
          });
          source.selectedFileCount = new Set(source.members.map((m) => m.fileId)).size;
        }
      }
      if (ticket.isCurrent()) preview.value = [...sources.values()];
    } catch (e) {
      if (ticket.isCurrent())
        previewError.value = getErrorMessage(e, "Preview could not be loaded");
    } finally {
      if (ticket.isCurrent()) previewLoading.value = false;
    }
  }
  return {
    groupColors,
    entries,
    sourceExperimentIds,
    ready: () => pendingLoad,
    selections,
    portfolios,
    selectedPortfolio,
    active,
    loading,
    busy,
    error,
    preview,
    previewLoading,
    previewError,
    load,
    save,
    show,
    clear,
    compare,
  };
}
