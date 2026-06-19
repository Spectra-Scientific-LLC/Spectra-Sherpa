import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { useAdvisorStore } from "@/stores/advisor";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import type {
  TemplateDataBinding,
  TemplateExampleBinding,
  TemplateLaunchMode,
  WorkflowListItem,
} from "@/stores/workflow-types";
import type { NodeOutput } from "@/utils/nodeOutput";

export interface WorkbookSheet {
  workflowId: number;
  name: string;
  tabColor: string | null;
  tabColorOverride?: string | null;
  colorSource?: "blank" | "ai" | "data" | "manual";
  primaryDataSourceId?: number | null;
  dataSourceIds?: number[];
  advisorChannelId?: number | null;
  createdFromTemplateName?: string | null;
  createdFromTemplateVersion?: string | null;
  createdFromWorkflowId?: number | null;
  sheetOrder: number;
  nodeCount?: number;
  kind?: "workflow" | "trial";
  trialId?: string;
  sourceWorkflowId?: number;
  sourceNodeId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- trial tabs carry the existing node-detail payload shape.
  trialData?: any;
  executionStatus?: "idle" | "running" | "success" | "error";
  lastSelectedNodeId?: string;
  nodeOutputsCache?: Map<string, NodeOutput>;
}

const activeSheetKey = (projectId: number): string => {
  // "local" matches the sentinel used by project.ts / data.ts /
  // synthesis.ts for "no signed-in user" so a local-mode user's saved
  // active sheet, active data tab, and synthesis state all key under the
  // same userId space.
  const userId = useAuthStore().user?.id ?? "local";
  return `spectra_sherpa_active_sheet_${userId}_${projectId}`;
};

const QUOTA_RECOVERY_PREFIXES = [
  "spectra_sherpa_workflow_draft_v1:",
];

const pruneTransientStorageForQuota = (): void => {
  try {
    const keysToRemove: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && QUOTA_RECOVERY_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach((key) => localStorage.removeItem(key));
  } catch {
    // If storage is blocked entirely, navigation should still continue.
  }
};

