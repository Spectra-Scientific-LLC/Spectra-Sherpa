import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import type { ConversationSummary, LlmMessage } from "@/types";
import { buildWsUrl, withCredentials } from "@/utils/ws";

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

interface LlmConfig {
  provider: string;
  base_url: string;
  model: string;
  verbose: boolean;
}

export const useLlmStore = defineStore("llm", () => {
  const messages = ref<LlmMessage[]>([]);
  const conversations = ref<ConversationSummary[]>(loadConversations());
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
  let configPollTimer: ReturnType<typeof setInterval> | null = null;

  const clearReconnect = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (!allowReconnect || reconnectTimer !== null) {
      return;
    }
    reconnectAttempts.value += 1;
    const delay = Math.min(1000 * 2 ** (reconnectAttempts.value - 1), 30000);
    connectionStatus.value = "connecting";
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect().catch(() => undefined);
    }, delay);
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
    const wsUrl = withCredentials(buildWsUrl());
    wsRef.value = new WebSocket(wsUrl);

    wsRef.value.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "llm_start") {
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
        } else if (payload.type === "error") {
          streaming.value = false;
          loading.value = false;
          messages.value.push({
            role: "assistant",
            content: payload.detail || "Streaming error.",
          });
        } else if (payload.type?.startsWith("sherpa_")) {
          // Forward Sherpa messages to the sherpa store via event bus
          window.dispatchEvent(
            new CustomEvent("sherpa-ws-message", { detail: payload })
          );
        }
      } catch (error) {
        // Ignore malformed messages but log them
        console.warn('Received malformed WebSocket message:', error);
      }
    });

    wsRef.value.addEventListener("open", () => {
      connectionStatus.value = "connected";
      reconnectAttempts.value = 0;
    });

    wsRef.value.addEventListener("error", () => {
      lastError.value = "WebSocket error.";
    });

    wsRef.value.addEventListener("close", (event) => {
      wsRef.value = null;
      connectionStatus.value = "disconnected";
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
        // Stale token may have caused the rejection.  Clear it and retry
        // once if an api_key is still available as fallback credential.
        const hadToken = !!localStorage.getItem("token");
        if (hadToken) {
          localStorage.removeItem("token");
        }
        if (hadToken && localStorage.getItem("api_key")) {
          // One retry with api_key only
          reconnectAttempts.value = 0;
          scheduleReconnect();
          return;
        }
        lastError.value = "Unauthorized. Check your credentials.";
        allowReconnect = false;
        return;
      }
      scheduleReconnect();
    });

    pendingConnect = new Promise((resolve, reject) => {
      const handleOpen = () => {
        pendingConnect = null;
        resolve();
      };
      const handleClose = (event: CloseEvent) => {
        pendingConnect = null;
        reject(
          new Error(
            event.code === 1008 ? "Unauthorized WebSocket connection." : "WebSocket closed."
          )
        );
      };
      wsRef.value?.addEventListener("open", handleOpen, { once: true });
      wsRef.value?.addEventListener("close", handleClose, { once: true });
    });

    return pendingConnect;
  };

  const updateConversationSummary = (conversationId: string) => {
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
    const response = await api.get(`/llm/conversation/${conversationId}`);
    currentConversationId.value = response.data.conversation_id;
    messages.value = response.data.messages;
  };

  const deleteConversation = async (conversationId: string) => {
    try {
      await api.delete(`/llm/conversation/${conversationId}`);
    } catch (error: any) {
      // If conversation not found in backend (404), that's okay - we still want to remove it from frontend
      if (error?.response?.status !== 404) {
        throw error; // Re-throw if it's not a 404
      }
      // If it's a 404, continue to remove from frontend localStorage
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
    allowReconnect = false;
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
