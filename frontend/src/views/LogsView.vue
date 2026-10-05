<template>
  <section class="logs-content">
    <header class="tab-header">
      <h1>Logs</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          class="p-button-sm p-button-text"
          :disabled="isHostedPro"
          @click="fetchLogs"
        />
      </ResponsiveHeaderActions>
    </header>
    <p v-if="isHostedPro" role="status">Server logs are available to the deployment operator. Contact your operator for hosted diagnostics.</p>
    <ChatExchangeHistory v-if="appMode === 'local'" />
    <div v-if="!isHostedPro" class="logs-list">
      <div v-if="error" class="logs-error">{{ error }}</div>
      <div v-for="entry in logs" :key="entry.timestamp" class="log-entry">
        <strong>{{ entry.level }}</strong>
        <span>{{ entry.timestamp }}</span>
        <div>{{ entry.message }}</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import Button from "primevue/button";

import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import ChatExchangeHistory from "@/components/ChatExchangeHistory.vue";
import api from "@/api/client";

const { appMode, siteProfile } = useAppConfig();
const isHostedPro = computed(() => appMode.value === "enterprise" && siteProfile?.value === "pro");

const logs = ref<Array<{ timestamp: string; level: string; message: string }>>([]);
const error = ref("");

const fetchLogs = async () => {
  if (isHostedPro.value) return;
  error.value = "";
  try {
    const response = await api.get("/logs");
    logs.value = response.data.logs || [];
  } catch {
    error.value = "Unable to load logs. Check API key and server status.";
  }
};

const headerActionItems = computed(() => [
  { label: "Refresh", icon: "pi pi-refresh", command: fetchLogs, disabled: isHostedPro.value },
]);
</script>

<style scoped>
.logs-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  height: 100%;
  padding: 0 1rem 1rem;
  overflow: auto;
}

:global(.content:has(.logs-content)) {
  background: #e4e0fa;
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.logs-error {
  color: #b91c1c;
}

.log-entry {
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.log-entry span {
  margin-left: 0.5rem;
  color: var(--text-color-secondary);
}

.log-entry div {
  margin-top: 0.25rem;
  white-space: pre-wrap;
}
</style>
