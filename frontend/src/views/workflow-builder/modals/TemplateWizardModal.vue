<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import Dropdown from "primevue/dropdown";
import Message from "primevue/message";
import { useToast } from "primevue/usetoast";
import {
  type ReferenceDatasetOption,
  type TemplateLaunchMode,
  useWorkflowStore,
  type TemplateDataBinding,
  type TemplateDataRole,
  type WorkflowTemplate,
} from "@/stores/workflow";
import { useProjectStore } from "@/stores/project";
import { useExperimentStore } from "@/stores/experiment";
import type { ExperimentBrief, ExperimentFile, ExperimentStage } from "@/types";
import { getErrorMessage } from "@/utils/errors";
import api from "@/api/client";

const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";

interface TemplateRoleEntry {
  key: string;
  label: string;
  role: TemplateDataRole;
}

interface TemplateBindingGroup {
  nodeId: string;
  label: string;
  sourceRole: TemplateRoleEntry | null;
  targetRole: TemplateRoleEntry | null;
  roles: TemplateRoleEntry[];
}

interface GroupBindingState {
  experimentId: number | null;
  fileId: number | null;
  targetExperimentId: number | null;
  targetFileId: number | null;
}

interface ExampleSourceSummary {
  nodeId: string;
  label: string;
  defaultSource: string;
  defaultDatasetName: string;
}

interface ExampleDatasetChoice {
  label: string;
  source: ReferenceDatasetOption["source"];
  datasetName: string;
  technique?: string | null;
  description?: string | null;
  targetType?: string | null;
  entryType?: string | null;
}

interface ExploreBinding {
  experimentId: number;
  fileId: number | null;
}

const visible = defineModel<boolean>({ default: false });
const emit = defineEmits<{
  instantiated: [result: { workflowId: number; projectId: number | null; slug: string }];
}>();

const router = useRouter();
const toast = useToast();
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const experimentStore = useExperimentStore();

const template = ref<WorkflowTemplate | null>(null);
const workflowName = ref("");
const workflowDescription = ref("");
const launchMode = ref<TemplateLaunchMode>("user");
const isInstantiating = ref(false);
const filesByExperimentId = ref<Record<number, ExperimentFile[]>>({});
const loadingFileIds = ref<Record<number, boolean>>({});
const bindingState = ref<Record<string, GroupBindingState>>({});
const selectedExampleDatasets = ref<Record<string, ExampleDatasetChoice | null>>({});
// Backend-computed match scores: { roleKey: [{ ...dataset, match_score }] }
const datasetMatchScores = ref<Record<string, Record<string, number>>>({});
const activeProjectId = computed(() => projectStore.currentProjectId);

const roleLabels: Record<string, string> = {
  X_spectra: "Spectral Data",
  Y_reference: "Reference Values",
  class_labels: "Class Labels",
  validation_set: "Validation Set",
  wavelength_axis: "Wavelength Axis",
  sample_metadata: "Sample Metadata",
  background_spectrum: "Background Spectrum",
};

const templateStatus = computed(() => template.value?.status || template.value?.template_data.status || "ready");

const projectExperiments = computed<ExperimentBrief[]>(() => {
  const project = projectStore.currentProject;
  if (!project || project.id !== activeProjectId.value) {
    return [];
  }
  return project.experiments || [];
});

const experimentOptions = computed(() =>
  projectExperiments.value.map((experiment) => ({
    label: `${experiment.name} (${experiment.file_count} file${experiment.file_count === 1 ? "" : "s"})`,
    value: experiment.id,
  }))
);

