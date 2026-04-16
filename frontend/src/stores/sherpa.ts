/* eslint-disable @typescript-eslint/no-explicit-any -- assistant sync payloads intentionally preserve flexible node parameter/result shapes. */
import { defineStore } from "pinia";
import { computed, ref, watch, type WatchStopHandle } from "vue";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  createSherpaRequestId,
  subscribeSherpaEvents,
  type SherpaEventPayload,
} from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT, getSherpaChatAction } from "@/lib/sherpaWs";
import {
  summarizeDatasetForSherpaContext,
  useDataStore,
  type SherpaDatasetContext,
} from "@/stores/data";
import { useLlmStore } from "@/stores/llm";
import { useNotificationStore } from "@/stores/notification";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import type { ConversationSummary, SherpaMessage, SherpaRecommendationPayload } from "@/types";

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

const STORAGE_KEY = "sherpa_conversations";

const loadConversations = (): ConversationSummary[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    return JSON.parse(raw) as ConversationSummary[];
  } catch (error) {
    console.error("Failed to load Sherpa conversations from localStorage:", error);
    return [];
  }
};

const persistConversations = (items: ConversationSummary[]) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
};

export const useSherpaStore = defineStore("sherpa", () => {
  const { appMode } = useAppConfig();
  const projectStore = useProjectStore();
  const messages = ref<SherpaMessage[]>([]);
  const isServerBacked = computed(() => appMode.value !== "local");
  const conversations = ref<ConversationSummary[]>(
    isServerBacked.value ? [] : loadConversations()
  );
  const currentConversationId = ref<string | null>(null);
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

  async function refreshConversations(projectId = projectStore.currentProjectId): Promise<void> {
    if (!isServerBacked.value) {
      conversations.value = loadConversations();
      return;
    }

    if (!projectId) {
      conversations.value = [];
      currentConversationId.value = null;
      messages.value = [];
      return;
    }

    const response = await api.get("/llm/conversations", {
      params: { project_id: projectId },
    });
    conversations.value = (response.data as Array<Record<string, unknown>>).map((item) => ({
      id: String(item.id),
      title: String(item.title || "Untitled conversation"),
      updatedAt: String(item.updated_at || item.updatedAt || new Date().toISOString()),
    }));

    // If the active conversation isn't in the refreshed list, the current
    // thread is stale (e.g. the user deleted it elsewhere). BUT: this branch
    // is also hit in a post-stream race where updateConversationSummary()
    // fires refreshConversations() immediately after a new conversation is
    // created and the server's list hasn't yet been updated — wiping
    // messages.value here made the just-received response vanish even
    // though the server had delivered it.
    //
    // Resolution: drop the current conversation id (so the next user send
    // starts fresh), but KEEP messages.value so the user can still read
    // the response they just received. If the conversation was genuinely
    // deleted, the next interaction will replace these messages; if the
    // race was harmless, nothing was lost.
    if (
      currentConversationId.value
      && !conversations.value.some((item) => item.id === currentConversationId.value)
    ) {
      currentConversationId.value = null;
    }
  }

  function updateConversationSummary(conversationId: string): void {
    if (isServerBacked.value) {
      void refreshConversations(projectStore.currentProjectId);
      return;
    }

    const firstUser = messages.value.find((message) => message.role === "user");
    const title =
      firstUser?.content.slice(0, 60) || `Sherpa Conversation ${conversations.value.length + 1}`;
    const updatedAt = new Date().toISOString();
    const existing = conversations.value.find((item) => item.id === conversationId);

    if (existing) {
      existing.title = title;
      existing.updatedAt = updatedAt;
    } else {
      conversations.value.unshift({ id: conversationId, title, updatedAt });
    }

    persistConversations(conversations.value);
  }

  async function loadConversation(conversationId: string): Promise<void> {
    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;

    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before loading a Sherpa conversation.");
    }

    const response = await api.get(`/llm/conversation/${conversationId}`, { params });
    currentConversationId.value = response.data.conversation_id;
    messages.value = (response.data.messages as Array<{ role: SherpaMessage["role"]; content: string }>)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));
    finalizeChatCommunication();
    finalizeSyncCommunication();
    chatState.value = "idle";
    syncState.value = "idle";
    streamingIndex.value = null;
    currentChatRequestId.value = null;
    currentSyncRequestId.value = null;
    activeTools.value = [];
    subscriptionRequired.value = null;
    subscriptionUpgradeUrl.value = null;
  }

  async function deleteConversation(conversationId: string): Promise<void> {
    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;

    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before deleting a Sherpa conversation.");
    }

    await api.delete(`/llm/conversation/${conversationId}`, { params });
    conversations.value = conversations.value.filter((item) => item.id !== conversationId);
    if (!isServerBacked.value) {
      persistConversations(conversations.value);
    }
    if (currentConversationId.value === conversationId) {
      startNewConversation();
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

  function _createWelcomeMessage(): SherpaMessage {
    return {
      role: "assistant",
      content: [
        "Sherpa Advisor is ready.",
        "",
        "1. Create a project.",
        "2. Pick a template or build a workflow.",
        "3. Run the workflow to generate results.",
        "4. Ask Sherpa about the outputs, diagnostics, or next steps.",
      ].join("\n"),
    };
  }

  function _ensureWelcomeMessage(): void {
    if (messages.value.length > 0) {
      return;
    }
    messages.value = [_createWelcomeMessage()];
  }

  function _resetTransientState(): void {
    syncState.value = "idle";
    chatState.value = "idle";
    lastSyncError.value = null;
    streamingIndex.value = null;
    chatServerAcknowledged.value = false;
    currentChatRequestId.value = null;
    currentSyncRequestId.value = null;
    activeTools.value = [];
    subscriptionRequired.value = null;
    subscriptionUpgradeUrl.value = null;
  }

  function startNewConversation(): void {
    finalizeChatCommunication();
    finalizeSyncCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    messages.value = [];
    _resetTransientState();
    currentConversationId.value = null;
    lastActivitySummary.value = null;
    _ensureWelcomeMessage();
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
    const lastExecutionResults = workflow.lastExecutionResults as Record<
      string,
      Record<string, unknown>
    > | null;
    const emptyDatasetContext = (): SherpaDatasetContext => ({
      label: null,
      source: null,
      dataset_name: null,
      description: null,
      n_samples: null,
      n_features: null,
      is_time_series: null,
      is_spectra: null,
      technique: null,
      x_title: null,
      x_units: null,
      x_min: null,
      x_max: null,
      data_quantity: null,
      value_units: null,
      feature_names: null,
      target_names: null,
      metadata_summary: null,
    });

    const toObject = (value: unknown): Record<string, unknown> | null =>
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;

    const toStringList = (value: unknown, limit = 20): string[] | null => {
      if (!Array.isArray(value)) {
        return null;
      }
      const items = value
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .slice(0, limit);
      return items.length > 0 ? items : null;
    };

    /**
     * Unwrap a multi-output node's serialized result to the dataset-bearing
     * port.  Multi-output nodes (``data.source``, ``model.*``) serialize to
     * ``{default: {...SherpaDataset fields...}, target: ..., ...}``, so the
     * dataset identity lives at ``result.default``, not at the top level.
     * Single-output nodes that serialize directly as a SherpaDataset have
     * ``type: "SherpaDataset"`` at the top level and pass through unchanged.
     */
    const unwrapDatasetResult = (
      rawResult: Record<string, unknown> | null | undefined
    ): Record<string, unknown> | null => {
      if (!rawResult || typeof rawResult !== "object") return null;
      if (rawResult.type === "SherpaDataset") return rawResult;
      const defaultPort = toObject(rawResult.default);
      if (defaultPort && defaultPort.type === "SherpaDataset") return defaultPort;
      return rawResult;
    };

    const deriveDatasetIdentity = (
      _node: { label?: unknown; params?: Record<string, unknown> },
      rawResult: Record<string, unknown> | null | undefined
    ): Partial<SherpaDatasetContext> | null => {
      const ds = unwrapDatasetResult(rawResult);
      if (!ds) return null;
      const metadata = toObject(ds.metadata);
      const extra = toObject(ds.extra);
      const targetContext = toObject(ds.target_context);
      const datasetName =
        typeof extra?.["sklearn.dataset_name"] === "string"
          ? extra["sklearn.dataset_name"]
          : typeof extra?.["catalog.dataset_name"] === "string"
            ? extra["catalog.dataset_name"]
            : typeof metadata?.["sklearn.dataset_name"] === "string"
              ? metadata["sklearn.dataset_name"]
              : typeof metadata?.["catalog.dataset_name"] === "string"
                ? metadata["catalog.dataset_name"]
                : typeof ds.title === "string" && ds.title.trim()
                  ? ds.title
                  : null;
      const featureNames =
        toStringList(metadata?.feature_names) ??
        toStringList(extra?.["csv.feature_names"]) ??
        toStringList(toObject(ds.x_axis)?.labels) ??
        toStringList(toObject(ds.feature_axis)?.labels);
      const targetNames =
        toStringList(targetContext?.target_names) ??
        toStringList(targetContext?.class_names) ??
        toStringList(extra?.["sklearn.target_names"]) ??
        toStringList(metadata?.["sklearn.target_names"]);

      const identity: Partial<SherpaDatasetContext> = {};
      if (typeof ds.title === "string" && ds.title.trim()) {
        identity.label = ds.title;
      }
      if (typeof ds.backend === "string" && ds.backend.trim()) {
        identity.source = ds.backend;
      }
      if (datasetName) {
        identity.dataset_name = datasetName;
      }
      if (featureNames) {
        identity.feature_names = featureNames;
      }
      if (targetNames) {
        identity.target_names = targetNames;
      }
      if (typeof ds.n_samples === "number") {
        identity.n_samples = ds.n_samples;
      }
      if (typeof ds.n_features === "number") {
        identity.n_features = ds.n_features;
      }

      return Object.keys(identity).length > 0 ? identity : null;
    };

    const deriveShapeAndType = (
      result: Record<string, unknown> | null | undefined
    ): { result_shape: number[] | null; output_type: string | null } => {
      let result_shape: number[] | null = null;
      let output_type: string | null = null;

      if (!result || typeof result !== "object") {
        return { result_shape, output_type };
      }

      const primary =
        result.default && typeof result.default === "object"
          ? (result.default as Record<string, unknown>)
          : result;

      if (typeof primary.type === "string" && primary.type.trim()) {
        output_type = primary.type;
      }

      if (
        Array.isArray(primary.shape)
        && primary.shape.every((value) => typeof value === "number")
      ) {
        result_shape = primary.shape as number[];
      } else if (
        typeof primary.n_samples === "number"
        && typeof primary.n_features === "number"
      ) {
        result_shape = [primary.n_samples, primary.n_features];
      }

      return { result_shape, output_type };
    };

    const nodes = workflow.nodes.map((n) => {
      const meta = workflow.getNodeMetadata(n.type);
      const exec = n.executionState;
      const userParams = (n.params || {}) as Record<string, unknown>;
      const rawResult = lastExecutionResults?.[String(n.id)] ?? null;
      const inferredResult = deriveShapeAndType(rawResult);
      const hasPersistedResult = rawResult !== null;
      const executionStatus =
        exec?.status && exec.status !== "pending"
          ? exec.status
          : hasPersistedResult
            ? "completed"
            : exec?.status ?? null;
      const resultShape = exec?.output_shape ?? inferredResult.result_shape;
      const outputType = exec?.output_type ?? inferredResult.output_type ?? meta?.output_type ?? null;

      // Build EFFECTIVE parameters = metadata defaults overlaid with user overrides.
      // Without this the Pipeline Nodes "Params: {...}" line sent to Sherpa is
      // often empty or partial, and the LLM falls back on describe_node (which
      // returns type-level defaults) and conflates "node type default" with
      // "this node's actual setting". Always sending the effective value
      // removes that ambiguity.
      const effectiveParams: Record<string, unknown> = {};
      if (meta?.parameters) {
        for (const p of meta.parameters) {
          if (p.default !== undefined) {
            effectiveParams[p.name] = p.default;
          }
        }
      }
      Object.assign(effectiveParams, userParams);

      const paramKeys = new Set(Object.keys(effectiveParams));
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
        parameters: effectiveParams,
        result_shape: resultShape,
        result_statistics: null,
        description: meta?.description ?? null,
        param_descriptions: paramDescriptions,
        output_type: outputType,
        execution_status: executionStatus,
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

    // Scientific scalars and structured fields that Sherpa's context builder
    // can summarize. Keep this list in sync with the per-node-type summarizers
    // in spectra-server/src/spectrasherpa_server/context_builder.py.
    const SCIENTIFIC_KEYS = new Set([
      // Shapes and identity
      "type",
      "shape",
      "n_samples",
      "n_features",
      "n_components",
      "n_classes",
      "classes",
      // Regression metrics
      "r2",
      "R2",
      "rmse",
      "RMSE",
      "rmsep",
      "RMSEP",
      "rmsecv",
      "RMSECV",
      "q2",
      "Q2",
      "mae",
      "MAE",
      "sep",
      "SEP",
      "rer",
      "RER",
      "rpd",
      "bias",
      // Classification metrics
      "accuracy",
      "train_accuracy",
      "cv_accuracy",
      "cv_balanced_accuracy",
      "f1_score",
      "precision",
      "recall",
      "confusion_matrix",
      "per_class",
      // Decomposition metrics
      "explained_variance",
      "explained_variance_ratio",
      "cumulative_variance",
      "reconstruction_error",
      // Clustering metrics
      "silhouette_score",
      "inertia",
      "n_clusters",
      // Diagnostics
      "hotelling_t2",
      "q_residuals",
      "t2_critical_95",
      "q_critical_95",
      "n_outliers",
      "outlier_percentage",
      "t2_limit",
      "q_limit",
      // Chemistry-aware context (consumed by extract_salient_features_context)
      "salient_features",
      // Status
      "status",
      "task_type",
    ]);

    const isSimpleValue = (v: unknown): boolean =>
      v == null ||
      typeof v === "string" ||
      typeof v === "number" ||
      typeof v === "boolean";

    const pickScientificFields = (
      obj: Record<string, unknown>
    ): Record<string, unknown> => {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(obj)) {
        if (!SCIENTIFIC_KEYS.has(k)) {
          continue;
        }
        // Pass through scalars, small arrays, and nested objects as-is.
        // The server's context builder further compacts these.
        if (isSimpleValue(v)) {
          out[k] = v;
        } else if (Array.isArray(v)) {
          out[k] = v;
        } else if (typeof v === "object") {
          out[k] = v;
        }
      }
      return out;
    };

    let results_summary: Record<string, Record<string, unknown>> | null = null;
    if (lastExecutionResults) {
      results_summary = {};
      for (const [nodeId, rawResult] of Object.entries(lastExecutionResults)) {
        if (!rawResult || typeof rawResult !== "object") {
          continue;
        }
        const result = rawResult as Record<string, unknown>;

        // Always include shape identity fields even if not in SCIENTIFIC_KEYS match.
        const summary: Record<string, unknown> = {
          type: result.type ?? null,
          shape: result.shape ?? null,
          n_samples: result.n_samples ?? null,
          n_features: result.n_features ?? null,
        };

        // Scientific fields from the top level of the result.
        Object.assign(summary, pickScientificFields(result));

        // Scientific fields from the nested metadata block.
        const metadata = result.metadata;
        if (metadata && typeof metadata === "object") {
          Object.assign(summary, pickScientificFields(metadata as Record<string, unknown>));
          // Also preserve the raw metadata primitives for backwards compat.
          summary.metadata = Object.fromEntries(
            Object.entries(metadata as Record<string, unknown>).filter(([, value]) =>
              isSimpleValue(value)
            )
          );
        } else {
          summary.metadata = null;
        }

        // For multi-output nodes the SherpaDataset lives under ``default``;
        // unwrap so the scientific fields (title, backend, extra,
        // target_context, metadata.feature_names) come from the right layer.
        // We pull fields from ``ds`` (unwrapped) for dataset identity but
        // keep using ``result`` above for the legacy summary shape.
        const ds = unwrapDatasetResult(result) ?? result;
        const dsMetadata = toObject(ds.metadata) ?? toObject(metadata);
        const extra = toObject(ds.extra);
        const targetContext = toObject(ds.target_context);
        const featureNames =
          toStringList(dsMetadata?.feature_names) ??
          toStringList(extra?.["csv.feature_names"]) ??
          toStringList(toObject(ds.x_axis)?.labels) ??
          toStringList(toObject(ds.feature_axis)?.labels);
        const targetNames =
          toStringList(targetContext?.target_names) ??
          toStringList(targetContext?.class_names) ??
          toStringList(extra?.["sklearn.target_names"]) ??
          toStringList(dsMetadata?.["sklearn.target_names"]);
        const datasetName =
          typeof extra?.["sklearn.dataset_name"] === "string"
            ? extra["sklearn.dataset_name"]
            : typeof extra?.["catalog.dataset_name"] === "string"
              ? extra["catalog.dataset_name"]
              : typeof dsMetadata?.["sklearn.dataset_name"] === "string"
                ? dsMetadata["sklearn.dataset_name"]
                : typeof dsMetadata?.["catalog.dataset_name"] === "string"
                  ? dsMetadata["catalog.dataset_name"]
                  : typeof ds.title === "string" && ds.title.trim()
                    ? ds.title
                    : null;
        if (typeof ds.backend === "string" && ds.backend.trim()) {
          summary.backend = ds.backend;
        }
        if (datasetName) {
          summary.dataset_name = datasetName;
        }
        if (featureNames) {
          summary.feature_names = featureNames;
        }
        if (targetNames) {
          summary.target_names = targetNames;
        }
        // Fill in shape fields from the unwrapped dataset too — they're
        // usually null at the top level of a multi-output wrapper.
        if (summary.n_samples == null && typeof ds.n_samples === "number") {
          summary.n_samples = ds.n_samples;
        }
        if (summary.n_features == null && typeof ds.n_features === "number") {
          summary.n_features = ds.n_features;
        }
        if ((summary.shape == null || (Array.isArray(summary.shape) && summary.shape.length === 0))
            && Array.isArray(ds.shape)) {
          summary.shape = ds.shape;
        }

        results_summary[nodeId] = summary;
      }
    }

    // Prefer explicitly explored catalog metadata, but fall back to the active file
    // inspection so Sherpa still gets technique/axis context for CSV/manual loads.
    const summarizedDatasetContext =
      summarizeDatasetForSherpaContext(
        dataStore.catalogDatasetInfo as Record<string, unknown> | null
      )
      ?? summarizeDatasetForSherpaContext(
        dataStore.fileInfo as unknown as Record<string, unknown> | null
      );
    let derivedDatasetIdentity: Partial<SherpaDatasetContext> | null = null;
    for (const node of workflow.nodes) {
      if (!node.type.startsWith("data.")) {
        continue;
      }
      const rawResult = lastExecutionResults?.[String(node.id)] ?? null;
      derivedDatasetIdentity = deriveDatasetIdentity(
        node as { label?: unknown; params?: Record<string, unknown> },
        rawResult
      );
      if (derivedDatasetIdentity) {
        break;
      }
    }
    const dataset_context =
      summarizedDatasetContext || derivedDatasetIdentity
        ? {
          ...(summarizedDatasetContext ?? emptyDatasetContext()),
          ...(derivedDatasetIdentity ?? {}),
        }
        : null;

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
          conversation_id: currentConversationId.value,
          project_id: projectStore.currentProjectId,
          workflow_id: workflow.workflowId,
          workflow_context: buildSyncPayload(),
        },
      })
    );
  }

  function clearMessages(): void {
    startNewConversation();
    lastPeaksResult.value = null;
    lastCodeResult.value = null;
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
        currentConversationId.value =
          typeof payload.conversation_id === "string" ? payload.conversation_id : currentConversationId.value;
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
        currentConversationId.value =
          typeof payload.conversation_id === "string" ? payload.conversation_id : currentConversationId.value;
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
          if (currentConversationId.value) {
            updateConversationSummary(currentConversationId.value);
          }
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
    _ensureWelcomeMessage();
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
    _resetTransientState();
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
    conversations,
    currentConversationId,
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
    startNewConversation,
    refreshConversations,
    loadConversation,
    deleteConversation,
    openSubscriptionUpgrade,
    init,
    dispose,
  };
});
