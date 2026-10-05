import { describe, expect, it } from "vitest";

import type { NodeTypeMetadata } from "@/types";
import type { NodeOutput } from "@/utils/nodeOutput";
import {
  ScientificPresentationError,
  availableScientificPresentations,
  isProjectedScientificKind,
  presentationSupports,
  projectScientificPresentation,
  resolveScientificPresentation,
  scientificEvidenceShape,
  scientificPlotOptions,
} from "@/utils/scientificPresentation";

const metadata = {
  presentation_contract: {
    digest: "a".repeat(64),
    payload: {
      schema_version: "spectrasherpa-node-presentation/1",
      default_presentation: "comparison",
      presentations: [
        {
          presentation_id: "comparison",
          label: "Held-out Comparison",
          kind: "regression_comparison",
          source_ports: ["comparison"],
          modes: ["plot", "table"],
          description: "Sample-level evidence.",
        },
        {
          presentation_id: "metrics",
          label: "Metrics",
          kind: "metric_record",
          source_ports: ["default"],
          modes: ["record"],
          description: "Aggregate evidence.",
        },
      ],
    },
  },
} as NodeTypeMetadata;

const output = {
  data: [],
  metadata: { diagnostics: { effective_n_components: 3 } },
  ports: {
    default: { data: [], metadata: { rmse: 0.2 }, value: { rmse: 0.2 } },
    comparison: {
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
      value: [
        {
          sample: "1",
          target: "Moisture",
          reference: 10,
          predicted: 9.8,
          residual: 0.2,
          role: "held_out_test",
        },
      ],
      metadata: { n_samples: 1, n_targets: 1 },
    },
  },
  primary_port: "default",
} as NodeOutput;

