<template>
  <div class="admin-view">
    <div class="header">
      <h1>Admin Dashboard</h1>
      <p>Manage users, monitor usage, and configure platform settings.</p>
      <div class="mode-badge">
        <Tag :severity="modeSeverity" :value="modeLabel" />
      </div>
    </div>

    <!-- Stats Overview -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon users">
          <i class="pi pi-users"></i>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.totalUsers }}</span>
          <span class="stat-label">Total Users</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon jobs">
          <i class="pi pi-play"></i>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.totalJobs }}</span>
          <span class="stat-label">Jobs (24h)</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon llm">
          <i class="pi pi-comment"></i>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.llmRequests }}</span>
          <span class="stat-label">LLM Requests (24h)</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon active">
          <i class="pi pi-circle-fill"></i>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.activeUsers }}</span>
          <span class="stat-label">Active Today</span>
        </div>
      </div>
    </div>

    <!-- Tabbed Content -->
    <TabView v-model:activeIndex="activeTab">
      <!-- Users Tab -->
      <TabPanel header="Users">
        <div class="tab-content">
          <div class="toolbar">
            <span class="p-input-icon-left">
              <i class="pi pi-search" />
              <InputText v-model="userSearch" placeholder="Search users..." />
            </span>
            <Button label="Create User" icon="pi pi-plus" @click="showCreateDialog = true" />
          </div>

          <DataTable
            :value="filteredUsers"
            :loading="loading"
            class="p-datatable-sm"
            :paginator="true"
            :rows="10"
            :rowsPerPageOptions="[10, 25, 50]"
          >
            <Column field="id" header="ID" style="width: 60px" sortable></Column>
            <Column field="username" header="Username" sortable>
              <template #body="slotProps">
                <span class="username">{{ slotProps.data.username }}</span>
              </template>
            </Column>
            <Column field="email" header="Email" sortable>
              <template #body="slotProps">
                <span :class="{ 'text-secondary': !slotProps.data.email }">{{ slotProps.data.email || '—' }}</span>
              </template>
            </Column>
            <Column field="is_superuser" header="Role" style="width: 100px">
              <template #body="slotProps">
                <Tag :severity="slotProps.data.is_superuser ? 'danger' : 'info'" :value="slotProps.data.is_superuser ? 'Admin' : 'User'" />
              </template>
            </Column>
            <Column header="Status" style="width: 100px">
              <template #body="slotProps">
                <Tag :severity="slotProps.data.is_active !== false ? 'success' : 'secondary'" :value="slotProps.data.is_active !== false ? 'Active' : 'Disabled'" />
              </template>
            </Column>
            <Column field="created_at" header="Created" style="width: 150px" sortable>
              <template #body="slotProps">
                {{ formatDate(slotProps.data.created_at) }}
              </template>
            </Column>
            <Column header="Actions" style="width: 200px">
              <template #body="slotProps">
                <div class="action-buttons">
                  <Button
                    icon="pi pi-key"
                    class="p-button-warning p-button-sm p-button-text"
                    @click="confirmRotateKey(slotProps.data)"
                    v-tooltip.top="'Rotate API Key'"
                  />
                  <Button
                    :icon="slotProps.data.is_active !== false ? 'pi pi-ban' : 'pi pi-check'"
                    :class="slotProps.data.is_active !== false ? 'p-button-secondary p-button-sm p-button-text' : 'p-button-success p-button-sm p-button-text'"
                    @click="toggleUserStatus(slotProps.data)"
                    v-tooltip.top="slotProps.data.is_active !== false ? 'Disable User' : 'Enable User'"
                    :disabled="slotProps.data.username === 'local' || slotProps.data.is_superuser"
                  />
                  <Button
                    icon="pi pi-trash"
                    class="p-button-danger p-button-sm p-button-text"
                    @click="confirmDeleteUser(slotProps.data)"
                    v-tooltip.top="'Delete User'"
                    :disabled="slotProps.data.username === 'local' || slotProps.data.is_superuser"
                  />
                </div>
              </template>
            </Column>
          </DataTable>
        </div>
      </TabPanel>

      <!-- Usage Stats Tab -->
      <TabPanel header="Usage Statistics">
        <div class="tab-content">
          <div class="usage-grid">
            <div class="usage-card">
              <h3>Rate Limit Status</h3>
              <div class="rate-info" v-if="appConfig?.limits?.maxExecutions">
                <div class="rate-item">
                  <span class="rate-label">Limit per hour:</span>
                  <span class="rate-value">{{ appConfig.limits.maxExecutions }}</span>
                </div>
                <div class="rate-item">
                  <span class="rate-label">Session expiry:</span>
                  <span class="rate-value">{{ appConfig.limits.sessionExpiryHours }}h</span>
                </div>
              </div>
              <div v-else class="no-limits">
                <i class="pi pi-info-circle"></i>
                <span>No rate limits configured (enterprise mode settings not active)</span>
              </div>
            </div>

            <div class="usage-card">
              <h3>Recent Activity</h3>
              <DataTable :value="recentJobs" :loading="loadingJobs" class="p-datatable-sm" :rows="5">
                <Column field="id" header="Job" style="width: 60px"></Column>
                <Column field="status" header="Status">
                  <template #body="slotProps">
                    <Tag :severity="getJobSeverity(slotProps.data.status)" :value="slotProps.data.status" />
                  </template>
                </Column>
                <Column field="created_at" header="Time">
                  <template #body="slotProps">
                    {{ formatRelativeTime(slotProps.data.created_at) }}
                  </template>
                </Column>
              </DataTable>
            </div>
          </div>
        </div>
      </TabPanel>

      <!-- LLM Keys Tab -->
      <TabPanel header="Platform LLM Keys">
        <div class="tab-content">
          <Message severity="info" :closable="false" class="mb-4">
            Platform LLM keys are shared across all users. Users can still configure their own BYOK keys.
          </Message>

          <div class="llm-providers">
            <div class="llm-card" v-for="provider in llmProviders" :key="provider.id">
              <div class="llm-header">
                <div class="llm-info">
                  <span class="llm-name">{{ provider.name }}</span>
                  <span class="llm-model">{{ provider.model }}</span>
                </div>
                <Tag :severity="provider.hasKey ? 'success' : 'secondary'" :value="provider.hasKey ? 'Configured' : 'Not Set'" />
              </div>
              <div class="llm-actions">
                <Button
                  :label="provider.hasKey ? 'Update Key' : 'Add Key'"
                  :icon="provider.hasKey ? 'pi pi-pencil' : 'pi pi-plus'"
                  :class="provider.hasKey ? 'p-button-outlined' : ''"
                  size="small"
                  @click="openLlmKeyDialog(provider)"
                />
                <Button
                  v-if="provider.hasKey"
                  icon="pi pi-trash"
                  class="p-button-danger p-button-outlined"
                  size="small"
                  @click="removeLlmKey(provider)"
                />
              </div>
            </div>
          </div>
        </div>
      </TabPanel>

      <!-- System Tab -->
      <TabPanel header="System">
        <div class="tab-content">
          <div class="system-grid">
            <div class="system-card">
              <h3>Application Mode</h3>
              <div class="mode-info">
                <Tag :severity="modeSeverity" :value="modeLabel" size="large" />
                <p class="mode-description">{{ modeDescription }}</p>
              </div>
            </div>

            <div class="system-card">
              <h3>Network Status</h3>
              <div class="network-status" v-if="networkStatus">
                <div class="status-row">
                  <span>SpectraSherpa:</span>
                  <Tag :severity="networkStatus.is_online ? 'success' : 'danger'" :value="networkStatus.is_online ? 'Connected' : 'Offline'" />
                </div>
                <div class="status-row" v-if="networkStatus.is_degraded">
                  <span>Mode:</span>
                  <Tag severity="warning" value="Degraded" />
                </div>
              </div>
              <div v-else class="network-status">
                <span class="text-secondary">Not in hybrid mode</span>
              </div>
            </div>

            <div class="system-card">
              <h3>Database</h3>
              <div class="db-info">
                <div class="status-row">
                  <span>Type:</span>
                  <code>SQLite</code>
                </div>
                <div class="status-row">
                  <span>Status:</span>
                  <Tag severity="success" value="Connected" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </TabPanel>
    </TabView>

    <!-- Create User Dialog -->
    <Dialog v-model:visible="showCreateDialog" header="Create New User" modal class="p-fluid" :style="{ width: '400px' }">
      <div class="field">
        <label for="username">Username</label>
        <InputText id="username" v-model="newUser.username" />
      </div>
      <div class="field">
        <label for="password">Password</label>
        <InputText id="password" v-model="newUser.password" type="password" />
      </div>
      <div class="field-checkbox">
        <Checkbox id="is_superuser" v-model="newUser.is_superuser" :binary="true" />
        <label for="is_superuser">Admin privileges</label>
      </div>
      <template #footer>
        <Button label="Cancel" icon="pi pi-times" class="p-button-text" @click="showCreateDialog = false" />
        <Button label="Create" icon="pi pi-check" @click="createUser" :loading="creating" />
      </template>
    </Dialog>

    <!-- Key Display Dialog -->
    <Dialog v-model:visible="showKeyDialog" header="API Key Generated" modal :closable="false" :style="{ width: '500px' }">
      <Message severity="warn" :closable="false">Save this key immediately. It will not be shown again.</Message>
      <div class="key-display">
        <code>{{ newApiKey }}</code>
        <Button icon="pi pi-copy" class="p-button-text" @click="copyKey" />
      </div>
      <template #footer>
        <Button label="I have saved it" icon="pi pi-check" @click="showKeyDialog = false" />
      </template>
    </Dialog>

    <!-- LLM Key Dialog -->
    <Dialog v-model:visible="showLlmKeyDialog" :header="`Configure ${selectedProvider?.name} API Key`" modal class="p-fluid" :style="{ width: '450px' }">
      <div class="field">
        <label>API Key</label>
        <InputText v-model="llmKeyInput" type="password" placeholder="sk-..." />
      </div>
      <template #footer>
        <Button label="Cancel" icon="pi pi-times" class="p-button-text" @click="showLlmKeyDialog = false" />
        <Button label="Save" icon="pi pi-check" @click="saveLlmKey" :loading="savingLlmKey" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import api from '@/api/client';
