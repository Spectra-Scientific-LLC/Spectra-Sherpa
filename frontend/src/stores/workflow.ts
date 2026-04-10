import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type { NodeTypeMetadata, NodeLibraryResponse, NodeExecutionStatus } from "@/types";
import { getErrorMessage } from "@/utils/errors";
import { useJobStore } from "@/stores/job";

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
  TrialExecuteResponse,
  DatasetFile,
  ExperimentDataset,
  LibraryDataset,
  AvailableDatasets,
  WorkflowListItem,
} from "@/stores/workflow-types";

import type {
  ParamsMap,
  UnknownRecord,
  WorkflowNode,
  WorkflowEdge,
  WorkflowTemplate,
  WorkflowTemplateCatalog,
  ReferenceDatasetOption,
  TypeRegistryEntry,
  TypeRegistryPayload,
  BackendWorkflowNode,
  BackendWorkflowEdge,
  WorkflowCreatePayload,
  WorkflowExecuteResponse,
  TrialExecuteResponse,
  TemplateLaunchMode,
  TemplateDataBinding,
  TemplateExampleBinding,
  AvailableDatasets,
  WorkflowListItem,
} from "@/stores/workflow-types";

import type { NodeExecutionState } from "@/types";

export const useWorkflowStore = defineStore("workflow", () => {
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
  const lastExecutionDiagnostics = ref<Record<string, UnknownRecord>>({});
  const workflowWarnings = ref<string[]>([]);
  const availableDatasets = ref<AvailableDatasets | null>(null);
  const templates = ref<WorkflowTemplate[]>([]);
  const templatesLoading = ref(false);
  const templatesError = ref<string | null>(null);

  // Node library metadata (validation schemas, parameters, etc.)
  const nodeLibrary = ref<Map<string, NodeTypeMetadata>>(new Map());
  const isLoadingNodeLibrary = ref(false);
  const nodeLibraryLoadError = ref<string | null>(null);
  const nodeLibraryVersion = ref<string | null>(null); // Track backend version for cache invalidation
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
    if (normalized === "completed" || normalized === "complete" || normalized === "success" || normalized === "succeeded") {
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
    result: unknown
  ): { output_shape: number[] | null; output_type: string | null } => {
    let output_shape: number[] | null = null;
    let output_type: string | null = null;

    if (!result || typeof result !== "object") {
      return { output_shape, output_type };
    }

    const resultRec = result as Record<string, unknown>;
    // Multi-port node: look inside `default` first, then fall back to the top-level result.
    const primaryRaw = "default" in resultRec ? resultRec.default : resultRec;
    if (!primaryRaw || typeof primaryRaw !== "object") {
      return { output_shape, output_type };
    }
    const primary = primaryRaw as Record<string, unknown>;

    if (typeof primary.type === "string") {
      output_type = primary.type;
    }
    if (Array.isArray(primary.shape)) {
      output_shape = primary.shape as number[];
    }
    // SherpaDataset/NDDataset expose n_samples/n_features at the top of the serialized dict.
    if (
      typeof primary.n_samples === "number" &&
      typeof primary.n_features === "number"
    ) {
      output_shape = [primary.n_samples, primary.n_features];
    }
    return { output_shape, output_type };
  };

  const parseTypeRef = (
    typeRef: string
  ): { name: string; major: number; minor: number } | null => {
    const match = typeRef.match(
      /^spectrasherpa:\/\/types\/(?<name>[A-Za-z0-9_]+)\/(?<major>\d+)\.(?<minor>\d+)$/
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
    targetTypeRef: string
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
    if (target.name === 'Any') {
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
      label: n.type,
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
    backendEdges: BackendWorkflowEdge[]
  ): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
    const frontendNodes: WorkflowNode[] = backendNodes.map((n) => {
      const frontendType = n.node_type;
      return {
        id: n.node_id,
        type: frontendType,
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
      template.template_data.edges || []
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
    nodes.value = [];
    edges.value = [];
    currentTemplateId.value = null;
    workflowName.value = "Untitled Workflow";
    workflowId.value = null;
    workflowDescription.value = "";
    workflowHash.value = null;
    hasUnsavedChanges.value = false;
    lastExecutionResults.value = null;
    lastExecutionDiagnostics.value = {};
    workflowWarnings.value = [];
  }

  // API Methods
  async function saveWorkflow(): Promise<number> {
    isLoading.value = true;
    try {
      const { nodes: backendNodes, edges: backendEdges } = toBackendFormat();

      if (workflowId.value) {
        // Update existing workflow
        const response = await api.put(`/workflows/${workflowId.value}`, {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          nodes: backendNodes,
          edges: backendEdges,
        });
        workflowHash.value = response.data.integrity_hash || null;
        hasUnsavedChanges.value = false;
        return response.data.id;
      } else {
        // Create new workflow
        const payload: WorkflowCreatePayload = {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          nodes: backendNodes,
          edges: backendEdges,
        };
        const response = await api.post("/workflows", payload);
        workflowId.value = response.data.id;
        workflowHash.value = response.data.integrity_hash || null;
        hasUnsavedChanges.value = false;
        return response.data.id;
      }
    } finally {
      isLoading.value = false;
    }
  }

  async function loadWorkflow(id: number): Promise<void> {
    isLoading.value = true;
    try {
      const response = await api.get(`/workflows/${id}`);
      const data = response.data;

      workflowId.value = data.id;
      workflowName.value = data.name;
      workflowDescription.value = data.description || "";
      workflowHash.value = data.integrity_hash || null;
      workflowWarnings.value = Array.isArray(data.warnings)
        ? data.warnings.filter((w: unknown): w is string => typeof w === "string")
        : [];

      const converted = fromBackendFormat(data.nodes || [], data.edges || []);
      nodes.value = converted.nodes;
      edges.value = converted.edges;
      validateAllEdges();

      currentTemplateId.value = null;
      hasUnsavedChanges.value = false;

      // Load latest auto-saved execution results (survives page refresh)
      try {
        const runResp = await api.get(`/workflows/${id}/runs/latest`);
        if (runResp.data) {
          lastExecutionResults.value = runResp.data.results_summary;
          lastExecutionDiagnostics.value = runResp.data.diagnostics || {};

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
              const { output_shape, output_type } = deriveShapeAndType(result);
              setNodeExecutionState(node.id, {
                status: "completed",
                last_executed: runResp.data.executed_at || null,
                output_shape,
                output_type,
              });
            } else if (status === "error") {
              setNodeExecutionState(node.id, {
                status: "error",
                error_message: runResp.data.error || null,
              });
            }
          }

          // Mark stale if workflow changed since last execution
          if (
            data.integrity_hash &&
            runResp.data.integrity_hash &&
            data.integrity_hash !== runResp.data.integrity_hash
          ) {
            workflowWarnings.value = [
              ...workflowWarnings.value,
              "Workflow was modified since last execution — results may be stale.",
            ];
          }
        }
      } catch {
        // No latest run — OK, nothing to restore
      }
    } finally {
      isLoading.value = false;
    }
  }

  async function listWorkflows(): Promise<WorkflowListItem[]> {
    const response = await api.get<WorkflowListItem[]>("/workflows");
    return response.data;
  }

  async function fetchTemplates(category?: string): Promise<WorkflowTemplate[]> {
    templatesLoading.value = true;
    templatesError.value = null;
    try {
      const response = await api.get<WorkflowTemplateCatalog>("/workflow-templates", {
        params: category ? { category } : undefined,
      });
      const fetched = response.data.templates;
      templates.value = fetched;
      return templates.value;
    } catch (error: unknown) {
      templatesError.value = getErrorMessage(error, "Failed to load workflow templates");
      throw error;
    } finally {
      templatesLoading.value = false;
    }
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
    }
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
        Object.entries(payload.exampleBindings || {}).map(([key, binding]) => [
          key,
          {
            source: binding.source,
            dataset_name: binding.datasetName,
          },
        ])
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

  async function executeWorkflow(
    initialData?: ParamsMap
  ): Promise<WorkflowExecuteResponse> {
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }

    // Mark all nodes as queued before execution
    for (const node of nodes.value) {
      setNodeExecutionState(node.id, { status: "pending" });
    }

    isLoading.value = true;

    // Subscribe to real-time per-node progress via existing WebSocket
    const jobStore = useJobStore();
    const wfChannel = workflowId.value ? `workflow:${workflowId.value}` : null;
    const ws = jobStore.wsRef;

    if (wfChannel && ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ action: "subscribe", channel: wfChannel }));
      } catch { /* ignore */ }
    }

    const _onNodeStatus = (ev: Event) => {
      const detail = (ev as CustomEvent).detail;
      if (!detail?.node_id || !detail?.status) return;
      const frontendId = String(detail.node_id);
      if (nodes.value.some((node) => node.id === frontendId)) {
        setNodeExecutionState(frontendId, {
          status: detail.status as NodeExecutionStatus,
          error_message: detail.error || null,
        });
      }
    };
    window.addEventListener("workflow-node-status", _onNodeStatus);

    try {
      const response = await api.post(`/workflows/${workflowId.value}/execute`, {
        initial_data: initialData || {},
      });

      // Store results and integrity hash
      lastExecutionResults.value = response.data.results;
      lastExecutionDiagnostics.value = response.data.diagnostics || {};
      if (response.data.integrity_hash) {
        workflowHash.value = response.data.integrity_hash;
      }

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      for (const node of nodes.value) {
        const backendNodeId = node.id;
        const status = nodeStatuses[backendNodeId];
        const result = response.data.results?.[backendNodeId];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          const { output_shape, output_type } = deriveShapeAndType(result);

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape,
            output_type,
          });
        } else if (normalizedStatus === "error") {
          // Extract error message from response or use generic message
          const errorMsg = response.data.error || "Node execution failed";
          setNodeExecutionState(node.id, {
            status: "error",
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
      clearWorkflowStale();

      return response.data;
    } catch (error: unknown) {
      // Mark all nodes as error on workflow execution failure
      const errorMsg = getErrorMessage(error, "Execution failed");
      for (const node of nodes.value) {
        setNodeExecutionState(node.id, {
          status: "error",
          error_message: errorMsg,
          error_details: errorMsg,
        });
      }
      throw error;
    } finally {
      // Clean up workflow progress subscription
      window.removeEventListener("workflow-node-status", _onNodeStatus);
      if (wfChannel && ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ action: "unsubscribe", channel: wfChannel }));
        } catch { /* ignore */ }
      }
      isLoading.value = false;
    }
  }

  async function executeNode(
    nodeId: string,
    initialData?: ParamsMap
  ): Promise<WorkflowExecuteResponse> {
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }

    // Mark target node and its dependencies as running
    const backendNodeId = nodeId;
    if (nodes.value.some((node) => node.id === nodeId)) {
      setNodeExecutionState(nodeId, { status: "running" });
    }

    isLoading.value = true;
    try {
      const response = await api.post(`/workflows/${workflowId.value}/execute`, {
        node_id: backendNodeId,
        initial_data: initialData || {},
      });

      // Update results for the specific node
      if (!lastExecutionResults.value) {
        lastExecutionResults.value = {};
      }
      Object.assign(lastExecutionResults.value, response.data.results);
      if (response.data.diagnostics) {
        lastExecutionDiagnostics.value = {
          ...lastExecutionDiagnostics.value,
          ...response.data.diagnostics,
        };
      }

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      for (const node of nodes.value) {
        const currentBackendNodeId = node.id;
        const status = nodeStatuses[currentBackendNodeId];
        const result = response.data.results?.[currentBackendNodeId];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          const { output_shape, output_type } = deriveShapeAndType(result);

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape,
            output_type,
          });
        } else if (normalizedStatus === "error") {
          const errorMsg = response.data.error || "Node execution failed";
          setNodeExecutionState(node.id, {
            status: "error",
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
      if (nodes.value.some((node) => node.id === nodeId)) {
        setNodeExecutionState(nodeId, {
          status: "error",
          error_message: errorMsg,
          error_details: errorMsg,
        });
      }
      throw error;
    } finally {
      isLoading.value = false;
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
    initialData?: ParamsMap
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
        error: getErrorMessage(error, String(error)),
      };
    }
  }

  async function exportToPython(): Promise<string> {
    if (!workflowId.value) {
      await saveWorkflow();
    }

    const response = await api.get(`/workflows/${workflowId.value}/export/python`);
    return response.data.python_code;
  }

  async function exportToNotebook(): Promise<Record<string, unknown>> {
    if (!workflowId.value) {
      await saveWorkflow();
    }

    const response = await api.get(`/workflows/${workflowId.value}/export/notebook`);
    return response.data.notebook;
  }

  async function downloadExport(format: "python" | "notebook" | "zip" = "python"): Promise<void> {
    if (!workflowId.value) {
      await saveWorkflow();
    }

    const response = await api.get(
      `/workflows/${workflowId.value}/export/download?format=${format}`,
      { responseType: "blob" },
    );

    const contentDisposition = response.headers["content-disposition"] || "";
    const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
    const safeName = (workflowName.value || "workflow").toLowerCase().replace(/\s+/g, "_");
    const extMap = { python: ".py", notebook: ".ipynb", zip: ".zip" };
    const fallbackName = `${safeName}_workflow${extMap[format] || ""}`;
    const filename = filenameMatch ? filenameMatch[1] : fallbackName;

    const blob = new Blob([response.data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function fetchAvailableDatasets(): Promise<AvailableDatasets> {
    const response = await api.get("/datasets/available");
    availableDatasets.value = response.data;
    return response.data;
  }

  /**
   * Cache for SpectroChemPy example files by dataset.
   * Avoids redundant API calls when switching between datasets.
   */
  const spectroChemPyFileCache = ref<Map<string, Array<{label: string; value: string; path: string}>>>(new Map());

  /**
   * Fetch available files for a SpectroChemPy example dataset.
   * Results are cached to avoid redundant API calls.
   *
   * @param dataset - Dataset name (irdata, ramandata, nmrdata, galacticdata)
   * @returns Array of file options for dropdown
   */
  async function fetchSpectroChemPyFiles(dataset: string): Promise<Array<{label: string; value: string; path: string}>> {
    // Check cache first
    if (spectroChemPyFileCache.value.has(dataset)) {
      const cached = spectroChemPyFileCache.value.get(dataset)!;
      console.log(`[fetchSpectroChemPyFiles] Returning ${cached.length} cached files for ${dataset}`);
      return cached;
    }

    // Ensure API key is set (fallback for dev mode)
    if (!localStorage.getItem("api_key") && import.meta.env.DEV) {
      const defaultKey = import.meta.env.VITE_DEFAULT_API_KEY || "default-local-key";
      console.log(`[fetchSpectroChemPyFiles] Setting default API key for dev mode`);
      localStorage.setItem("api_key", defaultKey);
    }

    try {
      console.log(`[fetchSpectroChemPyFiles] Fetching files from API for ${dataset}...`);
      console.log(`[fetchSpectroChemPyFiles] API key present:`, !!localStorage.getItem("api_key"));
      const response = await api.get("/workflows/spectrochempy-examples");
      const allFiles = response.data;

      console.log(`[fetchSpectroChemPyFiles] API returned datasets:`, Object.keys(allFiles));

      // Cache all datasets at once (response contains all dataset files)
      for (const [datasetName, files] of Object.entries(allFiles)) {
        const typedFiles = Array.isArray(files) ? files : [];
        spectroChemPyFileCache.value.set(
          datasetName,
          typedFiles as Array<{ label: string; value: string; path: string }>
        );
        console.log(`[fetchSpectroChemPyFiles] Cached ${typedFiles.length} files for ${datasetName}`);
      }

      const result = allFiles[dataset] || [];
      console.log(`[fetchSpectroChemPyFiles] Returning ${result.length} files for ${dataset}`, result.length > 0 ? result[0] : 'empty');
      return result;
    } catch (error: unknown) {
      console.error(`[fetchSpectroChemPyFiles] Failed for ${dataset}:`, error);
      console.error(`[fetchSpectroChemPyFiles] Error message:`, getErrorMessage(error));
      return [];
    }
  }

  /**
   * Get available SpectroChemPy dataset names.
   * Returns dataset names from cache, or empty array if not yet loaded.
   */
  const availableSpectroChemPyDatasets = computed(() => {
    return Array.from(spectroChemPyFileCache.value.keys());
  });

  /**
   * Clear SpectroChemPy file cache.
   * Call when backend version changes or on manual refresh.
   */
  function clearSpectroChemPyFileCache() {
    spectroChemPyFileCache.value.clear();
  }

  /**
   * Caches for reference dataset options (fetched from /builder/reference-datasets API).
   * Keep the full source-indexed catalog for template example selection, while
   * preserving the legacy per-source option arrays used elsewhere in the builder.
   */
  const referenceDatasetCache = ref<Record<string, ReferenceDatasetOption[]>>({});
  const eigenvectorDatasetCache = ref<Array<{label: string; value: string}>>([]);
  const sklearnDatasetCache = ref<Array<{label: string; value: string}>>([]);

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
      const response = await api.get<Record<string, ReferenceDatasetOption[]>>("/builder/reference-datasets");
      referenceDatasetCache.value = response.data;
      const toOptions = (arr: Array<{name: string; label: string}>) =>
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
          'Cache-Control': 'no-cache',  // Force fresh fetch
          'Pragma': 'no-cache'
        }
      });
      const library = new Map<string, NodeTypeMetadata>();

      for (const nodeMetadata of response.data.nodes) {
        library.set(nodeMetadata.node_type, nodeMetadata);
      }

      const newVersion = response.data.version || "1.0.0";
      const oldVersion = nodeLibraryVersion.value;

      nodeLibrary.value = library;
      nodeLibraryVersion.value = newVersion;

      if (oldVersion && oldVersion !== newVersion && !force) {
        console.warn(`[WorkflowStore] Backend version changed: ${oldVersion} → ${newVersion}. Node library refreshed.`);
      } else {
        console.log(`[WorkflowStore] Loaded ${library.size} node types from backend (v${newVersion})`);
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
    if (!nodeLibraryVersion.value) {
      // Initial load
      await fetchNodeLibrary();
      return;
    }

    try {
      // Quick version check (lightweight)
      const response = await api.get<NodeLibraryResponse>("/workflows/nodes/library", {
        headers: { 'Cache-Control': 'no-cache' }
      });
      const serverVersion = response.data.version || "1.0.0";

      if (serverVersion !== nodeLibraryVersion.value) {
        console.log(`[WorkflowStore] Backend updated (${nodeLibraryVersion.value} → ${serverVersion}), refreshing node library...`);
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
  function validateNodeParams(nodeType: string, params: ParamsMap): Array<{ param_name: string; message: string }> {
    const metadata = getNodeMetadata(nodeType);
    if (!metadata) {
      return [{ param_name: "_metadata", message: "Node metadata not available" }];
    }

    const errors: Array<{ param_name: string; message: string }> = [];

    for (const paramDef of metadata.parameters) {
      const value = params[paramDef.name];
      const displayParamName = paramDef.name;

      // Check required
      if (paramDef.required && (value === undefined || value === null || value === '')) {
        errors.push({
          param_name: displayParamName,
          message: `${paramDef.label} is required`,
        });
        continue;
      }

      // Skip validation if value is empty and not required
      if (value === undefined || value === null || value === '') {
        continue;
      }

      // Type validation
      if (paramDef.param_type === "number") {
        if (typeof value !== "number" || isNaN(value)) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be a number`,
          });
          continue;
        }

        // Range validation (only validate if min/max are actual numbers, not null/undefined)
        if (paramDef.min_value !== undefined && paramDef.min_value !== null && value < paramDef.min_value) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≥ ${paramDef.min_value}`,
          });
        }
        if (paramDef.max_value !== undefined && paramDef.max_value !== null && value > paramDef.max_value) {
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

  function updateNode(nodeId: string, updates: Partial<WorkflowNode>) {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node) {
      Object.assign(node, updates);
      hasUnsavedChanges.value = true;
      markWorkflowStale();
    }
  }

  /**
   * Validate an edge connection between two nodes.
   * Checks if the output type of the source node is compatible with the input types of the target node.
   */
  function validateEdge(edge: WorkflowEdge): { isValid: boolean; error?: string; dataType?: string } {
    const sourceNode = nodes.value.find(n => n.id === edge.from);
    const targetNode = nodes.value.find(n => n.id === edge.to);

    if (!sourceNode || !targetNode) {
      return {
        isValid: false,
        error: "⚠️ Connection Error: Source or target node no longer exists. Please delete this connection."
      };
    }

    const sourceMetadata = getNodeMetadata(sourceNode.type);
    const targetMetadata = getNodeMetadata(targetNode.type);

    if (!sourceMetadata || !targetMetadata) {
      return {
        isValid: false,
        error: "⚠️ Validation Unavailable: Node type information is still loading. Please wait and try again."
      };
    }

    // Port-level validation (if ports are defined)
    if (sourceMetadata.output_ports && targetMetadata.input_ports) {
      const outputPorts = sourceMetadata.output_ports;
      const inputPorts = targetMetadata.input_ports;

      const resolveOutputPort = () => {
        if (!edge.fromPort || edge.fromPort === "default") {
          return outputPorts.find((p) => p.name === "default")
            || outputPorts[0];
        }
        return outputPorts.find((p) => p.name === edge.fromPort) || null;
      };

      const resolveInputPort = () => {
        if (!edge.toPort) {
          return inputPorts.length === 1 ? inputPorts[0] : null;
        }
        if (edge.toPort === "default") {
          return inputPorts.find((p) => p.name === "default")
            || (inputPorts.length === 1 ? inputPorts[0] : null);
        }
        return inputPorts.find((p) => p.name === edge.toPort) || null;
      };

      const outputPort = resolveOutputPort();

      // Get the specific input port (must be specified for multi-input nodes)
      let inputPort;
      if (edge.toPort !== undefined) {
        inputPort = resolveInputPort();
        if (!inputPort) {
          const availablePorts = inputPorts.map(p => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`).join(', ');
          return {
            isValid: false,
            error: `❌ Invalid Port: "${edge.toPort}" doesn't resolve on ${targetMetadata.label}. Available ports: ${availablePorts}`
          };
        }
      } else if (inputPorts.length === 1) {
        // Single input port - auto-connect
        inputPort = inputPorts[0];
      } else {
        // Multi-input node but no port specified
        const availablePorts = inputPorts.map(p => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`).join(', ');
        return {
          isValid: false,
          error: `🔌 Select Input Port: ${targetMetadata.label} has multiple inputs. Please click the specific port: ${availablePorts}`
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
      const outputPort = sourceMetadata.output_ports.find(p => p.name === outputPortName)
                         || sourceMetadata.output_ports[0];

      if (!outputPort) {
        return {
          isValid: false,
          error: `❌ No output port found on ${sourceMetadata.label}. Available ports: ${sourceMetadata.output_ports.map(p => p.label).join(', ')}`
        };
      }

      // Derive category from type_ref to validate against legacy input_types
      const outputCategory = getCategoryFromTypeRef(outputPort.type_ref);
      const categoryToClassNames: Record<string, string[]> = {
        'dataset': ['NDDataset', 'SherpaDataset', 'array'],
        'target': ['array', 'list', 'any'],
        'model': ['PCAModel', 'PLSModel', 'PLSDAModel', 'HCAResult', 'any'],
        'config': ['dict', 'config', 'any'],
        'array': ['array', 'list', 'any'],
        'number': ['number', 'float', 'int', 'any'],
        'visualization': ['dict', 'plot', 'any'],
      };

      const inputTypes = targetMetadata.input_types;
      const compatibleClassNames = categoryToClassNames[outputCategory] || [outputCategory];

      // Check if any compatible class name is accepted by target
      const isCompatible = compatibleClassNames.some(className => inputTypes.includes(className))
                        || inputTypes.includes("any");

      if (!isCompatible) {
        return {
          isValid: false,
          error: `❌ Type Mismatch: ${sourceMetadata.label}'s "${outputPort.label}" port outputs "${typeRefToDisplayName(outputPort.type_ref)}" data, but ${targetMetadata.label} only accepts ${inputTypes.map(t => `"${t}"`).join(" or ")}. Try connecting from a different output port.`,
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
        error: `❌ Type Mismatch: ${sourceMetadata.label} outputs "${outputType}" data, but ${targetMetadata.label} only accepts ${inputTypes.map(t => `"${t}"`).join(" or ")}. Check the node documentation for compatible connections.`,
        dataType: outputType
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
        e.toPort === edge.toPort
    );
    if (!exists) {
      // Enforce max-1 cardinality on non-variadic ports:
      // if the target port already has an incoming edge, replace it.
      const targetNode = nodes.value.find(n => n.id === edge.to);
      const targetMeta = targetNode ? getNodeMetadata(targetNode.type) : null;
      if (targetMeta?.input_ports) {
        const toPort = edge.toPort || targetMeta.input_ports[0]?.name || 'default';
        const portMeta = targetMeta.input_ports.find(p => p.name === toPort);
        if (portMeta && !portMeta.variadic) {
          const existingIdx = edges.value.findIndex(
            e => e.to === edge.to && (e.toPort || targetMeta.input_ports![0]?.name || 'default') === toPort
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
    edges.value = edges.value.filter(
      (e) => !(e.from === from && e.to === to)
    );
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function setNodes(newNodes: WorkflowNode[]) {
    // Initialize execution state for all nodes
    for (const node of newNodes) {
      if (!node.executionState) {
        node.executionState = { status: "pending" };
      }
    }
    nodes.value = newNodes;
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function setEdges(newEdges: WorkflowEdge[]) {
    edges.value = newEdges.map((edge) => {
      const validation = validateEdge(edge);
      return {
        ...edge,
        isValid: validation.isValid,
        validationError: validation.error || null,
        dataType: validation.dataType || null,
      };
    });
    hasUnsavedChanges.value = true;
    markWorkflowStale();
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
    lastExecutionDiagnostics,
    workflowWarnings,
    availableDatasets,
    templates,
    templatesLoading,
    templatesError,

    // Node library state
    nodeLibrary,
    isLoadingNodeLibrary,
    nodeLibraryLoadError,
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
    setNodeExecutionState,
    getNodeExecutionState,
    markWorkflowStale,
    clearWorkflowStale,

    // API Actions
    saveWorkflow,
    loadWorkflow,
    listWorkflows,
    fetchTemplates,
    fetchTemplate,
    instantiateTemplate,
    deleteWorkflow,
    executeWorkflow,
    executeNode,
    executeTrial,
    exportToPython,
    exportToNotebook,
    downloadExport,
    fetchAvailableDatasets,
    fetchSpectroChemPyFiles,
    availableSpectroChemPyDatasets,
    clearSpectroChemPyFileCache,
    referenceDatasetCache,
    getReferenceDatasetOptions,
    eigenvectorDatasetCache,
    sklearnDatasetCache,
    fetchReferenceDatasets,
    fetchEigenvectorDatasets,
  };
});
