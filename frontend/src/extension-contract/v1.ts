/**
 * Public frontend extension contract, version 1.
 *
 * Import this module from both the host and independently built extensions.
 * Keep it free of host implementation imports: only framework/client types
 * cross this boundary. Breaking changes require a new versioned module.
 */
import type { AxiosInstance } from "axios";
import type { Component, DeepReadonly, Ref } from "vue";
import type { Router, RouteLocationRaw, RouteRecordRaw } from "vue-router";
import type { AppConfig as HostAppConfig, AppLimits } from "./config";

/** Existing descriptor/module handshake; extraction does not bump the wire version. */
export const EXTENSION_CONTRACT_VERSION = 1;
export const CONTEXTUAL_ACTIONS_VERSION = EXTENSION_CONTRACT_VERSION;

/** Extensions observe configuration; only the host can replace it. */
export type AppConfig = DeepReadonly<HostAppConfig>;
export type AppConfigLimits = DeepReadonly<AppLimits>;

export interface UserCapabilities {
  admin?: boolean;
}

export interface HostUser {
  id: number;
  username: string;
  principalKind?: "human" | "service" | string;
  is_active?: boolean;
  capabilities?: UserCapabilities;
  trial?: {
    state: string;
    policyVersion?: string | null;
    expiresAt?: string | null;
    daysRemaining?: number | null;
    termDays: number;
    supportEmail: string;
  } | null;
}

/** Real refs from storeToRefs: extension writes must reach the host's store. */
export interface HostAuthStore {
  user: Ref<HostUser | null>;
  token: Ref<string | null>;
  clearCredentials(): void;
}

export interface HostMenuItem {
  label?: string;
  icon?: string;
  command?: () => void;
  separator?: boolean;
  disabled?: boolean;
  class?: string;
}

export interface HostTopbarMenu {
  addItems(items: HostMenuItem[], contributorId?: string): void;
  removeItems(contributorId: string): void;
}

export interface HostPrimaryNavigationItem {
  label: string;
  to: string;
  icon: string;
  before?: string;
}

export interface HostPrimaryNavigation {
  addItems(items: HostPrimaryNavigationItem[], contributorId?: string): void;
  removeItems(contributorId: string): void;
}

export type HostActionContext =
  | { surface: "run"; projectId: number; runId: number; nodeId?: string }
  | {
      surface: "deploy";
      projectId: number;
      /** Opaque application-release handle owned by the active project. */
      applicationHandle: string;
    };

export interface HostContextualAction {
  id: string;
  label: string;
  icon?: string;
  available(context: Readonly<HostActionContext>): boolean;
  execute(context: Readonly<HostActionContext>, signal: AbortSignal): void | Promise<void>;
}

export interface HostConfirmOptions {
  title: string;
  message: string;
  acceptLabel: string;
  destructive?: boolean;
}

export interface HostAdvisorScope {
  projectId: number;
  tabKey: string;
  subscopeKey: string;
  resourceType?: string | null;
  resourceId?: number | null;
  title?: string | null;
}

/** Existing transport payloads remain provider-owned in version 1. */
export interface HostAdvisorTransport {
  prepareContext(workflowId: number | null): Promise<Record<string, unknown> | null>;
  loadConversation(id: string): Promise<any>;
  deleteConversation(id: string): Promise<unknown>;
  confirmProposal(sourceWorkflowId: number, proposal: Record<string, any>): Promise<number>;
}

export interface HostProjectCollection {
  key: string;
  label: string;
  total: number;
  to: RouteLocationRaw;
  items: Array<{ id: string; title: string; status: string; createdAt: string; to: RouteLocationRaw }>;
}

export type HostProjectCollectionsLoader = (projectId: number) => Promise<HostProjectCollection[]>;

export interface HostExtensions {
  version: number;
  projectId: number | null;
  signal: AbortSignal;
  isCurrent(): boolean;
  setProjectCollections?(loader: HostProjectCollectionsLoader): void;
  addActions(actions: HostContextualAction[]): void;
  onDispose(cleanup: () => void): void;
}

/**
 * Extension-facing context. Optional capabilities preserve compatibility with
 * older v1 hosts; extensions must check them before use. CurrentHostContext
 * separately requires the complete surface supplied by the current host.
 */
export interface HostContext {
  workspaceComponents?: Record<"Header" | "Context" | "ContextItem" | "Tabs", Component> & { State?: Component };
  api?: AxiosInstance;
  reloadConfig?(): Promise<unknown>;
  installAdvisorTransport?(transport: HostAdvisorTransport): void;
  /** Declines on caller abort or registration disposal. */
  confirmAction?(options: HostConfirmOptions, signal?: AbortSignal): Promise<boolean>;
  focusOptimization?(campaignId: string | null, candidateId?: string | null): void;
  focusSection?(section: string): void;
  setAdvisorScope?(args: HostAdvisorScope): Promise<void>;
  router: Router;
  authStore: HostAuthStore;
  topbarMenu: HostTopbarMenu;
  primaryNavigation?: HostPrimaryNavigation;
  appConfig: AppConfig;
  contributorId: string;
  /** Registers a route owned by this registration's lifetime. */
  addRoute(route: RouteRecordRaw): void;
  mountShell(component: Component, contributorId?: string): void;
  unmountShells(contributorId: string): void;
  extensions?: HostExtensions;
}

/** Host implementation must continue to supply every existing capability. */
export type CurrentHostContext = Required<Omit<HostContext, "extensions">> & {
  extensions: Required<HostExtensions>;
};

export type RegisterFn = (ctx: HostContext) => void | Promise<void>;

/** Loader shape, including the historical default-export registration form. */
export interface ServerModule {
  contextualActionsVersion?: number;
  register?: (ctx: CurrentHostContext) => void | Promise<void>;
  default?: (ctx: CurrentHostContext) => void | Promise<void>;
}

export type ImportModuleFn = (url: string) => Promise<ServerModule>;
