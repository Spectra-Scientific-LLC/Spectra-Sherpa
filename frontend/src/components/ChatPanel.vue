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
            @click="setActiveTab('llm')"
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
          <div v-if="activeTab === 'sherpa'" class="sherpa-conversation-picker">
            <Button
              icon="pi pi-list"
              label="Topics"
              class="p-button-text p-button-sm sherpa-topics-btn"
              aria-label="Sherpa topics"
              @click="toggleSherpaConversationMenu"
              v-tooltip.bottom="'Sherpa topics'"
            />
            <Menu ref="sherpaConversationMenu" :model="sherpaConversationMenuItems" :popup="true" class="sherpa-menu">
              <template #item="{ item }">
                <div
                  class="sherpa-menu-item"
                  :class="{
                    active: item.active,
                    'sherpa-menu-item--disabled': item.disabled,
                    'sherpa-menu-item--action': item.isAction,
                  }"
                >
                  <i v-if="item.icon" :class="item.icon"></i>
                  <div class="sherpa-menu-copy">
                    <span class="sherpa-menu-title">{{ item.label }}</span>
                    <span v-if="item.updatedAt" class="sherpa-menu-meta">{{ item.updatedAt }}</span>
                  </div>
                </div>
              </template>
            </Menu>
            <Button
              icon="pi pi-plus"
              class="p-button-text p-button-sm llm-settings-btn"
              aria-label="Start new Sherpa conversation"
              @click="startNewSherpaConversation"
              v-tooltip.bottom="'New Sherpa conversation'"
            />
          </div>
          <!-- LLM settings (only on LLM tab, local mode only — server owns model selection).
               Further gated by sherpaAdvisor capability: provider switching writes
               to /llm-config which is server-only. Hidden on OSS-only installs. -->
          <Button
            v-if="activeTab === 'llm' && appMode === 'local' && isFeatureEnabled('sherpaAdvisor')"
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
            :loading="sherpaStore.isSyncing"
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
                  <span>Set <code>CHAT_ENDPOINT_URL</code> and <code>CHAT_ENDPOINT_KEY</code> in your environment, then restart to enable chat.</span>
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
                    <div
                      v-else-if="message.role === 'assistant'"
                      class="chat-bubble chat-bubble--md"
                    >
                      <ChatMarkdown :source="message.content" :supplier="llmSupplier" />
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
                  <div
                    v-else-if="message.role !== 'assistant' || message.content"
                    class="chat-bubble"
                    :class="{ 'chat-bubble--md': message.role === 'assistant' }"
                  >
                    <ChatMarkdown v-if="message.role === 'assistant'" :source="message.content" />
                    <template v-else>{{ message.content }}</template>
                  </div>
                </div>
                <div v-if="sherpaStore.isSyncing" class="chat-message assistant">
                  <div class="chat-bubble">Analyzing workflow...</div>
                </div>
                <div
                  v-for="tool in activeSherpaTools"
                  :key="`${tool.tool_name}-${tool.status}`"
                  class="chat-message assistant"
                >
                  <div class="chat-bubble">
                    {{ tool.status === "started" ? `Running tool: ${tool.tool_name}...` : `Completed tool: ${tool.tool_name}.` }}
                  </div>
                </div>
                <div v-if="sherpaStatusMessage" class="chat-message assistant">
                  <div class="chat-bubble">{{ sherpaStatusMessage }}</div>
                </div>
              </template>
            </div>

            <div class="chat-input-shell">
              <div
                v-if="activeTab === 'sherpa' && sherpaStore.subscriptionRequired && sherpaStore.subscriptionUpgradeUrl"
                class="chat-upgrade-row"
              >
                <Button
                  label="Upgrade Plan"
                  size="small"
                  outlined
                  @click="sherpaStore.openSubscriptionUpgrade()"
                />
              </div>
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
import { useRoute, useRouter } from "vue-router";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Menu from "primevue/menu";
import { useToast } from "primevue/usetoast";

import ChatMarkdown from "@/components/ChatMarkdown.vue";
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
const route = useRoute();
const store = useLlmStore();
const sherpaStore = useSherpaStore();
const experimentStore = useExperimentStore();
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();
const authStore = useAuthStore();
const toast = useToast();
const { appMode, appConfig, isFeatureEnabled } = useAppConfig();
const { isDemoMode } = useDemoMode();

