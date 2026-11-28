// Additive navigation contract for the host and independently built extensions.
import type { RouteLocationRaw } from "vue-router";
import type { HostActionContext } from "./v1";

export const NAVIGATION_CONTRACT_VERSION = 1;

export interface NavPage {
  id: string;
  label: string;
  icon: string;
  route: RouteLocationRaw;
  /** Place before another page owned by this contributor, or a host page. */
  before?: string;
}

export interface NavSection {
  id: string;
  pageId: string;
  label: string;
  route: RouteLocationRaw;
}

export interface NavView {
  id: string;
  sectionId: string;
  label: string;
  route: RouteLocationRaw;
}

export interface NavScope {
  pageId: string;
  sectionId?: string;
  viewId?: string;
}

export interface NavActionContext extends NavScope {
  projectId: number | null;
  runId?: number;
  artifactUid?: string;
  /** An owned object from the active workspace, when present. */
  resource: Readonly<HostActionContext> | null;
}

export interface NavPrimaryAction {
  id: string;
  scope: NavScope;
  label: string;
  accelerator?: "CmdOrCtrl+Enter";
  available(context: Readonly<NavActionContext>): boolean;
  disabled?(context: Readonly<NavActionContext>): boolean;
  execute(context: Readonly<NavActionContext>, signal: AbortSignal): void | Promise<void>;
}

export interface NavigationContribution {
  pages?: readonly NavPage[];
  sections?: readonly NavSection[];
  views?: readonly NavView[];
  primaryActions?: readonly NavPrimaryAction[];
  /** Entries tied to the active project are disposed on project switch. */
  projectScoped?: boolean;
}

export interface HostNavigation {
  version: typeof NAVIGATION_CONTRACT_VERSION;
  register(contribution: NavigationContribution): () => void;
}
