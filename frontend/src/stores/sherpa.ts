import { sherpaResponseTimeoutMs } from "@/lib/sherpaTimeouts";
import { requireAdvisorTransport } from "@/lib/advisorTransport";
import { SCIENTIFIC_QUERY_REFUSAL, recordScientificQueryOutcome } from "@/lib/scientificQueryGuidance";
import { attentionSnapshot } from "@/lib/sherpaAttention";
/* eslint-disable @typescript-eslint/no-explicit-any -- assistant sync payloads intentionally preserve flexible node parameter/result shapes. */
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
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
import { useAdvisorStore } from "@/stores/advisor";
import { useLlmStore } from "@/stores/llm";
import { useWorkbookStore } from "@/stores/workbook";
import { useNotificationStore } from "@/stores/notification";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import { summarizeProposalReceipt } from "@/utils/proposalReceipt";
import { createMessageId } from "@/utils/messageIds";
import { bindAdvisorExecutionContext } from "@/utils/advisorExecutionContext";
import { summarizeNodePlots } from "@/utils/plotStateSummary";
import type {
  ConversationSummary,
  SherpaMessage,
  SherpaRecommendationPayload,
  SherpaResumeRecap,
} from "@/types";

type SherpaState = "idle" | "syncing" | "chatting" | "error";

function createSherpaMessage(
  role: SherpaMessage["role"],
  content: string,
  extras?: Partial<Omit<SherpaMessage, "id" | "role" | "content">>,
): SherpaMessage {
  return { id: createMessageId("sherpa"), role, content, ...extras };
}

function isSherpaRole(value: unknown): value is SherpaMessage["role"] {
  return value === "user" || value === "assistant" || value === "system";
}

function normalizeSherpaMessages(raw: unknown): SherpaMessage[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((m) => {
    const message = m && typeof m === "object" ? (m as Partial<SherpaMessage>) : {};
    return {
      ...message,
      id: typeof message.id === "string" && message.id ? message.id : createMessageId("sherpa"),
      role: isSherpaRole(message.role) ? message.role : "assistant",
      content: typeof message.content === "string" ? message.content : "",
    };
  });
}
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

export interface ProductWorkflowProposalPreview {
  proposal: Record<string, any>;
  sourceWorkflowId: number;
}

