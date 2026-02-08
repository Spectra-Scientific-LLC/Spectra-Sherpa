<template>
  <div class="integrations-tab">
    <!-- SpectraSherpa Cloud (hidden in local mode — no cloud connectivity) -->
    <div v-if="appMode !== 'local'" class="section">
      <div class="section-header">
        <h3>SpectraSherpa Cloud</h3>
        <Tag v-if="connectionStatus" :severity="connectionSeverity" :value="connectionLabel" />
      </div>
      <p class="muted-text">
        Connect to SpectraSherpa for managed LLM keys and cloud synchronization.
      </p>

      <div class="connection-panel">
        <div v-if="!isConfigured" class="setup-form">
          <div class="env-notice">
            <i class="pi pi-info-circle"></i>
            <div>
              <p><strong>Environment Configuration Required</strong></p>
              <p>SpectraSherpa connection is configured via environment variables for security.</p>
              <p>Add to your <code>.env</code> file:</p>
              <pre>SPECTRASHERPA_API_URL=https://endpoint.spectrascientific.ai/api/v1
SPECTRASHERPA_API_KEY=ss_your-key-here</pre>
            </div>
          </div>

          <div class="divider">
            <span>Test Connection</span>
          </div>

          <div class="field">
            <label for="server-url">Server URL (for testing)</label>
            <InputText
              id="server-url"
              v-model="serverUrl"
              placeholder="https://endpoint.spectrascientific.ai"
              :disabled="testing"
            />
          </div>
          <div class="field">
            <label for="api-key">API Key (for testing)</label>
            <div class="p-inputgroup">
              <InputText
                id="api-key"
                v-model="apiKey"
                :type="showKey ? 'text' : 'password'"
                placeholder="ss_..."
                :disabled="testing"
              />
              <Button
                :icon="showKey ? 'pi pi-eye-slash' : 'pi pi-eye'"
                @click="showKey = !showKey"
                class="p-button-secondary"
              />
            </div>
            <small class="help-text">Test your credentials before adding to environment</small>
          </div>
          <div class="actions">
            <Button
              label="Test Connection"
              icon="pi pi-check-circle"
              @click="testConnection"
              :loading="testing"
              :disabled="!apiKey"
            />
          </div>
        </div>

        <div v-else class="connected-info">
          <div class="info-grid">
            <div class="info-item">
              <span class="label">Server</span>
              <span class="value">{{ config.serverUrl }}</span>
            </div>
            <div class="info-item">
              <span class="label">API Key</span>
              <span class="value">{{ maskedKey }}</span>
            </div>
            <div class="info-item" v-if="userInfo">
              <span class="label">Account</span>
              <span class="value">{{ userInfo.email }}</span>
            </div>
            <div class="info-item" v-if="userInfo">
              <span class="label">Quota</span>
              <span class="value">{{ userInfo.llm_quota }} requests/hour</span>
            </div>
          </div>

          <div class="managed-keys" v-if="managedKeys.length">
            <h4>Available LLM Providers</h4>
            <div class="key-list">
              <div v-for="key in managedKeys" :key="key.provider" class="key-item">
                <i class="pi pi-check-circle" style="color: var(--green-500)"></i>
                <span>{{ key.display_name }}</span>
                <Tag severity="info" :value="key.model" size="small" />
              </div>
            </div>
          </div>

          <div class="actions">
            <Button
              label="Refresh"
              icon="pi pi-refresh"
              @click="refreshConnection"
              :loading="refreshing"
              class="p-button-secondary"
            />
          </div>

          <div class="env-notice small">
            <i class="pi pi-info-circle"></i>
            <span>To disconnect, remove <code>SPECTRASHERPA_API_KEY</code> from your environment.</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Mode Info -->
    <div class="section" v-if="appMode">
      <h3>Application Mode</h3>
      <div class="mode-panel">
        <div class="mode-info">
          <Tag :severity="modeSeverity" :value="modeLabel" size="large" />
          <p class="mode-description">{{ modeDescription }}</p>
        </div>
        <div class="mode-features" v-if="appMode === 'hybrid'">
          <div class="feature">
            <i class="pi pi-cloud"></i>
            <span>Managed LLM Keys</span>
          </div>
          <div class="feature">
            <i class="pi pi-sync"></i>
            <span>Cloud Sync</span>
          </div>
          <div class="feature">
            <i class="pi pi-server"></i>
            <span>Local Compute</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Connection Test Dialog -->
    <Dialog v-model:visible="showTestResult" header="Connection Test" modal :style="{ width: '400px' }">
      <div class="test-result">
        <div v-if="testResult?.success" class="success">
          <i class="pi pi-check-circle"></i>
          <div class="details">
            <p><strong>Connection successful!</strong></p>
            <p v-if="testResult.user">Logged in as: {{ testResult.user.email }}</p>
            <p v-if="testResult.keys?.length">{{ testResult.keys.length }} managed LLM provider(s) available</p>
          </div>
        </div>
        <div v-else class="error">
          <i class="pi pi-times-circle"></i>
          <div class="details">
            <p><strong>Connection failed</strong></p>
            <p>{{ testResult?.error || 'Unknown error' }}</p>
          </div>
        </div>
      </div>
      <template #footer>
        <Button label="Close" @click="showTestResult = false" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import api from '@/api/client';
