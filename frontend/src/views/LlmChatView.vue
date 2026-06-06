<template>
  <div class="llm-chat-view">
    <!-- Header with Close Button -->
    <header class="llm-chat-header">
      <div class="llm-chat-header-left">
        <i class="pi pi-comments" style="font-size: 1.5rem; color: #3b82f6"></i>
        <h1>{{ pageTitle }}</h1>
      </div>
      <div class="llm-chat-header-actions">
        <Button
          v-if="appMode === 'local' && canConfigureLlm"
          icon="pi pi-cog"
          class="p-button-text llm-settings-btn"
          aria-label="BYO Chat Settings"
          @click="toggleLlmMenu"
          v-tooltip.bottom="'BYO Chat Settings'"
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
          icon="pi pi-times"
          label="Close"
          class="p-button-outlined"
          @click="goBack"
        />
      </div>
    </header>

    <div class="llm-chat-content">
      <ChatPanel :compact="false" :collapsed="false" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Button from "primevue/button";
import Menu from "primevue/menu";
import { useToast } from "primevue/usetoast";
import ChatPanel from "@/components/ChatPanel.vue";
import { useLlmStore } from "@/stores/llm";
import { useAppConfig } from "@/composables/useAppConfig";
import { getErrorMessage } from "@/utils/errors";
import api from "@/api/client";

const router = useRouter();
const route = useRoute();
const store = useLlmStore();
const toast = useToast();
const { appMode, isFeatureEnabled } = useAppConfig();
// Capability gate: provider switching writes to /llm-config which
// is server-only. Hide the settings cog on OSS-only installs.
const canConfigureLlm = computed(() => isFeatureEnabled("sherpaAdvisor"));
const pageTitle = computed(() => (appMode.value === "local" ? "BYO Chat" : "Chat"));

const goBack = () => {
  const returnTo = route.query.returnTo;
  if (typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//")) {
    router.push(returnTo);
    return;
  }
  router.push("/dashboard");
};

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

const onProviderChange = async () => {
  if (appMode.value !== "local") return;
  if (!canConfigureLlm.value) return;
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
</script>

<style scoped>
.llm-chat-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #ffffff;
}

.llm-chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: #ffffff;
  border-bottom: 1px solid var(--surface-border, #e2e8f0);
  flex-shrink: 0;
}

.llm-chat-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.llm-chat-header h1 {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 500;
  letter-spacing: 0;
  color: #1e293b;
}

.llm-chat-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.llm-settings-btn {
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

.llm-chat-content {
  flex: 1;
  overflow: hidden;
  padding: 0;
}

.llm-chat-content :deep(.chat-panel) {
  height: 100%;
}

.llm-chat-content :deep(.panel-topbar) {
  display: none;
}

@media (max-width: 640px) {
  .llm-chat-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .llm-chat-header-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
