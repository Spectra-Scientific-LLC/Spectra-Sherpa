<template>
  <section class="page-content report-content">
    <!-- Header -->
    <WorkspaceHeader title="Report" :actions="reportHeaderActionItems">
      <Button
        v-if="linkedRunId"
        label="Run"
        icon="pi pi-arrow-left"
        class="p-button-sm p-button-text"
        @click="openLinkedRun"
      />
      <Button
        v-if="auditWorkflowId"
        label="Audit"
        icon="pi pi-shield"
        class="p-button-sm p-button-outlined"
        @click="openWorkflowAudit"
      />
      <Button
        v-if="reportStore.isReady"
        ref="exportBtnRef"
        label="Export"
        icon="pi pi-download"
        class="p-button-sm"
        @click="toggleExportMenu"
      />
      <Menu ref="exportMenuRef" :model="exportMenuItems" :popup="true" />
    </WorkspaceHeader>
    <WorkspaceContext label="Report context">
      <WorkspaceContextItem :label="sectionTitle" :value="contextTitle">
        {{
          reportStore.reportData
            ? `${reportStore.reportData.runs?.length || 0} retained runs`
            : "Choose report inputs"
        }}
      </WorkspaceContextItem>
    </WorkspaceContext>
    <div v-if="reportStore.error" class="error-banner" role="alert">{{ reportStore.error }}</div>
    <WorkspaceTabs v-model="activeTab" :tab-ids="tabIds">
      <TabPanel header="Setup">
        <p v-if="reportStore.workflowsError" role="alert">
          {{ reportStore.workflowsError }}
          <Button label="Retry" @click="reportStore.fetchWorkflows()" />
        </p>
        <p v-if="reportStore.runsError" role="alert">
          {{ reportStore.runsError }}
          <Button
            label="Retry"
            @click="
              reportStore.selectedWorkflowId &&
              reportStore.fetchRunsForWorkflow(reportStore.selectedWorkflowId)
            "
          />
        </p>
        <!-- Configuration bar -->
        <div class="report-config">
          <div class="config-field">
            <label for="report-workflow">Workflow</label>
            <Dropdown
              inputId="report-workflow"
              v-model="reportStore.selectedWorkflowId"
              :options="reportStore.workflows"
              optionLabel="display_label"
              optionValue="id"
              placeholder="Select a workflow..."
              class="w-full"
              :loading="reportStore.workflowsLoading"
              @change="onWorkflowChange"
            />
          </div>

          <div class="config-field">
            <label for="report-runs">Execution Runs (optional)</label>
            <Dropdown
              inputId="report-runs"
              v-model="selectedRunProxy"
              :options="runDropdownOptions"
              optionLabel="label"
              optionValue="value"
              placeholder="Select runs..."
              class="w-full"
              :disabled="!reportStore.selectedWorkflowId || reportStore.runsLoading"
              :loading="reportStore.runsLoading"
            />
          </div>

          <div class="config-field">
            <label for="report-mode">Report length</label>
            <Dropdown
              inputId="report-mode"
              v-model="reportStore.reportMode"
              :options="reportModeOptions"
              optionLabel="label"
              optionValue="value"
              class="w-full"
            />
          </div>
          <div class="config-actions">
            <Button
              label="Generate Report"
              icon="pi pi-file"
              :loading="reportStore.loading"
              :disabled="!reportStore.selectedWorkflowId"
              @click="generateReport"
            />
          </div>
          <div
            v-if="reportStore.selectedRunIds.length"
            class="selected-runs-chips"
            aria-label="Selected execution runs"
          >
            <span>Selected runs</span>
            <button
              v-for="runId in reportStore.selectedRunIds"
              :key="runId"
              type="button"
              class="run-chip"
              :aria-label="`Remove ${getRunName(runId)}`"
              @click="removeRun(runId)"
            >
              {{ getRunName(runId) }} <i class="pi pi-times" aria-hidden="true"></i>
            </button>
          </div>
          <div class="report-options">
            <p class="report-mode-help">
              {{
                reportStore.reportMode === "summary"
                  ? "Key results and context from selected runs, without AI."
                  : "All retained results, settings, diagnostics, and execution evidence."
              }}
            </p>
            <label class="row-level-option">
              <input type="checkbox" v-model="reportStore.includeRowLevelPlots" />
              <span>Include complete target lists and node plots</span>
            </label>
          </div>
        </div>
      </TabPanel>
      <TabPanel header="Preview">
        <p v-if="reportStore.isStale" class="message warning" role="status">
          Setup has changed; this preview and its exports retain the previously generated report.
        </p>
        <details v-if="reportStore.reportData">
          <summary>Details</summary>
          <p>
            Workflow {{ reportStore.reportData.workflow_id }} · Runs
            {{ reportStore.reportData.runs?.map((run) => run.id).join(", ") || "None" }}
          </p>
          <p v-if="reportStore.generatedSelection">
            Generated {{ reportStore.generatedSelection.generatedAt }}
          </p>
        </details>
        <details v-if="historicalExecutableExport" class="execution-export-scope">
          <summary>Export scope</summary>
          <p>
            Python and notebook export of saved executions is unavailable. Export this report as
            HTML, Markdown or JSON to retain its saved evidence. Use the workflow editor to export
            the current authored graph; it is not a replay of this saved run.
          </p>
        </details>
        <!-- Section toggles -->
        <div v-if="reportStore.isReady" class="section-toggles">
          <template v-if="(reportStore.generatedSelection?.reportMode || reportStore.reportMode) === 'detailed'">
            <ToggleButton
              v-model="reportStore.sections.pipelineDetails"
              onLabel="Workflow"
              offLabel="Workflow"
              onIcon="pi pi-check"
              offIcon="pi pi-times"
              class="toggle-chip"
            />
            <ToggleButton
              v-model="reportStore.sections.connections"
              onLabel="Connections"
              offLabel="Connections"
              onIcon="pi pi-check"
              offIcon="pi pi-times"
              class="toggle-chip"
            />
            <ToggleButton
              v-model="reportStore.sections.executionResults"
              onLabel="Results"
              offLabel="Results"
              onIcon="pi pi-check"
              offIcon="pi pi-times"
              class="toggle-chip"
              :disabled="!reportStore.hasRuns"
            />
            <ToggleButton
              v-model="reportStore.sections.diagnostics"
              onLabel="Diagnostics"
              offLabel="Diagnostics"
              onIcon="pi pi-check"
              offIcon="pi pi-times"
              class="toggle-chip"
              :disabled="!reportStore.hasRuns"
            />
            <ToggleButton
              v-model="reportStore.sections.runComparison"
              onLabel="Comparison"
              offLabel="Comparison"
              onIcon="pi pi-check"
              offIcon="pi pi-times"
              class="toggle-chip"
              :disabled="!reportStore.hasComparison"
            />
          </template>
          <ToggleButton
            v-model="reportStore.sections.aiNarrative"
            onLabel="AI Summary"
            offLabel="AI Summary"
            onIcon="pi pi-check"
            offIcon="pi pi-times"
            class="toggle-chip"
            :disabled="!llmAvailable"
            @change="onNarrativeToggle"
          />
          <ProgressSpinner
            v-if="reportStore.narrativeLoading"
            style="width: 20px; height: 20px"
            strokeWidth="4"
          />
        </div>

        <MemoryAttribution
          v-if="reportStore.narrativeText"
          :scopes="reportStore.narrativeMemoryScopes"
        />

        <!-- Loading state -->
        <div v-if="reportStore.loading" class="loading-state">
          <ProgressSpinner style="width: 40px; height: 40px" />
          <span>Generating report...</span>
        </div>

        <!-- Live preview -->
        <div v-else-if="reportStore.isReady" class="report-preview-container">
          <iframe
            ref="previewFrame"
            title="Report preview"
            :srcdoc="previewHtml"
            sandbox="allow-same-origin"
            class="preview-iframe"
          />
        </div>

        <!-- Empty state -->
        <div v-else class="empty-state">
          <i class="pi pi-file-pdf empty-icon"></i>
          <h3>Select a workflow to generate a report</h3>
          <p>Select inputs in Setup, then generate the report.</p>
        </div>
      </TabPanel>
      <TabPanel header="ISO Validation">
        <p>
          Review retained validation evidence against your declared method; this is not
          certification.
        </p>
        <ValidationWalkthroughPanel
          :workflow-id="reportStore.selectedWorkflowId"
          :audit-config="auditConfig"
          @open-audit="openWorkflowAudit"
        />
      </TabPanel>
    </WorkspaceTabs>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- report view bridges backend report payloads into export-generator types. */
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import ToggleButton from "primevue/togglebutton";
import ProgressSpinner from "primevue/progressspinner";
import Menu from "primevue/menu";
import { useToast } from "primevue/usetoast";
import { useRoute, useRouter } from "vue-router";

