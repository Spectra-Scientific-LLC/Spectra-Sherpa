import { validateScientificMetadata } from "@/utils/scientificMetadataValidation";
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type { NodeTypeMetadata, NodeLibraryResponse, NodeExecutionStatus } from "@/types";
import { getErrorMessage } from "@/utils/errors";
import { useProjectStore } from "@/stores/project";
import { useProjectProvenanceStore } from "@/stores/projectProvenance";
import { useAuthStore } from "@/stores/auth";
import {
  clearMatchingWorkflowDraft,
  workflowDraftKey,
  workflowDraftSignature,
} from "@/utils/workflowDraft";
import { useWorkbookStore } from "@/stores/workbook";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { newIdempotencyKey, requestScopedSingleFlightKey, singleFlight } from "@/utils/idempotency";
import {
  blobFromResponseData,
  downloadBlob,
  filenameFromContentDisposition,
} from "@/utils/download";
import type { EvidenceGap } from "@/utils/runEvidence";

// Types extracted to workflow-types.ts for module size reduction.
// Re-exported here for backward compatibility.
export type {
  TemplateDataRole,
  TemplateDataBinding,
  TemplateLaunchMode,
  TemplateExampleBinding,
  WorkflowNode,
  WorkflowEdge,
  WorkflowTemplate,
  WorkflowTemplateCatalog,
  ReferenceDatasetOption,
  DatasetCompatibilityDecision,
  DatasetCompatibilityMatrix,
  TrialExecuteResponse,
  DatasetFile,
  ExperimentDataset,
  LibraryDataset,
  AvailableDatasets,
  WorkflowListItem,
  NodeScientificValueDescriptors,
  ExecutedPresentationRecord,
} from "@/stores/workflow-types";

import type {
  ParamsMap,
  UnknownRecord,
  WorkflowNode,
  WorkflowEdge,
  WorkflowTemplate,
  WorkflowTemplateCatalog,
  ReferenceDatasetOption,
  DatasetCompatibilityDecision,
  DatasetCompatibilityMatrix,
  TypeRegistryEntry,
  TypeRegistryPayload,
  BackendWorkflowNode,
  BackendWorkflowEdge,
  WorkflowCreatePayload,
  WorkflowExecuteResponse,
  WorkflowPreflightResponse,
  TrialExecuteResponse,
  TemplateLaunchMode,
  TemplateDataBinding,
  TemplateExampleBinding,
  AvailableDatasets,
  WorkflowListItem,
  NodeScientificValueDescriptors,
  ExecutedPresentationRecord,
} from "@/stores/workflow-types";

import type { NodeExecutionState } from "@/types";

