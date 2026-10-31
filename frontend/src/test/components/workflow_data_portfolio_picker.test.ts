import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, put, saveWorkflow, loadWorkflow, workflowState } = vi.hoisted(() => ({
  get: vi.fn(), put: vi.fn(), saveWorkflow: vi.fn(), loadWorkflow: vi.fn(),
  workflowState: { hasUnsavedChanges: false },
}));
vi.mock("@/api/client", () => ({ default: { get, put } }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({
  workflowId: 8, saveWorkflow, loadWorkflow,
  get hasUnsavedChanges() { return workflowState.hasUnsavedChanges; },
}) }));
import WorkflowDataPortfolioPicker from "@/views/workflow-builder/WorkflowDataPortfolioPicker.vue";

const receipt = {
  experiment_id: 3, stage: "raw", selected_file_ids: [4], asset_id: null,
  source_manifest_sha256: "a".repeat(64), collection_definition_sha256: null,
  scientific_collection_sha256: "b".repeat(64), target_authority: null,
  group_column: null,
};
beforeEach(() => {
  get.mockReset().mockImplementation(async (url: string) => ({ data: url.includes("dataset-portfolios")
    ? { active: { name: "Default", dataset_view_id: null, digest: "c".repeat(64), selection: receipt },
        views: [{ id: 12, name: "Selected M5", experiment_id: 3,
          selection_sha256: "d".repeat(64), selection: { ...receipt, selected_file_ids: [5] } }] }
    : { current_revision: null, saved_selection: null },
  }));
  put.mockReset().mockResolvedValue({ data: { revision_number: 1 } });
  saveWorkflow.mockReset().mockResolvedValue(8);
  loadWorkflow.mockReset().mockResolvedValue(undefined);
  workflowState.hasUnsavedChanges = false;
});

describe("workflow Data Portfolio picker", () => {
  it.each([false, true])("requires a revision before claiming a saved portfolio is bound: %s", async (recorded) => {
    const originalGet = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => url.includes("dataset-portfolios")
      ? originalGet(url)
      : { data: {
          current_revision: recorded ? { revision_number: 1 } : null,
          saved_selection: { ...receipt, selected_file_ids: [5], dataset_view_id: 12,
            dataset_view_sha256: "d".repeat(64) },
        } });
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    expect(wrapper.text().includes("Exact source, target, and groups are bound")).toBe(recorded);
    expect(wrapper.find("button").exists()).toBe(!recorded);
    if (!recorded) {
      await wrapper.get("button").trigger("click");
      await flushPromises();
      expect(put).toHaveBeenCalledWith("/workflows/8/data-selections/source_1", expect.objectContaining({
        expected_revision: null,
        selection: expect.objectContaining({ dataset_view_id: 12, dataset_view_sha256: "d".repeat(64) }),
      }));
    }
    wrapper.unmount();
  });

  it("shows the active portfolio and binds a selected named definition without navigation", async () => {
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    expect((wrapper.get("select").element as HTMLSelectElement).value).toBe("active");
    expect(wrapper.text()).toContain("Active · Default");
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/workflows/8/data-selections/source_1", expect.objectContaining({
      origin: "canvas",
      selection: expect.objectContaining({
        experiment_id: 3, selected_file_ids: [5], dataset_view_id: 12,
        dataset_view_sha256: "d".repeat(64),
      }),
    }));
    expect(loadWorkflow).toHaveBeenCalledWith(8, undefined, expect.any(Function));
    expect(wrapper.text()).toContain("bound to this sheet");
    wrapper.unmount();
  });

  it("does not offer a no-op binding for an unavailable unrecorded portfolio", async () => {
    const originalGet = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => url.includes("dataset-portfolios")
      ? originalGet(url)
      : { data: {
          current_revision: null,
          saved_selection: { ...receipt, dataset_view_id: 99, dataset_view_sha256: "f".repeat(64) },
        } });
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.text()).toContain("Choose an available portfolio");
    expect(wrapper.text()).not.toContain("Exact source, target, and groups are bound");
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(put).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("persists dirty canvas edits before changing its data source", async () => {
    workflowState.hasUnsavedChanges = true;
    saveWorkflow.mockImplementation(async () => {
      workflowState.hasUnsavedChanges = false;
      return 8;
    });
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(saveWorkflow).toHaveBeenCalledWith({ createVersion: false, projectId: 2 });
    expect(saveWorkflow.mock.invocationCallOrder[0]).toBeLessThan(put.mock.invocationCallOrder[0]);
    wrapper.unmount();
  });

  it("binds in one action when saving a new sheet assigns its first ID", async () => {
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: null, nodeId: "source_1" },
    });
    saveWorkflow.mockImplementation(async () => {
      await wrapper.setProps({ workflowId: 8 });
      return 8;
    });
    await flushPromises();
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(saveWorkflow).toHaveBeenCalledOnce();
    expect(put).toHaveBeenCalledOnce();
    expect(loadWorkflow).toHaveBeenCalledWith(8, undefined, expect.any(Function));
    wrapper.unmount();
  });

  it("does not reload away edits made while a portfolio request is pending", async () => {
    put.mockImplementation(async () => {
      workflowState.hasUnsavedChanges = true;
      return { data: { revision_number: 1 } };
    });
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(put).toHaveBeenCalledOnce();
    expect(loadWorkflow).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Your edits remain here");
    wrapper.unmount();
  });

  it("guards the reload against edits made while the workflow fetch is pending", async () => {
    loadWorkflow.mockImplementation(async (_id: number, _run: undefined, shouldApply: () => boolean) => {
      workflowState.hasUnsavedChanges = true;
      expect(shouldApply()).toBe(false);
    });
    const wrapper = mount(WorkflowDataPortfolioPicker, {
      props: { projectId: 2, workflowId: 8, nodeId: "source_1" },
    });
    await flushPromises();
    await wrapper.get("select").setValue("view:12");
    await flushPromises();
    expect(wrapper.text()).toContain("Your edits remain here");
    wrapper.unmount();
  });
});
