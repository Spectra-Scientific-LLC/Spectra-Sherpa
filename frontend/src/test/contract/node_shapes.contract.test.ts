/**
 * Contract tests: verify the JSON fixtures committed under
 * ``tests/fixtures/node_serialization/`` still carry the shape
 * invariants the frontend stores / components depend on.
 *
 * These tests are the frontend half of a two-sided contract:
 *
 *   - Backend (pytest): ``tests/test_node_serialization_contract.py``
 *     re-runs each node and asserts its serialized output matches
 *     the committed fixture.  If the backend shape drifts, that test
 *     fails loudly.
 *
 *   - Frontend (vitest, this file): imports the **same** fixtures and
 *     asserts the top-level structure / identity fields that our
 *     ``sherpa.ts`` store, ``NodeDetailView`` panels, and ``DataTableModal``
 *     rely on.  If a fixture is regenerated with a new shape and the
 *     frontend consumer would silently break, this test should catch
 *     it.
 *
 * Why not just hand-write mocks?  The previous iteration of the
 * Sherpa store tests used hand-written shapes like
 * ``{type: "SherpaDataset", title: "wine", ...}`` at the top level,
 * which passed locally but didn't match the real wrapper shape
 * ``{default: {...}, target: [...]}`` — resulting in PR #16 passing
 * CI but failing on staging.  Consuming the same fixture files as
 * pytest eliminates that class of drift.
 */

import { describe, expect, it } from "vitest";

import datasourceWineFixture from "../../../../tests/fixtures/node_serialization/datasource_sklearn_wine.json";
import datasourceCornFixture from "../../../../tests/fixtures/node_serialization/datasource_eigenvector_corn_m5.json";
import holdoutMultitargetFixture from "../../../../tests/fixtures/node_serialization/holdout_regression_multitarget.json";
import dataTableMetricsFixture from "../../../../tests/fixtures/node_serialization/data_table_per_target_metrics.json";

// Type is intentionally loose — these JSON files are the single source
// of truth, so we navigate them with bracket access and per-test casts.
type FixturePayload = {
  _description: string;
  _spec: string;
  serialized: Record<string, any>;
};

const wine = datasourceWineFixture as FixturePayload;
const corn = datasourceCornFixture as FixturePayload;
const holdout = holdoutMultitargetFixture as FixturePayload;
const dataTable = dataTableMetricsFixture as FixturePayload;

describe("Node serialization contract — all fixtures parse cleanly", () => {
  it.each([
    ["datasource_sklearn_wine", wine],
    ["datasource_eigenvector_corn_m5", corn],
    ["holdout_regression_multitarget", holdout],
    ["data_table_per_target_metrics", dataTable],
  ])("%s has _spec and serialized payload", (name, fixture) => {
    expect(fixture._spec).toBe(name);
    expect(fixture.serialized).toBeDefined();
    expect(typeof fixture.serialized).toBe("object");
  });
});

