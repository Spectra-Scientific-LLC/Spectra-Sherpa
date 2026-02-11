import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { useLlmStore } from "@/stores/llm";
import { useWorkflowStore } from "@/stores/workflow";
import type { SherpaMessage, SherpaRecommendationPayload } from "@/types";

type SherpaState = "idle" | "syncing" | "chatting" | "error";

export const useSherpaStore = defineStore("sherpa", () => {
  const messages = ref<SherpaMessage[]>([]);
  const state = ref<SherpaState>("idle");
  const lastSyncError = ref<string | null>(null);
  const streamingIndex = ref<number | null>(null);

  // ── helpers ────────────────────────────────────────────────

  function getWs(): WebSocket | null {
    const llm = useLlmStore();
    return llm.wsRef;
  }

  function buildSyncPayload() {
    const workflow = useWorkflowStore();

    // Collect per-node execution results (shape, type) when available
    const nodes = workflow.nodes.map((n) => {
      const exec = n.executionState;
      return {
        node_id: String(n.id),
        node_type: n.type,
        label: n.type,
        parameters: n.params || {},
        result_shape: exec?.output_shape ?? null,
        result_statistics: null,
      };
    });

    // Derive top-level data dimensions from the first DATA node with results
    let n_samples: number | null = null;
    let n_features: number | null = null;
    for (const n of workflow.nodes) {
      if (n.type === "DATA" && n.executionState?.output_shape) {
        const shape = n.executionState.output_shape;
        n_samples = shape[0] ?? null;
        n_features = shape[1] ?? null;
        break;
      }
    }

    return {
      workflow_id: workflow.workflowId,
      workflow_name: workflow.workflowName,
      tier: "summaries",
      nodes,
      edges: workflow.edges.map((e) => ({
        from_node_id: String(e.from),
        to_node_id: String(e.to),
        from_output: e.fromPort || "default",
        to_input: e.toPort || "default",
      })),
      n_samples,
      n_features,
    };
  }

  // ── actions ────────────────────────────────────────────────

  async function syncWorkflow(): Promise<void> {
    const llm = useLlmStore();
    try {
      await llm.connect();
    } catch {
      lastSyncError.value = "WebSocket not connected";
      state.value = "error";
      messages.value.push({
        role: "system",
        content: "Unable to connect to the server. Please try again.",
      });
      return;
    }

    const workflow = useWorkflowStore();
    if (!workflow.workflowId) {
      messages.value.push({
        role: "system",
        content:
          "No workflow is currently loaded. Open or create a workflow first.",
      });
      return;
    }

    state.value = "syncing";
    lastSyncError.value = null;

    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      lastSyncError.value = "WebSocket not ready";
      state.value = "error";
      messages.value.push({
        role: "system",
        content: "Connection is not ready. Please try again in a moment.",
      });
      return;
    }

    ws.send(
      JSON.stringify({
        action: "sherpa_sync",
        payload: buildSyncPayload(),
      })
    );

    // Timeout: if no response within 90s, reset state.
    // Engine analysis with multi-round tool calls can take 30-60s.
    const syncTimeout = window.setTimeout(() => {
      if (state.value === "syncing") {
        state.value = "idle";
        messages.value.push({
          role: "system",
          content:
            "Sherpa sync timed out. The service may be unavailable.",
        });
      }
    }, 90_000);

    const unwatch = watch(
      () => state.value,
      (newState) => {
        if (newState !== "syncing") {
          clearTimeout(syncTimeout);
          unwatch();
        }
      }
    );
  }

  async function sendMessage(message: string): Promise<void> {
    if (!message.trim()) return;

    const llm = useLlmStore();
    try {
      await llm.connect();
    } catch {
      messages.value.push({
        role: "assistant",
        content: "Unable to connect. Check the server and try again.",
      });
      return;
    }

    messages.value.push({ role: "user", content: message });

    const workflow = useWorkflowStore();
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      messages.value.push({
        role: "system",
        content: "Connection is not ready. Please try again in a moment.",
      });
      return;
    }

    state.value = "chatting";
    ws.send(
      JSON.stringify({
        action: "sherpa_chat",
        payload: {
          message,
          workflow_id: workflow.workflowId,
          workflow_context: buildSyncPayload(),
          history: messages.value
            .slice(-10)
            .map((m) => ({ role: m.role, content: m.content })),
        },
      })
    );
  }

  function clearMessages(): void {
    messages.value = [];
    state.value = "idle";
    lastSyncError.value = null;
    streamingIndex.value = null;
  }

  // ── WebSocket message handler ──────────────────────────────

  /* eslint-disable @typescript-eslint/no-explicit-any */
  function handleWsMessage(payload: any): void {
    if (payload.type === "sherpa_recommendations") {
      state.value = "idle";
      const recs: SherpaRecommendationPayload[] = (
        payload.payload || []
      ).map((r: any) => ({
        suggestion_id: r.suggestion_id,
        workflow_id: r.workflow_id,
        category: r.category,
        title: r.title,
        explanation: r.explanation,
        confidence: r.confidence,
        has_patch: !!r.patch,
      }));

      if (recs.length === 0) {
        messages.value.push({
          role: "assistant",
          content:
            "Your workflow looks good -- no specific recommendations at this time.",
        });
      } else {
        for (const rec of recs) {
          const pct = Math.round(rec.confidence * 100);
          messages.value.push({
            role: "assistant",
            content: `**${rec.title}** (${rec.category}, ${pct}% confidence)\n\n${rec.explanation}`,
            recommendations: [rec],
          });
        }
      }
    } else if (payload.type === "sherpa_chat_start") {
      // Transition from "syncing" to "chatting" so the sync timeout is cleared
      if (state.value === "syncing" || state.value === "idle") {
        state.value = "chatting";
      }
      streamingIndex.value = messages.value.length;
      messages.value.push({ role: "assistant", content: "" });
    } else if (payload.type === "sherpa_chat_chunk") {
      if (streamingIndex.value !== null) {
        messages.value[streamingIndex.value].content += payload.chunk;
      }
    } else if (payload.type === "sherpa_chat_done") {
      state.value = "idle";
      streamingIndex.value = null;
    } else if (payload.type === "sherpa_status") {
      const connected = payload.payload?.connected;
      if (!connected) {
        const reason = payload.payload?.reason || "unknown";
        lastSyncError.value = `Sherpa unavailable: ${reason}`;
        state.value = "error";
        messages.value.push({
          role: "system",
          content: `Sherpa Advisor is not available (${reason}). Configure the cloud connection in Settings > Integrations.`,
        });
      }
    } else if (payload.type === "sherpa_error") {
      state.value = "error";
      lastSyncError.value = payload.detail || "Sherpa error";
      messages.value.push({
        role: "system",
        content: payload.detail || "An error occurred communicating with Sherpa.",
      });
    }
  }
  /* eslint-enable @typescript-eslint/no-explicit-any */

  // ── lifecycle ──────────────────────────────────────────────

  function _onSherpaEvent(event: Event): void {
    handleWsMessage((event as CustomEvent).detail);
  }

  function init(): void {
    window.addEventListener("sherpa-ws-message", _onSherpaEvent);
  }

  function dispose(): void {
    window.removeEventListener("sherpa-ws-message", _onSherpaEvent);
  }

  return {
    messages,
    state,
    lastSyncError,
    syncWorkflow,
    sendMessage,
    clearMessages,
    init,
    dispose,
  };
});
