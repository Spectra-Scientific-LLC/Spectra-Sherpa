<template>
  <div class="integrations-tab">
    <p v-if="appConfig?.desktop">Local desktop application. It does not connect to Spectra Scientific services.</p>
    <!-- Data & Privacy -->
    <div class="section">
      <h3>Data &amp; Privacy</h3>
      <p class="muted-text">Control how your data is shared with external services. Changes take effect immediately.</p>

      <div v-if="privacyLoadError" class="message error">
        <i class="pi pi-times-circle" />
        {{ privacyLoadError }}
      </div>

      <div class="panel" v-if="!privacyLoadError">
        <div v-if="privacyLoading" class="loading-row">
          <i class="pi pi-spin pi-spinner" /> Loading privacy settings...
        </div>

        <template v-else>
          <div class="toggle-row">
            <div class="toggle-info">
              <strong>Enable Chat Access</strong>
              <p v-if="chatToggleReason">{{ chatToggleReason }}</p>
              <p v-else>Allow Spectra Sherpa to call configured chat services.</p>
            </div>
            <InputSwitch v-model="privacyForm.allow_llm_chat" :disabled="!chatToggleEnabled" @change="savePrivacy" />
          </div>

          <div class="toggle-row">
            <div class="toggle-info">
              <strong>Share Workflow Context with Sherpa</strong>
              <p v-if="contextToggleReason">{{ contextToggleReason }}</p>
              <p v-else>
                Allow the Advisor to use workflow context. Your deployment controls which information is included.
              </p>
            </div>
            <InputSwitch v-model="privacyForm.allow_llm_context" :disabled="!contextToggleEnabled" @change="savePrivacy" />
          </div>

          <div class="toggle-row">
            <div class="toggle-info">
              <strong>NIST WebBook Queries</strong>
              <p>Allow outbound requests to the NIST WebBook for spectral library lookups.</p>
            </div>
            <InputSwitch v-model="privacyForm.allow_nist_queries" @change="savePrivacy" />
          </div>

          <div class="toggle-row">
            <div class="toggle-info">
              <strong>HITRAN/HAPI Queries</strong>
              <p>Allow outbound HITRAN line-table requests for synthesis spectra.</p>
            </div>
            <InputSwitch v-model="privacyForm.allow_hitran_queries" @change="savePrivacy" />
          </div>

          <div class="toggle-row">
            <div class="toggle-info">
              <strong>Data Export (managed deployments)</strong>
              <p>
                Allow browser downloads of processed spectra, results, and project files in managed deployments.
                Local installations always allow exports.
              </p>
            </div>
            <InputSwitch
              v-model="privacyForm.allow_export"
              :disabled="appMode === 'local'"
              @change="savePrivacy"
            />
          </div>

          <div class="toggle-row" v-if="showSyncOption">
            <div class="toggle-info">
              <strong>SpectraSherpa Cloud Sync</strong>
              <p>Allow syncing workflow data with the SpectraSherpa cloud service.</p>
            </div>
            <InputSwitch v-model="privacyForm.allow_spectrasherpa_sync" @change="savePrivacy" />
          </div>
        </template>

        <div v-if="privacySaveMessage" class="message success">
          <i class="pi pi-check-circle" />
          {{ privacySaveMessage }}
        </div>
        <div v-if="privacySaveError" class="message error">
          <i class="pi pi-times-circle" />
          {{ privacySaveError }}
        </div>
      </div>
    </div>

  </div>
</template>
<script setup lang="ts">
import axios from 'axios';
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import api from '@/api/client';
import { useAppConfig } from '@/composables/useAppConfig';
import { useDemoMode } from '@/composables/useDemoMode';
import { getErrorMessage } from '@/utils/errors';
import InputSwitch from 'primevue/inputswitch';