import { useToast } from 'primevue/usetoast';
import { useAppConfig } from '@/composables/useAppConfig';

import InputText from 'primevue/inputtext';
import Button from 'primevue/button';
import Tag from 'primevue/tag';
import Dialog from 'primevue/dialog';

const toast = useToast();
const { appConfig, loadConfig } = useAppConfig();

// State
const serverUrl = ref('https://endpoint.spectrascientific.ai');
const apiKey = ref('');
const showKey = ref(false);
const testing = ref(false);
const refreshing = ref(false);
const connectionTested = ref(false);
const showTestResult = ref(false);
const testResult = ref<any>(null);

// Connection state
const config = ref<any>(null);
const userInfo = ref<any>(null);
const managedKeys = ref<any[]>([]);
const connectionStatus = ref<'connected' | 'disconnected' | 'error' | null>(null);

// Computed
const isConfigured = computed(() => config.value?.configured);

const maskedKey = computed(() => {
  if (!config.value?.apiKey) return '';
  // API now returns masked key directly
  return config.value.apiKey;
});

const appMode = computed(() => appConfig.value?.mode);

const connectionSeverity = computed(() => {
  if (connectionStatus.value === 'connected') return 'success';
  if (connectionStatus.value === 'error') return 'danger';
  return 'secondary';
});

const connectionLabel = computed(() => {
  if (connectionStatus.value === 'connected') return 'Connected';
  if (connectionStatus.value === 'error') return 'Error';
  return 'Not Connected';
});

const modeSeverity = computed(() => {
  if (appMode.value === 'hybrid') return 'info';
  if (appMode.value === 'demo') return 'warning';
  return 'secondary';
});

const modeLabel = computed(() => {
  const mode = appMode.value || 'local';
  return mode.charAt(0).toUpperCase() + mode.slice(1) + ' Mode';
});

const modeDescription = computed(() => {
  if (appMode.value === 'hybrid') {
    return 'Local compute with SpectraSherpa cloud for managed LLM keys and sync.';
  }
  if (appMode.value === 'demo') {
    return 'Cloud-hosted demonstration deployment.';
  }
  return 'Fully local deployment. Configure SpectraSherpa to enable hybrid mode.';
});

// Lifecycle
onMounted(async () => {
  await loadConfig();
  await loadConnectionState();
});

// Methods
const loadConnectionState = async () => {
  try {
    const response = await api.get('/config/spectrasherpa');
    config.value = response.data;

    if (config.value?.apiKey) {
      connectionStatus.value = 'connected';
      await refreshConnection();
    } else {
      connectionStatus.value = 'disconnected';
    }
  } catch (error) {
    connectionStatus.value = 'disconnected';
  }
};

const testConnection = async () => {
  testing.value = true;
  connectionTested.value = false;

  try {
    const response = await api.post('/config/spectrasherpa/test', {
      server_url: serverUrl.value,
      api_key: apiKey.value,
    });

    testResult.value = response.data;
    connectionTested.value = response.data.success;
    showTestResult.value = true;
  } catch (error: any) {
    testResult.value = {
      success: false,
      error: error.response?.data?.detail || 'Connection test failed',
    };
    showTestResult.value = true;
  } finally {
    testing.value = false;
  }
};

const refreshConnection = async () => {
  refreshing.value = true;

  try {
    // Get user info
    const userResponse = await api.get('/config/spectrasherpa/user');
    userInfo.value = userResponse.data;

    // Get managed keys
    const keysResponse = await api.get('/config/spectrasherpa/keys');
    managedKeys.value = keysResponse.data.keys || [];

    connectionStatus.value = 'connected';
  } catch (error) {
    connectionStatus.value = 'error';
    toast.add({
      severity: 'warn',
      summary: 'Warning',
      detail: 'Failed to refresh connection status',
      life: 3000,
    });
  } finally {
    refreshing.value = false;
  }
};

</script>

<style scoped>
.integrations-tab {
  padding: 1rem 0;
}

.section {
  margin-bottom: 2rem;
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
  margin-bottom: 1rem;
}

.connection-panel {
  background: var(--surface-card);
  border-radius: 12px;
  padding: 1.5rem;
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

.divider {
  display: flex;
  align-items: center;
  margin: 1.5rem 0;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--surface-border);
}

.divider span {
  padding: 0 1rem;
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
  gap: 0.75rem;
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--surface-border);
}

.mode-panel {
  background: var(--surface-card);
  border-radius: 12px;
  padding: 1.5rem;
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
</style>
