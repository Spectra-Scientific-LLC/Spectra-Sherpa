import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import LogPanel from "@/views/workflow-builder/node-detail/panels/LogPanel.vue";
import type { LogEntry } from "@/views/workflow-builder/node-detail/composables/useNodeLog";

const iconFor = (type: LogEntry["type"]) =>
  ({
    success: "pi pi-check-circle",
    error: "pi pi-times-circle",
    warn: "pi pi-exclamation-triangle",
    info: "pi pi-info-circle",
  })[type];

function factory(props: Partial<InstanceType<typeof LogPanel>["$props"]> = {}) {
  return mount(LogPanel, {
    props: {
      logs: [],
      expanded: true,
      getLogIcon: iconFor,
      ...props,
    },
    global: { stubs: { Transition: false } },
  });
}

describe("LogPanel", () => {
  it("renders the empty state when there are no logs", () => {
    const w = factory();
    expect(w.text()).toContain("No execution logs yet");
    expect(w.find(".log-entries").exists()).toBe(false);
  });

  it("renders each log entry with time, icon, message, and optional details", () => {
    const logs: LogEntry[] = [
      { time: "12:00:00", type: "success", message: "Trial completed", details: "Output: 10 × 2 matrix" },
      { time: "11:59:58", type: "info", message: "Trial started" },
    ];
    const w = factory({ logs });
    const entries = w.findAll(".log-entry");
    expect(entries).toHaveLength(2);
    expect(entries[0].text()).toContain("Trial completed");
    expect(entries[0].text()).toContain("Output: 10 × 2 matrix");
    expect(entries[0].classes()).toContain("success");
    expect(entries[1].classes()).toContain("info");
  });

  it("shows the entry-count badge only when logs exist", async () => {
    const w = factory({ logs: [{ time: "1", type: "info", message: "a" }] });
    expect(w.find(".section-badge").text()).toBe("1 entries");
  });

  it("emits `toggle` when the header is clicked", async () => {
    const w = factory();
    await w.find(".section-header").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();
  });

  it("emits `clear` when the Clear Log button is clicked", async () => {
    const w = factory({ logs: [{ time: "1", type: "info", message: "x" }] });
    await w.find(".log-actions button").trigger("click");
    expect(w.emitted("clear")).toBeTruthy();
  });

  it("hides content when collapsed", () => {
    const w = factory({ expanded: false, logs: [{ time: "1", type: "info", message: "x" }] });
    expect(w.find(".log-entries").exists()).toBe(false);
    expect(w.find(".empty-section").exists()).toBe(false);
  });
});
