<template>
  <section class="chat-panel" :class="{ compact, collapsed }">
    <div class="chat-panel__inner">
      <!-- Panel Top Bar with Tab Toggle -->
      <div class="panel-topbar">
        <div v-if="showTabToggle" class="tab-toggle">
          <button
            v-if="showLlmTab"
            class="tab-btn"
            :class="{ active: activeTab === 'llm' }"
            @click="activeTab = 'llm'"
          >
            LLM Chat
          </button>
          <button
            v-if="sherpaEnabled"
            class="tab-btn"
            :class="{ active: activeTab === 'sherpa' }"
            @click="switchToSherpa"
          >
            Sherpa Advisor
          </button>
        </div>
        <div v-else class="tab-toggle tab-toggle--static">
          <span class="tab-label">{{ activeTabLabel }}</span>
        </div>
        <div class="panel-topbar-actions">
          <!-- LLM settings (only on LLM tab, local mode only — server owns model selection) -->
          <Button
            v-if="activeTab === 'llm' && appMode === 'local'"
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
          <!-- Sherpa refresh (only on Sherpa tab) -->
          <Button
            v-if="activeTab === 'sherpa'"
            icon="pi pi-refresh"
            class="p-button-text p-button-sm llm-settings-btn"
            :loading="sherpaStore.state === 'syncing'"
            aria-label="Re-sync workflow"
            @click="sherpaStore.syncWorkflow()"
            v-tooltip.bottom="'Re-sync workflow'"
          />
          <!-- Agentic tools toggle (Sherpa tab, subscription-gated) -->
          <Button
            v-if="activeTab === 'sherpa' && isFeatureEnabled('sherpaAgenticTools')"
            :icon="toolsActive ? 'pi pi-wrench' : 'pi pi-wrench'"
            class="p-button-text p-button-sm"
            :class="{ 'tools-active-btn': toolsActive }"
            aria-label="Toggle agentic tools"
            @click="toolsActive = !toolsActive"
            v-tooltip.bottom="toolsActive ? 'Agentic tools enabled' : 'Enable agentic tools'"
          />
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm open-tab-btn"
            aria-label="Open in new tab"
            @click="openInNewTab"
            v-tooltip.bottom="'Open in new tab'"
          />
        </div>
      </div>

      <section class="card chat-view" :class="{ 'no-sidebar': activeTab !== 'llm' }">
        <!-- Conversation sidebar (LLM tab only) -->
        <div v-if="activeTab === 'llm'" class="chat-sidebar">
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
          <div class="chat-layout">
            <div ref="messageContainer" class="chat-messages">
              <!-- LLM messages -->
              <template v-if="activeTab === 'llm'">
                <!-- No LLM configured -->
                <div v-if="!llmChatAllowed" class="no-key-notice">
                  <i class="pi pi-info-circle"></i>
                  <span>AI chat is disabled in Settings &gt; Data &amp; Privacy.</span>
                  <a class="setup-link" @click="router.push('/settings')">Enable</a>
                </div>
                <div v-else-if="!llmChatEnabled && appMode === 'local'" class="no-key-notice">
                  <i class="pi pi-info-circle"></i>
                  <span>Configure an LLM API key in Settings to enable chat.</span>
                  <a class="setup-link" @click="router.push('/settings')">Setup</a>
                </div>
                <div v-else-if="!llmChatEnabled" class="no-key-notice">
                  <i class="pi pi-info-circle"></i>
                  <span>{{ hasSherpaSubscription ? "Chat is unavailable for this deployment." : "Chat requires a Sherpa subscription." }}</span>
                </div>
                <template v-else>
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
                </template>
              </template>

              <!-- Sherpa messages -->
              <template v-else>
                <div
                  v-for="(message, idx) in sherpaStore.messages"
                  :key="idx"
                  class="chat-message"
                  :class="message.role"
                >
                  <div v-if="message.role === 'system'" class="system-notification">
                    {{ message.content }}
                  </div>
                  <div v-else class="chat-bubble">{{ message.content }}</div>
                </div>
                <div
                  v-for="(tool, tidx) in sherpaStore.activeTools"
                  :key="'tool-' + tidx"
                  class="tool-progress"
                >
                  <i
                    :class="tool.status === 'started' ? 'pi pi-spin pi-spinner' : 'pi pi-check-circle'"
                    :style="{ color: tool.status === 'started' ? '#3b82f6' : '#22c55e' }"
                  ></i>
                  <span v-if="tool.status === 'started'">Using {{ tool.tool_name }}...</span>
                  <span v-else>{{ tool.tool_name }} complete</span>
                </div>
                <div v-if="sherpaStore.state === 'syncing'" class="chat-message assistant">
                  <div class="chat-bubble">Analyzing workflow...</div>
                </div>
                <div v-if="sherpaStore.state === 'chatting'" class="chat-message assistant">
                  <div class="chat-bubble">Thinking...</div>
                </div>
              </template>
            </div>

            <div class="chat-input-shell">
              <div class="chat-input">
                <InputText
                  v-model="userMessage"
                  :placeholder="inputPlaceholder"
                  class="chat-input__field"
                  :disabled="inputDisabled"
                  @keyup.enter="sendMessage"
                />
                <Button
                  icon="pi pi-send"
                  @click="sendMessage"
                  :disabled="!userMessage.trim() || inputDisabled"
                />
              </div>
            </div>
          </div>
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
import { useToast } from "primevue/usetoast";

