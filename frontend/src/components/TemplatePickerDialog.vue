<template>
  <Dialog
    v-model:visible="visible"
    modal
    :draggable="false"
    :style="{ width: '720px' }"
    header="Analysis Starters"
    class="template-picker-dialog"
  >
    <div v-if="loading" class="tp-status">
      <i class="pi pi-spin pi-spinner"></i> Loading analysis starters...
    </div>
    <div v-else-if="loadError" class="tp-status tp-status-error">
      <i class="pi pi-exclamation-triangle"></i>
      {{ loadError }}
    </div>
    <div v-else-if="templates.length === 0" class="tp-status">
      No analysis starters are available. Reinstall <code>spectra-sherpa</code> to refresh the
      catalog.
    </div>
    <template v-else>
      <p v-if="activeProjectDataset" class="tp-row-requirement">
        <i class="pi pi-database" aria-hidden="true" />
        Project dataset: {{ activeProjectDataset.name }}
      </p>
      <p v-if="projectDatasetChoiceError" class="tp-status tp-status-warning" role="alert">
        {{ projectDatasetChoiceError }}
      </p>
      <div v-for="(group, idx) in groupedTemplates" :key="group.category" class="tp-group">
        <h4 class="tp-group-title">
          {{ group.category }}
          <span class="tp-group-count">({{ group.items.length }})</span>
        </h4>
        <ul class="tp-list">
          <li v-for="tpl in group.items" :key="tpl.id" class="tp-row">
            <div class="tp-row-main">
              <div class="tp-row-title">
                {{ tpl.name }}
                <span
                  v-if="!templateRuntimeReady(tpl)"
                  class="tp-needs-data"
                  title="This analysis starter is unavailable in the current server runtime."
                >
                  unavailable
                </span>
                <span
                  v-else-if="!canUseTemplate(tpl)"
                  class="tp-needs-data"
                  title="This analysis starter needs you to bind it to your own data after creation."
                >
                  needs data
                </span>
              </div>
              <p v-if="tpl.description" class="tp-row-description">{{ tpl.description }}</p>
              <p v-if="tpl.example_unavailable_reason" class="tp-row-requirement">
                {{ tpl.example_unavailable_reason }}
              </p>
              <p v-else-if="exampleDataSummary(tpl)" class="tp-row-requirement">
                <i class="pi pi-database" aria-hidden="true" />
                {{ exampleDataSummary(tpl) }}
              </p>
              <p v-if="currentSelectionDecisionMessage(tpl)" class="tp-row-requirement">
                <i class="pi pi-info-circle" aria-hidden="true" />
                Current selection: {{ currentSelectionDecisionMessage(tpl) }}
              </p>
              <p v-if="multiSourceBindingSummary(tpl)" class="tp-row-requirement">
                <i class="pi pi-link" aria-hidden="true" />
                {{ multiSourceBindingSummary(tpl) }}
              </p>
              <p v-if="managedCandidateSelectionWarning(tpl)" class="tp-row-requirement">
                <i class="pi pi-exclamation-triangle" aria-hidden="true" />
                {{ managedCandidateSelectionWarning(tpl) }}
              </p>
            </div>
            <div class="tp-row-actions">
              <Button
                v-if="hasCurrentData || projectDatasetChoiceError"
                :label="currentDataButtonLabel(tpl)"
                :icon="currentDataButtonIcon(tpl)"
                icon-pos="right"
                class="p-button-sm"
                :disabled="instantiating !== null || !projectAvailable || !!projectDatasetChoiceError || !canUseCurrentData(tpl)"
                :title="currentDataButtonTitle(tpl)"
                @click="onUse(tpl, 'current')"
              />
              <Button
                v-if="supportsExample(tpl)"
                label="Use Bundled Example"
                :icon="instantiating === tpl.id ? 'pi pi-spin pi-spinner' : 'pi pi-box'"
                icon-pos="right"
                class="p-button-sm p-button-outlined"
                :disabled="instantiating !== null || !projectAvailable || !templateRuntimeReady(tpl)"
                :title="exampleButtonTitle(tpl)"
                @click="onUse(tpl, 'example')"
              />
              <Button
                v-if="!hasCurrentData && !projectDatasetChoiceError && !supportsExample(tpl)"
                :label="templateRuntimeReady(tpl) ? 'Needs data' : 'Unavailable'"
                icon="pi pi-lock"
                class="p-button-sm"
                disabled
                :title="templateRuntimeMessage(tpl) || 'Select data in My Dataset before using this starter.'"
              />
              <Button
                v-if="requiresTargetSetup(tpl)"
                label="Set target in My Dataset"
                icon="pi pi-arrow-right"
                class="p-button-sm p-button-text tp-readiness-action"
                @click="openDatasetReadiness"
              />
            </div>
          </li>
        </ul>
        <hr v-if="idx < groupedTemplates.length - 1" class="tp-group-sep" />
      </div>
      <div v-if="!projectAvailable" class="tp-status tp-status-warning">
        <i class="pi pi-info-circle"></i>
        Create or open a project first — analysis starters create workflow sheets inside the active
        project.
      </div>
    </template>

    <template #footer>
      <Button label="Close" icon="pi pi-times" @click="visible = false" autofocus />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { api } from "@/api";
