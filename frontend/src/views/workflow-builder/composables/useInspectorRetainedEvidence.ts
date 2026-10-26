import { computed, ref, type Ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { NodeTypeMetadata } from "@/types";
import { buildNodeOutput, type NodeOutput, type PortOutput } from "@/utils/nodeOutput";
import type { NodeScientificValueDescriptors } from "@/stores/workflow-types";
import { bindPresentationInput } from "@/utils/featureRulePresentation";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";

export interface InspectorInputConnection {
  nodeId: string;
  nodeType: string;
  nodeLabel: string;
  port: string;
  toPort?: string;
  data?: NodeOutput | PortOutput | null;
}

interface RetainedEvidenceOptions {
  identity: () => readonly ScopeIdentity[];
  nodeId: () => string | undefined;
  projectId: () => number | null;
  runId: () => number | null;
  evidenceScope: () => string;
  metadata: Ref<NodeTypeMetadata | null>;
  output: Ref<NodeOutput | null>;
  presentationId: Ref<string | null>;
  inputs: () => InspectorInputConnection[];
  descriptors: (nodeId: string) => NodeScientificValueDescriptors | null;
  unavailable: (message: string) => void;
  closeContextDialogs: () => void;
}

/** Hydrates same-run evidence, then delegates to the shared scientific projectors. */
export function useInspectorRetainedEvidence(options: RetainedEvidenceOptions) {
  const exactQuickPlotOutput = ref<NodeOutput | null>(null);
  const exactQuickPlotInputs = ref<Record<string, PortOutput | NodeOutput | null> | null>(null);
  const quickPlotLoading = ref(false);
  const quickPlotEvidenceError = ref("");
  const showQuickPlotModal = ref(false);
  const showDataTableModal = ref(false);
  const requests = useScopedRequest(options.identity, () => {
    showQuickPlotModal.value = false;
    showDataTableModal.value = false;
    exactQuickPlotOutput.value = null;
    exactQuickPlotInputs.value = null;
    quickPlotEvidenceError.value = "";
    quickPlotLoading.value = false;
    options.closeContextDialogs();
  });
  const quickPlotInputs = computed(() => Object.fromEntries(options.inputs().map(connection =>
    [connection.toPort || "default", connection.data ?? null],
  )));
  const quickPlotResolvedInputs = computed(() => exactQuickPlotInputs.value ?? quickPlotInputs.value);
  const quickPlotPrimaryInput = computed(() =>
    exactQuickPlotInputs.value ? Object.values(exactQuickPlotInputs.value)[0] : options.inputs()[0]?.data,
  );
  const quickPlotNodeOutput = computed(() => {
    if (quickPlotEvidenceError.value) return null;
    const source = exactQuickPlotOutput.value ?? options.output.value;
    const resolved = resolveScientificPresentation(options.metadata.value, source, options.presentationId.value);
    return bindPresentationInput(
      projectScientificPresentation(source, resolved),
      resolved?.presentation.input_binding,
      quickPlotResolvedInputs.value,
    );
  });

  async function openRetainedEvidence(view: "plot" | "table" | "detail") {
    const ticket = requests.begin();
    const show = () => {
      if (!ticket.isCurrent()) return;
      if (view === "plot") showQuickPlotModal.value = true;
      else if (view === "table") showDataTableModal.value = true;
    };
    const evidence = () => ({
      output: exactQuickPlotOutput.value ?? options.output.value,
      inputs: quickPlotResolvedInputs.value,
      isCurrent: ticket.isCurrent,
    });
    const runId = options.runId();
    const projectId = options.projectId();
    const nodeId = options.nodeId();
    if (options.evidenceScope() !== "restored_summary") {
      show();
      return evidence();
    }
    if (runId == null || projectId == null || !nodeId) {
      exactQuickPlotOutput.value = null;
      exactQuickPlotInputs.value = null;
      quickPlotLoading.value = false;
      quickPlotEvidenceError.value = "The retained output has no complete run, project, and node identity. Reopen the run to inspect it.";
      if (view === "plot") show();
      else options.unavailable(quickPlotEvidenceError.value);
      return null;
    }
    quickPlotLoading.value = true;
    quickPlotEvidenceError.value = "";
    exactQuickPlotOutput.value = null;
    exactQuickPlotInputs.value = null;
    const read = async (sourceNodeId: string, port: string): Promise<unknown> => {
      const response = await api.get(
        `/runs/${runId}/outputs/${encodeURIComponent(sourceNodeId)}/${encodeURIComponent(port)}`,
        { params: { project_id: projectId }, signal: ticket.signal },
      );
      return response.data.value;
    };
    try {
      const source = options.output.value;
      const selected = resolveScientificPresentation(options.metadata.value, source, options.presentationId.value);
      // A detail sheet can select any of the node's presentations. Keep every
      // retained port, rather than handing it a projected or bounded preview.
      const availablePorts = Object.keys(source?.ports ?? {});
      const sourcePorts = view === "detail"
        ? (availablePorts.length ? availablePorts : source ? [source.primary_port ?? "default"] : [])
        : selected?.sourcePorts ?? [source?.primary_port ?? "default"];
      const binding = selected?.presentation.output_binding;
      const labelsField = selected?.presentation.sample_labels_field;
      const inputBinding = selected?.presentation.input_binding;
      // Preserve the existing combined PCA view using only same-run companions.
      const summaryPorts = view === "plot" && selected?.presentation.kind === "pca_scores"
        ? ["variable_correlations", "explained_variance", "loadings"].filter(port => source?.ports?.[port]) : [];
      const retainedPorts = view === "detail" && !source ? [] : [...new Set([
        ...(view !== "table" && source?.metadata.workflow_population ? ["__workflow_population"] : []),
        // Retain the original primary context when plotting another port.
        // Otherwise rebuilding a one-port node changes shared model labels.
        ...(view === "plot" && source?.primary_port ? [source.primary_port] : []),
        ...sourcePorts, ...(binding ? [binding[0]] : []), ...summaryPorts, ...(labelsField ? [labelsField] : []),
      ])];
      let connections = options.inputs();
      if (view === "table") {
        connections = inputBinding ? connections.filter(connection => (connection.toPort || "default") === inputBinding[0]) : [];
      } else if (view === "detail" && !source) {
        // An unexecuted node remains editable; load only inputs with retained
        // evidence, rather than requesting results from unexecuted ancestors.
        connections = connections.filter(connection => connection.data);
      }
      const [outputs, inputs] = await Promise.all([
        Promise.all(retainedPorts.map(async port => {
          if (port !== "__workflow_population") return [port, await read(nodeId, port)] as const;
          try { return [port, await read(nodeId, port)] as const; }
          catch {
            // Optional display evidence cannot invalidate exact active scores
            // or thresholds. Never fall back to its bounded preview coordinates.
            return [port, { sources: (source?.metadata.workflow_population as { sources?: unknown })?.sources ?? {},
              availability: "unavailable", outputs: {}, reason: "Excluded overlay was not retained; active results remain available." }] as const;
          }
        })),
        Promise.all(connections.map(async connection => {
          let value: unknown;
          try {
            value = await read(connection.nodeId, connection.port);
          } catch (error) {
            // Editing a node with no result must remain possible when an
            // ancestor's retained preview is unavailable. Keep it unavailable,
            // rather than passing the bounded preview off as exact input.
            if (view !== "detail" || source) throw error;
            value = null;
          }
          return [connection.toPort || "default", value] as const;
        })),
      ]);
      if (!ticket.isCurrent()) return null;
      const contract = source?.presentation_contract;
      const diagnostics = source?.metadata?.diagnostics;
      // Same normalizer used by node-detail/useNodeOutput. This surface carries
      // a contract, not a complete ExecutedPresentationRecord; never fabricate one.
      exactQuickPlotOutput.value = source ? buildNodeOutput(
        Object.fromEntries(outputs), options.metadata.value?.output_ports,
        diagnostics && typeof diagnostics === "object" ? diagnostics as Record<string, unknown> : null,
        options.descriptors(nodeId), contract,
      ) : null;
      if (exactQuickPlotOutput.value && source?.model_id) {
        exactQuickPlotOutput.value.model_id = source.model_id;
      }
      exactQuickPlotInputs.value = Object.fromEntries(inputs.map(([port, value]) => {
        if (value == null) return [port, null];
        const record = value && typeof value === "object" ? value as Record<string, unknown> : null;
        return [port, {
          data: Array.isArray(record?.data) ? record.data : Array.isArray(value) ? value : [],
          metadata: record?.metadata && typeof record.metadata === "object"
            ? record.metadata as Record<string, unknown> : {}, value,
        }];
      }));
      return evidence();
    } catch {
      if (!ticket.isCurrent()) return null;
      quickPlotEvidenceError.value = "The exact retained output is unavailable. The compact history summary cannot be used as full evidence.";
      if (view !== "plot") options.unavailable(quickPlotEvidenceError.value);
      return null;
    } finally {
      if (ticket.isCurrent()) {
        quickPlotLoading.value = false;
        if (view === "plot" || !quickPlotEvidenceError.value) show();
      }
    }
  }
  return {
    exactQuickPlotOutput, exactQuickPlotInputs, quickPlotLoading, quickPlotEvidenceError,
    quickPlotInputs, quickPlotResolvedInputs, quickPlotPrimaryInput, quickPlotNodeOutput,
    showQuickPlotModal, showDataTableModal, openRetainedEvidence,
    openQuickPlot: () => openRetainedEvidence("plot"),
    openDataTable: () => openRetainedEvidence("table"),
    prepareTrialEvidence: () => openRetainedEvidence("detail"),
  };
}
