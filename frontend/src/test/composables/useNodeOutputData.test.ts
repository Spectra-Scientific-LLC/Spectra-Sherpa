import { describe, expect, it } from "vitest";
import { ref } from "vue";
import { useNodeOutputData } from "@/views/workflow-builder/node-detail/composables/useNodeOutputData";

interface TestPort {
  value?: unknown;
}

function makeState(nodeOutput: unknown) {
  return useNodeOutputData({
    nodeOutput: ref(nodeOutput),
    nodeData: ref({}),
    nodeTypeKey: ref("selection.sample_partition"),
    resolvePortPayload: (port: TestPort | null | undefined) => port?.value,
    regressionTargetIdx: ref(0),
    previewRowLimit: 10,
  });
}

describe("useNodeOutputData", () => {
  it("uses dataset shape for axis cardinality when serialized axis arrays are preview-sized", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "X_test",
      ports: {
        X_test: {
          type: "dataset",
          metadata: {},
          value: {
            type: "SherpaDataset",
            shape: [196, 401],
            x_axis: {
              title: "Wavelength",
              units: "nm",
              data: Array.from({ length: 128 }, (_, idx) => 750 + idx * 2),
            },
            y_axis: {
              title: "Sample",
              labels: Array.from({ length: 20 }, (_, idx) => `Sample ${idx + 1}`),
            },
            metadata: {},
          },
        },
      },
    };

    const state = makeState(nodeOutput);

    expect(state.datasetInfo.value?.xAxis?.points).toBe(401);
    expect(state.datasetInfo.value?.yAxis?.nSamples).toBe(196);
    expect(state.datasetInfo.value?.xAxis?.range).toBeNull();
  });

  it("uses explicit axis range metadata instead of a decimated preview-axis range", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "X_test",
      ports: {
        X_test: {
          type: "dataset",
          metadata: { x_range: [4000, 650] },
          value: {
            type: "SherpaDataset",
            shape: [196, 401],
            x_axis: {
              title: "Wavenumber",
              units: "cm-1",
              data: Array.from({ length: 128 }, (_, idx) => 900 + idx),
            },
            y_axis: { title: "Sample", labels: Array.from({ length: 20 }, (_, idx) => `Sample ${idx + 1}`) },
            metadata: {},
          },
        },
      },
    };

    const state = makeState(nodeOutput);

    expect(state.datasetInfo.value?.xAxis?.points).toBe(401);
    expect(state.datasetInfo.value?.xAxis?.range).toEqual([650, 4000]);
  });

  it("flattens higher-dimensional shapes into feature counts", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "cube",
      ports: {
        cube: {
          type: "dataset",
          metadata: {},
          value: {
            type: "SherpaDataset",
            shape: [10, 12, 8],
            x_axis: { title: "Feature" },
            y_axis: { title: "Sample" },
            metadata: {},
          },
        },
      },
    };

    const state = makeState(nodeOutput);

    expect(state.datasetInfo.value?.xAxis?.points).toBe(96);
    expect(state.datasetInfo.value?.yAxis?.nSamples).toBe(10);
  });

  it("prefers explicit sample and feature metadata over raw shape", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "diagnostic",
      ports: {
        diagnostic: {
          type: "dataset",
          metadata: { n_samples: 196, n_features: 3 },
          value: {
            type: "SherpaDataset",
            shape: [3, 401],
            x_axis: { title: "Latent Variable" },
            y_axis: { title: "Sample" },
            metadata: {},
          },
        },
      },
    };

    const state = makeState(nodeOutput);

    expect(state.datasetInfo.value?.xAxis?.points).toBe(3);
    expect(state.datasetInfo.value?.yAxis?.nSamples).toBe(196);
  });

  it("uses dataset shape for secondary port summaries instead of preview label counts", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "X_train",
      ports: {
        X_train: {
          type: "dataset",
          metadata: {},
          value: {
            type: "SherpaDataset",
            shape: [588, 401],
            x_axis: { title: "Wavelength", units: "nm", data: Array.from({ length: 128 }, (_, idx) => idx) },
            y_axis: { title: "Sample", labels: Array.from({ length: 20 }, (_, idx) => `Sample ${idx + 1}`) },
            metadata: {},
          },
        },
        X_test: {
          type: "dataset",
          metadata: {},
          value: {
            type: "SherpaDataset",
            shape: [196, 401],
            x_axis: { title: "Wavelength", units: "nm", data: Array.from({ length: 128 }, (_, idx) => idx) },
            y_axis: { title: "Sample", labels: Array.from({ length: 20 }, (_, idx) => `Sample ${idx + 1}`) },
            metadata: {},
          },
        },
      },
    };

    const state = makeState(nodeOutput);
    const xTest = state.portSummaries.value.find((port) => port.name === "X_test");

    expect(xTest?.xPoints).toBe(401);
    expect(xTest?.yCount).toBe(196);
    expect(xTest?.yCountLabel).toBe("samples");
    expect(xTest?.nLabels).toBe(20);
  });
});