import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowStore } from "@/stores/workflow";
import type { TargetAuthority, TemplateDataBinding, WorkflowNode } from "@/stores/workflow-types";
import type {
  DatasetAnalysisReadiness,
  DatasetAnalysisReadinessDecision,
  ExperimentStage,
} from "@/types";
import { getErrorMessage } from "@/utils/errors";
import {
  bindingForTemplateSource,
  bindingFromSelectionReceipt,
  type DataSelectionReceipt,
} from "@/utils/workflowDataSelection";

interface TemplateNode {
  node_id?: string;
  node_type?: string;
  label?: string;
  parameters?: Record<string, unknown>;
  example_binding?: {
    source?: string;
    dataset_name?: string;
    selected_target?: string;
    target_type?: string;
  };
}

interface TemplateRole {
  node_binding?: string;
  required?: boolean;
  binding_mode?: string;
  target_type?: string | null;
}

interface TemplateOut {
  id: number;
  slug: string;
  name: string;
  description: string;
  example_unavailable_reason?: string | null;
  category: string;
  status: "ready" | "pending_data" | "pending_qualification" | "wip";
  status_detail: string | null;
  runtime_readiness?: {
    ready: boolean;
    blockers: string[];
    remediation: string[];
    unavailable_nodes: Array<{ node_id: string; node_type: string; blockers: string[] }>;
  };
  is_active: boolean;
  template_data: {
    nodes?: TemplateNode[];
    data_roles?: Record<string, TemplateRole>;
    [key: string]: unknown;
  };
}

interface ActiveProjectDataset {
  id: number;
  name: string;
  digest: string;
  definition: {
    experiment_id: number;
    stage: ExperimentStage;
    selected_file_ids: number[] | null;
    asset_id: string | null;
    target_authority: TargetAuthority | null;
    group_column: string | null;
  };
}

const visible = defineModel<boolean>("visible", { default: false });
const props = defineProps<{
  dataSelection?: DataSelectionReceipt | null;
  preferredTemplateSlug?: string | null;
}>();
const emit = defineEmits<{ "sheet-opened": [] }>();

const workbookStore = useWorkbookStore();
const workflowStore = useWorkflowStore();
const toast = useToast();
const router = useRouter();

const templates = ref<TemplateOut[]>([]);
const loading = ref(false);
const loadError = ref<string | null>(null);
const instantiating = ref<number | null>(null);
const selectedExperimentId = ref<number | null>(null);
const autoStartedSlug = ref<string | null>(null);
const effectiveDataSelection = ref<DataSelectionReceipt | null>(props.dataSelection ?? null);
const activeBindingReadiness = ref<DatasetAnalysisReadiness | null>(null);
const activeProjectDataset = ref<ActiveProjectDataset | null>(null);
const projectDatasetChoiceError = ref<string | null>(null);

const projectAvailable = computed(() => workbookStore.projectId !== null);

