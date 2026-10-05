import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";

/* eslint-disable @typescript-eslint/no-explicit-any */

function factory(overrides: Record<string, any> = {}) {
  return mount(DataTableModal, {
    props: {
      modelValue: true,
      nodeType: "data.file_load",
      nodeLabel: "My Dataset",
      nodeOutput: {
        data: [
          [1000, 1.2, 2.4],
          [1001, 1.3, 2.5],
        ],
        metadata: {
          data_type: "spectra",
          x_title: "Wavenumber",
          x_units: "cm-1",
          sample_labels: ["condition A", "condition B"],
        },
      },
      ...overrides,
    },
    global: {
      stubs: {
        Dialog: {
          props: ["visible", "header"],
          template: '<div v-if="visible" class="dialog-stub"><slot /></div>',
        },
        DataTable: {
          props: ["value", "scrollable", "scrollHeight", "virtualScrollerOptions", "size", "paginator", "rows"],
          template: `
            <div
              class="data-table-stub"
              :data-scroll-height="scrollHeight"
              :data-row-count="Array.isArray(value) ? value.length : 0"
              :data-item-size="virtualScrollerOptions?.itemSize"
              :data-page-size="rows"
              :data-paginator="paginator"
              :data-size="size || ''"
            >
              <slot />
            </div>
          `,
        },
        Column: true,
        Dropdown: {
          props: ["modelValue", "options", "optionLabel", "optionValue"],
          emits: ["update:modelValue"],
          template: `
            <select
              class="dropdown-stub"
              :value="modelValue"
              @change="$emit('update:modelValue', $event.target.value)"
            >
              <option
                v-for="option in options"
                :key="String(option[optionValue])"
                :value="option[optionValue]"
              >
                {{ option[optionLabel] }}
              </option>
            </select>
          `,
        },
        InputText: true,
        Button: true,
      },
    },
  });
}