import { useLlmStore } from "@/stores/llm";
import { useSherpaStore } from "@/stores/sherpa";
import { useExperimentStore } from "@/stores/experiment";
import { useWorkflowStore } from "@/stores/workflow";
import { useProjectStore } from "@/stores/project";
import { useAuthStore } from "@/stores/auth";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { formatDateTime } from "@/utils/format";
import { getErrorMessage } from "@/utils/errors";
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

const router = useRouter();
const store = useLlmStore();
const sherpaStore = useSherpaStore();
const experimentStore = useExperimentStore();
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const authStore = useAuthStore();
const toast = useToast();
const { appMode, appConfig, isFeatureEnabled } = useAppConfig();
const { isDemoMode } = useDemoMode();

const userMessage = ref("");
const messageContainer = ref<HTMLDivElement | null>(null);
const hadRealtime = ref(false);
const toolsActive = ref(false);
const llmChatAllowed = ref(true);

const scrollToBottom = async () => {
  await nextTick();
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight;
  }
};

// ── Tab toggle ───────────────────────────────────────────────

const activeTab = ref<"llm" | "sherpa">("llm");
const sherpaEnabled = computed(() => isFeatureEnabled("sherpaAdvisor"));
const llmChatEnabled = computed(() => isFeatureEnabled("chatAssistant"));
const showLlmTab = computed(() => !(isDemoMode.value && sherpaEnabled.value));
const showTabToggle = computed(() => showLlmTab.value && sherpaEnabled.value);
const activeTabLabel = computed(() => (activeTab.value === "sherpa" ? "Sherpa Advisor" : "LLM Chat"));
const hasSherpaSubscription = computed(
  () => (appConfig.value?.subscription?.plan || "none") !== "none"
);

const switchToSherpa = () => {
  activeTab.value = "sherpa";
  // In demo mode, show a one-time welcome message
  if (isDemoMode.value && sherpaStore.messages.length === 0) {
    sherpaStore.messages.push({
      role: "system",
      content:
        "Welcome to Sherpa Advisor! Try loading a Demo Pick template, " +
        "then click the refresh button to get AI-powered analysis recommendations.",
    });
  }
  // Auto-sync on switch (proactive assessment)
  sherpaStore.syncWorkflow();
};

const inputPlaceholder = computed(() => {
  if (activeTab.value === "sherpa") return "Ask Sherpa about your workflow...";
  return "Ask about spectra, exports, or processing... (Type '/' to clear chat)";
});

const inputDisabled = computed(() => {
  if (activeTab.value === "llm") return !llmChatEnabled.value || !llmChatAllowed.value;
  return false;
});

// ── LLM Provider Menu ────────────────────────────────────────

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
  () => [showLlmTab.value, sherpaEnabled.value] as const,
  ([llmVisible, sherpaVisible]) => {
    if (!llmVisible && sherpaVisible && activeTab.value !== "sherpa") {
      switchToSherpa();
    }
  },
  { immediate: true }
);

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
  if (appMode.value !== "local") return;
  await store.checkConfigChange();
};

const loadEgressDefaults = async () => {
  try {
    const { data } = await api.get("/egress/defaults");
    llmChatAllowed.value = data?.allow_llm_chat ?? false;
  } catch {
    llmChatAllowed.value = false;
  }
};

// ── Lifecycle ────────────────────────────────────────────────

