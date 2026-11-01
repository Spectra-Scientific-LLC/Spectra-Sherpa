import { mount } from "@vue/test-utils";
import { ref } from "vue";
import { describe, expect, it, vi } from "vitest";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";
const notify = vi.hoisted(() => vi.fn());
vi.mock("@/composables/useNotifier", () => ({ useNotifier: () => ({ notifySystemEvent: notify }) }));

describe("compact observation exclusion control", () => {
  it("distinguishes a new exclusion from membership in the displayed calculation", async () => {
    const excluded = ref(false);
    const change = vi.fn((_refs: string[], value: boolean) => { excluded.value = value; });
    const wrapper = mount(ObservationExclusionButton, { props: { observationRef: "canonical-one", label: "Sample 1", usedInResult: true },
      global: { provide: { [WORKFLOW_POPULATION_ACTIONS]: {
        resolve: () => ({ excluded: excluded.value, restorable: true }), change,
      } } } });
    expect(wrapper.get("button").attributes("title")).toBe("Exclude Sample 1.");
    await wrapper.get("button").trigger("click");
    expect(change).toHaveBeenCalledWith(["canonical-one"], true);
    expect(wrapper.get("button").attributes("aria-label")).toContain("Restore Sample 1");
    await wrapper.get("button").trigger("click");
    expect(change).toHaveBeenLastCalledWith(["canonical-one"], false);
    await wrapper.setProps({ usedInResult: false });
    expect(wrapper.get("button").attributes("title")).toBe("Exclude Sample 1.");
  });
  it("rechecks a stale reference and surfaces canonical refusal without mutation", async () => {
    let valid = true;
    const change = vi.fn();
    const wrapper = mount(ObservationExclusionButton, { props: { observationRef: "one" }, global: { provide: {
      [WORKFLOW_POPULATION_ACTIONS]: { resolve: () => valid ? { excluded: false, restorable: true } : null, change },
    } } });
    valid = false;
    await wrapper.get("button").trigger("click");
    expect(change).not.toHaveBeenCalled();
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("Inspect Load Data") }));
  });
  it("keeps source exclusions and retained-only results read-only", () => {
    const wrapper = mount(ObservationExclusionButton, { props: { observationRef: "one", usedInResult: false }, global: { provide: {
      [WORKFLOW_POPULATION_ACTIONS]: { resolve: () => ({ excluded: false, restorable: false }), change: vi.fn() },
    } } });
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    expect(wrapper.get("button").attributes("title")).toContain("Excluded in My Dataset; restore there");
    const historical = mount(ObservationExclusionButton, { props: { observationRef: "one", usedInResult: true } });
    expect(historical.get("button").attributes("title")).toBe("Used in this result (read-only)");
    expect(historical.get("button").text()).toBe("○");
  });
});
