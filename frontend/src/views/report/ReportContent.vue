<template>
  <section class="page-content">
    <!-- Header -->
    <div class="section-header">
      <div>
        <h1>Report</h1>
        <p class="section-subtitle">
          Assemble, preview, and export analysis reports
        </p>
      </div>
      <div v-if="reportStore.isReady || reportStore.selectedWorkflowId" class="header-actions">
        <Button
          v-if="reportStore.selectedWorkflowId"
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
      </div>
    </div>

    <!-- Configuration bar -->
    <div class="report-config">
      <div class="config-field">
        <label for="report-workflow">Workflow</label>
        <Dropdown
          id="report-workflow"
          v-model="reportStore.selectedWorkflowId"
          :options="reportStore.workflows"
          optionLabel="name"
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
          id="report-runs"
          v-model="selectedRunProxy"
          :options="runDropdownOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="Select runs..."
          class="w-full"
          :disabled="!reportStore.selectedWorkflowId || reportStore.runsLoading"
          :loading="reportStore.runsLoading"
        />
        <div v-if="reportStore.selectedRunIds.length > 0" class="selected-runs-chips">
          <Tag
            v-for="runId in reportStore.selectedRunIds"
            :key="runId"
            :value="getRunName(runId)"
            severity="info"
            class="run-chip"
            icon="pi pi-times"
            @click="removeRun(runId)"
          />
        </div>
      </div>

      <div class="config-actions">
        <Button
          label="Generate Report"
          icon="pi pi-refresh"
          :loading="reportStore.loading"
          :disabled="!reportStore.selectedWorkflowId"
          @click="reportStore.fetchReportData()"
        />
      </div>
    </div>

    <!-- Section toggles -->
    <div v-if="reportStore.isReady" class="section-toggles">
      <ToggleButton
        v-model="reportStore.sections.pipelineDetails"
        onLabel="Pipeline"
        offLabel="Pipeline"
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

    <!-- Error state -->
    <div v-if="reportStore.error" class="error-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ reportStore.error }}</span>
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
        :srcdoc="previewHtml"
        sandbox="allow-same-origin"
        class="preview-iframe"
      />
    </div>

    <!-- Empty state -->
    <div v-else class="empty-state">
      <i class="pi pi-file-pdf empty-icon"></i>
      <h3>Select a workflow to generate a report</h3>
      <p>
        Choose a workflow above, optionally select execution runs to include,
        then click Generate Report. You can toggle sections and export in
        multiple formats.
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- report view bridges backend report payloads into export-generator types. */
import { ref, computed, onMounted, watch } from "vue";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import Tag from "primevue/tag";
import ToggleButton from "primevue/togglebutton";
import ProgressSpinner from "primevue/progressspinner";
import Menu from "primevue/menu";
import { useToast } from "primevue/usetoast";
import { useRouter } from "vue-router";

import MemoryAttribution from "@/components/MemoryAttribution.vue";
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
import { downloadBlob, downloadText, downloadJson } from "@/utils/download";
import api from "@/api/client";

const reportStore = useReportStore();
const projectStore = useProjectStore();
const advisorStore = useAdvisorStore();
const toast = useToast();
const router = useRouter();
const { isFeatureEnabled } = useAppConfig();

// R4 — Single-scope Sherpa Advisor routing for the Report tab.
// Today's Report UI has no subtabs; the active scope is always
// ``report.draft``.  When the report editor grows ``Figures`` and
// ``Export`` subtabs we can switch this to a TabView watcher.
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
    if (next != null) void syncAdvisorForReport();
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

function openWorkflowAudit(): void {
  if (!reportStore.selectedWorkflowId) return;
  void router.push({
    path: "/audit",
    query: {
      scope_type: "Workflow",
      scope_id: String(reportStore.selectedWorkflowId),
      target_type: "Workflow",
      target_id: String(reportStore.selectedWorkflowId),
    },
  });
}

