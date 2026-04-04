/* eslint-disable @typescript-eslint/no-explicit-any -- assistant sync payloads intentionally preserve flexible node parameter/result shapes. */
import { defineStore } from "pinia";
import { computed, ref, watch, type WatchStopHandle } from "vue";
import {
  createSherpaRequestId,
  subscribeSherpaEvents,
  type SherpaEventPayload,
} from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT, getSherpaChatAction } from "@/lib/sherpaWs";
import { useDataStore } from "@/stores/data";
import { useLlmStore } from "@/stores/llm";
import { useNotificationStore } from "@/stores/notification";
import { useWorkflowStore } from "@/stores/workflow";
import type { SherpaMessage, SherpaRecommendationPayload } from "@/types";

type SherpaState = "idle" | "syncing" | "chatting" | "error";
type SherpaSyncState = "idle" | "syncing" | "error";
type SherpaChatState = "idle" | "chatting" | "error";

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
  const syncState = ref<SherpaSyncState>("idle");
  const chatState = ref<SherpaChatState>("idle");
  const state = computed<SherpaState>(() => {
    if (chatState.value === "chatting") {
      return "chatting";
    }
    if (syncState.value === "syncing") {
      return "syncing";
    }
    if (chatState.value === "error" || syncState.value === "error") {
      return "error";
    }
    return "idle";
  });
  const isSyncing = computed(() => syncState.value === "syncing");
  const isChatting = computed(() => chatState.value === "chatting");
  const lastSyncError = ref<string | null>(null);
  const streamingIndex = ref<number | null>(null);
  const notifications = useNotificationStore();

  // Subscription-gated feature results
  const lastPeaksResult = ref<PeaksResult | null>(null);
  const lastCodeResult = ref<CodeResult | null>(null);
  const activeTools = ref<ToolEvent[]>([]);
  const subscriptionRequired = ref<string | null>(null);
  const subscriptionUpgradeUrl = ref<string | null>(null);
  const lastActivitySummary = ref<string | null>(null);
  const chatServerAcknowledged = ref(false);
  const currentChatRequestId = ref<string | null>(null);
  const currentSyncRequestId = ref<string | null>(null);
  let chatCommunicationTimer: ReturnType<typeof setTimeout> | null = null;
  let syncCommunicationTimer: ReturnType<typeof setTimeout> | null = null;
  let activeChatTimeout: ReturnType<typeof setTimeout> | null = null;
  let activeSyncTimeout: ReturnType<typeof setTimeout> | null = null;
  let stopLlmWatch: WatchStopHandle | null = null;
  let unsubscribeChatEvents: (() => void) | null = null;
  let unsubscribeSyncEvents: (() => void) | null = null;
  let unsubscribeGeneralEvents: (() => void) | null = null;
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
      source: "sherpa",
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

  function _shortRequestId(requestId: unknown): string | null {
    if (typeof requestId !== "string") {
      return null;
    }
    const normalized = requestId.trim();
    if (!normalized) {
      return null;
    }
    return normalized.slice(0, 8);
  }

  function _formatRequestSuffix(requestId: unknown): string {
    const shortId = _shortRequestId(requestId);
    return shortId ? ` [req ${shortId}]` : "";
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

  function _upgradeUrlFromPayload(payload: Record<string, unknown>): string | null {
    const raw = payload.upgrade_url;
    return typeof raw === "string" && raw.trim() ? raw.trim() : null;
  }

  function _openUpgradeUrl(url: string | null): string | null {
    if (!url) {
      return null;
    }
    if (typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return url;
  }

  function _appendSystemMessage(content: string): void {
    messages.value.push({
      role: "system",
      content,
    });
  }

  function _currentStartedToolName(): string | null {
    for (let index = activeTools.value.length - 1; index >= 0; index -= 1) {
      const tool = activeTools.value[index];
      if (tool.status === "started") {
        return tool.tool_name;
      }
    }
    return null;
  }

  function _ensureAssistantBubbleForStreaming(requestId?: string | null): void {
    if (streamingIndex.value !== null && messages.value[streamingIndex.value]) {
      return;
    }
    streamingIndex.value = messages.value.length;
    currentChatRequestId.value =
      typeof requestId === "string" && requestId.trim() ? requestId : currentChatRequestId.value;
    messages.value.push({ role: "assistant", content: "" });
    _recordActivity(
      `Sherpa recovered a missing response start${_formatRequestSuffix(currentChatRequestId.value)}.`,
      {
        notify: true,
        severity: "warning",
      }
    );
  }

  function clearChatCommunicationTimer(): void {
    if (chatCommunicationTimer !== null) {
      clearTimeout(chatCommunicationTimer);
      chatCommunicationTimer = null;
    }
  }

  function clearSyncCommunicationTimer(): void {
    if (syncCommunicationTimer !== null) {
      clearTimeout(syncCommunicationTimer);
      syncCommunicationTimer = null;
    }
  }

  function clearActiveChatTimeout(): void {
    if (activeChatTimeout !== null) {
      clearTimeout(activeChatTimeout);
      activeChatTimeout = null;
    }
  }

  function clearActiveSyncTimeout(): void {
    if (activeSyncTimeout !== null) {
      clearTimeout(activeSyncTimeout);
      activeSyncTimeout = null;
    }
  }

  function scheduleActiveChatTimeout(): void {
    clearActiveChatTimeout();
    const expectedRequestId = currentChatRequestId.value;
    activeChatTimeout = window.setTimeout(() => {
      if (chatState.value === "chatting" && currentChatRequestId.value === expectedRequestId) {
        const timedOutBeforeAck = !chatServerAcknowledged.value;
        const inFlightTool = _currentStartedToolName();
        finalizeChatCommunication();
        chatState.value = "idle";
        streamingIndex.value = null;
        const timeoutMessage = timedOutBeforeAck
          ? `Sherpa Advisor timed out before the server acknowledged the request.${_formatRequestSuffix(currentChatRequestId.value)}`
          : inFlightTool
            ? `Sherpa Advisor timed out while waiting for tool: ${inFlightTool}${_formatRequestSuffix(currentChatRequestId.value)}`
          : lastActivitySummary.value
            ? `Sherpa Advisor timed out. Last activity: ${lastActivitySummary.value}`
            : "Sherpa Advisor is taking longer than expected. Please try again.";
        _notifySherpa(timeoutMessage, "warning");
        _appendSystemMessage(
          inFlightTool
            ? `Chat response timed out while Sherpa was waiting for tool: ${inFlightTool}.`
            : "Chat response timed out. The server may be processing a complex request — check the workflow and try again."
        );
        currentChatRequestId.value = null;
        unsubscribeChatEvents?.();
        unsubscribeChatEvents = null;
      }
    }, 120_000);
  }

  function noteChatActivity(): void {
    if (chatState.value === "chatting") {
      scheduleActiveChatTimeout();
    }
  }

  function scheduleSyncCommunicationNotice(): void {
    clearSyncCommunicationTimer();
    const expectedRequestId = currentSyncRequestId.value;
    syncCommunicationTimer = window.setTimeout(() => {
      if (syncState.value === "syncing" && currentSyncRequestId.value === expectedRequestId) {
        _notifySherpa("Sherpa Advisor is reviewing the workflow.");
      }
    }, 4000);
  }

  function scheduleChatCommunicationNotice(): void {
    clearChatCommunicationTimer();
    const expectedRequestId = currentChatRequestId.value;
    chatCommunicationTimer = window.setTimeout(() => {
      if (
        chatState.value === "chatting"
        && currentChatRequestId.value === expectedRequestId
        && streamingIndex.value === null
      ) {
        _notifySherpa("Sherpa request sent. Waiting for server acknowledgement.");
      }
    }, 4000);
  }

  function finalizeChatCommunication(): void {
    clearChatCommunicationTimer();
    clearActiveChatTimeout();
  }

  function finalizeSyncCommunication(): void {
    clearSyncCommunicationTimer();
    clearActiveSyncTimeout();
  }

  function recoverFromTransport(detail: string): void {
    if (chatState.value !== "chatting" && syncState.value !== "syncing") {
      return;
    }
    finalizeChatCommunication();
    finalizeSyncCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    chatState.value = "idle";
    syncState.value = "idle";
    streamingIndex.value = null;
    currentChatRequestId.value = null;
    currentSyncRequestId.value = null;
    lastSyncError.value = detail;
    _recordActivity(_truncateForLog(detail), { notify: true, severity: "warning" });
    _appendSystemMessage(detail);
  }

  function _validateSherpaPayload(payload: unknown): asserts payload is SherpaEventPayload {
    if (!payload || typeof payload !== "object") {
      throw new Error("Sherpa event payload was not an object.");
    }
    if (typeof (payload as SherpaEventPayload).type !== "string" || !(payload as SherpaEventPayload).type.trim()) {
      throw new Error("Sherpa event payload was missing a valid type.");
    }
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
    if (syncState.value === "syncing") {
      return;
    }
    const llm = useLlmStore();
    finalizeSyncCommunication();
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    syncState.value = "syncing";
    lastSyncError.value = null;
    currentSyncRequestId.value = createSherpaRequestId();
    _recordActivity("Workflow sync requested.", { notify: true });
    scheduleSyncCommunicationNotice();
    try {
      await llm.connect();
    } catch {
      finalizeSyncCommunication();
      lastSyncError.value = "WebSocket not connected";
      syncState.value = "error";
      messages.value.push({
        role: "system",
        content: "Unable to connect to the server. Please try again.",
      });
      return;
    }

    const workflow = useWorkflowStore();
    if (!workflow.workflowId) {
      finalizeSyncCommunication();
      syncState.value = "idle";
      currentSyncRequestId.value = null;
      messages.value.push({
        role: "system",
        content:
          "No workflow is currently loaded. Open or create a workflow first.",
      });
      return;
    }

    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      lastSyncError.value = "WebSocket not ready";
      syncState.value = "error";
      messages.value.push({
        role: "system",
        content: "Connection is not ready. Please try again in a moment.",
      });
      return;
    }

    if (!currentSyncRequestId.value) {
      return;
    }
    unsubscribeSyncEvents = subscribeSherpaEvents(handleSyncEvent, {
      requestId: currentSyncRequestId.value,
      types: [
        SHERPA_WS_EVENT.status,
        SHERPA_WS_EVENT.recommendations,
        SHERPA_WS_EVENT.subscriptionRequired,
        SHERPA_WS_EVENT.error,
      ],
    });

    ws.send(
      JSON.stringify({
        action: SHERPA_WS_ACTION.sync,
        payload: {
          request_id: currentSyncRequestId.value,
          ...buildSyncPayload(),
        },
      })
    );

    clearActiveSyncTimeout();
    const expectedRequestId = currentSyncRequestId.value;
    activeSyncTimeout = window.setTimeout(() => {
      if (syncState.value === "syncing" && currentSyncRequestId.value === expectedRequestId) {
        syncState.value = "idle";
        currentSyncRequestId.value = null;
        unsubscribeSyncEvents?.();
        unsubscribeSyncEvents = null;
        _notifySherpa("Sherpa sync timed out. The service may be unavailable.", "warning");
        _appendSystemMessage("Sherpa sync timed out. The service may be unavailable.");
      }
    }, 180_000);
  }

  async function sendMessage(message: string, useTools = false): Promise<void> {
    if (!message.trim()) return;

    const llm = useLlmStore();

    messages.value.push({ role: "user", content: message });
    const requestId = createSherpaRequestId();
    finalizeChatCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    currentChatRequestId.value = requestId;
    _recordActivity(`User asked Sherpa: ${_truncateForLog(message)}`, {
      notify: true,
      detail: message,
    });

    chatState.value = "chatting";
    activeTools.value = [];
    chatServerAcknowledged.value = false;
    subscriptionRequired.value = null;
    subscriptionUpgradeUrl.value = null;
    _recordActivity(
      `Sherpa request queued via ${useTools ? "agentic chat" : "chat"}${_formatRequestSuffix(requestId)}.`,
      {
        notify: true,
      }
    );
    scheduleChatCommunicationNotice();
    scheduleActiveChatTimeout();

    const workflow = useWorkflowStore();
    let ws: WebSocket | null = null;
    try {
      await llm.connect();
      ws = getWs();
    } catch {
      finalizeChatCommunication();
      chatState.value = "idle";
      currentChatRequestId.value = null;
      messages.value.push({
        role: "assistant",
        content: "Unable to connect. Check the server and try again.",
      });
      return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      finalizeChatCommunication();
      chatState.value = "idle";
      currentChatRequestId.value = null;
      messages.value.push({
        role: "system",
        content: "Connection is not ready. Please try again in a moment.",
      });
      return;
    }

    _recordActivity(`Sherpa request sent${_formatRequestSuffix(requestId)}.`, {
      notify: true,
    });

    unsubscribeChatEvents = subscribeSherpaEvents(handleChatEvent, {
      requestId,
      types: [
        SHERPA_WS_EVENT.chatStart,
        SHERPA_WS_EVENT.chatChunk,
        SHERPA_WS_EVENT.chatDone,
        SHERPA_WS_EVENT.status,
        SHERPA_WS_EVENT.toolStart,
        SHERPA_WS_EVENT.toolResult,
        SHERPA_WS_EVENT.subscriptionRequired,
        SHERPA_WS_EVENT.error,
      ],
    });

    ws.send(
      JSON.stringify({
        action: getSherpaChatAction(useTools),
        payload: {
          request_id: requestId,
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
    finalizeChatCommunication();
    finalizeSyncCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    messages.value = [];
    syncState.value = "idle";
    chatState.value = "idle";
    lastSyncError.value = null;
    streamingIndex.value = null;
    chatServerAcknowledged.value = false;
    currentChatRequestId.value = null;
    currentSyncRequestId.value = null;
    lastPeaksResult.value = null;
    lastCodeResult.value = null;
    activeTools.value = [];
    subscriptionRequired.value = null;
    subscriptionUpgradeUrl.value = null;
    lastActivitySummary.value = null;
  }

  // ── WebSocket message handlers ─────────────────────────────

  function handleSyncEvent(payload: SherpaEventPayload): void {
    try {
      _validateSherpaPayload(payload);

      if (payload.type === SHERPA_WS_EVENT.status) {
        const connected = payload.payload?.connected;
        if (connected && payload.payload?.stage === "analyzing") {
          syncState.value = "syncing";
          _recordActivity(
            `Sherpa connection established${_formatRequestSuffix(payload.request_id)}. Reviewing workflow.`,
            {
              notify: true,
            }
          );
          return;
        }
        if (!connected) {
          finalizeSyncCommunication();
          syncState.value = "error";
          currentSyncRequestId.value = null;
          unsubscribeSyncEvents?.();
          unsubscribeSyncEvents = null;
          const reason = payload.payload?.reason || "unknown";
          lastSyncError.value = `Sherpa unavailable: ${reason}`;
          _recordActivity(`Sherpa Advisor is unavailable (${reason}).`, {
            notify: true,
            severity: "warning",
          });
          _appendSystemMessage(
            `Sherpa Advisor is not available (${reason}). Configure the cloud connection in Settings > Integrations.`
          );
        }
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.recommendations) {
        finalizeSyncCommunication();
        syncState.value = "idle";
        currentSyncRequestId.value = null;
        unsubscribeSyncEvents?.();
        unsubscribeSyncEvents = null;
        _recordActivity(
          `Sherpa workflow review completed${_formatRequestSuffix(payload.request_id)}.`
        );
        const recs: SherpaRecommendationPayload[] = (payload.payload || []).map((r: any) => ({
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
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
        finalizeSyncCommunication();
        syncState.value = "idle";
        currentSyncRequestId.value = null;
        unsubscribeSyncEvents?.();
        unsubscribeSyncEvents = null;
        subscriptionRequired.value = payload.detail || "This feature requires a subscription.";
        subscriptionUpgradeUrl.value = _upgradeUrlFromPayload(payload as Record<string, unknown>);
        _recordActivity(
          `${payload.detail || "This feature requires a Sherpa subscription."}${_formatRequestSuffix(payload.request_id)}`,
          {
            notify: true,
            severity: "warning",
          }
        );
        const upgradeMessage =
          payload.detail
          || "This feature requires a Sherpa subscription. Upgrade your plan to unlock it.";
        _appendSystemMessage(
          subscriptionUpgradeUrl.value
            ? `${upgradeMessage}\nUpgrade: ${subscriptionUpgradeUrl.value}`
            : upgradeMessage
        );
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.error) {
        finalizeSyncCommunication();
        syncState.value = "error";
        currentSyncRequestId.value = null;
        unsubscribeSyncEvents?.();
        unsubscribeSyncEvents = null;
        const isDemoLimitError =
          payload.limit_type === "sherpa"
          || payload.limit_type === "execution"
          || typeof payload.message === "string";
        if (isDemoLimitError) {
          const message = payload.message || "Demo limit reached";
          lastSyncError.value = message;
          const detail = _formatDemoLimitDetail(payload as Record<string, unknown>);
          _recordActivity(`${message}${_formatRequestSuffix(payload.request_id)}`);
          _notifySherpa(
            `${message}${_inlineNotificationDetail(detail)}`,
            "warning",
            detail,
          );
          _appendSystemMessage(detail ? `${message}\n${detail}` : message);
        } else {
          lastSyncError.value = payload.detail || "Sherpa error";
          _recordActivity(
            `${payload.detail || "An error occurred communicating with Sherpa."}${_formatRequestSuffix(payload.request_id)}`,
            {
              notify: true,
              severity: "warning",
            }
          );
          _appendSystemMessage(
            payload.detail || "An error occurred communicating with Sherpa."
          );
        }
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown Sherpa sync event error.";
      finalizeSyncCommunication();
      syncState.value = "error";
      currentSyncRequestId.value = null;
      unsubscribeSyncEvents?.();
      unsubscribeSyncEvents = null;
      _notifySherpa(`Sherpa sync event handling failed: ${message}`, "warning");
      _appendSystemMessage(`Sherpa sync event handling failed: ${message}`);
    }
  }

  function handleChatEvent(payload: SherpaEventPayload): void {
    try {
      _validateSherpaPayload(payload);

      if (payload.type === SHERPA_WS_EVENT.chatStart) {
        finalizeChatCommunication();
        chatState.value = "chatting";
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        scheduleActiveChatTimeout();
        streamingIndex.value = messages.value.length;
        _recordActivity(
          `Sherpa started responding${_formatRequestSuffix(payload.request_id)}${_formatTimingSuffix(payload.timing)}.`,
          {
            notify: true,
          }
        );
        messages.value.push({ role: "assistant", content: "" });
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.chatChunk) {
        if (typeof payload.chunk !== "string") {
          throw new Error("Sherpa chat chunk payload was missing text.");
        }
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        _ensureAssistantBubbleForStreaming(currentChatRequestId.value);
        if (streamingIndex.value !== null) {
          messages.value[streamingIndex.value].content += payload.chunk;
        }
        _recordActivity(
          `Sherpa streamed response${_formatRequestSuffix(payload.request_id)}: ${_truncateForLog(payload.chunk)}${_formatTimingSuffix(payload.timing)}`
        );
        noteChatActivity();
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.chatDone) {
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        const response =
          streamingIndex.value !== null
            ? messages.value[streamingIndex.value]?.content ?? ""
            : "";
        finalizeChatCommunication();
        chatState.value = "idle";
        streamingIndex.value = null;
        unsubscribeChatEvents?.();
        unsubscribeChatEvents = null;
        if (response.trim()) {
          _recordActivity(
            `Sherpa response received${_formatRequestSuffix(payload.request_id)}: ${_truncateForLog(response)}${_formatTimingSuffix(payload.timing)}`,
            {
              notify: true,
              severity: "success",
              detail: response,
            }
          );
        } else {
          const emptyMessage = `Sherpa returned an empty response${_formatRequestSuffix(payload.request_id)}${_formatTimingSuffix(payload.timing)}.`;
          _recordActivity(emptyMessage, {
            notify: true,
            severity: "warning",
          });
          _appendSystemMessage(
            "Sherpa returned an empty response. The request may have been truncated or produced no visible output."
          );
        }
        currentChatRequestId.value = null;
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.status) {
        clearChatCommunicationTimer();
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        const stage = String(payload.payload?.stage || "unknown");
        const detail =
          typeof payload.payload?.detail === "string" ? payload.payload.detail : null;
        const stageMessages: Record<string, string> = {
          authorizing: "Sherpa server acknowledged the request.",
          rate_limit_check: "Sherpa is checking request limits.",
          demo_limit_check: "Sherpa is checking usage limits.",
          advisor_availability_check: "Sherpa is verifying advisor availability.",
          privacy_check: "Sherpa is checking privacy settings.",
          access_checks_complete: "Sherpa access checks passed.",
          context_filter_check: "Sherpa is checking workflow context permissions.",
          context_filter_result:
            "Sherpa finished the workflow context privacy check.",
          model_dispatch: "Sherpa is preparing the model request.",
          tool_round_limit:
            "Sherpa reached the tool round limit and is finishing without more tool calls.",
        };
        const baseMessage = stageMessages[stage] || `Sherpa status: ${stage}.`;
        const extraDetail = detail && detail !== baseMessage ? ` ${detail}` : "";
        const statusMessage = `${baseMessage}${_formatRequestSuffix(payload.request_id)}${extraDetail}${_formatTimingSuffix(payload.timing)}`;
        _recordActivity(statusMessage, {
          notify: true,
          severity: stage === "tool_round_limit" ? "warning" : "info",
        });
        if (stage === "tool_round_limit") {
          _appendSystemMessage(detail || baseMessage);
        }
        noteChatActivity();
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.toolStart) {
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        activeTools.value.push({
          tool_name: payload.tool_name || "unknown",
          status: "started",
        });
        _recordActivity(
          `Sherpa tool started${_formatRequestSuffix(payload.request_id)}: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`,
          {
            notify: true,
          }
        );
        noteChatActivity();
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.toolResult) {
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        const idx = activeTools.value.findIndex(
          (tool) => tool.tool_name === payload.tool_name && tool.status === "started"
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
            ? `Sherpa tool failed${_formatRequestSuffix(payload.request_id)}: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`
            : `Sherpa tool completed${_formatRequestSuffix(payload.request_id)}: ${payload.tool_name || "unknown"}${_formatTimingSuffix(payload.timing)}`,
          {
            notify: true,
            severity: payload.success === false ? "warning" : "success",
            detail: typeof payload.summary === "string" ? payload.summary : undefined,
          }
        );
        if (payload.success === false) {
          _appendSystemMessage(
            typeof payload.summary === "string" && payload.summary.trim()
              ? `Sherpa tool failed${typeof payload.error_category === "string" ? ` (${payload.error_category})` : ""}: ${payload.tool_name || "unknown"}.\n${payload.summary}`
              : `Sherpa tool failed${typeof payload.error_category === "string" ? ` (${payload.error_category})` : ""}: ${payload.tool_name || "unknown"}.`
          );
        }
        noteChatActivity();
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
        chatServerAcknowledged.value = true;
        finalizeChatCommunication();
        chatState.value = "idle";
        unsubscribeChatEvents?.();
        unsubscribeChatEvents = null;
        subscriptionRequired.value =
          payload.detail || "This feature requires a subscription.";
        subscriptionUpgradeUrl.value = _upgradeUrlFromPayload(
          payload as Record<string, unknown>
        );
        _recordActivity(
          `${payload.detail || "This feature requires a Sherpa subscription."}${_formatRequestSuffix(payload.request_id)}`,
          {
            notify: true,
            severity: "warning",
          }
        );
        const upgradeMessage =
          payload.detail
          || "This feature requires a Sherpa subscription. Upgrade your plan to unlock it.";
        _appendSystemMessage(
          subscriptionUpgradeUrl.value
            ? `${upgradeMessage}\nUpgrade: ${subscriptionUpgradeUrl.value}`
            : upgradeMessage
        );
        currentChatRequestId.value = null;
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.error) {
        chatServerAcknowledged.value = true;
        finalizeChatCommunication();
        chatState.value = "error";
        unsubscribeChatEvents?.();
        unsubscribeChatEvents = null;
        const isDemoLimitError =
          payload.limit_type === "sherpa"
          || payload.limit_type === "execution"
          || typeof payload.message === "string";
        if (isDemoLimitError) {
          const message = payload.message || "Demo limit reached";
          lastSyncError.value = message;
          const detail = _formatDemoLimitDetail(payload as Record<string, unknown>);
          _recordActivity(`${message}${_formatRequestSuffix(payload.request_id)}`);
          _notifySherpa(
            `${message}${_inlineNotificationDetail(detail)}`,
            "warning",
            detail,
          );
          _appendSystemMessage(detail ? `${message}\n${detail}` : message);
        } else {
          lastSyncError.value = payload.detail || "Sherpa error";
          _recordActivity(
            `${payload.detail || "An error occurred communicating with Sherpa."}${_formatRequestSuffix(payload.request_id)}`,
            {
              notify: true,
              severity: "warning",
            }
          );
          _appendSystemMessage(
            payload.detail || "An error occurred communicating with Sherpa."
          );
        }
        currentChatRequestId.value = null;
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown Sherpa chat event error.";
      finalizeChatCommunication();
      chatState.value = "error";
      streamingIndex.value = null;
      currentChatRequestId.value = null;
      unsubscribeChatEvents?.();
      unsubscribeChatEvents = null;
      subscriptionUpgradeUrl.value = null;
      _notifySherpa(`Sherpa event handling failed: ${message}`, "warning");
      _appendSystemMessage(`Sherpa event handling failed: ${message}`);
    }
  }

  function handleGeneralEvent(payload: SherpaEventPayload): void {
    try {
      _validateSherpaPayload(payload);

      if (payload.type === SHERPA_WS_EVENT.decisionAck) {
        if (payload.payload?.delivered) {
          _recordActivity("Sherpa Advisor recorded your decision.", {
            notify: true,
            severity: "success",
          });
          _appendSystemMessage("Sherpa Advisor recorded your decision.");
        } else {
          const message =
            payload.detail || "Sherpa Advisor could not confirm your decision.";
          notifications.add({
            source: "sherpa",
            severity: "warning",
            title: "Sherpa Advisor",
            message,
          });
          _appendSystemMessage(message);
        }
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.peaksResult) {
        lastPeaksResult.value = {
          peaks: payload.peaks as PeaksResult["peaks"],
          response: typeof payload.response === "string" ? payload.response : undefined,
        };
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.peaksError) {
        lastPeaksResult.value = null;
        _appendSystemMessage(payload.detail || "Peak identification failed.");
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.codeResult) {
        const rawCode = payload.code || _extractCodeFromMarkdown(payload.response || "");
        lastCodeResult.value = {
          code: typeof rawCode === "string" ? rawCode : "",
          language: typeof payload.language === "string" ? payload.language : "python",
          response: typeof payload.response === "string" ? payload.response : undefined,
        };
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.codeError) {
        lastCodeResult.value = null;
        _appendSystemMessage(payload.detail || "Code generation failed.");
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown Sherpa event error.";
      _notifySherpa(`Sherpa event handling failed: ${message}`, "warning");
      _appendSystemMessage(`Sherpa event handling failed: ${message}`);
    }
  }


  // ── lifecycle ──────────────────────────────────────────────

  function _onTransportEvent(event: Event): void {
    const detail = (event as CustomEvent).detail as { kind?: string; detail?: string | null };
    if (detail.kind === "socket_open" || detail.kind === "auth_sent" || detail.kind === "auth_ack") {
      if (chatState.value === "chatting" || syncState.value === "syncing") {
        const messagesByKind: Record<string, string> = {
          socket_open: "Sherpa transport connected. Starting WebSocket authentication.",
          auth_sent: "Sherpa transport sent WebSocket authentication.",
          auth_ack: "Sherpa transport authentication acknowledged.",
        };
        _recordActivity(
          `${messagesByKind[detail.kind]}${_formatRequestSuffix(currentChatRequestId.value || currentSyncRequestId.value)}`,
          {
          notify: true,
          }
        );
        if (chatState.value === "chatting") {
          noteChatActivity();
        }
      }
      return;
    }
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
    unsubscribeGeneralEvents = subscribeSherpaEvents(handleGeneralEvent, {
      types: [
        SHERPA_WS_EVENT.decisionAck,
        SHERPA_WS_EVENT.peaksResult,
        SHERPA_WS_EVENT.peaksError,
        SHERPA_WS_EVENT.codeResult,
        SHERPA_WS_EVENT.codeError,
      ],
    });
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
    finalizeChatCommunication();
    finalizeSyncCommunication();
    isInitialized = false;
    unsubscribeGeneralEvents?.();
    unsubscribeGeneralEvents = null;
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    window.removeEventListener("app-ws-transport", _onTransportEvent);
    stopLlmWatch?.();
    stopLlmWatch = null;
  }

  function openSubscriptionUpgrade(): void {
    _openUpgradeUrl(subscriptionUpgradeUrl.value);
  }

  return {
    messages,
    state,
    syncState,
    chatState,
    isSyncing,
    isChatting,
    lastSyncError,
    lastPeaksResult,
    lastCodeResult,
    activeTools,
    subscriptionRequired,
    subscriptionUpgradeUrl,
    syncWorkflow,
    sendMessage,
    clearMessages,
    openSubscriptionUpgrade,
    init,
    dispose,
  };
});