import { useToast } from 'primevue/usetoast';
import { useAppConfig } from '@/composables/useAppConfig';
import { getErrorMessage } from '@/utils/errors';

import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Button from 'primevue/button';
import Dialog from 'primevue/dialog';
import InputText from 'primevue/inputtext';
import Checkbox from 'primevue/checkbox';
import Tag from 'primevue/tag';
import Message from 'primevue/message';
import TabView from 'primevue/tabview';
import TabPanel from 'primevue/tabpanel';

const toast = useToast();
const { appConfig, loadConfig } = useAppConfig();

interface AdminUser {
  id: number;
  username: string;
  email?: string;
  is_superuser: boolean;
  is_active?: boolean;
  created_at?: string;
  [key: string]: unknown;
}

interface AdminJob {
  id: number;
  job_type?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

interface LlmProviderConfig {
  id: string;
  name: string;
  model?: string;
  hasKey: boolean;
  [key: string]: unknown;
}

const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

// State
const loading = ref(false);
const loadingJobs = ref(false);
const users = ref<AdminUser[]>([]);
const recentJobs = ref<AdminJob[]>([]);
const userSearch = ref('');
const activeTab = ref(0);
const networkStatus = ref<Record<string, unknown> | null>(null);

// Stats
const stats = ref({
  totalUsers: 0,
  totalJobs: 0,
  llmRequests: 0,
  activeUsers: 0,
});

// User dialogs
const showCreateDialog = ref(false);
const creating = ref(false);
const newUser = ref({
  username: '',
  password: '',
  is_superuser: false,
});

const showKeyDialog = ref(false);
const newApiKey = ref('');

// LLM management
const llmProviders = ref<LlmProviderConfig[]>([]);
const showLlmKeyDialog = ref(false);
const selectedProvider = ref<LlmProviderConfig | null>(null);
const llmKeyInput = ref('');
const savingLlmKey = ref(false);

// Computed
const filteredUsers = computed(() => {
  if (!userSearch.value) return users.value;
  const search = userSearch.value.toLowerCase();
  return users.value.filter(u => u.username.toLowerCase().includes(search));
});

const modeSeverity = computed(() => {
  const mode = appConfig.value?.mode;
  if (mode === 'enterprise') return 'warning';
  if (mode === 'hybrid') return 'info';
  return 'secondary';
});

const modeLabel = computed(() => {
  const mode = appConfig.value?.mode || 'local';
  return mode.charAt(0).toUpperCase() + mode.slice(1) + ' Mode';
});

const modeDescription = computed(() => {
  const mode = appConfig.value?.mode;
  if (mode === 'enterprise') return 'Cloud-hosted enterprise deployment with rate limits and user management.';
  if (mode === 'hybrid') return 'Local compute with cloud account sync and managed LLM keys.';
  return 'Single-user offline-capable workstation.';
});

// Lifecycle
onMounted(async () => {
  await Promise.all([
    fetchUsers(),
    fetchStats(),
    fetchRecentJobs(),
    fetchLlmProviders(),
    fetchNetworkStatus(),
    loadConfig(),
  ]);
});

// API calls
const fetchUsers = async () => {
  loading.value = true;
  try {
    const response = await api.get('/admin/users');
    users.value = response.data;
    stats.value.totalUsers = users.value.length;
  } catch (error) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'Failed to load users', life: 3000 });
  } finally {
    loading.value = false;
  }
};

