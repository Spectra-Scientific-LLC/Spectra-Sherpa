import { describe, expect, it } from "vitest";
import { extractValidationLedgerRows, validationLedgerCsv, validationLedgerUnavailableReason } from "@/utils/validationLedger";
import regressionPlot from "../fixtures/regression-comparison-plot.json";

describe("validation ledger", () => {
  it("extracts classification truth and prediction rows", () => {
    const rows = extractValidationLedgerRows({
      presentation_value: {
        schema_version: "spectrasherpa-classification-comparison/1",
        shape: [2, 5],
        data: [
          { sample: "A", reference: "wine", predicted: "wine", correct: true, role: "held_out_test" },
          { sample: "B", reference: "beer", predicted: "wine", correct: false, role: "held_out_test" },
        ],
      },
    });
    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({ sample: "B", reference: "beer", predicted: "wine", correct: false });
  });

  it("extracts regression traces and exports a complete CSV", () => {
    const rows = extractValidationLedgerRows({
      presentation_value: {
        metadata: { source_schema: "spectrasherpa-regression-comparison/1", n_rows: 1 },
        data: [{ type: "scatter", mode: "markers", name: "density", text: ["A"], x: [1], y: [1.2], customdata: [[-0.2, "held_out_test"]] }],
      },
    });
    expect(rows[0]).toMatchObject({ sample: "A", target: "density", reference: 1, predicted: 1.2, residual: -0.2, role: "held_out_test" });
    expect(validationLedgerCsv(rows)).toContain("sample,target,reference,predicted,residual,correct,role");
    expect(validationLedgerCsv(rows)).toContain("A,density,1,1.2,-0.2,,held_out_test");
  });

  it("round-trips the actual backend plot without turning its 1:1 line into observations", () => {
    const reopened = JSON.parse(JSON.stringify({ presentation_value: regressionPlot }));
    const rows = extractValidationLedgerRows(reopened);
    expect(rows).toHaveLength(regressionPlot.metadata.n_rows);
    expect(rows.map(row => row.sample)).toEqual(["A", "B"]);
    expect(rows.map(row => row.reference)).toEqual([1, 2]);
    expect(rows.map(row => row.predicted)).toEqual([1.1, 1.8]);
    expect(rows.every(row => row.role === "held_out_test")).toBe(true);
    expect(validationLedgerCsv(rows).split("\n")).toHaveLength(3);
    expect(validationLedgerCsv(rows)).not.toContain("1:1 Line");
  });

  it("preserves sample/target pairs for multiple responses and ignores additional lines", () => {
    const plot = JSON.parse(JSON.stringify(regressionPlot));
    plot.data.push({ ...plot.data[0], name: "viscosity" });
    plot.data.push({ ...plot.data[1], name: "Fitted line" });
    plot.metadata.n_rows = 4;
    const rows = extractValidationLedgerRows(plot);
    expect(rows.map(row => [row.sample, row.target])).toEqual([
      ["A", "density"], ["B", "density"], ["A", "viscosity"], ["B", "viscosity"],
    ]);
  });

  it.each(["missing identity", "truncated predictions", "missing role", "wrong count", "nonfinite"])(
    "refuses an incomplete ledger: %s", (fault) => {
      const plot = JSON.parse(JSON.stringify(regressionPlot));
      if (fault === "missing identity") delete plot.data[0].text;
      if (fault === "truncated predictions") plot.data[0].y.pop();
      if (fault === "missing role") plot.data[0].customdata[0].pop();
      if (fault === "wrong count") plot.metadata.n_rows++;
      if (fault === "nonfinite") plot.data[0].y[0] = NaN;
      const rows = extractValidationLedgerRows(plot);
      expect(rows).toEqual([]);
      expect(validationLedgerUnavailableReason(plot, rows)).toContain("unavailable");
    },
  );

  it("does not invent identities or silently omit damaged table rows", () => {
    for (const data of [
      [{ reference: "A", predicted: "B" }],
      [{ sample: "A", reference: 1, predicted: 2 }, { sample: "B", reference: 3 }],
    ]) expect(extractValidationLedgerRows({ schema_version: "spectrasherpa-regression-comparison/1", shape: [data.length, 6], data })).toEqual([]);
  });

  it("handles empty and singleton comparisons without manufacturing rows", () => {
    expect(extractValidationLedgerRows(null)).toEqual([]);
    expect(extractValidationLedgerRows({ data: [] })).toEqual([]);
    expect(validationLedgerUnavailableReason({ data: [] }, [])).toBeNull();
    expect(extractValidationLedgerRows({ schema_version: "spectrasherpa-regression-comparison/1", shape: [1, 6], data: [{ sample: "A", target: "density", reference: 1, predicted: 1.2, residual: -0.2, role: "calibration" }] }))
      .toMatchObject([{ sample: "A", reference: 1, predicted: 1.2, role: "calibration" }]);
  });

  it("does not infer a scientific ledger from arbitrary table column names", () => {
    expect(extractValidationLedgerRows({ data: [{ sample: "A", reference: 1, predicted: 1.2 }] })).toEqual([]);
  });
});


it("retains unqualified evaluation rows without inventing held-out scope", () => {
  const rows = extractValidationLedgerRows({
    schema_version: "spectrasherpa-regression-comparison/1",
    shape: [1, 6],
    data: [{ sample: "A", target: "y", reference: 1, predicted: 1.2, residual: -0.2, role: "unqualified_evaluation" }],
  });
  expect(rows).toHaveLength(1);
  expect(rows[0].role).toBe("unqualified_evaluation");
});
