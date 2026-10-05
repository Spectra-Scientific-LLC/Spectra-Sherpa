import { describe, expect, it } from "vitest";

import type { DatasetPlotSource, SherpaDatasetDict } from "@/types";
import { buildMultiDatasetOverlay, selectedDatasetRows } from "@/utils/multiDatasetOverlay";

function dataset(
  labels: string[],
  rows: number[][],
  specimenIds: string[],
  options: { xUnits?: string; xQuantity?: string; yTitle?: string; yUnits?: string } = {},
): SherpaDatasetDict {
  return {
    data_role: "X_spectra",
    n_samples: rows.length,
    n_features: 3,
    data: rows,
    x_axis: {
      data: [1800, 1200, 600],
      title: "Wavenumber",
      units: options.xUnits ?? "cm-1",
      quantity: options.xQuantity ?? "wavenumber",
    },
    y_axis: {
      labels,
      sample_table: { sample_id: labels, specimen_id: specimenIds },
    },
    domain: { data_quantity: options.yTitle ?? "Absorbance" },
    units: options.yUnits ?? "absorbance",
    metadata: { is_spectra: true },
  };
}

function source(experimentId: number, name: string, value: SherpaDatasetDict): DatasetPlotSource {
  return {
    experimentId,
    name,
    members: [{ fileId: experimentId, fileName: `${name}.spa`, dataset: value }],
    selectedFileCount: 1,
    totalFileCount: 1,
  };
}