import MemoryAttribution from "@/components/MemoryAttribution.vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import TabPanel from "primevue/tabpanel";
import { focusSection } from "@/lib/sherpaAttention";
import ValidationWalkthroughPanel from "@/views/report/ValidationWalkthroughPanel.vue";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import { useReportStore } from "@/stores/report";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  generateProvenanceReport,
  type ReportData,
  type ReportNode,
  type ReportEdge,
} from "@/utils/reportGenerator";
import { generateMarkdownReport } from "@/utils/reportMarkdownGenerator";
import { openReportPdfExport } from "@/utils/reportPdf";
import { downloadBlob, downloadText, downloadJson } from "@/utils/download";
import api from "@/api/client";

const reportStore = useReportStore();
const reportModeOptions = [
  { label: "Short summary", value: "summary" },
  { label: "Detailed report", value: "detailed" },
];
const projectStore = useProjectStore();
const advisorStore = useAdvisorStore();
const toast = useToast();
const router = useRouter();
const route = useRoute();
const { isFeatureEnabled, appConfig } = useAppConfig();
const auditConfig = computed(() => appConfig.value?.audit);

const tabIds = ["setup", "preview", "validation"] as const;
const activeTab = ref<string>("setup");
const sectionTitle = computed(
  () =>
    ({ setup: "Setup", preview: "Preview", validation: "ISO Validation" })[activeTab.value] ||
    "Setup",
);
const contextTitle = computed(() =>
  activeTab.value === "preview" && reportStore.reportData
    ? reportStore.reportData.name
    : reportStore.workflows.find((item) => item.id === reportStore.selectedWorkflowId)?.name ||
      "No workflow selected",
);
watch(activeTab, (section) => focusSection(section), { immediate: true });
async function generateReport(): Promise<void> {
  await reportStore.fetchReportData();
  if (!disposed && reportStore.isReady) activeTab.value = "preview";
}
// All presentation sections retain the existing report memory; section is attention.
async function syncAdvisorForReport(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "report",
      subscopeKey: "draft",
      title: "Draft",
    });
  } catch (err) {
    console.warn("[report] switchScope failed", err);
  }
}

