import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createPinia, disposePinia, setActivePinia, type Pinia } from "pinia";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { enableGuiTrace, flushGuiTrace, resetGuiTrace } from "@/lib/guiTrace";
import { _resetSingleFlightForTests } from "@/utils/idempotency";
import { _clearProjectScopeRegistryForTests } from "@/stores/projectScopeRegistry";

vi.mock("@/api/client", () => ({ default: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }));
vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => ({ activeSheet: null, sheets: [], syncSavedSheetMetadata: vi.fn() }),
}));
vi.mock("@/stores/job", () => ({ useJobStore: () => ({ wsRef: null }) }));

type Trace = Record<string, unknown>;
const send = vi.fn<(body: { events: Trace[] }) => Promise<void>>();
let pinia: Pinia;
const response = { status: "completed", run_id: 698, results: { source: [[1]] }, node_statuses: { source: "completed" } };
beforeEach(() => {
  localStorage.clear();
  resetGuiTrace();
  _resetSingleFlightForTests();
  _clearProjectScopeRegistryForTests();
  pinia = createPinia(); setActivePinia(pinia); vi.resetAllMocks();
  useAuthStore().user = { id: 7, username: "not-for-diagnostics" };
  useProjectStore().currentProjectId = 126;
  send.mockResolvedValue(); enableGuiTrace(send);
});
afterEach(() => { disposePinia(pinia); resetGuiTrace(); _clearProjectScopeRegistryForTests(); });
function setup() {
  const store = useWorkflowStore();
  store.workflowId = 424;
  store.nodes = [{ id: "source", type: "data.file_load", x: 0, y: 0, params: {} }];
  store.hasUnsavedChanges = false;
  return store;
}
async function events() {
  await flushGuiTrace();
  return send.mock.calls.flatMap(([body]) => body.events).filter(e => String(e.operation).startsWith("workflow_execute_"));
}
function pendingResponse() {
  let resolve!: (value: { data: typeof response }) => void;
  let reject!: (reason: Error) => void;
  const pending = new Promise<{ data: typeof response }>((yes, no) => { resolve = yes; reject = no; });
  vi.mocked(api.post).mockImplementation(async url => {
    if (url.endsWith("/preflight")) return { data: { is_valid: true, issues: [], semantic_edges: [] } };
    return pending;
  });
  return { resolve, reject };
}
it("correlates the real store's response, application and authorized clearing without altering results", async () => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow();
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  expect(store.nodes[0].executionState?.status).toBe("pending");
  held.resolve({ data: response }); await pending;
  expect(store.isLoading).toBe(false);
  expect(store.nodes[0].executionState?.status).toBe("completed");
  expect(store.lastExecutionResults).toEqual(response.results);
  const trace = await events();
  expect(trace.map(e => [e.operation, e.state])).toEqual([
    ["workflow_execute_http", "start"], ["workflow_execute_http", "ok"],
    ["workflow_execute_apply", "start"], ["workflow_execute_apply", "ok"],
    ["workflow_execute_finalize", "ok"],
  ]);
  expect(new Set(trace.map(e => e.attempt_id)).size).toBe(1);
  expect(trace.every(e => e.workflow_id === 424 && e.project_id === 126)).toBe(true);
  expect(trace.at(-1)).toMatchObject({ workflow_loading: false, loading_clear_authorized: true, workflow_owner_current: true, execution_owner_current: true, workflow_id_matches: true, run_id: 698 });
  expect(JSON.stringify(trace)).not.toContain("not-for-diagnostics");
  const execute = vi.mocked(api.post).mock.calls.find(([url]) => url.endsWith("/execute"))!;
  expect(Object.keys(execute[1] as object).sort()).toEqual(["expected_definition", "initial_data"]);
  expect(Object.keys(execute[2]!.headers!)).toEqual(["Idempotency-Key"]);
});
it("distinguishes a rejected transport from application failure without logging exception text", async () => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  held.reject(new Error("secret transport detail")); await pending;
  const trace = await events();
  expect(trace.map(e => [e.operation, e.state])).toEqual([
    ["workflow_execute_http", "start"], ["workflow_execute_http", "error"], ["workflow_execute_finalize", "ok"],
  ]);
  expect(store.isLoading).toBe(false); expect(store.restoredRunId).toBeNull();
  expect(JSON.stringify(trace)).not.toContain("secret");
});
it("records cancellation without inventing a completed result", async () => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  held.reject(new DOMException("private cancellation detail", "AbortError")); await pending;
  const trace = await events();
  expect(trace.map(e => [e.operation, e.state])).toEqual([
    ["workflow_execute_http", "start"], ["workflow_execute_http", "cancelled"], ["workflow_execute_finalize", "ok"],
  ]);
  expect(store.isLoading).toBe(false); expect(store.restoredRunId).toBeNull();
  expect(JSON.stringify(trace)).not.toContain("private cancellation");
});
it("reports application failure after HTTP success and still runs the original finalizer", async () => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  // A genuine response getter failure exercises the store's application catch, not a mocked store action.
  const broken = { ...response, get results(): typeof response.results { throw new Error("secret application detail"); } };
  held.resolve({ data: broken }); await pending;
  const trace = await events();
  expect(trace.map(e => [e.operation, e.state])).toEqual([
    ["workflow_execute_http", "start"], ["workflow_execute_http", "ok"],
    ["workflow_execute_apply", "start"], ["workflow_execute_apply", "error"], ["workflow_execute_finalize", "ok"],
  ]);
  expect(store.isLoading).toBe(false); expect(JSON.stringify(trace)).not.toContain("secret");
});
it("never clears another sheet's newer attempt when a superseded response arrives", async () => {
  const store = setup(); const old = pendingResponse(); const first = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  store.clearWorkflow(); setup(); store.workflowId = 425;
  const fresh = pendingResponse(); const second = store.executeWorkflow();
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  old.resolve({ data: response }); expect((await first).name).toBe("AbortError");
  expect(store.isLoading).toBe(true); expect(store.restoredRunId).toBeNull();
  let trace = await events();
  const rejected = trace.find(e => e.operation === "workflow_execute_apply" && e.state === "superseded");
  expect(rejected).toMatchObject({ workflow_id_matches: false, workflow_owner_current: false, execution_owner_current: false });
  expect(trace.find(e => e.operation === "workflow_execute_finalize" && e.attempt_id === rejected?.attempt_id)).toMatchObject({ loading_clear_authorized: false, workflow_loading: true });
  fresh.resolve({ data: { ...response, run_id: 699 } }); await second;
  expect(store.restoredRunId).toBe(699); expect(store.isLoading).toBe(false);
  trace = await events(); expect(new Set(trace.map(e => e.attempt_id)).size).toBe(2);
});
it("refuses A to B to A response application even though the workflow ID matches again", async () => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  store.clearWorkflow(); store.workflowId = 425; store.clearWorkflow(); setup();
  await expect(store.executeWorkflow()).rejects.toThrow("already in progress");
  held.resolve({ data: response }); expect((await pending).name).toBe("AbortError");
  expect(store.restoredRunId).toBeNull(); expect(store.isLoading).toBe(false);
  const trace = await events();
  expect(trace.find(e => e.operation === "workflow_execute_apply")).toMatchObject({ state: "superseded", workflow_id_matches: true, workflow_owner_current: false, execution_owner_current: false });
  expect(trace.at(-1)).toMatchObject({ state: "superseded", loading_clear_authorized: false });
});
it.each([false, true])("does not emit old owner IDs after a session change (trace reset=%s)", async reset => {
  const store = setup(); const held = pendingResponse(); const pending = store.executeWorkflow().catch(e => e);
  await vi.waitFor(() => expect(store.isLoading).toBe(true));
  await events(); send.mockClear();
  useAuthStore().user = { id: 8, username: "replacement" };
  if (reset) { resetGuiTrace(); enableGuiTrace(send); }
  held.resolve({ data: response }); expect((await pending).name).toBe("AbortError");
  expect(await events()).toEqual([]); expect(store.restoredRunId).toBeNull();
});
