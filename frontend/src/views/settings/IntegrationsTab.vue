<template>
  <div class="integrations-tab">
    <div class="section">
      <div class="section-header">
        <h3>SpectraSherpa Cloud</h3>
        <Tag v-if="connectionStatus" :severity="connectionSeverity" :value="connectionLabel" />
      </div>
      <p class="muted-text">
        Connect to SpectraSherpa for managed LLM keys, cloud sync, and hybrid identity linking.
      </p>

      <div class="connection-panel">
        <div v-if="!isConfigured" class="setup-form">
          <div class="field">
            <label for="server-url">Server URL</label>
            <InputText
              id="server-url"
              v-model="serverUrl"
              placeholder="https://your-server.example.com"
              :disabled="testing || connecting || modeSwitchLocked"
            />
          </div>

          <div class="field">
            <label for="api-key">API Key</label>
            <div class="p-inputgroup">
              <InputText
                id="api-key"
                v-model="apiKey"
                :type="showKey ? 'text' : 'password'"
                placeholder="ss_..."
                :disabled="testing || connecting || modeSwitchLocked"
              />
              <Button
                :icon="showKey ? 'pi pi-eye-slash' : 'pi pi-eye'"
                @click="showKey = !showKey"
                class="p-button-secondary"
                :disabled="testing || connecting || modeSwitchLocked"
              />
            </div>
            <small class="help-text">
              The server host must be in the allowlist (set via <code>SPECTRASHERPA_ALLOWED_HOSTS</code> env var).
            </small>
          </div>

          <div class="actions">
            <Button
              label="Test Connection"
              icon="pi pi-check-circle"
              @click="testConnection"
              :loading="testing"
              :disabled="!canSubmitCredentials || modeSwitchLocked"
              class="p-button-secondary"
            />
            <Button
              label="Connect & Enable Hybrid"
              icon="pi pi-cloud"
              @click="activateHybrid"
              :loading="connecting"
              :disabled="!canSubmitCredentials || modeSwitchLocked"
              class="p-button-success"
            />
          </div>

          <div v-if="modeSwitchLocked" class="env-notice small">
            <i class="pi pi-lock"></i>
            <span>Mode switching is disabled in enterprise mode.</span>
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
            <div class="info-item" v-if="userInfo?.email">
              <span class="label">Account</span>
              <span class="value">{{ userInfo.email }}</span>
            </div>
            <div class="info-item" v-if="typeof userInfo?.llm_quota === 'number'">
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
            <Button
              label="Disconnect & Return Local"
              icon="pi pi-power-off"
              @click="deactivateHybrid"
              :loading="disconnecting"
              :disabled="modeSwitchLocked"
              class="p-button-danger"
            />
          </div>

          <div v-if="modeSwitchLocked" class="env-notice small">
            <i class="pi pi-lock"></i>
            <span>Disconnect is disabled in enterprise mode.</span>
          </div>
        </div>
      </div>
    </div>

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

    <Dialog v-model:visible="showTestResult" header="Connection Test" modal :style="{ width: '420px' }">
      <div class="test-result">
        <div v-if="testResult?.success" class="success">
          <i class="pi pi-check-circle"></i>
          <div class="details">
            <p><strong>Connection successful!</strong></p>
            <p v-if="testResult.user">Logged in as: {{ testResult.user.email || testResult.user.username }}</p>
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

const serverUrl = ref('');
const apiKey = ref('');
const showKey = ref(false);
const testing = ref(false);
const connecting = ref(false);
const disconnecting = ref(false);
const refreshing = ref(false);
const showTestResult = ref(false);
const testResult = ref<any>(null);

const config = ref<any>(null);
const userInfo = ref<any>(null);
const managedKeys = ref<any[]>([]);
const connectionStatus = ref<'connected' | 'disconnected' | 'error' | null>(null);

const isConfigured = computed(() => Boolean(config.value?.configured));
const canSubmitCredentials = computed(() => Boolean(serverUrl.value.trim() && apiKey.value.trim()));
const appMode = computed(() => appConfig.value?.mode);
const modeSwitchLocked = computed(() => appMode.value === 'enterprise');

const maskedKey = computed(() => {
  if (!config.value?.apiKey) return '';
  return config.value.apiKey;
});

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
  if (appMode.value === 'enterprise') return 'warning';
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
  if (appMode.value === 'enterprise') {
    return 'Cloud-hosted enterprise deployment with full auth and rate limits.';
  }
  return 'Fully local deployment. Connect SpectraSherpa to enable hybrid mode.';
});

onMounted(async () => {
  await loadConfig();
  await loadConnectionState();
});

const loadConnectionState = async () => {
  try {
    const response = await api.get('/config/spectrasherpa');
    config.value = response.data;

    if (config.value?.configured) {
      connectionStatus.value = 'connected';
      await refreshConnection();
      return;
    }

    userInfo.value = null;
    managedKeys.value = [];
    connectionStatus.value = 'disconnected';
  } catch {
    userInfo.value = null;
    managedKeys.value = [];
    connectionStatus.value = 'disconnected';
  }
};

const testConnection = async () => {
  testing.value = true;
  try {
    const response = await api.post('/config/spectrasherpa/test', {
      server_url: serverUrl.value.trim(),
      api_key: apiKey.value.trim(),
    });

    testResult.value = response.data;
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

const activateHybrid = async () => {
  connecting.value = true;
  try {
    const response = await api.post('/config/activate-hybrid', {
      server_url: serverUrl.value.trim(),
      api_key: apiKey.value.trim(),
    });

    apiKey.value = '';
    await loadConfig();
    await loadConnectionState();

    toast.add({
      severity: 'success',
      summary: 'Hybrid Enabled',
      detail: response.data?.secret_key_generated
        ? 'Hybrid mode activated. SECRET_KEY was generated and persisted.'
        : 'Hybrid mode activated successfully.',
      life: 3500,
    });
  } catch (error: any) {
    connectionStatus.value = 'error';
    toast.add({
      severity: 'error',
      summary: 'Activation Failed',
      detail: error.response?.data?.detail || 'Unable to activate hybrid mode.',
      life: 4500,
    });
  } finally {
    connecting.value = false;
  }
};

const deactivateHybrid = async () => {
  if (!window.confirm('Disconnect SpectraSherpa and return to local mode?')) {
    return;
  }

  disconnecting.value = true;
  try {
    await api.post('/config/deactivate-hybrid');

    await loadConfig();
    await loadConnectionState();

    toast.add({
      severity: 'success',
      summary: 'Disconnected',
      detail: 'Hybrid mode disabled. Running in local mode.',
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: 'error',
      summary: 'Disconnect Failed',
      detail: error.response?.data?.detail || 'Unable to disable hybrid mode.',
      life: 4500,
    });
  } finally {
    disconnecting.value = false;
  }
};

const refreshConnection = async () => {
  refreshing.value = true;
  try {
    const userResponse = await api.get('/config/spectrasherpa/user');
    userInfo.value = userResponse.data?.error ? null : userResponse.data;

    const keysResponse = await api.get('/config/spectrasherpa/keys');
    managedKeys.value = Array.isArray(keysResponse.data?.keys) ? keysResponse.data.keys : [];

    connectionStatus.value = 'connected';
  } catch {
    userInfo.value = null;
    managedKeys.value = [];
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