onMounted(async () => {
  // Skip WS connect and data fetches when not authenticated in enterprise mode.
  // Use authStore.user (not isAuthenticated) to avoid acting on a stale token
  // before /auth/me validates it.
  if (authStore.user || appMode.value === "local") {
    store.connect();
    experimentStore.fetchExperiments();
    sherpaStore.init();
    await loadEgressDefaults();
    if (appMode.value === "local") {
      // Fetch initial config only when authenticated (requires /llm/debug/config)
      await store.checkConfigChange();
    } else {
      await store.refreshConversations(projectStore.currentProjectId);
    }
  }

  // Listen for config change notifications
  window.addEventListener("llm-config-changed", handleConfigChange);
  window.addEventListener("egress-defaults-changed", loadEgressDefaults);
});

onUnmounted(() => {
  window.removeEventListener("llm-config-changed", handleConfigChange);
  window.removeEventListener("egress-defaults-changed", loadEgressDefaults);
  sherpaStore.dispose();
});

// ── Auto-scroll ──────────────────────────────────────────────

watch(
  () => store.messages.length,
  async () => {
    if (activeTab.value === "llm") {
      await scrollToBottom();
    }
  }
);

watch(
  () => store.messages.map((message) => message.content).join("\n"),
  async () => {
    if (activeTab.value === "llm" && (store.streaming || store.loading)) {
      await scrollToBottom();
    }
  }
);

watch(
  () => sherpaStore.messages.length,
  async () => {
    if (activeTab.value === "sherpa") {
      await scrollToBottom();
    }
  }
);

// ── Auto-scroll for active tab messages ───────────────────────

watch(
  () => [activeTab.value, store.loading, store.streaming, sherpaStore.state],
  async () => {
    await scrollToBottom();
  }
);

watch(
  () => projectStore.currentProjectId,
  async (projectId) => {
    if (appMode.value !== "local") {
      await store.refreshConversations(projectId);
    }
  }
);

// ── Connection status toasts ─────────────────────────────────