const llmSupplier = computed(() => store.currentConfig?.provider ?? undefined);

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

type ChatTab = "llm" | "sherpa";

const sherpaEnabled = computed(() => isFeatureEnabled("sherpaAdvisor"));
const llmChatEnabled = computed(() => isFeatureEnabled("chatAssistant"));
const showLlmTab = computed(() => !(isDemoMode.value && sherpaEnabled.value));
const showTabToggle = computed(() => showLlmTab.value && sherpaEnabled.value);
const activeTabLabel = computed(() => (activeTab.value === "sherpa" ? "Sherpa Advisor" : "LLM Chat"));
const hasSherpaSubscription = computed(
  () => (appConfig.value?.subscription?.plan || "none") !== "none"
);
const hasExecutionResults = computed(
  () => Object.keys(workflowStore.lastExecutionResults || {}).length > 0
);

const requestedTab = computed<ChatTab | null>(() => {
  const rawTab = route.query.tab;
  if (rawTab === "sherpa" || rawTab === "llm") {
    return rawTab;
  }
  return null;
});

const resolveInitialTab = (): ChatTab => {
  if (requestedTab.value === "sherpa" && sherpaEnabled.value) {
    return "sherpa";
  }
  if (requestedTab.value === "llm" && showLlmTab.value) {
    return "llm";
  }
  if (!showLlmTab.value && sherpaEnabled.value) {
    return "sherpa";
  }
  return "llm";
};

const activeTab = ref<ChatTab>(resolveInitialTab());

const setActiveTab = (tab: ChatTab) => {
  if (tab === "sherpa" && !sherpaEnabled.value) {
    return;
  }
  if (tab === "llm" && !showLlmTab.value) {
    return;
  }
  activeTab.value = tab;
};

const switchToSherpa = () => {
  setActiveTab("sherpa");
};

const inputPlaceholder = computed(() => {
  if (activeTab.value === "sherpa") {
    if (workflowStore.workflowId && !hasExecutionResults.value) {
      return "Run the workflow first, then ask Sherpa about the results...";
    }
    return workflowStore.workflowId
      ? "Ask Sherpa about your workflow results, diagnostics, or next steps..."
      : "Ask Sherpa about chemistry, datasets, or your next workflow step...";
  }
  return "Ask about spectra, exports, or processing... (Type '/' to clear chat)";
});

const inputDisabled = computed(() => {
  if (activeTab.value === "llm") return !llmChatEnabled.value || !llmChatAllowed.value;
  return false;
});

const sherpaStatusMessage = computed(() => {
  if (!sherpaStore.isChatting) {
    return null;
  }

  const lastMessage =
    sherpaStore.messages.length > 0
      ? sherpaStore.messages[sherpaStore.messages.length - 1]
      : null;
  const hasRunningTools = sherpaStore.activeTools.some((tool) => tool.status === "started");

  if (!lastMessage || lastMessage.role !== "assistant") {
    return hasRunningTools
      ? `Sherpa Advisor is running ${sherpaStore.activeTools.find((tool) => tool.status === "started")?.tool_name || "a tool"}...`
      : "Contacting Sherpa Advisor...";
  }

  if (!lastMessage.content.trim()) {
    return hasRunningTools
      ? `Sherpa Advisor is running ${sherpaStore.activeTools.find((tool) => tool.status === "started")?.tool_name || "a tool"}...`
      : "Sherpa Advisor is preparing a response...";
  }

  return null;
});

const activeSherpaTools = computed(() =>
  sherpaStore.activeTools.filter((tool) => tool.status === "started")
);

// ── LLM Provider Menu ────────────────────────────────────────

const llmMenu = ref();
const sherpaConversationMenu = ref();
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