defineProps<{ privacyOnly?: boolean }>();
const { appConfig, loadConfig, isFeatureEnabled } = useAppConfig();
const appMode = computed(() => appConfig.value?.mode);
const { isDemoMode } = useDemoMode();
// --- Data & Privacy state ---
const privacyLoading = ref(true);
const privacyLoadError = ref('');
const privacySaveMessage = ref('');
const privacySaveError = ref('');
const showSyncOption = ref(false);
const privacyForm = reactive({
  allow_llm_chat: false,
  allow_llm_context: false,
  allow_nist_queries: false,
  allow_hitran_queries: false,
  allow_export: false,
  allow_spectrasherpa_sync: false,
});

const chatToggleEnabled = computed(() => !isDemoMode.value);
const chatToggleReason = computed(() =>
  isDemoMode.value ? 'Chat access is always enabled in the Sherpa demo.' : ''
);
const contextToggleEnabled = computed(() => {
  if (isDemoMode.value) return false;
  if (appMode.value === 'local') return false;
  if (!privacyForm.allow_llm_chat) return false;
  return isFeatureEnabled('chatAssistant');
});
const contextToggleReason = computed(() => {
  if (isDemoMode.value) return 'Workflow context sharing is always enabled in the Sherpa demo.';
  if (appMode.value === 'local') return 'Context-aware chat requires a Sherpa subscription.';
  if (!privacyForm.allow_llm_chat) return 'Enable Chat Access to share workflow context with Sherpa.';
  if (!isFeatureEnabled('chatAssistant')) return 'Context-aware chat requires a Sherpa subscription.';
  return '';
});

let privacySaveTimer: ReturnType<typeof setTimeout> | null = null;

async function savePrivacy() {
  privacySaveError.value = '';
  privacySaveMessage.value = '';
  try {
    if (isDemoMode.value) {
      privacyForm.allow_llm_chat = true;
      privacyForm.allow_llm_context = true;
    } else {
      if (!contextToggleEnabled.value) privacyForm.allow_llm_context = false;
      if (!privacyForm.allow_llm_chat) privacyForm.allow_llm_context = false;
    }
    await api.put('/egress/defaults', {
      allow_llm_chat: isDemoMode.value ? true : privacyForm.allow_llm_chat,
      allow_llm_context: isDemoMode.value ? true : (contextToggleEnabled.value ? privacyForm.allow_llm_context : false),
      allow_nist_queries: privacyForm.allow_nist_queries,
      allow_hitran_queries: privacyForm.allow_hitran_queries,
      allow_export: privacyForm.allow_export,
      allow_spectrasherpa_sync: privacyForm.allow_spectrasherpa_sync,
    });
    window.dispatchEvent(new CustomEvent('egress-defaults-changed'));
    privacySaveMessage.value = 'Privacy settings updated.';
    if (privacySaveTimer) clearTimeout(privacySaveTimer);
    privacySaveTimer = setTimeout(() => { privacySaveMessage.value = ''; }, 3000);
  } catch (err: unknown) {
    privacySaveError.value = getErrorMessage(err, 'Failed to save privacy settings');
  }
}


onUnmounted(() => { if (privacySaveTimer) clearTimeout(privacySaveTimer); });
onMounted(async () => {
  await loadConfig();
  // Load privacy settings
  // Managed deployments may expose a separate synchronization permission.
  showSyncOption.value = appMode.value === 'enterprise' && appConfig.value?.siteProfile !== 'pro';
  if (isDemoMode.value) {
    privacyForm.allow_llm_chat = true;
    privacyForm.allow_llm_context = true;
  }
  try {
    const { data } = await api.get('/egress/defaults');
    if (data) {
      privacyForm.allow_llm_chat = isDemoMode.value ? true : (data.allow_llm_chat ?? false);
      privacyForm.allow_llm_context = isDemoMode.value
        ? true
        : (appMode.value === 'local' || !(data.allow_llm_chat ?? false)
            ? false
            : (data.allow_llm_context ?? false));
      privacyForm.allow_nist_queries = data.allow_nist_queries ?? false;
      privacyForm.allow_hitran_queries = data.allow_hitran_queries ?? false;
      privacyForm.allow_export = data.allow_export ?? false;
      privacyForm.allow_spectrasherpa_sync = data.allow_spectrasherpa_sync ?? false;
      if (appConfig.value?.advisorContextPolicy === 'receipt') {
        privacyForm.allow_spectrasherpa_sync = false;
      }
    }
  } catch (err: unknown) {
    if (!axios.isAxiosError(err) || err.response?.status !== 404) {
      privacyLoadError.value = getErrorMessage(err, 'Failed to load privacy settings');
    }
  } finally {
    privacyLoading.value = false;
  }
});
</script>
<style scoped>
.integrations-tab {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 920px;
  padding: 0;
}