// "Pretty" category labels — keys match the slugs in the YAML catalog
// (calibration, classification, curve_resolution, etc.).  Anything not
// listed here falls through to a title-cased version of the slug.
const CATEGORY_LABELS: Record<string, string> = {
  calibration: "Calibration",
  classification: "Classification",
  clustering: "Clustering",
  curve_resolution: "Curve Resolution",
  exploratory: "Exploratory Analysis",
  preprocessing: "Preprocessing",
  quality_control: "Quality Control",
  selection_design: "Variable Selection & Design",
  spectroscopy: "Spectroscopy",
};

const labelFor = (category: string): string =>
  CATEGORY_LABELS[category] ?? category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const groupedTemplates = computed(() => {
  const groups = new Map<string, TemplateOut[]>();
  for (const tpl of templates.value) {
    const arr = groups.get(tpl.category) ?? [];
    arr.push(tpl);
    groups.set(tpl.category, arr);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, items]) => ({
      category: labelFor(category),
      items: items.slice().sort((a, b) => a.name.localeCompare(b.name)),
    }));
});

// Example selection is template metadata. The persisted DAG receives only an
// exact data.file_load identity after materialization.
const supportsExample = (tpl: TemplateOut): boolean => {
  if (tpl.example_unavailable_reason) return false;
  const nodes = tpl.template_data?.nodes ?? [];
  return nodes.some((n) => {
    if (n.node_type !== "data.file_load") return false;
    return (
      typeof n.example_binding?.source === "string" &&
      typeof n.example_binding.dataset_name === "string"
    );
  });
};

const exampleDataSummary = (tpl: TemplateOut): string | null => {
  const examples = (tpl.template_data?.nodes ?? [])
    .filter((node) => node.node_type === "data.file_load" && node.example_binding?.dataset_name)
    .map(
      (node) =>
        `${node.example_binding?.dataset_name} (${node.example_binding?.source || "bundled"})`,
    );
  const unique = [...new Set(examples)];
  return unique.length
    ? `Example source: ${unique.join(", ")}. The new sheet and report will retain this identity.`
    : null;
};

const parseNumberParam = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const normalizeStage = (value: unknown): ExperimentStage =>
  typeof value === "string" && value.trim() ? (value as ExperimentStage) : "raw";

const targetAuthorityFromParams = (value: unknown): TargetAuthority | null => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.schema_version !== "spectrasherpa-target-authority/1" ||
    typeof candidate.column !== "string" ||
    !candidate.column ||
    (candidate.target_type !== "continuous" && candidate.target_type !== "categorical") ||
    (candidate.units !== null && typeof candidate.units !== "string") ||
    typeof candidate.source_digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(candidate.source_digest)
  ) {
    return null;
  }
  return candidate as unknown as TargetAuthority;
};

const isPrimaryDataSourceNode = (node: WorkflowNode): boolean =>
  (node.type === "data.file_load" || node.type === "data.collection_load") &&
  !String(node.id).endsWith("__target_source");

const isTargetDataSourceNode = (node: WorkflowNode): boolean =>
  node.type === "data.file_load" && String(node.id).endsWith("__target_source");

const bindingFromNode = (node: WorkflowNode | undefined): TemplateDataBinding | null => {
  if (!node) return null;
  const params = node.params || {};
  const experimentId = parseNumberParam(params.experiment_id);
  if (experimentId === null) return null;
  if (node.type === "data.collection_load") {
    const fileIds = Array.isArray(params.selected_file_ids)
      ? params.selected_file_ids
          .map(parseNumberParam)
          .filter((value): value is number => value !== null)
      : [];
    if (fileIds.length === 0) return null;
    return {
      source: "experiment",
      experimentId,
      displayName:
        typeof params.group_title === "string" && params.group_title ? params.group_title : null,
      fileIds,
      allFiles: false,
      targetAuthority: targetAuthorityFromParams(params.target_authority),
      groupColumn:
        typeof params.group_column === "string" && params.group_column ? params.group_column : null,
      stage: normalizeStage(params.stage),
    };
  }
  const fileId = parseNumberParam(params.file_id);
  if (fileId === null) return null;
  return {
    source: "experiment",
    experimentId,
    fileId,
    targetAuthority: targetAuthorityFromParams(params.target_authority),
    groupColumn:
      typeof params.group_column === "string" && params.group_column ? params.group_column : null,
    stage: normalizeStage(params.stage),
  };
};