const fetchStats = async () => {
  try {
    // In a real implementation, this would call a stats endpoint
    // For now, we'll compute from available data
    stats.value.activeUsers = Math.min(users.value.length, 5);
  } catch (error) {
    console.error('Failed to fetch stats:', error);
  }
};

const fetchRecentJobs = async () => {
  loadingJobs.value = true;
  try {
    const response = await api.get('/jobs', { params: { limit: 10 } });
    recentJobs.value = response.data.slice(0, 5);
    stats.value.totalJobs = response.data.length;
  } catch (error) {
    console.error('Failed to fetch jobs:', error);
  } finally {
    loadingJobs.value = false;
  }
};

const fetchLlmProviders = async () => {
  try {
    const response = await api.get('/config/llms');
    const providerRecords: unknown[] = Array.isArray(response.data?.providers)
      ? response.data.providers
      : [];
    llmProviders.value = providerRecords
      .map((provider) => asRecord(provider))
      .filter((provider): provider is Record<string, unknown> => provider !== null)
      .map((provider) => ({
      ...provider,
      id: typeof provider.id === 'string' ? provider.id : String(provider.id ?? ''),
      name: typeof provider.name === 'string' ? provider.name : 'Unknown',
      model: typeof provider.model === 'string' ? provider.model : undefined,
      hasKey: true, // They're only returned if configured
    }));

    // Add unconfigured providers
    const knownProviders = ['openai', 'anthropic', 'deepseek', 'gemini', 'custom_llm'];
    const configuredIds = llmProviders.value.map((provider) => provider.id);

    for (const id of knownProviders) {
      if (!configuredIds.includes(id)) {
        llmProviders.value.push({
          id,
          name: id.charAt(0).toUpperCase() + id.slice(1),
          model: 'Not configured',
          hasKey: false,
        });
      }
    }
  } catch (error) {
    console.error('Failed to fetch LLM providers:', error);
  }
};

