import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import WorkflowCanvas from "@/views/workflow-builder/WorkflowCanvas.vue";
import { useWorkflowStore, type WorkflowNode } from "@/stores/workflow";

enableAutoUnmount(afterEach);
beforeEach(() => setActivePinia(createPinia()));
const nodes: WorkflowNode[] = [
  { id: "source", type: "DATA", x: 100, y: 100, params: {} },
  { id: "target", type: "PREPROCESS", x: 300, y: 100, params: {} },
];
function canvas() {
  const store = useWorkflowStore();
  const port = { name: "default", label: "Spectra", type_ref: "spectrasherpa://types/SpectralDataset/1.0", required: true };
  const metadata = { category: "data", label: "Test", description: "", parameters: [], input_types: [], output_type: "" };
  store.nodeLibrary = new Map([
    ["DATA", { ...metadata, node_type: "DATA", output_ports: [port] }],
    ["PREPROCESS", { ...metadata, node_type: "PREPROCESS", input_ports: [port], output_ports: [port] }],
  ]);
  vi.spyOn(store, "validateEdge").mockReturnValue({ isValid: true, error: null });
  return mount(WorkflowCanvas, { attachTo: document.body, props: { nodes, edges: [], nodeOutputs: new Map() } });
}
describe("Workflow canvas gestures", () => {
  it("supports assistive click-only activation without rearming a completed pointer drag", async () => {
    const wrapper = canvas();
    await wrapper.get(".port-output").trigger("click", { detail: 0 });
    await wrapper.get(".port-input").trigger("click");
    expect(wrapper.emitted("node-connect")).toHaveLength(1);
    await wrapper.get(".port-output").trigger("click", { detail: 1 });
    expect(wrapper.find(".cancel-connect-pill").exists()).toBe(false);
  });

  it.each(["node", "rubber-band", "port"])("cancels a lost-release %s gesture", async (kind) => {
    const wrapper = canvas();
    const start = () => wrapper.get(kind === "node" ? ".workflow-node" : kind === "port" ? ".port-output" : ".workflow-canvas")
      .trigger("mousedown", { clientX: 130, clientY: 200 });
    await start();
    await wrapper.trigger("mousemove", { clientX: 160, clientY: 230, buttons: 0 });
    expect(wrapper.emitted("update:nodes")).toBeUndefined();
    expect(wrapper.find(".rubber-band").exists()).toBe(false);
    expect(wrapper.find(".cancel-connect-pill").exists()).toBe(false);
    await start();
    window.dispatchEvent(new Event("blur"));
    await wrapper.trigger("mousemove", { clientX: 180, clientY: 250, buttons: 1 });
    expect(wrapper.emitted("update:nodes")).toBeUndefined();
    expect(wrapper.find(".rubber-band").exists()).toBe(false);
    expect(wrapper.find(".cancel-connect-pill").exists()).toBe(false);
  });
  it("keeps the grab offset across scrolling and layout shifts", async () => {
    const wrapper = canvas();
    const surface = wrapper.get(".canvas-surface").element;
    const bounds = { left: 200, top: 100, width: 1500 };
    vi.spyOn(surface, "getBoundingClientRect").mockImplementation(() => bounds as DOMRect);
    await wrapper.get(".workflow-node").trigger("mousedown", { clientX: 320, clientY: 220 });
    bounds.left = 160;
    bounds.top = 80;
    await wrapper.trigger("mousemove", { clientX: 360, clientY: 250, buttons: 1 });
    const latest = wrapper.emitted("update:nodes")!.at(-1)![0] as WorkflowNode[];
    expect(latest[0]).toMatchObject({ x: 180, y: 150 });
    // Screen origin 340/230: original 20px/20px grab offset is preserved.
  });
  it("connects by dragging without moving or selecting either node", async () => {
    const wrapper = canvas();
    await wrapper.get(".port-output").trigger("mousedown", { clientX: 130, clientY: 200 });
    await wrapper.trigger("mousemove", { clientX: 330, clientY: 100, buttons: 1 });
    await wrapper.get(".port-input").trigger("mouseup", { clientX: 330, clientY: 100 });
    await wrapper.get(".port-input").trigger("click");
    expect(wrapper.emitted("node-connect")).toEqual([[{ from: "source", to: "target", fromPort: "default", toPort: "default" }]]);
    expect(wrapper.emitted("update:nodes")).toBeUndefined();
    expect(wrapper.emitted("node-select")).toBeUndefined();
  });
  it("retains click and keyboard connection paths", async () => {
    const wrapper = canvas();
    await wrapper.get(".port-output").trigger("mousedown", { clientX: 130, clientY: 200 });
    await wrapper.get(".port-output").trigger("mouseup", { clientX: 130, clientY: 200 });
    await wrapper.get(".port-input").trigger("click");
    await wrapper.get(".port-output").trigger("keydown", { key: "Enter" });
    await wrapper.get(".port-input").trigger("keydown", { key: " " });
    expect(wrapper.emitted("node-connect")).toHaveLength(2);
  });
  it("cancels outside releases and refuses incompatible connections", async () => {
    const wrapper = canvas();
    await wrapper.get(".port-output").trigger("mousedown", { clientX: 130, clientY: 200 });
    window.dispatchEvent(new MouseEvent("mouseup", { clientX: 900, clientY: 900 }));
    await wrapper.get(".port-input").trigger("click");
    expect(wrapper.emitted("node-connect")).toBeUndefined();
    vi.mocked(useWorkflowStore().validateEdge).mockReturnValue({ isValid: false, error: "Incompatible ports" });
    await wrapper.get(".port-output").trigger("mousedown", { clientX: 130, clientY: 200 });
    await wrapper.get(".port-input").trigger("mouseup", { clientX: 330, clientY: 100 });
    expect(wrapper.emitted("node-connect")).toBeUndefined();
    expect(wrapper.find(".cancel-connect-pill").exists()).toBe(false);
  });
});
