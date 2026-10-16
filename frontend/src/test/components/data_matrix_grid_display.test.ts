import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import DataMatrixGrid from "@/views/data/DataMatrixGrid.vue";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
import type { DataMatrixResponse } from "@/stores/data";

afterEach(() => { useDisplayPreferences().maxRows = 300; });

describe("dataset matrix visual row limit", () => {
  it("caps sample rows, not feature columns, and responds to the shared setting", async () => {
    const matrix = {
      row_start: 0, rows_shown: 400, total_rows: 400, col_start: 0,
      cols_shown: 2, total_cols: 2, truncated: false,
      row_labels: Array.from({ length: 400 }, (_, i) => `sample-${i}`),
      col_labels: ["feature-1", "feature-2"],
      matrix: Array.from({ length: 400 }, () => [0.5, 0.6]),
      x_title: "Wavenumber", x_units: "cm-1", y_title: "Sample",
    } as unknown as DataMatrixResponse;
    const wrapper = mount(DataMatrixGrid, { props: { matrix } });
    expect((wrapper.vm as unknown as { displayedRows: unknown[] }).displayedRows).toHaveLength(300);
    expect(wrapper.text()).toContain("300 of 400 fetched rows");
    useDisplayPreferences().maxRows = 500;
    await nextTick();
    expect((wrapper.vm as unknown as { displayedRows: unknown[] }).displayedRows).toHaveLength(400);
    await wrapper.setProps({ matrix: {
      ...matrix, row_labels: ["sample-1"], rows_shown: 1, total_rows: 1,
      col_labels: Array.from({ length: 501 }, (_, i) => `feature-${i}`),
      cols_shown: 501, total_cols: 501, matrix: [Array(501).fill(0.5)],
    } });
    expect(wrapper.findAll("thead th")).toHaveLength(502);
    expect((wrapper.vm as unknown as { displayedRows: unknown[] }).displayedRows).toHaveLength(1);
    wrapper.unmount();
  });
});
