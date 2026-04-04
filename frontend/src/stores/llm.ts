import { defineStore } from "pinia";
import axios from "axios";
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

const loadConversations = (): ConversationSummary[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    return JSON.parse(raw) as ConversationSummary[];
  } catch (error) {
    console.error('Failed to load conversations from localStorage:', error);
    return [];
  }
};

const persistConversations = (items: ConversationSummary[]) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
};

const emitWsTransport = (kind: string, detail?: string) => {
  window.dispatchEvent(
    new CustomEvent("app-ws-transport", {
      detail: { kind, detail: detail || null },
    })
  );
};

interface LlmConfig {
  provider: string;
  base_url: string;
  model: string;
  verbose: boolean;
}

export const useLlmStore = defineStore("llm", () => {
  const { appMode } = useAppConfig();
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
          messages.value.push({
            role: "assistant",
            content: detail,
          });
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
    if (isServerBacked.value) {
      void refreshConversations();
      return;
    }
    const firstUser = messages.value.find((msg) => msg.role === "user");
    const title =
      firstUser?.content.slice(0, 60) || `Conversation ${conversations.value.length + 1}`;
    const updatedAt = new Date().toISOString();
    const existing = conversations.value.find((item) => item.id === conversationId);
    if (existing) {
      existing.title = title;
      existing.updatedAt = updatedAt;
    } else {
      conversations.value.unshift({ id: conversationId, title, updatedAt });
    }
    persistConversations(conversations.value);
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
    if (
      currentConversationId.value
      && !conversations.value.some((item) => item.id === currentConversationId.value)
    ) {
      currentConversationId.value = null;
      messages.value = [];
    }
  };

  const sendMessage = async (message: string, metadata?: Record<string, unknown>) => {
    if (!message.trim()) {
      return;
    }
    try {
      await connect();
    } catch (error) {
      console.error('Failed to connect WebSocket:', error);
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
    if (isServerBacked.value && projectStore.currentProjectId == null) {
      throw new Error("Select a project before loading a server-backed conversation.");
    }
    const params = isServerBacked.value
      ? { project_id: projectStore.currentProjectId }
      : undefined;
    const response = await api.get(`/llm/conversation/${conversationId}`, { params });
    currentConversationId.value = response.data.conversation_id;
    messages.value = response.data.messages;
  };

  const deleteConversation = async (conversationId: string) => {
    if (isServerBacked.value) {
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
      return;
    }

    try {
      await api.delete(`/llm/conversation/${conversationId}`);
    } catch (error: unknown) {
      if (!axios.isAxiosError(error) || error.response?.status !== 404) {
        throw error;
      }
    }

    conversations.value = conversations.value.filter(
      (item) => item.id !== conversationId
    );
    persistConversations(conversations.value);
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
    try {
      const response = await api.get("/llm/debug/config");
      return response.data as LlmConfig;
    } catch (error) {
      console.error('Failed to fetch LLM config:', error);
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