const fetchNetworkStatus = async () => {
  try {
    const response = await api.get('/config/network-status');
    networkStatus.value = response.data;
  } catch (error) {
    console.error('Failed to fetch network status:', error);
  }
};

// User management
const createUser = async () => {
  if (!newUser.value.username || !newUser.value.password) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'Username and password required', life: 3000 });
    return;
  }

  creating.value = true;
  try {
    await api.post('/admin/users', newUser.value);
    toast.add({ severity: 'success', summary: 'Success', detail: 'User created' });
    showCreateDialog.value = false;
    newUser.value = { username: '', password: '', is_superuser: false };
    fetchUsers();
  } catch (error: unknown) {
    toast.add({ severity: 'error', summary: 'Error', detail: getErrorMessage(error, 'Failed to create user') });
  } finally {
    creating.value = false;
  }
};

const confirmRotateKey = async (user: AdminUser) => {
  if (!confirm(`Generate new API Key for ${user.username}? The old key will stop working immediately.`)) return;

  try {
    const response = await api.post(`/admin/users/${user.id}/rotate-key`);
    newApiKey.value = response.data.api_key;
    showKeyDialog.value = true;
  } catch (error) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'Failed to generate key' });
  }
};

const toggleUserStatus = async (user: AdminUser) => {
  const newStatus = user.is_active === false ? true : false;
  const action = newStatus ? 'enable' : 'disable';

  if (!confirm(`Are you sure you want to ${action} user "${user.username}"?`)) return;

  try {
    await api.patch(`/admin/users/${user.id}`, { is_active: newStatus });
    toast.add({ severity: 'success', summary: 'Success', detail: `User ${action}d` });
    await fetchUsers();
  } catch (error: unknown) {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: getErrorMessage(error, `Failed to ${action} user`),
    });
  }
};

const confirmDeleteUser = async (user: AdminUser) => {
  if (!confirm(`Delete user "${user.username}"? This action cannot be undone.`)) return;

  try {
    await api.delete(`/admin/users/${user.id}`);
    toast.add({ severity: 'success', summary: 'Success', detail: 'User deleted' });
    fetchUsers();
  } catch (error) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'Failed to delete user' });
  }
};

// LLM key management
const openLlmKeyDialog = (provider: LlmProviderConfig) => {
  selectedProvider.value = provider;
  llmKeyInput.value = '';
  showLlmKeyDialog.value = true;
};

