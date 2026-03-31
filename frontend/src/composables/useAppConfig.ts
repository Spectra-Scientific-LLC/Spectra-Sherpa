/**
 * Application configuration composable
 *
 * Provides access to app configuration and mode-dependent features
 */

import { ref, computed, readonly } from 'vue'
import axios from 'axios'
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
async function loadConfig(force = false): Promise<boolean> {
  if (config.value && !force) return true // Already loaded

  loading.value = true
  error.value = null

  try {
    const response = await api.get<AppConfig>('/config')
    config.value = response.data
    return true
  } catch (err: unknown) {
    error.value = axios.isAxiosError(err) ? err.message : 'Failed to load configuration'
    console.error('Config load error:', err)
    config.value = null
    return false
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
async function reloadConfig(): Promise<boolean> {
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
const appMode = computed(() => config.value?.mode || 'enterprise')

/**
 * Get site profile (marketing label, independent of runtime mode)
 */
const siteProfile = computed(() => config.value?.siteProfile || null)

/**
 * Check if network egress is globally enabled
 */
const egressEnabled = computed(() => config.value?.egressEnabled ?? false)

/**
 * Check if user self-registration is available
 */
const registrationEnabled = computed(() => config.value?.registrationEnabled ?? false)

/**
 * Check if registration requires an access code header
 */
const registrationRequiresCode = computed(() => config.value?.registrationRequiresCode ?? false)

/**
 * Config delivery status for degraded server-backed modes.
 */
const configStatus = computed(() => config.value?.configStatus ?? 'ok')

/**
 * Machine-readable config load degradation reason from the backend.
 */
const configError = computed(() => config.value?.configError ?? null)

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
    siteProfile,
    egressEnabled,
    registrationEnabled,
    registrationRequiresCode,
    configStatus,
    configError,
    isFeatureEnabled,
    formatProviderName,
  }
}
