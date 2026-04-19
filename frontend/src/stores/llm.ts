import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { dispatchSherpaEvent } from "@/lib/sherpaEvents";
import type { ConversationSummary, LlmMessage } from "@/types";
import { useAppConfig } from "@/composables/useAppConfig";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notification";
import { useProjectStore } from "@/stores/project";
import { buildAuthMessage, buildWsUrl, withCredentials } from "@/utils/ws";

const STORAGE_KEY = "llm_conversations";
const RECORD_STORAGE_KEY = "llm_conversation_records";

interface LocalConversationRecord extends ConversationSummary {
  messages: LlmMessage[];
}

const createConversationId = (): string => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const deriveConversationTitle = (
  messages: LlmMessage[],
  fallbackIndex: number
): string => {
  const firstUser = messages.find((message) => message.role === "user");
  return firstUser?.content.slice(0, 60) || `Conversation ${fallbackIndex}`;
};

const loadLegacyConversationSummaries = (): ConversationSummary[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    return JSON.parse(raw) as ConversationSummary[];
  } catch (error) {
    console.error("Failed to load conversations from localStorage:", error);
    return [];
  }
};

const persistConversationSummaries = (items: ConversationSummary[]) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
};

const loadLocalConversationRecords = (): LocalConversationRecord[] => {
  try {
    const raw = localStorage.getItem(RECORD_STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw) as LocalConversationRecord[];
    }
  } catch (error) {
    console.error("Failed to load local conversation records:", error);
  }

  return loadLegacyConversationSummaries().map((item) => ({
    ...item,
    messages: [],
  }));
};

const persistLocalConversationRecords = (items: LocalConversationRecord[]) => {
  localStorage.setItem(RECORD_STORAGE_KEY, JSON.stringify(items));
  persistConversationSummaries(
    items.map(({ id, title, updatedAt }) => ({ id, title, updatedAt }))
  );
};

const loadConversations = (): ConversationSummary[] => {
  return loadLocalConversationRecords().map(({ id, title, updatedAt }) => ({
    id,
    title,
    updatedAt,
  }));
};

const emitWsTransport = (kind: string, detail?: string) => {
  window.dispatchEvent(
    new CustomEvent("app-ws-transport", {
      detail: { kind, detail: detail || null },
    })
  );
};

const buildApiUrl = (path: string): string => {
  const baseUrl = (api.defaults.baseURL || "/api/v1").replace(/\/$/, "");
  if (baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
    return `${baseUrl}${path}`;
  }
  return `${window.location.origin}${baseUrl}${path}`;
};

const getRequestHeaders = (): HeadersInit => {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  const token = localStorage.getItem("token");
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const apiKey = localStorage.getItem("api_key");
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  return headers;
};

async function* streamSsePayloads(
  response: Response
): AsyncGenerator<Record<string, unknown>> {
  if (!response.body) {
    throw new Error("Chat stream returned no response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const dataLines = rawEvent
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());

      if (dataLines.length > 0) {
        yield JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      }

      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      break;
    }
  }
}

interface LlmConfig {
  provider: string;
  base_url: string;
  model: string;
  verbose: boolean;
}

