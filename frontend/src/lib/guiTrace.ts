/** Temporary, bounded staging trace. No values, names, URLs, tokens or error text. */
type Operation = "experiments" | "projects" | "catalogue" | "workflow" | "runs" | "autosave" | "other" | "workbook_load" | "workbook_reset" | "workflow_reset" | "workflow_apply" | "guidance";
type State = "start" | "ok" | "error" | "cancelled" | "superseded" | "reset" | "refused";
type Fields = { elapsed_ms?: number; status?: number; project_id?: number | null; workflow_id?: number | null; node_count?: number };
type Event = Fields & { seq: number; operation: Operation; state: State };
let sequence = 0;
let queue: Event[] = [];
let sender: ((body: unknown) => Promise<unknown>) | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
const newPageId = () => globalThis.crypto?.randomUUID?.() ?? null;
let pageId = newPageId();

export function traceGui(operation: Operation, state: State, fields: Fields = {}): void {
  if (!pageId) return;
  queue.push({ seq: ++sequence, operation, state, ...fields });
  queue = queue.slice(-100);
  if (sender && !timer) timer = setTimeout(flushGuiTrace, 250);
}

export function enableGuiTrace(send: (body: unknown) => Promise<unknown>): void {
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
  pageId = newPageId();
}

export async function flushGuiTrace(): Promise<void> {
  timer = undefined;
  if (!sender || !queue.length) return;
  const events = queue.splice(0, 30);
  try { await sender({ page_id: pageId, events }); } catch { /* Diagnostics never interrupt work or retry indefinitely. */ }
  if (queue.length && !timer) timer = setTimeout(flushGuiTrace, 250);
}

export function traceOperation(path = "", method = "get"): Operation {
  if (path.startsWith("/experiments")) return "experiments";
  if (path.startsWith("/projects")) return "projects";
  if (path.includes("/nodes/library") || path.includes("/types")) return "catalogue";
  if (path.includes("/runs")) return "runs";
  if (path.startsWith("/workflows")) return method === "put" ? "autosave" : "workflow";
  return "other";
}
