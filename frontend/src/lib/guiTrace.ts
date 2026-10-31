import { readBrowserSession, sameBrowserSession } from "@/extension-contract/session-v1";

/** Temporary, bounded staging trace. No values, names, URLs, tokens or error text. */
type Operation = "experiments" | "projects" | "catalogue" | "workflow" | "runs" | "autosave" | "other" | "workbook_load" | "workbook_reset" | "workflow_reset" | "workflow_apply" | "guidance" | "workflow_loading" | "workflow_execute_http" | "workflow_execute_apply" | "workflow_execute_finalize";
type State = "start" | "ok" | "error" | "cancelled" | "superseded" | "reset" | "refused";
type Fields = {
  elapsed_ms?: number; status?: number; project_id?: number | null; workflow_id?: number | null; node_count?: number;
  attempt_id?: number; run_id?: number;
  workbook_context_ready?: boolean; workbook_loading?: boolean; workflow_loading?: boolean;
  workflow_id_matches?: boolean; workflow_owner_current?: boolean; execution_owner_current?: boolean;
  loading_clear_authorized?: boolean;
};
type Event = Fields & { seq: number; operation: Operation; state: State };
let sequence = 0;
let queue: { event: Event; current?: () => boolean }[] = [];
let epoch = 0;
let attemptSequence = 0;
let sender: ((body: unknown, current: () => boolean) => Promise<unknown>) | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
const newPageId = () => globalThis.crypto?.randomUUID?.() ?? null;
let pageId = newPageId();

export function traceGui(operation: Operation, state: State, fields: Fields = {}): void {
  enqueue(operation, state, fields);
}

function enqueue(operation: Operation, state: State, fields: Fields, current?: () => boolean): void {
  if (!pageId || sequence >= 1000000 || (current && !current())) return;
  queue.push({ event: { seq: ++sequence, operation, state, ...fields }, current });
  queue = queue.slice(-100);
  if (sender && !timer) timer = setTimeout(flushGuiTrace, 250);
}

/** Captures diagnostic ownership only; never grants or cancels a scientific request. */
export function captureGuiTrace(sameOwnerSession: () => boolean) {
  const capturedEpoch = epoch;
  const capturedPage = pageId;
  try {
    const session = readBrowserSession();
    const current = () => {
      try {
        return epoch === capturedEpoch && pageId === capturedPage && sameBrowserSession(session) && sameOwnerSession();
      } catch { return false; }
    };
    return (operation: Operation, state: State, fields: Fields = {}) => enqueue(operation, state, fields, current);
  } catch {
    return (_operation: Operation, _state: State, _fields: Fields = {}) => { /* Unavailable diagnostics must not affect work. */ };
  }
}

export function createGuiTraceAttempt(owner: Pick<Fields, "project_id" | "workflow_id">, sameOwnerSession: () => boolean) {
  const emit = captureGuiTrace(sameOwnerSession);
  const attempt = attemptSequence < 1000000 ? ++attemptSequence : null;
  return (operation: Operation, state: State, fields: Fields = {}) => {
    if (attempt === null) return;
    emit(operation, state, { ...fields, ...owner, attempt_id: attempt });
  };
}

export function enableGuiTrace(send: (body: unknown, current: () => boolean) => Promise<unknown>): void {
  if (!pageId) return;
  sender = send;
  if (queue.length && !timer) timer = setTimeout(flushGuiTrace, 250);
}

export function resetGuiTrace(): void {
  if (timer) clearTimeout(timer);
  timer = undefined;
  sender = null;
  queue = [];
  sequence = 0;
  attemptSequence = 0;
  epoch += 1;
  pageId = newPageId();
}

export async function flushGuiTrace(): Promise<void> {
  timer = undefined;
  if (!sender || !queue.length) return;
  const capturedEpoch = epoch;
  const capturedPage = pageId;
  const entries = queue.splice(0, 30).filter(entry => !entry.current || entry.current());
  const events = entries.map(entry => entry.event);
  try {
    const session = readBrowserSession();
    const current = () => {
      try {
        return epoch === capturedEpoch && pageId === capturedPage && sameBrowserSession(session) &&
          entries.every(entry => !entry.current || entry.current());
      } catch { return false; }
    };
    if (events.length) await sender({ page_id: capturedPage, events }, current);
  } catch { /* Diagnostics never interrupt work or retry indefinitely. */ }
  if (epoch === capturedEpoch && queue.length && !timer) timer = setTimeout(flushGuiTrace, 250);
}

export function traceOperation(path = "", method = "get"): Operation {
  if (path.startsWith("/experiments")) return "experiments";
  if (path.startsWith("/projects")) return "projects";
  if (path.includes("/nodes/library") || path.includes("/types")) return "catalogue";
  if (path.includes("/runs")) return "runs";
  if (path.startsWith("/workflows")) return method === "put" ? "autosave" : "workflow";
  return "other";
}
