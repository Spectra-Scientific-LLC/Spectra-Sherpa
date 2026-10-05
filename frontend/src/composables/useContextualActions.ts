import { computed, readonly, shallowRef } from "vue";

export const CONTEXTUAL_ACTIONS_VERSION = 1;

export interface RunActionContext {
  surface: "run";
  projectId: number;
  runId: number;
  nodeId?: string;
}

/**
 * Context for actions contributed to Deploy.  The handle is deliberately
 * opaque to the OSS shell: a hosted extension may use it to authorize and
 * package an application, while the open-source Deploy page only carries it
 * between the release list and the extension slot.
 */
export interface DeployActionContext {
  surface: "deploy";
  projectId: number;
  applicationHandle: string;
}

export type ActionContext = RunActionContext | DeployActionContext;

export interface ContextualAction {
  id: string;
  label: string;
  icon?: string;
  available(context: Readonly<ActionContext>): boolean;
  execute(context: Readonly<ActionContext>, signal: AbortSignal): void | Promise<void>;
}

interface Contribution {
  key: string;
  owner: string;
  action: ContextualAction;
  current: () => boolean;
}

const contributions = shallowRef<Contribution[]>([]);
const context = shallowRef<Readonly<ActionContext> | null>(null);
const error = shallowRef<string | null>(null);
const running = shallowRef<string | null>(null);
export const actionContextRevision = shallowRef(0);
let lease = 0;
let execution: AbortController | null = null;

export function invalidateActionContext(): void {
  setActionContext(null);
  actionContextRevision.value++;
}

export function setActionContext(value: ActionContext | null): () => void {
  execution?.abort();
  execution = null;
  running.value = null;
  error.value = null;
  const currentLease = ++lease;
  context.value = value ? Object.freeze({ ...value }) : null;
  return () => { if (lease === currentLease) setActionContext(null); };
}

export function removeContextualActions(owner: string): void {
  if (contributions.value.some((item) => item.owner === owner && item.key === running.value)) {
    execution?.abort();
    running.value = null;
  }
  contributions.value = contributions.value.filter((item) => item.owner !== owner);
}

export function registerContextualActions(owner: string, actions: ContextualAction[], current: () => boolean): void {
  if (!current()) return;
  const ids = new Set<string>();
  for (const action of actions) {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(action.id) || !action.label.trim()
      || typeof action.available !== "function" || typeof action.execute !== "function" || ids.has(action.id)) {
      throw new Error("Invalid contextual action contribution");
    }
    ids.add(action.id);
  }
  removeContextualActions(owner);
  contributions.value = [...contributions.value, ...actions.map((action) => ({
    key: `${owner}:${action.id}`, owner, action, current,
  }))];
}

function available(item: Contribution): boolean {
  try {
    return item.current() && context.value !== null && item.action.available(context.value);
  } catch {
    return false;
  }
}

const actions = computed(() => contributions.value.filter(available).map(({ key, action }) => ({
  key, label: action.label, icon: action.icon,
})));

async function execute(key: string): Promise<void> {
  const item = contributions.value.find((entry) => entry.key === key);
  const snapshot = context.value;
  if (!item || !snapshot || running.value || !available(item)) return;
  const controller = new AbortController();
  const currentLease = lease;
  execution = controller;
  running.value = key;
  error.value = null;
  try {
    await item.action.execute(snapshot, controller.signal);
  } catch (cause) {
    if (!controller.signal.aborted && lease === currentLease && item.current()) {
      error.value = cause instanceof Error ? cause.message : "The contextual action failed.";
    }
  } finally {
    if (execution === controller) {
      execution = null;
      running.value = null;
    }
  }
}

export function useContextualActions() {
  return { actions, error: readonly(error), running: readonly(running), execute };
}