watch(
  () => projectStore.currentProjectId,
  (next) => {
    if (next != null) {
      void syncAdvisorForReport();
      if (reportMounted) void reportStore.fetchWorkflows();
    }
  },
);

// AI is opt-in and independent of the deterministic scientific summary.
watch(
  () => reportStore.isReady,
  (ready) => {
    if (
      ready &&
      reportStore.sections.aiNarrative &&
      !reportStore.narrativeText &&
      llmAvailable.value
    ) {
      void onNarrativeToggle();
    }
  },
);
onMounted(() => {
  void syncAdvisorForReport();
});

const exportMenuRef = ref();
const previewFrame = ref<HTMLIFrameElement>();

const llmAvailable = computed(() => isFeatureEnabled("sherpaWriteReport"));

// Run dropdown — acts as a "picker" that adds to selectedRunIds
const selectedRunProxy = ref<number | null>(null);

const runDropdownOptions = computed(() => {
  return reportStore.availableRuns
    .filter((r) => !reportStore.selectedRunIds.includes(r.id))
    .map((r) => ({
      label: `${r.name} (${r.status})`,
      value: r.id,
    }));
});

watch(selectedRunProxy, (newVal) => {
  if (newVal !== null) {
    reportStore.selectedRunIds = [...reportStore.selectedRunIds, newVal];
    selectedRunProxy.value = null;
  }
});

function getRunName(runId: number): string {
  return reportStore.availableRuns.find((r) => r.id === runId)?.name || `Run #${runId}`;
}

function removeRun(runId: number): void {
  reportStore.selectedRunIds = reportStore.selectedRunIds.filter((id) => id !== runId);
}

