<template>
  <section class="chat-panel" :class="{ compact, collapsed }">
    <div class="chat-panel__inner">
      <!-- Panel Top Bar with Open in New Tab -->
      <div class="panel-topbar">
        <h1>LLM assistant</h1>
        <div class="panel-topbar-actions">
          <Button
            icon="pi pi-cog"
            class="p-button-text p-button-sm llm-settings-btn"
            aria-label="LLM Settings"
            @click="toggleLlmMenu"
            v-tooltip.bottom="'LLM Settings'"
          />
          <Menu ref="llmMenu" :model="llmMenuItems" :popup="true" class="llm-menu">
            <template #item="{ item }">
              <div class="llm-menu-item" :class="{ active: item.active }">
                <i class="pi pi-sparkles" style="color: #3b82f6; font-size: 0.85rem"></i>
                <span class="llm-provider-name">{{ item.label }}</span>
                <span class="llm-model-name">{{ item.model }}</span>
              </div>
            </template>
          </Menu>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm open-tab-btn"
            aria-label="Open in new tab"
            @click="openInNewTab"
            v-tooltip.bottom="'Open in new tab'"
          />
        </div>
      </div>

      <section class="card chat-view">
        <div class="chat-sidebar">
          <div class="conversation-list">
            <div
              v-for="conversation in store.conversations"
              :key="conversation.id"
              class="conversation-item"
              :class="{ active: conversation.id === store.currentConversationId }"
            >
              <button class="conversation-button" @click="loadConversation(conversation.id)">
                <strong>{{ conversation.title }}</strong>
                <span>{{ formatDateTime(conversation.updatedAt) }}</span>
              </button>
              <Button
                icon="pi pi-trash"
                class="p-button-text p-button-sm p-button-danger delete-btn"
                @click="deleteConversation(conversation.id)"
                v-tooltip.left="'Delete conversation'"
              />
            </div>
          </div>
        </div>

        <div class="chat-main">
          <Splitter layout="vertical" class="chat-splitter" :gutterSize="6">
            <SplitterPanel class="message-panel" :size="85" :minSize="20" style="display: flex; flex-direction: column; overflow: hidden;">
              <div ref="messageContainer" class="chat-messages">
                <div
                  v-for="(message, idx) in store.messages"
                  :key="idx"
                  class="chat-message"
                  :class="message.role"
                >
                  <div v-if="message.role === 'system'" class="system-notification">
                    {{ message.content }}
                  </div>
                  <div v-else class="chat-bubble">{{ message.content }}</div>
                </div>
                <div v-if="store.loading" class="chat-message assistant">
                  <div class="chat-bubble">Streaming...</div>
                </div>
              </div>
            </SplitterPanel>

            <SplitterPanel class="input-panel" :size="15" :minSize="10" style="display: flex; flex-direction: column; overflow: hidden;">
              <div class="chat-input">
                <InputText
                  v-model="userMessage"
                  placeholder="Ask about spectra, exports, or processing... (Type '/' to clear chat)"
                  class="chat-input__field"
                  @keyup.enter="sendMessage"
                />
                <Button icon="pi pi-send" @click="sendMessage" :disabled="!userMessage.trim()" />
              </div>
            </SplitterPanel>
          </Splitter>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Menu from "primevue/menu";
import Splitter from "primevue/splitter";
import SplitterPanel from "primevue/splitterpanel";
import { useToast } from "primevue/usetoast";

import { useLlmStore } from "@/stores/llm";
import { useExperimentStore } from "@/stores/experiment";
import { formatDateTime } from "@/utils/format";
import api from "@/api/client";

const props = withDefaults(
  defineProps<{
    compact?: boolean;
    collapsed?: boolean;
  }>(),
  {
    compact: false,
    collapsed: false,
  }
);

const emit = defineEmits<{
  (event: "toggle"): void;
}>();

const router = useRouter();
const store = useLlmStore();
const experimentStore = useExperimentStore();
const toast = useToast();

const userMessage = ref("");
const messageContainer = ref<HTMLDivElement | null>(null);

const hadRealtime = ref(false);

// LLM Provider Menu
const llmMenu = ref();
const selectedProvider = ref<string>("deepseek");

const llmProviders = [
  { label: "DeepSeek", value: "deepseek", model: "deepseek-chat" },
  { label: "OpenAI", value: "openai", model: "gpt-5-mini" },
  { label: "Google", value: "gemini", model: "gemini-2.5-flash" },
];