const exampleSources = computed<ExampleSourceSummary[]>(() => {
  const nodes = template.value?.template_data.nodes || [];
  return nodes.flatMap((node) => {
    if (node.node_type !== "data.source") {
      return [];
    }

    const params = node.parameters || {};
    const source = typeof params.source === "string" ? params.source : null;
    if (!source) {
      return [];
    }

    const datasetName =
      (source === "eigenvector" && typeof params.eigenvector_dataset === "string" && params.eigenvector_dataset) ||
      (source === "sklearn" && typeof params.sklearn_dataset === "string" && params.sklearn_dataset) ||
      (source === "spectrochempy" &&
        ((typeof params.example_dataset === "string" && params.example_dataset) ||
          (typeof params.example_file === "string" && params.example_file))) ||
      (source === "oes" && typeof params.oes_dataset === "string" && params.oes_dataset) ||
      null;

    if (!datasetName) {
      return [];
    }

    return [
      {
        nodeId: node.node_id,
        label: node.label || node.node_id,
        defaultSource: source as ExampleSourceSummary["defaultSource"],
        defaultDatasetName: datasetName,
      },
    ];
  });
});

const supportsExampleMode = computed(() => exampleSources.value.length > 0);

const dataRoleGroups = computed<TemplateBindingGroup[]>(() => {
  const roles = template.value?.template_data.data_roles || {};
  const grouped = new Map<string, TemplateRoleEntry[]>();

  for (const [key, role] of Object.entries(roles)) {
    if (role.required === false) continue;
    const nodeId = role.node_binding;
    if (!nodeId) continue;

    const entry: TemplateRoleEntry = {
      key,
      label: roleLabels[role.role_type] || key.replace(/_/g, " "),
      role,
    };
    if (!grouped.has(nodeId)) {
      grouped.set(nodeId, []);
    }
    grouped.get(nodeId)!.push(entry);
  }

  return Array.from(grouped.entries()).map(([nodeId, rolesForNode]) => {
    const sourceRole =
      rolesForNode.find((entry) => entry.role.role_type === "X_spectra") || rolesForNode[0] || null;
    const targetRole =
      rolesForNode.find((entry) => ["Y_reference", "class_labels"].includes(entry.role.role_type)) || null;

    return {
      nodeId,
      label: sourceRole ? sourceRole.label : "Input Data",
      sourceRole,
      targetRole,
      roles: rolesForNode,
    };
  });
});

const canInstantiate = computed(() => {
  if (!template.value || !workflowName.value.trim() || activeProjectId.value === null) {
    return false;
  }
  if (templateStatus.value !== "ready") {
    return false;
  }
  if (launchMode.value === "example") {
    return supportsExampleMode.value && exampleSources.value.every((source) => !!selectedExampleDatasets.value[source.nodeId]);
  }
  if (dataRoleGroups.value.length === 0) {
    return true;
  }
  if (projectExperiments.value.length === 0) {
    return false;
  }

  return dataRoleGroups.value.every((group) => {
    const state = bindingState.value[group.nodeId];
    if (!state?.experimentId || !state.fileId) {
      return false;
    }
    if (group.targetRole?.role.binding_mode === "separate_source") {
      return !!state.targetExperimentId && !!state.targetFileId;
    }
    return true;
  });
});

function compactPath(filePath: string): string {
  const normalized = filePath.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || filePath;
}

function roleDescription(entry: TemplateRoleEntry): string {
  const description = entry.role.description?.trim();
  const techniques = entry.role.accepted_techniques?.length
    ? `Accepted techniques: ${entry.role.accepted_techniques.join(", ")}.`
    : "";
  if (description && techniques) {
    return `${description} ${techniques}`;
  }
  return description || techniques || "";
}

function roleHint(entry: TemplateRoleEntry): string {
  if (entry.role.binding_mode === "embedded") {
    return "This information must already be embedded in the selected source file.";
  }
  if (entry.role.binding_mode === "separate_source") {
    return "This role is supplied from a separate experiment file and attached during instantiation.";
  }
  return "This role is bound through the template workflow.";
}

function sourceLabel(source: string): string {
  if (source === "eigenvector") return "Eigenvector Research";
  if (source === "sklearn") return "Scikit-learn";
  if (source === "spectrochempy") return "SpectroChemPy";
  if (source === "oes") return "OES";
  return source;
}