watch(
  () => store.connectionStatus,
  (status, prev) => {
    if (prev === "connected" && status === "disconnected" && hadRealtime.value) {
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

// ── Build typed workflow context for server-side LLM ──────────

function buildWorkflowChatContext(): Record<string, unknown> | null {
  const { nodes, edges, workflowName, workflowDescription, currentTemplateId,
    lastExecutionResults, lastExecutionDiagnostics, getNodeMetadata, workflowId } = workflowStore;

  if (nodes.length === 0) return null;

  // Build V2 node list with library metadata
  const contextNodes = nodes.map((n) => {
    const meta = getNodeMetadata(n.type);
    const execState = n.executionState;

    // Filter param_descriptions to params actually set on this node
    const setParamNames = new Set(Object.keys(n.params || {}));
    const paramDescriptions = meta?.parameters
      ?.filter((p) => setParamNames.has(p.name))
      .map((p) => ({ name: p.name, label: p.label, description: p.description || null }))
      ?? null;

    // Result summary for this node (strip raw arrays, keep scalars + shapes)
    const resultShape = execState?.output_shape ?? null;
    const resultStatistics: Record<string, number> | null = null;

    return {
      node_id: n.id,
      node_type: n.type,
      label: meta?.label ?? n.type,
      parameters: n.params || {},
      result_shape: resultShape,
      result_statistics: resultStatistics,
      // V2 fields
      description: meta?.description ?? null,
      param_descriptions: paramDescriptions,
      output_type: execState?.output_type ?? meta?.output_type ?? null,
      execution_status: execState?.status ?? null,
    };
  });

  const contextEdges = edges.map((e) => ({
    from_node_id: e.from,
    to_node_id: e.to,
    from_output: e.fromPort || "default",
    to_input: e.toPort || "default",
  }));

  // Derive n_samples/n_features from DATA-type node results
  let nSamples: number | null = null;
  let nFeatures: number | null = null;
  if (lastExecutionResults) {
    for (const node of nodes) {
      if (node.type.startsWith("data.")) {
        const res = lastExecutionResults[node.id] as Record<string, unknown> | undefined;
        if (res?.n_samples != null) nSamples = res.n_samples as number;
        if (res?.n_features != null) nFeatures = res.n_features as number;
        if (nSamples != null) break;
      }
    }
  }

  // Build results_summary: per-node, keeping scalars and shapes but not raw arrays
  let resultsSummary: Record<string, Record<string, unknown>> | null = null;
  if (lastExecutionResults) {
    resultsSummary = {};
    for (const [nodeId, rawResult] of Object.entries(lastExecutionResults)) {
      if (!rawResult || typeof rawResult !== "object") continue;
      const result = rawResult as Record<string, unknown>;
      const metadata = result.metadata;
      const summary: Record<string, unknown> = {
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
      resultsSummary[nodeId] = summary;
    }
  }

  return {
    workflow_id: workflowId ?? null,
    workflow_name: workflowName,
    workflow_description: workflowDescription || null,
    template_id: currentTemplateId ?? null,
    nodes: contextNodes,
    edges: contextEdges,
    n_samples: nSamples,
    n_features: nFeatures,
    diagnostics: Object.keys(lastExecutionDiagnostics).length > 0
      ? lastExecutionDiagnostics
      : null,
    results_summary: resultsSummary,
  };
}

// ── Send message (dispatches to active tab's store) ──────────

const sendMessage = async () => {
  if (!userMessage.value.trim()) {
    return;
  }

  // Sherpa tab: send via sherpa store
  if (activeTab.value === "sherpa") {
    // Handle "/" clear in Sherpa tab too
    if (userMessage.value.trim() === "/") {
      sherpaStore.clearMessages();
      toast.add({
        severity: "success",
        summary: "Sherpa Chat Cleared",
        detail: "Cleared Sherpa conversation",
        life: 2000,
      });
      userMessage.value = "";
      return;
    }
    await sherpaStore.sendMessage(userMessage.value, toolsActive.value);
    userMessage.value = "";
    return;
  }

  // LLM tab: existing logic
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

  const metadata: Record<string, unknown> = {};
  if (experimentStore.experiments.length > 0) {
    metadata.experiments = experimentStore.experiments;
  }
  if (projectStore.currentProjectId != null) {
    metadata.project_id = projectStore.currentProjectId;
  }
  const wfCtx = buildWorkflowChatContext();
  if (wfCtx) {
    metadata.workflow_context = wfCtx;
  }

  await store.sendMessage(
    userMessage.value,
    Object.keys(metadata).length > 0 ? metadata : undefined,
  );
  userMessage.value = "";
};

// ── Conversation management (LLM tab) ───────────────────────

const loadConversation = async (conversationId: string) => {
  try {
    await store.loadConversation(conversationId);
    toast.add({
      severity: "success",
      summary: "Conversation Loaded",
      detail: "Previous conversation restored",
      life: 2000,
    });
  } catch (error: unknown) {
    console.error('Failed to load conversation:', error);
    toast.add({
      severity: "error",
      summary: "Load Failed",
      detail: getErrorMessage(error, "Unknown error"),
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
  } catch (error: unknown) {
    console.error('Failed to delete conversation:', error);
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: getErrorMessage(error, "Unknown error"),
      life: 3000,
    });
  }
};

const openInNewTab = () => {
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
  } catch (error: unknown) {
    console.error("Failed to change provider:", error);
    toast.add({
      severity: "error",
      summary: "Provider Change Failed",
      detail: getErrorMessage(error, "Unknown error"),
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

/* Tab Toggle */
.tab-toggle {
  display: flex;
  gap: 2px;
  background: #e2e8f0;
  border-radius: 8px;
  padding: 2px;
}

.tab-btn {
  padding: 5px 12px;
  font-size: 0.82rem;
  font-weight: 500;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.tab-btn:hover {
  color: #334155;
  background: rgba(255, 255, 255, 0.5);
}

.tab-btn.active {
  background: #ffffff;
  color: #1e293b;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
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

.chat-view.no-sidebar {
  grid-template-columns: 1fr;
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
  min-height: 0;
}

.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: transparent;
  overflow: hidden;
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

.chat-input-shell {
  flex-shrink: 0;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
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
  flex-shrink: 0;
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

/* Tools toggle active state */
.tools-active-btn {
  color: #3b82f6 !important;
  background: rgba(59, 130, 246, 0.1) !important;
  border-radius: 6px;
}

/* Agentic tool progress */
.tool-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 0.8rem;
  color: #475569;
}

/* No BYOK key notice */
.no-key-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  margin: 8px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.85rem;
  color: #64748b;
}

.no-key-notice i {
  color: #3b82f6;
  font-size: 1rem;
}

.setup-link {
  color: #3b82f6;
  cursor: pointer;
  font-weight: 500;
  text-decoration: underline;
  margin-left: auto;
}

.setup-link:hover {
  color: #2563eb;
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