const llmMenuItems = computed(() => {
  return llmProviders.map(provider => ({
    label: provider.label,
    model: provider.model,
    active: store.currentConfig?.provider === provider.value,
    command: () => switchProvider(provider.value)
  }));
});

const toggleLlmMenu = (event: Event) => {
  llmMenu.value.toggle(event);
};

const switchProvider = async (provider: string) => {
  selectedProvider.value = provider;
  await onProviderChange();
};

// Sync with current config
watch(
  () => store.currentConfig,
  (config) => {
    if (config) {
      selectedProvider.value = config.provider;
    }
  },
  { immediate: true }
);

const handleConfigChange = async () => {
  console.log('[ChatPanel] LLM config change event received');
  await store.checkConfigChange();
};

onMounted(async () => {
  store.connect();
  experimentStore.fetchExperiments();

  // Fetch initial config
  await store.checkConfigChange();

  // Listen for config change notifications
  window.addEventListener("llm-config-changed", handleConfigChange);
});

onUnmounted(() => {
  window.removeEventListener("llm-config-changed", handleConfigChange);
});

watch(
  () => store.messages.length,
  async () => {
    await nextTick();
    if (messageContainer.value) {
      messageContainer.value.scrollTop = messageContainer.value.scrollHeight;
    }
  }
);

watch(
  () => store.connectionStatus,
  (status, prev) => {
    if (prev === "connected" && status === "disconnected") {
      toast.add({
        severity: "warn",
        summary: "Realtime disconnected",
        detail: store.lastError || "Trying to reconnect...",
        life: 4000,
      });
    }
    if (status === "connected") {
      if (hadRealtime.value && prev === "disconnected") {
        toast.add({
          severity: "success",
          summary: "Realtime restored",
          detail: "Chat streaming is back online.",
          life: 2500,
        });
      }
      hadRealtime.value = true;
    }
  }
);

const sendMessage = async () => {
  if (!userMessage.value.trim()) {
    return;
  }

  // Handle slash commands
  if (userMessage.value.trim() === "/") {
    store.startNewConversation();
    toast.add({
      severity: "success",
      summary: "Chat Cleared",
      detail: "Started a new conversation",
      life: 2000,
    });
    userMessage.value = "";
    return;
  }

  // Always include experiment metadata if available
  const metadata = experimentStore.experiments.length > 0
    ? { experiments: experimentStore.experiments }
    : undefined;

  await store.sendMessage(userMessage.value, metadata);
  userMessage.value = "";
};

const loadConversation = async (conversationId: string) => {
  try {
    await store.loadConversation(conversationId);
    toast.add({
      severity: "success",
      summary: "Conversation Loaded",
      detail: "Previous conversation restored",
      life: 2000,
    });
  } catch (error: any) {
    console.error('Failed to load conversation:', error);
    const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error';
    toast.add({
      severity: "error",
      summary: "Load Failed",
      detail: errorMessage,
      life: 3000,
    });
  }
};

const deleteConversation = async (conversationId: string) => {
  try {
    await store.deleteConversation(conversationId);
    toast.add({
      severity: "success",
      summary: "Conversation Deleted",
      detail: "Conversation removed",
      life: 2000,
    });
  } catch (error: any) {
    console.error('Failed to delete conversation:', error);
    const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error';
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: errorMessage,
      life: 3000,
    });
  }
};

const openInNewTab = () => {
  // Navigate to dedicated full-screen LLM chat view
  router.push('/llm-chat');
};

const onProviderChange = async () => {
  if (!store.currentConfig) return;

  const newProvider = selectedProvider.value;
  const providerNames: Record<string, string> = {
    deepseek: "DeepSeek",
    openai: "OpenAI",
    gemini: "Google",
  };

  try {
    const providerDefaults: Record<string, { model: string; base_url: string }> = {
      deepseek: {
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
      },
      openai: {
        model: "gpt-5-mini",
        base_url: "https://api.openai.com/v1",
      },
      gemini: {
        model: "gemini-2.5-flash",
        base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
      },
    };

    const defaults = providerDefaults[newProvider];
    if (!defaults) return;

    await api.post("/llm-config", {
      provider: newProvider,
      base_url: defaults.base_url,
      model: defaults.model,
      verbose: store.currentConfig.verbose,
    });

    await store.checkConfigChange();
    await store.reconnect();

    toast.add({
      severity: "success",
      summary: "LLM Provider Changed",
      detail: `Now using ${providerNames[newProvider]} (${defaults.model})`,
      life: 3000,
    });
  } catch (error: any) {
    console.error("Failed to change provider:", error);
    const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error';
    toast.add({
      severity: "error",
      summary: "Provider Change Failed",
      detail: errorMessage,
      life: 3000,
    });
    if (store.currentConfig) {
      selectedProvider.value = store.currentConfig.provider;
    }
  }
};