export const useWorkflowStore = defineStore("workflow", () => {
  let workflowLoadGeneration = 0;
  // State
  const nodes = ref<WorkflowNode[]>([]);
  const edges = ref<WorkflowEdge[]>([]);
  const currentTemplateId = ref<string | null>(null);
  const hasUnsavedChanges = ref(false);
  const workflowName = ref("Untitled Workflow");
  const workflowId = ref<number | null>(null);
  const workflowDescription = ref("");
  const workflowHash = ref<string | null>(null);
  const isLoading = ref(false);
  const lastExecutionResults = ref<UnknownRecord | null>(null);
  const restoredRunId = ref<number | null>(null);
  const lastExecutionParams = ref<Record<string, ParamsMap>>({});
  let executionRequestGeneration = 0;
  const restoredEvidenceNotice = ref<string | null>(null);
  const restoredEvidenceGaps = ref<EvidenceGap[]>([]);
  const executionEvidenceScope = ref<"live_full" | "partial" | "restored_summary" | "unavailable">("unavailable");
  const lastExecutionDiagnostics = ref<Record<string, UnknownRecord>>({});
  const lastExecutionResultDescriptors = ref<Record<string, NodeScientificValueDescriptors>>({});
  const lastExecutionPresentations = ref<Record<string, ExecutedPresentationRecord>>({});
  const workflowWarnings = ref<string[]>([]);
  async function recordActiveWorkflowChoice(projectId: number | null | undefined, id: number): Promise<void> {
    if (projectId == null || projectId !== useProjectStore().currentProjectId) return;
    try {
      await api.post(`/projects/${projectId}/choices`, { kind: "workflow", workflow_id: id });
      await useProjectProvenanceStore().refresh(projectId);
    } catch (error) {
      workflowWarnings.value = [
        ...workflowWarnings.value,
        `The sheet is available, but its active project choice was not recorded: ${getErrorMessage(error, "Try opening the sheet again.")}`,
      ];
    }
  }
  const hasFoldValidationPlan = ref(false);
  // A persisted workflow's canonical admission status. Local edge validation
  // remains an editing cue for unsaved canvas changes only; save/load replaces
  // it with this server-produced result.
  const workflowPreflight = ref<WorkflowPreflightResponse | null>(null);
  const availableDatasets = ref<AvailableDatasets | null>(null);
  const templates = ref<WorkflowTemplate[]>([]);
  const templatesLoading = ref(false);
  const templatesError = ref<string | null>(null);
  const compatibilityMatrix = ref<DatasetCompatibilityMatrix | null>(null);
  const compatibilityLoading = ref(false);
  const compatibilityError = ref<string | null>(null);

  // Node library metadata (validation schemas, parameters, etc.)
  const nodeLibrary = ref<Map<string, NodeTypeMetadata>>(new Map());
  const isLoadingNodeLibrary = ref(false);
  const nodeLibraryLoadError = ref<string | null>(null);
  const nodeLibraryVersion = ref<string | null>(null); // Track backend version for cache invalidation
  // Contract/readiness changes need their own cache key: application version
  // alone cannot tell a client that a node's executable identity changed.
  const nodeLibraryCacheIdentity = ref<string | null>(null);
  const typeRegistry = ref<TypeRegistryPayload | null>(null);
  const isLoadingTypeRegistry = ref(false);
  const typeRegistryLoadError = ref<string | null>(null);

  // Workflow has been modified since last execution (stale state)
  const isWorkflowStale = ref(false);

  // Getters
  const nodeCount = computed(() => nodes.value.length);
  const edgeCount = computed(() => edges.value.length);
  const availableTemplates = computed(() => templates.value);

  const normalizeBackendExecutionStatus = (status: unknown): NodeExecutionStatus | null => {
    if (typeof status !== "string") {
      return null;
    }
    const normalized = status.toLowerCase();
    if (
      normalized === "completed" ||
      normalized === "complete" ||
      normalized === "success" ||
      normalized === "succeeded" ||
      normalized === "done" ||
      normalized === "finished"
    ) {
      return "completed";
    }
    if (normalized === "error" || normalized === "failed" || normalized === "failure") {
      return "error";
    }
    if (normalized === "running" || normalized === "in_progress" || normalized === "processing") {
      return "running";
    }
    if (normalized === "pending" || normalized === "queued") {
      return "pending";
    }
    return null;
  };

  /**
   * Derive output shape and type from a serialized node result.
   * Shared between executeWorkflow (live run) and loadWorkflow (restore).
   */
  const deriveShapeAndType = (
    result: unknown,
    descriptors?: NodeScientificValueDescriptors | null,
    presentation?: ExecutedPresentationRecord | null,
  ): {
    output_shape: number[] | null;
    output_shape_label: string | null;
    output_type: string | null;
  } => {
    let output_shape: number[] | null = null;
    let output_shape_label: string | null = null;
    let output_type: string | null = null;

    const descriptorValues = Object.values(descriptors ?? {});
    const defaultDescriptor = descriptors?.default;
    const defaultPresentation = presentation?.contract.presentations.find(
      (candidate) => candidate.presentation_id === presentation.contract.default_presentation,
    );
    const presentedDescriptor = defaultPresentation?.source_ports
      .map((portName) => descriptors?.[portName])
      .find((candidate) => candidate?.shape_valid && candidate.shape !== null);
    const descriptor =
      presentedDescriptor ??
      (defaultDescriptor?.shape_valid && defaultDescriptor.shape ? defaultDescriptor : null) ??
      descriptorValues.find((candidate) => candidate.shape_valid && candidate.shape !== null) ??
      defaultDescriptor ??
      descriptorValues[0];
    if (descriptor) {
      return {
        output_shape: descriptor.shape,
        output_shape_label:
          descriptor === presentedDescriptor && defaultPresentation
            ? defaultPresentation.label
            : descriptor.label,
        output_type: descriptor.scientific_kind,
      };
    }

    if (!result || typeof result !== "object") {
      return { output_shape, output_shape_label, output_type };
    }

    const resultRec = result as Record<string, unknown>;
    // Multi-port node: look inside `default` first, then fall back to the top-level result.
    const primaryRaw = "default" in resultRec ? resultRec.default : resultRec;
    if (!primaryRaw || typeof primaryRaw !== "object") {
      return { output_shape, output_shape_label, output_type };
    }
    const primary = primaryRaw as Record<string, unknown>;

    if (typeof primary.type === "string") {
      output_type = primary.type;
      output_shape_label = primary.type;
    }
    if (Array.isArray(primary.shape)) {
      output_shape = primary.shape as number[];
    }
    // SherpaDataset exposes n_samples/n_features at the top of the serialized dict.
    if (typeof primary.n_samples === "number" && typeof primary.n_features === "number") {
      output_shape = [primary.n_samples, primary.n_features];
    }
    return { output_shape, output_shape_label, output_type };
  };

  const markScopedExecutionFailure = (message: string): void => {
    const failed = nodes.value.find((node) =>
      message.startsWith(`${node.id}:`) || message.includes(` ${node.id}:`),
    );
    const downstream = new Set<string>();
    if (failed) {
      const queue = [failed.id];
      while (queue.length) {
        const current = queue.shift()!;
        for (const edge of edges.value) {
          if (edge.from === current && !downstream.has(edge.to)) {
            downstream.add(edge.to);
            queue.push(edge.to);
          }
        }
      }
    }
    for (const node of nodes.value) {
      if (node.id === failed?.id) {
        setNodeExecutionState(node.id, {
          status: "error",
          error_message: message,
          error_details: message,
        });
      } else if (downstream.has(node.id)) {
        setNodeExecutionState(node.id, {
          status: "pending",
          error_message: `Not run because upstream node ${failed?.id ?? ""} failed.`,
          error_details: null,
        });
      } else {
        setNodeExecutionState(node.id, {
          status: "pending",
          error_message: null,
          error_details: null,
        });
      }
    }
  };

  // The executor marks a failed node and every skipped descendant as
  // `error` in its compact status map. Reconstruct the causal boundary for
  // the canvas so one optional-node failure does not turn the whole graph red.
  const executionFailureRoots = (statusMap: Record<string, unknown>): Map<string, string> => {
    const errorIds = new Set(
      nodes.value
        .filter((node) => normalizeBackendExecutionStatus(statusMap[node.id]) === "error")
        .map((node) => node.id),
    );
    const roots = Array.from(errorIds).filter(
      (nodeId) => !edges.value.some((edge) => edge.to === nodeId && errorIds.has(edge.from)),
    );
    const rootByNode = new Map<string, string>();
    for (const root of roots.length > 0 ? roots : Array.from(errorIds).slice(0, 1)) {
      const queue = [root];
      while (queue.length > 0) {
        const current = queue.shift()!;
        if (rootByNode.has(current)) continue;
        rootByNode.set(current, root);
        for (const edge of edges.value) {
          if (edge.from === current && errorIds.has(edge.to)) queue.push(edge.to);
        }
      }
    }
    return rootByNode;
  };

  const parseTypeRef = (typeRef: string): { name: string; major: number; minor: number } | null => {
    const match = typeRef.match(
      /^spectrasherpa:\/\/types\/(?<name>[A-Za-z0-9_]+)\/(?<major>\d+)\.(?<minor>\d+)$/,
    );
    if (!match?.groups) {
      return null;
    }
    return {
      name: match.groups.name,
      major: Number.parseInt(match.groups.major, 10),
      minor: Number.parseInt(match.groups.minor, 10),
    };
  };

  const typeRefToDisplayName = (typeRef: string): string => {
    const parsed = parseTypeRef(typeRef);
    if (!parsed) return typeRef;
    return parsed.name;
  };

  /** Derive visual category (dataset, model, target, ...) from a type_ref URI. */
  const getCategoryFromTypeRef = (typeRef: string): string => {
    const parsed = parseTypeRef(typeRef);
    if (!parsed) return "dataset";
    const registry = typeRegistry.value;
    if (registry?.types?.[parsed.name]?.category) {
      return registry.types[parsed.name].category;
    }
    return "dataset";
  };

  const isSubtypeName = (childName: string, parentName: string): boolean => {
    const fallbackSubtypeMap: Record<string, string | null> = {
      Spectrum: "Array1D",
      SpectralDataset: "Array2D",
      ScoreMatrix: "Array2D",
      LoadingMatrix: "Array2D",
    };

    const registry = typeRegistry.value;
    if (!registry) {
      let current: string | null = childName;
      const seen = new Set<string>();
      while (current && !seen.has(current)) {
        seen.add(current);
        if (current === parentName) return childName !== parentName;
        current = fallbackSubtypeMap[current] ?? null;
      }
      return false;
    }

    const seen = new Set<string>();
    let currentName: string | null = childName;

    while (currentName && !seen.has(currentName)) {
      seen.add(currentName);
      if (currentName === parentName) {
        return childName !== parentName;
      }
      const currentEntry: TypeRegistryEntry | undefined = registry.types[currentName];
      currentName = currentEntry?.parent ?? null;
    }
    return false;
  };

  const validateTypeRefs = (
    sourceTypeRef: string,
    targetTypeRef: string,
  ): { isValid: boolean; error?: string; dataType?: string } => {
    const source = parseTypeRef(sourceTypeRef);
    const target = parseTypeRef(targetTypeRef);

    if (!source) {
      return {
        isValid: false,
        error: `Malformed source type_ref: ${sourceTypeRef}`,
      };
    }
    if (!target) {
      return {
        isValid: false,
        error: `Malformed target type_ref: ${targetTypeRef}`,
      };
    }

    // Any wildcard: any source type can connect to Any target
    if (target.name === "Any") {
      return { isValid: true, dataType: `${source.name}@${source.major}.${source.minor}` };
    }

    if (source.name === target.name) {
      if (source.major === target.major) {
        return {
          isValid: true,
          dataType: `${source.name}@${source.major}.${source.minor}`,
        };
      }
      return {
        isValid: false,
        error: `Version mismatch: ${typeRefToDisplayName(sourceTypeRef)} cannot connect to ${typeRefToDisplayName(targetTypeRef)} (major version differs)`,
        dataType: source.name,
      };
    }

    // Subtype compatibility (child output to parent input).
    if (isSubtypeName(source.name, target.name)) {
      return {
        isValid: true,
        dataType: source.name,
      };
    }

    return {
      isValid: false,
      error: `Type mismatch: ${typeRefToDisplayName(sourceTypeRef)} cannot connect to ${typeRefToDisplayName(targetTypeRef)}`,
      dataType: source.name,
    };
  };

  // Helper: Convert frontend nodes/edges to backend format
  function toBackendFormat(): { nodes: BackendWorkflowNode[]; edges: BackendWorkflowEdge[] } {
    const backendNodes: BackendWorkflowNode[] = nodes.value.map((n) => ({
      node_id: n.id,
      node_type: n.type,
      label: n.label && n.label !== n.type ? n.label : getNodeMetadata(n.type)?.label || n.type,
      parameters: n.params,
      position_x: n.x,
      position_y: n.y,
    }));

    const backendEdges: BackendWorkflowEdge[] = edges.value.map((e) => ({
      from_node_id: e.from,
      to_node_id: e.to,
      from_output: e.fromPort || "default",
      to_input: e.toPort || "default",
    }));

    return { nodes: backendNodes, edges: backendEdges };
  }

  // Helper: Convert backend format to frontend nodes/edges
  function fromBackendFormat(
    backendNodes: BackendWorkflowNode[],
    backendEdges: BackendWorkflowEdge[],
  ): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
    const frontendNodes: WorkflowNode[] = backendNodes.map((n) => {
      const frontendType = n.node_type;
      return {
        id: n.node_id,
        type: frontendType,
        label: n.label && n.label !== frontendType ? n.label : getNodeMetadata(frontendType)?.label || undefined,
        x: n.position_x || 100,
        y: n.position_y || 100,
        params: { ...(n.parameters || {}) },
      };
    });

    const frontendEdges: WorkflowEdge[] = backendEdges.map((e) => ({
      from: e.from_node_id,
      to: e.to_node_id,
      // Preserve explicit "default" ports from the backend so multi-input or
      // multi-output nodes that genuinely expose a "default" port remain valid.
      fromPort: e.from_output || undefined,
      toPort: e.to_input || undefined,
    }));

    return { nodes: frontendNodes, edges: frontendEdges };
  }

  // Actions
  function loadTemplate(templateId: number) {
    const template = templates.value.find((item) => item.id === templateId);
    if (!template) {
      console.warn(`Template not found: ${templateId}`);
      return false;
    }

    const converted = fromBackendFormat(
      template.template_data.nodes || [],
      template.template_data.edges || [],
    );
    nodes.value = converted.nodes;
    edges.value = converted.edges;
    validateAllEdges();
    currentTemplateId.value = String(templateId);
    workflowName.value = template.name;
    workflowDescription.value = template.description;
    hasUnsavedChanges.value = false;

    return true;
  }

  function clearWorkflow() {
    workflowLoadGeneration += 1;
    nodes.value = [];
    edges.value = [];
    currentTemplateId.value = null;
    workflowName.value = "Untitled Workflow";
    workflowId.value = null;
    workflowDescription.value = "";
    workflowHash.value = null;
    hasUnsavedChanges.value = false;
    lastExecutionResults.value = null;
    restoredRunId.value = null;
    lastExecutionParams.value = {};
    executionEvidenceScope.value = "unavailable";
    restoredEvidenceNotice.value = null;
    restoredEvidenceGaps.value = [];
    lastExecutionDiagnostics.value = {};
    lastExecutionResultDescriptors.value = {};
    lastExecutionPresentations.value = {};
    workflowWarnings.value = [];
    hasFoldValidationPlan.value = false;
    workflowPreflight.value = null;
  }

  function applyPersistedPreflight(preflight: WorkflowPreflightResponse) {
    workflowPreflight.value = preflight;
    const byEdge = new Map(
      preflight.semantic_edges.map((edge) => [
        `${edge.from_node_id}\u0000${edge.from_output}\u0000${edge.to_node_id}\u0000${edge.to_input}`,
        edge,
      ]),
    );
    for (const edge of edges.value) {
      // Persisted edges store port identities, not presentation labels. Restore
      // the source type without replacing the authoritative server validity.
      const sourceNode = nodes.value.find((node) => node.id === edge.from);
      const sourceMetadata = sourceNode ? getNodeMetadata(sourceNode.type) : undefined;
      const ports = sourceMetadata?.output_ports || [];
      const port = !edge.fromPort || edge.fromPort === "default"
        ? ports.find((item) => item.name === "default") || ports[0]
        : ports.find((item) => item.name === edge.fromPort);
      const sourceType = port?.type_ref ? parseTypeRef(port.type_ref) : null;
      edge.dataType = sourceType
        ? `${sourceType.name}@${sourceType.major}.${sourceType.minor}`
        : port?.type_ref || (ports.length === 0 ? sourceMetadata?.output_type : null) || null;
      const outcome = byEdge.get(
        `${edge.from}\u0000${edge.fromPort || "default"}\u0000${edge.to}\u0000${edge.toPort || "default"}`,
      );
      edge.isValid = outcome?.status === "typed_valid";
      edge.validationError = outcome
        ? outcome.status === "typed_valid"
          ? null
          : outcome.reason || outcome.status
        : "The authoritative preflight did not report this persisted edge.";
    }
    const messages = preflight.issues.map((issue) => issue.message);
    workflowWarnings.value = Array.from(new Set([...workflowWarnings.value, ...messages]));
  }

  async function refreshPersistedPreflight(): Promise<WorkflowPreflightResponse | null> {
    const id = workflowId.value;
    if (id === null) return null;
    const response = await api.post<WorkflowPreflightResponse>(`/workflows/${id}/preflight`);
    // Do not let a slow response overwrite a newly loaded workflow.
    if (workflowId.value === id) applyPersistedPreflight(response.data);
    return response.data;
  }

  // API Methods
  let pendingSave: Promise<number> | null = null;

  async function saveWorkflow(
    options: { createVersion?: boolean; projectId?: number | null } = {},
  ): Promise<number> {
    const previous = pendingSave;
    const generation = workflowLoadGeneration;
    const next = (async () => {
      if (previous) await previous;
      if (generation !== workflowLoadGeneration) {
        throw new Error("Active workflow changed before saving. Retry on the current sheet.");
      }
      return performSaveWorkflow(options);
    })();
    pendingSave = next;
    try {
      return await next;
    } finally {
      if (pendingSave === next) pendingSave = null;
    }
  }

  async function performSaveWorkflow(
    options: { createVersion?: boolean; projectId?: number | null } = {},
  ): Promise<number> {
    isLoading.value = true;
    try {
      const { nodes: backendNodes, edges: backendEdges } = toBackendFormat();
      const savedSignature = workflowDraftSignature({
        workflowName: workflowName.value,
        workflowDescription: workflowDescription.value,
        nodes: nodes.value,
        edges: edges.value,
      });
      const draftProjectId = options.projectId ?? useProjectStore().currentProjectId;
      const draftUserId = useAuthStore().user?.id;
      const clearSavedDraft = (id: number) => {
        if (draftProjectId != null) {
          clearMatchingWorkflowDraft(
            workflowDraftKey(draftUserId, draftProjectId, id),
            savedSignature,
          );
        }
      };
      const hasNewerEdits = () =>
        workflowDraftSignature({
          workflowName: workflowName.value,
          workflowDescription: workflowDescription.value,
          nodes: nodes.value,
          edges: edges.value,
        }) !== savedSignature;
      const createVersion = options.createVersion ?? true;

      if (workflowId.value) {
        // Update existing workflow
        const response = await api.put(`/workflows/${workflowId.value}`, {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          create_version: createVersion,
          nodes: backendNodes,
          edges: backendEdges,
        });
        workflowHash.value = response.data.integrity_hash || null;
        clearSavedDraft(response.data.id);
        hasUnsavedChanges.value = hasNewerEdits();
        await refreshPersistedPreflight();
        await recordActiveWorkflowChoice(draftProjectId, response.data.id);
        return response.data.id;
      } else {
        // Create new workflow. Require a project context — without one the
        // workflow lands with project_id=null, becomes invisible in every
        // project view, and effectively orphans the user's work. We resolve
        // the project at call time (caller may pass an explicit one;
        // otherwise the active project store wins) and fail loudly when
        // neither is available, rather than silently creating an orphan.
        const projectId = options.projectId ?? useProjectStore().currentProjectId;
        if (projectId === null || projectId === undefined) {
          throw new Error(
            "Cannot save a new workflow without an active project. " +
              "Select or create a project before saving.",
          );
        }
        const payload: WorkflowCreatePayload = {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          project_id: projectId,
          nodes: backendNodes,
          edges: backendEdges,
        };
        const response = await api.post("/workflows", payload);
        workflowId.value = response.data.id;
        workflowHash.value = response.data.integrity_hash || null;
        clearSavedDraft(response.data.id);
        hasUnsavedChanges.value = hasNewerEdits();
        await refreshPersistedPreflight();
        await recordActiveWorkflowChoice(projectId, response.data.id);
        return response.data.id;
      }
    } finally {
      isLoading.value = false;
    }
  }

  async function loadWorkflow(id: number, retainedRunId?: number): Promise<void> {
    const loadGeneration = ++workflowLoadGeneration;
    isLoading.value = true;
    try {
      // Ensure the node library and type registry are loaded BEFORE we
      // validate the workflow's edges. Otherwise validateAllEdges runs
      // with an empty library, every edge resolves to "metadata missing"
      // and turns red in the canvas. This race is visible after a
      // frontend container rebuild: the initial fetchNodeLibrary in
      // main.ts is still in flight when the workflow auto-loads.
      if (nodeLibrary.value.size === 0) {
        await fetchNodeLibrary();
      } else if (!typeRegistry.value) {
        await fetchTypeRegistry();
      }
      if (loadGeneration !== workflowLoadGeneration) return;

      const response = await api.get(`/workflows/${id}`);
      if (loadGeneration !== workflowLoadGeneration) return;
      const data = response.data;

      workflowId.value = data.id;
      workflowName.value = data.name;
      workflowDescription.value = data.description || "";
      workflowHash.value = data.integrity_hash || null;
      workflowWarnings.value = Array.isArray(data.warnings)
        ? data.warnings.filter((w: unknown): w is string => typeof w === "string")
        : [];
      hasFoldValidationPlan.value = data.fold_validation_plan != null;

      const converted = fromBackendFormat(data.nodes || [], data.edges || []);
      nodes.value = converted.nodes;
      edges.value = converted.edges;
      await refreshPersistedPreflight();

      currentTemplateId.value = null;
      hasUnsavedChanges.value = false;
      lastExecutionResults.value = null;
      restoredRunId.value = null;
      lastExecutionParams.value = {};
      executionEvidenceScope.value = "unavailable";
      restoredEvidenceNotice.value = null;
      restoredEvidenceGaps.value = [];
      lastExecutionDiagnostics.value = {};
      lastExecutionResultDescriptors.value = {};
      lastExecutionPresentations.value = {};
      isWorkflowStale.value = false;

      // Load latest auto-saved execution results (survives page refresh)
      try {
        const runResp = await api.get(`/workflows/${id}/runs/${retainedRunId ?? "latest"}`);
        if (retainedRunId != null && runResp.data?.id !== retainedRunId) {
          throw new Error("Requested run identity is unavailable");
        }
        if (loadGeneration !== workflowLoadGeneration) return;
        if (runResp.data) {
          restoredRunId.value = Number.isInteger(runResp.data.id) ? runResp.data.id : null;
          lastExecutionParams.value = runResp.data.params_snapshot ?? {};
          executionEvidenceScope.value = "restored_summary";
          const evidence = runResp.data.evidence_completeness;
          restoredEvidenceGaps.value = Array.isArray(runResp.data.evidence_gaps)
            ? runResp.data.evidence_gaps
            : [];
          restoredEvidenceNotice.value = evidence?.qualification !== 'qualified'
            ? 'Restored summary. Historical evidence completeness is unverified.'
            : restoredEvidenceGaps.value.length
              ? `Restored summary. ${restoredEvidenceGaps.value.length} retained outputs are incomplete.`
              : 'Restored summary. Full retained results are available in the saved run.';
          lastExecutionResults.value = runResp.data.results_summary;
          lastExecutionDiagnostics.value = runResp.data.diagnostics || {};
          lastExecutionResultDescriptors.value = runResp.data.diagnostics?._scientific_values ?? {};
          lastExecutionPresentations.value =
            runResp.data.diagnostics?._scientific_presentations ?? {};

          // Restore node execution states from the persisted run.
          // CRITICAL: also restore output_shape / output_type so that after a
          // page refresh, buildSyncPayload() can still report shapes to Sherpa
          // (otherwise the LLM hallucinates dimensions from common datasets).
          const savedStatuses = runResp.data.node_statuses || {};
          const savedResults = runResp.data.results_summary || {};
          for (const node of nodes.value) {
            const status = normalizeBackendExecutionStatus(savedStatuses[node.id]);
            const result = savedResults[node.id];
            const hasResult = result !== undefined;
            if (status === "completed" || (status === null && hasResult)) {
              const { output_shape, output_shape_label, output_type } = deriveShapeAndType(
                result,
                lastExecutionResultDescriptors.value[node.id],
                lastExecutionPresentations.value[node.id],
              );
              setNodeExecutionState(node.id, {
                status: "completed",
                last_executed: runResp.data.executed_at || null,
                output_shape,
                output_shape_label,
                output_type,
              });
            } else if (status === "error") {
              setNodeExecutionState(node.id, {
                status: "error",
                error_message: runResp.data.error || null,
              });
            }
          }

          const staleSinceLastExecution = Boolean(
            !data.integrity_hash ||
            !runResp.data.integrity_hash ||
            data.integrity_hash !== runResp.data.integrity_hash,
          );
          isWorkflowStale.value = staleSinceLastExecution;

          // Warn if workflow changed since last execution.
          if (staleSinceLastExecution) {
            workflowWarnings.value = [
              ...workflowWarnings.value,
              "Current graph and retained run identity are different or unverified — results may be stale.",
            ];
          }
        }
      } catch {
        // Missing requested evidence must not silently become another run.
        if (retainedRunId != null) {
          restoredEvidenceNotice.value = `Requested run ${retainedRunId} is unavailable; no substitute result was loaded.`;
        }
        // No latest run — OK, nothing to restore
      }
      if (loadGeneration === workflowLoadGeneration && data.purpose === "analysis" &&
          data.project_id != null && data.project_id === useProjectStore().currentProjectId) {
        await recordActiveWorkflowChoice(data.project_id, data.id);
      }
    } finally {
      if (loadGeneration === workflowLoadGeneration) {
        isLoading.value = false;
      }
    }
  }

  registerProjectScopeReset(clearWorkflow);

  async function listWorkflows(
    projectId: number | null = useProjectStore().currentProjectId,
  ): Promise<WorkflowListItem[]> {
    const params = projectId != null ? { project_id: projectId } : undefined;
    const response = await api.get<WorkflowListItem[]>("/workflows", { params });
    return response.data;
  }

  async function duplicateWorkflow(id: number): Promise<WorkflowListItem> {
    const response = await api.post<WorkflowListItem>(`/workflows/${id}/duplicate`);
    return response.data;
  }

  async function fetchTemplates(
    category?: string,
    includeWip: boolean = false,
  ): Promise<WorkflowTemplate[]> {
    templatesLoading.value = true;
    templatesError.value = null;
    try {
      const response = await api.get<WorkflowTemplateCatalog>("/workflow-templates", {
        params: {
          ...(category ? { category } : {}),
          ...(includeWip ? { include_wip: true } : {}),
        },
      });
      const fetched = response.data.templates;
      templates.value = fetched;
      return templates.value;
    } catch (error: unknown) {
      templatesError.value = getErrorMessage(error, "Failed to load analysis starters");
      throw error;
    } finally {
      templatesLoading.value = false;
    }
  }

  async function fetchCompatibilityMatrix(
    force: boolean = false,
  ): Promise<DatasetCompatibilityMatrix> {
    if (compatibilityMatrix.value && !force) return compatibilityMatrix.value;
    compatibilityLoading.value = true;
    compatibilityError.value = null;
    try {
      const response = await api.get<DatasetCompatibilityMatrix>(
        "/workflow-templates/compatibility-matrix",
      );
      compatibilityMatrix.value = response.data;
      return response.data;
    } catch (error: unknown) {
      compatibilityError.value = getErrorMessage(error, "Could not load analysis compatibility");
      throw error;
    } finally {
      compatibilityLoading.value = false;
    }
  }

  function compatibilityDecision(
    datasetId: string,
    templateSlug: string,
  ): DatasetCompatibilityDecision | null {
    return (
      compatibilityMatrix.value?.matrix.find(
        (decision) => decision.dataset_id === datasetId && decision.template_slug === templateSlug,
      ) || null
    );
  }

  function compatibleAnalysisCount(datasetId: string): number {
    return (
      compatibilityMatrix.value?.matrix.filter(
        (decision) => decision.dataset_id === datasetId && decision.status === "compatible",
      ).length || 0
    );
  }

  async function fetchTemplate(templateId: number): Promise<WorkflowTemplate> {
    const response = await api.get<WorkflowTemplate>(`/workflow-templates/${templateId}`);
    // Update the cached copy in the templates list too
    const idx = templates.value.findIndex((t) => t.id === templateId);
    if (idx >= 0) {
      templates.value[idx] = response.data;
    }
    return response.data;
  }

  async function instantiateTemplate(
    templateId: number,
    payload: {
      workflowName: string;
      workflowDescription?: string;
      projectId?: number | null;
      launchMode?: TemplateLaunchMode;
      dataBindings?: Record<string, TemplateDataBinding>;
      exampleBindings?: Record<string, TemplateExampleBinding>;
    },
  ): Promise<{ workflowId: number; projectId: number | null; slug: string }> {
    const response = await api.post(`/workflow-templates/${templateId}/instantiate`, {
      workflow_name: payload.workflowName,
      workflow_description: payload.workflowDescription,
      project_id: payload.projectId ?? null,
      launch_mode: payload.launchMode ?? "user",
      data_bindings: Object.fromEntries(
        Object.entries(payload.dataBindings || {}).map(([key, binding]) => [
          key,
          {
            source: binding.source ?? "experiment",
            experiment_id: binding.experimentId,
            display_name: binding.displayName ?? null,
            file_id: binding.fileId ?? null,
            file_ids: binding.fileIds ?? null,
            all_files: binding.allFiles ?? false,
            asset_id: binding.assetId ?? null,
            target_authority: binding.targetAuthority ?? null,
            group_column: binding.groupColumn ?? null,
            stage: binding.stage ?? "raw",
            target_binding: binding.targetBinding
              ? {
                  source: binding.targetBinding.source ?? "experiment",
                  experiment_id: binding.targetBinding.experimentId,
                  display_name: binding.targetBinding.displayName ?? null,
                  file_id: binding.targetBinding.fileId,
                  asset_id: binding.targetBinding.assetId ?? null,
                  stage: binding.targetBinding.stage ?? "raw",
                  target_authority: binding.targetBinding.targetAuthority ?? null,
                }
              : null,
          },
        ]),
      ),
      example_bindings: Object.fromEntries(
        Object.entries(payload.exampleBindings || {}).map(([key, binding]) => [
          key,
          {
            source: binding.source,
            dataset_name: binding.datasetName,
            selected_target: binding.selectedTarget ?? null,
            target_type: binding.targetType ?? null,
          },
        ]),
      ),
    });

    return {
      workflowId: response.data.id,
      projectId: response.data.project_id ?? null,
      slug: response.data.source_template_slug || String(templateId),
    };
  }

  async function deleteWorkflow(id: number): Promise<void> {
    await api.delete(`/workflows/${id}`);
    if (workflowId.value === id) {
      clearWorkflow();
    }
  }

  // Check numeric drafts at every execution entry point, including upstream
  // dependencies and trial overrides. A disabled Inspector button is not a gate.
  function assertNumericExecutionInputs(
    targetNodeId?: string, trialParams?: ParamsMap,
    executionNodes: WorkflowNode[] = nodes.value, executionEdges: WorkflowEdge[] = edges.value,
  ): void {
    const included = new Set<string>();
    const visit = (id: string) => {
      if (included.has(id)) return;
      included.add(id);
      for (const edge of executionEdges) if (edge.to === id) visit(edge.from);
    };
    if (targetNodeId) visit(targetNodeId);
    else for (const node of executionNodes) included.add(node.id);
    for (const node of executionNodes) {
      if (!included.has(node.id)) continue;
      const params = node.id === targetNodeId && trialParams
        ? trialParams : node.params;
      const metadata = getNodeMetadata(node.type);
      const numericNames = new Set(metadata?.parameters
        .filter((parameter) => parameter.param_type === "number")
        .map((parameter) => parameter.name));
      const errors = metadata
        ? validateNodeParams(node.type, params).filter((error) =>
          numericNames.has(error.param_name) || error.param_name.startsWith("metadata."))
        : validateScientificMetadata(params.metadata);
      if (errors.length) {
        throw new Error(`${node.label || node.id}: ${errors.map((error) => error.message).join("; ")}`);
      }
    }
  }

  const isExecuting = ref(false);
  async function withExecutionOwnership(action: () => Promise<WorkflowExecuteResponse>) {
    if (isExecuting.value) throw new Error("An execution is already in progress. Wait for it to finish.");
    isExecuting.value = true;
    const ownershipGeneration = workflowLoadGeneration;
    // A new attempt owns the surface. Older evidence stays accessible through History.
    lastExecutionResults.value = null;
    lastExecutionDiagnostics.value = {};
    lastExecutionResultDescriptors.value = {};
    lastExecutionPresentations.value = {};
    lastExecutionParams.value = {};
    executionEvidenceScope.value = "unavailable";
    restoredRunId.value = null;
    restoredEvidenceNotice.value = "Execution pending. Prior run evidence is available in History.";
    restoredEvidenceGaps.value = [];
    markWorkflowStale();
    try { return await action(); }
    catch (error) {
      if (ownershipGeneration !== workflowLoadGeneration) throw new DOMException("Execution belongs to a previously active workflow.", "AbortError");
      if (ownershipGeneration === workflowLoadGeneration) restoredEvidenceNotice.value = "Execution did not finish. No current execution evidence is available; inspect History or rerun.";
      throw error;
    } finally { isExecuting.value = false; }
  }
  async function executeWorkflow(initialData?: ParamsMap): Promise<WorkflowExecuteResponse> {
    return withExecutionOwnership(() => executeWorkflowSnapshot(initialData));
  }
  async function executeNode(nodeId: string, initialData?: ParamsMap): Promise<WorkflowExecuteResponse> {
    return withExecutionOwnership(() => executeNodeSnapshot(nodeId, initialData));
  }

  async function executeWorkflowSnapshot(initialData?: ParamsMap): Promise<WorkflowExecuteResponse> {
    const activeSheet = useWorkbookStore().activeSheet;
    if (activeSheet?.purpose === "managed_candidate_authority") {
      throw new Error(
        "Managed candidate authority workflows may only be executed by the governed Harness",
      );
    }
    assertNumericExecutionInputs();
    const preparingGeneration = workflowLoadGeneration;
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }

    if (hasUnsavedChanges.value || preparingGeneration !== workflowLoadGeneration) {
      throw new Error("The workflow changed while saving. Review the current draft and run again.");
    }
    const executingWorkflowId = workflowId.value;
    const executingLoadGeneration = workflowLoadGeneration;
    const executionGeneration = ++executionRequestGeneration;
    const executedGraph = canonicalWorkflowForStaleCheck(nodes.value);

    // Mark all nodes as queued before execution
    for (const node of nodes.value) {
      setNodeExecutionState(node.id, { status: "pending" });
    }

    isLoading.value = true;

    // Workflow-only WebSocket statuses cannot identify the producing attempt.
    // Display provisional local state until the exact HTTP execution snapshot arrives.

    const workbookStore = useWorkbookStore();
    const sheet = workbookStore.sheets.find((s) => s.workflowId === executingWorkflowId);
    // Trial tabs are passive views of a source workflow — mirror the
    // source's run state onto every trial sheet pointing at it so the
    // tab dots stay honest while another tab triggers the execution.
    const trialMirrors = workbookStore.sheets.filter(
      (s) => s.kind === "trial" && s.sourceWorkflowId === executingWorkflowId,
    );
    const allMirroredSheets = sheet ? [sheet, ...trialMirrors] : trialMirrors;
    const setMirroredStatus = (status: "idle" | "running" | "success" | "error") => {
      for (const s of allMirroredSheets) s.executionStatus = status;
    };
    const scheduleStatusClear = (terminal: "success" | "error") => {
      setTimeout(() => {
        for (const s of allMirroredSheets) {
          if (s.executionStatus === terminal) s.executionStatus = "idle";
        }
      }, 3000);
    };

    setMirroredStatus("running");

    try {
      // REM-4: every execute carries a fresh Idempotency-Key so a network
      // blip that drops the response is replayed server-side instead of
      // creating a second ExecutionRun. singleFlight coalesces rapid
      // double-clicks BEFORE the network call leaves the browser.
      const requestPayload = { initial_data: initialData || {}, expected_definition: toBackendFormat() };
      const response = await singleFlight(
        requestScopedSingleFlightKey(`execute:${executingWorkflowId}`, requestPayload),
        () =>
          api.post(`/workflows/${executingWorkflowId}/execute`, requestPayload, {
            headers: { "Idempotency-Key": newIdempotencyKey() },
          }),
      );

      const isStillActiveWorkflow = workflowId.value === executingWorkflowId && executingLoadGeneration === workflowLoadGeneration && executionGeneration === executionRequestGeneration;
      if (!isStillActiveWorkflow) {
        setMirroredStatus("success");
        scheduleStatusClear("success");
        throw new DOMException("Execution belongs to a previously active workflow.", "AbortError");
      }

      // Store results and integrity hash
      lastExecutionResults.value = response.data.results;
      restoredRunId.value = Number.isInteger(response.data.run_id) ? response.data.run_id : null;
      lastExecutionParams.value = response.data.params_snapshot ?? {};
      executionEvidenceScope.value = response.data.status === "completed" && !response.data.error ? "live_full" : "partial";
      restoredEvidenceNotice.value = null;
      restoredEvidenceGaps.value = [];
      lastExecutionDiagnostics.value = response.data.diagnostics || {};
      lastExecutionResultDescriptors.value = response.data.result_descriptors || {};
      lastExecutionPresentations.value = response.data.result_presentations || {};
      if (response.data.integrity_hash) {
        workflowHash.value = response.data.integrity_hash;
      }

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      const failureRoots = executionFailureRoots(nodeStatuses);
      for (const node of nodes.value) {
        const backendNodeId = node.id;
        const status = nodeStatuses[backendNodeId];
        const result = response.data.results?.[backendNodeId];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          const { output_shape, output_shape_label, output_type } = deriveShapeAndType(
            result,
            lastExecutionResultDescriptors.value[node.id],
            lastExecutionPresentations.value[node.id],
          );

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape,
            output_shape_label,
            output_type,
          });
        } else if (normalizedStatus === "error") {
          const rootId = failureRoots.get(node.id) || node.id;
          const isRootFailure = rootId === node.id;
          const errorMsg = isRootFailure
            ? response.data.error || "Node execution failed"
            : `Not run because upstream node '${rootId}' failed.`;
          setNodeExecutionState(node.id, {
            status: isRootFailure ? "error" : "pending",
            error_message: errorMsg,
            error_details: errorMsg, // Could be enhanced with stack trace
            last_executed: new Date().toISOString(),
            output_shape: null,
            output_type: null,
          });
        } else if (normalizedStatus === "running") {
          setNodeExecutionState(node.id, { status: "running" });
        } else {
          // Pending/unknown/non-executed node.
          setNodeExecutionState(node.id, { status: "pending" });
        }
      }

      // Clear stale flag after successful execution
      if (executedGraph === canonicalWorkflowForStaleCheck(nodes.value)) clearWorkflowStale();
      else markWorkflowStale();

      setMirroredStatus("success");
      scheduleStatusClear("success");

      return response.data;
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      const errorMsg = getErrorMessage(error, "Execution failed");
      if (workflowId.value === executingWorkflowId && executingLoadGeneration === workflowLoadGeneration && executionGeneration === executionRequestGeneration) {
        markScopedExecutionFailure(errorMsg);
      }
      setMirroredStatus("error");
      scheduleStatusClear("error");
      throw error;
    } finally {
      if (executingLoadGeneration === workflowLoadGeneration) isLoading.value = false;
    }
  }

  async function executeStoredWorkflow(
    targetWorkflowId: number,
    initialData?: ParamsMap,
  ): Promise<WorkflowExecuteResponse> {
    const workbookStore = useWorkbookStore();
    const sheet = workbookStore.sheets.find((s) => s.workflowId === targetWorkflowId);
    if (sheet?.purpose === "managed_candidate_authority") {
      throw new Error(
        "Managed candidate authority workflows may only be executed by the governed Harness",
      );
    }
    // Trial tabs mirror the source workflow's run state — see executeWorkflow.
    const trialMirrors = workbookStore.sheets.filter(
      (s) => s.kind === "trial" && s.sourceWorkflowId === targetWorkflowId,
    );
    const allMirroredSheets = sheet ? [sheet, ...trialMirrors] : trialMirrors;
    const setMirroredStatus = (status: "idle" | "running" | "success" | "error") => {
      for (const s of allMirroredSheets) s.executionStatus = status;
    };
    const scheduleStatusClear = (terminal: "success" | "error") => {
      setTimeout(() => {
        for (const s of allMirroredSheets) {
          if (s.executionStatus === terminal) s.executionStatus = "idle";
        }
      }, 3000);
    };

    setMirroredStatus("running");

    try {
      const requestPayload = { initial_data: initialData || {} };
      const response = await singleFlight(
        requestScopedSingleFlightKey(`execute:${targetWorkflowId}`, requestPayload),
        () =>
          api.post<WorkflowExecuteResponse>(
            `/workflows/${targetWorkflowId}/execute`,
            requestPayload,
            { headers: { "Idempotency-Key": newIdempotencyKey() } },
          ),
      );
      setMirroredStatus("success");
      scheduleStatusClear("success");
      return response.data;
    } catch (error) {
      setMirroredStatus("error");
      scheduleStatusClear("error");
      throw error;
    }
  }

  async function executeNodeSnapshot(
    nodeId: string,
    initialData?: ParamsMap,
  ): Promise<WorkflowExecuteResponse> {
    if (useWorkbookStore().activeSheet?.purpose === "managed_candidate_authority") {
      throw new Error(
        "Managed candidate authority workflows may only be executed by the governed Harness",
      );
    }
    assertNumericExecutionInputs(nodeId);
    const preparingGeneration = workflowLoadGeneration;
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }
    if (hasUnsavedChanges.value || preparingGeneration !== workflowLoadGeneration) {
      throw new Error("The workflow changed while saving. Review the current draft and run again.");
    }
    const executingWorkflowId = workflowId.value;
    const executingLoadGeneration = workflowLoadGeneration;
    const executionGeneration = ++executionRequestGeneration;
    const executedGraph = canonicalWorkflowForStaleCheck(nodes.value);

    // Mark target node and its dependencies as running
    const backendNodeId = nodeId;
    if (nodes.value.some((node) => node.id === nodeId)) {
      setNodeExecutionState(nodeId, { status: "running" });
    }

    isLoading.value = true;
    try {
      // Per-node execute scopes single-flight by (workflow, node) so two
      // rapid clicks on the same node coalesce but distinct nodes still
      // run independently. The Idempotency-Key is also a fresh UUID per
      // logical click intent.
      const requestPayload = { node_id: backendNodeId, initial_data: initialData || {}, expected_definition: toBackendFormat() };
      const response = await singleFlight(
        requestScopedSingleFlightKey(`execute:${executingWorkflowId}:${nodeId}`, requestPayload),
        () =>
          api.post(`/workflows/${executingWorkflowId}/execute`, requestPayload, {
            headers: { "Idempotency-Key": newIdempotencyKey() },
          }),
      );

      if (workflowId.value !== executingWorkflowId || executingLoadGeneration !== workflowLoadGeneration || executionGeneration !== executionRequestGeneration) {
        throw new DOMException("Execution belongs to a previously active workflow.", "AbortError");
      }

      // A partial run is a new coherent snapshot, never an overlay onto prior outputs.
      lastExecutionResults.value = response.data.results || {};
      lastExecutionDiagnostics.value = response.data.diagnostics || {};
      lastExecutionResultDescriptors.value = response.data.result_descriptors || {};
      lastExecutionPresentations.value = response.data.result_presentations || {};
      lastExecutionParams.value = response.data.params_snapshot || {};
      executionEvidenceScope.value = "partial";
      restoredRunId.value = Number.isInteger(response.data.run_id) ? response.data.run_id : null;
      restoredEvidenceNotice.value = "Partial execution. Only returned nodes belong to this run; previous downstream results are unavailable.";
      restoredEvidenceGaps.value = [];
      if (executedGraph === canonicalWorkflowForStaleCheck(nodes.value)) clearWorkflowStale();
      else markWorkflowStale();
      for (const node of nodes.value) node.executionState = { status: "pending" };

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      const failureRoots = executionFailureRoots(nodeStatuses);
      for (const node of nodes.value) {
        const currentBackendNodeId = node.id;
        const status = nodeStatuses[currentBackendNodeId];
        const result = response.data.results?.[currentBackendNodeId];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          const { output_shape, output_shape_label, output_type } = deriveShapeAndType(
            result,
            lastExecutionResultDescriptors.value[node.id],
            lastExecutionPresentations.value[node.id],
          );

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape,
            output_shape_label,
            output_type,
          });
        } else if (normalizedStatus === "error") {
          const rootId = failureRoots.get(node.id) || node.id;
          const isRootFailure = rootId === node.id;
          const errorMsg = isRootFailure
            ? response.data.error || "Node execution failed"
            : `Not run because upstream node '${rootId}' failed.`;
          setNodeExecutionState(node.id, {
            status: isRootFailure ? "error" : "pending",
            error_message: errorMsg,
            error_details: errorMsg,
            last_executed: new Date().toISOString(),
            output_shape: null,
            output_type: null,
          });
        } else if (normalizedStatus === "running") {
          setNodeExecutionState(node.id, { status: "running" });
        }
      }

      return response.data;
    } catch (error: unknown) {
      // Mark node as error
      const errorMsg = getErrorMessage(error, "Execution failed");
      if (
        workflowId.value === executingWorkflowId && executingLoadGeneration === workflowLoadGeneration && executionGeneration === executionRequestGeneration &&
        nodes.value.some((node) => node.id === nodeId)
      ) {
        setNodeExecutionState(nodeId, {
          status: "error",
          error_message: errorMsg,
          error_details: errorMsg,
        });
      }
      throw error;
    } finally {
      if (executingLoadGeneration === workflowLoadGeneration) isLoading.value = false;
    }
  }

  /**
   * Execute a trial run of a node with trial parameters.
   *
   * This is used by DetailView to run a node with temporary parameters
   * without persisting anything to the workflow. Creates a fresh execution
   * context (no caching) for each trial.
   *
   * @param targetNodeId - The node to execute with trial params
   * @param trialParams - Trial parameters to override for target node
   * @param initialData - Initial data for DATA nodes (optional)
   * @returns Trial execution result
   */
  async function executeTrial(
    targetNodeId: string,
    trialParams: ParamsMap,
    initialData?: ParamsMap,
  ): Promise<TrialExecuteResponse> {
    const resolvedTargetNodeId = targetNodeId;

    // Build nodes list from current workflow (using backend format)
    const trialNodes = nodes.value.map((node) => ({
      node_id: node.id,
      node_type: node.type,
      parameters: node.params || {},
    }));

    // Build edges list from current workflow
    const trialEdges = edges.value.map((edge) => ({
      from_node_id: edge.from,
      to_node_id: edge.to,
      from_output: edge.fromPort || "default",
      to_input: edge.toPort || "default",
    }));

    try {
      assertNumericExecutionInputs(targetNodeId, trialParams);
      const response = await api.post("/workflows/trial/execute", {
        target_node_id: resolvedTargetNodeId,
        trial_params: trialParams,
        nodes: trialNodes,
        edges: trialEdges,
        initial_data: initialData || {},
      });
      return response.data;
    } catch (error: unknown) {
      // Return error in the same format as backend
      return {
        target_node_id: targetNodeId,
        status: "error",
        result: null,
        result_descriptor: null,
        error: getErrorMessage(error, String(error)),
      };
    }
  }

  async function prepareExport(): Promise<number> {
    const generation = workflowLoadGeneration;
    while (pendingSave) await pendingSave;
    if (generation !== workflowLoadGeneration) {
      throw new Error("Active workflow changed. Retry export on the current sheet.");
    }
    if (!workflowId.value || hasUnsavedChanges.value) await saveWorkflow();
    if (generation !== workflowLoadGeneration || !workflowId.value || hasUnsavedChanges.value) {
      throw new Error("Workflow changed while saving. Retry export after edits are saved.");
    }
    return workflowId.value;
  }

  async function exportToPython(): Promise<string> {
    const id = await prepareExport();
    const response = await api.get(`/workflows/${id}/export/python`);
    return response.data.python_code;
  }

  async function exportToNotebook(): Promise<Record<string, unknown>> {
    const id = await prepareExport();
    const response = await api.get(`/workflows/${id}/export/notebook`);
    return response.data.notebook;
  }

  async function downloadExport(format: "python" | "notebook" | "zip" = "python"): Promise<void> {
    const id = await prepareExport();
    const response = await api.get(`/workflows/${id}/export/download`, {
      params: { format },
      responseType: "blob",
    });

    const contentDisposition = response.headers["content-disposition"] || "";
    const safeName = (workflowName.value || "workflow").toLowerCase().replace(/\s+/g, "_");
    const extMap = { python: ".py", notebook: ".ipynb", zip: ".zip" };
    const fallbackName = `${safeName}_workflow${extMap[format] || ""}`;
    const filename = filenameFromContentDisposition(contentDisposition, fallbackName);
    downloadBlob(blobFromResponseData(response.data), filename);
  }

  async function fetchAvailableDatasets(
    projectId: number | null = useProjectStore().currentProjectId,
  ): Promise<AvailableDatasets> {
    if (projectId == null) {
      const empty = { experiments: [], library: [], builder: [] };
      availableDatasets.value = empty;
      return empty;
    }
    const response = await api.get("/datasets/available", {
      params: { project_id: projectId },
    });
    availableDatasets.value = response.data;
    return response.data;
  }

  /**
   * Caches for reference dataset options (fetched from /builder/reference-datasets API).
   * Keep the full source-indexed catalog for template example selection, while
   * preserving the legacy per-source option arrays used elsewhere in the builder.
   */
  const referenceDatasetCache = ref<Record<string, ReferenceDatasetOption[]>>({});
  const eigenvectorDatasetCache = ref<Array<{ label: string; value: string }>>([]);
  const sklearnDatasetCache = ref<Array<{ label: string; value: string }>>([]);

  /**
   * Fetch available reference datasets from the API.
   * Populates both eigenvector and sklearn caches from one call.
   */
  async function fetchReferenceDatasets(): Promise<void> {
    if (
      Object.keys(referenceDatasetCache.value).length > 0 &&
      eigenvectorDatasetCache.value.length > 0 &&
      sklearnDatasetCache.value.length > 0
    ) {
      return;
    }
    try {
      const response = await api.get<Record<string, ReferenceDatasetOption[]>>(
        "/builder/reference-datasets",
      );
      referenceDatasetCache.value = response.data;
      const toOptions = (arr: Array<{ name: string; label: string }>) =>
        arr.map((d) => ({ label: d.label, value: d.name }));
      eigenvectorDatasetCache.value = toOptions(response.data.eigenvector || []);
      sklearnDatasetCache.value = toOptions(response.data.sklearn || []);
    } catch (error: unknown) {
      console.error("[fetchReferenceDatasets] Failed:", getErrorMessage(error));
    }
  }

  function getReferenceDatasetOptions(source: string): ReferenceDatasetOption[] {
    return referenceDatasetCache.value[source] || [];
  }

  // Backward-compatible alias
  const fetchEigenvectorDatasets = fetchReferenceDatasets;

  /**
   * Fetch type registry metadata used for connection compatibility checks.
   */
  async function fetchTypeRegistry(force: boolean = false): Promise<void> {
    if (isLoadingTypeRegistry.value) return;
    if (!force && typeRegistry.value) return;

    isLoadingTypeRegistry.value = true;
    typeRegistryLoadError.value = null;

    try {
      const response = await api.get<TypeRegistryPayload>("/workflows/types/registry", {
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      });
      typeRegistry.value = response.data;
    } catch (error: unknown) {
      const errMsg = getErrorMessage(error, "Failed to load type registry");
      typeRegistryLoadError.value = errMsg;
      console.error("[WorkflowStore] Failed to load type registry:", errMsg);
    } finally {
      isLoadingTypeRegistry.value = false;
    }
  }

  /**
   * Fetch node library from backend (validation schemas, parameter definitions).
   * Call this on app initialization.
   */
  async function fetchNodeLibrary(force: boolean = false): Promise<void> {
    if (isLoadingNodeLibrary.value) return;

    isLoadingNodeLibrary.value = true;
    nodeLibraryLoadError.value = null;

    try {
      const response = await api.get<NodeLibraryResponse>("/workflows/nodes/library", {
        headers: {
          "Cache-Control": "no-cache", // Force fresh fetch
          Pragma: "no-cache",
        },
      });
      const library = new Map<string, NodeTypeMetadata>();

      for (const nodeMetadata of response.data.nodes) {
        library.set(nodeMetadata.node_type, nodeMetadata);
      }

      const newVersion = response.data.version || "1.0.0";
      const oldVersion = nodeLibraryVersion.value;
      const newCacheIdentity = response.data.cache_identity || newVersion;
      const oldCacheIdentity = nodeLibraryCacheIdentity.value;

      nodeLibrary.value = library;
      nodeLibraryVersion.value = newVersion;
      nodeLibraryCacheIdentity.value = newCacheIdentity;

      if (oldCacheIdentity && oldCacheIdentity !== newCacheIdentity && !force) {
        console.warn(
          `[WorkflowStore] Node-library contract changed: ${oldCacheIdentity} → ${newCacheIdentity}. Node library refreshed.`,
        );
      } else {
        console.log(
          `[WorkflowStore] Loaded ${library.size} node types from backend (v${newVersion})`,
        );
      }

      // Keep type compatibility registry aligned with node metadata refresh.
      await fetchTypeRegistry(force || !typeRegistry.value);
    } catch (error: unknown) {
      const errMsg = getErrorMessage(error, "Failed to load node library");
      nodeLibraryLoadError.value = errMsg;
      console.error("[WorkflowStore] Failed to load node library:", errMsg);
    } finally {
      isLoadingNodeLibrary.value = false;
    }
  }

  /**
   * Check if backend version has changed and refetch if needed.
   * Call this on visibility change or periodically.
   */
  async function checkAndRefreshNodeLibrary(): Promise<void> {
    if (!nodeLibraryCacheIdentity.value && !nodeLibraryVersion.value) {
      // Initial load
      await fetchNodeLibrary();
      return;
    }

    try {
      // Quick version check (lightweight)
      const response = await api.get<NodeLibraryResponse>("/workflows/nodes/library", {
        headers: { "Cache-Control": "no-cache" },
      });
      const serverVersion = response.data.version || "1.0.0";
      const serverCacheIdentity = response.data.cache_identity || serverVersion;
      const currentCacheIdentity = nodeLibraryCacheIdentity.value || nodeLibraryVersion.value;

      if (serverCacheIdentity !== currentCacheIdentity) {
        console.log(
          `[WorkflowStore] Node-library contract updated (${currentCacheIdentity} → ${serverCacheIdentity}), refreshing node library...`,
        );
        await fetchNodeLibrary(true);
      }
    } catch {
      // Silently fail - don't disrupt user experience
      console.debug("[WorkflowStore] Version check failed");
    }
  }

  /**
   * Get metadata for a node type (from library).
   */
  function getNodeMetadata(nodeType: string): NodeTypeMetadata | null {
    return nodeLibrary.value.get(nodeType) || null;
  }

  /**
   * Validate node parameters against metadata.
   * Returns array of validation errors (empty if valid).
   */
  function validateNodeParams(
    nodeType: string,
    params: ParamsMap,
  ): Array<{ param_name: string; message: string }> {
    const metadata = getNodeMetadata(nodeType);
    if (!metadata) {
      return [{ param_name: "_metadata", message: "Node metadata not available" }];
    }

    const errors = validateScientificMetadata(params.metadata);

    for (const paramDef of metadata.parameters) {
      // Match canonical execution: absence uses the declared default, whereas
      // explicit null remains blank (and fails for a required parameter).
      const value = params[paramDef.name] === undefined ? paramDef.default : params[paramDef.name];
      const displayParamName = paramDef.name;

      // Check required
      if (paramDef.required && (value === undefined || value === null || value === "")) {
        errors.push({
          param_name: displayParamName,
          message: `${paramDef.label} is required`,
        });
        continue;
      }

      // Skip validation if value is empty and not required
      if (value === undefined || value === null || value === "") {
        continue;
      }

      // Type validation
      if (paramDef.param_type === "number") {
        if (typeof value !== "number" || !Number.isFinite(value)) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be a finite number`,
          });
          continue;
        }

        // Range validation (only validate if min/max are actual numbers, not null/undefined)
        if (
          paramDef.min_value !== undefined &&
          paramDef.min_value !== null &&
          value < paramDef.min_value
        ) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≥ ${paramDef.min_value}`,
          });
        }
        if (
          paramDef.max_value !== undefined &&
          paramDef.max_value !== null &&
          value > paramDef.max_value
        ) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≤ ${paramDef.max_value}`,
          });
        }
      } else if (paramDef.param_type === "boolean") {
        if (typeof value !== "boolean") {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be true or false`,
          });
        }
      }

      // Custom validation for n_components in PCA/PLS nodes
      if (paramDef.name === "n_components" && paramDef.param_type === "text") {
        const strValue = String(value).trim();
        const lowerValue = strValue.toLowerCase();

        // Check if it's "mle"
        if (lowerValue === "mle") {
          continue; // Valid
        }

        // Try to parse as number
        try {
          const numValue = parseFloat(strValue);

          if (isNaN(numValue)) {
            errors.push({
              param_name: displayParamName,
              message: `${paramDef.label} must be an integer (e.g., 5), 'mle', or float 0-1 (e.g., 0.95)`,
            });
            continue;
          }

          // Check if it's an integer >= 1
          if (Number.isInteger(numValue) && numValue >= 1) {
            continue; // Valid
          }

          // Check if it's a float between 0 and 1 (variance threshold)
          if (numValue > 0 && numValue < 1) {
            continue; // Valid
          }

          // Invalid number
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≥ 1 (integer) or between 0-1 (variance threshold)`,
          });
        } catch {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be an integer (e.g., 5), 'mle', or float 0-1 (e.g., 0.95)`,
          });
        }
      }
    }

    if (nodeType === "preprocess.clip_range") {
      const minimum = params.minimum;
      const maximum = params.maximum;
      if (
        typeof minimum === "number" &&
        Number.isFinite(minimum) &&
        typeof maximum === "number" &&
        Number.isFinite(maximum) &&
        minimum >= maximum
      ) {
        errors.push({
          param_name: "maximum",
          message: "Maximum Feature Coordinate must be greater than Minimum Feature Coordinate",
        });
      }
    }

    return errors;
  }

  /**
   * Set node execution state.
   */
  function setNodeExecutionState(nodeId: string, state: Partial<NodeExecutionState>) {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node) {
      node.executionState = { ...(node.executionState || { status: "pending" }), ...state };
    }
  }

  /**
   * Get node execution state.
   */
  function getNodeExecutionState(nodeId: string): NodeExecutionState | null {
    const node = nodes.value.find((n) => n.id === nodeId);
    return node?.executionState || null;
  }

  /**
   * Mark workflow as stale (modified since last execution).
   */
  function markWorkflowStale() {
    isWorkflowStale.value = true;
  }

  /**
   * Clear stale flag (after successful execution).
   */
  function clearWorkflowStale() {
    isWorkflowStale.value = false;
  }

  function addNode(node: WorkflowNode) {
    if (!node.label || node.label === node.type) node.label = getNodeMetadata(node.type)?.label;
    // Initialize execution state
    node.executionState = { status: "pending" };
    nodes.value.push(node);
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function removeNode(nodeId: string) {
    nodes.value = nodes.value.filter((n) => n.id !== nodeId);
    edges.value = edges.value.filter((e) => e.from !== nodeId && e.to !== nodeId);
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  const stableStringify = (value: unknown): string => {
    if (Array.isArray(value)) {
      return `[${value.map((item) => stableStringify(item)).join(",")}]`;
    }
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      return `{${Object.keys(record)
        .sort()
        .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
        .join(",")}}`;
    }
    return JSON.stringify(value);
  };

  const valuesEqual = (left: unknown, right: unknown): boolean =>
    stableStringify(left) === stableStringify(right);

  const canonicalNodeForStaleCheck = (node: WorkflowNode): UnknownRecord => ({
    node_id: node.id,
    node_type: node.type,
    parameters: node.params || {},
  });

  const canonicalEdgeForStaleCheck = (edge: WorkflowEdge): UnknownRecord => ({
    from_node_id: edge.from,
    to_node_id: edge.to,
    from_output: edge.fromPort || "default",
    to_input: edge.toPort || "default",
  });

  const canonicalWorkflowForStaleCheck = (
    candidateNodes: WorkflowNode[],
    candidateEdges: WorkflowEdge[] = edges.value,
  ): string =>
    stableStringify({
      nodes: candidateNodes
        .map(canonicalNodeForStaleCheck)
        .sort((left, right) => String(left.node_id).localeCompare(String(right.node_id))),
      edges: candidateEdges
        .map(canonicalEdgeForStaleCheck)
        .sort(
          (left, right) =>
            [
              String(left.from_node_id).localeCompare(String(right.from_node_id)),
              String(left.to_node_id).localeCompare(String(right.to_node_id)),
              String(left.from_output).localeCompare(String(right.from_output)),
              String(left.to_input).localeCompare(String(right.to_input)),
            ].find((comparison) => comparison !== 0) ?? 0,
        ),
    });

  function updateNode(nodeId: string, updates: Partial<WorkflowNode>) {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node) {
      const changed = Object.entries(updates).some(([key, value]) => {
        const currentValue = node[key as keyof WorkflowNode];
        return !valuesEqual(currentValue, value);
      });
      if (!changed) {
        return;
      }
      Object.assign(node, updates);
      hasUnsavedChanges.value = true;
      markWorkflowStale();
    }
  }

  /**
   * Validate an edge connection between two nodes.
   * Checks if the output type of the source node is compatible with the input types of the target node.
   */
  function validateEdge(edge: WorkflowEdge): {
    isValid: boolean;
    error?: string;
    dataType?: string;
  } {
    const sourceNode = nodes.value.find((n) => n.id === edge.from);
    const targetNode = nodes.value.find((n) => n.id === edge.to);

    if (!sourceNode || !targetNode) {
      return {
        isValid: false,
        error:
          "⚠️ Connection Error: Source or target node no longer exists. Please delete this connection.",
      };
    }

    const sourceMetadata = getNodeMetadata(sourceNode.type);
    const targetMetadata = getNodeMetadata(targetNode.type);

    if (!sourceMetadata || !targetMetadata) {
      return {
        isValid: false,
        error:
          "⚠️ Validation Unavailable: Node type information is still loading. Please wait and try again.",
      };
    }

    // Port-level validation (if ports are defined)
    if (sourceMetadata.output_ports && targetMetadata.input_ports) {
      const outputPorts = sourceMetadata.output_ports;
      const inputPorts = targetMetadata.input_ports;

      const resolveOutputPort = () => {
        if (!edge.fromPort || edge.fromPort === "default") {
          return outputPorts.find((p) => p.name === "default") || outputPorts[0];
        }
        return outputPorts.find((p) => p.name === edge.fromPort) || null;
      };

      const resolveInputPort = () => {
        if (!edge.toPort) {
          return inputPorts.length === 1 ? inputPorts[0] : null;
        }
        if (edge.toPort === "default") {
          return (
            inputPorts.find((p) => p.name === "default") ||
            (inputPorts.length === 1 ? inputPorts[0] : null)
          );
        }
        return inputPorts.find((p) => p.name === edge.toPort) || null;
      };

      const outputPort = resolveOutputPort();

      // Get the specific input port (must be specified for multi-input nodes)
      let inputPort;
      if (edge.toPort !== undefined) {
        inputPort = resolveInputPort();
        if (!inputPort) {
          const availablePorts = inputPorts
            .map((p) => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`)
            .join(", ");
          return {
            isValid: false,
            error: `❌ Invalid Port: "${edge.toPort}" doesn't resolve on ${targetMetadata.label}. Available ports: ${availablePorts}`,
          };
        }
      } else if (inputPorts.length === 1) {
        // Single input port - auto-connect
        inputPort = inputPorts[0];
      } else {
        // Multi-input node but no port specified
        const availablePorts = inputPorts
          .map((p) => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`)
          .join(", ");
        return {
          isValid: false,
          error: `🔌 Select Input Port: ${targetMetadata.label} has multiple inputs. Please click the specific port: ${availablePorts}`,
        };
      }

      if (!outputPort || !inputPort) {
        return {
          isValid: false,
          error: "❌ Missing source or target port metadata for this connection.",
        };
      }

      // type_ref-based validation
      const typeValidation = validateTypeRefs(outputPort.type_ref, inputPort.type_ref);
      if (!typeValidation.isValid) {
        return {
          isValid: false,
          error: `❌ ${typeValidation.error}. ${sourceMetadata.label}'s "${outputPort.label}" (${typeRefToDisplayName(outputPort.type_ref)}) cannot connect to ${targetMetadata.label}'s "${inputPort.label}" (${typeRefToDisplayName(inputPort.type_ref)}).`,
          dataType: typeValidation.dataType ?? typeRefToDisplayName(outputPort.type_ref),
        };
      }
      return {
        isValid: true,
        dataType: typeValidation.dataType ?? typeRefToDisplayName(outputPort.type_ref),
      };
    }

    // Hybrid validation: multi-output source (with output_ports) → legacy target (without input_ports)
    // Example: DataSourceNode (has "default" and "target" ports) → PCA/HCA (legacy single input)
    if (sourceMetadata.output_ports && !targetMetadata.input_ports) {
      // Get the default output port (what the executor will extract)
      const outputPortName = edge.fromPort || "default";
      const outputPort =
        sourceMetadata.output_ports.find((p) => p.name === outputPortName) ||
        sourceMetadata.output_ports[0];

      if (!outputPort) {
        return {
          isValid: false,
          error: `❌ No output port found on ${sourceMetadata.label}. Available ports: ${sourceMetadata.output_ports.map((p) => p.label).join(", ")}`,
        };
      }

      // Derive category from type_ref to validate against legacy input_types
      const outputCategory = getCategoryFromTypeRef(outputPort.type_ref);
      const categoryToClassNames: Record<string, string[]> = {
        dataset: ["SherpaDataset", "array"],
        target: ["array", "list", "any"],
        model: ["PCAModel", "PLSModel", "PLSDAModel", "HCAResult", "any"],
        config: ["dict", "config", "any"],
        array: ["array", "list", "any"],
        number: ["number", "float", "int", "any"],
        visualization: ["dict", "plot", "any"],
      };

      const inputTypes = targetMetadata.input_types;
      const compatibleClassNames = categoryToClassNames[outputCategory] || [outputCategory];

      // Check if any compatible class name is accepted by target
      const isCompatible =
        compatibleClassNames.some((className) => inputTypes.includes(className)) ||
        inputTypes.includes("any");

      if (!isCompatible) {
        return {
          isValid: false,
          error: `❌ Type Mismatch: ${sourceMetadata.label}'s "${outputPort.label}" port outputs "${typeRefToDisplayName(outputPort.type_ref)}" data, but ${targetMetadata.label} only accepts ${inputTypes.map((t) => `"${t}"`).join(" or ")}. Try connecting from a different output port.`,
          dataType: typeRefToDisplayName(outputPort.type_ref),
        };
      }

      return { isValid: true, dataType: typeRefToDisplayName(outputPort.type_ref) };
    }

    // Legacy validation (backward compatibility for nodes without port metadata)
    const outputType = sourceMetadata.output_type;
    const inputTypes = targetMetadata.input_types;

    // Check if output type is compatible with any of the accepted input types
    const isCompatible = inputTypes.includes(outputType) || inputTypes.includes("any");

    if (!isCompatible) {
      return {
        isValid: false,
        error: `❌ Type Mismatch: ${sourceMetadata.label} outputs "${outputType}" data, but ${targetMetadata.label} only accepts ${inputTypes.map((t) => `"${t}"`).join(" or ")}. Check the node documentation for compatible connections.`,
        dataType: outputType,
      };
    }

    return { isValid: true, dataType: outputType };
  }

  /**
   * Validate all edges in the workflow and update their validation state.
   */
  function validateAllEdges() {
    for (const edge of edges.value) {
      const validation = validateEdge(edge);
      edge.isValid = validation.isValid;
      edge.validationError = validation.error || null;
      edge.dataType = validation.dataType || null;
    }
  }

  function addEdge(edge: WorkflowEdge) {
    // Prevent duplicates - same from/to/fromPort/toPort
    const exists = edges.value.some(
      (e) =>
        e.from === edge.from &&
        e.to === edge.to &&
        e.fromPort === edge.fromPort &&
        e.toPort === edge.toPort,
    );
    if (!exists) {
      // Enforce max-1 cardinality on non-variadic ports:
      // if the target port already has an incoming edge, replace it.
      const targetNode = nodes.value.find((n) => n.id === edge.to);
      const targetMeta = targetNode ? getNodeMetadata(targetNode.type) : null;
      if (targetMeta?.input_ports) {
        const toPort = edge.toPort || targetMeta.input_ports[0]?.name || "default";
        const portMeta = targetMeta.input_ports.find((p) => p.name === toPort);
        if (portMeta && !portMeta.variadic) {
          const existingIdx = edges.value.findIndex(
            (e) =>
              e.to === edge.to &&
              (e.toPort || targetMeta.input_ports![0]?.name || "default") === toPort,
          );
          if (existingIdx !== -1) {
            edges.value.splice(existingIdx, 1);
          }
        }
      }

      // Validate the edge before adding
      const validation = validateEdge(edge);
      edge.isValid = validation.isValid;
      edge.validationError = validation.error || null;
      edge.dataType = validation.dataType || null;

      edges.value.push(edge);
      hasUnsavedChanges.value = true;
      markWorkflowStale();
    }
  }

  function removeEdge(from: string, to: string) {
    edges.value = edges.value.filter((e) => !(e.from === from && e.to === to));
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function setNodes(newNodes: WorkflowNode[]) {
    const previousCanonical = canonicalWorkflowForStaleCheck(nodes.value);
    // Initialize execution state for all nodes
    for (const node of newNodes) {
      if (!node.executionState) {
        node.executionState = { status: "pending" };
      }
    }
    const nextCanonical = canonicalWorkflowForStaleCheck(newNodes);
    nodes.value = newNodes;
    hasUnsavedChanges.value = true;
    if (previousCanonical !== nextCanonical) {
      markWorkflowStale();
    }
  }

  function setEdges(newEdges: WorkflowEdge[]) {
    const previousCanonical = canonicalWorkflowForStaleCheck(nodes.value);
    edges.value = newEdges.map((edge) => {
      const validation = validateEdge(edge);
      return {
        ...edge,
        isValid: validation.isValid,
        validationError: validation.error || null,
        dataType: validation.dataType || null,
      };
    });
    const nextCanonical = canonicalWorkflowForStaleCheck(nodes.value);
    hasUnsavedChanges.value = true;
    if (previousCanonical !== nextCanonical) {
      markWorkflowStale();
    }
  }

  return {
    // State
    nodes,
    edges,
    currentTemplateId,
    hasUnsavedChanges,
    workflowName,
    workflowId,
    workflowDescription,
    workflowHash,
    isLoading,
    lastExecutionResults,
    restoredRunId,
    lastExecutionParams,
    restoredEvidenceNotice,
    restoredEvidenceGaps,
    executionEvidenceScope,
    isExecuting,
    lastExecutionDiagnostics,
    lastExecutionResultDescriptors,
    lastExecutionPresentations,
    workflowWarnings,
    hasFoldValidationPlan,
    workflowPreflight,
    availableDatasets,
    templates,
    templatesLoading,
    templatesError,
    compatibilityMatrix,
    compatibilityLoading,
    compatibilityError,

    // Node library state
    nodeLibrary,
    isLoadingNodeLibrary,
    nodeLibraryLoadError,
    nodeLibraryVersion,
    nodeLibraryCacheIdentity,
    typeRegistry,
    isLoadingTypeRegistry,
    typeRegistryLoadError,
    isWorkflowStale,

    // Getters
    nodeCount,
    edgeCount,
    availableTemplates,

    // Local Actions
    loadTemplate,
    clearWorkflow,
    addNode,
    removeNode,
    updateNode,
    addEdge,
    removeEdge,
    setNodes,
    setEdges,

    // Node library & validation
    fetchNodeLibrary,
    fetchTypeRegistry,
    checkAndRefreshNodeLibrary,
    getNodeMetadata,
    validateTypeRefs,
    validateNodeParams,
    validateEdge,
    validateAllEdges,
    refreshPersistedPreflight,
    setNodeExecutionState,
    getNodeExecutionState,
    markWorkflowStale,
    clearWorkflowStale,

    // API Actions
    saveWorkflow,
    loadWorkflow,
    listWorkflows,
    duplicateWorkflow,
    fetchTemplates,
    fetchCompatibilityMatrix,
    compatibilityDecision,
    compatibleAnalysisCount,
    fetchTemplate,
    instantiateTemplate,
    deleteWorkflow,
    assertNumericExecutionInputs,
    executeWorkflow,
    executeStoredWorkflow,
    executeNode,
    executeTrial,
    exportToPython,
    exportToNotebook,
    downloadExport,
    fetchAvailableDatasets,
    referenceDatasetCache,
    getReferenceDatasetOptions,
    eigenvectorDatasetCache,
    sklearnDatasetCache,
    fetchReferenceDatasets,
    fetchEigenvectorDatasets,
  };
});
