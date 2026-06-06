/* eslint-disable vue/one-component-per-file */
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { describe, expect, it } from "vitest";

import DataQualityPanel from "@/views/data/DataQualityPanel.vue";

const TagStub = defineComponent({
  name: "Tag",
  props: { value: { type: [String, Number], default: "" } },
  template: "<span>{{ value }}</span>",
});

const SpinnerStub = defineComponent({
  name: "ProgressSpinner",
  template: "<div />",
});

const mountPanel = (datasetDict: Record<string, unknown>) =>
  mount(DataQualityPanel, {
    props: { datasetDict },
    global: {
      stubs: {
        Tag: TagStub,
        ProgressSpinner: SpinnerStub,
      },
    },
  });

describe("DataQualityPanel", () => {
  it("renders useful quality checks for feature-table datasets", () => {
    const wrapper = mountPanel({
      data: [
        [1, 2, 3],
        [4, null, 6],
        [7, 8, 9],
      ],
      n_samples: 3,
      n_features: 3,
      x_axis: { labels: ["a", "b", "c"] },
      y_axis: { labels: ["sample 1", "sample 2", "sample 3"] },
      metadata: { data_role: "X_features" },
    });

    expect(wrapper.text()).toContain("Multiple samples loaded");
    expect(wrapper.text()).toContain("3 features detected");
    expect(wrapper.text()).toContain("1 missing values");
    expect(wrapper.text()).toContain("Sample IDs (3)");
  });

  it("separates target labels from sample IDs for classification feature tables", () => {
    const wrapper = mount(DataQualityPanel, {
      props: {
        datasetDict: {
          data: [
            [1, 2],
            [3, 4],
            [5, 6],
          ],
          n_samples: 3,
          n_features: 2,
          x_axis: { labels: ["mean radius", "mean texture"] },
          y_axis: { data: [0, 1, 2], title: "Sample" },
          target: ["malignant", "benign", "benign"],
          target_context: {
            target_type: "categorical",
            target_name: "Label",
            class_names: ["benign", "malignant"],
          },
          metadata: { data_role: "X_features" },
        },
      },
      global: {
        stubs: {
          Tag: TagStub,
          ProgressSpinner: SpinnerStub,
        },
      },
    });

    expect(wrapper.text()).toContain("Target labels (2)");
    expect(wrapper.text()).toContain("benign");
    expect(wrapper.text()).toContain("malignant");
    expect(wrapper.text()).toContain("No sample IDs detected; target labels are available");
    expect(wrapper.text()).not.toContain("No sample labels detected");
  });

  it("shows synthetic concentration target metadata separately from sample row labels", () => {
    const wrapper = mountPanel({
      n_samples: 4,
      n_features: 8,
      target: [
        [100, 0],
        [80, 20],
        [20, 80],
        [0, 100],
      ],
      target_context: {
        target_type: "continuous",
        target_name: "synthetic concentration",
        target_names: ["water", "carbon dioxide"],
        target_units: "ppm",
      },
      metadata: {
        is_spectra: true,
        wavenumbers: [400, 401, 402, 403, 404, 405, 406, 407],
      },
    });

    expect(wrapper.text()).toContain("Target labels (2)");
    expect(wrapper.text()).toContain("ppm");
    expect(wrapper.text()).toContain("water");
    expect(wrapper.text()).toContain("carbon dioxide");
    expect(wrapper.text()).toContain("No sample IDs detected; target labels are available");
  });
});
