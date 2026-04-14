import { describe, it, expect } from "vitest";
import { useNodeLog } from "@/views/workflow-builder/node-detail/composables/useNodeLog";

describe("useNodeLog", () => {
  it("prepends entries so the newest appears first", () => {
    const { executionLogs, addLog } = useNodeLog();
    addLog("info", "first");
    addLog("success", "second");
    expect(executionLogs.value.map((e) => e.message)).toEqual(["second", "first"]);
  });

  it("caps the buffer at 50 entries", () => {
    const { executionLogs, addLog } = useNodeLog();
    for (let i = 0; i < 60; i++) addLog("info", `msg-${i}`);
    expect(executionLogs.value.length).toBe(50);
    expect(executionLogs.value[0].message).toBe("msg-59");
  });

  it("clears all entries", () => {
    const { executionLogs, addLog, clearLogs } = useNodeLog();
    addLog("info", "x");
    clearLogs();
    expect(executionLogs.value).toEqual([]);
  });

  it("maps log types to PrimeIcons", () => {
    const { getLogIcon } = useNodeLog();
    expect(getLogIcon("success")).toBe("pi pi-check-circle");
    expect(getLogIcon("error")).toBe("pi pi-times-circle");
    expect(getLogIcon("warn")).toBe("pi pi-exclamation-triangle");
    expect(getLogIcon("info")).toBe("pi pi-info-circle");
  });

  it("records a time stamp string", () => {
    const { executionLogs, addLog } = useNodeLog();
    addLog("info", "hello");
    expect(executionLogs.value[0].time).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});
