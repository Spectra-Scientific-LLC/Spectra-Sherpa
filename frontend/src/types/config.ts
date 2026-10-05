/**
 * Application configuration types
 *
 * These types match the backend AppConfig structure
 */

export type AppMode = "local" | "enterprise" | (string & {});

export type SiteProfile = "demo" | "pro" | "org" | "production" | "internal";

export type LLMProvider = "openai" | "anthropic" | "deepseek" | "gemini" | "custom_llm";

export interface LLMConfig {
  provider: LLMProvider;
  model: string;
  enabled: boolean;
}

export interface AppFeatures {
  apiTokenSettings: boolean;
  /** False only in the desktop app when OS credential protection is unavailable. */
  credentialStorage?: boolean;
  chatAssistant: boolean;
  sherpaAdvisor: boolean;
  nistDownloads: boolean;
  // Subscription-gated Sherpa capabilities
  sherpaPeakId: boolean;
  sherpaCodeGen: boolean;
  sherpaWriteReport: boolean;
  sherpaAgenticTools: boolean;
  sherpaDataStory: boolean;
  sherpaFullContext: boolean;
  sherpaGuidance: boolean;
}

export interface AppCapabilities {
  llmByok: boolean;
  managedLlm: boolean;
  governedTools: boolean;
  hostedFolderWatch: boolean;
  workbenchDeploy: boolean;
  hitranKeyManagement: boolean;
  hitranQueries: boolean;
  privateBatchPrediction: boolean;
}

export interface SubscriptionInfo {
  plan: string; // "none" | "pro" | "team" | "demo"
  upgrade_url?: string;
}

export interface AppLimits {
  /** Server-derived wait windows, including reasoning and availability fallback. */
  sherpaResponseTimeoutMs?: number;
  sherpaSyncTimeoutMs?: number;
  maxSherpaRequestsHour?: number;
  maxFileSizeMB: number;
  adminBypass?: boolean;
  sessionExpiryHours?: number;
}

export interface AuditConfig {
  localQuery: boolean;
  fullPipeline: boolean;
  reportPack: boolean;
  exportAudited: boolean;
}

export interface DataFormatInfo {
  key: string;
  name: string;
  extensions: string[];
  description: string;
  requiresExport?: boolean;
  unsupportedReason?: string;
  available: boolean;
  parserId?: string;
  parserVersion?: string;
  filenamePatterns?: string[];
  extensionExamples?: string[];
}

export interface DataFormatsConfig {
  baseExtensions: string[];
  canonicalFileLoadExtensions: string[];
  knownUnsupportedExtensions?: string[];
  acceptedExtensions: string[];
  acceptedFilenamePatterns: string[];
  formats: DataFormatInfo[];
}

export interface DemoContract {
  featuredDatasets: string[];
  featuredTemplates: string[];
  maxExecutionsPerHour: number;
  maxExecutionsPerDay: number;
  maxSherpaPerHour: number;
  maxSherpaPerDay: number;
  maxUploadPerWeek: number;
  maxCampaignsPerWeek: number;
  maxConcurrentCampaigns: number;
  maxSiteCampaignsPerWeek: number;
  maxSiteConcurrentCampaigns: number;
  maxSiteCampaignComputeSecondsPerWeek: number;
  campaignAdmissionEnabled: boolean;
  disabledCapabilities: string[];
  upgradeUrl: string;
  upgradeMessage: string;
  availablePlans: string[];
}

export interface DemoQuotaWindow {
  lastHour: number;
  lastDay: number;
  limitPerHour: number;
  limitPerDay: number;
  resetHourAt?: string | null;
  resetDayAt?: string | null;
}

export interface DemoUploadQuotaWindow {
  lastWeek: number;
  limitPerWeek: number;
  resetWeekAt?: string | null;
}

export interface DemoCampaignQuotaWindow extends DemoUploadQuotaWindow {
  limitConcurrent: number;
}

export interface DemoDeploymentCampaignQuota extends DemoCampaignQuotaWindow {
  admissionEnabled: boolean;
  active: number;
  inflight: number;
  computeSecondsUsed: number;
  computeSecondsLimit: number;
  computeSecondsRemaining: number;
  estimatedCostUsdUsed: string;
  estimatedCostUsdLimit: string;
  estimatedCostUsdRemaining: string;
  estimatedCostPricingVersion: string;
}

export interface DemoQuotaResponse {
  demo: boolean;
  adminBypass?: boolean;
  executions?: DemoQuotaWindow;
  sherpa?: DemoQuotaWindow;
  uploads?: DemoUploadQuotaWindow;
  campaigns?: DemoCampaignQuotaWindow;
  deploymentCampaigns?: DemoDeploymentCampaignQuota;
}

/** Structured detail from demo 403 guards */
export interface DemoBlockedDetail {
  message: string;
  upgrade_url: string;
  available_plans: string[];
  blocked_capability: string;
}

export interface AppConfig {
  implicitIdentity?: boolean;
  advisorContextPolicy?: "receipt";
  uiExtensions?: Array<{ id: string; url: string; contractVersion: number; bootstrap?: boolean; required?: boolean }>;
  mode: AppMode;
  siteProfile?: SiteProfile | null;
  /** Signed desktop app: local-only, no hosted-service connection. */
  desktop?: boolean;
  configStatus?: "ok" | "degraded";
  configError?: "subscription_overlay_unavailable" | null;
  egressEnabled: boolean;
  registrationEnabled?: boolean;
  apiBaseUrl: string;
  features: AppFeatures;
  capabilities?: AppCapabilities;
  llms: Record<string, LLMConfig>;
  limits?: AppLimits;
  dataFormats?: DataFormatsConfig;
  subscription?: SubscriptionInfo | null;
  audit?: AuditConfig;
  demo?: DemoContract | null;
}

/**
 * Local storage format for API tokens
 * Tokens are base64 encoded (not encrypted for MVP)
 */
export interface StoredToken {
  provider: LLMProvider;
  token: string;
  savedAt: string;
}