describe("Contract: data.source sklearn wine (multi-output wrapper)", () => {
  // This fixture is the canary for the PR #16 bug: the data-source node
  // serializes as ``{default: SherpaDataset, target: ndarray}``, not as
  // a flat SherpaDataset at the top level.  Frontend consumers that
  // read ``rawResult.title``, ``rawResult.extra``, etc. directly will
  // silently see ``undefined`` — they must unwrap ``default`` first.

  it("has a multi-output wrapper with default and target keys", () => {
    const s = wine.serialized;
    expect(Object.keys(s)).toEqual(expect.arrayContaining(["default", "target"]));
    expect(s.default).toBeDefined();
    expect(typeof s.default).toBe("object");
  });

  it("does NOT expose dataset identity at the top level", () => {
    // If any of these appear at the top level, the serializer shape has
    // changed and the unwrap logic needs to be revisited.
    const s = wine.serialized;
    expect(s.title).toBeUndefined();
    expect(s.backend).toBeUndefined();
    expect(s.extra).toBeUndefined();
    expect(s.metadata).toBeUndefined();
    expect(s.target_context).toBeUndefined();
  });

  it("carries the SherpaDataset type marker on default", () => {
    expect(wine.serialized.default.type).toBe("SherpaDataset");
  });

  it("exposes the real dataset identity fields on default", () => {
    const ds = wine.serialized.default;
    expect(ds.title).toBe("wine");
    expect(ds.backend).toBe("sklearn");
    expect(ds.n_samples).toBe(178);
    expect(ds.n_features).toBe(13);
  });

  it("carries sklearn metadata in default.extra", () => {
    const extra = wine.serialized.default.extra;
    expect(extra).toBeDefined();
    expect(extra["sklearn.dataset_name"]).toBe("wine");
    // sklearn.target_names should be a real list of class names.
    expect(Array.isArray(extra["sklearn.target_names"])).toBe(true);
    expect(extra["sklearn.target_names"]).toEqual([
      "class_0",
      "class_1",
      "class_2",
    ]);
  });

  it("carries feature names in default.metadata.feature_names", () => {
    const meta = wine.serialized.default.metadata;
    expect(meta).toBeDefined();
    expect(Array.isArray(meta.feature_names)).toBe(true);
    expect(meta.feature_names.length).toBe(13);
    // Spot-check the well-known wine feature names.
    expect(meta.feature_names).toEqual(
      expect.arrayContaining([
        "alcohol",
        "malic_acid",
        "ash",
        "flavanoids",
        "color_intensity",
        "proline",
      ])
    );
  });

  it("carries target_context.class_names on default", () => {
    const tc = wine.serialized.default.target_context;
    expect(tc).toBeDefined();
    expect(tc.target_type).toBe("categorical");
    expect(tc.n_classes).toBe(3);
    expect(tc.class_names).toEqual(["class_0", "class_1", "class_2"]);
  });

  it("summarizes bulk data arrays instead of inlining them", () => {
    // The raw X matrix and target vector are replaced with shape
    // descriptors to keep fixture files small.  This test documents
    // and locks in that behaviour — if future fixtures inline the raw
    // data, they'll blow up to > 1 MB and this test fails.
    const ds = wine.serialized.default;
    expect(ds.data).toMatchObject({
      __array_summary__: true,
      shape: [178, 13],
    });
    expect(wine.serialized.target).toMatchObject({
      __array_summary__: true,
      shape: [178],
    });
  });
});

describe("Contract: data.source eigenvector corn_m5 (continuous multi-target)", () => {
  // Eigenvector datasets use continuous reference properties in
  // ``target_context.target_names`` rather than ``class_names``.  This
  // fixture exercises the path PR #13's per-target HoldoutEvaluation
  // relies on.

  it("has the same multi-output wrapper shape as wine", () => {
    const s = corn.serialized;
    expect(Object.keys(s)).toEqual(expect.arrayContaining(["default", "target"]));
    expect(s.default.type).toBe("SherpaDataset");
  });

  it("carries the 80x700 NIR shape on default", () => {
    const ds = corn.serialized.default;
    expect(ds.n_samples).toBe(80);
    expect(ds.n_features).toBe(700);
  });

  it("exposes continuous reference properties in target_context.target_names", () => {
    const tc = corn.serialized.default.target_context;
    expect(tc.target_type).toBe("continuous");
    expect(tc.target_names).toEqual([
      "Moisture",
      "Oil",
      "Protein",
      "Starch",
    ]);
  });
});

