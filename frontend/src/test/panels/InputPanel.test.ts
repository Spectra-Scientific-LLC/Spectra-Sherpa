import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import InputPanel from "@/views/workflow-builder/node-detail/panels/InputPanel.vue";

function factory(props: Partial<InstanceType<typeof InputPanel>["$props"]> = {}) {
  return mount(InputPanel, {
    props: {
      expanded: true,
      hasInput: true,
      inputSummary: "",
      inputData: null,
      inputConnections: [],
      inputPreview: [],
      inputDataSummary: "",
      inputPreviewColumns: [],
      ...props,
    },
    global: { stubs: { Transition: false, DataTable: true, Column: true } },
  });
}

describe("InputPanel", () => {
  it("renders the empty state when hasInput is false", () => {
    const w = factory({ hasInput: false });
    expect(w.text()).toContain("No input data available");
  });

  it("renders shape / data type info when inputData is present", () => {
    const w = factory({
      inputData: { shape: [80, 700], source: "experiment", dataType: "absorbance" },
    });
    expect(w.text()).toContain("80 x 700");
    expect(w.text()).toContain("absorbance");
    // "Source" row removed in favor of the richer "Connected From" list — see #27.
    expect(w.text()).not.toContain("experiment");
  });

  it("renders connected-from list when inputConnections is non-empty", () => {
    const w = factory({
      inputConnections: [
        { nodeId: "data_1", icon: "🧪", label: "Iris Data", port: "default" },
      ],
    });
    expect(w.text()).toContain("Connected From");
    expect(w.text()).toContain("Iris Data");
    expect(w.text()).toContain("default");
  });

  it("renders preview heading when inputPreview is non-empty", () => {
    const w = factory({
      inputPreview: [{ _index: 1, col_0: "1.0" }],
      inputDataSummary: "50 rows × 10 cols",
      inputPreviewColumns: [{ field: "_index", header: "#" }],
    });
    expect(w.text()).toContain("Input Preview");
    expect(w.text()).toContain("50 rows × 10 cols");
  });

  it("emits `toggle` when the header is clicked", async () => {
    const w = factory();
    await w.find(".section-header").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();
  });

  it("shows the summary badge when inputSummary is set", () => {
    const w = factory({ inputSummary: "80 rows × 700 cols" });
    expect(w.find(".section-badge").text()).toBe("80 rows × 700 cols");
  });
});
