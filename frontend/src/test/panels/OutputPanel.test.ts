import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import OutputPanel from "@/views/workflow-builder/node-detail/panels/OutputPanel.vue";

function factory(props: Partial<InstanceType<typeof OutputPanel>["$props"]> = {}) {
  return mount(OutputPanel, {
    props: {
      expanded: true,
      outputSummary: "",
      hasOutput: true,
      outputData: null,
      outputMetadata: {},
      outputSubsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: false,
      },
      datasetInfo: null,
      datasetLabelTable: { headers: [], rows: [] },
      labelPreviewLimit: 10,
      processingHistory: null,
      provenanceInfo: null,
      qualitySummary: null,
      isRegressionNode: false,
      regressionTargetOptions: [],
      regressionTargetIdx: 0,
      selectedRegressionR2: null,
      selectedRegressionRmse: null,
      portSummaries: [],
      outputPreview: [],
      outputPreviewColumns: [],
      outputDataSummary: "",
      pcaDiagnosticsPreview: [],
      pcaDiagSummary: "",
      pcaDiagnosticsColumns: [],
      getMetaTooltip: () => null,
      formatMetaValue: (v: unknown) => String(v),
      ...props,
    },
    global: {
      stubs: {
        Transition: false,
        DataTable: true,
        Column: true,
        Dropdown: true,
        Button: {
          props: ["label"],
          template: '<button :aria-label="label" @click="$emit(\'click\')"><slot/></button>',
        },
      },
    },
  });
}

describe("OutputPanel", () => {
  it("renders empty state when hasOutput is false", () => {
    const w = factory({ hasOutput: false });
    expect(w.text()).toContain("No output data available");
  });

  it("renders rows / cols / type / range stats when outputData is present", () => {
    const w = factory({
      outputData: { rows: 50, cols: 10, type: "PCA scores", range: [-1.5, 1.5] },
    });
    expect(w.text()).toContain("50");
    expect(w.text()).toContain("PCA scores");
    expect(w.text()).toContain("-1.500 - 1.500");
  });

  it("emits toggleSub with the correct subsection key", async () => {
    const w = factory({
      processingHistory: [{ operation: "scale" }],
    });
    const toggles = w.findAll(".inspector-toggle");
    expect(toggles.length).toBeGreaterThan(0);
    await toggles[0].trigger("click");
    const events = w.emitted("toggleSub");
    expect(events).toBeTruthy();
    expect(["coordinates", "metadata", "processing", "provenance", "quality", "ports"]).toContain(
      events?.[0]?.[0] as string,
    );
  });

  it("expands metadata subsection and renders key/value pairs", () => {
    const w = factory({
      outputMetadata: { n_components: 3, explained_variance: 0.92 },
      outputSubsections: {
        coordinates: false,
        metadata: true,
        processing: false,
        provenance: false,
        quality: false,
        ports: false,
      },
    });
    expect(w.text()).toContain("n_components");
    expect(w.text()).toContain("3");
    expect(w.text()).toContain("explained_variance");
  });

  it("renders processing timeline when processingHistory is expanded", () => {
    const w = factory({
      processingHistory: [
        { operation: "snv", parameters: {}, input_shape: [80, 700], output_shape: [80, 700] },
        "smooth",
      ],
      outputSubsections: {
        coordinates: false,
        metadata: false,
        processing: true,
        provenance: false,
        quality: false,
        ports: false,
      },
    });
    expect(w.findAll(".timeline-item")).toHaveLength(2);
    expect(w.text()).toContain("snv");
    expect(w.text()).toContain("smooth");
    expect(w.text()).toContain("In: 80×700");
  });

  it("renders port summary cards when portSummaries is non-empty + expanded", () => {
    const w = factory({
      portSummaries: [{ name: "scores", type: "dataset", shape: [50, 3] }],
      outputSubsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: true,
      },
    });
    expect(w.findAll(".port-summary-card")).toHaveLength(1);
    expect(w.text()).toContain("scores");
    expect(w.text()).toContain("Shape: 50×3");
  });

  it("emits the action events from the output-actions buttons", async () => {
    const w = factory();
    const click = (label: string) =>
      w.find(`button[aria-label="${label}"]`).trigger("click");
    await click("View Full Metadata (JSON)");
    await click("View Data Table");
    await click("Quick Plot");
    await click("Export CSV");
    expect(w.emitted("showFullMetadata")).toBeTruthy();
    expect(w.emitted("openDataTable")).toBeTruthy();
    expect(w.emitted("openQuickPlot")).toBeTruthy();
    expect(w.emitted("exportOutput")).toBeTruthy();
  });

  it("emits update:regressionTargetIdx when the regression dropdown changes", async () => {
    const w = factory({
      isRegressionNode: true,
      regressionTargetOptions: [
        { label: "all", value: -1 },
        { label: "target 0", value: 0 },
      ],
      qualitySummary: { latest_model_type: "pls" },
      outputSubsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: true,
        ports: false,
      },
    });
    const dropdown = w.findComponent({ name: "Dropdown" });
    dropdown.vm.$emit("update:model-value", 0);
    expect(w.emitted("update:regressionTargetIdx")).toEqual([[0]]);
  });
});
