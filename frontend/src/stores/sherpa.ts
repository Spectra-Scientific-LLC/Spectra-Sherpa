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
  const lastActivitySummary = ref<string | null>(null);
  let communicationTimer: ReturnType<typeof setTimeout> | null = null;
  let activeChatTimeout: ReturnType<typeof setTimeout> | null = null;
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

  function _truncateForLog(text: string, max = 180): string {
    const normalized = text.replace(/\s+/g, " ").trim();
    if (normalized.length <= max) {
      return normalized;
    }
    return `${normalized.slice(0, max - 1)}…`;
  }

  function _notifySherpa(message: string, severity: "info" | "success" | "warning" | "error" = "info", detail?: string): void {
    notifications.add({
      source: "system",
      severity,
      title: "Sherpa Advisor",
      message,
      detail,
    });
  }

  function _formatTimingSuffix(timing: unknown): string {
    if (!timing || typeof timing !== "object") {
      return "";
    }
    const timingRecord = timing as Record<string, unknown>;
    const elapsedMs = timingRecord.elapsed_ms;
    const sinceLastMs = timingRecord.since_last_event_ms;
    const parts: string[] = [];

    if (typeof elapsedMs === "number" && Number.isFinite(elapsedMs)) {
      parts.push(`server ${(elapsedMs / 1000).toFixed(1)}s`);
    }
    if (typeof sinceLastMs === "number" && Number.isFinite(sinceLastMs)) {
      parts.push(`+${(sinceLastMs / 1000).toFixed(1)}s`);
    }

    return parts.length > 0 ? ` (${parts.join(", ")})` : "";
  }

  function _recordActivity(summary: string, options?: {
    notify?: boolean;
    severity?: "info" | "success" | "warning" | "error";
    detail?: string;
  }): void {
    lastActivitySummary.value = summary;
    if (options?.notify) {
      _notifySherpa(summary, options.severity ?? "info", options.detail);
    }
  }

  function _formatDemoLimitDetail(payload: Record<string, unknown>): string | undefined {
    const details: string[] = [];
    if (typeof payload.remaining === "number" && Number.isFinite(payload.remaining)) {
      details.push(`Remaining: ${payload.remaining}`);
    }
    if (
      typeof payload.session_expiry_hours === "number"
      && Number.isFinite(payload.session_expiry_hours)
    ) {
      details.push(
        `Usage resets after ${payload.session_expiry_hours} hour${payload.session_expiry_hours === 1 ? "" : "s"} of inactivity.`
      );
    }
    return details.length > 0 ? details.join("\n") : undefined;
  }

  function _inlineNotificationDetail(detail: string | undefined): string {
    if (!detail) {
      return "";
    }
    return ` ${detail.replace(/\n+/g, " ")}`;
  }

  function clearCommunicationTimer(): void {
    if (communicationTimer !== null) {
      clearTimeout(communicationTimer);
      communicationTimer = null;
    }
  }

  function clearActiveChatTimeout(): void {
    if (activeChatTimeout !== null) {
      clearTimeout(activeChatTimeout);
      activeChatTimeout = null;
    }
  }

  function scheduleActiveChatTimeout(): void {
    clearActiveChatTimeout();
    activeChatTimeout = window.setTimeout(() => {
      if (state.value === "chatting") {
        finalizeCommunication();
        state.value = "idle";
        streamingIndex.value = null;
        const timeoutMessage = lastActivitySummary.value
          ? `Sherpa Advisor timed out. Last activity: ${lastActivitySummary.value}`
          : "Sherpa Advisor is taking longer than expected. Please try again.";
        _notifySherpa(timeoutMessage, "warning");
        messages.value.push({
          role: "system",
          content:
            "Chat response timed out. The server may be processing a complex request — check the workflow and try again.",
        });
      }
    }, 120_000);
  }

  function noteChatActivity(): void {
    if (state.value === "chatting") {
      scheduleActiveChatTimeout();
    }
  }

  function scheduleCommunicationNotice(kind: "sync" | "chat"): void {
    clearCommunicationTimer();
    communicationTimer = window.setTimeout(() => {
      if (kind === "sync" && state.value === "syncing") {
        _notifySherpa("Sherpa Advisor is reviewing the workflow.");
      } else if (kind === "chat" && state.value === "chatting" && streamingIndex.value === null) {
        _notifySherpa("Sherpa Advisor is preparing a response.");
      }
    }, 4000);
  }

  function finalizeCommunication(): void {
    clearCommunicationTimer();
    clearActiveChatTimeout();
  }

  function recoverFromTransport(detail: string): void {
    if (state.value !== "chatting" && state.value !== "syncing") {
      return;
    }
    finalizeCommunication();
    state.value = "idle";
    streamingIndex.value = null;
    lastSyncError.value = detail;
    _recordActivity(_truncateForLog(detail), { notify: true, severity: "warning" });
    messages.value.push({
      role: "system",
      content: detail,
    });
  }

  function buildSyncPayload() {
    const workflow = useWorkflowStore();
    const dataStore = useDataStore();

    const nodes = workflow.nodes.map((n) => {
      const meta = workflow.getNodeMetadata(n.type);
      const exec = n.executionState;
      const paramKeys = new Set(Object.keys(n.params || {}));
      const paramDescriptions =
        meta?.parameters
          ?.filter((param) => paramKeys.has(param.name))
          .map((param) => ({
            name: param.name,
            label: param.label,
            description: param.description || null,
          })) ?? null;

      return {
        node_id: String(n.id),
        node_type: n.type,
        label: meta?.label ?? n.type,
        parameters: n.params || {},
        result_shape: exec?.output_shape ?? null,
        result_statistics: null,
        description: meta?.description ?? null,
        param_descriptions: paramDescriptions,
        output_type: exec?.output_type ?? meta?.output_type ?? null,
        execution_status: exec?.status ?? null,
      };
    });

    const edges = workflow.edges.map((e) => ({
      from_node_id: String(e.from),
      to_node_id: String(e.to),
      from_output: e.fromPort || "default",
      to_input: e.toPort || "default",
    }));

    // Derive top-level data dimensions from the first data node with results
    let n_samples: number | null = null;
    let n_features: number | null = null;
    const lastExecutionResults = workflow.lastExecutionResults as Record<
      string,
      Record<string, unknown>
    > | null;
    for (const n of workflow.nodes) {
      if (!n.type.startsWith("data.")) {
        continue;
      }

      const result = lastExecutionResults?.[String(n.id)];
      if (result?.n_samples != null) {
        n_samples = Number(result.n_samples);
      }
      if (result?.n_features != null) {
        n_features = Number(result.n_features);
      }
      if (n_samples != null || n_features != null) {
        break;
      }

      if (n.executionState?.output_shape) {
        const shape = n.executionState.output_shape;
        n_samples = shape[0] ?? null;
        n_features = shape[1] ?? null;
        break;
      }
    }

    let results_summary: Record<string, Record<string, unknown>> | null = null;
    if (lastExecutionResults) {
      results_summary = {};
      for (const [nodeId, rawResult] of Object.entries(lastExecutionResults)) {
        if (!rawResult || typeof rawResult !== "object") {
          continue;
        }
        const result = rawResult as Record<string, unknown>;
        const metadata = result.metadata;
        results_summary[nodeId] = {
          type: result.type ?? null,
          shape: result.shape ?? null,
          n_samples: result.n_samples ?? null,
          n_features: result.n_features ?? null,
          metadata:
            metadata && typeof metadata === "object"
              ? Object.fromEntries(
                  Object.entries(metadata as Record<string, unknown>).filter(
                    ([, value]) =>
                      value == null ||
                      typeof value === "string" ||
                      typeof value === "number" ||
                      typeof value === "boolean"
                  )
                )
              : null,
        };
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
      workflow_description: workflow.workflowDescription || null,
      template_id: workflow.currentTemplateId ?? null,
      tier: "summaries",
      nodes,
      edges,
      n_samples,
      n_features,
      diagnostics:
        Object.keys(workflow.lastExecutionDiagnostics || {}).length > 0
          ? workflow.lastExecutionDiagnostics
          : null,
      results_summary,
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
    _recordActivity("Workflow sync requested.", { notify: true });
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
    _recordActivity(`User asked Sherpa: ${_truncateForLog(message)}`, {
      notify: true,
      detail: message,
    });

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
    activeTools.value = [];
    _recordActivity(`Sherpa request sent via ${useTools ? "agentic chat" : "chat"}.`, {
      notify: true,
    });
    scheduleCommunicationNotice("chat");
    scheduleActiveChatTimeout();

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
    lastActivitySummary.value = null;
  }

  // ── WebSocket message handler ──────────────────────────────

   
  function handleWsMessage(payload: any): void {
    if (payload.type === SHERPA_WS_EVENT.recommendations) {
      finalizeCommunication();
      state.value = "idle";
      _recordActivity("Sherpa workflow review completed.");
      const recs: SherpaRecommendationPayload[] = (
        payload.payload || []
      ).map((r: any) => ({
        suggestion_id: r.suggestion_id,
        workflow_id: r.workflow_id,
        category: r.category,
        title: r.title,
        explanation: r.explanation,
        confidence: r.confidence,
        status: r.status,
        created_at: r.created_at,
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
    } else if (payload.type === SHERPA_WS_EVENT.decisionAck) {
      if (payload.payload?.delivered) {
        _recordActivity("Sherpa Advisor recorded your decision.", {
          notify: true,
          severity: "success",
        });
        messages.value.push({
          role: "system",
          content: "Sherpa Advisor recorded your decision.",
        });
      } else {
        const message =
          payload.detail || "Sherpa Advisor could not confirm your decision.";
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
      }
    } else if (payload.type === SHERPA_WS_EVENT.chatStart) {
      finalizeCommunication();
      // Transition from "syncing" to "chatting" so the sync timeout is cleared
      if (state.value === "syncing" || state.value === "idle") {
        state.value = "chatting";
      }
      scheduleActiveChatTimeout();
      streamingIndex.value = messages.value.length;
      _recordActivity(`Sherpa started responding${_formatTimingSuffix(payload.timing)}.`, {
        notify: true,
      });
      messages.value.push({ role: "assistant", content: "" });
    } else if (payload.type === SHERPA_WS_EVENT.chatChunk) {
      if (streamingIndex.value !== null) {
        messages.value[streamingIndex.value].content += payload.chunk;
      }
      _recordActivity(
        `Sherpa streamed response: ${_truncateForLog(payload.chunk || "")}${_formatTimingSuffix(payload.timing)}`
      );
      noteChatActivity();
    } else if (payload.type === SHERPA_WS_EVENT.chatDone) {
      const response =
        streamingIndex.value !== null ? messages.value[streamingIndex.value]?.content ?? "" : "";
      finalizeCommunication();
      state.value = "idle";
      streamingIndex.value = null;
      if (response.trim()) {
        _recordActivity(
          `Sherpa response received: ${_truncateForLog(response)}${_formatTimingSuffix(payload.timing)}`,
          {
          notify: true,
          severity: "success",
          detail: response,
          }
        );
      } else {
        _recordActivity(`Sherpa response completed${_formatTimingSuffix(payload.timing)}.`, {
          notify: true,
          severity: "success",
        });
      }
    } else if (payload.type === SHERPA_WS_EVENT.status) {
      const connected = payload.payload?.connected;
      if (connected && payload.payload?.stage === "analyzing" && state.value === "idle") {
        state.value = "syncing";
        _recordActivity("Sherpa connection established. Reviewing workflow.", {
          notify: true,
        });
      } else if (!connected) {
        finalizeCommunication();
        const reason = payload.payload?.reason || "unknown";
        lastSyncError.value = `Sherpa unavailable: ${reason}`;
        state.value = "error";
        _recordActivity(`Sherpa Advisor is unavailable (${reason}).`, {
          notify: true,
          severity: "warning",
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
      _recordActivity(
        `Sherpa tool started: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`,
        {
        notify: true,
        }
      );
      noteChatActivity();
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
      _recordActivity(
        payload.success === false
          ? `Sherpa tool failed: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`
          : `Sherpa tool completed: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`,
        {
          notify: true,
          severity: payload.success === false ? "warning" : "success",
          detail: typeof payload.summary === "string" ? payload.summary : undefined,
        }
      );
      noteChatActivity();
    } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
      finalizeCommunication();
      subscriptionRequired.value = payload.detail || "This feature requires a subscription.";
      state.value = "idle";
      _recordActivity(payload.detail || "This feature requires a Sherpa subscription.", {
        notify: true,
        severity: "warning",
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
        const detail = _formatDemoLimitDetail(payload as Record<string, unknown>);
        _recordActivity(message);
        _notifySherpa(
          `${message}${_inlineNotificationDetail(detail)}`,
          "warning",
          detail,
        );
        messages.value.push({
          role: "system",
          content: detail ? `${message}\n${detail}` : message,
        });
      } else {
        lastSyncError.value = payload.detail || "Sherpa error";
        _recordActivity(payload.detail || "An error occurred communicating with Sherpa.", {
          notify: true,
          severity: "warning",
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