.info-callout {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  background: #1e3a5f;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  color: #bfdbfe;
  font-size: 0.875rem;
  line-height: 1.5;
}

.info-callout .pi {
  color: #3b82f6;
  font-size: 1rem;
  flex-shrink: 0;
  margin-top: 2px;
}

.section {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 1.25rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.muted-text {
  color: var(--text-color-secondary);
  font-size: 0.9rem;
  margin: 0 0 1rem;
}

.connection-panel {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid var(--surface-border);
}

.setup-form .field {
  margin-bottom: 1.25rem;
}

.setup-form label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
}

.setup-form .help-text {
  display: block;
  margin-top: 0.25rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.setup-form .actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.env-notice {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  background: var(--surface-ground);
  border-radius: 8px;
  margin-bottom: 1.5rem;
}

.env-notice i {
  font-size: 1.5rem;
  color: var(--primary-color);
  flex-shrink: 0;
}

.env-notice p {
  margin: 0.25rem 0;
  font-size: 0.9rem;
}

.env-notice pre {
  background: var(--surface-card);
  padding: 0.75rem;
  border-radius: 4px;
  font-size: 0.85rem;
  overflow-x: auto;
  margin: 0.5rem 0;
}

.env-notice code {
  background: var(--surface-card);
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-size: 0.85rem;
}

.env-notice.small {
  padding: 0.75rem;
  margin-top: 1rem;
  margin-bottom: 0;
}

.env-notice.small i {
  font-size: 1rem;
}

.env-notice.small span {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.connected-info .info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.info-item .label {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.info-item .value {
  font-weight: 500;
}

.sherpa-features {
  margin: 1.5rem 0;
  padding-top: 1.5rem;
  border-top: 1px solid var(--surface-border);
}

.sherpa-features h4 {
  margin: 0 0 1rem;
  font-size: 0.95rem;
  font-weight: 600;
}

.feature-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.5rem;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
}

.feature-disabled {
  color: var(--text-color-secondary);
}

.managed-keys {
  margin: 1.5rem 0;
  padding-top: 1.5rem;
  border-top: 1px solid var(--surface-border);
}

.managed-keys h4 {
  margin: 0 0 1rem;
  font-size: 0.95rem;
  font-weight: 600;
}

.key-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.key-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--surface-ground);
  border-radius: 8px;
}

.connected-info .actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--surface-border);
}

.mode-panel {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid var(--surface-border);
}

.mode-info {
  text-align: center;
  margin-bottom: 1.5rem;
}

.mode-description {
  margin-top: 0.75rem;
  color: var(--text-color-secondary);
}

.mode-features {
  display: flex;
  justify-content: center;
  gap: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--surface-border);
}

.feature {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-color-secondary);
}

.feature i {
  font-size: 1.1rem;
}

.test-result {
  padding: 1rem;
}

.test-result .success,
.test-result .error {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.test-result .success i {
  font-size: 2rem;
  color: var(--green-500);
}

.test-result .error i {
  font-size: 2rem;
  color: var(--red-500);
}

.test-result .details p {
  margin: 0.25rem 0;
}

.panel {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid var(--surface-border);
}

.toggle-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--surface-border);
}

.toggle-row:last-of-type {
  border-bottom: none;
}

.toggle-info {
  flex: 1;
}

.toggle-info strong {
  font-size: 0.95rem;
  color: var(--text-color);
}

.toggle-info p {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.loading-row {
  padding: 20px;
  text-align: center;
  color: var(--text-color-secondary);
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
