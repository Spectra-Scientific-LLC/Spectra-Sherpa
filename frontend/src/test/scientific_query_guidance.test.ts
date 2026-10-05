import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { attentionSnapshot, focusPlot, releasePlot, setAttentionWindow } from "@/lib/sherpaAttention";
import { observeQueryFilterEvent, recordScientificQueryOutcome, resetScientificQueryGuidance, scientificQuerySuggestion } from "@/lib/scientificQueryGuidance";
import GuidanceToast from "@/components/guidance/GuidanceToast.vue";
vi.mock("@/stores/guidance", () => ({ useGuidanceStore: () => ({ activeToast: null, dismiss: vi.fn() }) }));
describe("scientific query guidance and attention", () => {
  beforeEach(() => { setActivePinia(createPinia()); resetScientificQueryGuidance(); setAttentionWindow("/data"); });
  it("suggests help after repeated rejection, then clears on acceptance", () => {
    recordScientificQueryOutcome(false);
    expect(scientificQuerySuggestion.value).toBeNull();
    recordScientificQueryOutcome(false);
    expect(scientificQuerySuggestion.value).toContain("dataset");
    recordScientificQueryOutcome(false);
    expect(scientificQuerySuggestion.value).toContain("missing");
    recordScientificQueryOutcome(true);
    expect(scientificQuerySuggestion.value).toBeNull();
    recordScientificQueryOutcome(false);
    expect(scientificQuerySuggestion.value).toBeNull();
  });
  it("uses current plot focus but clears stale focus on unmount and navigation", () => {
    focusPlot("plot-3", "node-2");
    expect(attentionSnapshot()).toEqual({ window: "data", surface: "plot", plot_id: "plot-3", node_id: "node-2" });
    releasePlot("plot-1");
    expect(attentionSnapshot().surface).toBe("plot");
    recordScientificQueryOutcome(false); recordScientificQueryOutcome(false);
    expect(scientificQuerySuggestion.value).toContain("plot");
    releasePlot("plot-3");
    expect(attentionSnapshot()).toEqual({ window: "data", surface: "window" });
    focusPlot("plot-4"); setAttentionWindow("/workflow");
    expect(attentionSnapshot().plot_id).toBeUndefined();
  });
  it("handles hosted and Product outcomes and clears on logout reset", () => {
    const rejection = { query_filter: { code: "scientific_query_rejected" } };
    observeQueryFilterEvent(rejection); observeQueryFilterEvent(rejection);
    expect(scientificQuerySuggestion.value).not.toBeNull();
    observeQueryFilterEvent({ payload: { stage: "scientific_query_accepted" } });
    expect(scientificQuerySuggestion.value).toBeNull();
    observeQueryFilterEvent(rejection); observeQueryFilterEvent(rejection);
    resetScientificQueryGuidance();
    expect(scientificQuerySuggestion.value).toBeNull();
  });
  it("renders guidance locally and fills Advisor without automatically submitting", async () => {
    recordScientificQueryOutcome(false); recordScientificQueryOutcome(false);
    const listener = vi.fn();
    window.addEventListener("advisor-prompt-request", listener);
    const wrapper = mount(GuidanceToast);
    expect(wrapper.text()).toContain("Sherpa Advisor Guidance");
    await wrapper.findAll("button").find(b => b.text() === "Ask Sherpa")!.trigger("click");
    expect(listener.mock.calls[0][0].detail.autoSend).toBe(false);
    await wrapper.get('[aria-label="Dismiss"]').trigger("click");
    expect(scientificQuerySuggestion.value).toBeNull();
    window.removeEventListener("advisor-prompt-request", listener);
    wrapper.unmount();
  });
});
