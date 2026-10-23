import { afterEach, expect, it, vi } from "vitest";
import { enableGuiTrace, flushGuiTrace, resetGuiTrace, traceGui, traceOperation } from "@/lib/guiTrace";

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
