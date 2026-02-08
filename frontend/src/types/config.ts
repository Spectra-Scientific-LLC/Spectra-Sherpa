/**
 * Application configuration types
 *
 * These types match the backend AppConfig structure
 */

export type AppMode = 'local' | 'hybrid' | 'demo'

export type LLMProvider = 'openai' | 'anthropic' | 'deepseek' | 'gemini'

export interface LLMConfig {
  provider: LLMProvider
  model: string
  enabled: boolean
}

export interface AppFeatures {
  apiTokenSettings: boolean
  cloudOffload: boolean
  demoMode: boolean
  agenticWorkflow: boolean
  chatAssistant: boolean
  sherpaAdvisor?: boolean
  pluginSystem?: boolean
  nistDownloads?: boolean
}

export interface AppLimits {
  maxExecutions?: number
  maxFileSizeMB: number
  sessionExpiryHours?: number
}

export interface AppConfig {
  mode: AppMode
  apiBaseUrl: string
  features: AppFeatures
  llms: Record<string, LLMConfig>
  limits?: AppLimits
}

/**
 * Local storage format for API tokens
 * Tokens are base64 encoded (not encrypted for MVP)
 */
export interface StoredToken {
  provider: LLMProvider
  token: string
  savedAt: string
}
