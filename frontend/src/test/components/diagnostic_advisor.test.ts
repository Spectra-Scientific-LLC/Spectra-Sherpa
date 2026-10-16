import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { reactive, ref } from "vue";
import type { PcaReview } from "@/utils/sampleReview";
const mode = ref("enterprise");
const config = ref({ advisorContextPolicy: "server", siteProfile: "demo" });
const project = reactive({ currentProjectId: 7 });
const sherpa = reactive({ chatState: "idle" });
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ appMode: mode, appConfig: config, isFeatureEnabled: () => true }),
}));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/sherpa", () => ({ useSherpaStore: () => sherpa }));
const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/advisorPromptActions", () => ({ requestAdvisorPrompt: request }));
import DiagnosticAdvisor from "@/components/DiagnosticAdvisor.vue";
const review = {
  model_kind: "pls",
  target_names: ["Protein", "Moisture"],
  run_id: 42,
  revision: 3,
  graph_digest: "a".repeat(64),
  source_digest: "b".repeat(64),
  rows: [{ id: "a" }, { id: "b" }],
  state: { marked: [], excluded: [] },
} as PcaReview;
function view() {
  return mount(DiagnosticAdvisor, {
    props: {
      review,
      workflowId: 8,
      nodeId: "pls",
      selected: ["a", "b"],
      variables: ["axis:2"],
      responseIndex: 0,
      variableResponseIndex: 1,
      focusedSample: "b",
      stale: false,
    },
  });
}
beforeEach(() => {
  request.mockReset();
  mode.value = "enterprise";
  config.value.advisorContextPolicy = "server";
  sherpa.chatState = "idle";
});
describe("Ask Sherpa diagnostic actions", () => {
  it("distinguishes applicability variables and predictor novelty from response explanations",async()=>{
    const w=view();await w.setProps({variableContext:"applicability",review:{...review,pls_applicability:{unavailable_reason:"Legacy evidence unavailable"}}});
    const button=w.findAll("button").find(button=>button.text()==="Explain predictor-space novelty")!;await button.trigger("click");
    expect(request.mock.calls[0][0]).toContain("Passing a global screen does not establish local support or prediction certainty");
    await w.findAll("button").find(button=>button.text()==="Explain these applicability variables")!.trigger("click");
    expect(request.mock.calls[1][0]).toContain("Q and signed T² applicability contributions");expect(request.mock.calls[1][1].diagnosticScope.reference).toMatchObject({selected_ids:["b"],variable_ids:["axis:2"],response_index:1});w.unmount();
  });

  it("sends sample sets versus the focused variable explanation sample and response only on demand", async () => {
    const w = view();
    expect(request).not.toHaveBeenCalled();
    expect(w.text()).toContain("Variable explanation: b · Moisture");
    await w.findAll("button")[0].trigger("click");
    expect(request.mock.calls[0][1].diagnosticScope.reference).toMatchObject({
      select_all: true,
      response_index: 0,
      variable_ids: [],
    });
    await w.findAll("button")[1].trigger("click");
    expect(request.mock.calls[1][1].diagnosticScope.reference).toMatchObject({
      select_all: false,
      selected_ids: ["b"],
      response_index: 1,
      variable_ids: ["axis:2"],
    });
    expect(w.emitted("opened")).toHaveLength(2);
    w.unmount();
  });
  it("requires an explicit saved comparison run and resets it when the source run changes", async () => {
    const w = view();
    const compare = w.findAll("button")[3];
    expect(compare.attributes("disabled")).toBeDefined();
    await w.get("input").setValue("21");
    await compare.trigger("click");
    expect(request.mock.calls[0][1].diagnosticScope.reference.baseline_run_id).toBe(21);
    await w.setProps({ review: { ...review, run_id: 43 } });
    expect((w.get("input").element as HTMLInputElement).value).toBe("");
    w.unmount();
  });
  it("blocks stale and busy requests, and keeps unsupported deployments explicit", async () => {
    const w = view();
    await w.setProps({ stale: true });
    expect(w.findAll("button").every((b) => b.attributes("disabled") !== undefined)).toBe(true);
    await w.setProps({ stale: false });
    sherpa.chatState = "chatting";
    await flushPromises();
    expect(w.findAll("button")[0].attributes("disabled")).toBeDefined();
    config.value.advisorContextPolicy = "receipt";
    await flushPromises();
    expect(w.text()).toContain("Hybrid diagnostic disclosure is not yet supported");
    expect(w.findAll("button")).toHaveLength(0);
    w.unmount();
  });
});
