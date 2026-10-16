import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/client", () => ({ default: mocks }));
import DatasetCurationPanel from "@/components/DatasetCurationPanel.vue";
import { savedPortfolioInclusion } from "@/utils/datasetCuration";

it("decodes the exact saved portfolio mask without selecting excluded rows", () => {
  const receipt = {
    schema_version: "spectrasherpa-dataset-view/2",
    n_samples: 3,
    observations: [{ sample_id: "a" }, { sample_id: "b" }, { sample_id: "c" }],
    included_sample_mask_hex: "05",
    source_selection: { included_sample_mask_hex: "07" },
  };
  expect(savedPortfolioInclusion(receipt)?.rows).toEqual([
    { sampleId: "a", included: true, editable: true },
    { sampleId: "b", included: false, editable: true },
    { sampleId: "c", included: true, editable: true },
  ]);
  expect(savedPortfolioInclusion({
    ...receipt,
    included_sample_mask_hex: "01",
    source_selection: { included_sample_mask_hex: "05" },
  })?.rows).toEqual([
    { sampleId: "a", included: true, editable: true },
    { sampleId: "b", included: false, editable: false },
    { sampleId: "c", included: false, editable: true },
  ]);
  expect(savedPortfolioInclusion({ ...receipt, observations: [{ sample_id: "a" }] })).toBeNull();
});
const source = {
  experiment_id: 7,
  stage: "raw" as const,
  selected_file_ids: [1, 2],
  asset_id: null,
  target_authority: null,
  group_column: null,
};
function context() {
  return {
    selection_sha256: "source-sha",
    observations_sha256: "rows-sha",
    selection: { included_count: 2 },
    rows: [
      {
        sample_id: "a",
        file_name: "a.csv",
        source_row: 0,
        included: true,
        source_included: true,
        status: "included",
      },
      {
        sample_id: "b",
        file_name: "b.csv",
        source_row: 0,
        included: true,
        source_included: true,
        status: "included",
      },
      {
        sample_id: "source-excluded",
        file_name: "b.csv",
        source_row: 1,
        included: false,
        source_included: false,
        status: "source_excluded",
      },
    ],
  };
}
const dependent = {
  workflow_id: 5,
  workflow_name: "PCA",
  source_node_id: "source",
  expected_revision: 2,
  expected_graph_digest: "graph-sha",
  blocked_reason: null,
};
function button(wrapper: any, text: string) {
  return wrapper.findAll("button").find((b: any) => b.text() === text)!;
}
beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue({ data: [dependent] });
  mocks.post.mockReset().mockImplementation((url: string) =>
    Promise.resolve({
      data: url.endsWith("curation-context")
        ? context()
        : { id: 9, name: "Checked", selection_sha256: "view-sha" },
    }),
  );
});
describe("dataset curation", () => {
  it("preserves sample inclusion when target and group selections change", async () => {
    const wrapper = mount(DatasetCurationPanel, {
      props: { source, embedded: true, controlsOnly: true, autoLoad: true },
    });
    await flushPromises();
    wrapper.vm.toggleSample("b");
    await flushPromises();
    await wrapper.setProps({
      source: {
        ...source,
        target_authority: { column: "moisture", source_digest: "b".repeat(64) },
        group_column: "batch",
      },
    });
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curation-context",
      expect.objectContaining({ group_column: "batch" }),
    );
    expect(wrapper.emitted("selectionChanged")?.at(-1)).toEqual(["exclude"]);
    await wrapper.vm.saveWith("exclude", "Reviewed", "Defective acquisition");
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curations",
      expect.objectContaining({ sample_ids: ["b"], group_column: "batch" }),
    );
  });
  it("loads inclusion state automatically without a review button or duplicate table", async () => {
    const prepareSource = vi.fn();
    const wrapper = mount(DatasetCurationPanel, {
      props: { source, embedded: true, controlsOnly: true, autoLoad: true, prepareSource },
    });
    await flushPromises();
    expect(prepareSource).not.toHaveBeenCalled();
    expect(wrapper.find("table").exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
    const state = wrapper.emitted("inclusionChanged")?.at(-1)?.[0] as {
      rows: Array<{ sampleId: string; included: boolean; editable: boolean }>;
    };
    expect(state.rows.find((row) => row.sampleId === "b")).toEqual({
      sampleId: "b",
      included: true,
      editable: true,
    });
    wrapper.vm.toggleSample("b");
    await flushPromises();
    expect(wrapper.emitted("selectionChanged")?.at(-1)).toEqual(["exclude"]);
    await wrapper.vm.saveWith("exclude", "Reviewed", "Defective acquisition");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curations",
      expect.objectContaining({ sample_ids: ["b"] }),
    );
  });
  it("reviews samples in place and defers the only save action to the portfolio section", async () => {
    const matrix = {
      total_rows: 2,
      total_cols: 1,
      rows_shown: 2,
      cols_shown: 1,
      row_start: 0,
      col_labels: ["1000"],
      row_labels: ["b", "source-excluded"],
      matrix: [[42], [7]],
      truncated: false,
    } as any;
    const wrapper = mount(DatasetCurationPanel, {
      props: { source, embedded: true, matrix, fileName: "b.csv" },
    });
    await button(wrapper, "Select samples").trigger("click");
    await flushPromises();
    expect(wrapper.findAll("table")).toHaveLength(1);
    expect(
      wrapper.get('input[aria-label="Include sample source-excluded"]').attributes("disabled"),
    ).toBeDefined();
    expect(
      (wrapper.get('input[aria-label="Include sample b"]').element as HTMLInputElement).checked,
    ).toBe(true);
    await wrapper.get('input[aria-label="Include sample b"]').setValue(false);
    expect(wrapper.emitted("selectionChanged")?.at(-1)).toEqual(["exclude"]);
    expect(wrapper.find('input[maxlength="120"]').exists()).toBe(false);
    expect(wrapper.findAll("button").some((item) => item.text().startsWith("Save portfolio"))).toBe(
      false,
    );
    await wrapper.vm.saveWith("exclude", "Revised samples", "Defective acquisition");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curations",
      expect.objectContaining({
        name: "Revised samples",
        reason: "Defective acquisition",
        sample_ids: ["b"],
      }),
    );
  });
  it("refreshes the exact source before opening the sample list", async () => {
    const bridge: { wrapper?: ReturnType<typeof mount> } = {};
    const refreshed = {
      ...source,
      target_authority: { column: "moisture", source_digest: "b".repeat(64) },
    };
    const wrapper = mount(DatasetCurationPanel, {
      props: {
        source,
        embedded: true,
        prepareSource: async () => {
          await bridge.wrapper!.setProps({ source: refreshed });
        },
      },
    });
    bridge.wrapper = wrapper;
    await button(wrapper, "Select samples").trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curation-context",
      expect.objectContaining({ target_authority: refreshed.target_authority }),
    );
    expect(wrapper.find("table").exists()).toBe(true);
  });
  it("does not offer matrix exclusions when source rows cannot be matched exactly", async () => {
    const wrapper = mount(DatasetCurationPanel, {
      props: {
        source,
        embedded: true,
        fileName: "b.csv",
        matrix: {
          total_rows: 3,
          total_cols: 1,
          rows_shown: 1,
          cols_shown: 1,
          row_start: 0,
          col_labels: ["1000"],
          row_labels: ["b"],
          matrix: [[42]],
          truncated: true,
        } as any,
      },
    });
    await button(wrapper, "Select samples").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("cannot be matched");
    expect(wrapper.find('input[aria-label="Include sample b"]').exists()).toBe(false);
  });
  it("maps a later matrix page to its exact source row", async () => {
    const later = context();
    later.rows[2] = {
      ...later.rows[2],
      sample_id: "later",
      included: true,
      source_included: true,
      status: "included",
    };
    mocks.post.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("curation-context") ? later : { id: 9 } }),
    );
    const wrapper = mount(DatasetCurationPanel, {
      props: {
        source,
        embedded: true,
        fileName: "b.csv",
        matrix: {
          total_rows: 2,
          total_cols: 1,
          rows_shown: 1,
          cols_shown: 1,
          row_start: 1,
          col_labels: ["1000"],
          row_labels: ["later"],
          matrix: [[7]],
          truncated: true,
        } as any,
      },
    });
    await button(wrapper, "Select samples").trigger("click");
    await flushPromises();
    expect(wrapper.find('input[aria-label="Include sample b"]').exists()).toBe(false);
    await wrapper.get('input[aria-label="Include sample later"]').setValue(false);
    expect(wrapper.emitted("selectionChanged")?.at(-1)).toEqual(["exclude"]);
  });
  it("requires deliberate save and individual workflow update; binds exact context and retains original exclusions", async () => {
    const wrapper = mount(DatasetCurationPanel, { props: { source, seedIds: ["b"] } });
    expect(mocks.post).not.toHaveBeenCalled();
    await button(wrapper, "Review dataset observations").trigger("click");
    await flushPromises();
    expect(
      (wrapper.get('input[aria-label="Curate observation b"]').element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      wrapper.get('input[aria-label="Curate observation source-excluded"]').attributes("disabled"),
    ).toBeDefined();
    expect(button(wrapper, "Save portfolio with exclusions").attributes("disabled")).toBeDefined();
    await wrapper.get('input[maxlength="120"]').setValue("Checked");
    await wrapper.get('textarea[maxlength="2000"]').setValue("Acquisition fault");
    await button(wrapper, "Save portfolio with exclusions").trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/curations",
      expect.objectContaining({
        sample_ids: ["b"],
        expected_selection_sha256: "source-sha",
        expected_observations_sha256: "rows-sha",
        action: "exclude",
      }),
    );
    expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/apply"))).toBe(false);
    await wrapper.setProps({ disabled: true });
    expect(button(wrapper, "Update PCA to Checked").attributes("disabled")).toBeDefined();
    await button(wrapper, "Update PCA to Checked").trigger("click");
    await flushPromises();
    expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/apply"))).toBe(false);
    await wrapper.setProps({ disabled: false });
    mocks.get.mockResolvedValue({ data: [] });
    await button(wrapper, "Update PCA to Checked").trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/experiments/7/dataset-views/9/apply",
      expect.objectContaining({
        workflow_id: 5,
        expected_revision: 2,
        expected_graph_digest: "graph-sha",
      }),
    );
    expect(wrapper.text()).toContain("Rerun it to calculate results");
    expect(wrapper.emitted("applied")?.[0]).toEqual([5]);
  });
  it("rejects stale asynchronous context when switching datasets", async () => {
    let resolve: (value: any) => void = () => {};
    mocks.post.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const wrapper = mount(DatasetCurationPanel, { props: { source } });
    await button(wrapper, "Review dataset observations").trigger("click");
    await wrapper.setProps({ source: { ...source, experiment_id: 8 } });
    resolve({ data: context() });
    await flushPromises();
    expect(wrapper.find("table").exists()).toBe(false);
    expect(wrapper.find('input[maxlength="120"]').exists()).toBe(false);
  });
  it("offers restore only for curation exclusions and explains pinned workflows", async () => {
    const data = context();
    data.rows[1].included = false;
    data.rows[1].status = "curated_excluded";
    mocks.post.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.endsWith("curation-context")
          ? data
          : { id: 9, name: "Restored", selection_sha256: "view-sha" },
      }),
    );
    mocks.get.mockResolvedValue({
      data: [
        {
          ...dependent,
          blocked_reason: "Reviewed PLS cohort is pinned. Start a separate analysis.",
        },
      ],
    });
    const wrapper = mount(DatasetCurationPanel, { props: { source, seedIds: ["b"] } });
    await button(wrapper, "Review dataset observations").trigger("click");
    await flushPromises();
    await wrapper.get('input[maxlength="120"]').setValue("Restored");
    await wrapper.get('textarea[maxlength="2000"]').setValue("Record cleared");
    expect(button(wrapper, "Save portfolio with exclusions").attributes("disabled")).toBeDefined();
    await button(wrapper, "Save portfolio with restored samples").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Reviewed PLS cohort is pinned");
    expect(wrapper.findAll("button").some((b) => b.text().startsWith("Update PCA"))).toBe(false);
  });
});
