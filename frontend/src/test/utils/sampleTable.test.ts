import { describe, expect, it } from "vitest";

import {
  assignPlateCoordinates,
  applyAcquisitionPlan,
  assignSequential96WellCoordinates,
  compareAcquisitionPlan,
  createSampleTableRows,
  proposeMeasuredSamples,
  serializeSampleTableCsv,
  validateSampleTable,
  wellForOrdinal,
  wellsForRectangle,
  type SampleTargetDefinition,
} from "@/utils/sampleTable";
import type { AcquisitionPlan } from "@/types";

const targets: SampleTargetDefinition[] = [
  { name: "moisture", type: "continuous" },
  { name: "cultivar", type: "categorical" },
];

describe("portable sample table", () => {
  it("preserves exact source row identity and supplied sample labels", () => {
    const rows = createSampleTableRows(3, 41, ["QC, 1", "sample-2"], ["moisture"]);
    expect(rows.map((row) => [row.row_index, row.source_file_id, row.sample_id])).toEqual([
      [0, 41, "QC, 1"],
      [1, 41, "sample-2"],
      [2, 41, "sample-0003"],
    ]);
    expect(rows[0].targets).toEqual({ moisture: "" });
  });

  it("assigns deterministic coordinates across multiple complete plates", () => {
    const rows = createSampleTableRows(98, 7);
    assignSequential96WellCoordinates(rows);
    expect(wellForOrdinal(0)).toBe("A01");
    expect(wellForOrdinal(95)).toBe("H12");
    expect(rows[95]).toMatchObject({ plate_id: "plate-1", well: "H12" });
    expect(rows[96]).toMatchObject({ plate_id: "plate-2", well: "A01" });
  });

  it("traverses an inclusive rectangular subsection by rows or columns", () => {
    expect(
      wellsForRectangle({
        startWell: "B03",
        endWell: "C05",
        direction: "rows",
        serpentine: false,
      }),
    ).toEqual(["B03", "B04", "B05", "C03", "C04", "C05"]);
    expect(
      wellsForRectangle({
        startWell: "B03",
        endWell: "C05",
        direction: "columns",
        serpentine: true,
      }),
    ).toEqual(["B03", "C03", "C04", "B04", "B05", "C05"]);
  });

  it("repeats the selected rectangular region on the next plate", () => {
    const rows = createSampleTableRows(7, 7);
    assignPlateCoordinates(rows, {
      startWell: "B03",
      endWell: "C05",
      direction: "rows",
      serpentine: true,
    });
    expect(rows.map((row) => `${row.plate_id}:${row.well}`)).toEqual([
      "plate-1:B03",
      "plate-1:B04",
      "plate-1:B05",
      "plate-1:C05",
      "plate-1:C04",
      "plate-1:C03",
      "plate-2:B03",
    ]);
  });

  it("applies an exact acquisition plan without changing scientific decisions", () => {
    const rows = createSampleTableRows(2, 9, ["a", "b"], ["class"]);
    rows[0].include = false;
    rows[0].targets.class = "healthy";
    rows[0].annotations.batch = "day-1";

    applyAcquisitionPlan(rows, ["A01", "B02"]);

    expect(rows[0]).toMatchObject({
      sample_id: "a",
      include: false,
      targets: { class: "healthy" },
      annotations: { batch: "day-1" },
      plate_id: "plate-1",
      well: "A01",
    });
    expect(compareAcquisitionPlan(rows, ["A01", "B02"])).toEqual({
      planned: 2,
      assigned: 2,
      matched: 2,
      unmeasured: 0,
      outsidePlan: 0,
    });
  });

  it("refuses ambiguous acquisition-plan assignment", () => {
    const rows = createSampleTableRows(2, 9);
    expect(() => applyAcquisitionPlan(rows, ["A01"])).toThrow(
      "Exact assignment requires one planned well for each measured row",
    );
    expect(rows.every((row) => row.well === "")).toBe(true);
  });

  it("proposes measured rows from retained matches, sample identity, and factor values", () => {
    const rows = createSampleTableRows(2, 9, ["raw-1", "raw-2"], ["target"]);
    const plan: AcquisitionPlan = {
      schema_version: "spectrasherpa-acquisition-plan/3",
      experiment_id: 1,
      plate_format_id: "plate-96",
      plate_format_label: "96-well plate",
      capacity: 96,
      revision: "a".repeat(64),
      samples: [
        { sample_id: "oil", source_specimen_uid: null, name: "Oil", sample_type: null, notes: null },
      ],
      mixtures: [],
      factors: [
        {
          factor_id: "temperature",
          name: "Temperature",
          scope: "method",
          factor_type: "numeric",
          unit: "C",
          levels: [20],
        },
      ],
      wells: [
        {
          well_position: "A01",
          planned_sample_label: "Oil",
          sample_id: "oil",
          mixture_id: null,
          factor_values: {},
        },
        {
          well_position: "A02",
          planned_sample_label: null,
          sample_id: null,
          mixture_id: null,
          factor_values: {},
        },
      ],
      acquisition_order: [],
      matching: {
        rules: { filename_pattern: "_(\\d+)" },
        matches: [
          {
            sequence_order: 0,
            filename: "run_1.csv",
            folder: null,
            timestamp: null,
            date: null,
            batch: null,
            sample_id: "oil",
            well_position: "A01",
            special: null,
            factor_values: { Temperature: 20 },
          },
        ],
      },
    };

    const proposal = proposeMeasuredSamples(rows, plan);

    expect(proposal.rows[0]).toMatchObject({
      sample_id: "oil",
      plate_id: "plate-1",
      well: "A01",
      annotations: { temperature: "20" },
    });
    expect(proposal.rows[1]).toMatchObject({ sample_id: "raw-2", well: "A02" });
    expect(proposal.status).toMatchObject({ planned: 2, matched: 2, unmeasured: 0 });
    expect(proposal.differences.map((item) => item.field)).toEqual([
      "well",
      "sample_id",
      "annotations",
      "well",
    ]);
  });

  it("validates the selected target without requiring unfinished alternate targets", () => {
    const rows = createSampleTableRows(
      2,
      9,
      ["a", "b"],
      targets.map((target) => target.name),
    );
    rows[0].targets.moisture = "1.5";
    rows[1].include = false;
    rows[1].well = "A13";
    rows[1].plate_id = "plate-1";
    expect(validateSampleTable(rows, targets, "moisture", [])).toEqual({
      valid: false,
      errors: [
        "Row 2 has invalid well 'A13'. Well 'A13' is outside 96-well plate (A01 through H12).",
      ],
    });
  });

  it("rejects an empty scientific cohort before saving", () => {
    const rows = createSampleTableRows(2, 9, ["a", "b"], ["moisture"]);
    rows.forEach((row) => {
      row.include = false;
    });
    expect(validateSampleTable(rows, [targets[0]], "moisture", [])).toEqual({
      valid: false,
      errors: ["At least one sample must be included."],
    });
  });

  it("rejects duplicate physical coordinates but permits the same well on another plate", () => {
    const rows = createSampleTableRows(3, 9, ["a", "b", "c"], ["moisture"]);
    rows.forEach((row, index) => {
      row.targets.moisture = String(index + 1);
      row.plate_id = index === 2 ? "plate-2" : "plate-1";
      row.well = "A01";
    });

    expect(validateSampleTable(rows, [targets[0]], "moisture", [])).toEqual({
      valid: false,
      errors: [
        "Rows 1 and 2 both assign plate-1/A01. Each physical well may contain only one sample.",
      ],
    });

    rows[1].well = "A02";
    expect(validateSampleTable(rows, [targets[0]], "moisture", [])).toEqual({
      valid: true,
      errors: [],
    });
  });

  it("serializes multiple typed targets in a deterministic portable schema", () => {
    const rows = createSampleTableRows(
      1,
      5,
      ["QC, 1"],
      targets.map((target) => target.name),
    );
    rows[0].targets.moisture = "10.2";
    rows[0].targets.cultivar = "class A";
    rows[0].annotations.batch = "batch,blue";
    const csv = serializeSampleTableCsv(rows, targets, ["batch"]);
    expect(csv).toContain("plate_format");
    expect(csv).toContain("plate-96");
    expect(csv).toBe(
      "row_index,source_file_id,sample_id,include,target_schema,moisture,cultivar,plate_format,plate_id,well,batch\n" +
        '0,5,"QC, 1",true,"{""moisture"":""continuous"",""cultivar"":""categorical""}",10.2,class A,plate-96,,,"batch,blue"\n',
    );
  });
});
