export interface SherpaEventPayload {
  type: string;
  request_id?: string | null;
  conversation_id?: string | null;
  payload?: any;
  detail?: string;
  message?: string;
  limit_type?: string;
  chunk?: string;
  tool_name?: string;
  result?: unknown;
  success?: boolean;
  summary?: string;
  error_category?: string;
  timing?: unknown;
  peaks?: unknown;
  response?: string;
  code?: string;
  language?: string;
  text?: string;
  report?: string;
  diagnostics?: Record<string, unknown> | null;
  memory_scopes?: string[];
  upgrade_url?: string;
  remaining?: number;
  session_expiry_hours?: number;
  [key: string]: unknown;
}

export interface SherpaSubscriptionOptions {
  requestId?: string | null;
  types?: string[];
}

type SherpaEventHandler = (payload: SherpaEventPayload) => void | Promise<void>;

interface SherpaSubscription {
  handler: SherpaEventHandler;
  requestId: string | null;
  types: Set<string> | null;
}

const subscriptions = new Map<number, SherpaSubscription>();
let nextSubscriptionId = 1;

export function createSherpaRequestId(): string {
  return crypto.randomUUID();
}

export function dispatchSherpaEvent(payload: SherpaEventPayload): void {
  for (const subscription of subscriptions.values()) {
    if (subscription.requestId && payload.request_id !== subscription.requestId) {
      continue;
    }
    if (subscription.types && !subscription.types.has(payload.type)) {
      continue;
    }
    subscription.handler(payload);
  }
}

export function subscribeSherpaEvents(
  handler: SherpaEventHandler,
  options?: SherpaSubscriptionOptions
): () => void {
  const subscriptionId = nextSubscriptionId;
  nextSubscriptionId += 1;
  subscriptions.set(subscriptionId, {
    handler,
    requestId:
      typeof options?.requestId === "string" && options.requestId.trim()
        ? options.requestId
        : null,
    types: options?.types?.length ? new Set(options.types) : null,
  });
  return () => {
    subscriptions.delete(subscriptionId);
  };
}
