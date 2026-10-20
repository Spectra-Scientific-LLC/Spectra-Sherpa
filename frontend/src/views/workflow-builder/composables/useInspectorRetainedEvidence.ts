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

  async function openRetainedEvidence(view: "plot" | "table"): Promise<void> {
    const ticket = requests.begin();
    const show = () => {
      if (!ticket.isCurrent()) return;
      if (view === "plot") showQuickPlotModal.value = true;
      else showDataTableModal.value = true;
    };
    const runId = options.runId();
    const projectId = options.projectId();
    const nodeId = options.nodeId();
    if (options.evidenceScope() !== "restored_summary") {
      show();
      return;
    }
    if (runId == null || projectId == null || !nodeId) {
      exactQuickPlotOutput.value = null;
      exactQuickPlotInputs.value = null;
      quickPlotLoading.value = false;
      quickPlotEvidenceError.value = "The retained output has no complete run, project, and node identity. Reopen the run to inspect it.";
      if (view === "plot") show();
      else options.unavailable(quickPlotEvidenceError.value);
      return;
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
      const sourcePorts = selected?.sourcePorts ?? [source?.primary_port ?? "default"];
      const binding = selected?.presentation.output_binding;
      const labelsField = selected?.presentation.sample_labels_field;
      const inputBinding = selected?.presentation.input_binding;
      // Preserve the existing combined PCA view using only same-run companions.
      const summaryPorts = view === "plot" && selected?.presentation.kind === "pca_scores"
        ? ["variable_correlations", "explained_variance", "loadings"].filter(port => source?.ports?.[port]) : [];
      const retainedPorts = [...new Set([
        ...sourcePorts, ...(binding ? [binding[0]] : []), ...summaryPorts, ...(labelsField ? [labelsField] : []),
      ])];
      const [outputs, inputs] = await Promise.all([
        Promise.all(retainedPorts.map(async port => [port, await read(nodeId, port)] as const)),
        Promise.all((view === "plot" ? options.inputs()
          : inputBinding ? options.inputs().filter(connection => (connection.toPort || "default") === inputBinding[0]) : [])
          .map(async connection => [connection.toPort || "default", await read(connection.nodeId, connection.port)] as const)),
      ]);
      if (!ticket.isCurrent()) return;
      const contract = source?.presentation_contract;
      const diagnostics = source?.metadata?.diagnostics;
      // Same normalizer used by node-detail/useNodeOutput. This surface carries
      // a contract, not a complete ExecutedPresentationRecord; never fabricate one.
      exactQuickPlotOutput.value = buildNodeOutput(
        Object.fromEntries(outputs), options.metadata.value?.output_ports,
        diagnostics && typeof diagnostics === "object" ? diagnostics as Record<string, unknown> : null,
        options.descriptors(nodeId), contract,
      );
      exactQuickPlotInputs.value = Object.fromEntries(inputs.map(([port, value]) => {
        const record = value && typeof value === "object" ? value as Record<string, unknown> : null;
        return [port, {
          data: Array.isArray(record?.data) ? record.data : Array.isArray(value) ? value : [],
          metadata: record?.metadata && typeof record.metadata === "object"
            ? record.metadata as Record<string, unknown> : {}, value,
        }];
      }));
    } catch {
      if (!ticket.isCurrent()) return;
      quickPlotEvidenceError.value = "The exact retained output is unavailable. The compact history summary cannot be used as full evidence.";
      if (view === "table") options.unavailable(quickPlotEvidenceError.value);
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
  };
}
