/**
 * Application configuration types
 *
 * These types match the backend AppConfig structure
 */

export type AppMode = 'local' | 'hybrid' | 'enterprise'

export type SiteProfile = 'demo' | 'production' | 'internal'

export type LLMProvider = 'openai' | 'anthropic' | 'deepseek' | 'gemini' | 'custom_llm'

export interface LLMConfig {
  provider: LLMProvider
  model: string
  enabled: boolean
}

export interface AppFeatures {
  apiTokenSettings: boolean
  cloudOffload: boolean
  chatAssistant: boolean
  sherpaAdvisor?: boolean
  pluginSystem?: boolean
  customCodeExecution?: boolean
  nistDownloads?: boolean
  // Subscription-gated Sherpa capabilities
  sherpaPeakId?: boolean
  sherpaCodeGen?: boolean
  sherpaWriteReport?: boolean
  sherpaAgenticTools?: boolean
  sherpaFullContext?: boolean
}

export interface SubscriptionInfo {
  plan: string  // "none" | "pro" | "team" | "demo"
  upgrade_url?: string
}

export interface AppLimits {
  maxExecutions?: number
  maxFileSizeMB: number
  sessionExpiryHours?: number
}

export interface DemoContract {
  featuredDatasets: string[]
  featuredTemplates: string[]
  maxExecutionsPerSession: number
  maxSherpaInteractions: number
  sessionExpiryHours?: number
  disabledCapabilities: string[]
  upgradeUrl: string
  upgradeMessage: string
  availablePlans: string[]
}

export interface DemoQuota {
  remaining: number
  limit: number
}

export interface DemoQuotaResponse {
  demo: boolean
  executions?: DemoQuota
  sherpa?: DemoQuota
}

/** Structured detail from demo 403 guards */
export interface DemoBlockedDetail {
  message: string
  upgrade_url: string
  available_plans: string[]
  blocked_capability: string
}

export interface AppConfig {
  mode: AppMode
  siteProfile?: SiteProfile | null
  egressEnabled: boolean
  registrationEnabled?: boolean
  registrationRequiresCode?: boolean
  apiBaseUrl: string
  features: AppFeatures
  llms: Record<string, LLMConfig>
  limits?: AppLimits
  subscription?: SubscriptionInfo | null
  demo?: DemoContract | null
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