const STORAGE_KEY = "sherpa_conversations";
const RESUME_RECAP_LAST_SEEN_PREFIX = "spectra_sherpa_project_recap_last_seen_";
const RESUME_RECAP_DISMISSED_PREFIX = "spectra_sherpa_project_recap_dismissed_";
const RESUME_RECAP_FAILURE_PREFIX = "spectra_sherpa_project_recap_failure_";
const RESUME_RECAP_INTERVAL_MS = 24 * 60 * 60 * 1000;
const RESUME_RECAP_FAILURE_RETRY_MS = 60 * 60 * 1000;

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
  const { appMode, siteProfile, appConfig } = useAppConfig();
  const boundedContext = computed(() => appConfig.value?.advisorContextPolicy === "receipt");
  const qualified = computed(() => appMode.value === "enterprise" && siteProfile?.value === "pro");
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
  const pendingProductProposal = ref<ProductWorkflowProposalPreview | null>(null);
  const subscriptionRequired = ref<string | null>(null);
  const subscriptionUpgradeUrl = ref<string | null>(null);
  const lastActivitySummary = ref<string | null>(null);
  const resumeRecap = ref<SherpaResumeRecap | null>(null);
  const chatServerAcknowledged = ref(false);
  const currentChatRequestId = ref<string | null>(null);
  const currentSyncRequestId = ref<string | null>(null);
  // R1 canonical routing — captured at sendMessage time so a sheet
  // switch mid-stream cannot rebind the conversation to the wrong scope.
  const pendingAdvisorNodeId = ref<number | null>(null);
  const pendingWorkflowId = ref<number | null>(null);
  const conversationSnapshots = new Map<
    string,
    { messages: SherpaMessage[]; summary: ConversationSummary }
  >();
  const analysisStatus = ref("");
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

  let conversationIndexRequest = 0;
  async function refreshConversations(projectId = projectStore.currentProjectId): Promise<void> {
    const indexRequest = ++conversationIndexRequest;
    if (qualified.value) {
      if (!projectId) { conversations.value = []; return; }
      const response = await api.get(`/commercial/projects/${projectId}/conversations`);
      if (indexRequest === conversationIndexRequest && projectId === projectStore.currentProjectId) conversations.value = response.data;
      return;
    }

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

    const activeConversationId =
      useAdvisorStore().activeChannel?.conversation_id ?? currentConversationId.value;
    if (!activeConversationId) {
      conversations.value = [];
      return;
    }

    try {
      const response = boundedContext.value
        ? await requireAdvisorTransport().loadConversation(activeConversationId)
        : await api.get(`/llm/conversation/${activeConversationId}`, {
            params: { project_id: projectId },
          });
      const loadedConversationId = String(
        response.data.conversation_id || response.data.id || activeConversationId,
      );
      setActiveChannelTopics(
        loadedConversationId,
        typeof response.data.title === "string" ? response.data.title : null,
        String(response.data.updated_at || response.data.updatedAt || new Date().toISOString()),
      );
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404 && restoreConversationSnapshot(activeConversationId)) {
        console.warn(
          "[sherpa] refreshConversations 404 — restored active worksheet topic from memory:",
          { activeConversationId, projectId },
        );
        return;
      }
      console.warn("[sherpa] refreshConversations failed — preserving worksheet topic state:", err);
    }
  }

  function cloneMessages(items = messages.value): SherpaMessage[] {
    return items.map((message) => ({ ...message }));
  }

  function isWelcomeOnly(items = messages.value): boolean {
    return (
      items.length === 1
      && items[0]?.role === "assistant"
      && items[0]?.content.includes("Welcome to Sherpa Advisor")
    );
  }

  function deriveConversationTitle(fallbackIndex = conversations.value.length + 1): string {
    const firstUser = messages.value.find((message) => message.role === "user");
    return firstUser?.content.slice(0, 60) || `Sherpa Conversation ${fallbackIndex}`;
  }

  function setActiveChannelTopics(
    conversationId: string,
    title?: string | null,
    updatedAt = new Date().toISOString(),
  ): void {
    const existing =
      conversations.value.find((item) => item.id === conversationId)
      ?? conversationSnapshots.get(conversationId)?.summary;
    const summary = {
      id: conversationId,
      title: title || existing?.title || deriveConversationTitle(1),
      updatedAt,
    };
    conversations.value = [summary];
    conversationSnapshots.set(conversationId, {
      messages: cloneMessages(),
      summary,
    });
  }

  function clearActiveChannelTopics(): void {
    if (isServerBacked.value) {
      conversations.value = [];
    }
  }

  function snapshotCurrentConversation(): void {
    const conversationId = currentConversationId.value;
    if (!conversationId || isWelcomeOnly()) {
      return;
    }
    const existing =
      conversations.value.find((item) => item.id === conversationId)
      ?? conversationSnapshots.get(conversationId)?.summary;
    const summary = {
      id: conversationId,
      title: existing?.title || deriveConversationTitle(1),
      updatedAt: new Date().toISOString(),
    };
    conversationSnapshots.set(conversationId, {
      messages: cloneMessages(),
      summary,
    });
  }

  function restoreConversationSnapshot(conversationId: string): boolean {
    const snapshot = conversationSnapshots.get(conversationId);
    if (!snapshot) {
      return false;
    }
    currentConversationId.value = conversationId;
    messages.value = cloneMessages(snapshot.messages);
    conversations.value = [snapshot.summary];
    return true;
  }

  function ensureOptimisticSidebarEntry(conversationId: string): void {
    if (isServerBacked.value) {
      setActiveChannelTopics(conversationId);
      return;
    }
    if (conversations.value.some((item) => item.id === conversationId)) {
      return;
    }
    const derivedTitle = deriveConversationTitle();
    conversations.value.unshift({
      id: conversationId,
      title: derivedTitle,
      updatedAt: new Date().toISOString(),
    });
  }

  function updateConversationSummary(conversationId: string): void {
    // In server-backed mode, Topics is intentionally scoped to the active
    // worksheet channel: one channel, one topic. Local mode keeps the old
    // multi-topic localStorage list.
    const derivedTitle = deriveConversationTitle();
    const updatedAt = new Date().toISOString();
    const existing = conversations.value.find((item) => item.id === conversationId);

    if (isServerBacked.value) {
      setActiveChannelTopics(conversationId, existing?.title || derivedTitle, updatedAt);
      return;
    }

    if (existing) {
      existing.updatedAt = updatedAt;
      // Don't overwrite an existing title — server may have a
      // better one from prior messages.
      if (!existing.title || existing.title === "Untitled conversation") {
        existing.title = derivedTitle;
      }
    } else {
      conversations.value.unshift({ id: conversationId, title: derivedTitle, updatedAt });
    }

    persistConversations(conversations.value);
  }

  let conversationLoadRequest = 0;
  async function loadConversation(conversationId: string): Promise<void> {
    const request = ++conversationLoadRequest;
    const projectId = projectStore.currentProjectId;
    if (conversationId === currentConversationId.value && messages.value.length > 0) {
      if (isServerBacked.value) {
        setActiveChannelTopics(conversationId);
      }
      return;
    }

    snapshotCurrentConversation();

    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;

    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before loading a Sherpa conversation.");
    }

    let response;
    try {
      response = qualified.value
        ? await api.get(`/commercial/projects/${projectId}/conversations/${conversationId}`)
        : boundedContext.value
        ? await requireAdvisorTransport().loadConversation(conversationId)
        : await api.get(`/llm/conversation/${conversationId}`, { params });
    } catch (err) {
      if (request !== conversationLoadRequest || projectId !== projectStore.currentProjectId) return;
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) {
        if (!qualified.value && isServerBacked.value && restoreConversationSnapshot(conversationId)) {
          console.warn(
            "[sherpa] conversation detail 404 during channel switch — restored in-memory worksheet conversation:",
            { conversationId },
          );
          return;
        }
        // Stale sidebar entry — the backend no longer has this
        // conversation (optimistic-only row, or upstream lost it).
        // Remove it so it can't be clicked again, and start fresh.
        if (!isServerBacked.value) {
          conversations.value = conversations.value.filter(
            (item) => item.id !== conversationId,
          );
        }
        if (currentConversationId.value === conversationId) {
          currentConversationId.value = null;
          messages.value = [];
        }
        throw new Error("This conversation is no longer available. It has been removed from Topics.");
      }
      throw err;
    }

    if (request !== conversationLoadRequest || projectId !== projectStore.currentProjectId) return;
    const loadedConversationId = String(
      response.data.conversation_id || response.data.id || conversationId,
    );
    currentConversationId.value = loadedConversationId;
    messages.value = normalizeSherpaMessages(
      response.data.messages as Array<{ role: SherpaMessage["role"]; content: string }>,
    );
    if (isServerBacked.value) {
      setActiveChannelTopics(
        loadedConversationId,
        typeof response.data.title === "string" ? response.data.title : null,
      );
    }
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
    pendingAdvisorNodeId.value = null;
  }

  async function deleteConversation(conversationId: string): Promise<void> {
    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;

    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before deleting a Sherpa conversation.");
    }

    if (boundedContext.value) {
      await requireAdvisorTransport().deleteConversation(conversationId);
    } else {
      await api.delete(`/llm/conversation/${conversationId}`, { params });
    }
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

  function _recapStorageKey(prefix: string, projectId: number): string {
    return `${prefix}${projectId}`;
  }

  function _readRecapLastSeen(projectId: number): number | null {
    try {
      const raw = localStorage.getItem(
        _recapStorageKey(RESUME_RECAP_LAST_SEEN_PREFIX, projectId)
      );
      const parsed = raw === null ? NaN : Number(raw);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    } catch {
      return null;
    }
  }

  function _writeRecapLastSeen(projectId: number, value: number): void {
    try {
      localStorage.setItem(
        _recapStorageKey(RESUME_RECAP_LAST_SEEN_PREFIX, projectId),
        String(value),
      );
    } catch {
      /* localStorage can be unavailable in tests or hardened browsers. */
    }
  }

  function _readRecapFailure(projectId: number): number | null {
    try {
      const raw = localStorage.getItem(
        _recapStorageKey(RESUME_RECAP_FAILURE_PREFIX, projectId)
      );
      const parsed = raw === null ? NaN : Number(raw);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    } catch {
      return null;
    }
  }

  function _writeRecapFailure(projectId: number, value: number): void {
    try {
      localStorage.setItem(
        _recapStorageKey(RESUME_RECAP_FAILURE_PREFIX, projectId),
        String(value),
      );
    } catch {
      /* localStorage can be unavailable in tests or hardened browsers. */
    }
  }

  function _clearRecapFailure(projectId: number): void {
    try {
      localStorage.removeItem(_recapStorageKey(RESUME_RECAP_FAILURE_PREFIX, projectId));
    } catch {
      /* localStorage can be unavailable in tests or hardened browsers. */
    }
  }

  function _isRecapDismissed(projectId: number, lastActiveAt: string | null): boolean {
    try {
      const dismissedMarker = localStorage.getItem(
        _recapStorageKey(RESUME_RECAP_DISMISSED_PREFIX, projectId)
      );
      return Boolean(dismissedMarker && dismissedMarker === (lastActiveAt || "unknown"));
    } catch {
      return false;
    }
  }

  function _markRecapDismissed(recap: SherpaResumeRecap): void {
    try {
      localStorage.setItem(
        _recapStorageKey(RESUME_RECAP_DISMISSED_PREFIX, recap.projectId),
        recap.lastActiveAt || "unknown",
      );
    } catch {
      /* localStorage can be unavailable in tests or hardened browsers. */
    }
  }

  function _appendSystemMessage(content: string): void {
    messages.value.push(createSherpaMessage("system", content));
  }

  function _memoryScopesFromPayload(payload: SherpaEventPayload): string[] {
    const raw = payload.memory_scopes;
    if (!Array.isArray(raw)) {
      return [];
    }
    return Array.from(
      new Set(
        raw
          .map((scope) => String(scope).trim())
          .filter(Boolean)
      )
    );
  }

  function _followUpsFromPayload(payload: SherpaEventPayload): string[] {
    const raw = payload.suggestions;
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw
      .map((suggestion) => String(suggestion).trim())
      .filter(Boolean)
      .slice(0, 3);
  }

  function _createWelcomeMessage(): SherpaMessage {
    return createSherpaMessage(
      "assistant",
      [
        "Welcome to Sherpa Advisor. Quick tour:",
        "",
        "1. **Dashboard** — start a new analysis or return to recent work.",
        "2. **Project** — review project context, files, and Advisor memory.",
        "3. **Data** — import, upload, synthesize, or stage library datasets.",
        "4. **Workflows** — build and run chemometric pipelines.",
        "5. **Runs** — inspect model runs, metrics, outputs, and saved models.",
        "6. **Deploy** — package validated workflows for reuse.",
        "7. **Report** — turn results into shareable analysis notes.",
        "",
        "Use **Settings** for keys and integrations. Ask me as you go; I can explain choices, diagnose runs, and suggest next steps.",
      ].join("\n"),
    );
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
    ++conversationLoadRequest;
    snapshotCurrentConversation();
    finalizeChatCommunication();
    finalizeSyncCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    messages.value = [];
    _resetTransientState();
    currentConversationId.value = null;
    clearActiveChannelTopics();
    lastActivitySummary.value = null;
    _ensureWelcomeMessage();
  }

  registerProjectScopeReset(() => {
    if (!qualified.value) return;
    ++conversationIndexRequest;
    startNewConversation();
    // An old project snapshot must never satisfy a later 404 or same-ID load.
    conversationSnapshots.clear();
    conversations.value = [];
    resumeRecap.value = null;
  });

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
    messages.value.push(createSherpaMessage("assistant", ""));
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
    // Absolute deadline: acknowledgments, heartbeats and tool activity cannot reset it.
    if (activeChatTimeout !== null) return;
    const expectedRequestId = currentChatRequestId.value;
    activeChatTimeout = window.setTimeout(() => {
      if (chatState.value === "chatting" && currentChatRequestId.value === expectedRequestId) {
        sendInterrupt(expectedRequestId);
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
        pendingAdvisorNodeId.value = null;
        currentChatRequestId.value = null;
        unsubscribeChatEvents?.();
        unsubscribeChatEvents = null;
      }
    }, sherpaResponseTimeoutMs());
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
    analysisStatus.value = "";
  }

  function finalizeSyncCommunication(): void {
    clearSyncCommunicationTimer();
    clearActiveSyncTimeout();
    if (chatState.value !== "chatting") analysisStatus.value = "";
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
    pendingAdvisorNodeId.value = null;
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
      dataset_id: null,
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
     * port. Multi-output nodes (for example ``data.file_load`` and ``model.*``) serialize to
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
      if (typeof ds.dataset_id === "string" && ds.dataset_id.trim()) {
        identity.dataset_id = ds.dataset_id;
      }
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
        // Saved typed projections at default selection (not the current open plot) —
        // grounds "explain the plot" answers in the real plot state instead of
        // textbook defaults. Null when the node has no executed result.
        plot_states: hasPersistedResult ? summarizeNodePlots(rawResult, workflow.lastExecutionPresentations?.[String(n.id)], workflow.lastExecutionResultDescriptors?.[String(n.id)]) : null,
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
    // in the commercial server's context builder.
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
      "r2_cv",
      "r2_test",
      "rmse",
      "RMSE",
      "rmsep",
      "RMSEP",
      "rmse_test",
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
      "metrics",
      "schema_version",
      "primary_split",
      "primary_metric",
      "accuracy",
      "train_accuracy",
      "train_balanced_accuracy",
      "train_f1_macro",
      "train_precision_macro",
      "train_recall_macro",
      "train_sensitivity_macro",
      "train_specificity_macro",
      "cv_accuracy",
      "cv_balanced_accuracy",
      "cv_f1_macro",
      "cv_precision_macro",
      "cv_recall_macro",
      "cv_sensitivity_macro",
      "cv_specificity_macro",
      "test_accuracy",
      "test_balanced_accuracy",
      "test_f1_macro",
      "test_precision_macro",
      "test_recall_macro",
      "test_sensitivity_macro",
      "test_specificity_macro",
      "balanced_accuracy",
      "f1_macro",
      "precision_macro",
      "recall_macro",
      "sensitivity_macro",
      "specificity_macro",
      "f1_score",
      "precision",
      "recall",
      "confusion_matrix",
      "confusion_matrix_train",
      "confusion_matrix_cv",
      "confusion_matrix_test",
      "confusion_matrices",
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

        // PeakTable owns the computed consensus results. Project the existing
        // fields into the chat context schema; this is not a workflow output.
        const peaks = toObject(result.peaks);
        const peakMetadata = toObject(peaks?.metadata);
        if (peakMetadata?.method === "peak_finding" && Array.isArray(peaks?.data)) {
          summary.salient_features = {
            ...peakMetadata,
            features: peaks.data.map((row: Record<string, unknown>) => ({
              position: row.median_pos,
              importance: row.detection_fraction,
              label: row.label,
            })),
          };
        }

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
        if (typeof ds.dataset_id === "string" && ds.dataset_id.trim()) {
          summary.dataset_id = ds.dataset_id;
        }
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
    const myDataset = dataStore.captureAdvisorDatasetContext?.() ?? null;
    const workbookStore = useWorkbookStore();
    const activeSheet = workbookStore.activeSheet;
    const analysisContext = {
      schema: "spectra-analysis-context/1",
      captured_at: new Date().toISOString(),
      project_id: projectStore.currentProjectId,
      sheet: activeSheet
        ? {
            workflow_id: activeSheet.workflowId,
            name: activeSheet.name,
            purpose: activeSheet.purpose,
            sheet_order: activeSheet.sheetOrder,
          }
        : null,
      selection: myDataset,
      authority:
        "The active workflow sheet and current My Dataset selection are the input authority. " +
        "Treat this context as sheet-scoped and do not reuse settings from another sheet.",
    };
    // Input authority (contract section 1) is what the user loaded: explored catalog
    // metadata, the active file inspection, and the data store's own capture. It is
    // disclosed even when execution interpretation is refused, so it must exclude
    // derivedDatasetIdentity, which is read out of lastExecutionResults and is
    // execution evidence that a stale draft may no longer describe.
    const current_input_context =
      summarizedDatasetContext || myDataset
        ? {
          ...(summarizedDatasetContext ?? emptyDatasetContext()),
          analysis_context: analysisContext,
          ...(myDataset ? { my_dataset: myDataset } : {}),
        }
        : null;
    const dataset_context =
      summarizedDatasetContext || derivedDatasetIdentity || myDataset
        ? {
          ...(summarizedDatasetContext ?? emptyDatasetContext()),
          ...(derivedDatasetIdentity ?? {}),
          analysis_context: analysisContext,
          ...(myDataset ? { my_dataset: myDataset } : {}),
        }
        : null;

    return bindAdvisorExecutionContext({
      active_attention: attentionSnapshot(),
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
    }, {
      isWorkflowStale: workflow.isWorkflowStale,
      executionEvidenceScope: workflow.executionEvidenceScope,
      restoredEvidenceNotice: workflow.restoredEvidenceNotice,
      lastExecutionResults: workflow.lastExecutionResults,
      restoredRunId: workflow.restoredRunId,
      lastExecutionParams: workflow.lastExecutionParams,
      currentInputContext: current_input_context,
    });
  }

  async function prepareProductWorkflowContext(workflowId: number | null): Promise<Record<string, unknown> | null> {
    return requireAdvisorTransport().prepareContext(workflowId);
  }

  // ── actions ────────────────────────────────────────────────

  async function maybeLoadResumeRecap(projectId = projectStore.currentProjectId): Promise<void> {
    if (!isServerBacked.value || !projectId) {
      resumeRecap.value = null;
      return;
    }
    if (resumeRecap.value?.projectId !== projectId) {
      resumeRecap.value = null;
    }

    const now = Date.now();
    const lastSeen = _readRecapLastSeen(projectId);
    if (lastSeen !== null && now - lastSeen < RESUME_RECAP_INTERVAL_MS) {
      return;
    }
    const lastFailure = _readRecapFailure(projectId);
    if (lastFailure !== null && now - lastFailure < RESUME_RECAP_FAILURE_RETRY_MS) {
      return;
    }

    try {
      const response = await api.get("/sherpa/recap", {
        params: { project_id: projectId },
      });
      _writeRecapLastSeen(projectId, now);
      _clearRecapFailure(projectId);
      const recap = typeof response.data?.recap === "string" ? response.data.recap.trim() : "";
      const lastActiveAt =
        typeof response.data?.last_active_at === "string"
          ? response.data.last_active_at
          : null;
      if (!recap || _isRecapDismissed(projectId, lastActiveAt)) {
        resumeRecap.value = null;
        return;
      }
      resumeRecap.value = {
        projectId,
        recap,
        lastActiveAt,
        cached: Boolean(response.data?.cached),
      };
    } catch (error) {
      _writeRecapFailure(projectId, now);
      console.warn("[sherpa] Resume recap could not be loaded:", error);
    }
  }

  function dismissResumeRecap(): void {
    if (resumeRecap.value) {
      _markRecapDismissed(resumeRecap.value);
    }
    resumeRecap.value = null;
  }

  async function syncWorkflow(): Promise<void> {
    if (syncState.value === "syncing") {
      return;
    }
    const llm = useLlmStore();
    finalizeSyncCommunication();
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    syncState.value = "syncing";
    analysisStatus.value = "Analysis in progress. Hit stop to interrupt";
    lastSyncError.value = null;
    const requestId = createSherpaRequestId();
    currentSyncRequestId.value = requestId;
    _recordActivity("Workflow sync requested.", { notify: true });
    scheduleSyncCommunicationNotice();
    clearActiveSyncTimeout();
    const expectedRequestId = requestId;
    activeSyncTimeout = window.setTimeout(() => {
      if (syncState.value === "syncing" && currentSyncRequestId.value === expectedRequestId) {
        sendInterrupt(currentSyncRequestId.value);
        syncState.value = "idle";
        currentSyncRequestId.value = null;
        unsubscribeSyncEvents?.();
        unsubscribeSyncEvents = null;
        _notifySherpa("Sherpa sync timed out. The service may be unavailable.", "warning");
        _appendSystemMessage("Sherpa sync timed out. The service may be unavailable.");
      }
    }, sherpaResponseTimeoutMs(true));
    try {
      await llm.connect();
    } catch {
      if (currentSyncRequestId.value !== requestId) return;
      finalizeSyncCommunication();
      lastSyncError.value = "WebSocket not connected";
      syncState.value = "error";
      messages.value.push(
        createSherpaMessage("system", "Unable to connect to the server. Please try again."),
      );
      return;
    }

    if (currentSyncRequestId.value !== requestId) return;
    const workflow = useWorkflowStore();
    if (!workflow.workflowId) {
      finalizeSyncCommunication();
      syncState.value = "idle";
      currentSyncRequestId.value = null;
      messages.value.push(
        createSherpaMessage(
          "system",
          "No workflow is currently loaded. Open or create a workflow first.",
        ),
      );
      return;
    }

    let syncPayload: Record<string, unknown>;
    try {
      syncPayload = boundedContext.value
        ? {
            workflow_id: workflow.workflowId,
            workflow_context: await prepareProductWorkflowContext(workflow.workflowId),
          }
        : buildSyncPayload();
    } catch (error: any) {
      if (currentSyncRequestId.value !== requestId) return;
      finalizeSyncCommunication();
      syncState.value = "idle";
      currentSyncRequestId.value = null;
      messages.value.push(
        createSherpaMessage(
          "system",
          error?.response?.data?.detail || error?.message || "Product workflow disclosure was refused.",
        ),
      );
      return;
    }

    if (currentSyncRequestId.value !== requestId) return;
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      lastSyncError.value = "WebSocket not ready";
      syncState.value = "error";
      messages.value.push(
        createSherpaMessage("system", "Connection is not ready. Please try again in a moment."),
      );
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
          ...syncPayload,
        },
      })
    );


  }

  function sendInterrupt(requestId: string | null): void {
    const ws = getWs();
    if (requestId && ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "cancel_request", request_id: requestId }));
    }
  }

  function stopAnalysis(): void {
    if (chatState.value !== "chatting" && syncState.value !== "syncing") return;
    sendInterrupt(currentChatRequestId.value);
    sendInterrupt(currentSyncRequestId.value);
    finalizeChatCommunication();
    finalizeSyncCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    unsubscribeSyncEvents?.();
    unsubscribeSyncEvents = null;
    chatState.value = "idle";
    syncState.value = "idle";
    currentChatRequestId.value = null;
    currentSyncRequestId.value = null;
    pendingAdvisorNodeId.value = null;
    streamingIndex.value = null;
    activeTools.value = [];
    _appendSystemMessage("Analysis interrupted. Any completed workflow or run has been preserved.");
  }

  async function sendMessage(message: string, _legacyUseTools?: boolean): Promise<void> {
    if (!message.trim() || chatState.value === "chatting") return;

    const llm = useLlmStore();

    messages.value.push(createSherpaMessage("user", message));
    const requestId = createSherpaRequestId();
    finalizeChatCommunication();
    unsubscribeChatEvents?.();
    unsubscribeChatEvents = null;
    currentChatRequestId.value = requestId;
    const advisorStoreSnapshot = useAdvisorStore();
    pendingAdvisorNodeId.value = advisorStoreSnapshot.activeNodeId;
    pendingProductProposal.value = null;
    _recordActivity(`User asked Sherpa: ${_truncateForLog(message)}`, {
      notify: true,
      detail: message,
    });

    chatState.value = "chatting";
    analysisStatus.value = "Analysis in progress. Hit stop to interrupt";
    activeTools.value = [];
    chatServerAcknowledged.value = false;
    subscriptionRequired.value = null;
    subscriptionUpgradeUrl.value = null;
    _recordActivity(
      `Sherpa request queued${_formatRequestSuffix(requestId)}.`,
      {
        notify: true,
      }
    );
    scheduleChatCommunicationNotice();
    scheduleActiveChatTimeout();

    const workflow = useWorkflowStore();
    pendingWorkflowId.value = workflow.workflowId;
    let workflowContext: Record<string, unknown> | null;
    try {
      workflowContext = boundedContext.value
        ? await prepareProductWorkflowContext(workflow.workflowId)
        : buildSyncPayload();
    } catch (error: any) {
      if (currentChatRequestId.value !== requestId) return;
      finalizeChatCommunication();
      chatState.value = "idle";
      currentChatRequestId.value = null;
      pendingAdvisorNodeId.value = null;
      messages.value.push(
        createSherpaMessage(
          "system",
          error?.response?.data?.detail || error?.message || "Product workflow disclosure was refused.",
        ),
      );
      return;
    }
    if (currentChatRequestId.value !== requestId) return;
    let ws: WebSocket | null = null;
    try {
      await llm.connect();
      ws = getWs();
    } catch {
      if (currentChatRequestId.value !== requestId) return;
      finalizeChatCommunication();
      chatState.value = "idle";
      currentChatRequestId.value = null;
      pendingAdvisorNodeId.value = null;
      messages.value.push(
        createSherpaMessage("assistant", "Unable to connect. Check the server and try again."),
      );
      return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      finalizeChatCommunication();
      chatState.value = "idle";
      currentChatRequestId.value = null;
      pendingAdvisorNodeId.value = null;
      messages.value.push(
        createSherpaMessage("system", "Connection is not ready. Please try again in a moment."),
      );
      return;
    }

    if (currentChatRequestId.value !== requestId) return;
    _recordActivity(`Sherpa request sent${_formatRequestSuffix(requestId)}.`, {
      notify: true,
    });

    // A fast server run may finish while the proposed sheet is still loading.
    // Preserve event order across that asynchronous navigation boundary.
    let proposalQueue: Promise<void> | null = null;
    unsubscribeChatEvents = subscribeSherpaEvents((payload) => {
      if (proposalQueue) {
        proposalQueue = proposalQueue.then(() => handleChatEvent(payload));
        return proposalQueue;
      }
      if (payload.type === SHERPA_WS_EVENT.workflowProposed) {
        proposalQueue = handleChatEvent(payload);
        return proposalQueue;
      }
      return handleChatEvent(payload);
    }, {
      requestId,
      types: [
        SHERPA_WS_EVENT.chatStart,
        SHERPA_WS_EVENT.chatChunk,
        SHERPA_WS_EVENT.chatFollowUps,
        SHERPA_WS_EVENT.chatDone,
        SHERPA_WS_EVENT.status,
        SHERPA_WS_EVENT.toolStart,
        SHERPA_WS_EVENT.toolResult,
        SHERPA_WS_EVENT.workflowProposed,
        SHERPA_WS_EVENT.workflowProposalPreview,
        SHERPA_WS_EVENT.subscriptionRequired,
        SHERPA_WS_EVENT.error,
      ],
    });

    ws.send(
      JSON.stringify({
        action: getSherpaChatAction(true),
        payload: {
          request_id: requestId,
          active_attention: attentionSnapshot(),
          message,
          // R1 canonical routing key.  Server resolves to topic →
          // conversation_id internally.  Legacy conversation_id field
          // retained in parallel for one release; retired in R2.
          advisor_node_id: pendingAdvisorNodeId.value,
          conversation_id: currentConversationId.value,
          project_id: projectStore.currentProjectId,
          workflow_id: workflow.workflowId,
          workflow_context: workflowContext,
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
    if (payload.request_id && payload.request_id !== currentSyncRequestId.value) return;
    try {
      _validateSherpaPayload(payload);

      if (payload.type === SHERPA_WS_EVENT.status) {
        if (payload.payload?.heartbeat) {
          analysisStatus.value = `Analysis in progress. Hit stop to interrupt · ${Number(payload.payload.elapsed_seconds || 0)}s — ${payload.payload.detail || "Reviewing workflow."}`;
          return;
        }
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
          messages.value.push(
            createSherpaMessage(
              "assistant",
              "Your workflow looks good -- no specific recommendations at this time.",
            ),
          );
        } else {
          for (const rec of recs) {
            const pct = Math.round(rec.confidence * 100);
            messages.value.push(
              createSherpaMessage(
                "assistant",
                `**${rec.title}** (${rec.category}, ${pct}% confidence)\n\n${rec.explanation}`,
                { recommendations: [rec] },
              ),
            );
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

  async function handleChatEvent(payload: SherpaEventPayload): Promise<void> {
    if (payload.request_id && payload.request_id !== currentChatRequestId.value) return;
    const eventRequestId = currentChatRequestId.value;
    try {
      _validateSherpaPayload(payload);

      if (payload.type === SHERPA_WS_EVENT.chatStart) {
        clearChatCommunicationTimer();
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
        messages.value.push(createSherpaMessage("assistant", ""));
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

      if (payload.type === SHERPA_WS_EVENT.chatFollowUps) {
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        currentConversationId.value =
          typeof payload.conversation_id === "string" ? payload.conversation_id : currentConversationId.value;
        _ensureAssistantBubbleForStreaming(currentChatRequestId.value);
        const followUps = _followUpsFromPayload(payload);
        if (
          followUps.length > 0
          && streamingIndex.value !== null
          && messages.value[streamingIndex.value]?.role === "assistant"
        ) {
          messages.value[streamingIndex.value].followUps = followUps;
        }
        _recordActivity(
          `Sherpa suggested follow-up questions${_formatRequestSuffix(payload.request_id)}${_formatTimingSuffix(payload.timing)}.`
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
        if (response.trim()) recordScientificQueryOutcome(response.trim() !== SCIENTIFIC_QUERY_REFUSAL);
        const memoryScopes = _memoryScopesFromPayload(payload);
        if (
          memoryScopes.length > 0
          && streamingIndex.value !== null
          && messages.value[streamingIndex.value]?.role === "assistant"
        ) {
          messages.value[streamingIndex.value].memoryScopes = memoryScopes;
        }
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
        } else if (!(payload as any).execution_result) {
          const emptyMessage = `Sherpa returned an empty response${_formatRequestSuffix(payload.request_id)}${_formatTimingSuffix(payload.timing)}.`;
          _recordActivity(emptyMessage, {
            notify: true,
            severity: "warning",
          });
          _appendSystemMessage(
            "Sherpa returned an empty response. The request may have been truncated or produced no visible output."
          );
        }
        const execution = (payload as any).execution_result;
        if (execution && typeof execution === "object") {
          const workflowStore = useWorkflowStore();
          _appendSystemMessage(`Workflow execution: ${String(execution.status)}${execution.run_id ? ` (run ${execution.run_id})` : ""}.${execution.error ? ` ${typeof execution.error === "string" ? execution.error : JSON.stringify(execution.error)}` : ""}`);
          if (execution.run_id && workflowStore.workflowId === execution.workflow_id && !workflowStore.hasUnsavedChanges) {
            await workflowStore.loadWorkflow(execution.workflow_id, execution.run_id);
            if (currentChatRequestId.value !== eventRequestId) return;
          }
        }
        currentChatRequestId.value = null;
        pendingAdvisorNodeId.value = null;
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.status) {
        clearChatCommunicationTimer();
        chatServerAcknowledged.value = true;
        currentChatRequestId.value =
          typeof payload.request_id === "string" ? payload.request_id : currentChatRequestId.value;
        if (payload.payload?.heartbeat) {
          const elapsed = Number(payload.payload.elapsed_seconds || 0);
          analysisStatus.value = `Analysis in progress. Hit stop to interrupt · ${elapsed}s — ${payload.payload.detail || "Waiting for the model response."}`;
          return;
        }
        const stage = String(payload.payload?.stage || "unknown");
        const detail =
          typeof payload.payload?.detail === "string" ? payload.payload.detail : null;
        // Audit findings #15 + #19: the server attaches the secondary model
        // name and an explicit tool-support flag on the secondary_llm warning
        // event so the frontend can render contextual messaging without
        // hard-coding model identity into the bundle.
        const secondaryModel =
          typeof payload.payload?.secondary_model === "string"
            ? payload.payload.secondary_model
            : null;
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
          secondary_llm: secondaryModel
            ? `Primary AI is busy — Sherpa is using a backup model (${secondaryModel}). Responses may be briefer; agentic tools are unavailable for this reply.`
            : "Primary AI is busy — Sherpa is using a backup model. Responses may be briefer and some agentic tools are unavailable.",
          tool_round_limit:
            "Sherpa reached the tool round limit and is finishing without more tool calls.",
        };
        const baseMessage = stageMessages[stage] || `Sherpa status: ${stage}.`;
        // For secondary_llm the server-provided detail already includes the
        // model name + tool-availability hint; treating it as the canonical
        // text avoids redundant phrasing in the activity toast.
        const useServerDetail = stage === "secondary_llm" && detail !== null;
        const renderedMessage = useServerDetail ? detail : baseMessage;
        const extraDetail = !useServerDetail && detail && detail !== baseMessage ? ` ${detail}` : "";
        const statusMessage = `${renderedMessage}${_formatRequestSuffix(payload.request_id)}${extraDetail}${_formatTimingSuffix(payload.timing)}`;
        // Severity split (audit finding #16): the secondary-LLM event signals
        // a degraded server-side service outside the user's control and
        // warrants a warning.  tool_round_limit is operational (Sherpa hit
        // its in-request loop budget) and stays at info.
        _recordActivity(statusMessage, {
          notify: true,
          severity: stage === "secondary_llm" ? "warning" : "info",
        });
        if (stage === "tool_round_limit" || stage === "secondary_llm") {
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

      if (payload.type === SHERPA_WS_EVENT.workflowProposed) {
        chatServerAcknowledged.value = true;
        // The proposal event owns channel binding for both the source sheet
        // and generated sheet. Clear the normal chat completion binder before
        // any awaited work so a following chat_done event cannot race in and
        // re-bind the source sheet to the generated conversation.
        pendingAdvisorNodeId.value = null;
        const newWorkflowId = Number(payload.new_workflow_id);
        const suggestedName = String(payload.suggested_name || "Alternative");
        const newConversationId = (payload as any).conversation_id;
        const parentConversationId = (payload as any).parent_conversation_id;

        const workbookStore = useWorkbookStore();
        await workbookStore.refreshSheets();
        if (currentChatRequestId.value !== eventRequestId) return;

        // Conversation → topic binding is handled server-side via
        // ``_persist_advisor_node_conversation`` after every chat turn,
        // and the parent/child memory_node rows are created on the
        // first switchScope call against each scope.  The frontend's
        // job is just to surface the new conversation ids in the
        // Topics sidebar.
        if (parentConversationId && typeof parentConversationId === "string") {
          ensureOptimisticSidebarEntry(parentConversationId);
        }
        if (newConversationId && typeof newConversationId === "string") {
          currentConversationId.value = newConversationId;
          ensureOptimisticSidebarEntry(newConversationId);
        }
        if (Number.isFinite(newWorkflowId)) {
          await workbookStore.selectWorkflowSheet(newWorkflowId);
          if (currentChatRequestId.value !== eventRequestId) return;
          // Proposal events describe drafts. Execution requires server-owned
          // authority pinned to the admitted definition.
        }
        _appendSystemMessage(`Generated alternative → opened as Sheet '${suggestedName}'.\n${summarizeProposalReceipt((payload as any).proposal_receipt)}`);
        noteChatActivity();
        return;
      }

      if (payload.type === SHERPA_WS_EVENT.workflowProposalPreview) {
        chatServerAcknowledged.value = true;
        const proposal = (payload as any).proposal;
        const sourceWorkflowId = pendingWorkflowId.value;
        if (!proposal || typeof proposal !== "object" || sourceWorkflowId == null) {
          _appendSystemMessage("Sherpa's workflow proposal could not be bound to the source sheet.");
          return;
        }
        pendingProductProposal.value = { proposal, sourceWorkflowId };
        _appendSystemMessage("Sherpa prepared a workflow proposal. Review the exact preview before applying it.");
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
        pendingAdvisorNodeId.value = null;
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
        pendingAdvisorNodeId.value = null;
      }
    } catch (error) {
      if (currentChatRequestId.value !== eventRequestId) return;
      const message =
        error instanceof Error ? error.message : "Unknown Sherpa chat event error.";
      finalizeChatCommunication();
      chatState.value = "error";
      streamingIndex.value = null;
      currentChatRequestId.value = null;
      pendingAdvisorNodeId.value = null;
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

  async function confirmProductProposal(): Promise<void> {
    const pending = pendingProductProposal.value;
    if (!pending) return;
    const workflowId = await requireAdvisorTransport().confirmProposal(pending.sourceWorkflowId, pending.proposal);
    pendingProductProposal.value = null;
    const workbookStore = useWorkbookStore();
    await workbookStore.refreshSheets();
    await workbookStore.selectWorkflowSheet(workflowId);
    _appendSystemMessage("Confirmed proposal → opened as a new workflow sheet. It has not been executed.");
  }

  function rejectProductProposal(): void {
    pendingProductProposal.value = null;
    _appendSystemMessage("Workflow proposal dismissed without changing the project.");
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
    pendingProductProposal,
    subscriptionRequired,
    subscriptionUpgradeUrl,
    resumeRecap,
    maybeLoadResumeRecap,
    dismissResumeRecap,
    syncWorkflow,
    prepareProductWorkflowContext,
    sendMessage,
    stopAnalysis,
    analysisStatus,
    clearMessages,
    startNewConversation,
    refreshConversations,
    updateConversationSummary,
    loadConversation,
    deleteConversation,
    openSubscriptionUpgrade,
    confirmProductProposal,
    rejectProductProposal,
    init,
    dispose,
  };
});
