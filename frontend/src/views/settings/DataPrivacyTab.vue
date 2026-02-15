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
            <strong>LLM Context Sharing</strong>
            <p>Allow spectral data and metadata to be sent to LLM providers (OpenAI, Anthropic, DeepSeek, etc.) for AI assistant features.</p>
          </div>
          <InputSwitch v-model="form.allow_llm_context" @change="save" />
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
import { onMounted, reactive, ref } from "vue";
import InputSwitch from "primevue/inputswitch";
import api from "@/api/client";
import { useAppConfig } from "@/composables/useAppConfig";

const { appMode } = useAppConfig();

const loading = ref(true);
const loadError = ref("");
const saveMessage = ref("");
const saveError = ref("");

const showSyncOption = ref(false);

const form = reactive({
  allow_llm_context: false,
  allow_nist_queries: false,
  allow_export: false,
  allow_spectrasherpa_sync: false,
});

onMounted(async () => {
  showSyncOption.value = appMode.value !== "local";
  try {
    const { data } = await api.get("/egress/defaults");
    if (data) {
      form.allow_llm_context = data.allow_llm_context ?? false;
      form.allow_nist_queries = data.allow_nist_queries ?? false;
      form.allow_export = data.allow_export ?? false;
      form.allow_spectrasherpa_sync = data.allow_spectrasherpa_sync ?? false;
    }
  } catch (err: any) {
    // 404 or no defaults yet — use form defaults (all conservative)
    if (err.response?.status !== 404) {
      loadError.value = err.response?.data?.detail || "Failed to load privacy settings";
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
    await api.put("/egress/defaults", {
      allow_llm_context: form.allow_llm_context,
      allow_nist_queries: form.allow_nist_queries,
      allow_export: form.allow_export,
      allow_spectrasherpa_sync: form.allow_spectrasherpa_sync,
    });
    saveMessage.value = "Privacy settings updated.";
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveMessage.value = ""; }, 3000);
  } catch (err: any) {
    saveError.value = err.response?.data?.detail || "Failed to save privacy settings";
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