const currentPrimaryDataBinding = (): TemplateDataBinding | null => {
  if (projectDatasetChoiceError.value) return null;
  const selected = activeProjectDataset.value;
  if (selected) {
    const definition = selected.definition;
    return {
      source: "experiment",
      experimentId: definition.experiment_id,
      displayName: selected.name,
      fileIds: definition.selected_file_ids,
      allFiles: definition.selected_file_ids === null,
      assetId: definition.asset_id,
      targetAuthority: definition.target_authority,
      groupColumn: definition.group_column,
      stage: definition.stage,
    };
  }
  return bindingFromNode(workflowStore.nodes.find(isPrimaryDataSourceNode));
};

const selectedReceiptBinding = (): TemplateDataBinding | null => {
  return bindingFromSelectionReceipt(effectiveDataSelection.value, selectedExperimentId.value);
};

const currentSelectionDecision = (tpl: TemplateOut): DatasetAnalysisReadinessDecision | null => {
  if (
    effectiveDataSelection.value?.analysis_readiness_experiment_id != null &&
    effectiveDataSelection.value.analysis_readiness_experiment_id !== selectedExperimentId.value
  ) {
    return null;
  }
  return (
    (effectiveDataSelection.value?.analysis_readiness ?? activeBindingReadiness.value)?.decisions.find(
      (decision) => decision.template_slug === tpl.slug,
    ) ?? null
  );
};

const currentSelectionDecisionMessage = (tpl: TemplateOut): string | null => {
  const decision = currentSelectionDecision(tpl);
  if (decision?.status === "compatible") return null;
  const receiptBinding = selectedReceiptBinding();
  if (receiptBinding && multiSourceReceiptBindings(tpl, receiptBinding, decision)) return null;
  if (
    effectiveDataSelection.value?.datasets.length &&
    effectiveDataSelection.value.analysis_readiness_experiment_id !== selectedExperimentId.value
  ) {
    return "Compatibility has not been evaluated for this dataset. Inspect it in My Dataset before using a starter.";
  }
  if (!decision) {
    return hasCurrentData.value
      ? "Compatibility could not be established for this selection."
      : null;
  }
  const reasons = decision.reasons.map((reason) => reason.message).filter(Boolean);
  return reasons.length ? reasons.join(" ") : "This selection is not structurally ready.";
};

const requiresTargetSetup = (tpl: TemplateOut): boolean =>
  (currentSelectionDecision(tpl)?.reason_codes ?? []).some((code) =>
    ["continuous_target_missing", "categorical_target_missing", "target_missing"].includes(code),
  );

const openDatasetReadiness = async (): Promise<void> => {
  visible.value = false;
  await router.push({
    path: "/data",
    query: {
      tab: "my-dataset",
      project_id: String(workbookStore.projectId),
      ...(selectedExperimentId.value == null
        ? {}
        : { experiment: String(selectedExperimentId.value) }),
    },
  });
};

const currentTargetDataBinding = (): TemplateDataBinding | null =>
  activeProjectDataset.value || projectDatasetChoiceError.value
    ? null
    : bindingFromNode(workflowStore.nodes.find(isTargetDataSourceNode));

const selectedReceiptDataset = () =>
  effectiveDataSelection.value?.datasets.find(
    (dataset) => dataset.experiment_id === selectedExperimentId.value,
  ) ?? effectiveDataSelection.value?.datasets[0];

const templateSourceNodeIds = (tpl: TemplateOut): string[] => {
  const roles = Object.values(tpl.template_data.data_roles || {});
  const roleNodeIds = Array.from(
    new Set(
      roles
        .filter((role) => role.required !== false && role.node_binding)
        .map((role) => String(role.node_binding)),
    ),
  );
  if (roleNodeIds.length > 0) return roleNodeIds;

  return (tpl.template_data.nodes || [])
    .filter(
      (node) =>
        node.node_type === "data.file_load" &&
        !String(node.node_id || "").endsWith("__target_source"),
    )
    .map((node) => String(node.node_id))
    .filter(Boolean);
};