const auditWorkflowId = computed(() =>
  activeTab.value === "preview" && reportStore.reportData
    ? reportStore.reportData.workflow_id
    : reportStore.selectedWorkflowId,
);
function openWorkflowAudit(): void {
  if (!auditWorkflowId.value) return;
  void router.push({
    path: "/audit",
    query: {
      scope_type: "Workflow",
      scope_id: String(auditWorkflowId.value),
      target_type: "Workflow",
      target_id: String(auditWorkflowId.value),
    },
  });
}

const linkedRunId = computed(() => {
  const runId = Number(route.query.run);
  return Number.isSafeInteger(runId) && runId > 0 ? runId : null;
});

function openLinkedRun(): void {
  if (!linkedRunId.value || projectStore.currentProjectId == null) return;
  void router.push({
    path: `/runs/${linkedRunId.value}`,
    query: { project: String(projectStore.currentProjectId) },
  });
}

// Build ReportData from backend response for the HTML generator
function buildReportData(): ReportData | null {
  const rd = reportStore.reportData;
  if (!rd) return null;

  const nodes: ReportNode[] = rd.nodes.map((n) => ({
    nodeId: n.node_id,
    nodeType: n.node_type,
    label: n.label || n.node_type,
    parameters: n.parameters as Record<string, any>,
    positionX: n.position_x,
    positionY: n.position_y,
  }));

  const edges: ReportEdge[] = rd.edges.map((e) => ({
    fromNodeId: e.from_node_id,
    toNodeId: e.to_node_id,
    fromOutput: e.from_output,
    toInput: e.to_input,
  }));

  return {
    reportMode: reportStore.generatedSelection?.reportMode || reportStore.reportMode,
    workflowName: rd.name,
    workflowDescription: rd.description,
    integrityHash: rd.integrity_hash,
    generatedAt: reportStore.generatedSelection?.generatedAt || "Generation time unavailable",
    nodes,
    edges,
    plotImages: new Map(),
    terminalMetrics: {},
    technique: rd.technique,
    sampleType: rd.sample_type,
    runs: rd.runs,
    comparison: rd.comparison,
    narrativeMarkdown: reportStore.narrativeText,
    sections: { ...reportStore.sections },
    workflowIdentity: rd.workflow_identity,
    projectEvidence: reportStore.projectEvidenceSnapshot,
  };
}

const previewHtml = computed(() => {
  const data = buildReportData();
  if (!data) return "";
  return generateProvenanceReport(data);
});

// Workflow change handler
async function onWorkflowChange(): Promise<void> {
  reportStore.selectedRunIds = [];
  selectedRunProxy.value = null;

  if (reportStore.selectedWorkflowId) {
    await reportStore.fetchRunsForWorkflow(reportStore.selectedWorkflowId);
  }
}

// AI narrative toggle
async function onNarrativeToggle(): Promise<void> {
  if (reportStore.sections.aiNarrative && !reportStore.narrativeText) {
    await reportStore.generateNarrative();
    if (!reportStore.narrativeText) {
      toast.add({
        severity: "warn",
        summary: "Narrative Unavailable",
        detail:
          reportStore.narrativeError || "Could not generate AI narrative. Check LLM configuration.",
        life: 5000,
      });
      reportStore.sections.aiNarrative = false;
    }
  }
}

// Executable export endpoints consume current authored graphs, not retained run definitions.
// Guard both menus and action handlers so selection changes cannot substitute a graph.
const historicalExecutableExport = computed(
  () =>
    !!linkedRunId.value ||
    reportStore.selectedRunIds.length > 0 ||
    (reportStore.reportData?.runs?.length ?? 0) > 0,
);

// Export menu
function toggleExportMenu(event: Event): void {
  exportMenuRef.value?.toggle(event);
}

function getExportFilename(ext: string): string {
  const name = reportStore.reportData?.name || "report";
  const safe = name.replace(/\s+/g, "_").toLowerCase();
  return `${safe}_report.${ext}`;
}

