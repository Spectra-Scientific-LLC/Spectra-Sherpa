<template>
  <div class="api-tokens-settings">
    <div class="settings-header">
      <h2>API Token Configuration</h2>
      <p class="description">
        Configure API keys for LLM-powered features (workflow generation, chat assistant).
        Tokens are stored locally in your browser.
      </p>
    </div>

    <div v-if="!appConfig" class="loading-state">
      <ProgressSpinner style="width: 30px; height: 30px" />
      <span>Loading configuration...</span>
    </div>

    <div v-else class="llm-configs">
      <div
        v-for="(llm, name) in appConfig.llms"
        :key="name"
        class="llm-config-card"
      >
        <div class="llm-header">
          <div class="llm-title">
            <i :class="getProviderIcon(name)" class="provider-icon" />
            <h3>{{ formatProviderName(name) }}</h3>
          </div>
          <Tag :severity="getTokenStatus(name).severity">
            {{ getTokenStatus(name).label }}
          </Tag>
        </div>

        <div class="llm-info">
          <div class="info-row">
            <span class="label">Model:</span>
            <span class="value">{{ llm.model }}</span>
          </div>
          <div class="info-row">
            <span class="label">Backend Status:</span>
            <Tag :severity="llm.enabled ? 'success' : 'secondary'" size="small">
              {{ llm.enabled ? 'Configured' : 'Not Configured' }}
            </Tag>
          </div>
        </div>

        <div class="token-input-section">
          <label :for="`token-${name}`">API Key:</label>
          <div class="input-with-actions">
            <Password
              :id="`token-${name}`"
              v-model="tokenInputs[name]"
              :feedback="false"
              toggleMask
              :placeholder="hasToken(name) ? '••••••••••••••••' : 'sk-...'"
              class="token-input"
              @keydown.enter="saveToken(name)"
            />
            <Button
              icon="pi pi-check"
              label="Save"
              size="small"
              @click="saveToken(name)"
              :disabled="!tokenInputs[name]"
            />
          </div>
        </div>

        <div class="actions">
          <Button
            v-if="hasToken(name)"
            icon="pi pi-times"
            label="Clear Local Token"
            severity="secondary"
            size="small"
            outlined
            @click="clearToken(name)"
          />
          <Button
            icon="pi pi-send"
            label="Send to Backend"
            severity="info"
            size="small"
            @click="sendToBackend(name)"
            :disabled="!hasToken(name)"
            :loading="sending[name]"
          />
          <Button
            icon="pi pi-bolt"
            label="Test Connection"
            severity="success"
            size="small"
            outlined
            @click="testConnection(name)"
            :disabled="!llm.enabled && !hasToken(name)"
            :loading="testing[name]"
          />
        </div>

        <Message v-if="statusMessages[name]" :severity="statusMessages[name].severity" :closable="false">
          {{ statusMessages[name].text }}
        </Message>
      </div>
    </div>

    <Divider />

    <div class="danger-zone">
      <h3>Danger Zone</h3>
      <Button
        icon="pi pi-trash"
        label="Clear All Local Tokens"
        severity="danger"
        outlined
        @click="confirmClearAll"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import Button from 'primevue/button'
import Password from 'primevue/password'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'
import Message from 'primevue/message'
import Divider from 'primevue/divider'

import { useAppConfig } from '@/composables/useAppConfig'
import type { LLMProvider } from '@/types/config'
import { getErrorMessage } from '@/utils/errors'
import {
  saveToken as saveTokenToStorage,
  loadToken as loadTokenFromStorage,
  clearToken as clearTokenFromStorage,
  hasToken as hasTokenInStorage,
  clearAllTokens,
} from '@/utils/tokenStorage'
import { api } from '@/api'

const toast = useToast()
const confirm = useConfirm()
const { config: appConfig, formatProviderName, loadConfig, reloadConfig } = useAppConfig()

const tokenInputs = reactive<Record<string, string>>({})
const sending = reactive<Record<string, boolean>>({})
const testing = reactive<Record<string, boolean>>({})
const statusMessages = reactive<Record<string, { severity: string; text: string }>>({})

onMounted(async () => {
  await loadConfig()
})

function getProviderIcon(provider: string): string {
  const icons: Record<string, string> = {
    openai: 'pi pi-box',
    anthropic: 'pi pi-sparkles',
    deepseek: 'pi pi-search',
    gemini: 'pi pi-star',
  }
  return icons[provider] || 'pi pi-cog'
}

function hasToken(provider: string): boolean {
  return hasTokenInStorage(provider as LLMProvider)
}

function getTokenStatus(provider: string) {
  const localToken = hasToken(provider as LLMProvider)
  const backendConfigured = appConfig.value?.llms[provider]?.enabled || false

  if (backendConfigured) {
    return { label: 'Backend Configured', severity: 'success' }
  } else if (localToken) {
    return { label: 'Locally Saved', severity: 'info' }
  } else {
    return { label: 'Not Configured', severity: 'secondary' }
  }
}