const separateTargetTypeForNode = (tpl: TemplateOut, nodeId: string): string | null => {
  const targetRole = Object.values(tpl.template_data.data_roles || {}).find(
    (role) =>
      role.required !== false &&
      role.binding_mode === "separate_source" &&
      String(role.node_binding || "") === nodeId,
  );
  return targetRole?.target_type || null;
};

const multiSourceReceiptBindings = (
  tpl: TemplateOut,
  primaryBinding: TemplateDataBinding,
  decision: DatasetAnalysisReadinessDecision | null,
): Record<string, TemplateDataBinding> | null => {
  const sourceNodeIds = templateSourceNodeIds(tpl);
  if (sourceNodeIds.length < 2) return null;
  const selected = selectedReceiptDataset();
  const fileIds = selected?.file_ids;
  if (
    !Array.isArray(fileIds) ||
    fileIds.length !== sourceNodeIds.length ||
    selected?.selected_file_count !== sourceNodeIds.length ||
    primaryBinding.targetAuthority ||
    primaryBinding.groupColumn
  ) {
    return null;
  }
  const reasonCodes = decision?.reason_codes ?? [];
  if (
    decision?.status !== "needs_input" ||
    reasonCodes.length === 0 ||
    reasonCodes.some((code) => code !== "additional_data_source_required")
  ) {
    return null;
  }
  return Object.fromEntries(
    sourceNodeIds.map((nodeId, index) => [
      nodeId,
      {
        ...primaryBinding,
        fileIds: [fileIds[index]],
        allFiles: false,
        targetAuthority: null,
        groupColumn: null,
      },
    ]),
  );
};

const sourceNodeLabel = (tpl: TemplateOut, nodeId: string): string => {
  const node = (tpl.template_data.nodes ?? []).find((candidate) => candidate.node_id === nodeId);
  const label = node?.label;
  return label?.trim() || nodeId;
};

const sourceFileLabel = (path: string | undefined, index: number): string => {
  const normalized = path?.trim();
  return normalized ? normalized.split("/").pop() || normalized : `selected view ${index + 1}`;
};

const multiSourceBindingSummary = (tpl: TemplateOut): string | null => {
  const primaryBinding = selectedReceiptBinding();
  const decision = currentSelectionDecision(tpl);
  if (!primaryBinding || !multiSourceReceiptBindings(tpl, primaryBinding, decision)) return null;
  const selected = selectedReceiptDataset();
  const paths = selected?.file_paths ?? [];
  return `Explicit source mapping: ${templateSourceNodeIds(tpl)
    .map(
      (nodeId, index) =>
        `${sourceFileLabel(paths[index], index)} → ${sourceNodeLabel(tpl, nodeId)}`,
    )
    .join("; ")}.`;
};

const inheritedDataBindingsForTemplate = (
  tpl: TemplateOut,
): Record<string, TemplateDataBinding> | null => {
  const receiptBinding = selectedReceiptBinding();
  const decision = receiptBinding ? currentSelectionDecision(tpl) : null;
  // A My Dataset receipt is an explicit scientific intent. Never silently
  // replace it with a template's bundled example, and never treat missing or
  // stale compatibility evidence as approval.
  if (receiptBinding && decision?.status !== "compatible") {
    return multiSourceReceiptBindings(tpl, receiptBinding, decision);
  }
  const primaryBinding = receiptBinding || currentPrimaryDataBinding();
  if (!primaryBinding) return null;
  if (!receiptBinding && currentSelectionDecision(tpl)?.status !== "compatible") return null;

  const sourceNodeIds = templateSourceNodeIds(tpl);
  if (sourceNodeIds.length !== 1) return null;

  const targetType = separateTargetTypeForNode(tpl, sourceNodeIds[0]);
  const targetBinding = targetType ? currentTargetDataBinding() : null;
  if (targetType && !targetBinding) return null;

  const binding = bindingForTemplateSource(primaryBinding, targetType, targetBinding);
  return binding ? { [sourceNodeIds[0]]: binding } : null;
};

