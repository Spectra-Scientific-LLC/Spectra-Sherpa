<template>
  <div class="workflow-portfolio-picker" aria-label="Workflow data portfolio">
    <label for="workflow-data-portfolio">Data Portfolio</label>
    <div class="picker-controls">
      <select
        id="workflow-data-portfolio"
        v-model="selectedKey"
        :disabled="busy || !options.length"
        @change="applySelection"
      >
        <option v-for="option in options" :key="option.key" :value="option.key">
          {{ option.label }}
        </option>
      </select>
      <button v-if="!bound && selectedKey" type="button" :disabled="busy" @click="applySelection">
        Use selected
      </button>
    </div>
    <small v-if="busy" role="status">Checking portfolio…</small>
    <small v-else-if="!options.length">Save or choose a Data Portfolio in My Dataset first.</small>
    <small v-else-if="!bound">Choose this portfolio to bind it to the sheet.</small>
    <small v-else>Exact source, target, and groups are bound to this sheet.</small>
    <small v-if="error" class="picker-error" role="alert">{{ error }}</small>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import { getErrorMessage } from "@/utils/errors";

interface Receipt {
  experiment_id: number;
  stage: "raw" | "preprocessed" | "synthetic";
  selected_file_ids: number[] | null;
  asset_id: string | null;
  source_manifest_sha256: string;
  collection_definition_sha256: string | null;
  scientific_collection_sha256: string;
  target_authority: Record<string, unknown> | null;
  group_column: string | null;
}
interface PortfolioOption {
  key: string;
  label: string;
  selection: Receipt;
  viewId: number | null;
  viewSha: string | null;
}
interface PortfolioList {
  active: { name: string; dataset_view_id: number | null; digest: string; selection: Receipt } | null;
  views: Array<{ id: number; name: string; experiment_id: number; selection_sha256: string; selection: Receipt }>;
}
interface SelectionContext {
  current_revision: { revision_number: number } | null;
  saved_selection: (Receipt & { dataset_view_id?: number | null; dataset_view_sha256?: string | null }) | null;
}

const props = defineProps<{ projectId: number | null; workflowId: number | null; nodeId: string }>();
const workflowStore = useWorkflowStore();
const options = ref<PortfolioOption[]>([]);
const selectedKey = ref("");
const bound = ref(false);
const busy = ref(false);
const error = ref("");
let generation = 0;
let creatingSheetForSelection = false;

watch(
  () => [props.projectId, props.workflowId, props.nodeId] as const,
  ([projectId, workflowId, nodeId], previous) => {
    // Saving a new sheet assigns its ID before this same selection request
    // finishes. Do not cancel that request as though another sheet opened.
    if (creatingSheetForSelection && previous &&
      previous[0] === projectId && previous[1] == null && workflowId != null && previous[2] === nodeId) return;
    void load();
  },
  { immediate: true },
);

async function load(): Promise<void> {
  const ticket = ++generation;
  options.value = [];
  selectedKey.value = "";
  bound.value = false;
  error.value = "";
  if (props.projectId == null) return;
  busy.value = true;
  try {
    const [portfoliosResponse, contextResponse] = await Promise.all([
      api.get<PortfolioList>(`/projects/${props.projectId}/choices/dataset-portfolios`),
      props.workflowId == null
        ? Promise.resolve(null)
        : api.get<SelectionContext>(`/workflows/${props.workflowId}/data-selections/${encodeURIComponent(props.nodeId)}`),
    ]);
    if (ticket !== generation) return;
    const catalog = portfoliosResponse.data;
    const choices: PortfolioOption[] = [];
    if (catalog.active) choices.push({
      key: "active", label: `Active · ${catalog.active.name}`,
      selection: catalog.active.selection,
      viewId: catalog.active.dataset_view_id,
      viewSha: catalog.active.dataset_view_id ? catalog.active.digest : null,
    });
    for (const view of catalog.views) choices.push({
      key: `view:${view.id}`, label: view.name,
      selection: view.selection, viewId: view.id, viewSha: view.selection_sha256,
    });
    const saved = contextResponse?.data.saved_selection;
    const matching = saved?.dataset_view_id != null
      ? choices.find((option) => option.viewId === saved.dataset_view_id && option.viewSha === saved.dataset_view_sha256)
      : choices.find((option) => option.viewId === null && saved &&
          ["experiment_id", "stage", "selected_file_ids", "asset_id", "source_manifest_sha256",
            "collection_definition_sha256", "scientific_collection_sha256", "target_authority", "group_column"]
            .every((key) => JSON.stringify(option.selection[key as keyof Receipt]) === JSON.stringify(saved[key as keyof Receipt])));
    if (saved && !matching) choices.unshift({
      key: "sheet", label: "Current sheet source",
      selection: saved, viewId: saved.dataset_view_id ?? null, viewSha: saved.dataset_view_sha256 ?? null,
    });
    options.value = choices;
    selectedKey.value = matching?.key ?? (saved ? "sheet" : choices[0]?.key ?? "");
    bound.value = Boolean(saved);
  } catch (failure) {
    if (ticket === generation) error.value = getErrorMessage(failure, "Data portfolios could not be loaded.");
  } finally {
    if (ticket === generation) busy.value = false;
  }
}