function findWorkflowExploreBinding(): ExploreBinding | null {
  const candidates = workflowStore.nodes
    .filter((node) => node.type === "data.source" && !String(node.id).endsWith("__target_source"))
    .map((node) => {
      const params = node.params || {};
      const experimentId =
        typeof params.experiment_id === "number"
          ? params.experiment_id
          : typeof params.experiment_id === "string"
            ? Number.parseInt(params.experiment_id, 10)
            : NaN;
      const fileId =
        typeof params.file_id === "number"
          ? params.file_id
          : typeof params.file_id === "string" && params.file_id.trim()
            ? Number.parseInt(params.file_id, 10)
            : null;
      if (!Number.isFinite(experimentId)) {
        return null;
      }
      return {
        experimentId,
        fileId: fileId != null && Number.isFinite(fileId) ? fileId : null,
      };
    })
    .filter((binding): binding is ExploreBinding => binding !== null);

  return candidates.find((binding) => binding.fileId !== null) || candidates[0] || null;
}

function normalizeTargetType(group: TemplateBindingGroup | undefined): string | null {
  if (!group?.targetRole) return null;
  return group.targetRole.role.target_type || (group.targetRole.role.role_type === "class_labels" ? "categorical" : null);
}

function compatibleExampleDatasetsForNode(nodeId: string): ExampleDatasetChoice[] {
  const group = dataRoleGroups.value.find((entry) => entry.nodeId === nodeId);
  const acceptedTechniques = new Set(
    (group?.roles || [])
      .filter((entry) => entry.role.role_type === "X_spectra")
      .flatMap((entry) => entry.role.accepted_techniques || [])
      .map((technique) => technique.trim())
      .filter(Boolean)
  );
  const requiredTargetType = normalizeTargetType(group);

  const allOptions = ["eigenvector", "spectrochempy", "oes", "sklearn"]
    .flatMap((source) => workflowStore.getReferenceDatasetOptions(source))
    .filter((option) => {
      if (requiredTargetType) {
        if (!option.has_embedded_target || option.target_type !== requiredTargetType) {
          return false;
        }
      }

      if (acceptedTechniques.size === 0) {
        return true;
      }

      if (option.technique && acceptedTechniques.has(option.technique)) {
        return true;
      }

      if (option.source === "sklearn" && requiredTargetType === "categorical") {
        return true;
      }

      return false;
    })
    .map((option) => ({
      label: option.label,
      source: option.source,
      datasetName: option.name,
      technique: option.technique,
      description: option.description,
      targetType: option.target_type,
      entryType: option.entry_type,
    }));

  // Sort by backend match score (descending) then alphabetically
  const roleKeys = (group?.roles || []).map((r) => r.key);
  const scoreLookup = roleKeys.reduce<Record<string, number>>((acc, key) => {
    const scores = datasetMatchScores.value[key];
    if (scores) Object.assign(acc, scores);
    return acc;
  }, {});

  return allOptions.sort((left, right) => {
    const scoreLeft = scoreLookup[`${left.source}:${left.datasetName}`] || 0;
    const scoreRight = scoreLookup[`${right.source}:${right.datasetName}`] || 0;
    if (scoreRight !== scoreLeft) return scoreRight - scoreLeft;
    return left.label.localeCompare(right.label);
  });
}

function resetExampleSelections() {
  const nextState: Record<string, ExampleDatasetChoice | null> = {};

  for (const source of exampleSources.value) {
    const options = compatibleExampleDatasetsForNode(source.nodeId);
    const defaultMatch =
      options.find(
        (option) => option.source === source.defaultSource && option.datasetName === source.defaultDatasetName
      ) || null;
    // Auto-select: template default > sole option > highest-scored match (score >= 15)
    let autoSelection: ExampleDatasetChoice | null = defaultMatch;
    if (!autoSelection && options.length === 1) {
      autoSelection = options[0];
    }
    if (!autoSelection && options.length > 0) {
      // options are already sorted by match_score descending — pick top if strong match
      const topKey = `${options[0].source}:${options[0].datasetName}`;
      const allScores = Object.values(datasetMatchScores.value);
      const topScore = allScores.reduce((max, lookup) => Math.max(max, lookup[topKey] || 0), 0);
      if (topScore >= 15) {
        autoSelection = options[0];
      }
    }
    nextState[source.nodeId] = autoSelection;
  }

  selectedExampleDatasets.value = nextState;
}