const managedCandidateSelectionWarning = (tpl: TemplateOut): string | null => {
  if (!tpl.template_data.canonical_project) return null;
  const bindings = inheritedDataBindingsForTemplate(tpl);
  if (!bindings) return null;
  const collectionSelected = Object.values(bindings).some(
    (binding) => binding.allFiles || (binding.fileIds?.length ?? 0) > 1,
  );
  return collectionSelected
    ? "This selection starts an analysis workflow. After a successful run, choose Optimize; its exact data and fold-safe recipe will be checked there. No companion workflow is required."
    : null;
};

const hasCurrentData = computed(
  () => Boolean(effectiveDataSelection.value?.datasets.length) || currentPrimaryDataBinding() !== null,
);

const templateRuntimeReady = (tpl: TemplateOut): boolean => tpl.runtime_readiness?.ready !== false;

const templateRuntimeMessage = (tpl: TemplateOut): string | null => {
  if (templateRuntimeReady(tpl)) return null;
  const operations = (tpl.runtime_readiness?.unavailable_nodes ?? [])
    .map((node) => node.node_type)
    .filter(Boolean);
  const operationText = operations.length ? ` Required operation: ${operations.join(", ")}.` : "";
  return `This analysis is unavailable in the current server runtime.${operationText}`;
};

const canUseCurrentData = (tpl: TemplateOut): boolean =>
  !projectDatasetChoiceError.value && templateRuntimeReady(tpl) && !!inheritedDataBindingsForTemplate(tpl);

const canUseTemplate = (tpl: TemplateOut): boolean =>
  canUseCurrentData(tpl) || (templateRuntimeReady(tpl) && supportsExample(tpl));

const currentDataButtonLabel = (tpl: TemplateOut): string => {
  if (instantiating.value === tpl.id) return "Creating…";
  if (projectDatasetChoiceError.value) return "Project Dataset Unavailable";
  if (!templateRuntimeReady(tpl)) return "Unavailable";
  if (inheritedDataBindingsForTemplate(tpl)) {
    return activeProjectDataset.value
      ? "Use Project Dataset"
      : effectiveDataSelection.value
        ? "Use Current Data"
        : "Use Sheet Data";
  }
  return "Not Ready";
};

const currentDataButtonIcon = (tpl: TemplateOut): string => {
  if (projectDatasetChoiceError.value) return "pi pi-lock";
  if (!templateRuntimeReady(tpl)) return "pi pi-lock";
  if (inheritedDataBindingsForTemplate(tpl)) {
    return instantiating.value === tpl.id ? "pi pi-spin pi-spinner" : "pi pi-link";
  }
  return "pi pi-lock";
};

const currentDataButtonTitle = (tpl: TemplateOut): string => {
  if (projectDatasetChoiceError.value) return projectDatasetChoiceError.value;
  const runtimeMessage = templateRuntimeMessage(tpl);
  if (runtimeMessage) return runtimeMessage;
  if (inheritedDataBindingsForTemplate(tpl)) {
    return activeProjectDataset.value
      ? `Create a new workflow sheet using the active project dataset: ${activeProjectDataset.value.name}.`
      : effectiveDataSelection.value
        ? "Create a new workflow sheet using the selection from My Dataset."
        : "Create a new workflow sheet using the active sheet's Data Source.";
  }
  const decisionMessage = currentSelectionDecisionMessage(tpl);
  if (decisionMessage) {
    return decisionMessage;
  }
  return "This analysis starter needs compatible current data before it can be created from this selection.";
};

const exampleButtonTitle = (tpl: TemplateOut): string =>
  templateRuntimeMessage(tpl) ??
  `${exampleDataSummary(tpl) ?? "Use this starter's bundled example."} This creates a separate sheet and does not use the project's current dataset.`;

