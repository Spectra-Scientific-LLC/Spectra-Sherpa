import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SampleSelectionMap from "@/components/SampleSelectionMap.vue";

describe("Filter sample map display", () => {
  it("uses only output-bound names and keeps excluded names unavailable", async () => {
    const value = { sample_axis: { labels: ["Original A", "Original C"] }, provenance: [{
      op_id: "data.filter_samples", parameters: { n_input: 3, n_selected: 2, selected_indices: [0, 2] },
    }] };
    const wrapper = mount(SampleSelectionMap, { props: { value, count: 2, limit: 500 }, global: { stubs: {
      DataTable: { props: ["value"], template: '<pre>{{ JSON.stringify(value) }}</pre>' }, Column: true,
    } } });
    const details = wrapper.get("details").element as HTMLDetailsElement;
    details.open = true;
    await wrapper.get("details").trigger("toggle");
    expect(JSON.parse(wrapper.get("pre").text())).toEqual([
      { inputRow: 1, sample: "Original A", status: "Retained", resultRow: 1 },
      { inputRow: 2, sample: "—", status: "Excluded", resultRow: "—" },
      { inputRow: 3, sample: "Original C", status: "Retained", resultRow: 2 },
    ]);
    // A changed connection is not an input to this component at all. Even
    // explicitly passing it as an attribute cannot rename this retained run.
    await wrapper.setProps({ input: { y_axis: { labels: ["Other C", "Other B", "Other A"] } } } as never);
    expect(wrapper.get("pre").text()).not.toContain("Other");
    await wrapper.setProps({ value: { ...value, sample_axis: { labels: [] } } });
    expect(JSON.parse(wrapper.get("pre").text()).every((row: { sample: string }) => row.sample === "—")).toBe(true);
    wrapper.unmount();
  });
});