const sherpaConversationMenuItems = computed(() => {
  const items: Array<Record<string, unknown>> = [
    {
      label: "New conversation",
      icon: "pi pi-plus",
      isAction: true,
      command: () => startNewSherpaConversation(),
    },
  ];

  if (sherpaStore.conversations.length > 0) {
    items.push({ separator: true });
    items.push(
      ...sherpaStore.conversations.map((conversation) => ({
        label: conversation.title,
        updatedAt: formatDateTime(conversation.updatedAt),
        icon: conversation.id === sherpaStore.currentConversationId ? "pi pi-check" : "pi pi-comment",
        active: conversation.id === sherpaStore.currentConversationId,
        command: () => {
          void onSherpaConversationSelect(conversation.id);
        },
      }))
    );
  } else {
    items.push({ separator: true });
    items.push({
      label: "No saved topics yet",
      icon: "pi pi-info-circle",
      disabled: true,
    });
  }

  return items;
});

const toggleSherpaConversationMenu = (event: Event) => {
  sherpaConversationMenu.value?.toggle(event);
};

const switchProvider = async (provider: string) => {
  selectedProvider.value = provider;
  await onProviderChange();
};

// Sync with current config
watch(
  () => [showLlmTab.value, sherpaEnabled.value, requestedTab.value] as const,
  ([llmVisible, sherpaVisible, tabFromRoute]) => {
    if (tabFromRoute === "sherpa" && sherpaVisible) {
      setActiveTab("sherpa");
      return;
    }
    if (tabFromRoute === "llm" && llmVisible) {
      setActiveTab("llm");
      return;
    }
    if (!llmVisible && sherpaVisible) {
      setActiveTab("sherpa");
      return;
    }
    if (activeTab.value === "sherpa" && !sherpaVisible && llmVisible) {
      setActiveTab("llm");
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
    await sherpaStore.refreshConversations(projectStore.currentProjectId);
    if (appMode.value === "local") {
      // Local mode derives chat readiness from /config rather than server-owned /llm/debug/config.
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
  () => [activeTab.value, store.loading, store.streaming, sherpaStore.isSyncing, sherpaStore.isChatting],
  async () => {
    await scrollToBottom();
  }
);

watch(
  () => projectStore.currentProjectId,
  async (projectId) => {
    await sherpaStore.refreshConversations(projectId);
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

  const deriveShapeAndType = (
    result: Record<string, unknown> | null | undefined
  ): { resultShape: number[] | null; outputType: string | null } => {
    let resultShape: number[] | null = null;
    let outputType: string | null = null;

    if (!result || typeof result !== "object") {
      return { resultShape, outputType };
    }

    const primary =
      result.default && typeof result.default === "object"
        ? (result.default as Record<string, unknown>)
        : result;

    if (typeof primary.type === "string" && primary.type.trim()) {
      outputType = primary.type;
    }

    if (Array.isArray(primary.shape) && primary.shape.every((value) => typeof value === "number")) {
      resultShape = primary.shape as number[];
    } else if (typeof primary.n_samples === "number" && typeof primary.n_features === "number") {
      resultShape = [primary.n_samples, primary.n_features];
    }

    return { resultShape, outputType };
  };

  // Build V2 node list with library metadata
  const contextNodes = nodes.map((n) => {
    const meta = getNodeMetadata(n.type);
    const execState = n.executionState;
    const rawResult =
      lastExecutionResults && typeof lastExecutionResults === "object"
        ? (lastExecutionResults[n.id] as Record<string, unknown> | undefined)
        : undefined;
    const inferredResult = deriveShapeAndType(rawResult);
    const hasPersistedResult = rawResult !== undefined;

    // Filter param_descriptions to params actually set on this node
    const setParamNames = new Set(Object.keys(n.params || {}));
    const paramDescriptions = meta?.parameters
      ?.filter((p) => setParamNames.has(p.name))
      .map((p) => ({ name: p.name, label: p.label, description: p.description || null }))
      ?? null;

    // Result summary for this node (strip raw arrays, keep scalars + shapes)
    const resultShape = execState?.output_shape ?? inferredResult.resultShape;
    const resultStatistics: Record<string, number> | null = null;
    const executionStatus =
      execState?.status && execState.status !== "pending"
        ? execState.status
        : hasPersistedResult
          ? "completed"
          : execState?.status ?? null;

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
      output_type: execState?.output_type ?? inferredResult.outputType ?? meta?.output_type ?? null,
      execution_status: executionStatus,
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
      sherpaStore.startNewConversation();
      toast.add({
        severity: "success",
        summary: "New Sherpa Conversation",
        detail: "Started a new Sherpa conversation",
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

const onSherpaConversationSelect = async (conversationId: string | null) => {
  if (!conversationId) {
    return;
  }
  try {
    await sherpaStore.loadConversation(conversationId);
    toast.add({
      severity: "success",
      summary: "Sherpa Conversation Loaded",
      detail: "Previous Sherpa conversation restored",
      life: 2000,
    });
  } catch (error: unknown) {
    console.error("Failed to load Sherpa conversation:", error);
    toast.add({
      severity: "error",
      summary: "Sherpa Load Failed",
      detail: getErrorMessage(error, "Unknown error"),
      life: 3000,
    });
  }
};

const startNewSherpaConversation = () => {
  sherpaStore.startNewConversation();
  userMessage.value = "";
  toast.add({
    severity: "success",
    summary: "New Sherpa Conversation",
    detail: "Started a new Sherpa conversation",
    life: 2000,
  });
};

const openInNewTab = () => {
  const target = router.resolve({
    path: "/llm-chat",
    query: { tab: activeTab.value },
  });
  if (typeof window !== "undefined") {
    const opened = window.open(target.href, "_blank", "noopener,noreferrer");
    if (opened) {
      return;
    }
  }
  router.push({
    path: "/llm-chat",
    query: { tab: activeTab.value },
  });
};

const onProviderChange = async () => {
  if (!store.currentConfig) return;
  // Capability gate: /llm-config is server-only. On OSS-only
  // installs, silently no-op — the settings UI should be hidden already
  // but this guards direct invocation paths.
  if (!isFeatureEnabled("sherpaAdvisor")) return;

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
  flex-wrap: wrap;
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
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
  min-width: 0;
  justify-content: flex-end;
}

.sherpa-conversation-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 0 1 auto;
  justify-content: flex-end;
}

.sherpa-topics-btn {
  color: #475569;
}

.sherpa-menu {
  min-width: 260px;
}

.sherpa-menu-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sherpa-menu-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.sherpa-menu-item--action {
  font-weight: 600;
}

.sherpa-menu-item--disabled {
  color: #94a3b8;
  cursor: default;
}

.sherpa-menu-item.active {
  background: #e0f2fe;
}

.sherpa-menu-title {
  color: #1e293b;
  font-size: 0.85rem;
  line-height: 1.2;
}

.sherpa-menu-meta {
  color: #64748b;
  font-size: 0.72rem;
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

.chat-upgrade-row {
  display: flex;
  justify-content: flex-end;
  padding: 8px 8px 0;
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

.chat-bubble--md {
  white-space: normal;
}

.chat-bubble--md :deep(p) {
  margin: 0.4em 0;
}

.chat-bubble--md :deep(p:first-child) {
  margin-top: 0;
}

.chat-bubble--md :deep(p:last-child) {
  margin-bottom: 0;
}

.chat-bubble--md :deep(ul),
.chat-bubble--md :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.4em;
}

.chat-bubble--md :deep(code) {
  background: rgba(0, 0, 0, 0.08);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.9em;
}

.chat-bubble--md :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 8px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.4em 0;
}

.chat-bubble--md :deep(pre code) {
  background: none;
  padding: 0;
}

.chat-bubble--md :deep(h1),
.chat-bubble--md :deep(h2),
.chat-bubble--md :deep(h3) {
  margin: 0.5em 0 0.3em;
  font-size: 1em;
  font-weight: 600;
}

.chat-bubble--md :deep(table) {
  border-collapse: collapse;
  margin: 0.4em 0;
  font-size: 0.9em;
}

.chat-bubble--md :deep(th),
.chat-bubble--md :deep(td) {
  border: 1px solid rgba(0, 0, 0, 0.15);
  padding: 3px 8px;
}

.chat-bubble--md :deep(.katex-display) {
  margin: 0.5em 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.chat-bubble--md :deep(.katex-display::-webkit-scrollbar) {
  height: 6px;
}

.chat-bubble--md :deep(.katex) {
  font-size: 1em;
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