const loadTemplates = async () => {
  loading.value = true;
  loadError.value = null;
  try {
    const receipt = props.dataSelection ?? null;
    effectiveDataSelection.value = receipt;
    const profile = receipt?.analysis_readiness?.profile;
    activeBindingReadiness.value = null;
    activeProjectDataset.value = null;
    projectDatasetChoiceError.value = null;
    const [templateResponse, choiceResult] = await Promise.all([
      api.get<{ templates: TemplateOut[]; total: number }>("/workflow-templates"),
      !receipt && workbookStore.projectId != null
        ? api.get<{ dataset: ActiveProjectDataset | null }>(
            `/projects/${workbookStore.projectId}/choices/current-dataset`,
          )
            .then((response) => ({ dataset: response.data.dataset, failed: false }))
            .catch(() => ({ dataset: null, failed: true }))
        : Promise.resolve({ dataset: null, failed: false }),
    ]);
    if (choiceResult.failed) {
      projectDatasetChoiceError.value =
        "Project dataset selection could not be verified. Select data in My Dataset, then reopen Analysis Starters.";
    }
    activeProjectDataset.value = choiceResult.dataset;
    const activeBinding = receipt || projectDatasetChoiceError.value ? null : currentPrimaryDataBinding();
    const [readinessResponse, activeReadinessResponse] = await Promise.all([
      profile
        ? api
            .post<DatasetAnalysisReadiness>("/workflow-templates/compatibility-preview", {
              analysis_profile: profile,
            })
            .catch(() => undefined)
        : Promise.resolve(null),
      activeBinding && workbookStore.projectId != null
        ? api.post<DatasetAnalysisReadiness>("/workflow-templates/binding-compatibility-preview", {
              project_id: workbookStore.projectId,
              binding: {
                source: activeBinding.source ?? "experiment",
                experiment_id: activeBinding.experimentId,
                display_name: activeBinding.displayName ?? null,
                file_id: activeBinding.fileId ?? null,
                file_ids: activeBinding.fileIds ?? null,
                asset_id: activeBinding.assetId ?? null,
                all_files: activeBinding.allFiles ?? false,
                stage: activeBinding.stage ?? "raw",
                target_authority: activeBinding.targetAuthority ?? null,
                group_column: activeBinding.groupColumn ?? null,
              },
            })
            .catch(() => undefined)
        : Promise.resolve(null),
    ]);
    templates.value = templateResponse.data.templates;
    if (receipt && profile) {
      effectiveDataSelection.value = {
        ...receipt,
        analysis_readiness:
          readinessResponse === undefined
            ? null
            : (readinessResponse?.data ?? receipt.analysis_readiness),
      };
    }
    if (!receipt && activeBinding) {
      activeBindingReadiness.value = activeReadinessResponse?.data ?? null;
      selectedExperimentId.value = activeBinding.experimentId;
    }
  } catch (err) {
    loadError.value = getErrorMessage(err, "Failed to load analysis starters.");
    templates.value = [];
  } finally {
    loading.value = false;
  }
};

const maybeAutoStartPreferredTemplate = () => {
  const slug = props.preferredTemplateSlug;
  if (!visible.value || !slug || autoStartedSlug.value === slug || loading.value || projectDatasetChoiceError.value) return;
  const tpl = templates.value.find((candidate) => candidate.slug === slug);
  if (!tpl) return;
  const launchMode = canUseCurrentData(tpl)
    ? "current"
    : !hasCurrentData.value && templateRuntimeReady(tpl) && supportsExample(tpl)
      ? "example"
      : null;
  if (!launchMode) return;
  autoStartedSlug.value = slug;
  void onUse(tpl, launchMode);
};

watch(visible, (next) => {
  if (next) {
    selectedExperimentId.value = props.dataSelection?.datasets[0]?.experiment_id ?? null;
    autoStartedSlug.value = null;
    void loadTemplates();
  } else {
    activeProjectDataset.value = null;
    projectDatasetChoiceError.value = null;
  }
});

watch(
  () => [templates.value, props.preferredTemplateSlug, visible.value, loading.value] as const,
  () => maybeAutoStartPreferredTemplate(),
);