async function applySelection(): Promise<void> {
  const option = options.value.find((entry) => entry.key === selectedKey.value);
  const projectId = props.projectId;
  const nodeId = props.nodeId;
  if (!option || projectId == null || busy.value || option.key === "sheet") return;
  const ticket = ++generation;
  busy.value = true;
  error.value = "";
  try {
    creatingSheetForSelection = props.workflowId == null;
    // Persist draft graph edits first. The selection endpoint changes a saved
    // revision; reloading it while the canvas is dirty would discard edits.
    const workflowId = props.workflowId == null || workflowStore.hasUnsavedChanges
      ? await workflowStore.saveWorkflow({ createVersion: false, projectId })
      : props.workflowId;
    if (workflowStore.hasUnsavedChanges) {
      throw new Error("The sheet changed while saving. Save it, then choose the portfolio again.");
    }
    const context = (await api.get<SelectionContext>(
      `/workflows/${workflowId}/data-selections/${encodeURIComponent(nodeId)}`,
    )).data;
    const selection = {
      experiment_id: option.selection.experiment_id,
      dataset_name: option.label.replace(/^Active · /, ""),
      stage: option.selection.stage,
      selected_file_ids: option.selection.selected_file_ids,
      asset_id: option.selection.asset_id,
      source_manifest_sha256: option.selection.source_manifest_sha256,
      collection_definition_sha256: option.selection.collection_definition_sha256,
      scientific_collection_sha256: option.selection.scientific_collection_sha256,
      target_authority: option.selection.target_authority,
      group_column: option.selection.group_column,
      dataset_view_id: option.viewId,
      dataset_view_sha256: option.viewSha,
    };
    if (ticket !== generation || props.projectId !== projectId || props.nodeId !== nodeId) return;
    if (workflowStore.hasUnsavedChanges) {
      throw new Error("The canvas changed while preparing the portfolio. Save it and choose the portfolio again.");
    }
    await api.put(`/workflows/${workflowId}/data-selections/${encodeURIComponent(nodeId)}`, {
      expected_revision: context.current_revision?.revision_number ?? null,
      idempotency_key: typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `portfolio-${Date.now()}`,
      origin: "canvas",
      reason: null,
      selection,
    });
    if (ticket !== generation || props.projectId !== projectId || props.nodeId !== nodeId) return;
    if (workflowStore.hasUnsavedChanges) {
      // The server selection was recorded, but a newer local edit must never
      // be discarded by loadWorkflow. A retry saves that edit then reapplies
      // the chosen portfolio to the resulting graph revision.
      bound.value = false;
      error.value = "The portfolio was recorded, but the canvas changed during the request. Your edits remain here; choose the portfolio again to save and combine them.";
      return;
    }
    bound.value = true;
    await workflowStore.loadWorkflow(workflowId, undefined, () => !workflowStore.hasUnsavedChanges);
    if (workflowStore.hasUnsavedChanges) {
      bound.value = false;
      error.value = "The portfolio was recorded, but the canvas changed while reloading. Your edits remain here; save them and choose the portfolio again.";
    }
  } catch (failure) {
    if (ticket === generation) {
      const message = getErrorMessage(failure, "This portfolio could not be bound. Review it in My Dataset.");
      await load();
      error.value = message;
    }
  } finally {
    creatingSheetForSelection = false;
    if (ticket === generation) busy.value = false;
  }
}
</script>

<style scoped>
.workflow-portfolio-picker { display: grid; gap: .35rem; margin: .5rem 0 .75rem; }
.workflow-portfolio-picker label { font-size: .8rem; font-weight: 600; }
.picker-controls { display: flex; gap: .4rem; }
.picker-controls select { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 4px; color: var(--text-color); flex: 1; min-width: 0; padding: .4rem; }
.picker-controls button { border: 1px solid var(--primary-color); border-radius: 4px; background: var(--primary-color); color: white; cursor: pointer; }
.workflow-portfolio-picker small { color: var(--text-color-secondary); }
.workflow-portfolio-picker .picker-error { color: #b91c1c; }
</style>