describe("multi-dataset spectral overlay", () => {
  it("filters retained rows, labels and values without changing the source dataset", () => {
    const value = dataset(
      ["A", "B"],
      [
        [1, 2, 3],
        [4, 5, 6],
      ],
      ["one", "two"],
    );
    value.metadata = {
      source_member_metadata: [{ file_name: "raw/a.spa" }, { file_name: "raw/b.spa" }],
    };
    const original = JSON.stringify(value);
    const selected = { ...source(1, "Collection", value), selectedFileNames: ["raw/b.spa"] };
    const result = buildMultiDatasetOverlay([selected]);
    expect(selectedDatasetRows(value, ["raw/b.spa"])).toEqual([1]);
    expect(result.error).toBeNull();
    expect(result.displayedSpectra).toBe(1);
    expect(result.totalSpectra).toBe(1);
    expect(result.traces[0].y).toEqual([4, 5, 6]);
    expect(JSON.stringify(value)).toBe(original);
    expect(selectedDatasetRows(value, ["missing.spa"])).toBeNull();
    expect(selectedDatasetRows({ ...value, n_samples: 3 }, ["raw/b.spa"])).toBeNull();
  });
  it("uses shared specimen colors, dataset line styles, and source-aware hover labels", () => {
    const result = buildMultiDatasetOverlay([
      source(
        1,
        "YF block 1",
        dataset(
          ["YF_ESL", "YF_ELF"],
          [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
          ],
          ["ESL", "ELF"],
        ),
      ),
      source(
        2,
        "JF observations",
        dataset(
          ["JF2_ESL", "JF1_ELF"],
          [
            [0.11, 0.21, 0.31],
            [0.41, 0.51, 0.61],
          ],
          ["ESL", "ELF"],
          { xUnits: "cm⁻¹" },
        ),
      ),
    ]);

    expect(result.error).toBeNull();
    expect(result.displayedSpectra).toBe(4);
    expect(result.totalSpectra).toBe(4);
    expect(result.xAxisTitle).toBe("Wavenumber (cm-1)");
    const spectralTraces = result.traces.slice(0, 4) as Array<{
      line: { color: string; dash: string };
      customdata: string[][];
    }>;
    expect(spectralTraces[0].line.color).toBe(spectralTraces[2].line.color);
    expect(spectralTraces[1].line.color).toBe(spectralTraces[3].line.color);
    expect(spectralTraces[0].line.dash).toBe("solid");
    expect(spectralTraces[2].line.dash).toBe("dash");
    expect(spectralTraces[2].customdata[0]).toEqual([
      "JF2_ESL",
      "JF observations",
      "JF observations.spa",
      "ESL",
    ]);
    expect(result.traces[2].hovertemplate).toContain("Filename: %{customdata[2]}");
    expect(result.traces).toHaveLength(4);
  });

  it("refuses incompatible ordinate authorities instead of drawing a misleading overlay", () => {
    const result = buildMultiDatasetOverlay([
      source(1, "Absorbance package", dataset(["A"], [[0.1, 0.2, 0.3]], ["A"])),
      source(
        2,
        "Transmittance package",
        dataset(["B"], [[80, 81, 82]], ["B"], {
          yTitle: "Transmittance",
          yUnits: "percent",
        }),
      ),
    ]);

    expect(result.traces).toEqual([]);
    expect(result.error).toContain("incompatible ordinate quantities");
    expect(result.error).toContain("Absorbance package");
    expect(result.error).toContain("Transmittance package");
  });

  it("refuses equal inverse-centimetre grids with different physical meanings", () => {
    const raman = dataset(["R"], [[0.1, 0.2, 0.3]], ["R"], {
      xQuantity: "raman_shift",
    });
    if (raman.x_axis) raman.x_axis.title = "Raman Shift";
    const result = buildMultiDatasetOverlay([
      source(1, "IR", dataset(["IR"], [[0.1, 0.2, 0.3]], ["IR"])),
      source(2, "Raman", raman),
    ]);

    expect(result.traces).toEqual([]);
    expect(result.error).toContain("incompatible feature-axis quantities");
    expect(result.error).toContain("IR: wavenumber");
    expect(result.error).toContain("Raman: raman_shift");
  });

  it("refuses mixing a declared axis quantity with an undeclared authority", () => {
    const unknown = dataset(["U"], [[0.1, 0.2, 0.3]], ["U"]);
    if (unknown.x_axis) delete unknown.x_axis.quantity;
    const result = buildMultiDatasetOverlay([
      source(1, "Declared", dataset(["D"], [[0.1, 0.2, 0.3]], ["D"])),
      source(2, "Unknown", unknown),
    ]);

    expect(result.error).toContain("Unknown: undeclared");
  });

  it("plots mixed color authorities without asserting shared specimen identity", () => {
    const withoutSpecimen = dataset(["ESL"], [[0.11, 0.21, 0.31]], ["ESL"]);
    delete withoutSpecimen.y_axis?.sample_table?.specimen_id;
    const result = buildMultiDatasetOverlay([
      source(1, "YF block", dataset(["YF_ESL"], [[0.1, 0.2, 0.3]], ["ESL"])),
      source(2, "JF observations", withoutSpecimen),
    ]);

    expect(result.error).toBeNull();
    expect(result.traces).toHaveLength(2);
    expect(result.traces[0].line).not.toEqual(result.traces[1].line);
    expect((result.traces[0].line as { color: string }).color)
      .not.toBe((result.traces[1].line as { color: string }).color);
    expect(result.traces[1].y).toEqual([0.11, 0.21, 0.31]);
  });

  it("refuses a partial specimen_id column rather than silently using labels", () => {
    const partial = dataset(
      ["JF2_ESL", "JF1_ELF"],
      [
        [0.11, 0.21, 0.31],
        [0.41, 0.51, 0.61],
      ],
      ["ESL", ""],
    );
    const result = buildMultiDatasetOverlay([source(1, "JF observations", partial)]);

    expect(result.traces).toEqual([]);
    expect(result.error).toBe(
      "JF observations declares a blank or invalid specimen_id at plotted row 2.",
    );
  });

  it("refuses a short specimen_id column instead of projecting a mixed identity", () => {
    const short = dataset(
      ["JF2_ESL", "JF1_ELF"],
      [
        [0.11, 0.21, 0.31],
        [0.41, 0.51, 0.61],
      ],
      ["ESL"],
    );
    const result = buildMultiDatasetOverlay([source(1, "JF observations", short)]);

    expect(result.traces).toEqual([]);
    expect(result.error).toBe(
      "JF observations declares specimen_id without exactly 2 row-aligned values.",
    );
  });

  it("keeps equal sample labels in different datasets as independent color identities", () => {
    const first = dataset(["Shared"], [[0.1, 0.2, 0.3]], ["unused"]);
    const second = dataset(["Shared"], [[0.11, 0.21, 0.31]], ["unused"]);
    delete first.y_axis?.sample_table?.specimen_id;
    delete second.y_axis?.sample_table?.specimen_id;
    const result = buildMultiDatasetOverlay([
      source(1, "First", first),
      source(2, "Second", second),
    ]);

    expect(result.error).toBeNull();
    expect(result.traces[0].line).not.toEqual(
      expect.objectContaining({ color: (result.traces[1].line as { color: string }).color }),
    );
  });

  it("refuses a numeric matrix that is not declared as spectra", () => {
    const tabular = dataset(["A"], [[0.1, 0.2, 0.3]], ["A"]);
    tabular.data_role = "X_tabular";
    tabular.metadata = {};
    const result = buildMultiDatasetOverlay([
      source(1, "Spectra", dataset(["A"], [[0.1, 0.2, 0.3]], ["A"])),
      source(2, "Properties", tabular),
    ]);

    expect(result.traces).toEqual([]);
    expect(result.error).toBe("Properties is not declared as spectral data.");
  });

  it("applies one global 50-spectrum display bound across selected packages", () => {
    const rows = Array.from({ length: 30 }, (_, index) => [index, index + 1, index + 2]);
    const labels = Array.from({ length: 30 }, (_, index) => `sample-${index + 1}`);
    const result = buildMultiDatasetOverlay([
      source(1, "First", dataset(labels, rows, labels)),
      source(2, "Second", dataset(labels, rows, labels)),
    ]);

    expect(result.error).toBeNull();
    expect(result.displayedSpectra).toBe(50);
    expect(result.totalSpectra).toBe(60);
    expect(result.traces).toHaveLength(50);
    expect(result.traces.filter((trace) => trace.legendgroup === "dataset-1")).toHaveLength(25);
    expect(result.traces.filter((trace) => trace.legendgroup === "dataset-2")).toHaveLength(25);
  });

  it("plots only the selected file members while retaining package identity", () => {
    const result = buildMultiDatasetOverlay([
      {
        experimentId: 7,
        name: "JF observations",
        members: [
          {
            fileId: 71,
            fileName: "ESL.spa",
            dataset: dataset(["JF2_ESL"], [[0.1, 0.2, 0.3]], ["ESL"]),
          },
          {
            fileId: 72,
            fileName: "PL.spa",
            dataset: dataset(["JF1_PL"], [[0.4, 0.5, 0.6]], ["PL"]),
          },
        ],
        selectedFileCount: 2,
        totalFileCount: 6,
      },
    ]);

    expect(result.error).toBeNull();
    expect(result.displayedSpectra).toBe(2);
    expect(result.traces.map((trace) => trace.name)).toEqual(["JF2_ESL", "JF1_PL"]);
    expect((result.traces[1].customdata as string[][])[0][2]).toBe("PL.spa");
  });

  it("keeps each sample label attached to its exact aggregate-member filename", () => {
    const aggregate = dataset(
      ["2EWL", "2ELF"],
      [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
      ],
      ["EWL", "ELF"],
    );
    aggregate.metadata = {
      is_spectra: true,
      source_member_metadata: [
        {
          file_name: "raw/EO_Lavender_001_YF_0031.spa",
          metadata: { source_file: "EO_Lavender_001_YF_0031.spa" },
        },
        {
          file_name: "raw/EO_Lavender_001_YF_0030.spa",
          metadata: { source_file: "EO_Lavender_001_YF_0030.spa" },
        },
      ],
    };
    const result = buildMultiDatasetOverlay(
      [
        {
          experimentId: 11,
          name: "YF block",
          members: [{ fileId: null, fileName: "All 2 files", dataset: aggregate }],
          selectedFileCount: 2,
          totalFileCount: 2,
        },
      ],
      50,
      { experimentId: 11, fileName: "EO_Lavender_001_YF_0030.spa" },
    );

    expect(result.error).toBeNull();
    expect((result.traces[0].customdata as string[][])[0]).toEqual([
      "2EWL",
      "YF block",
      "EO_Lavender_001_YF_0031.spa",
      "EWL",
    ]);
    expect((result.traces[1].customdata as string[][])[0]).toEqual([
      "2ELF",
      "YF block",
      "EO_Lavender_001_YF_0030.spa",
      "ELF",
    ]);
    expect(result.traces[0].line).toEqual(expect.objectContaining({ width: 1.4 }));
    expect(result.traces[1].line).toEqual(expect.objectContaining({ width: 3.2 }));
    expect(result.traces[1].hovertemplate).toContain("Filename: %{customdata[2]}");
  });
});


it("preserves tiny values in multi-dataset overlay hover",()=>{
  const plot=buildMultiDatasetOverlay([source(1,"micro",dataset(["A"],[[1e-6,0,2e-6]],["A"]))]);
  expect(plot.traces[0].hovertemplate).toContain(".15g}");
  expect(plot.traces[0].y).toEqual([1e-6,0,2e-6]);
});
