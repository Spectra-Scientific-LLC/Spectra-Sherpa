import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import api from "@/api/client";
import Panel from "@/views/deploy/QualificationPanel.vue";
import Applications from "@/views/deploy/QualificationApplications.vue";
vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const record = {kind: "assessment", record_digest: "dossier-1", context_digest: "context-1", payload: {
  assessment: "criteria_met", context: {intended_use: "Screen fuels", intended_population: "Summer fuels", instrument_id: "NIR-1"},
  policy: {policy_name: "Lab", policy_version: "1"}, criteria: [{name: "rmsep", state: "met", detail: "0.5 <= 1"}],
}};
function button(wrapper: ReturnType<typeof mount>, text: string) { return wrapper.findAll("button").find(item => item.text() === text)!; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({data: {records: [record]}}); vi.mocked(api.post).mockResolvedValue({data: {}}); });
describe("qualification evidence and decisions", () => {
  it("requires exact-context acknowledgement and reason before submitting the dossier identity", async () => {
    const wrapper = mount(Panel, {props: {workflowId: 3}}); await flushPromises();
    expect(wrapper.text()).toContain("No ASTM or regulatory compliance is implied");
    await button(wrapper, "Review this assessment").trigger("click");
    const accept = button(wrapper, "Accept under declared policy");
    expect(accept.attributes("disabled")).toBeDefined();
    await wrapper.find('textarea').setValue("Reviewed frozen use");
    expect(accept.attributes("disabled")).toBeDefined();
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await accept.trigger("click"); await flushPromises();
    expect(api.post).toHaveBeenCalledWith("/deploy/workflows/3/qualification/decisions", {
      dossier_digest: "dossier-1", accepted_context_digest: "context-1", decision: "accepted_under_declared_policy", reason: "Reviewed frozen use",
    });
  });
  it("does not accept incomplete evidence", async () => {
    vi.mocked(api.get).mockResolvedValue({data: {records: [{...record, payload: {...record.payload, assessment: "incomplete"}}]}});
    const wrapper = mount(Panel, {props: {workflowId: 3}}); await flushPromises();
    await button(wrapper, "Review this assessment").trigger("click");
    await wrapper.find('textarea').setValue("Insufficient instrument evidence");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    expect(button(wrapper, "Accept under declared policy").attributes("disabled")).toBeDefined();
    expect(button(wrapper, "Record pending review").attributes("disabled")).toBeUndefined();
  });
  it("clears review when workflow changes", async () => {
    const wrapper = mount(Panel, {props: {workflowId: 3}}); await flushPromises();
    await button(wrapper, "Review this assessment").trigger("click");
    await wrapper.find('textarea').setValue("Reviewed");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await wrapper.setProps({workflowId: 4}); await flushPromises();
    expect(wrapper.find("fieldset").exists()).toBe(false);
    expect(api.post).not.toHaveBeenCalled();
  });
  it("shows refusal without reporting acceptance saved", async () => {
    vi.mocked(api.post).mockRejectedValue({response: {data: {detail: "Application changed; reassess"}}});
    const wrapper = mount(Panel, {props: {workflowId: 3}}); await flushPromises();
    await button(wrapper, "Review this assessment").trigger("click");
    await wrapper.find('textarea').setValue("Reviewed");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await button(wrapper, "Accept under declared policy").trigger("click"); await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toContain("Application changed");
    expect(wrapper.find("fieldset").exists()).toBe(true);
  });
  it("exports full evidence", async () => {
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:qualification");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const wrapper = mount(Panel, {props: {workflowId: 3}}); await flushPromises();
    await button(wrapper, "Export complete evidence history").trigger("click");
    const output = JSON.parse(await (create.mock.calls[0][0] as Blob).text());
    expect(output.records).toEqual([record]); expect(output.workflow_id).toBe(3);
    expect(output.scope).toContain("not authenticated certification");
    vi.restoreAllMocks();
  });
  it("discovers hosted candidates without watch calls and clears selection on project change", async () => {
    vi.mocked(api.get).mockResolvedValue({data: [{canonical_artifact_id: 9, workflow_id: 3, name: "Imported PLS", artifact_digest: "exact-model"}]});
    const wrapper = mount(Applications, {props: {projectId: 7}, global: {stubs: {QualificationPanel: true}}}); await flushPromises();
    expect(api.get).toHaveBeenCalledExactlyOnceWith("/deploy/projects/7/qualification-applications");
    await wrapper.findAll("option")[1].setSelected();
    expect(wrapper.find("qualification-panel-stub").attributes("canonicalartifactid")).toBe("9");
    await wrapper.setProps({projectId: 8}); await flushPromises();
    expect(wrapper.find("qualification-panel-stub").exists()).toBe(false);
  });
});