async function ensureProjectLoaded(projectId: number | null) {
  if (projectId == null) return;
  // Always re-fetch to get fresh experiment list
  await projectStore.fetchProject(projectId);
}

async function ensureExperimentFiles(experimentId: number | null) {
  if (experimentId == null || filesByExperimentId.value[experimentId]) {
    return;
  }
  loadingFileIds.value = { ...loadingFileIds.value, [experimentId]: true };
  try {
    const files = await experimentStore.fetchFiles(experimentId);
    filesByExperimentId.value = {
      ...filesByExperimentId.value,
      [experimentId]: files,
    };
  } finally {
    loadingFileIds.value = { ...loadingFileIds.value, [experimentId]: false };
  }
}

function resetBindingState() {
  const nextState: Record<string, GroupBindingState> = {};
  for (const group of dataRoleGroups.value) {
    nextState[group.nodeId] = {
      experimentId: null,
      fileId: null,
      targetExperimentId: null,
      targetFileId: null,
    };
  }
  bindingState.value = nextState;
}

function getGroupState(nodeId: string): GroupBindingState {
  if (!bindingState.value[nodeId]) {
    bindingState.value[nodeId] = {
      experimentId: null,
      fileId: null,
      targetExperimentId: null,
      targetFileId: null,
    };
  }
  return bindingState.value[nodeId];
}

function fileOptionsForExperiment(experimentId: number | null) {
  if (experimentId == null) return [];
  return (filesByExperimentId.value[experimentId] || []).map((file) => ({
    label: `${compactPath(file.file_path)} · ${file.stage}`,
    value: file.id,
  }));
}

function resolveStage(experimentId: number, fileId: number | null): ExperimentStage {
  const file = (filesByExperimentId.value[experimentId] || []).find((candidate) => candidate.id === fileId);
  return (file?.stage || "raw") as ExperimentStage;
}

function firstSelectedBinding(): { experimentId: number; fileId: number } | null {
  for (const group of dataRoleGroups.value) {
    const state = getGroupState(group.nodeId);
    if (state.experimentId != null && state.fileId != null) {
      return {
        experimentId: state.experimentId,
        fileId: state.fileId,
      };
    }
  }
  return null;
}

async function onSourceExperimentChange(nodeId: string, experimentId: number | null) {
  const state = getGroupState(nodeId);
  state.experimentId = experimentId;
  state.fileId = null;
  if (experimentId != null) {
    await ensureExperimentFiles(experimentId);
  }
}

async function onTargetExperimentChange(nodeId: string, experimentId: number | null) {
  const state = getGroupState(nodeId);
  state.targetExperimentId = experimentId;
  state.targetFileId = null;
  if (experimentId != null) {
    await ensureExperimentFiles(experimentId);
  }
}

async function open(nextTemplate: WorkflowTemplate) {
  // Always fetch the full template from the API to ensure data_roles
  // and other fields are present (list endpoint responses may be cached
  // or incomplete due to browser/HMR caching).
  try {
    const fresh = await workflowStore.fetchTemplate(nextTemplate.id);
    template.value = fresh;
  } catch {
    // Fall back to the passed object if the fetch fails
    template.value = nextTemplate;
  }
  workflowName.value = template.value!.name;
  workflowDescription.value = template.value!.description;
  launchMode.value = supportsExampleMode.value ? "example" : "user";
  isInstantiating.value = false;
  filesByExperimentId.value = {};
  resetBindingState();
  await workflowStore.fetchReferenceDatasets();

  // Fetch backend-computed dataset match scores for smarter sorting
  datasetMatchScores.value = {};
  try {
    const matchResp = await api.get(`/workflow-templates/${template.value!.id}/matching-datasets`);
    if (matchResp.data) {
      // Build lookup: { roleKey: { "source:datasetName": score } }
      const lookup: Record<string, Record<string, number>> = {};
      for (const [roleKey, matches] of Object.entries(matchResp.data as Record<string, Array<{ source: string; name: string; match_score: number }>>)) {
        lookup[roleKey] = {};
        for (const m of matches) {
          lookup[roleKey][`${m.source}:${m.name}`] = m.match_score;
        }
      }
      datasetMatchScores.value = lookup;
    }
  } catch {
    // Non-critical — fall back to client-side sorting
  }

  resetExampleSelections();

  if (activeProjectId.value != null) {
    await ensureProjectLoaded(activeProjectId.value);
  }

  visible.value = true;
}

