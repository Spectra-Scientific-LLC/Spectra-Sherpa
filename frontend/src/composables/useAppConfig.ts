/**
 * Application configuration composable
 *
 * Provides access to app configuration and mode-dependent features
 */

import { ref, computed, readonly } from 'vue'
import type { AppConfig } from '@/types/config'
import { api } from '@/api'

const config = ref<AppConfig | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

/**
 * Load configuration from backend
 *
 * @param force - Force reload even if config already loaded
 */
async function loadConfig(force = false): Promise<void> {
  if (config.value && !force) return // Already loaded

  loading.value = true
  error.value = null

  try {
    const response = await api.get<AppConfig>('/config')
    config.value = response.data
  } catch (err: any) {
    error.value = err.message || 'Failed to load configuration'
    console.error('Config load error:', err)

    // Fallback to default local config
    config.value = {
      mode: 'local',
      apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1',
      features: {
        apiTokenSettings: true,
        cloudOffload: false,
        demoMode: false,
        agenticWorkflow: false,
        chatAssistant: false,
        sherpaAdvisor: false,
        pluginSystem: true,
        nistDownloads: false,
      },
      llms: {
        openai: { provider: 'openai', model: 'gpt-4o', enabled: false },
        anthropic: { provider: 'anthropic', model: 'claude-3-5-sonnet-20241022', enabled: false },
        deepseek: { provider: 'deepseek', model: 'deepseek-chat', enabled: false },
        gemini: { provider: 'gemini', model: 'gemini-1.5-pro', enabled: false },
      },
    }
  } finally {
    loading.value = false
  }
}

/**
 * Force reload configuration from backend
 *
 * Use this after making changes that affect configuration
 * (e.g., adding API keys, changing providers)
 */
async function reloadConfig(): Promise<void> {
  return loadConfig(true)
}

/**
 * Get list of configured LLM providers
 */
const configuredLLMs = computed(() => {
  if (!config.value) return []
  return Object.entries(config.value.llms)
    .filter(([_, llm]) => llm.enabled)
    .map(([name, llm]) => ({ name, ...llm }))
})

/**
 * Check if any LLM is configured
 */
const hasLLMConfigured = computed(() => {
  return configuredLLMs.value.length > 0
})

/**
 * Get current app mode
 */
const appMode = computed(() => config.value?.mode || 'local')

/**
 * Check if specific feature is enabled
 */
function isFeatureEnabled(feature: keyof AppConfig['features']): boolean {
  return config.value?.features[feature] || false
}

/**
 * Format provider name for display
 */
function formatProviderName(provider: string): string {
  const names: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic (Claude)',
    deepseek: 'DeepSeek',
    gemini: 'Google Gemini',
  }
  return names[provider] || provider
}

export function useAppConfig() {
  return {
    config: readonly(config),
    appConfig: readonly(config),  // backward-compatible alias
    loading: readonly(loading),
    error: readonly(error),
    loadConfig,
    reloadConfig,  // NEW: Force reload config
    configuredLLMs,
    hasLLMConfigured,
    appMode,
    isFeatureEnabled,
    formatProviderName,
  }
}
