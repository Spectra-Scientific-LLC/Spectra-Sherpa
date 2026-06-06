<template>
  <section class="logs-content">
    <header class="tab-header">
      <h1>Logs</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          class="p-button-sm p-button-text"
          @click="fetchLogs"
        />
      </ResponsiveHeaderActions>
    </header>
    <div class="logs-list">
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
import { ref } from "vue";
import Button from "primevue/button";

import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import api from "@/api/client";

const logs = ref<Array<{ timestamp: string; level: string; message: string }>>([]);
const error = ref("");

const fetchLogs = async () => {
  error.value = "";
  try {
    const response = await api.get("/logs");
    logs.value = response.data.logs || [];
  } catch {
    error.value = "Unable to load logs. Check API key and server status.";
  }
};

const headerActionItems = [
  { label: "Refresh", icon: "pi pi-refresh", command: fetchLogs },
];
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
