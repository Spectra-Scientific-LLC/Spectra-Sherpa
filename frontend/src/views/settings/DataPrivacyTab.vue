<template>
  <div class="tab-section">
    <h3>Data &amp; Privacy</h3>
    <p class="muted-text">
      Control how your data is shared with external services.
      Changes take effect immediately.
    </p>

    <div v-if="loadError" class="message error">
      <i class="pi pi-times-circle" />
      {{ loadError }}
    </div>

    <div class="panel" v-if="!loadError">
      <div v-if="loading" class="loading-row">
        <i class="pi pi-spin pi-spinner" /> Loading privacy settings...
      </div>

      <template v-else>
        <div class="toggle-row">
          <div class="toggle-info">
            <strong>Enable AI Chat</strong>
            <p>Allow Spectra Sherpa to call an LLM for chat and assistant features.</p>
          </div>
          <InputSwitch v-model="form.allow_llm_chat" @change="save" />
        </div>

        <div class="toggle-row">
          <div class="toggle-info">
            <strong>Share Workflow Context with Sherpa</strong>
            <p v-if="contextToggleReason">{{ contextToggleReason }}</p>
            <p v-else>Allow workflow structure, parameters, and execution summaries to be sent to Sherpa for context-aware chat.</p>
          </div>
          <InputSwitch
            v-model="form.allow_llm_context"
            :disabled="!contextToggleEnabled"
            @change="save"
          />
        </div>

        <div class="toggle-row">
          <div class="toggle-info">
            <strong>NIST WebBook Queries</strong>
            <p>Allow outbound requests to the NIST WebBook for spectral library lookups.</p>
          </div>
          <InputSwitch v-model="form.allow_nist_queries" @change="save" />
        </div>

        <div class="toggle-row">
          <div class="toggle-info">
            <strong>Data Export</strong>
            <p>Allow downloading processed spectra and results to your browser.</p>
          </div>
          <InputSwitch v-model="form.allow_export" @change="save" />
        </div>

        <div class="toggle-row" v-if="showSyncOption">
          <div class="toggle-info">
            <strong>SpectraSherpa Cloud Sync</strong>
            <p>Allow syncing workflow data with the SpectraSherpa cloud service.</p>
          </div>
          <InputSwitch v-model="form.allow_spectrasherpa_sync" @change="save" />
        </div>
      </template>

      <div v-if="saveMessage" class="message success">
        <i class="pi pi-check-circle" />
        {{ saveMessage }}
      </div>
      <div v-if="saveError" class="message error">
        <i class="pi pi-times-circle" />
        {{ saveError }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, reactive, ref } from "vue";
import InputSwitch from "primevue/inputswitch";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";
import { getErrorMessage } from "@/utils/errors";

const { appMode, isFeatureEnabled } = useAppConfig();

const loading = ref(true);
const loadError = ref("");
const saveMessage = ref("");
const saveError = ref("");

const showSyncOption = ref(false);

const form = reactive({
  allow_llm_chat: false,
  allow_llm_context: false,
  allow_nist_queries: false,
  allow_export: false,
  allow_spectrasherpa_sync: false,
});

const contextToggleEnabled = computed(() => {
  if (appMode.value === "local") return false;
  return isFeatureEnabled("chatAssistant");
});

const contextToggleReason = computed(() => {
  if (appMode.value === "local") {
    return "Context-aware chat requires a Sherpa subscription.";
  }
  if (!isFeatureEnabled("chatAssistant")) {
    return "Context-aware chat requires a Sherpa subscription.";
  }
  return "";
});

onMounted(async () => {
  showSyncOption.value = appMode.value !== "local";
  try {
    const { data } = await api.get("/egress/defaults");
    if (data) {
      form.allow_llm_chat = data.allow_llm_chat ?? false;
      form.allow_llm_context = appMode.value === "local" ? false : (data.allow_llm_context ?? false);
      form.allow_nist_queries = data.allow_nist_queries ?? false;
      form.allow_export = data.allow_export ?? false;
      form.allow_spectrasherpa_sync = data.allow_spectrasherpa_sync ?? false;
    }
  } catch (err: unknown) {
    // 404 or no defaults yet — use form defaults (all conservative)
    if (!axios.isAxiosError(err) || err.response?.status !== 404) {
      loadError.value = getErrorMessage(err, "Failed to load privacy settings");
    }
  } finally {
    loading.value = false;
  }
});

let saveTimer: ReturnType<typeof setTimeout> | null = null;

async function save() {
  saveError.value = "";
  saveMessage.value = "";
  try {
    if (!contextToggleEnabled.value) {
      form.allow_llm_context = false;
    }
    await api.put("/egress/defaults", {
      allow_llm_chat: form.allow_llm_chat,
      allow_llm_context: contextToggleEnabled.value ? form.allow_llm_context : false,
      allow_nist_queries: form.allow_nist_queries,
      allow_export: form.allow_export,
      allow_spectrasherpa_sync: form.allow_spectrasherpa_sync,
    });
    window.dispatchEvent(new CustomEvent("egress-defaults-changed"));
    saveMessage.value = "Privacy settings updated.";
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveMessage.value = ""; }, 3000);
  } catch (err: unknown) {
    saveError.value = getErrorMessage(err, "Failed to save privacy settings");
  }
}
</script>

<style scoped>
.panel {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 20px;
  margin-top: 16px;
}

.toggle-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid #e2e8f0;
}

.toggle-row:last-of-type {
  border-bottom: none;
}

.toggle-info {
  flex: 1;
}

.toggle-info strong {
  font-size: 0.95rem;
  color: #1e293b;
}

.toggle-info p {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: #64748b;
}

.loading-row {
  padding: 20px;
  text-align: center;
  color: #64748b;
  font-size: 0.9rem;
}

.message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 6px;
  margin-top: 12px;
  font-size: 0.85rem;
}

.message.success {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.message.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
</style>
