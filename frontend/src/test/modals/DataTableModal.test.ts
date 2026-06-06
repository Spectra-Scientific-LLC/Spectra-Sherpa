import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";

/* eslint-disable @typescript-eslint/no-explicit-any */

function factory(overrides: Record<string, any> = {}) {
  return mount(DataTableModal, {
    props: {
      modelValue: true,
      nodeType: "data.my_dataset",
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
          props: ["value", "scrollable", "scrollHeight", "virtualScrollerOptions", "size"],
          template: `
            <div
              class="data-table-stub"
              :data-scroll-height="scrollHeight"
              :data-row-count="Array.isArray(value) ? value.length : 0"
              :data-item-size="virtualScrollerOptions?.itemSize"
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
  it("keeps metadata as a separate panel below the scrollable matrix", () => {
    const wrapper = factory();
    const tableWrapper = wrapper.find(".table-wrapper");
    const metadataPanel = wrapper.find(".metadata-panel");

    expect(tableWrapper.exists()).toBe(true);
    expect(metadataPanel.exists()).toBe(true);
    expect(wrapper.find(".data-table-stub").attributes("data-scroll-height")).toBe("flex");
    expect(tableWrapper.element.compareDocumentPosition(metadataPanel.element)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
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
    expect(wrapper.find(".data-table-stub").attributes("data-item-size")).toBe("28");
    expect(wrapper.find(".data-table-stub").attributes("data-size")).toBe("small");

    await wrapper.findAll(".dropdown-stub")[2].setValue("spectrum B");

    expect(wrapper.find(".data-table-stub").attributes("data-row-count")).toBe("6");
    expect(wrapper.text()).toContain("6 matched");
  });
});