async function handleInstantiate() {
  if (!template.value || activeProjectId.value === null) return;

  isInstantiating.value = true;
  try {
    const dataBindings: Record<string, TemplateDataBinding> = {};

    for (const group of dataRoleGroups.value) {
      const state = getGroupState(group.nodeId);
      if (state.experimentId == null || state.fileId == null) {
        continue;
      }

      dataBindings[group.nodeId] = {
        source: "experiment",
        experimentId: state.experimentId,
        fileId: state.fileId,
        stage: resolveStage(state.experimentId, state.fileId),
        targetType: group.targetRole?.role.target_type || null,
      };

      if (
        group.targetRole?.role.binding_mode === "separate_source" &&
        state.targetExperimentId != null &&
        state.targetFileId != null
      ) {
        dataBindings[group.nodeId].targetBinding = {
          source: "experiment",
          experimentId: state.targetExperimentId,
          fileId: state.targetFileId,
          stage: resolveStage(state.targetExperimentId, state.targetFileId),
        };
      }
    }

    const result = await workflowStore.instantiateTemplate(template.value.id, {
      workflowName: workflowName.value.trim(),
      workflowDescription: workflowDescription.value.trim() || undefined,
      projectId: activeProjectId.value,
      launchMode: launchMode.value,
      dataBindings: launchMode.value === "user" ? dataBindings : undefined,
      exampleBindings:
        launchMode.value === "example"
          ? Object.fromEntries(
              Object.entries(selectedExampleDatasets.value)
                .filter(([, choice]) => !!choice)
                .map(([nodeId, choice]) => [
                  nodeId,
                  {
                    source: choice!.source,
                    datasetName: choice!.datasetName,
                  },
                ])
            )
          : undefined,
    });

    await projectStore.fetchProject(activeProjectId.value);
    await workflowStore.loadWorkflow(result.workflowId);

    toast.add({
      severity: "success",
      summary: "Template Ready",
      detail: `Created "${workflowName.value.trim()}" in the active project`,
      life: 3000,
    });

    visible.value = false;
    emit("instantiated", result);
    if (launchMode.value === "example") {
      window.sessionStorage.setItem(DATA_ENTRY_MODE_KEY, "template-example");
      window.sessionStorage.setItem(DATA_ENTRY_PROJECT_KEY, String(activeProjectId.value));
    } else {
      window.sessionStorage.removeItem(DATA_ENTRY_MODE_KEY);
      window.sessionStorage.removeItem(DATA_ENTRY_PROJECT_KEY);
    }
    const selectedBinding = launchMode.value === "user" ? firstSelectedBinding() : null;
    const exploreBinding = selectedBinding || findWorkflowExploreBinding();
    const exploreQuery: Record<string, string> = {
      tab: "explore",
      fromTemplate: "1",
      workflowId: String(result.workflowId),
    };
    if (exploreBinding?.experimentId) {
      exploreQuery.experimentId = String(exploreBinding.experimentId);
      if (exploreBinding.fileId != null) {
        exploreQuery.fileId = String(exploreBinding.fileId);
      }
    } else {
      exploreQuery.focus = "latest-project";
    }
    await router.push({
      path: "/data",
      query: exploreQuery,
    });
  } catch (error: unknown) {
    toast.add({
      severity: "error",
      summary: "Template Failed",
      detail: getErrorMessage(error, "Could not create the workflow from this template"),
      life: 5000,
    });
  } finally {
    isInstantiating.value = false;
  }
}