describe("DataTableModal", () => {
  it("pages through appended feature columns without changing row identity or nulls", async () => {
    const values = Array.from({ length: 554 }, (_, i) => i === 553 ? null : i);
    const names = values.map((_, i) => i === 553 ? "added::peak_magnitude" : `feature_${i + 1}`);
    const wrapper = factory({ nodeOutput: { data: [values], metadata: { column_names: names } } });
    const vm = wrapper.vm as any;
    expect(vm.columnPageOptions).toHaveLength(12);
    vm.columnPage = 11;
    await wrapper.vm.$nextTick();
    expect(vm.tableColumns.map((c: any) => c.header)).toContain("added::peak_magnitude");
    expect(vm.tableData[0].col_550).toBe(550);
    expect(vm.tableData[0].col_553).toBeNull();
    expect(vm.tableData[0]._index).toBe(1);
    wrapper.unmount();
  });
  it("uses diagnostic sample labels for outlier rows", () => {
    const wrapper = factory({
      nodeType: "diagnostics.outliers",
      nodeLabel: "Outlier Diagnostics",
      nodeOutput: {
        data: [[false], [true]],
        metadata: {
          diagnostics: {
            sample_labels: ["Lavender 01", "Lavender 28"],
          },
        },
      },
    });

    expect((wrapper.vm as any).previewTableData.map((row: any) => row._label_full)).toEqual([
      "Lavender 01",
      "Lavender 28",
    ]);
  });

  it("uses scientific dimension labels for an evaluator actual/predicted table", () => {
    const wrapper = factory({
      nodeType: "diagnostics.regression_evaluator",
      nodeLabel: "Test Evaluation",
      nodeOutput: {
        data: [
          [1, 1.1],
          [2, 1.9],
        ],
        metadata: {},
        descriptor: {
          dimensions: [
            { role: "held_out_sample", size: 2 },
            {
              role: "actual_predicted_value",
              size: 2,
              labels: ["Actual", "Predicted"],
            },
          ],
        },
      },
    });

    const columns = (wrapper.vm as any).tableColumns;
    expect(columns.map((column: any) => column.header)).toEqual(["#", "Actual", "Predicted"]);
  });

  it("uses analyte names instead of inherited spectral coordinates for target matrices", () => {
    const wrapper = factory({
      nodeOutput: {
        data: [
          [20, 3],
          [25, 4],
        ],
        metadata: {
          target_names: ["Carbon dioxide", "Methane"],
          wavenumbers: [600, 600.5],
          sample_labels: ["sample_001", "sample_002"],
          scientific_presentation: {
            schema_version: "spectrasherpa-node-presentation/1",
            contract_digest: "a".repeat(64),
            presentation_id: "targets",
            kind: "target_matrix",
            source_port: "target",
            source_ports: ["target"],
            modes: ["table"],
          },
        },
      },
    });

    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Sample",
      "Carbon dioxide",
      "Methane",
    ]);
  });

  it("labels PLS explained-variance rows and domains without borrowing sample labels", () => {
    const wrapper = factory({
      nodeType: "classification.plsda",
      nodeLabel: "Train PLS-DA Classifier",
      nodeOutput: {
        data: [
          [0.31, 0.32],
          [0.32, 0.05],
        ],
        metadata: {
          sample_labels: ["CL__B1", "ML__B1"],
          scientific_presentation: {
            schema_version: "spectrasherpa-node-presentation/1",
            contract_digest: "a".repeat(64),
            presentation_id: "explained_variance",
            kind: "pls_explained_variance",
            source_port: "explained_variance",
            source_ports: ["explained_variance"],
            modes: ["plot", "table"],
          },
        },
      },
    });

    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Latent Variable",
      "X variance",
      "Y variance",
    ]);
    expect((wrapper.vm as any).previewTableData.map((row: any) => row._label_full)).toEqual([
      "LV 1",
      "LV 2",
    ]);
  });

  it("labels coefficient tables by variables and response classes", () => {
    const wrapper = factory({
      nodeType: "classification.plsda",
      nodeLabel: "Class-Response Coefficients",
      nodeOutput: {
        data: [
          [0.1, 0.2, 0.3],
          [0.4, 0.5, 0.6],
        ],
        metadata: {
          sample_labels: ["wrong sample 1", "wrong sample 2"],
          target_names: [],
          classes: ["class_0", "class_1", "class_2"],
        },
        descriptor: {
          dimensions: [
            { role: "spectral_variable", size: 2 },
            { role: "target", size: 3 },
          ],
        },
        ports: {
          loadings: {
            value: {
              x_axis: { labels: ["alcohol", "malic acid"] },
            },
          },
        },
      },
    });

    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Variable",
      "class_0",
      "class_1",
      "class_2",
    ]);
    expect((wrapper.vm as any).previewTableData.map((row: any) => row._label_full)).toEqual([
      "alcohol",
      "malic acid",
    ]);
  });

  it("shows all six canonical regression-comparison fields", () => {
    const wrapper = factory({
      nodeType: "diagnostics.regression_evaluator",
      nodeLabel: "Test Evaluation",
      nodeOutput: {
        data: [
          {
            sample: "1",
            target: "Moisture",
            reference: 10,
            predicted: 9.8,
            residual: 0.2,
            role: "held_out_test",
          },
        ],
        metadata: {
          column_names: ["sample", "target", "reference", "predicted", "residual", "role"],
        },
      },
    });

    expect((wrapper.vm as any).dataShape).toEqual({ rows: 1, cols: 6 });
    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "sample",
      "target",
      "reference",
      "predicted",
      "residual",
      "role",
    ]);
  });

  it("shows per-class rows from a structured classification metric record", () => {
    const wrapper = factory({
      nodeType: "diagnostics.classification_evaluator",
      nodeLabel: "Test Evaluation",
      nodeOutput: {
        data: [],
        metadata: {},
        presentation_value: {
          task_type: "classification",
          n_samples: 8,
          accuracy: 0.625,
          per_class: [
            {
              label: "Lavandula angustifolia",
              support: 5,
              predicted_count: 6,
              precision: 0.8333,
              recall: 1,
              specificity: 0.6667,
              f1: 0.9091,
            },
            {
              label: "Lavandula latifolia",
              support: 2,
              predicted_count: 0,
              precision: 0,
              recall: 0,
              specificity: 1,
              f1: 0,
            },
          ],
        },
      },
    });

    expect((wrapper.vm as any).dataShape).toEqual({ rows: 2, cols: 7 });
    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "label",
      "support",
      "predicted_count",
      "precision",
      "recall",
      "specificity",
      "f1",
    ]);
    expect((wrapper.vm as any).previewTableData[0]).toMatchObject({
      label: "Lavandula angustifolia",
      support: 5,
      recall: 1,
      specificity: 0.6667,
    });
  });

  it("shows one held-out reference and prediction decision per classification sample", () => {
    const wrapper = factory({
      nodeType: "diagnostics.classification_evaluator",
      nodeLabel: "Test Evaluation",
      nodeOutput: {
        data: [],
        metadata: {},
        presentation_value: {
          schema_version: "spectrasherpa-classification-comparison/1",
          shape: [2, 5],
          data: [
            { sample: "1", reference: "0", predicted: "0", correct: true, role: "held_out_test" },
            { sample: "2", reference: "1", predicted: "2", correct: false, role: "held_out_test" },
          ],
          metadata: {
            column_names: ["sample", "reference", "predicted", "correct", "role"],
          },
        },
      },
    });

    expect((wrapper.vm as any).dataShape).toEqual({ rows: 2, cols: 5 });
    expect((wrapper.vm as any).previewTableData[1]).toMatchObject({
      sample: "2",
      reference: "1",
      predicted: "2",
      correct: false,
    });
  });

  it("shows scalar metric records as one inspectable row", () => {
    const wrapper = factory({
      nodeType: "diagnostics.regression_evaluator",
      nodeLabel: "Test Evaluation",
      nodeOutput: {
        data: [],
        metadata: {},
        presentation_value: {
          task_type: "regression",
          n_samples: 12,
          rmse: 1.25,
          r2: 0.88,
          fold_assignments: [1, 2, 3],
        },
      },
    });

    expect((wrapper.vm as any).dataShape).toEqual({ rows: 1, cols: 4 });
    expect((wrapper.vm as any).previewTableData[0]).toMatchObject({
      task_type: "regression",
      n_samples: 12,
      rmse: 1.25,
      r2: 0.88,
    });
  });

  it("shows nested peak membership without object coercion", () => {
    const wrapper = factory();
    const format = (wrapper.vm as any).formatValue;
    expect(format([{ position: 1200 }, { position: 1202 }], false)).toBe("2 records (hover for details)");
    expect(format([1, 2], false)).toBe("[1,2]");
    expect(format(null, true)).toBe("-");
  });

  it("keeps metadata as a separate panel below the scrollable matrix", () => {
    const wrapper = factory();
    const tableWrapper = wrapper.find(".table-wrapper");
    const metadataPanel = wrapper.find(".metadata-panel");

    expect(tableWrapper.exists()).toBe(true);
    expect(metadataPanel.exists()).toBe(true);
    // A flex viewport collapses when provenance panels exhaust the modal height.
    expect(wrapper.find(".data-table-stub").attributes("data-scroll-height")).toBe("360px");
    expect(wrapper.find(".data-table-stub").attributes("data-item-size")).toBeUndefined();
    expect(tableWrapper.element.compareDocumentPosition(metadataPanel.element)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("bounds large previews with pagination instead of assuming fixed row heights", async () => {
    const wrapper = factory({ nodeOutput: { data: Array.from({ length: 155 }, (_, i) => ({
      median_pos: i, members: [{ label: "A long label that can wrap over several lines" }],
    })), metadata: {} } });
    (wrapper.vm as any).rowLimit = 0;
    await wrapper.vm.$nextTick();
    const table = wrapper.find(".data-table-stub");
    expect(table.attributes("data-paginator")).toBe("true");
    expect(table.attributes("data-page-size")).toBe("100");
    expect(table.attributes("data-row-count")).toBe("155");
    expect(table.attributes("data-item-size")).toBeUndefined();
  });

  it("shows every scientific field represented by a regression-comparison plot", () => {
    const wrapper = factory({
      nodeType: "output.plot",
      nodeLabel: "Predicted vs Actual",
      nodeOutput: {
        data: [
          {
            type: "scatter",
            mode: "markers",
            name: "Moisture",
            x: [10, 11],
            y: [9.8, 11.1],
            text: ["Corn 1", "Corn 2"],
            customdata: [
              [0.2, "held_out_test"],
              [-0.1, "held_out_test"],
            ],
          },
          {
            type: "scatter",
            mode: "lines",
            name: "1:1 Line",
            x: [9, 12],
            y: [9, 12],
          },
        ],
        metadata: {
          source_schema: "spectrasherpa-regression-comparison/1",
          role: "held_out_test",
        },
      },
    });

    expect((wrapper.vm as any).isPlotlyFormat).toBe(true);
    expect((wrapper.vm as any).isRowDictFormat).toBe(true);
    expect((wrapper.vm as any).dataShape).toEqual({ rows: 2, cols: 6 });
    expect((wrapper.vm as any).tableColumns.map((column: any) => column.header)).toEqual([
      "#",
      "sample",
      "target",
      "reference",
      "predicted",
      "residual",
      "role",
    ]);
    expect(wrapper.find(".data-table-stub").attributes("data-row-count")).toBe("2");
    expect((wrapper.vm as any).previewTableData[0]).toMatchObject({
      sample: "Corn 1",
      target: "Moisture",
      reference: 10,
      predicted: 9.8,
      residual: 0.2,
      role: "held_out_test",
    });
  });

  it("filters Compare vs Library HQI rows by spectrum before applying the row limit", async () => {
    const rows = Array.from({ length: 12 }, (_, index) => ({
      sample: index < 6 ? "spectrum A" : "spectrum B",
      sample_rank: (index % 6) + 1,
      library: `Species ${index + 1}`,
      hqi: 1000 - index,
      candidate_status: "review",
    }));

    const wrapper = factory({
      nodeType: "analysis.compare_library",
      nodeLabel: "Compare vs. Library",
      nodeOutput: {
        data: rows,
        metadata: {
          column_names: ["sample", "sample_rank", "library", "hqi", "candidate_status"],
        },
      },
    });

    expect(wrapper.text()).toContain("Spectrum");
    expect(wrapper.find(".data-table-stub").attributes("data-row-count")).toBe("6");
    expect(wrapper.find(".data-table-stub").attributes("data-item-size")).toBeUndefined();
    expect(wrapper.find(".data-table-stub").attributes("data-size")).toBe("small");

    await wrapper.findAll(".dropdown-stub")[2].setValue("spectrum B");

    expect(wrapper.find(".data-table-stub").attributes("data-row-count")).toBe("6");
    expect(wrapper.text()).toContain("6 matched");
  });
});
