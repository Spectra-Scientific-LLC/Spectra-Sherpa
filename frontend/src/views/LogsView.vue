<template>
  <section class="logs-content">
    <WorkspaceHeader title="Logs" :actions="headerActionItems">
      <Button
        label="Refresh"
        icon="pi pi-refresh"
        class="p-button-sm p-button-text"
        :disabled="!canReadLogs || loading"
        :loading="loading"
        @click="fetchLogs"
      />
    </WorkspaceHeader>
    <p v-if="isHostedPro" role="status">Server logs are available to the deployment operator. Contact your operator for hosted diagnostics.</p>
    <p v-else-if="isDemo && !canReadLogs" role="status">Application logs are available only to Demo administrators.</p>
    <p v-else-if="isDemo" role="note">Recent backend application logs across this Demo deployment, including other users' activity. This sensitive snapshot is limited to this backend process; it does not include worker, Docker, or system logs. Credential redaction is best effort.</p>
    <ChatExchangeHistory v-if="appMode === 'local'" />
    <div v-if="canReadLogs" class="logs-list" :aria-busy="loading">
      <div v-if="error" class="logs-error" role="alert">{{ error }}</div>
      <p v-else-if="loading" role="status">Loading logs…</p>
      <p v-else-if="!logs.length" role="status">{{ loaded ? 'No recent application logs are available.' : 'Select Refresh to load recent application logs.' }}</p>
      <div v-for="(entry, index) in logs" :key="`${entry.timestamp}-${index}`" class="log-entry">
        <strong>{{ entry.level }}</strong>
        <span>{{ entry.timestamp }}</span>
        <div>{{ entry.message }}</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useAuthStore } from "@/stores/auth";
import Button from "primevue/button";

import ChatExchangeHistory from "@/components/ChatExchangeHistory.vue";
import api from "@/api/client";

const { appMode, siteProfile } = useAppConfig();
const auth = useAuthStore();
const isHostedPro = computed(() => appMode.value === "enterprise" && siteProfile?.value === "pro");
const isDemo = computed(() => appMode.value === "enterprise" && siteProfile?.value === "demo");
const canReadLogs = computed(() => !isHostedPro.value && (!isDemo.value ||
  (auth.user?.capabilities?.admin === true && auth.user?.is_active !== false)));

const logs = ref<Array<{ timestamp: string; level: string; message: string }>>([]);
const error = ref("");
const loading = ref(false);
const loaded = ref(false);
let pending: AbortController | null = null;

const clearLogs = () => {
  pending?.abort();
  pending = null;
  logs.value = [];
  error.value = "";
  loading.value = false;
  loaded.value = false;
};
watch(() => [appMode.value, siteProfile?.value, auth.user?.id,
  auth.user?.capabilities?.admin, auth.user?.is_active, auth.token], clearLogs, { flush: "sync" });
onBeforeUnmount(clearLogs);

const fetchLogs = async () => {
  if (!canReadLogs.value || loading.value) return;
  error.value = "";
  logs.value = [];
  loading.value = true;
  const controller = new AbortController();
  pending = controller;
  try {
    const response = isDemo.value
      ? await api.get("/admin/logs", { signal: controller.signal })
      : await api.get("/logs", { signal: controller.signal });
    if (pending !== controller) return;
    logs.value = response.data.logs || [];
    loaded.value = true;
  } catch (cause) {
    if (pending !== controller) return;
    const status = (cause as { response?: { status?: number } }).response?.status;
    error.value = status === 401 ? "Your session has expired. Sign in again to view logs."
      : status === 403 ? (isDemo.value ? "Only Demo administrators can view application logs."
        : "Application logs are accessible only from the server's localhost connection.")
      : "Unable to load application logs. Try Refresh again or contact the deployment operator.";
  } finally {
    if (pending === controller) {
      pending = null;
      loading.value = false;
    }
  }
};

const headerActionItems = computed(() => [
  { label: "Refresh", icon: "pi pi-refresh", command: fetchLogs, disabled: !canReadLogs.value || loading.value },
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
  background: var(--workspace-background);
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.logs-error {
  color: var(--ss-danger);
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
