import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import api from "@/api/client";
import Panel from "@/views/deploy/InstrumentQCPanel.vue";
vi.mock("@/api/client", () => ({default: {get: vi.fn(), post: vi.fn()}}));
const history = {snapshot: {status: "attention_required", evaluated_at: "2026-09-28T12:00:00Z",
  reasons: ["control_overdue", "unacknowledged_control_failure"], calculation: {due_at: "2026-09-28T11:00:00Z"}},
  events: [{kind: "control", event_id: "failed", occurred_at: "2026-09-28T10:00:00Z", recorded_at: "2026-09-28T10:01:00Z", payload: {measured_values:[0.000001]}}],
  last_event_digest: "a".repeat(64), application_refusal: null};
const button = (w: ReturnType<typeof mount>, label: string) => w.findAll("button").find(b => b.text() === label)!;
beforeEach(() => {vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({data: history}); vi.mocked(api.post).mockResolvedValue({data:{}});});
describe("QC report-only authority", () => {
  it("discloses every concurrent reason and both event times", async () => {
    const w = mount(Panel, {props:{watchId:1}}); await flushPromises();
    expect(w.text()).toContain("Predictions continue");
    expect(w.text()).toContain("control_overdue"); expect(w.text()).toContain("unacknowledged_control_failure");
    expect(w.text()).toContain("Observed: 2026-09-28T10:00:00Z"); expect(w.text()).toContain("Recorded: 2026-09-28T10:01:00Z");
  });
  it("sends exact measured values and the reviewed history identity", async () => {
    const w = mount(Panel, {props:{watchId:1}}); await flushPromises();
    const inputs = w.findAll("input"); await inputs[0].setValue("my-control"); await inputs[1].setValue("2026-09-28T12:00:00Z");
    await w.find("textarea").setValue('{"measured_values":[0.000001,0.5]}');
    await button(w,"Append evidence").trigger("click"); await flushPromises();
    expect(api.post).toHaveBeenCalledWith("/deploy/watches/1/qc", {event_id:"my-control", kind:"control", occurred_at:"2026-09-28T12:00:00Z", expected_last_event_digest:"a".repeat(64), payload:{measured_values:[0.000001,0.5]}});
    expect(w.find("textarea").element.value).toBe("");
  });
  it("retains rejected input and displays a concurrency refusal without retrying", async () => {
    vi.mocked(api.post).mockRejectedValue({response:{data:{detail:"QC history changed; refresh"}}});
    const w=mount(Panel,{props:{watchId:1}}); await flushPromises();
    await w.findAll("input")[1].setValue("2026-09-28T12:00:00Z"); await w.find("textarea").setValue('{"reason":"reviewed"}');
    await button(w,"Append evidence").trigger("click"); await flushPromises();
    expect(w.find('[role="alert"]').text()).toContain("history changed"); expect(api.post).toHaveBeenCalledTimes(1);
    expect(w.find("textarea").element.value).toContain("reviewed");
  });
  it("clears pending form and evidence when the watch changes", async () => {
    const w=mount(Panel,{props:{watchId:1}}); await flushPromises();
    await w.find("textarea").setValue('{"old":true}'); await w.setProps({watchId:2}); await flushPromises();
    expect(w.find("textarea").element.value).toBe(""); expect(api.get).toHaveBeenLastCalledWith("/deploy/watches/2/qc");
    expect(api.post).not.toHaveBeenCalled();
  });
  it("exports the exact retained snapshot and failed event", async () => {
    const create=vi.spyOn(URL,"createObjectURL").mockReturnValue("blob:qc"); vi.spyOn(URL,"revokeObjectURL").mockImplementation(()=>{});
    vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
    const w=mount(Panel,{props:{watchId:1}}); await flushPromises(); await button(w,"Export complete QC history").trigger("click");
    const payload=JSON.parse(await (create.mock.calls[0][0] as Blob).text());
    expect(payload.snapshot).toEqual(history.snapshot); expect(payload.events).toEqual(history.events);
    expect(payload.scope).toContain("assertions"); vi.restoreAllMocks();
  });
});
