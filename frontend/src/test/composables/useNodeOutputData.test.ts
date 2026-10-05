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
    nodeTypeKey: ref("data.train_test_split"),
    resolvePortPayload: (port: TestPort | null | undefined) => port?.value,
    regressionTargetIdx: ref(0),
    previewRowLimit: 10,
  });
}

describe("useNodeOutputData", () => {
  it("summarizes Peak Detection evidence without inventing a matrix shape", () => {
    const state = makeState({
      data: [],
      metadata: {
        diagnostics: { n_samples: 50, n_peaks: 61 },
        scientific_presentation: {
          schema_version: "spectrasherpa-node-presentation/1",
          contract_digest: "b".repeat(64),
          presentation_id: "peak_overlay",
          label: "Spectra with Peaks",
          kind: "visualization",
          source_port: "plots",
          source_ports: ["plots"],
          modes: ["plot"],
          description: "Detected peaks overlaid on the input spectra.",
        },
      },
    });

    expect(state.outputSummary.value).toBe("50 spectra · 61 peak detections");
    expect(state.outputData.value).toMatchObject({
      rows: 50,
      cols: 61,
      rowLabel: "spectra",
      colLabel: "peak detections",
      type: "visualization",
    });
  });

  it("uses dataset shape for axis cardinality when serialized axis arrays are preview-sized", () => {
    const nodeOutput = {
      data: [[0]],
      metadata: {},
      primary_port: "X_test",
      ports: {
        X_test: {
          type: "dataset",
          descriptor: {
            label: "Test spectra",
            scientific_kind: "spectral_dataset",
            shape: [196, 401],
            dimensions: [
              { role: "sample", size: 196 },
              { role: "spectral_variable", size: 401 },
            ],
          },
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
            x_axis: {
              title: "Wavelength",
              units: "nm",
              data: Array.from({ length: 128 }, (_, idx) => idx),
            },
            y_axis: {
              title: "Sample",
              labels: Array.from({ length: 20 }, (_, idx) => `Sample ${idx + 1}`),
            },
            metadata: {},
          },
        },
        X_test: {
          type: "dataset",
          descriptor: {
            label: "Test spectra",
            scientific_kind: "spectral_dataset",
            shape: [196, 401],
            dimensions: [
              { role: "sample", size: 196 },
              { role: "spectral_variable", size: 401 },
            ],
          },
          metadata: {},
          value: {
            type: "SherpaDataset",
            shape: [196, 401],
            x_axis: {
              title: "Wavelength",
              units: "nm",
              data: Array.from({ length: 128 }, (_, idx) => idx),
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
    const xTest = state.portSummaries.value.find((port) => port.name === "X_test");

    expect(xTest?.xPoints).toBe(401);
    expect(xTest?.yCount).toBe(196);
    expect(xTest?.yCountLabel).toBe("samples");
    expect(xTest?.nLabels).toBe(20);
    expect(xTest?.displayLabel).toBe("Test spectra (X_test)");
    expect(xTest?.shape).toEqual([196, 401]);
    expect(xTest?.dimensions).toEqual([
      { role: "sample", size: 196 },
      { role: "spectral_variable", size: 401 },
    ]);
  });
});

it("qualifies historical multi-response Quality fields while retaining selected response metrics", () => {
  const original = {
    data: [[1, 2], [2, 3]],
    metadata: {
      n_targets: 2, target_names: ["CN", "Density"],
      quality_summary: { latest_r2: .9, latest_rmse: 4, r2: .9, rmse: 4 },
      r2_per_target: [.8, null], rmse_per_target: [.2, .001],
    },
  };
  const before = JSON.stringify(original);
  const state = makeState(original);
  expect(state.qualitySummary.value?.latest_r2).toBeUndefined();
  expect(state.qualitySummary.value?.latest_rmse).toBeUndefined();
  expect(state.qualitySummary.value?.extras?.rmse).toBeUndefined();
  expect(state.qualitySummary.value?.qualification).toContain("unqualified");
  expect(state.selectedRegressionR2.value).toBe(.8);
  expect(state.selectedRegressionRmse.value).toBe(.2);
  expect(JSON.stringify(original)).toBe(before);
});