// Build ReportData from backend response for the HTML generator
function buildReportData(): ReportData | null {
  const rd = reportStore.reportData;
  if (!rd) return null;

  const nodes: ReportNode[] = rd.nodes.map((n) => ({
    nodeId: n.node_id,
    nodeType: n.node_type,
    label: n.label,
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
    workflowName: rd.name,
    workflowDescription: rd.description,
    integrityHash: rd.integrity_hash,
    generatedAt: new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC",
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
  };
}

const previewHtml = computed(() => {
  const data = buildReportData();
  if (!data) return "";
  return generateProvenanceReport(data);
});

// Workflow change handler
async function onWorkflowChange(): Promise<void> {
  reportStore.reportData = null;
  reportStore.selectedRunIds = [];
  reportStore.narrativeText = null;
  reportStore.narrativeMemoryScopes = [];
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
        detail: "Could not generate AI narrative. Check LLM configuration.",
        life: 5000,
      });
      reportStore.sections.aiNarrative = false;
    }
  }
}

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
    label: "HTML Report",
    icon: "pi pi-code",
    command: () => {
      const html = previewHtml.value;
      if (!html) return;
      downloadBlob(new Blob([html], { type: "text/html" }), getExportFilename("html"));
      toast.add({ severity: "success", summary: "Exported", detail: "HTML report downloaded", life: 3000 });
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
      toast.add({ severity: "success", summary: "Exported", detail: "Markdown report downloaded", life: 3000 });
    },
  },
  {
    label: "JSON Data",
    icon: "pi pi-database",
    command: () => {
      if (!reportStore.reportData) return;
      downloadJson(reportStore.reportData, getExportFilename("json"));
      toast.add({ severity: "success", summary: "Exported", detail: "JSON data downloaded", life: 3000 });
    },
  },
  {
    separator: true,
  },
  {
    label: "Python Script",
    icon: "pi pi-external-link",
    disabled: !reportStore.selectedWorkflowId,
    command: () => {
      if (!reportStore.selectedWorkflowId) return;
      window.open(
        `/api/v1/workflows/${reportStore.selectedWorkflowId}/export/python`,
        "_blank"
      );
    },
  },
  {
    label: "Jupyter Notebook",
    icon: "pi pi-book",
    disabled: !reportStore.selectedWorkflowId,
    command: async () => {
      if (!reportStore.selectedWorkflowId) return;
      try {
        const resp = await api.get(
          `/workflows/${reportStore.selectedWorkflowId}/export/notebook`
        );
        const safeName = (resp.data.workflow_name || "workflow")
          .replace(/\s+/g, "_")
          .toLowerCase();
        downloadText(
          JSON.stringify(resp.data.notebook, null, 1),
          `${safeName}_workflow.ipynb`,
          "application/x-ipynb+json"
        );
        toast.add({ severity: "success", summary: "Exported", detail: "Notebook downloaded", life: 3000 });
      } catch {
        toast.add({ severity: "error", summary: "Failed", detail: "Notebook export failed", life: 3000 });
      }
    },
  },
]);

onMounted(() => {
  reportStore.fetchWorkflows();
});
</script>

<style scoped>
.page-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.section-subtitle {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 0.9rem;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.report-config {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 220px;
  flex: 1;
  max-width: 320px;
}

.config-field label {
  font-size: 0.85rem;
  font-weight: 500;
  color: #475569;
}

.config-actions {
  display: flex;
  align-items: flex-end;
}

.selected-runs-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.run-chip {
  font-size: 0.7rem;
  cursor: pointer;
}

.section-toggles {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.toggle-chip {
  font-size: 0.8rem;
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
  color: #64748b;
}

.report-preview-container {
  border: 1px solid #e2e8f0;
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
  background: #0f172a;
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
  color: #334155;
  font-size: 1.1rem;
}

.empty-state p {
  margin: 0;
  max-width: 480px;
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.6;
}

.w-full {
  width: 100%;
}
</style>