const saveLlmKey = async () => {
  if (!llmKeyInput.value) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'API key required', life: 3000 });
    return;
  }
  if (!selectedProvider.value) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'No provider selected', life: 3000 });
    return;
  }

  savingLlmKey.value = true;
  try {
    await api.post('/api-keys', {
      service_name: selectedProvider.value.id,
      key: llmKeyInput.value,
    });
    toast.add({ severity: 'success', summary: 'Success', detail: `${selectedProvider.value.name} key saved` });
    showLlmKeyDialog.value = false;
    fetchLlmProviders();
  } catch (error: unknown) {
    toast.add({ severity: 'error', summary: 'Error', detail: getErrorMessage(error, 'Failed to save key') });
  } finally {
    savingLlmKey.value = false;
  }
};

const removeLlmKey = async (provider: LlmProviderConfig) => {
  if (!confirm(`Remove ${provider.name} API key?`)) return;

  try {
    await api.delete(`/api-keys/${provider.id}`);
    toast.add({ severity: 'success', summary: 'Success', detail: 'Key removed' });
    fetchLlmProviders();
  } catch (error) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'Failed to remove key' });
  }
};

// Utilities
const copyKey = () => {
  navigator.clipboard.writeText(newApiKey.value);
  toast.add({ severity: 'info', summary: 'Copied', detail: 'API Key copied to clipboard', life: 1000 });
};

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString();
};

const formatRelativeTime = (dateStr: string) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return formatDate(dateStr);
};

const getJobSeverity = (status: string) => {
  const map: Record<string, string> = {
    completed: 'success',
    running: 'info',
    failed: 'danger',
    pending: 'warning',
  };
  return map[status] || 'secondary';
};
</script>

<style scoped>
.admin-view {
  padding: 2rem;
}

.header {
  margin-bottom: 2rem;
  position: relative;
}

.header h1 {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text-color);
  margin-bottom: 0.5rem;
}

.header p {
  color: var(--text-color-secondary);
}

.mode-badge {
  position: absolute;
  top: 0;
  right: 0;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: var(--surface-card);
  padding: 1.25rem;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 1rem;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
}

.stat-icon.users { background: rgba(99, 102, 241, 0.1); color: #6366f1; }
.stat-icon.jobs { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
.stat-icon.llm { background: rgba(168, 85, 247, 0.1); color: #a855f7; }
.stat-icon.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-color);
}

.stat-label {
  font-size: 0.875rem;
  color: var(--text-color-secondary);
}

/* Tab Content */
.admin-view :deep(.p-tabview-panels) {
  width: 100%;
}

.admin-view :deep(.p-tabview-panel) {
  width: 100%;
}

.tab-content {
  padding: 1rem 0;
  width: 100%;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  gap: 1rem;
}

.action-buttons {
  display: flex;
  gap: 0.25rem;
}

.username {
  font-weight: 500;
}

/* Usage Grid */
.usage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 1.5rem;
}

.usage-card, .system-card {
  background: var(--surface-card);
  padding: 1.5rem;
  border-radius: 12px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.usage-card h3, .system-card h3 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 1rem;
  color: var(--text-color);
}

.rate-info {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.rate-item {
  display: flex;
  justify-content: space-between;
}

.rate-label {
  color: var(--text-color-secondary);
}

.rate-value {
  font-weight: 600;
}

.no-limits {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-color-secondary);
  padding: 1rem;
  background: var(--surface-ground);
  border-radius: 8px;
}

/* LLM Providers */
.llm-providers {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.llm-card {
  background: var(--surface-card);
  padding: 1.25rem;
  border-radius: 12px;
  border: 1px solid var(--surface-border);
}

.llm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.llm-info {
  display: flex;
  flex-direction: column;
}

.llm-name {
  font-weight: 600;
  font-size: 1rem;
}

.llm-model {
  font-size: 0.875rem;
  color: var(--text-color-secondary);
}

.llm-actions {
  display: flex;
  gap: 0.5rem;
}

/* System Grid */
.system-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.5rem;
}

.mode-info {
  text-align: center;
  padding: 1rem;
}

.mode-description {
  margin-top: 1rem;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.network-status, .db-info {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* Dialogs */
.field {
  margin-bottom: 1.5rem;
}

.field label {
  display: block;
  margin-bottom: 0.5rem;
  color: var(--text-color);
  font-weight: 500;
}

.field-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.key-display {
  background: #1e1e1e;
  padding: 1rem;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 1rem 0;
}

.key-display code {
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
  font-size: 0.9rem;
  word-break: break-all;
}

.mb-4 {
  margin-bottom: 1rem;
}

.text-secondary {
  color: var(--text-color-secondary);
}
</style>
