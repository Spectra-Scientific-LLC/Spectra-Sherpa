/* eslint-disable @typescript-eslint/no-explicit-any -- assistant sync payloads intentionally preserve flexible node parameter/result shapes. */
import { defineStore } from "pinia";
import { ref, watch, type WatchStopHandle } from "vue";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT, getSherpaChatAction } from "@/lib/sherpaWs";
import { useDataStore } from "@/stores/data";
import { useLlmStore } from "@/stores/llm";
import { useNotificationStore } from "@/stores/notification";
import { useWorkflowStore } from "@/stores/workflow";
import type { SherpaMessage, SherpaRecommendationPayload } from "@/types";

type SherpaState = "idle" | "syncing" | "chatting" | "error";

export interface PeaksResult {
  /** Structured peaks array (if server provides it) */
  peaks?: Array<{ wavenumber: number; assignment?: string; confidence?: number }>;
  /** Text analysis from server (PRD-defined response shape) */
  response?: string;
}

export interface CodeResult {
  /** Extracted code string */
  code: string;
  language?: string;
  /** Raw text analysis from server */
  response?: string;
}

export interface ToolEvent {
  tool_name: string;
  status: "started" | "completed";
  result?: unknown;
}

export const useSherpaStore = defineStore("sherpa", () => {
  const messages = ref<SherpaMessage[]>([]);
  const state = ref<SherpaState>("idle");
  const lastSyncError = ref<string | null>(null);
  const streamingIndex = ref<number | null>(null);
  const notifications = useNotificationStore();

  // Subscription-gated feature results
  const lastPeaksResult = ref<PeaksResult | null>(null);
  const lastCodeResult = ref<CodeResult | null>(null);
  const activeTools = ref<ToolEvent[]>([]);
  const subscriptionRequired = ref<string | null>(null);
  let communicationTimer: ReturnType<typeof setTimeout> | null = null;
  let stopLlmWatch: WatchStopHandle | null = null;
  let isInitialized = false;

  // ── helpers ────────────────────────────────────────────────

  /** Extract code from a markdown response (```lang\n...\n```) */
  function _extractCodeFromMarkdown(text: string): string {
    const match = text.match(/```(?:\w+)?\n([\s\S]*?)```/);
    return match ? match[1].trim() : text.trim();
  }

  function getWs(): WebSocket | null {
    const llm = useLlmStore();
    return llm.wsRef;
  }

  function clearCommunicationTimer(): void {
    if (communicationTimer !== null) {
      clearTimeout(communicationTimer);
      communicationTimer = null;
    }
  }

  function scheduleCommunicationNotice(kind: "sync" | "chat"): void {
    clearCommunicationTimer();
    communicationTimer = window.setTimeout(() => {
      if (kind === "sync" && state.value === "syncing") {
        notifications.add({
          source: "system",
          severity: "info",
          title: "Sherpa Advisor",
          message: "Sherpa Advisor is reviewing the workflow.",
        });
      } else if (kind === "chat" && state.value === "chatting" && streamingIndex.value === null) {
        notifications.add({
          source: "system",
          severity: "info",
          title: "Sherpa Advisor",
          message: "Sherpa Advisor is preparing a response.",
        });
      }
    }, 4000);
  }

  function finalizeCommunication(): void {
    clearCommunicationTimer();
  }

  function recoverFromTransport(detail: string): void {
    if (state.value !== "chatting" && state.value !== "syncing") {
      return;
    }
    finalizeCommunication();
    state.value = "idle";
    streamingIndex.value = null;
    lastSyncError.value = detail;
    messages.value.push({
      role: "system",
      content: detail,
    });
    notifications.add({
      source: "system",
      severity: "warning",
      title: "Sherpa Advisor",
      message: detail,
    });
  }

  function buildSyncPayload() {
    const workflow = useWorkflowStore();
    const dataStore = useDataStore();

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

    // Include dataset metadata so the LLM knows the data context
    const dsInfo = dataStore.catalogDatasetInfo as Record<string, unknown> | null;
    const dsMeta = dsInfo?.metadata as Record<string, unknown> | undefined;
    const dataset_context = dsInfo ? {
      is_time_series: dsInfo.is_time_series ?? dsMeta?.is_time_series ?? null,
      is_spectra: dsInfo.is_spectra ?? dsMeta?.is_spectra ?? null,
      technique: dsInfo.technique ?? dsMeta?.spectral_technique ?? null,
      x_title: dsInfo.x_title ?? dsMeta?.x_title ?? null,
      x_units: dsInfo.x_units ?? dsMeta?.x_units ?? null,
      data_quantity: dsInfo.data_quantity ?? dsMeta?.data_quantity ?? null,
      value_units: dsMeta?.value_units ?? null,
      description: dsInfo.description ?? null,
    } : null;

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
      dataset_context,
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
    scheduleCommunicationNotice("sync");

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
        action: SHERPA_WS_ACTION.sync,
        payload: buildSyncPayload(),
      })
    );

    // Timeout: if no response within 180s, reset state.
    // Engine analysis with multi-round tool calls can take 60-120s on Opus.
    const syncTimeout = window.setTimeout(() => {
      if (state.value === "syncing") {
        state.value = "idle";
        messages.value.push({
          role: "system",
          content:
            "Sherpa sync timed out. The service may be unavailable.",
        });
      }
    }, 180_000);

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

  async function sendMessage(message: string, useTools = false): Promise<void> {
    if (!message.trim()) return;

    const workflow = useWorkflowStore();
    if (!workflow.workflowId) {
      const detail = "Load or create a workflow before asking Sherpa Advisor a question.";
      lastSyncError.value = detail;
      notifications.add({
        source: "system",
        severity: "info",
        title: "Sherpa Advisor",
        message: detail,
      });
      messages.value.push({
        role: "system",
        content: detail,
      });
      return;
    }

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

    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      messages.value.push({
        role: "system",
        content: "Connection is not ready. Please try again in a moment.",
      });
      return;
    }

    state.value = "chatting";
    activeTools.value = [];
    scheduleCommunicationNotice("chat");

    // Safety timeout: if no chatDone arrives within 120s, reset state
    const chatTimeout = window.setTimeout(() => {
      if (state.value === "chatting") {
        finalizeCommunication();
        state.value = "idle";
        streamingIndex.value = null;
        notifications.add({
          source: "system",
          severity: "warning",
          title: "Sherpa Advisor",
          message: "Sherpa Advisor is taking longer than expected. Please try again.",
        });
        messages.value.push({
          role: "system",
          content: "Chat response timed out. The server may be processing a complex request — check the workflow and try again.",
        });
      }
    }, 120_000);
    const unwatchChat = watch(
      () => state.value,
      (newState) => {
        if (newState !== "chatting") {
          clearTimeout(chatTimeout);
          unwatchChat();
        }
      }
    );

    ws.send(
      JSON.stringify({
        action: getSherpaChatAction(useTools),
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
    finalizeCommunication();
    messages.value = [];
    state.value = "idle";
    lastSyncError.value = null;
    streamingIndex.value = null;
    lastPeaksResult.value = null;
    lastCodeResult.value = null;
    activeTools.value = [];
    subscriptionRequired.value = null;
  }

  // ── WebSocket message handler ──────────────────────────────

   
  function handleWsMessage(payload: any): void {
    if (payload.type === SHERPA_WS_EVENT.recommendations) {
      finalizeCommunication();
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
    } else if (payload.type === SHERPA_WS_EVENT.chatStart) {
      finalizeCommunication();
      // Transition from "syncing" to "chatting" so the sync timeout is cleared
      if (state.value === "syncing" || state.value === "idle") {
        state.value = "chatting";
      }
      streamingIndex.value = messages.value.length;
      messages.value.push({ role: "assistant", content: "" });
    } else if (payload.type === SHERPA_WS_EVENT.chatChunk) {
      if (streamingIndex.value !== null) {
        messages.value[streamingIndex.value].content += payload.chunk;
      }
    } else if (payload.type === SHERPA_WS_EVENT.chatDone) {
      finalizeCommunication();
      state.value = "idle";
      streamingIndex.value = null;
    } else if (payload.type === SHERPA_WS_EVENT.status) {
      const connected = payload.payload?.connected;
      if (!connected) {
        finalizeCommunication();
        const reason = payload.payload?.reason || "unknown";
        lastSyncError.value = `Sherpa unavailable: ${reason}`;
        state.value = "error";
        notifications.add({
          source: "system",
          severity: "warning",
          title: "Sherpa Advisor",
          message: `Sherpa Advisor is unavailable (${reason}).`,
        });
        messages.value.push({
          role: "system",
          content: `Sherpa Advisor is not available (${reason}). Configure the cloud connection in Settings > Integrations.`,
        });
      }
    } else if (payload.type === SHERPA_WS_EVENT.peaksResult) {
      // Server returns {response: "text..."} and optionally {peaks: [...]}
      // WS handler flattens result fields alongside type
      lastPeaksResult.value = {
        peaks: payload.peaks,
        response: payload.response,
      };
    } else if (payload.type === SHERPA_WS_EVENT.peaksError) {
      lastPeaksResult.value = null;
      messages.value.push({
        role: "system",
        content: payload.detail || "Peak identification failed.",
      });
    } else if (payload.type === SHERPA_WS_EVENT.codeResult) {
      // Server returns {response: "```python\n...```"} and optionally {code, language}
      const rawCode = payload.code || _extractCodeFromMarkdown(payload.response || "");
      lastCodeResult.value = {
        code: rawCode,
        language: payload.language || "python",
        response: payload.response,
      };
    } else if (payload.type === SHERPA_WS_EVENT.codeError) {
      lastCodeResult.value = null;
      messages.value.push({
        role: "system",
        content: payload.detail || "Code generation failed.",
      });
    } else if (payload.type === SHERPA_WS_EVENT.toolStart) {
      activeTools.value.push({
        tool_name: payload.tool_name || "unknown",
        status: "started",
      });
    } else if (payload.type === SHERPA_WS_EVENT.toolResult) {
      const idx = activeTools.value.findIndex(
        (t) => t.tool_name === payload.tool_name && t.status === "started"
      );
      if (idx >= 0) {
        activeTools.value[idx] = {
          ...activeTools.value[idx],
          status: "completed",
          result: payload.result,
        };
      }
    } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
      finalizeCommunication();
      subscriptionRequired.value = payload.detail || "This feature requires a subscription.";
      state.value = "idle";
      notifications.add({
        source: "system",
        severity: "warning",
        title: "Sherpa Advisor",
        message: payload.detail || "This feature requires a Sherpa subscription.",
      });
      messages.value.push({
        role: "system",
        content: payload.detail || "This feature requires a Sherpa subscription. Upgrade your plan to unlock it.",
      });
    } else if (payload.type === SHERPA_WS_EVENT.error) {
      finalizeCommunication();
      state.value = "error";
      const isDemoLimitError =
        payload.limit_type === "sherpa"
        || payload.limit_type === "execution"
        || typeof payload.message === "string";
      if (isDemoLimitError) {
        const message = payload.message || "Demo limit reached";
        lastSyncError.value = message;
        notifications.add({
          source: "system",
          severity: "warning",
          title: "Sherpa Advisor",
          message,
        });
        messages.value.push({
          role: "system",
          content: message,
        });
      } else {
        lastSyncError.value = payload.detail || "Sherpa error";
        notifications.add({
          source: "system",
          severity: "warning",
          title: "Sherpa Advisor",
          message: payload.detail || "An error occurred communicating with Sherpa.",
        });
        messages.value.push({
          role: "system",
          content: payload.detail || "An error occurred communicating with Sherpa.",
        });
      }
    }
  }
   

  // ── lifecycle ──────────────────────────────────────────────

  function _onSherpaEvent(event: Event): void {
    handleWsMessage((event as CustomEvent).detail);
  }

  function _onTransportEvent(event: Event): void {
    const detail = (event as CustomEvent).detail as { kind?: string; detail?: string | null };
    const message = detail.detail
      || (detail.kind === "unauthorized"
        ? "Authorization failed while contacting Sherpa Advisor."
        : "Connection lost during Sherpa request. Please try again.");
    recoverFromTransport(message);
  }

  function init(): void {
    if (isInitialized) {
      return;
    }
    isInitialized = true;
    window.addEventListener("sherpa-ws-message", _onSherpaEvent);
    window.addEventListener("app-ws-transport", _onTransportEvent);
    const llm = useLlmStore();
    stopLlmWatch = watch(
      () => llm.connectionStatus,
      (newStatus) => {
        if (newStatus === "disconnected") {
          recoverFromTransport("Connection lost during Sherpa request. Please try again.");
        }
      }
    );
  }

  function dispose(): void {
    finalizeCommunication();
    isInitialized = false;
    window.removeEventListener("sherpa-ws-message", _onSherpaEvent);
    window.removeEventListener("app-ws-transport", _onTransportEvent);
    stopLlmWatch?.();
    stopLlmWatch = null;
  }

  return {
    messages,
    state,
    lastSyncError,
    lastPeaksResult,
    lastCodeResult,
    activeTools,
    subscriptionRequired,
    syncWorkflow,
    sendMessage,
    clearMessages,
    init,
    dispose,
  };
});
