import { describe, expect, it } from "vitest";
import { buildNodeOutput } from "@/utils/nodeOutput";
import type { NodePortMetadata, NodePresentationContract, ScientificPresentation } from "@/types";

const contextContract = (bindings: Record<string, string>, labelPorts: string[] = []): NodePresentationContract => ({
  digest: "test-declarations",
  payload: {
    schema_version: "spectrasherpa-node-presentation/1",
    default_presentation: Object.keys(bindings)[0] ?? "diagnostics",
    presentations: [
      ...Object.entries(bindings).map(([port, source]): ScientificPresentation => ({
        presentation_id: port, label: port, kind: "target_matrix", modes: ["table"],
        source_ports: [port], description: "", output_binding: [source, "target_context"],
      })),
      ...(labelPorts.length ? [{ presentation_id: "diagnostics", label: "Diagnostics", kind: "t2_q_diagnostics",
        modes: ["table" as const], source_ports: labelPorts, description: "", sample_labels_field: "sample_labels" }] : []),
    ],
  },
});

describe("buildNodeOutput", () => {
  it("preserves shared scientific metadata while allowing primary-port metadata to take precedence", () => {
    const output = buildNodeOutput({
      default: { data: [[1]], metadata: { n_samples: 1 } },
      metadata: { type: "HCA", n_samples: 99, linkage: "ward" },
      plots: { dendrogram: { data: [{ x: [0, 1], y: [1, 2] }] } },
    });
    expect(output.metadata).toMatchObject({ type: "HCA", n_samples: 1, linkage: "ward" });
    expect(output.plots).toHaveProperty("dendrogram");
  });
  const descriptor = (
    portName: string,
    scientificKind: string,
    shape: number[] | null,
    viewModes: string[],
  ) => ({
    schema_version: "spectrasherpa-scientific-value/1" as const,
    port_name: portName,
    type_ref: `spectrasherpa://types/${scientificKind}/1.0`,
    label: portName,
    scientific_kind: scientificKind,
    view_kind: shape ? "matrix" : "metric_record",
    shape,
    dimensions: (shape ?? []).map((size, index) => ({ role: `axis_${index + 1}`, size })),
    view_modes: viewModes,
    content_categories: ["unclassified"],
    shape_valid: true,
    shape_issue: null,
  });

  it("retains canonical PLS ports and attaches executor diagnostics", () => {
    const output = buildNodeOutput(
      {
        default: [[1.1], [2.2]],
        fitted_state: { schema_version: "sherpa-fitted-pls-state-envelope/1" },
        vip_scores: [0.8, 1.2],
      },
      [
        { name: "default" },
        { name: "fitted_state" },
        { name: "vip_scores" },
      ] as unknown as NodePortMetadata[],
      {
        algorithm_id: "simpls",
        effective_n_components: 2,
        x_explained_variance: [0.7, 0.2],
        y_explained_variance: [0.8, 0.1],
      },
    );

    expect(output.primary_port).toBe("default");
    expect(output.data).toEqual([[1.1], [2.2]]);
    expect(output.ports?.vip_scores.data).toEqual([0.8, 1.2]);
    expect(output.ports?.fitted_state.value).toEqual({
      schema_version: "sherpa-fitted-pls-state-envelope/1",
    });
    expect(output.metadata.diagnostics).toEqual({
      algorithm_id: "simpls",
      effective_n_components: 2,
      x_explained_variance: [0.7, 0.2],
      y_explained_variance: [0.8, 0.1],
    });
  });

  it("retains a canonical visualization as the primary output", () => {
    const visualization = {
      schema_version: "spectra-plot/1",
      plot_type: "scatter",
      data: [{ x: [1, 2], y: [1.1, 1.9], type: "scatter" }],
      layout: { title: "Predicted vs Actual" },
      metadata: { source: "eval_1" },
    };
    const output = buildNodeOutput({ visualization }, [
      { name: "visualization", type_ref: "sherpa://types/Visualization/1.0" },
    ] as unknown as NodePortMetadata[]);

    expect(output.primary_port).toBe("visualization");
    expect(output.data).toEqual(visualization.data);
    expect(output.metadata).toEqual(visualization.metadata);
    expect(output.ports?.visualization.value).toEqual(visualization);
  });

  it("selects a shaped evaluator projection instead of collapsing onto its metrics record", () => {
    const output = buildNodeOutput(
      {
        default: { rmse: 0.3, r2: 0.9 },
        visualization: {
          data: [
            [1, 1.1],
            [2, 1.9],
          ],
          metadata: { type: "RegressionTest" },
        },
      },
      [{ name: "default" }, { name: "visualization" }] as unknown as NodePortMetadata[],
      null,
      {
        default: descriptor("default", "validation_result", null, ["record"]),
        visualization: descriptor("visualization", "visualization", [2, 2], ["plot", "table"]),
      },
    );

    expect(output.primary_port).toBe("visualization");
    expect(output.data).toEqual([
      [1, 1.1],
      [2, 1.9],
    ]);
    expect(output.descriptor?.shape).toEqual([2, 2]);
    expect(output.ports?.default.value).toEqual({ rmse: 0.3, r2: 0.9 });
  });

  it("selects the first declared shaped split port when no default exists", () => {
    const output = buildNodeOutput(
      { X_train: [[1, 2]], y_train: [3] },
      [{ name: "X_train" }, { name: "y_train" }] as unknown as NodePortMetadata[],
      null,
      {
        X_train: descriptor("X_train", "spectral_dataset", [1, 2], ["table", "spectral_plot"]),
        y_train: descriptor("y_train", "target_matrix", [1, 1], ["table"]),
      },
    );

    expect(output.primary_port).toBe("X_train");
    expect(output.descriptor?.shape).toEqual([1, 2]);
    expect(output.ports?.y_train.descriptor?.shape).toEqual([1, 1]);
  });

  it("keeps equal-sized training and test response identities separate", () => {
    const dataset = (label: string) => ({ type: "SherpaDataset", data: [[1]],
      y_axis: { labels: [label] }, target_context: { target_names: ["Moisture"] } });
    const output = buildNodeOutput({ X_train: dataset("train-A"), X_test: dataset("test-B"), y_train: [2], y_test: [3] },
      undefined, null, {
        y_train: descriptor("y_train", "target_matrix", [1, 1], ["table"]),
        y_test: descriptor("y_test", "target_matrix", [1, 1], ["table"]),
      }, contextContract({ y_train: "X_train", y_test: "X_test" }));
    expect(output.ports?.y_train.metadata.sample_labels).toEqual(["train-A"]);
    expect(output.ports?.y_test.metadata.sample_labels).toEqual(["test-B"]);
    const missing = buildNodeOutput({ X_train: dataset("train-A"), y_test: [3] }, undefined, null,
      { y_test: descriptor("y_test", "target_matrix", [1, 1], ["table"]) }, contextContract({ y_test: "X_test" }));
    expect(missing.ports?.y_test.metadata.sample_labels).toBeUndefined();
  });

  it("carries dataset target names and sample labels onto TargetMatrix ports", () => {
    const output = buildNodeOutput(
      {
        default: {
          type: "SherpaDataset",
          data: [
            [0.1, 0.2],
            [0.3, 0.4],
          ],
          target_context: {
            target_names: ["Carbon dioxide", "Methane"],
            target_units: "ppm",
          },
          metadata: { wavenumbers: [600, 600.5] },
          y_axis: { labels: ["sample_001", "sample_002"] },
        },
        target: [
          [20, 3],
          [25, 4],
        ],
      },
      [
        { name: "default", type_ref: "spectrasherpa://types/SpectralDataset/1.0" },
        { name: "target", type_ref: "spectrasherpa://types/TargetMatrix/1.0" },
      ] as unknown as NodePortMetadata[],
      null,
      {
        default: descriptor("default", "spectral_dataset", [2, 2], ["table", "plot"]),
        target: descriptor("target", "target_matrix", [2, 2], ["table"]),
      },
      contextContract({ target: "default" }),
    );

    expect(output.ports?.target.metadata).toMatchObject({
      sample_labels: ["sample_001", "sample_002"],
      target_names: ["Carbon dioxide", "Methane"],
      column_names: ["Carbon dioxide", "Methane"],
      target_units: "ppm",
    });
    expect(output.ports?.target.metadata).not.toHaveProperty("wavenumbers");
  });

  it("uses the selected response name for a one-column TargetMatrix", () => {
    const output = buildNodeOutput(
      {
        default: {
          type: "SherpaDataset",
          data: [[0.1, 0.2]],
          target_context: {
            target_names: ["Carbon dioxide", "Methane"],
            selected_target: "Methane",
          },
          y_axis: { labels: ["sample_001"] },
        },
        target: [3],
      },
      [{ name: "default" }, { name: "target" }] as unknown as NodePortMetadata[],
      null,
      {
        default: descriptor("default", "spectral_dataset", [1, 2], ["table", "plot"]),
        target: descriptor("target", "target_matrix", [1, 1], ["table"]),
      },
      contextContract({ target: "default" }),
    );

    expect(output.ports?.target.metadata.target_names).toEqual(["Methane"]);
  });

  it("carries result labels only onto explicitly declared row-wise ports", () => {
    const labels = ["sample_001", "sample_002", "sample_003"];
    const output = buildNodeOutput(
      {
        T2: [1.2, 2.3, 3.4],
        Q: [0.1, 0.2, 0.3],
        flags: [false, true, false],
        sample_labels: labels,
        feature_importance: [4, 5, 6],
      },
      [{ name: "T2" }, { name: "Q" }, { name: "flags" }, { name: "feature_importance" }] as unknown as NodePortMetadata[],
      null,
      {
        T2: descriptor("T2", "array_1d", [3], ["table", "plot"]),
        Q: descriptor("Q", "array_1d", [3], ["table", "plot"]),
        flags: descriptor("flags", "array_1d", [3], ["table"]),
        feature_importance: descriptor("feature_importance", "array_1d", [3], ["table"]),
      },
      contextContract({}, ["T2", "Q", "flags"]),
    );

    expect(output.ports?.T2.metadata.sample_labels).toEqual(labels);
    expect(output.ports?.Q.metadata.sample_labels).toEqual(labels);
    expect(output.ports?.flags.metadata.sample_labels).toEqual(labels);
    expect(output.ports?.feature_importance.data).toEqual([4, 5, 6]);
    expect(output.ports?.feature_importance.metadata.sample_labels).toBeUndefined();
  });

  it("does not guess a response cohort from port spelling or equal sizes", () => {
    const result = { X_train: { type: "SherpaDataset", data: [[1]], y_axis: { labels: ["A"] } }, y_train: [2] };
    const descriptors = { y_train: descriptor("y_train", "target_matrix", [1, 1], ["table"]) };
    expect(buildNodeOutput(result, undefined, null, descriptors).ports?.y_train.metadata.sample_labels).toBeUndefined();
    const renamed = { acquired: result.X_train, measured: result.y_train };
    const output = buildNodeOutput(renamed, undefined, null,
      { measured: descriptor("measured", "target_matrix", [1, 1], ["table"]) },
      contextContract({ measured: "acquired" }));
    expect(output.ports?.measured.metadata.sample_labels).toEqual(["A"]);
  });

  it("retains the summary carried by a typed StatisticsSummary port", () => {
    const rows = [
      { pc: 1, mean: 0, std: 0.51 },
      { pc: 2, mean: 0, std: 0.33 },
    ];
    const summary = {
      n_observations: 50,
      n_components: 2,
      total_variance_explained: 0.963,
    };
    const output = buildNodeOutput(
      {
        statistics: {
          input_type: "PCA",
          summary,
          data: rows,
          metadata: { type: "PCA", shape: [50, 2] },
        },
      },
      [{ name: "statistics" }] as unknown as NodePortMetadata[],
      null,
      {
        statistics: descriptor("statistics", "statistics_summary", null, ["record", "table"]),
      },
    );

    expect(output.data).toEqual(rows);
    expect(output.metadata).toMatchObject({ type: "PCA", input_type: "PCA", summary });
    expect(output.ports?.statistics.metadata).toMatchObject({ input_type: "PCA", summary });
  });

  it("honors retained typed ports even when the result includes top-level metadata", () => {
    const output = buildNodeOutput(
      { result: [[2.5], [4]], model_id: "exact-model", metadata: { model_type: "linear_regression" } },
      undefined, undefined,
      {
        result: descriptor("result", "numeric_matrix", [2, 1], ["table"]),
        model_id: descriptor("model_id", "model_reference", null, ["model_summary"]),
      },
    );
    expect(output.ports?.result.data).toEqual([[2.5], [4]]);
    expect(output.ports?.model_id.value).toBe("exact-model");
    expect(output.model_id).toBe("exact-model");
  });

  it("restores renderable previews from persisted numerical compaction records", () => {
    const output = buildNodeOutput(
      {
        vip_scores: {
          _truncated_sequence: true,
          length: 700,
          preview: [0.8, 1.2, 0.9],
          last: 0.7,
        },
        x_scores: {
          _truncated_matrix: true,
          rows: 60,
          preview: [
            { _truncated_sequence: true, length: 3, preview: [1, 2, 3], last: 3 },
            { _truncated_sequence: true, length: 3, preview: [4, 5, 6], last: 6 },
          ],
        },
        x_loadings: [
          { _truncated_sequence: true, length: 700, preview: [0.1, 0.2], last: 0.3 },
          { _truncated_sequence: true, length: 700, preview: [0.4, 0.5], last: 0.6 },
        ],
      },
      [
        { name: "vip_scores" },
        { name: "x_scores" },
        { name: "x_loadings" },
      ] as unknown as NodePortMetadata[],
    );

    expect(output.ports?.vip_scores.data).toEqual([0.8, 1.2, 0.9]);
    expect(output.ports?.x_scores.data).toEqual([
      [1, 2, 3],
      [4, 5, 6],
    ]);
    expect(output.ports?.x_loadings.data).toEqual([
      [0.1, 0.2],
      [0.4, 0.5],
    ]);
    expect(output.ports?.vip_scores.metadata).toMatchObject({
      persisted_preview: true,
      data_truncated: true,
      original_length: 700,
    });
  });
});