describe("Contract: HoldoutEvaluation regression (named ports)", () => {
  // PR #13 introduced per-target metrics and the
  // ``visualization.series`` multi-target shape.  The Inspector Quick
  // Plot / View Data buttons depend on ``metrics`` being the primary
  // port (first in output_ports) and on ``visualization`` carrying
  // ``series`` instead of the legacy ``data: number[][]``.

  it("has named ports and no default port", () => {
    const s = holdout.serialized;
    expect(Object.keys(s)).toEqual(
      expect.arrayContaining(["metrics", "visualization", "predictions", "evaluation"])
    );
    expect(s.default).toBeUndefined();
  });

  it("metrics.data is a list of per-target row dicts, not a numeric matrix", () => {
    const metrics = holdout.serialized.metrics;
    expect(Array.isArray(metrics.data)).toBe(true);
    expect(metrics.data.length).toBe(4);
    for (const row of metrics.data) {
      expect(typeof row).toBe("object");
      expect(row.target).toBeDefined();
      expect(typeof row.RMSEP).toBe("number");
      expect(typeof row.R2).toBe("number");
    }
  });

  it("metrics.data rows carry real reference property names", () => {
    const targets = holdout.serialized.metrics.data.map((r: any) => r.target);
    expect(targets).toEqual(["Moisture", "Oil", "Protein", "Starch"]);
  });

  it("metrics.metadata carries target_names and n_targets", () => {
    const meta = holdout.serialized.metrics.metadata;
    expect(meta.n_targets).toBe(4);
    expect(meta.target_names).toEqual(["Moisture", "Oil", "Protein", "Starch"]);
    expect(meta.aggregate).toBe("mean_across_targets");
  });

  it("visualization uses series (not data) for multi-target", () => {
    const viz = holdout.serialized.visualization;
    expect(viz.type).toBe("predicted_vs_actual");
    expect(Array.isArray(viz.series)).toBe(true);
    expect(viz.series.length).toBe(4);
    // Legacy ``data: number[][]`` should NOT be present for multi-target
    // — the presence check guards against a regression back to the old
    // flat shape that would break PlotNode._plot_predicted_vs_actual.
    expect(viz.data).toBeUndefined();
  });

  it("each visualization series has name/actual/predicted arrays", () => {
    for (const s of holdout.serialized.visualization.series) {
      expect(typeof s.name).toBe("string");
      // Actual/predicted may be array summaries (if the fixture grew
      // over the summarize threshold) or plain arrays — accept both.
      const isArraySummary = (v: any) => v && v.__array_summary__ === true;
      const isPlainArray = Array.isArray;
      expect(isArraySummary(s.actual) || isPlainArray(s.actual)).toBe(true);
      expect(isArraySummary(s.predicted) || isPlainArray(s.predicted)).toBe(true);
    }
  });

  it("metrics port also has top-level aggregate keys", () => {
    const m = holdout.serialized.metrics;
    expect(typeof m.mean_across_targets).toBe("object");
    expect(typeof m.mean_across_targets.RMSEP).toBe("number");
    expect(typeof m.mean_across_targets.R2).toBe("number");
    expect(m.n_samples).toBe(20);
    expect(m.n_targets).toBe(4);
  });
});

describe("Contract: DataTableNode per-target metrics visualization", () => {
  // PR #13's DataTableNode rewrite produces
  // ``{visualization: {data: [row_dict, ...], metadata: {...}}}``
  // which the frontend ``outputPreview`` and ``DataTableModal`` consume.
  // Regressing back to ``{columns, rows}`` (the pre-PR#13 shape that
  // nothing rendered) would silently break the Metrics Table panel.

  it("visualization.data is a list of row dicts", () => {
    const viz = dataTable.serialized.visualization;
    expect(Array.isArray(viz.data)).toBe(true);
    expect(viz.data.length).toBe(4);
  });

  it("visualization.data rows have real target names, not [object Object]", () => {
    const rows = dataTable.serialized.visualization.data;
    expect(rows[0].target).toBe("Moisture");
    expect(rows.map((r: any) => r.target)).toEqual([
      "Moisture",
      "Oil",
      "Protein",
      "Starch",
    ]);
  });

  it("visualization.metadata has type=metrics and column_names", () => {
    const meta = dataTable.serialized.visualization.metadata;
    expect(meta.type).toBe("metrics");
    expect(Array.isArray(meta.column_names)).toBe(true);
    expect(meta.column_names).toEqual(
      expect.arrayContaining(["target", "RMSEP", "R2", "MAE"])
    );
  });

  it("does NOT expose the legacy {columns, rows} shape", () => {
    // The PR #13 rewrite replaced this shape; if a future commit
    // accidentally reverts to it, this assertion fails loudly.
    const viz = dataTable.serialized.visualization;
    expect(viz.columns).toBeUndefined();
    expect(viz.rows).toBeUndefined();
  });
});
