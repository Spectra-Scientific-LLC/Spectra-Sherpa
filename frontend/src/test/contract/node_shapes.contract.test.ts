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

import fileLoadFixture from "../../../../tests/fixtures/node_serialization/file_load_canonical_result.json";
import regressionEvaluatorFixture from "../../../../tests/fixtures/node_serialization/regression_evaluator_single_target.json";
import dataTableMetricsFixture from "../../../../tests/fixtures/node_serialization/data_table_per_target_metrics.json";

// Type is intentionally loose — these JSON files are the single source
// of truth, so we navigate them with bracket access and per-test casts.
type FixturePayload = {
  _description: string;
  _spec: string;
  serialized: Record<string, any>;
};

const fileLoad = fileLoadFixture as FixturePayload;
const regressionEvaluator = regressionEvaluatorFixture as FixturePayload;
const dataTable = dataTableMetricsFixture as FixturePayload;

describe("Node serialization contract — all fixtures parse cleanly", () => {
  it.each([
    ["file_load_canonical_result", fileLoad],
    ["regression_evaluator_single_target", regressionEvaluator],
    ["data_table_per_target_metrics", dataTable],
  ])("%s has _spec and serialized payload", (name, fixture) => {
    expect(fixture._spec).toBe(name);
    expect(fixture.serialized).toBeDefined();
    expect(typeof fixture.serialized).toBe("object");
  });
});

describe("Contract: canonical data.file_load result (multi-output wrapper)", () => {
  // This fixture is the canary for the PR #16 bug: the data-source node
  // serializes as ``{default: SherpaDataset, target: ndarray}``, not as
  // a flat SherpaDataset at the top level.  Frontend consumers that
  // read ``rawResult.title``, ``rawResult.extra``, etc. directly will
  // silently see ``undefined`` — they must unwrap ``default`` first.

  it("has a multi-output wrapper with default and target keys", () => {
    const s = fileLoad.serialized;
    expect(Object.keys(s)).toEqual(expect.arrayContaining(["default", "target"]));
    expect(s.default).toBeDefined();
    expect(typeof s.default).toBe("object");
  });

  it("does NOT expose dataset identity at the top level", () => {
    // If any of these appear at the top level, the serializer shape has
    // changed and the unwrap logic needs to be revisited.
    const s = fileLoad.serialized;
    expect(s.title).toBeUndefined();
    expect(s.backend).toBeUndefined();
    expect(s.extra).toBeUndefined();
    expect(s.metadata).toBeUndefined();
    expect(s.target_context).toBeUndefined();
  });

  it("carries the SherpaDataset type marker on default", () => {
    expect(fileLoad.serialized.default.type).toBe("SherpaDataset");
  });

  it("exposes the real dataset identity fields on default", () => {
    const ds = fileLoad.serialized.default;
    expect(ds.title).toBe("canonical-file-load");
    expect(ds.backend).toBe("numpy");
    expect(ds.n_samples).toBe(40);
    expect(ds.n_features).toBe(6);
  });

  it("carries canonical persisted-source identity fields in default.extra", () => {
    const extra = fileLoad.serialized.default.extra;
    expect(extra).toBeDefined();
    expect(extra["source.experiment_id"]).toBe(17);
    expect(extra["source.file_id"]).toBe(23);
  });

  it("carries explicit continuous target context on default", () => {
    const tc = fileLoad.serialized.default.target_context;
    expect(tc).toBeDefined();
    expect(tc.target_type).toBe("continuous");
    expect(tc.target_names).toEqual(["Moisture"]);
    expect(tc.selected_target).toBe("Moisture");
  });

  it("summarizes bulk data arrays instead of inlining them", () => {
    // The raw X matrix and target vector are replaced with shape
    // descriptors to keep fixture files small.  This test documents
    // and locks in that behaviour — if future fixtures inline the raw
    // data, they'll blow up to > 1 MB and this test fails.
    const ds = fileLoad.serialized.default;
    expect(ds.data).toMatchObject({
      __array_summary__: true,
      shape: [40, 6],
    });
    expect(fileLoad.serialized.target).toMatchObject({
      __array_summary__: true,
      shape: [40],
    });
  });
});

describe("Contract: canonical regression evaluator", () => {
  it("has the closed default metric record and comparison ports", () => {
    const s = regressionEvaluator.serialized;
    expect(Object.keys(s)).toEqual(["default", "comparison"]);
    expect(Object.keys(s.default).sort()).toEqual(
      [
        "bias",
        "intercept",
        "mae",
        "n_samples",
        "r2",
        "registry_version",
        "rer",
        "rmse",
        "sep",
        "slope",
        "task_type",
      ].sort()
    );
  });

  it("binds scalar regression metrics to the versioned registry", () => {
    const metrics = regressionEvaluator.serialized.default;
    expect(metrics.task_type).toBe("regression");
    expect(metrics.registry_version).toBe("2");
    expect(metrics.n_samples).toBe(20);
    for (const key of ["rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"]) {
      expect(typeof metrics[key]).toBe("number");
    }
  });

  it("carries a closed predicted-versus-actual comparison table", () => {
    const { default: metrics, comparison } = regressionEvaluator.serialized;
    expect(comparison.schema_version).toBe("spectrasherpa-regression-comparison/1");
    expect(comparison.shape).toEqual([metrics.n_samples, 6]);
    expect(Array.isArray(comparison.data)).toBe(true);
    expect(comparison.data).toHaveLength(metrics.n_samples);
    for (const row of comparison.data) {
      expect(Object.keys(row)).toEqual([
        "sample",
        "target",
        "reference",
        "predicted",
        "residual",
        "role",
      ]);
      expect(row.residual).toBeCloseTo(row.reference - row.predicted, 12);
      // Explicit arrays alone do not establish an independent held-out population.
      expect(row.role).toBe("unqualified_evaluation");
    }
    expect(comparison.metadata).toMatchObject({
      n_samples: metrics.n_samples,
      n_targets: 1,
      role: "unqualified_evaluation",
      residual_definition: "reference_minus_predicted",
    });
    expect(comparison.statistics.schema_version).toBe("spectrasherpa-regression-statistics/1");
    expect(comparison.statistics.targets[0].metrics).toMatchObject({
      n_samples: metrics.n_samples, rmse: metrics.rmse, r2: metrics.r2,
    });
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