function saveToken(provider: string) {
  const token = tokenInputs[provider]
  if (!token) {
    toast.add({
      severity: 'warn',
      summary: 'No Token',
      detail: 'Please enter an API key',
      life: 3000,
    })
    return
  }

  try {
    saveTokenToStorage(provider as LLMProvider, token)
    tokenInputs[provider] = ''

    toast.add({
      severity: 'success',
      summary: 'Token Saved',
      detail: `${formatProviderName(provider)} API key saved locally`,
      life: 3000,
    })

    statusMessages[provider] = {
      severity: 'success',
      text: 'Token saved to browser storage. Click "Send to Backend" to use it.',
    }
  } catch (error: unknown) {
    toast.add({
      severity: 'error',
      summary: 'Save Failed',
      detail: getErrorMessage(error, 'Failed to save token'),
      life: 5000,
    })
  }
}

function clearToken(provider: string) {
  clearTokenFromStorage(provider as LLMProvider)

  toast.add({
    severity: 'info',
    summary: 'Token Cleared',
    detail: `${formatProviderName(provider)} local token removed`,
    life: 3000,
  })

  delete statusMessages[provider]
}

async function sendToBackend(provider: string) {
  const token = loadTokenFromStorage(provider as LLMProvider)
  if (!token) {
    toast.add({
      severity: 'warn',
      summary: 'No Token',
      detail: 'No local token found',
      life: 3000,
    })
    return
  }

  sending[provider] = true
  delete statusMessages[provider]

  try {
    await api.post('/api-keys', {
      service_name: provider,
      key: token,
      description: `${formatProviderName(provider)} API Key`,
    })

    toast.add({
      severity: 'success',
      summary: 'Token Sent',
      detail: `${formatProviderName(provider)} API key configured on backend`,
      life: 3000,
    })

    // Force reload config to update enabled status with database check
    await reloadConfig()

    statusMessages[provider] = {
      severity: 'success',
      text: 'Token configured on backend. You can now use this LLM provider.',
    }
  } catch (error: unknown) {
    const errorMessage = getErrorMessage(error, 'Failed to send token')
    toast.add({
      severity: 'error',
      summary: 'Send Failed',
      detail: errorMessage,
      life: 5000,
    })

    statusMessages[provider] = {
      severity: 'error',
      text: `Failed to send token: ${errorMessage}`,
    }
  } finally {
    sending[provider] = false
  }
}

async function testConnection(provider: string) {
  testing[provider] = true
  delete statusMessages[provider]

  try {
    await api.get(`/llm/test?provider=${provider}`)

    toast.add({
      severity: 'success',
      summary: 'Connection Successful',
      detail: `${formatProviderName(provider)} API is working correctly`,
      life: 3000,
    })

    statusMessages[provider] = {
      severity: 'success',
      text: 'Connection test passed!',
    }
  } catch (error: unknown) {
    const errorMessage = getErrorMessage(error, 'Check your API key and try again')
    toast.add({
      severity: 'error',
      summary: 'Connection Failed',
      detail: errorMessage,
      life: 5000,
    })

    statusMessages[provider] = {
      severity: 'error',
      text: `Connection test failed: ${errorMessage}`,
    }
  } finally {
    testing[provider] = false
  }
}

function confirmClearAll() {
  confirm.require({
    message: 'Are you sure you want to clear all local API tokens?',
    header: 'Clear All Tokens',
    icon: 'pi pi-exclamation-triangle',
    accept: () => {
      clearAllTokens()
      Object.keys(statusMessages).forEach((key) => delete statusMessages[key])

      toast.add({
        severity: 'info',
        summary: 'Tokens Cleared',
        detail: 'All local API tokens have been removed',
        life: 3000,
      })
    },
  })
}
</script>

<style scoped>
.api-tokens-settings {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem;
}

.settings-header {
  margin-bottom: 2rem;
}

.settings-header h2 {
  font-size: 1.75rem;
  margin-bottom: 0.5rem;
  color: var(--text-color);
}

.description {
  color: var(--text-color-secondary);
  line-height: 1.6;
}

.loading-state {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 2rem;
  justify-content: center;
}

.llm-configs {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.llm-config-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.llm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.llm-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.provider-icon {
  font-size: 1.5rem;
  color: var(--primary-color);
}

.llm-title h3 {
  margin: 0;
  font-size: 1.25rem;
}

.llm-info {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  background: var(--surface-ground);
  border-radius: 6px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.info-row .label {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.info-row .value {
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
}

.token-input-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.token-input-section label {
  font-weight: 600;
  font-size: 0.875rem;
}

.input-with-actions {
  display: flex;
  gap: 0.5rem;
}

.token-input {
  flex: 1;
}

.actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.danger-zone {
  padding: 1.5rem;
  border: 1px solid var(--red-500);
  border-radius: 8px;
  background: var(--surface-card);
}

.danger-zone h3 {
  margin-top: 0;
  margin-bottom: 1rem;
  color: var(--red-500);
}
</style>