const exportMenuItems = computed(() => [
  {
    label: "PDF",
    icon: "pi pi-file-pdf",
    command: () => {
      const html = previewHtml.value;
      if (!html) return;
      const opened = openReportPdfExport(html, getExportFilename("pdf"));
      if (opened) {
        toast.add({
          severity: "success",
          summary: "PDF Ready",
          detail: "Use the print dialog to save the report as PDF.",
          life: 5000,
        });
      } else {
        toast.add({
          severity: "warn",
          summary: "Popup Blocked",
          detail: "Allow popups for SpectraSherpa, then export PDF again.",
          life: 5000,
        });
      }
    },
  },
  {
    label: "HTML Report",
    icon: "pi pi-code",
    command: () => {
      const html = previewHtml.value;
      if (!html) return;
      downloadBlob(new Blob([html], { type: "text/html" }), getExportFilename("html"));
      toast.add({
        severity: "success",
        summary: "Exported",
        detail: "HTML report downloaded",
        life: 3000,
      });
    },
  },
  {
    label: "Markdown",
    icon: "pi pi-file",
    command: () => {
      const data = buildReportData();
      if (!data) return;
      const md = generateMarkdownReport(data);
      downloadText(md, getExportFilename("md"), "text/markdown");
      toast.add({
        severity: "success",
        summary: "Exported",
        detail: "Markdown report downloaded",
        life: 3000,
      });
    },
  },
  {
    label: "JSON Data (full evidence)",
    icon: "pi pi-database",
    command: () => {
      if (!reportStore.reportData) return;
      downloadJson(
        { ...reportStore.reportData, report_presentation: reportStore.generatedSelection,
          project_evidence_at_generation: reportStore.projectEvidenceSnapshot },
        getExportFilename("json"),
      );
      toast.add({
        severity: "success",
        summary: "Exported",
        detail: "JSON data downloaded",
        life: 3000,
      });
    },
  },
  {
    separator: true,
  },
  {
    label: "Python Script (current workflow)",
    icon: "pi pi-code",
    disabled: !reportStore.selectedWorkflowId || historicalExecutableExport.value,
    command: async () => {
      if (!reportStore.selectedWorkflowId || historicalExecutableExport.value) return;
      const workflowId = reportStore.selectedWorkflowId;
      try {
        const resp = await api.get(`/workflows/${workflowId}/export/python`);
        // A user may switch to a historical report while the request is in flight.
        if (historicalExecutableExport.value || reportStore.selectedWorkflowId !== workflowId)
          return;
        downloadText(
          resp.data.python_code,
          `${String(resp.data.workflow_name || "workflow").replace(/\s+/g, "_")}.py`,
          "text/x-python",
        );
      } catch {
        toast.add({
          severity: "error",
          summary: "Failed",
          detail: "Python export failed",
          life: 3000,
        });
      }
    },
  },
  {
    label: "Jupyter Notebook (current workflow)",
    icon: "pi pi-book",
    disabled: !reportStore.selectedWorkflowId || historicalExecutableExport.value,
    command: async () => {
      if (!reportStore.selectedWorkflowId || historicalExecutableExport.value) return;
      const workflowId = reportStore.selectedWorkflowId;
      try {
        const resp = await api.get(`/workflows/${workflowId}/export/notebook`);
        if (historicalExecutableExport.value || reportStore.selectedWorkflowId !== workflowId)
          return;
        const safeName = (resp.data.workflow_name || "workflow").replace(/\s+/g, "_").toLowerCase();
        downloadText(
          JSON.stringify(resp.data.notebook, null, 1),
          `${safeName}_workflow.ipynb`,
          "application/x-ipynb+json",
        );
        toast.add({
          severity: "success",
          summary: "Exported",
          detail: "Notebook downloaded",
          life: 3000,
        });
      } catch {
        toast.add({
          severity: "error",
          summary: "Failed",
          detail: "Notebook export failed",
          life: 3000,
        });
      }
    },
  },
]);

const reportHeaderActionItems = computed(() => [
  ...(linkedRunId.value
    ? [
        {
          label: "Run",
          icon: "pi pi-arrow-left",
          command: openLinkedRun,
        },
      ]
    : []),
  ...(auditWorkflowId.value
    ? [
        {
          label: "Audit",
          icon: "pi pi-shield",
          command: openWorkflowAudit,
        },
      ]
    : []),
  ...(reportStore.isReady
    ? [
        {
          label: "Export",
          icon: "pi pi-download",
          items: exportMenuItems.value,
        },
      ]
    : []),
]);