watch(activeProjectId, async (projectId) => {
  resetBindingState();
  filesByExperimentId.value = {};
  if (projectId != null) {
    await ensureProjectLoaded(projectId);
  }
});

defineExpose({ open });
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="template ? `Use Template: ${template.name}` : 'Use Template'"
    :style="{ width: '760px' }"
    :closable="!isInstantiating"
    :close-on-escape="!isInstantiating"
  >
    <div v-if="template" class="template-wizard">
      <div class="template-summary">
        <div class="template-summary-row">
          <span class="template-category">{{ template.category.replace(/_/g, " ") }}</span>
          <span class="template-status" :class="templateStatus">{{ templateStatus }}</span>
        </div>
        <p class="template-description">{{ template.description }}</p>
      </div>

      <div class="launch-mode-section">
        <div class="binding-header">
          <h4>Launch Mode</h4>
          <p>Choose whether to start from the bundled validated example or bind this template to your own project data.</p>
        </div>
        <div class="launch-mode-grid">
          <button
            type="button"
            class="launch-mode-card"
            :class="{ active: launchMode === 'example', disabled: !supportsExampleMode }"
            :disabled="!supportsExampleMode"
            @click="launchMode = 'example'"
          >
            <span class="launch-mode-title">Use Example Data</span>
            <span class="launch-mode-copy">
              Import the bundled example dataset into this project automatically and instantiate the workflow against it.
            </span>
          </button>
          <button
            type="button"
            class="launch-mode-card"
            :class="{ active: launchMode === 'user' }"
            @click="launchMode = 'user'"
          >
            <span class="launch-mode-title">Use My Dataset</span>
            <span class="launch-mode-copy">
              Bind explicit project experiments and files for the required chemometric roles before the workflow is created.
            </span>
          </button>
        </div>
      </div>

      <Message v-if="templateStatus !== 'ready'" severity="warn" :closable="false">
        This template is still marked work in progress and cannot be instantiated for production work.
      </Message>

      <Message v-if="activeProjectId === null" severity="warn" :closable="false">
        Select an active project first. Templates now belong to Projects so new workflows keep their data and analysis context together.
      </Message>

      <div class="field">
        <label for="template-workflow-name">Workflow Name</label>
        <InputText
          id="template-workflow-name"
          v-model="workflowName"
          placeholder="Workflow name"
          class="full-width"
        />
      </div>

      <div class="field">
        <label for="template-workflow-description">Description</label>
        <Textarea
          id="template-workflow-description"
          v-model="workflowDescription"
          rows="3"
          auto-resize
          class="full-width"
          placeholder="Optional description"
        />
      </div>

      <div v-if="launchMode === 'example'" class="binding-section">
        <div class="binding-header">
          <h4>Bundled Example Data</h4>
          <p>Select one compatible bundled dataset. It will be imported into a project-linked dataset so you can inspect and rerun the workflow with visible provenance.</p>
        </div>

        <article
          v-for="source in exampleSources"
          :key="source.nodeId"
          class="binding-card"
        >
          <div class="binding-card-header">
            <h5>{{ source.label }}</h5>
            <span class="binding-node-id">{{ source.nodeId }}</span>
          </div>
          <div class="field">
            <label :for="`${source.nodeId}-example-dataset`">Compatible Example Dataset</label>
            <Dropdown
              :id="`${source.nodeId}-example-dataset`"
              v-model="selectedExampleDatasets[source.nodeId]"
              :options="compatibleExampleDatasetsForNode(source.nodeId)"
              option-label="label"
              placeholder="Select example dataset"
              class="full-width"
            >
              <template #value="{ value, placeholder }">
                <span v-if="value" class="example-choice-value">
                  {{ value.label }} · {{ sourceLabel(value.source) }}
                </span>
                <span v-else class="p-dropdown-placeholder">{{ placeholder }}</span>
              </template>
              <template #option="{ option }">
                <div class="example-choice-option">
                  <strong>{{ option.label }}</strong>
                  <small>{{ sourceLabel(option.source) }}<span v-if="option.technique"> · {{ option.technique }}</span></small>
                </div>
              </template>
            </Dropdown>
            <small class="field-hint">
              Only example datasets compatible with this template’s required roles are shown.
            </small>
          </div>
          <Message
            v-if="compatibleExampleDatasetsForNode(source.nodeId).length === 0"
            severity="warn"
            :closable="false"
          >
            No bundled example datasets currently satisfy this template’s required roles.
          </Message>
          <div
            v-else-if="selectedExampleDatasets[source.nodeId]"
            class="binding-role-list"
          >
            <div class="binding-role">
              <strong>{{ sourceLabel(selectedExampleDatasets[source.nodeId]!.source) }}</strong>
              <p>{{ selectedExampleDatasets[source.nodeId]!.datasetName }}</p>
              <small>
                {{ selectedExampleDatasets[source.nodeId]!.description || "This example dataset will be imported automatically." }}
              </small>
            </div>
          </div>
        </article>
      </div>

      <div v-else-if="dataRoleGroups.length > 0" class="binding-section">
        <div class="binding-header">
          <h4>Bind Project Data</h4>
          <p>Templates now bind explicit chemometric data roles before the workflow is created. Select the experiment files that supply each required role.</p>
        </div>

        <Message
          v-if="activeProjectId !== null && projectExperiments.length === 0"
          severity="warn"
          :closable="false"
        >
          This project has no linked experiments yet. Add data to the project first, then instantiate the template with project data.
        </Message>

        <article
          v-for="group in dataRoleGroups"
          :key="group.nodeId"
          class="binding-card"
        >
          <div class="binding-card-header">
            <h5>{{ group.label }}</h5>
            <span class="binding-node-id">{{ group.nodeId }}</span>
          </div>

          <div class="binding-role-list">
            <div
              v-for="entry in group.roles"
              :key="entry.key"
              class="binding-role"
            >
              <strong>{{ entry.label }}</strong>
              <p>{{ roleDescription(entry) }}</p>
              <small>{{ roleHint(entry) }}</small>
            </div>
          </div>

          <div class="binding-grid">
            <div class="field">
              <label :for="`${group.nodeId}-experiment`">Experiment</label>
              <Dropdown
                :id="`${group.nodeId}-experiment`"
                :model-value="getGroupState(group.nodeId).experimentId"
                :options="experimentOptions"
                option-label="label"
                option-value="value"
                placeholder="Select experiment"
                class="full-width"
                @update:model-value="(value) => onSourceExperimentChange(group.nodeId, value)"
              />
            </div>

            <div class="field">
              <label :for="`${group.nodeId}-file`">Source File</label>
              <Dropdown
                :id="`${group.nodeId}-file`"
                v-model="getGroupState(group.nodeId).fileId"
                :options="fileOptionsForExperiment(getGroupState(group.nodeId).experimentId)"
                option-label="label"
                option-value="value"
                placeholder="Select source file"
                class="full-width"
                :loading="loadingFileIds[getGroupState(group.nodeId).experimentId || -1]"
                :disabled="getGroupState(group.nodeId).experimentId === null"
              />
            </div>
          </div>

          <div
            v-if="group.targetRole?.role.binding_mode === 'separate_source'"
            class="binding-grid secondary-binding-grid"
          >
            <div class="field">
              <label :for="`${group.nodeId}-target-experiment`">{{ group.targetRole.label }} Experiment</label>
              <Dropdown
                :id="`${group.nodeId}-target-experiment`"
                :model-value="getGroupState(group.nodeId).targetExperimentId"
                :options="experimentOptions"
                option-label="label"
                option-value="value"
                placeholder="Select target experiment"
                class="full-width"
                @update:model-value="(value) => onTargetExperimentChange(group.nodeId, value)"
              />
            </div>

            <div class="field">
              <label :for="`${group.nodeId}-target-file`">{{ group.targetRole.label }} File</label>
              <Dropdown
                :id="`${group.nodeId}-target-file`"
                v-model="getGroupState(group.nodeId).targetFileId"
                :options="fileOptionsForExperiment(getGroupState(group.nodeId).targetExperimentId)"
                option-label="label"
                option-value="value"
                placeholder="Select target file"
                class="full-width"
                :loading="loadingFileIds[getGroupState(group.nodeId).targetExperimentId || -1]"
                :disabled="getGroupState(group.nodeId).targetExperimentId === null"
              />
            </div>
          </div>
        </article>
      </div>
    </div>

    <template #footer>
      <Button
        label="Cancel"
        class="p-button-text"
        :disabled="isInstantiating"
        @click="visible = false"
      />
      <Button
        label="Create Workflow"
        icon="pi pi-check"
        :loading="isInstantiating"
        :disabled="!canInstantiate"
        @click="handleInstantiate"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.template-wizard {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.template-summary {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.template-summary-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.template-category {
  width: fit-content;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  background: var(--surface-200);
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: capitalize;
}

.template-status {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.5rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.template-status.ready {
  background: color-mix(in srgb, var(--green-500) 15%, white);
  color: var(--green-700);
}

.template-status.wip {
  background: color-mix(in srgb, var(--yellow-500) 18%, white);
  color: var(--yellow-800);
}

.template-description {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.field label {
  font-weight: 600;
}

.field-hint {
  color: var(--text-color-secondary);
}

.binding-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.launch-mode-section {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.launch-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link) {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  width: 100%;
  padding: 0.9rem 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 14px;
  background: var(--surface-card);
  color: var(--text-color, #1e293b);
  text-align: left;
  cursor: pointer;
  appearance: none;
  transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease, background-color 120ms ease;
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link):hover:not(.disabled) {
  border-color: color-mix(in srgb, var(--text-color, #1e293b) 20%, var(--surface-border));
  transform: translateY(-1px);
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link):focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text-color, #1e293b) 10%, transparent);
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link).active {
  border-width: 2px;
  border-color: color-mix(in srgb, var(--text-color, #1e293b) 42%, var(--surface-border));
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--text-color, #1e293b) 8%, transparent),
    0 10px 24px rgba(15, 23, 42, 0.08);
  background: var(--surface-card);
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link).active::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  border-radius: 14px 0 0 14px;
  background: var(--text-color, #1e293b);
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link).disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}

.launch-mode-title {
  font-weight: 700;
  color: var(--text-color, #1e293b);
}

button.launch-mode-card:not(.p-button):not(.p-dialog-header-icon):not(.p-link).active .launch-mode-title {
  font-weight: 800;
}

.launch-mode-copy {
  color: var(--text-color-secondary, #64748b);
  line-height: 1.45;
}

.binding-header h4 {
  margin: 0 0 0.3rem;
}

.binding-header p {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.binding-card {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 14px;
  background: var(--surface-card);
}

.binding-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.binding-card-header h5 {
  margin: 0;
  font-size: 1rem;
}

.binding-node-id {
  font-family: var(--font-family-monospace, monospace);
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.binding-role-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}

.binding-role {
  padding: 0.75rem;
  border-radius: 10px;
  background: var(--surface-50);
}

.binding-role p,
.binding-role small {
  margin: 0.25rem 0 0;
  color: var(--text-color-secondary);
  line-height: 1.45;
}

.binding-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
}

.example-choice-value {
  display: inline-flex;
  align-items: center;
  min-height: 1.5rem;
}

.example-choice-option {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.example-choice-option small {
  color: var(--text-color-secondary);
}

.secondary-binding-grid {
  padding-top: 0.3rem;
  border-top: 1px dashed var(--surface-border);
}

.full-width {
  width: 100%;
}

@media (max-width: 720px) {
  .launch-mode-grid,
  .binding-grid,
  .binding-role-list {
    grid-template-columns: 1fr;
  }
}
</style>