const readActiveSheetWorkflowId = (targetProjectId: number): number | null => {
  try {
    const raw = localStorage.getItem(activeSheetKey(targetProjectId));
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

const toSheet = (item: WorkflowListItem): WorkbookSheet => ({
  workflowId: item.id,
  name: item.name,
  tabColor: item.tab_color ?? null,
  tabColorOverride: item.tab_color_override ?? null,
  colorSource: item.color_source ?? (item.tab_color ? "manual" : "blank"),
  primaryDataSourceId: item.primary_data_source_id ?? null,
  dataSourceIds: item.data_source_ids ?? [],
  advisorChannelId: item.advisor_channel_id ?? null,
  createdFromTemplateName: item.created_from_template_name ?? null,
  createdFromTemplateVersion: item.created_from_template_version ?? null,
  createdFromWorkflowId: item.created_from_workflow_id ?? null,
  sheetOrder: item.sheet_order ?? 0,
  nodeCount: item.node_count ?? 0,
});

export const useWorkbookStore = defineStore("workbook", () => {
  const sheets = ref<WorkbookSheet[]>([]);
  const activeIndex = ref(0);
  const projectId = ref<number | null>(null);
  const isLoading = ref(false);
  const trialCounter = ref(0);

  const activeSheet = computed(() => sheets.value[activeIndex.value] ?? null);
  const activeTrialSheet = computed(() =>
    activeSheet.value?.kind === "trial" ? activeSheet.value : null
  );

  function persistActiveSheet(): void {
    if (projectId.value === null || !activeSheet.value || activeSheet.value.kind === "trial") return;
    const key = activeSheetKey(projectId.value);
    const value = String(activeSheet.value.workflowId);
    try {
      localStorage.setItem(key, value);
    } catch {
      // Remembering the last active sheet is best-effort. If quota is full,
      // clear stale workflow drafts (server autosave remains primary) and try
      // once more so refresh lands back on the selected sheet.
      pruneTransientStorageForQuota();
      try {
        localStorage.setItem(key, value);
      } catch {
        // Hardened-browser or still-full storage must never block navigation.
      }
    }
  }

  async function syncAdvisorForSheet(sheet: WorkbookSheet | null): Promise<void> {
    if (!sheet || projectId.value === null) return;

    const advisorStore = useAdvisorStore();
    const sourceSheet =
      sheet.kind === "trial" && sheet.sourceWorkflowId
        ? sheets.value.find((item) => item.kind !== "trial" && item.workflowId === sheet.sourceWorkflowId)
        : sheet;
    if (!sourceSheet || sourceSheet.kind === "trial") return;

    // Canonical scope-based routing.  switchScope returns the active
    // node + topics + active topic, and the sherpa store loads the
    // bound conversation.  No legacy channel fallback — R2 retired it.
    try {
      await advisorStore.switchScope({
        projectId: projectId.value,
        tabKey: "workflow",
        subscopeKey: `sheet:${sourceSheet.workflowId}`,
        resourceType: "workflow",
        resourceId: sourceSheet.workflowId,
        title: sourceSheet.name,
      });
    } catch (err) {
      console.warn("[workbook] switchScope failed", err);
    }
  }

  function nextSheetName(): string {
    const used = new Set(sheets.value.map((sheet) => sheet.name));
    let index = sheets.value.length + 1;
    while (used.has(`Sheet ${index}`)) {
      index += 1;
    }
    return `Sheet ${index}`;
  }

  async function fetchSheets(targetProjectId: number): Promise<WorkbookSheet[]> {
    const response = await api.get<WorkflowListItem[]>("/workflows", {
      params: { project_id: targetProjectId, in_workbook: true, limit: 200 },
    });
    return response.data.map(toSheet).sort((a, b) => a.sheetOrder - b.sheetOrder);
  }

  async function createSheetRecord(name = nextSheetName()): Promise<WorkbookSheet> {
    if (projectId.value === null) {
      throw new Error("Project is required before creating sheets");
    }
    const response = await api.post<WorkflowListItem>("/workflows", {
      name,
      description: "",
      status: "draft",
      project_id: projectId.value,
      tab_color: null,
      color_source: "blank",
      nodes: [],
      edges: [],
    });
    return toSheet(response.data);
  }

  async function loadSheets(targetProjectId: number): Promise<void> {
    const workflowStore = useWorkflowStore();
    isLoading.value = true;
    try {
      projectId.value = targetProjectId;
      let loadedSheets = await fetchSheets(targetProjectId);
      if (loadedSheets.length === 0) {
        loadedSheets = [await createSheetRecord("Sheet 1")];
      }

      sheets.value = loadedSheets;
      const savedWorkflowId = readActiveSheetWorkflowId(targetProjectId);
      const savedIndex = savedWorkflowId !== null
        ? sheets.value.findIndex((sheet) => sheet.workflowId === savedWorkflowId)
        : -1;
      activeIndex.value = savedIndex >= 0 ? savedIndex : 0;
      persistActiveSheet();

      const sheet = activeSheet.value;
      if (sheet) {
        await workflowStore.loadWorkflow(sheet.workflowId);
        await syncAdvisorForSheet(sheet);
      }
    } finally {
      isLoading.value = false;
    }
  }

  async function refreshSheets(): Promise<void> {
    if (projectId.value === null) return;
    const activeWorkflowId = activeSheet.value?.workflowId ?? null;
    const trialSheets = sheets.value.filter((sheet) => sheet.kind === "trial");
    sheets.value = [...(await fetchSheets(projectId.value)), ...trialSheets];
    const nextIndex = activeWorkflowId
      ? sheets.value.findIndex((sheet) => sheet.workflowId === activeWorkflowId)
      : -1;
    activeIndex.value = nextIndex >= 0 ? nextIndex : 0;
    persistActiveSheet();
  }

  async function switchSheet(index: number): Promise<void> {
    if (index < 0 || index >= sheets.value.length || index === activeIndex.value) {
      return;
    }

    const workflowStore = useWorkflowStore();
    if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
      await workflowStore.saveWorkflow({ createVersion: false });
    }

    const target = sheets.value[index];
    if (target.kind === "trial") {
      if (target.sourceWorkflowId && workflowStore.workflowId !== target.sourceWorkflowId) {
        await workflowStore.loadWorkflow(target.sourceWorkflowId);
      }
      activeIndex.value = index;
      await syncAdvisorForSheet(target);
      return;
    }

    activeIndex.value = index;
    persistActiveSheet();
    await workflowStore.loadWorkflow(target.workflowId);
    await syncAdvisorForSheet(target);
  }

  async function selectWorkflowSheet(workflowId: number, targetProjectId = projectId.value): Promise<void> {
    if (targetProjectId === null) {
      throw new Error("Project is required before selecting a workflow sheet");
    }

    const workflowStore = useWorkflowStore();
    if (projectId.value !== targetProjectId || sheets.value.length === 0) {
      if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
        await workflowStore.saveWorkflow({ createVersion: false });
      }
      await loadSheets(targetProjectId);
    }

    let index = sheets.value.findIndex((sheet) => sheet.workflowId === workflowId);
    if (index < 0) {
      await refreshSheets();
      index = sheets.value.findIndex((sheet) => sheet.workflowId === workflowId);
    }
    if (index < 0) {
      throw new Error("Selected workflow is not available as a sheet in this project");
    }

    await switchSheet(index);
  }

  async function addSheet(): Promise<WorkbookSheet> {
    const sheet = await createSheetRecord();
    sheets.value.push(sheet);
    await switchSheet(sheets.value.length - 1);
    return sheet;
  }

  async function duplicateSheet(workflowId: number): Promise<WorkbookSheet> {
    const response = await api.post<WorkflowListItem>(`/workflows/${workflowId}/duplicate`);
    const sheet = toSheet(response.data);
    sheets.value.push(sheet);
    await switchSheet(sheets.value.length - 1);
    return sheet;
  }

  // Non-destructive version-restore: opens the snapshot of a specific
  // workflow_version as a brand-new sheet in the same project.  The original
  // workflow + its version history are untouched, so users can compare-side
  // by-side or copy nodes between sheets.
  async function openVersionAsSheet(
    workflowId: number,
    versionId: number,
  ): Promise<WorkbookSheet> {
    const response = await api.post<WorkflowListItem>(
      `/workflows/${workflowId}/versions/${versionId}/open-as-new-sheet`,
    );
    const sheet = toSheet(response.data);
    sheets.value.push(sheet);
    await switchSheet(sheets.value.length - 1);
    return sheet;
  }

  // Instantiate a curated template as a new sheet in the current project.
  // Always uses launch_mode=example so the template's bundled / certified
  // dataset auto-materializes — the v0.4.x picker doesn't yet collect
  // user-supplied data bindings.  The backend rejects templates that have
  // no example data with a 400 we surface as a toast.
  async function openTemplateAsSheet(
    templateId: number,
    workflowName: string,
    options: {
      launchMode?: TemplateLaunchMode;
      dataBindings?: Record<string, TemplateDataBinding>;
      exampleBindings?: Record<string, TemplateExampleBinding>;
    } = {},
  ): Promise<WorkbookSheet> {
    if (projectId.value === null) {
      throw new Error("Open or create a project before starting analysis.");
    }
    const launchMode = options.launchMode ?? "example";
    const response = await api.post<WorkflowListItem>(
      `/workflow-templates/${templateId}/instantiate`,
      {
        workflow_name: workflowName,
        project_id: projectId.value,
        launch_mode: launchMode,
        data_bindings: Object.fromEntries(
          Object.entries(options.dataBindings || {}).map(([key, binding]) => [
            key,
            {
              source: binding.source ?? "experiment",
              experiment_id: binding.experimentId,
              file_id: binding.fileId ?? null,
              stage: binding.stage ?? "raw",
              target_binding: binding.targetBinding
                ? {
                    source: binding.targetBinding.source ?? "experiment",
                    experiment_id: binding.targetBinding.experimentId,
                    file_id: binding.targetBinding.fileId ?? null,
                    stage: binding.targetBinding.stage ?? "raw",
                  }
                : null,
              target_type: binding.targetType ?? null,
            },
          ])
        ),
        example_bindings: Object.fromEntries(
          Object.entries(options.exampleBindings || {}).map(([key, binding]) => [
            key,
            {
              source: binding.source,
              dataset_name: binding.datasetName,
            },
          ])
        ),
      },
    );
    const sheet = toSheet(response.data);
    sheets.value.push(sheet);
    await switchSheet(sheets.value.length - 1);
    return sheet;
  }

  async function renameSheet(workflowId: number, newName: string): Promise<void> {
    const trimmed = newName.trim().slice(0, 40);
    if (!trimmed) return;

    const response = await api.put<WorkflowListItem>(`/workflows/${workflowId}`, {
      name: trimmed,
      create_version: false,
    });
    const sheet = sheets.value.find((item) => item.workflowId === workflowId);
    if (sheet) {
      sheet.name = response.data.name;
    }

    const workflowStore = useWorkflowStore();
    if (workflowStore.workflowId === workflowId) {
      workflowStore.workflowName = response.data.name;
    }
  }

  async function setSheetColor(workflowId: number, color: string | null): Promise<void> {
    const response = await api.put<WorkflowListItem>(`/workflows/${workflowId}`, {
      tab_color: color,
      create_version: false,
    });
    const sheet = sheets.value.find((item) => item.workflowId === workflowId);
    if (sheet) {
      sheet.tabColor = response.data.tab_color ?? null;
      sheet.tabColorOverride = response.data.tab_color_override ?? color;
      sheet.colorSource = response.data.color_source ?? (color ? "manual" : "blank");
    }
  }

  async function reorderSheets(orderedIds: number[]): Promise<void> {
    if (projectId.value === null) return;
    const currentId = activeSheet.value?.workflowId;
    const response = await api.put<WorkflowListItem[]>(
      `/workflows/reorder-sheets?project_id=${projectId.value}`,
      { ordered_ids: orderedIds },
    );
    sheets.value = response.data.map(toSheet).sort((a, b) => a.sheetOrder - b.sheetOrder);
    const nextIndex = currentId
      ? sheets.value.findIndex((sheet) => sheet.workflowId === currentId)
      : -1;
    activeIndex.value = nextIndex >= 0 ? nextIndex : 0;
    persistActiveSheet();
  }

  async function deleteSheet(workflowId: number): Promise<void> {
    const target = sheets.value.find((sheet) => sheet.workflowId === workflowId);
    if (target?.kind === "trial") {
      if (target.trialId) {
        await closeTrialTab(target.trialId);
      }
      return;
    }

    if (sheets.value.filter((sheet) => sheet.kind !== "trial").length <= 1) {
      throw new Error("Cannot delete the last sheet");
    }

    const deleteIndex = sheets.value.findIndex((sheet) => sheet.workflowId === workflowId);
    if (deleteIndex < 0) return;

    const currentWorkflowId = activeSheet.value?.workflowId;
    const wasActive = currentWorkflowId === workflowId;
    // ``activeSheetWasTrialOfDeleted`` covers the edge case where the
    // currently-active sheet is a TRIAL whose ``sourceWorkflowId`` is the
    // workflow being deleted. The cascade loop below will splice that
    // active trial sheet out, and the wasActive flag (computed above)
    // will be false because the trial's own workflowId differs from the
    // deleted workflow id. Without this flag the post-cascade
    // currentWorkflowId lookup returns -1 and activeIndex points at a
    // surprise sheet.
    const activeSheetWasTrialOfDeleted =
      activeSheet.value?.kind === "trial" && activeSheet.value?.sourceWorkflowId === workflowId;
    // R4: conversation cleanup is handled by the server's cascade
    // chain (workflow → advisor_memory_node → advisor_topic), so the
    // frontend no longer needs to chase the channel/conversation
    // pointer.  When the AdvisorChannel table is finally retired, the
    // server's workflow-delete handler will also drop any orphan rows.
    await api.delete(`/workflows/${workflowId}`);
    useProjectStore().removeWorkflowFromCurrentProject(workflowId);
    sheets.value.splice(deleteIndex, 1);

    // Cascade-drop trial sheets that pointed at the deleted source workflow.
    // Without this they remain in the tab list as orphans whose
    // ``sourceWorkflowId`` no longer resolves — activating them then calls
    // ``loadWorkflow(deletedId)`` which 404s. Walk indices high-to-low so
    // the running splice doesn't shift positions we still need to read.
    let activeShift = 0;
    for (let i = sheets.value.length - 1; i >= 0; i -= 1) {
      const candidate = sheets.value[i];
      if (candidate.kind === "trial" && candidate.sourceWorkflowId === workflowId) {
        sheets.value.splice(i, 1);
        if (i < activeIndex.value) activeShift += 1;
      }
    }

    if (wasActive || activeSheetWasTrialOfDeleted) {
      // Either the active sheet WAS the deleted workflow, or it was a
      // trial whose source got cascade-deleted out from under it. In
      // both cases the active sheet no longer exists in the array, so
      // we need to land on a sensible neighbour rather than letting the
      // currentWorkflowId lookup below (which would return -1) leave
      // activeIndex pointing at a surprise sheet.
      const nextIndex = Math.min(deleteIndex, sheets.value.length - 1);
      activeIndex.value = nextIndex;
      persistActiveSheet();
      const nextSheet = sheets.value[nextIndex];
      await useWorkflowStore().loadWorkflow(nextSheet.workflowId);
      // Switch the Sherpa Advisor to the next sheet's channel — without this,
      // the advisor remains bound to the deleted sheet's channel (now cascaded
      // away in the DB), and the next prompt 404s or orphans data.
      await syncAdvisorForSheet(nextSheet);
    } else {
      if (deleteIndex < activeIndex.value) {
        activeIndex.value -= 1;
      }
      if (activeShift > 0) {
        activeIndex.value = Math.max(0, activeIndex.value - activeShift);
      }
      if (currentWorkflowId) {
        const nextIndex = sheets.value.findIndex((sheet) => sheet.workflowId === currentWorkflowId);
        activeIndex.value = nextIndex >= 0 ? nextIndex : activeIndex.value;
      }
      persistActiveSheet();
    }
    await refreshSheets();
  }

  async function openTrialTab(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- trial tabs reuse WorkflowInspector's node-detail payload.
    trialData: any,
    sourceWorkflowId: number,
    tabColor: string | null,
  ): Promise<WorkbookSheet> {
    const sourceNodeId = String(trialData?.id ?? "");
    const sourceSheet = sheets.value.find(
      (sheet) => sheet.kind !== "trial" && sheet.workflowId === sourceWorkflowId,
    );
    const existingIndex = sheets.value.findIndex(
      (sheet) =>
        sheet.kind === "trial" &&
        sheet.sourceWorkflowId === sourceWorkflowId &&
        sheet.sourceNodeId === sourceNodeId,
    );

    if (existingIndex >= 0) {
      const existing = sheets.value[existingIndex];
      existing.trialData = trialData;
      existing.tabColor = tabColor;
      await switchSheet(existingIndex);
      return existing;
    }

    trialCounter.value += 1;
    const trialId = `trial-${sourceWorkflowId}-${sourceNodeId}-${trialCounter.value}`;
    const sheet: WorkbookSheet = {
      kind: "trial",
      workflowId: -trialCounter.value,
      trialId,
      sourceWorkflowId,
      sourceNodeId,
      name: `Trial: ${trialData?.label || sourceNodeId || "Node"}`,
      tabColor,
      tabColorOverride: null,
      colorSource: "data",
      primaryDataSourceId: sourceSheet?.primaryDataSourceId,
      dataSourceIds: sourceSheet?.dataSourceIds ?? [],
      advisorChannelId: sourceSheet?.advisorChannelId ?? null,
      sheetOrder: sheets.value.length,
      trialData,
    };

    sheets.value.push(sheet);
    await switchSheet(sheets.value.length - 1);
    return sheet;
  }

  async function closeTrialTab(trialId: string): Promise<void> {
    // Match strictly on trialId AND kind === "trial". The previous fallback
    // to `String(sheet.workflowId) === trialId` could collide when the caller
    // passed a stringified negative workflowId (e.g. "-1"), closing the wrong
    // trial tab.
    const index = sheets.value.findIndex(
      (sheet) => sheet.kind === "trial" && sheet.trialId === trialId,
    );
    if (index < 0) return;

    const sheet = sheets.value[index];
    const wasActive = index === activeIndex.value;
    sheets.value.splice(index, 1);

    if (!wasActive) {
      if (index < activeIndex.value) activeIndex.value -= 1;
      return;
    }

    const sourceIndex = sheet.sourceWorkflowId
      ? sheets.value.findIndex((item) => item.kind !== "trial" && item.workflowId === sheet.sourceWorkflowId)
      : -1;
    const nextIndex = sourceIndex >= 0 ? sourceIndex : Math.min(index, sheets.value.length - 1);
    if (nextIndex >= 0) {
      activeIndex.value = nextIndex;
      persistActiveSheet();
      const nextSheet = sheets.value[nextIndex];
      if (nextSheet.kind !== "trial") {
        const workflowStore = useWorkflowStore();
        if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
          await workflowStore.saveWorkflow({ createVersion: false });
        }
        await workflowStore.loadWorkflow(nextSheet.workflowId);
      }
      await syncAdvisorForSheet(nextSheet);
    } else {
      activeIndex.value = 0;
    }
  }

  function setLastSelectedNodeId(workflowId: number, nodeId: string | null): void {
    const sheet = sheets.value.find((s) => s.workflowId === workflowId);
    if (sheet) {
      sheet.lastSelectedNodeId = nodeId || undefined;
    }
  }

  return {
    sheets,
    activeIndex,
    activeSheet,
    activeTrialSheet,
    projectId,
    isLoading,
    loadSheets,
    refreshSheets,
    selectWorkflowSheet,
    addSheet,
    switchSheet,
    duplicateSheet,
    openVersionAsSheet,
    openTemplateAsSheet,
    renameSheet,
    setSheetColor,
    reorderSheets,
    deleteSheet,
    openTrialTab,
    closeTrialTab,
    setLastSelectedNodeId,
  };
});