let disposed = false;
let reportMounted = false;
onBeforeUnmount(() => {
  disposed = true;
});
onMounted(async () => {
  const initialPath = route.fullPath;
  const isCurrent = () => !disposed && route.fullPath === initialPath;
  const workflowId = Number(route.query.workflow);
  const runId = Number(route.query.run);
  const linkedProjectId = Number(route.query.project);
  if (
    Number.isSafeInteger(linkedProjectId) &&
    linkedProjectId > 0 &&
    linkedProjectId !== projectStore.currentProjectId
  ) {
    await projectStore.selectProject(linkedProjectId);
  } else {
    await projectStore.ensureProjectForBrowserTab();
  }
  if (!isCurrent()) return;
  reportMounted = true;
  await reportStore.fetchWorkflows();
  if (!isCurrent()) return;
  const section = String(route.query.tab || "setup");
  if (tabIds.includes(section as (typeof tabIds)[number])) activeTab.value = section;
  if (
    !Number.isSafeInteger(workflowId) ||
    workflowId < 1 ||
    !Number.isSafeInteger(runId) ||
    runId < 1
  )
    return;
  if (linkedProjectId !== projectStore.currentProjectId) {
    toast.add({
      severity: "error",
      summary: "Report unavailable",
      detail: "Select the project that owns this run.",
    });
    return;
  }
  reportStore.selectedWorkflowId = workflowId;
  reportStore.selectedRunIds = [runId];
  await reportStore.fetchReportData();
  if (!isCurrent() || reportStore.selectedWorkflowId !== workflowId) return;
  if (reportStore.isReady) activeTab.value = "preview";
  await reportStore.fetchRunsForWorkflow(workflowId);
});
</script>

<style scoped>
.page-content {
  display: flex;
  flex-direction: column;
  padding: 0 1rem;
  color: var(--text-color);
}

:global(.content:has(.report-content)) {
  background: #e4e0fa;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.report-config {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 16px;
  align-items: end;
  padding: 20px;
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  background: var(--surface-card);
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.config-field label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-color-secondary);
}

.config-actions {
  display: flex;
  align-items: flex-end;
}

.selected-runs-chips {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.run-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  overflow-wrap: anywhere;
  text-align: left;
  padding: 6px 10px;
  border: 1px solid var(--surface-border);
  border-radius: 16px;
  background: var(--surface-hover);
  color: var(--primary-color);
  font: inherit;
  cursor: pointer;
}

.report-options {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  text-align: left;
}
.report-mode-help {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  line-height: 1.5;
}
.row-level-option {
  display: flex;
  justify-content: flex-start;
  gap: 10px;
  align-items: flex-start;
  text-align: left;
  font-size: 0.85rem;
  color: var(--text-color);
  cursor: pointer;
}
.row-level-option input[type="checkbox"] {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  padding: 0;
  margin: 2px 0 0;
}
.row-level-option span {
  min-width: 0;
}
.row-level-option small {
  color: var(--text-color-secondary);
}
.config-field :deep(.p-dropdown) {
  min-height: 42px;
}
.config-field :deep(.p-dropdown-label) {
  overflow: hidden;
  text-overflow: ellipsis;
}
.config-actions :deep(.p-button) {
  min-height: 42px;
  white-space: nowrap;
}
.run-chip:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}
@media (max-width: 1100px) {
  .report-config {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .report-config {
    grid-template-columns: minmax(0, 1fr);
    padding: 12px;
  }
  .config-actions :deep(.p-button) {
    width: 100%;
  }
}

.section-toggles {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.toggle-chip {
  font-size: 0.72rem;
}

.toggle-chip :deep(.p-button) {
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
  min-width: 0;
  line-height: 1.1;
}

.toggle-chip :deep(.p-button .p-button-icon) {
  font-size: 0.65rem;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 0.85rem;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px;
  color: var(--text-color-secondary);
}

.report-preview-container {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
  flex: 1;
  min-height: 500px;
}

.preview-iframe {
  width: 100%;
  height: 100%;
  min-height: 500px;
  border: none;
  background: var(--surface-card);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 64px 24px;
  text-align: center;
}

.empty-icon {
  font-size: 3rem;
  color: #94a3b8;
}

.empty-state h3 {
  margin: 0;
  color: var(--text-color);
  font-size: 1.1rem;
}

.empty-state p {
  margin: 0;
  max-width: 480px;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
  line-height: 1.6;
}

.w-full {
  width: 100%;
}
</style>
