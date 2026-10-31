import { afterEach, expect, it, vi } from "vitest";
import { captureGuiTrace, createGuiTraceAttempt, enableGuiTrace, flushGuiTrace, resetGuiTrace, traceGui, traceOperation } from "@/lib/guiTrace";

afterEach(resetGuiTrace);
it("does not break startup when randomUUID is unavailable", async () => {
  const uuid = vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(() => undefined as unknown as `${string}-${string}-${string}-${string}-${string}`);
  try {
    resetGuiTrace();
    const send = vi.fn();
    expect(() => traceGui("workflow", "start")).not.toThrow();
    enableGuiTrace(send);
    await flushGuiTrace();
    expect(send).not.toHaveBeenCalled();
  } finally { uuid.mockRestore(); }
});
it("buffers a bounded number until explicitly enabled and sends no free-form content", async () => {
  const send = vi.fn().mockResolvedValue(undefined);
  for (let i = 0; i < 150; i++) traceGui("workflow", "start", { workflow_id: 9 });
  await flushGuiTrace();
  expect(send).not.toHaveBeenCalled();
  enableGuiTrace(send);
  await flushGuiTrace();
  expect(send).toHaveBeenCalledTimes(1);
  const batch = send.mock.calls[0][0];
  expect(batch.events).toHaveLength(30);
  expect(batch.events[0]).toEqual({ seq: 51, operation: "workflow", state: "start", workflow_id: 9 });
  expect(batch.page_id).toMatch(/^[0-9a-f-]{36}$/);
});
it("clears prior account observations and never propagates logging failure", async () => {
  const send = vi.fn().mockRejectedValue(new Error("offline"));
  traceGui("experiments", "cancelled");
  resetGuiTrace();
  enableGuiTrace(send);
  await flushGuiTrace();
  expect(send).not.toHaveBeenCalled();
  traceGui("workbook_reset", "reset");
  await expect(flushGuiTrace()).resolves.toBeUndefined();
  expect(send).toHaveBeenCalledTimes(1);
});
it("reduces paths to closed operation names", () => {
  expect(traceOperation("/experiments/private-name?key=secret")).toBe("experiments");
  expect(traceOperation("/unknown/secret")).toBe("other");
  expect(traceOperation("/workflows/9", "put")).toBe("autosave");
});

it("drops captured completions and queued owner IDs across a page/session reset", async () => {
  let sameOwner = true;
  const send = vi.fn().mockResolvedValue(undefined);
  enableGuiTrace(send);
  const old = createGuiTraceAttempt({ workflow_id: 424, project_id: 126 }, () => sameOwner);
  old("workflow_execute_http", "start");
  sameOwner = false;
  old("workflow_execute_http", "ok");
  await flushGuiTrace();
  expect(send).not.toHaveBeenCalled();
  sameOwner = true;
  resetGuiTrace(); enableGuiTrace(send);
  old("workflow_execute_finalize", "superseded");
  await flushGuiTrace(); expect(send).not.toHaveBeenCalled();
  const fresh = createGuiTraceAttempt({ workflow_id: 425 }, () => true);
  fresh("workflow_execute_http", "start"); await flushGuiTrace();
  expect(send.mock.calls[0][0].events).toEqual([expect.objectContaining({ attempt_id: 1, workflow_id: 425 })]);
});
it("checks the canonical browser credential epoch even before an auth-store notification", async () => {
  localStorage.setItem("token", "original-secret");
  const send = vi.fn().mockResolvedValue(undefined); enableGuiTrace(send);
  const old = captureGuiTrace(() => true);
  old("workflow_loading", "start", { workflow_id: 424 });
  localStorage.setItem("token", "replacement-secret");
  old("workflow_loading", "ok", { workflow_id: 424 });
  await flushGuiTrace(); expect(send).not.toHaveBeenCalled();
  localStorage.clear();
});
it("stops allocating diagnostic attempts at the schema bound without reusing IDs", async () => {
  resetGuiTrace();
  for (let i = 0; i < 1000000; i++) createGuiTraceAttempt({}, () => true);
  const send = vi.fn().mockResolvedValue(undefined); enableGuiTrace(send);
  createGuiTraceAttempt({ workflow_id: 424 }, () => true)("workflow_execute_http", "start");
  await flushGuiTrace(); expect(send).not.toHaveBeenCalled();
});