export const useLlmStore = defineStore("llm", () => {
  const { appMode, isFeatureEnabled } = useAppConfig();
  const authStore = useAuthStore();
  const notifications = useNotificationStore();
  const projectStore = useProjectStore();
  const isServerBacked = computed(() => appMode.value !== "local");
  const messages = ref<LlmMessage[]>([]);
  const conversations = ref<ConversationSummary[]>(
    isServerBacked.value ? [] : loadConversations()
  );
  const currentConversationId = ref<string | null>(null);
  const loading = ref(false);
  const streaming = ref(false);
  const wsRef = ref<WebSocket | null>(null);
  const streamingIndex = ref<number | null>(null);
  const connectionStatus = ref<"disconnected" | "connecting" | "connected">(
    "disconnected"
  );
  const lastError = ref<string | null>(null);
  const reconnectAttempts = ref(0);
  const currentConfig = ref<LlmConfig | null>(null);
  const configStatus = ref<"unknown" | "configured" | "unavailable">("unknown");
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let allowReconnect = true;
  let pendingConnect: Promise<void> | null = null;
  let pendingConnectResolve: (() => void) | null = null;
  let pendingConnectReject: ((error: Error) => void) | null = null;
  let socketOpenTimer: ReturnType<typeof setTimeout> | null = null;
  let authAckTimer: ReturnType<typeof setTimeout> | null = null;
  let configPollTimer: ReturnType<typeof setInterval> | null = null;
  const SOCKET_OPEN_TIMEOUT_MS = 5000;
  const AUTH_ACK_TIMEOUT_MS = 5000;
  const CONNECT_RETRY_ATTEMPTS = 3;
  let connectAttempt = 0;
  let authFallbackRetried = false;
  let lastConversationProjectId: number | null = null;

  const persistLocalConversationState = (conversationId: string) => {
    const records = loadLocalConversationRecords();
    const existing = records.find((item) => item.id === conversationId);
    const nextRecord: LocalConversationRecord = {
      id: conversationId,
      title: existing?.title || deriveConversationTitle(messages.value, records.length + 1),
      updatedAt: new Date().toISOString(),
      messages: messages.value.map((message) => ({ ...message })),
    };

    const nextRecords = [
      nextRecord,
      ...records.filter((item) => item.id !== conversationId),
    ];

    persistLocalConversationRecords(nextRecords);
    conversations.value = nextRecords.map(({ id, title, updatedAt }) => ({
      id,
      title,
      updatedAt,
    }));
  };

  const formatChatWarning = (
    payload: Record<string, unknown>
  ): { message: string; detail?: string } => {
    const code = typeof payload.code === "string" ? payload.code : null;
    const detail =
      typeof payload.detail === "string" && payload.detail.trim()
        ? payload.detail.trim()
        : typeof payload.message === "string" && payload.message.trim()
          ? payload.message.trim()
          : "The server reported a chat warning.";

    if (code === "persistence_failed") {
      return {
        message: "Chat response was delivered but could not be saved to history.",
        detail,
      };
    }
    if (code === "history_load_failed") {
      return {
        message: "Conversation history could not be loaded. Continuing without prior chat context.",
        detail,
      };
    }
    return { message: detail, detail };
  };

  const clearReconnect = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const clearAuthAckTimer = () => {
    if (authAckTimer !== null) {
      clearTimeout(authAckTimer);
      authAckTimer = null;
    }
  };

  const clearSocketOpenTimer = () => {
    if (socketOpenTimer !== null) {
      clearTimeout(socketOpenTimer);
      socketOpenTimer = null;
    }
  };

  const resolvePendingConnect = () => {
    clearSocketOpenTimer();
    clearAuthAckTimer();
    connectAttempt = 0;
    authFallbackRetried = false;
    if (pendingConnectResolve) {
      const resolve = pendingConnectResolve;
      pendingConnect = null;
      pendingConnectResolve = null;
      pendingConnectReject = null;
      resolve();
    }
  };

  const MAX_RECONNECT_ATTEMPTS = 10;

  const scheduleReconnect = () => {
    if (!allowReconnect || reconnectTimer !== null) {
      return;
    }
    reconnectAttempts.value += 1;
    if (reconnectAttempts.value > MAX_RECONNECT_ATTEMPTS) {
      connectionStatus.value = "disconnected";
      lastError.value = "Max reconnection attempts reached";
      return;
    }
    const delay = Math.min(1000 * 2 ** (reconnectAttempts.value - 1), 30000);
    connectionStatus.value = "connecting";
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect().catch(() => undefined);
    }, delay);
  };

  const rejectPendingConnect = (error: Error) => {
    clearSocketOpenTimer();
    clearAuthAckTimer();
    connectAttempt = 0;
    authFallbackRetried = false;
    if (pendingConnectReject) {
      const reject = pendingConnectReject;
      pendingConnect = null;
      pendingConnectResolve = null;
      pendingConnectReject = null;
      reject(error);
    }
  };

  const schedulePendingConnectRetry = (detail: string): boolean => {
    if (!pendingConnect || connectAttempt >= CONNECT_RETRY_ATTEMPTS) {
      return false;
    }
    emitWsTransport(
      "connect_retry",
      `${detail} Retrying live connection (attempt ${connectAttempt + 1} of ${CONNECT_RETRY_ATTEMPTS}).`
    );
    window.setTimeout(() => {
      if (!pendingConnect) {
        return;
      }
      startConnectAttempt();
    }, 250);
    return true;
  };

  const startConnectAttempt = () => {
    clearSocketOpenTimer();
    clearAuthAckTimer();
    connectAttempt += 1;
    connectionStatus.value = "connecting";
    const wsUrl = withCredentials(buildWsUrl());
    wsRef.value = new WebSocket(wsUrl);

    wsRef.value.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "ping") {
          wsRef.value?.send(JSON.stringify({ action: "pong" }));
        } else if (payload.type === "pong") {
          return;
        } else if (payload.type === "authenticated") {
          connectionStatus.value = "connected";
          emitWsTransport("auth_ack", "Server acknowledged WebSocket authentication.");
          resolvePendingConnect();
          return;
        } else if (payload.type === "llm_start") {
          currentConversationId.value = payload.conversation_id;
          streamingIndex.value = messages.value.length;
          messages.value.push({ role: "assistant", content: "" });
          streaming.value = true;
          updateConversationSummary(payload.conversation_id);
        } else if (payload.type === "llm_chunk") {
          if (streamingIndex.value !== null) {
            messages.value[streamingIndex.value].content += payload.chunk;
          }
        } else if (payload.type === "llm_done") {
          streaming.value = false;
          loading.value = false;
          streamingIndex.value = null;
          updateConversationSummary(payload.conversation_id);
        } else if (payload.type === "warning" || payload.type === "llm_warning") {
          const { message, detail } = formatChatWarning(payload as Record<string, unknown>);
          messages.value.push({
            role: "system",
            content: message,
          });
          notifications.add({
            source: "system",
            severity: "warning",
            title: "AI Chat",
            message,
            detail,
          });
        } else if (payload.type === "error" || payload.type === "llm_error") {
          streaming.value = false;
          loading.value = false;
          const detail = payload.detail || "Streaming error.";
          messages.value.push({ role: "assistant", content: detail });
          emitWsTransport("message_error", detail);
        } else if (payload.type?.startsWith("sherpa_")) {
          dispatchSherpaEvent(payload);
        }
      } catch (error) {
        console.warn("Received malformed WebSocket message:", error);
        emitWsTransport("malformed_message", "Received a malformed WebSocket message.");
      }
    });

    wsRef.value.addEventListener("open", () => {
      clearSocketOpenTimer();
      emitWsTransport(
        "socket_open",
        connectAttempt > 1
          ? `Live connection opened on retry ${connectAttempt}.`
          : "Live connection opened."
      );
      reconnectAttempts.value = 0;
      wsRef.value?.send(buildAuthMessage());
      emitWsTransport("auth_sent", "WebSocket authentication sent.");
      clearAuthAckTimer();
      authAckTimer = window.setTimeout(() => {
        lastError.value = "WebSocket authentication timed out.";
        emitWsTransport("auth_timeout", "Server did not acknowledge WebSocket authentication.");
        wsRef.value?.close(4001, "Authentication timeout");
      }, AUTH_ACK_TIMEOUT_MS);
    });

    wsRef.value.addEventListener("error", () => {
      lastError.value = "WebSocket error.";
      emitWsTransport("socket_error", "Connection error while talking to the server.");
    });

    wsRef.value.addEventListener("close", (event) => {
      const awaitingAuth = !!pendingConnect;
      wsRef.value = null;
      connectionStatus.value = "disconnected";

      if (awaitingAuth) {
        if (
          event.code === 1008 &&
          !authFallbackRetried &&
          localStorage.getItem("token") &&
          localStorage.getItem("api_key")
        ) {
          localStorage.removeItem("token");
          authFallbackRetried = true;
          emitWsTransport(
            "auth_retry",
            "Retrying WebSocket authentication with API key fallback."
          );
          startConnectAttempt();
          return;
        }
        if (event.code !== 1008 && schedulePendingConnectRetry("Initial connection failed.")) {
          return;
        }
        if (event.code === 1008) {
          lastError.value = "Unauthorized. Check your credentials.";
          allowReconnect = false;
          emitWsTransport("unauthorized", "Authorization failed for the live connection.");
          rejectPendingConnect(new Error("Unauthorized WebSocket connection."));
          return;
        }
        rejectPendingConnect(
          new Error(
            event.code === 4001
              ? "WebSocket authentication timed out."
              : event.code === 4000
                ? "WebSocket connection timed out."
                : "WebSocket closed."
          )
        );
        return;
      }

      if (streaming.value || loading.value) {
        streaming.value = false;
        loading.value = false;
        streamingIndex.value = null;
        messages.value.push({
          role: "assistant",
          content: "Connection lost. Please try again.",
        });
      }
      if (event.code === 1008) {
        const hadToken = !!localStorage.getItem("token");
        if (hadToken) {
          localStorage.removeItem("token");
        }
        if (hadToken && localStorage.getItem("api_key")) {
          reconnectAttempts.value = 0;
          scheduleReconnect();
          return;
        }
        lastError.value = "Unauthorized. Check your credentials.";
        allowReconnect = false;
        emitWsTransport("unauthorized", "Authorization failed for the live connection.");
        return;
      }
      emitWsTransport("closed", "Connection lost while communicating with the server.");
      scheduleReconnect();
    });

    socketOpenTimer = window.setTimeout(() => {
      lastError.value = "WebSocket connection timed out.";
      emitWsTransport("socket_timeout", "Live connection timed out before the socket opened.");
      wsRef.value?.close(4000, "Connection timeout");
    }, SOCKET_OPEN_TIMEOUT_MS);
  };

  const connect = (): Promise<void> => {
    if (!isServerBacked.value) {
      connectionStatus.value = "disconnected";
      return Promise.resolve();
    }
    if (wsRef.value && wsRef.value.readyState === WebSocket.OPEN) {
      connectionStatus.value = "connected";
      return Promise.resolve();
    }
    if (wsRef.value && wsRef.value.readyState === WebSocket.CONNECTING) {
      return pendingConnect || Promise.resolve();
    }
    clearReconnect();
    allowReconnect = true;
    connectionStatus.value = "connecting";
    lastError.value = null;
    connectAttempt = 0;
    authFallbackRetried = false;
    pendingConnect = new Promise((resolve, reject) => {
      pendingConnectResolve = resolve;
      pendingConnectReject = reject;
    });
    startConnectAttempt();

    return pendingConnect;
  };

  const updateConversationSummary = (conversationId: string) => {
    // Optimistic insertion runs for BOTH modes so the sidebar shows the
    // active thread synchronously, before the async server-backed refresh
    // resolves. refreshConversations() will restore this row if a stale
    // list erases it (probe-then-re-insert path).
    const firstUser = messages.value.find((msg) => msg.role === "user");
    const title =
      firstUser?.content.slice(0, 60) || `Conversation ${conversations.value.length + 1}`;
    const updatedAt = new Date().toISOString();
    const existing = conversations.value.find((item) => item.id === conversationId);
    if (existing) {
      existing.updatedAt = updatedAt;
      // Preserve an existing server-assigned title; only fill in when
      // there isn't one yet.
      if (!existing.title || existing.title === "Untitled conversation") {
        existing.title = title;
      }
    } else {
      conversations.value.unshift({ id: conversationId, title, updatedAt });
    }

    if (isServerBacked.value) {
      // Don't fire refreshConversations here — see sherpa.ts for full
      // rationale. The server list may not contain locally-created
      // conversations and replacing conversations.value destroys all
      // prior optimistic sidebar entries.
      return;
    }
    persistConversationSummaries(conversations.value);
  };

  const refreshConversations = async (projectId = projectStore.currentProjectId) => {
    if (!isServerBacked.value) {
      conversations.value = loadConversations();
      return;
    }
    if (!projectId || !authStore.user?.id) {
      conversations.value = [];
      currentConversationId.value = null;
      messages.value = [];
      lastConversationProjectId = null;
      return;
    }

    // Failure modes handled — see sherpa.ts refreshConversations for
    // the full design notes. This parallel implementation preserves the
    // same contract: probe must run regardless of list outcome so project
    // switches with list failures clear state correctly (via probe 404),
    // and the active row is re-inserted optimistically if the list was
    // healthy but stale.
    let listResponse;
    let listFailed = false;
    const switchingProjects = lastConversationProjectId !== null && lastConversationProjectId !== projectId;
    try {
      listResponse = await api.get("/llm/conversations", {
        params: { project_id: projectId },
      });
    } catch (err) {
      console.warn(
        "[llm] refreshConversations list fetch failed — will probe active id before deciding:",
        err,
      );
      listFailed = true;
    }

    if (listResponse) {
      conversations.value = (listResponse.data as Array<Record<string, unknown>>).map(
        (item) => ({
          id: String(item.id),
          title: String(item.title || "Untitled conversation"),
          updatedAt: String(item.updated_at || item.updatedAt || new Date().toISOString()),
        }),
      );
      lastConversationProjectId = projectId;
    }

    const activeId = currentConversationId.value;
    if (!activeId) {
      if (switchingProjects) {
        currentConversationId.value = null;
        messages.value = [];
        if (listFailed) {
          conversations.value = [];
        }
        lastConversationProjectId = projectId;
      }
      return;
    }

    if (!listFailed && conversations.value.some((item) => item.id === activeId)) {
      return;
    }

    try {
      await api.get(`/llm/conversation/${activeId}`, {
        params: { project_id: projectId },
      });
      if (!listFailed) {
        ensureOptimisticSidebarEntry(activeId);
      }
      lastConversationProjectId = projectId;
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404 && switchingProjects) {
        // Project switch: stale id belongs to a different project.
        // Clear so the next send doesn't pair an old id with a new project_id.
        currentConversationId.value = null;
        messages.value = [];
        if (listFailed) {
          conversations.value = [];
        }
        lastConversationProjectId = projectId;
      } else if (status === 404) {
        // Same-project 404: preserve state + restore sidebar entry.
        console.warn(
          "[llm] getConversation probe 404 on same project — preserving state + sidebar entry:",
          { activeId, projectId },
        );
        ensureOptimisticSidebarEntry(activeId);
        lastConversationProjectId = projectId;
      } else {
        console.warn(
          "[llm] getConversation probe failed — keeping active thread intact:",
          err,
        );
      }
    }
  };

  const ensureOptimisticSidebarEntry = (conversationId: string): void => {
    if (conversations.value.some((item) => item.id === conversationId)) {
      return;
    }
    const firstUser = messages.value.find((message) => message.role === "user");
    const derivedTitle =
      firstUser?.content.slice(0, 60) || `Conversation ${conversations.value.length + 1}`;
    conversations.value.unshift({
      id: conversationId,
      title: derivedTitle,
      updatedAt: new Date().toISOString(),
    });
  };

  const sendMessage = async (message: string, metadata?: Record<string, unknown>) => {
    if (!message.trim()) {
      return;
    }

    if (!isServerBacked.value) {
      const conversationId = currentConversationId.value || createConversationId();
      currentConversationId.value = conversationId;
      loading.value = true;
      streaming.value = true;
      messages.value.push({ role: "user", content: message });
      messages.value.push({ role: "assistant", content: "" });
      persistLocalConversationState(conversationId);

      try {
        const response = await fetch(buildApiUrl("/chat/stream"), {
          method: "POST",
          headers: getRequestHeaders(),
          body: JSON.stringify({ message, metadata: metadata || null }),
        });

        if (!response.ok) {
          let detail = `Chat request failed (HTTP ${response.status}).`;
          try {
            const body = await response.json();
            if (typeof body?.detail === "string") {
              detail = body.detail;
            } else if (
              body?.detail &&
              typeof body.detail === "object" &&
              typeof body.detail.message === "string"
            ) {
              detail = body.detail.message;
            }
          } catch {
            // Fall back to the generic HTTP status message.
          }
          throw new Error(detail);
        }

        for await (const payload of streamSsePayloads(response)) {
          if (payload.type === "chunk") {
            const text = typeof payload.text === "string" ? payload.text : "";
            const lastMessage = messages.value[messages.value.length - 1];
            if (lastMessage?.role === "assistant") {
              lastMessage.content += text;
            }
          } else if (payload.type === "error") {
            throw new Error(
              typeof payload.detail === "string"
                ? payload.detail
                : "Chat request failed."
            );
          } else if (payload.type === "done") {
            break;
          }
        }
      } catch (error) {
        const detail =
          error instanceof Error
            ? error.message
            : "Unable to reach the configured chat endpoint.";
        const lastMessage = messages.value[messages.value.length - 1];
        if (lastMessage?.role === "assistant") {
          lastMessage.content = detail;
        } else {
          messages.value.push({ role: "assistant", content: detail });
        }
      } finally {
        loading.value = false;
        streaming.value = false;
        persistLocalConversationState(conversationId);
      }
      return;
    }

    try {
      await connect();
    } catch (error) {
      console.error("Failed to connect WebSocket:", error);
      messages.value.push({
        role: "assistant",
        content: "Unable to connect for streaming. Check the API key and try again.",
      });
      return;
    }

    loading.value = true;
    messages.value.push({ role: "user", content: message });
    wsRef.value?.send(
      JSON.stringify({
        action: "llm_chat",
        message: message,
        conversation_id: currentConversationId.value,
        metadata: metadata || null,
      })
    );
  };

  const loadConversation = async (conversationId: string) => {
    if (conversationId === currentConversationId.value && messages.value.length > 0) {
      return;
    }
    if (!isServerBacked.value) {
      const conversation = loadLocalConversationRecords().find(
        (item) => item.id === conversationId
      );
      if (!conversation) {
        conversations.value = conversations.value.filter(
          (item) => item.id !== conversationId
        );
        throw new Error(
          "This conversation is no longer available. It has been removed from Topics."
        );
      }
      currentConversationId.value = conversation.id;
      messages.value = conversation.messages.map((message) => ({ ...message }));
      return;
    }
    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before loading a server-backed conversation.");
    }
    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;
    try {
      const response = await api.get(`/llm/conversation/${conversationId}`, { params });
      currentConversationId.value = response.data.conversation_id;
      messages.value = response.data.messages;
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) {
        conversations.value = conversations.value.filter(
          (item) => item.id !== conversationId,
        );
        if (currentConversationId.value === conversationId) {
          currentConversationId.value = null;
          messages.value = [];
        }
        throw new Error("This conversation is no longer available. It has been removed from Topics.");
      }
      throw err;
    }
  };

  const deleteConversation = async (conversationId: string) => {
    if (!isServerBacked.value) {
      const nextRecords = loadLocalConversationRecords().filter(
        (item) => item.id !== conversationId
      );
      persistLocalConversationRecords(nextRecords);
      conversations.value = nextRecords.map(({ id, title, updatedAt }) => ({
        id,
        title,
        updatedAt,
      }));
      if (currentConversationId.value === conversationId) {
        currentConversationId.value = null;
        messages.value = [];
      }
      return;
    }

    if (projectStore.currentProjectId == null) {
      throw new Error("Select a project before deleting a server-backed conversation.");
    }
    await api.delete(`/llm/conversation/${conversationId}`, {
      params: { project_id: projectStore.currentProjectId },
    });
    conversations.value = conversations.value.filter(
      (item) => item.id !== conversationId
    );
    if (currentConversationId.value === conversationId) {
      currentConversationId.value = null;
      messages.value = [];
    }
  };

  const startNewConversation = () => {
    currentConversationId.value = null;
    messages.value = [];
  };

  const disconnect = () => {
    clearReconnect();
    clearSocketOpenTimer();
    clearAuthAckTimer();
    allowReconnect = false;
    rejectPendingConnect(new Error("WebSocket disconnected."));
    if (wsRef.value) {
      wsRef.value.close(1000, "Manual disconnect");
      wsRef.value = null;
    }
    connectionStatus.value = "disconnected";
  };

  const reconnect = async () => {
    disconnect();
    allowReconnect = true;
    reconnectAttempts.value = 0;
    await connect();
  };

  const fetchConfig = async (): Promise<LlmConfig | null> => {
    if (!isServerBacked.value) {
      return isFeatureEnabled("chatAssistant")
        ? {
            provider: "byo-endpoint",
            base_url: "",
            model: "configured-via-env",
            verbose: false,
          }
        : null;
    }
    try {
      const response = await api.get("/llm/debug/config");
      return response.data as LlmConfig;
    } catch (error) {
      console.error("Failed to fetch LLM config:", error);
      return null;
    }
  };

  const checkConfigChange = async () => {
    const newConfig = await fetchConfig();
    if (!newConfig) {
      console.warn('[LLM] Failed to fetch config');
      configStatus.value = "unavailable";
      return;
    }
    configStatus.value = "configured";

    const oldConfig = currentConfig.value;
    const isInitialLoad = !oldConfig;

    if (oldConfig) {
      // Check if config changed
      const providerChanged = oldConfig.provider !== newConfig.provider;
      const modelChanged = oldConfig.model !== newConfig.model;
      const verboseChanged = oldConfig.verbose !== newConfig.verbose;

      if (providerChanged || modelChanged) {
        // Add system message for provider/model change
        const providerNames: Record<string, string> = {
          deepseek: "DeepSeek",
          openai: "OpenAI",
          gemini: "Google",
        };
        const providerLabel = providerNames[newConfig.provider] || newConfig.provider;
        const oldProviderLabel = providerNames[oldConfig.provider] || oldConfig.provider;

        console.log(`[LLM] Config changed: ${oldProviderLabel} → ${providerLabel}`);

        messages.value.push({
          role: "system",
          content: `──── LLM engine switched to ${providerLabel} (${newConfig.model}) ────`,
        });
      }

      if (verboseChanged) {
        // Add system message for verbose change
        console.log(`[LLM] Verbose mode ${newConfig.verbose ? 'enabled' : 'disabled'}`);

        messages.value.push({
          role: "system",
          content: `──── Verbose mode ${newConfig.verbose ? 'enabled' : 'disabled'} ────`,
        });
      }
    }

    if (isInitialLoad) {
      console.log(`[LLM] Initial config loaded: ${newConfig.provider} (${newConfig.model})`);
    }

    currentConfig.value = newConfig;
  };

  const startConfigPolling = (intervalMs = 60_000) => {
    if (appMode.value !== "local") return;
    checkConfigChange();
    if (configPollTimer !== null) return;
    configPollTimer = setInterval(() => {
      if (document.visibilityState === "visible") {
        checkConfigChange();
      }
    }, intervalMs);
  };

  const stopConfigPolling = () => {
    if (configPollTimer !== null) {
      clearInterval(configPollTimer);
      configPollTimer = null;
    }
  };

  return {
    messages,
    conversations,
    currentConversationId,
    loading,
    streaming,
    currentConfig,
    configStatus,
    wsRef,
    connect,
    disconnect,
    reconnect,
    sendMessage,
    refreshConversations,
    loadConversation,
    deleteConversation,
    startNewConversation,
    fetchConfig,
    checkConfigChange,
    startConfigPolling,
    stopConfigPolling,
    connectionStatus,
    lastError,
  };
});
