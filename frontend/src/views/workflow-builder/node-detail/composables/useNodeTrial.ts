import { ref, onMounted, onUnmounted, type Ref } from "vue";
import type { ToastServiceMethods } from "primevue/toastservice";
import type { NodeOutput } from "@/utils/nodeOutput";
import api from "@/api/client";

export const STORAGE_KEY = "node_detail_data";
export const BROADCAST_CHANNEL_NAME = "workflow_node_updates";

type AddLog = (
  type: "info" | "success" | "error" | "warn",
  message: string,
  details?: string,
) => void;

interface UseNodeTrialDeps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  nodeData: Ref<any>;
  localParams: Ref<Record<string, unknown>>;
  nodeType: Ref<string>;
  addLog: AddLog;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  normalizeNodeOutput: (result: any) => NodeOutput;
  toast: ToastServiceMethods;
}

export function useNodeTrial({
  nodeData,
  localParams,
  nodeType,
  addLog,
  normalizeNodeOutput,
  toast,
}: UseNodeTrialDeps) {
  const isExecuting = ref(false);
  const broadcastChannel = ref<BroadcastChannel | null>(null);

  const broadcastParamsUpdate = () => {
    const updateMessage = {
      type: "node_params_updated",
      nodeId: nodeData.value?.id,
      nodeType: nodeData.value?.type,
      params: { ...localParams.value },
      timestamp: Date.now(),
    };

    if (broadcastChannel.value) {
      broadcastChannel.value.postMessage(updateMessage);
    }

    const updatedData = {
      ...nodeData.value,
      params: { ...localParams.value },
      _saved: true,
      _savedAt: Date.now(),
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(updatedData));
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: STORAGE_KEY,
        newValue: JSON.stringify(updatedData),
      }),
    );
  };

  const handleRunTrial = async () => {
    if (!nodeData.value) return;

    isExecuting.value = true;
    addLog("info", "Trial started", `Running ${nodeType.value} with trial settings`);

    toast.add({
      severity: "info",
      summary: "Running Trial",
      detail: "Executing with current settings...",
      life: 2000,
    });

    try {
      const workflowNodes = nodeData.value.workflowNodes || [];
      const workflowEdges = nodeData.value.workflowEdges || [];

      if (workflowNodes.length === 0) {
        throw new Error(
          "No workflow nodes found. Please reopen from the workflow inspector.",
        );
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const trialNodes = workflowNodes.map((node: any) => ({
        node_id: String(node.id),
        node_type: node.type,
        parameters: { ...(node.params || {}) },
      }));

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const trialEdges = workflowEdges.map((edge: any) => ({
        from_node_id: String(edge.from),
        to_node_id: String(edge.to),
        from_output: edge.fromPort || "default",
        to_input: edge.toPort || "default",
      }));

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const initialData: Record<string, any> = {};
      if (nodeData.value.inputData?.experiment_id) {
        const inputConnections = nodeData.value.inputConnections || [];
        for (const conn of inputConnections) {
          if (conn.nodeType === "data.source") {
            initialData[String(conn.nodeId)] = {
              experiment_id: nodeData.value.inputData.experiment_id,
              source: nodeData.value.inputData.source || "experiment",
            };
          }
        }
      }

      const mappedTrialParams = { ...localParams.value };

      const trialPayload = {
        target_node_id: String(nodeData.value.id),
        trial_params: mappedTrialParams,
        nodes: trialNodes,
        edges: trialEdges,
        initial_data: Object.keys(initialData).length > 0 ? initialData : null,
      };

      const changes: string[] = [];
      for (const [key, value] of Object.entries(mappedTrialParams)) {
        const oldValue = nodeData.value.params?.[key];
        if (oldValue !== undefined && oldValue !== value) {
          changes.push(`${key}: ${oldValue} → ${value}`);
        }
      }
      if (changes.length > 0) {
        addLog("info", "Parameter changes", changes.join(", "));
      }

      const response = await api.post("/workflows/trial/execute", trialPayload);

      isExecuting.value = false;

      if (response.data.status === "error" || response.data.error) {
        addLog("error", "Trial failed", response.data.error || "Unknown error");
        toast.add({
          severity: "error",
          summary: "Trial Failed",
          detail: response.data.error || "Execution failed",
          life: 5000,
        });
        return;
      }

      if (response.data.result) {
        const output = normalizeNodeOutput(response.data.result);

        nodeData.value = {
          ...nodeData.value,
          output: output,
        };

        let outputSummary = "Trial completed";
        if (output.data && Array.isArray(output.data)) {
          const rows = output.data.length;
          const cols = Array.isArray(output.data[0]) ? output.data[0].length : 1;
          outputSummary = `Output: ${rows} × ${cols} matrix`;
        }

        addLog("success", "Trial completed", outputSummary);
        toast.add({
          severity: "success",
          summary: "Trial Complete",
          detail: outputSummary,
          life: 3000,
        });
      } else {
        addLog("warn", "Trial completed", "No output data returned");
        toast.add({
          severity: "warn",
          summary: "Trial Complete",
          detail: "Execution completed but no output data was returned",
          life: 3000,
        });
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } catch (error: any) {
      isExecuting.value = false;
      const message =
        error?.response?.data?.detail || error?.message || String(error);
      addLog("error", "Trial failed", message);
      toast.add({
        severity: "error",
        summary: "Trial Failed",
        detail: message,
        life: 5000,
      });
    }
  };

  // NodeDetailView is a sender-only participant on the BroadcastChannel;
  // it posts `node_params_updated` via broadcastParamsUpdate() and does not
  // need to receive anything back.
  onMounted(() => {
    try {
      broadcastChannel.value = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    } catch (e) {
      console.warn("[NodeDetailView] BroadcastChannel not supported:", e);
    }
  });

  onUnmounted(() => {
    if (broadcastChannel.value) {
      broadcastChannel.value.close();
      broadcastChannel.value = null;
    }
  });

  return {
    isExecuting,
    broadcastChannel,
    broadcastParamsUpdate,
    handleRunTrial,
  };
}