const onUse = async (tpl: TemplateOut, launchMode: "current" | "example") => {
  if (!projectAvailable.value) return;
  if (launchMode === "current" && activeProjectDataset.value && !props.dataSelection) {
    try {
      const latest = await api.get<{ dataset: ActiveProjectDataset | null }>(
        `/projects/${workbookStore.projectId}/choices/current-dataset`,
      );
      if (
        latest.data.dataset?.id !== activeProjectDataset.value.id ||
        latest.data.dataset?.digest !== activeProjectDataset.value.digest
      ) {
        throw new Error("Project dataset changed. Reopen Analysis Starters to use the new selection.");
      }
    } catch (err) {
      toast.add({
        severity: "warn",
        summary: "Project dataset needs review",
        detail: getErrorMessage(err, "Reopen Analysis Starters to verify the current dataset."),
        life: 6000,
      });
      return;
    }
  }
  const inheritedBindings = launchMode === "current" ? inheritedDataBindingsForTemplate(tpl) : null;
  if (launchMode === "current" && !inheritedBindings) {
    toast.add({
      severity: "warn",
      summary: "Current data not ready",
      detail:
        currentSelectionDecisionMessage(tpl) ??
        "Compatibility could not be established for this selection.",
      life: 5000,
    });
    return;
  }
  if (launchMode === "example" && !supportsExample(tpl)) {
    toast.add({
      severity: "info",
      summary: "Data binding required",
      detail: "This analysis starter needs your data to be bound before creation.",
      life: 3000,
    });
    return;
  }
  instantiating.value = tpl.id;
  try {
    const workflowName = `${tpl.name}`;
    const sheet = await workbookStore.openTemplateAsSheet(
      tpl.id,
      workflowName,
      launchMode === "current" && inheritedBindings
        ? {
            launchMode: "user",
            dataBindings: inheritedBindings,
          }
        : { launchMode: "example" },
    );
    emit("sheet-opened");
    const managedWarning = managedCandidateSelectionWarning(tpl);
    toast.add({
      severity: managedWarning ? "info" : "success",
      summary: "Analysis started",
      detail:
        managedWarning ??
        (inheritedBindings
          ? `"${sheet.name}" is now active and linked to the current Data Source.`
          : `"${sheet.name}" is now active with ${sheet.primaryDataSourceName || "the bundled example source"}; it is separate from current project data.`),
      life: managedWarning ? 8000 : 2500,
    });
    visible.value = false;
  } catch (err) {
    const message = getErrorMessage(err, "Could not start analysis.");
    toast.add({
      severity: "error",
      summary: "Could not start analysis",
      detail: message,
      life: 4000,
    });
  } finally {
    instantiating.value = null;
    if (autoStartedSlug.value === tpl.slug) {
      autoStartedSlug.value = null;
    }
  }
};
</script>

<style scoped>
.tp-status {
  padding: 20px 8px;
  text-align: center;
  color: #6b7280;
  font-size: 0.9rem;
}

.tp-status-error {
  color: #b91c1c;
}

.tp-status-warning {
  margin-top: 16px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 10px 12px;
  text-align: left;
}

.tp-tagline {
  margin: 0 0 12px;
  color: #4b5563;
  font-size: 0.9rem;
}

.tp-group {
  margin-bottom: 4px;
}

.tp-group-title {
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
  margin: 12px 0 6px;
}

.tp-group-count {
  font-weight: 400;
  color: #9ca3af;
  margin-left: 4px;
}

.tp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: none;
}

.tp-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 4px;
  border-bottom: 1px solid #f3f4f6;
}

.tp-row:last-child {
  border-bottom: none;
}

.tp-row-main {
  flex: 1;
  min-width: 0;
}

.tp-row-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.35rem;
  min-width: 10.75rem;
}

.tp-row-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.92rem;
  font-weight: 500;
  color: #111827;
}

.tp-needs-data {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  background: #fef3c7;
  color: #92400e;
  padding: 1px 6px;
  border-radius: 3px;
}

.tp-row-description {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: #4b5563;
  line-height: 1.4;
}

.tp-row-requirement {
  margin: 5px 0 0;
  color: #92400e;
  font-size: 0.78rem;
  line-height: 1.35;
}

.tp-row-requirement i {
  margin-right: 0.3rem;
}

.tp-group-sep {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 12px 0 0;
}
</style>