const compact = computed(() => props.compact);
const collapsed = computed(() => props.collapsed);
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;
}

.chat-panel__inner {
  height: 100%;
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.chat-panel.collapsed {
  pointer-events: none;
  opacity: 0;
}

/* Panel Top Bar */
.panel-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.panel-topbar h1,
.panel-topbar h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.panel-topbar .divider {
  color: #cbd5e1;
  font-weight: 300;
}

.panel-topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.llm-settings-btn {
  color: #64748b;
}

.open-tab-btn {
  color: #64748b;
}

/* LLM Menu Styles */
.llm-menu {
  min-width: 250px;
}

.llm-menu :deep(.p-menu-list) {
  padding: 4px;
}

.llm-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.2s;
}

.llm-menu-item:hover {
  background: #f1f5f9;
}

.llm-menu-item.active {
  background: #e0f2fe;
  border: 1px solid #3b82f6;
}

.llm-provider-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: #1e293b;
  flex: 1;
}

.llm-model-name {
  font-size: 0.75rem;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
}

.chat-view {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 12px;
  height: 100%;
  flex: 1;
  padding: 8px;
  overflow: hidden;
}

.chat-sidebar {
  border-right: 1px solid #e2e8f0;
  padding-right: 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #1b1f23;
}

.conversation-item.active {
  background: #e0f2fe;
  border-color: #3b82f6;
}

.conversation-button {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  background: transparent;
  border: none;
  text-align: left;
  cursor: pointer;
  color: inherit;
  border-radius: 8px;
  transition: background 0.2s;
}

.conversation-button:hover {
  background: rgba(0, 0, 0, 0.05);
}

.conversation-item strong {
  font-weight: 500;
  font-size: 0.85rem;
}

.conversation-item span {
  font-size: 0.7rem;
  color: #64748b;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.conversation-item:hover .delete-btn {
  opacity: 1;
}

.chat-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  height: 100%;
}

.chat-splitter {
  height: 100%;
  border: none;
  background: transparent;
}

:deep(.message-panel),
:deep(.input-panel) {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-splitter :deep(.p-splitter) {
  border: none;
}

.chat-splitter :deep(.p-splitter-gutter) {
  background: #e2e8f0;
  transition: background 0.2s;
}

.chat-splitter :deep(.p-splitter-gutter:hover) {
  background: #cbd5e1;
}

.chat-splitter :deep(.p-splitter-gutter-handle) {
  background: #94a3b8;
}

.chat-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ws-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #fde047;
  background: #fefce8;
  color: #a16207;
  font-size: 0.85rem;
}

.ws-status.disconnected {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.ws-status.connecting {
  border-color: #fde047;
  background: #fefce8;
  color: #a16207;
}

.chat-messages {
  flex: 1;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}

.chat-message {
  display: flex;
}

.chat-message.user {
  justify-content: flex-end;
}

.chat-bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: 12px;
  background: #e2e8f0;
  white-space: pre-wrap;
}

.chat-message.user .chat-bubble {
  background: #2563eb;
  color: white;
}

.chat-input {
  display: flex;
  gap: 12px;
  align-items: center;
  flex: 1;
  min-height: 0;
  padding: 8px;
}

.chat-input__field {
  flex: 1;
}

.chat-panel.compact .chat-view {
  grid-template-columns: 1fr;
  min-height: 0;
}

.chat-panel.compact .chat-sidebar {
  border-right: none;
  padding-right: 0;
  max-height: 180px;
}

/* System Messages */
.chat-message.system {
  justify-content: center;
}

.system-notification {
  width: 100%;
  text-align: center;
  padding: 6px 10px;
  margin: 4px 0;
  font-size: 0.75rem;
  color: #64748b;
  background: rgba(100, 116, 139, 0.1);
  border: 1px solid rgba(100, 116, 139, 0.2);
  border-radius: 6px;
  font-style: italic;
}

@media (max-width: 900px) {
  .chat-view {
    grid-template-columns: 1fr;
  }

  .chat-sidebar {
    border-right: none;
    padding-right: 0;
  }
}
</style>