describe("scientific presentation resolver", () => {
  it.each([["A", "B", "C"], ["A"]])("uses exact response class labels, never inherited LV labels: %j", (...classes) => {
    const resolved = resolveScientificPresentation(metadata, output)!;
    const projected = projectScientificPresentation({
      ...output,
      metadata: { pc_labels: ["LV1", "LV2"], x_title: "Latent Variable", feature_names: ["LV1", "LV2"] },
    }, {
      ...resolved,
      presentation: { ...resolved.presentation, kind: "classification_responses" },
      portOutput: { data: [[0.1, 0.2, 0.7]], value: [[0.1, 0.2, 0.7]], metadata: { classes } },
    });
    expect(projected?.metadata?.feature_names).toEqual(classes.length === 3 ? classes : ["Class 1", "Class 2", "Class 3"]);
    expect(projected?.metadata?.x_title).toBe("Response class");
    expect(projected?.metadata).not.toHaveProperty("pc_labels");
  });
  it("counts bound OOF observations, not the empty generic matrix wrapper", () => {
    const resolved = resolveScientificPresentation(metadata, output)!;
    const projected = projectScientificPresentation(output, {
      ...resolved,
      presentation: { ...resolved.presentation, kind: "out_of_fold_evidence" },
      portOutput: { ...resolved.portOutput, value: {
        observations: [1, 2, 3], predictions: [1.1, 1.9, 3.2], fold_assignments: [0, 1, 2],
      } },
    });
    expect(scientificEvidenceShape(projected)).toEqual({
      rows: 3, cols: 1, rowLabel: "held-out samples", colLabel: "target",
    });
    expect(projected?.data).toEqual([
      { observation: 1, prediction: 1.1, fold_index: 0 },
      { observation: 2, prediction: 1.9, fold_index: 1 },
      { observation: 3, prediction: 3.2, fold_index: 2 },
    ]);
  });
  it("projects salient feature rows rather than the wrapper metadata", () => {
    const resolved = resolveScientificPresentation(metadata, output)!;
    const features = [{ position: 1200, importance: 0.8, label: "Peak" }];
    const projected = projectScientificPresentation(output, {
      ...resolved,
      presentation: { ...resolved.presentation, kind: "salient_features" },
      portOutput: { ...resolved.portOutput, value: { method: "peak_finding", features, n_total_variables: 100 } },
    });
    expect(projected?.data).toEqual(features);
    expect(projected?.presentation_value).toEqual({ method: "peak_finding", features, n_total_variables: 100 });
    expect(scientificEvidenceShape(projected)).toEqual({
      rows: 1, cols: 100, rowLabel: "features", colLabel: "source variables",
    });
  });
  it("uses the contract default instead of the node default port", () => {
    const resolved = resolveScientificPresentation(metadata, output);
    expect(resolved?.sourcePort).toBe("comparison");
    expect(presentationSupports(resolved, "plot")).toBe(true);
    expect(presentationSupports(resolved, "table")).toBe(true);

    const projected = projectScientificPresentation(output, resolved);
    expect(projected?.data).toEqual(output.ports?.comparison.data);
    expect(projected?.primary_port).toBe("comparison");
    expect(projected?.presentation_value).toEqual(output.ports?.comparison.value);
    expect(projected?.metadata.scientific_presentation).toMatchObject({
      presentation_id: "comparison",
      kind: "regression_comparison",
      source_port: "comparison",
    });
    expect(projected?.metadata.diagnostics).toEqual({ effective_n_components: 3 });
  });

  it("keeps record-only metrics separate from sample-level comparison rows", () => {
    const resolved = resolveScientificPresentation(metadata, output, "metrics");
    expect(resolved?.sourcePort).toBe("default");
    expect(presentationSupports(resolved, "record")).toBe(true);
    expect(presentationSupports(resolved, "table")).toBe(false);
  });

  it("does not let empty port metadata erase fitted-model annotations", () => {
    const annotatedOutput = {
      ...output,
      metadata: {
        ...output.metadata,
        classes: ["class_0", "class_1", "class_2"],
        feature_names: ["alcohol", "malic_acid"],
      },
      ports: {
        ...output.ports,
        comparison: {
          ...output.ports?.comparison,
          metadata: {
            ...output.ports?.comparison?.metadata,
            classes: [],
            feature_names: [],
          },
        },
      },
    } as NodeOutput;

    const projected = projectScientificPresentation(
      annotatedOutput,
      resolveScientificPresentation(metadata, annotatedOutput),
    );

    expect(projected?.metadata.classes).toEqual(["class_0", "class_1", "class_2"]);
    expect(projected?.metadata.feature_names).toEqual(["alcohol", "malic_acid"]);
  });

  it("does not advertise a presentation whose typed source port is absent", () => {
    const withoutMetrics = {
      ...output,
      ports: { comparison: output.ports?.comparison },
    } as NodeOutput;
    expect(
      availableScientificPresentations(metadata, withoutMetrics).map((item) => item.sourcePort),
    ).toEqual(["comparison"]);
  });

  it("fails closed instead of falling back when a requested presentation is unknown", () => {
    expect(resolveScientificPresentation(metadata, output, "not-declared")).toBeNull();
    expect(projectScientificPresentation(output, null)).toBeNull();
  });

  it("selects plot adapters only from the projected scientific kind", () => {
    const projected = projectScientificPresentation(
      output,
      resolveScientificPresentation(metadata, output),
    );
    expect(scientificPlotOptions(projected)).toEqual([
      { key: "scientific_regression_comparison", label: "Predicted vs Reference" },
    ]);

    const unknown = {
      ...projected,
      metadata: {
        ...projected?.metadata,
        scientific_presentation: {
          ...projected?.metadata.scientific_presentation,
          kind: "future_plot_kind",
        },
      },
    } as NodeOutput;
    expect(() => scientificPlotOptions(unknown)).toThrow(ScientificPresentationError);
  });

  it("keeps the declared label for a single nested visualization", () => {
    const projected = {
      data: [],
      presentation_value: {
        peak_finding: {
          data: [{ type: "scatter", x: [1], y: [2] }],
          layout: {},
        },
      },
      metadata: {
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
    } as NodeOutput;

    expect(scientificPlotOptions(projected)).toEqual([
      { key: "scientific_visualization:peak_finding", label: "Spectra with Peaks" },
    ]);
  });

  it("carries Peak Detection evidence metadata through presentation projection", () => {
    const peakMetadata = {
      presentation_contract: {
        digest: "b".repeat(64),
        payload: {
          schema_version: "spectrasherpa-node-presentation/1",
          default_presentation: "peak_overlay",
          presentations: [
            {
              presentation_id: "peak_overlay",
              label: "Spectra with Peaks",
              kind: "visualization",
              source_ports: ["plots"],
              modes: ["plot"],
              description: "Detected peaks overlaid on the input spectra.",
            },
          ],
        },
      },
    } as NodeTypeMetadata;
    const peakOutput = {
      data: [],
      metadata: { diagnostics: { n_samples: 50, n_peaks: 61, n_consensus_peaks: 4 } },
      ports: {
        plots: {
          data: [],
          metadata: {},
          value: {
            peak_finding: { data: [{ type: "scatter", mode: "lines" }], layout: {} },
            metadata: { n_samples: 50, n_peaks: 61, n_consensus_peaks: 4 },
          },
        },
      },
    } as NodeOutput;

    const projected = projectScientificPresentation(
      peakOutput,
      resolveScientificPresentation(peakMetadata, peakOutput),
    );

    expect(scientificEvidenceShape(projected)).toEqual({
      rows: 50,
      cols: 61,
      rowLabel: "spectra",
      colLabel: "peak detections",
    });
  });

  it("derives behavior from the projected kind rather than an operation identity", () => {
    const projected = projectScientificPresentation(
      output,
      resolveScientificPresentation(metadata, output),
    );

    expect(isProjectedScientificKind(projected, "regression_comparison")).toBe(true);
    expect(isProjectedScientificKind(projected, "regression_model")).toBe(false);

    const unrelatedOperationIdentity = {
      ...projected,
      metadata: {
        ...projected?.metadata,
        operation_id: "model.future_regression_operation",
      },
    } as NodeOutput;
    expect(isProjectedScientificKind(unrelatedOperationIdentity, "regression_comparison")).toBe(
      true,
    );
  });

  it("prefers the presentation contract persisted with the executed result", () => {
    const persisted = {
      ...output,
      presentation_contract: {
        digest: "b".repeat(64),
        payload: {
          schema_version: "spectrasherpa-node-presentation/1" as const,
          default_presentation: "metrics",
          presentations: metadata.presentation_contract!.payload.presentations,
        },
      },
    } as NodeOutput;

    const resolved = resolveScientificPresentation(metadata, persisted);

    expect(resolved?.contractDigest).toBe("b".repeat(64));
    expect(resolved?.presentation.presentation_id).toBe("metrics");
  });

  it("does not leak spectral axes into a target-matrix presentation", () => {
    const targetMetadata = {
      presentation_contract: {
        digest: "c".repeat(64),
        payload: {
          schema_version: "spectrasherpa-node-presentation/1" as const,
          default_presentation: "targets",
          presentations: [
            {
              presentation_id: "targets",
              label: "Target Values",
              kind: "target_matrix",
              source_ports: ["target"],
              modes: ["table" as const],
              description: "Response values by sample.",
            },
          ],
        },
      },
    } as NodeTypeMetadata;
    const targetOutput = {
      data: [[0.1, 0.2]],
      metadata: {
        wavenumbers: [600, 600.5],
        feature_names: ["600.0", "600.5"],
        x_title: "Wavenumber",
        x_units: "cm-1",
        spectral_technique: "FTIR",
      },
      ports: {
        target: {
          data: [[20, 3]],
          value: [[20, 3]],
          metadata: { target_names: ["Carbon dioxide", "Methane"] },
        },
      },
    } as NodeOutput;

    const projected = projectScientificPresentation(
      targetOutput,
      resolveScientificPresentation(targetMetadata, targetOutput),
    );

    expect(projected?.metadata).toMatchObject({
      target_names: ["Carbon dioxide", "Methane"],
      data_type: "targets",
      is_spectra: false,
    });
    for (const spectralKey of [
      "wavenumbers",
      "feature_names",
      "x_title",
      "x_units",
      "spectral_technique",
    ]) {
      expect(projected?.metadata).not.toHaveProperty(spectralKey);
    }
  });
});
