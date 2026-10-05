import { describe, expect, it } from "vitest";

import {
  buildMetadataLineTraces,
  buildMetadataScoreTraces,
  metadataGroupingState,
} from "@/utils/sampleMetadataGrouping";

function fixture() {
  const specimens = Array.from({ length: 11 }, (_, index) => `S${index + 1}`);
  const specimenIds = [...specimens, ...specimens, ...specimens];
  const blocks = [1, 2, 3].flatMap((block) => Array(11).fill(block));
  const sampleIds = specimenIds.map((specimen, index) => `${specimen}__B${blocks[index]}`);
  return {
    yAxis: {
      labels: sampleIds,
      sample_table: {
        sample_id: sampleIds,
        specimen_id: specimenIds,
        block: blocks,
        authenticity_status: specimenIds.map((_, index) => (index % 2 ? "reported" : "pending")),
        acquisition_order: [
          ...Array.from({ length: 11 }, (_, index) => index + 1),
          ...Array.from({ length: 11 }, (_, index) => index + 1),
          ...Array.from({ length: 11 }, (_, index) => index + 1),
        ],
      },
    },
    scores: sampleIds.map((_, index) => [index, index / 2, -index]),
  };
}

describe("PCA typed specimen/block grouping", () => {
  it("renders 33 points with 11 specimen colors and three block symbols", () => {
    const { yAxis, scores } = fixture();
    const state = metadataGroupingState(yAxis, 33);
    expect(state.kind).toBe("valid");
    if (state.kind !== "valid") throw new Error("expected valid grouping");
    const traces = buildMetadataScoreTraces(
      scores,
      state,
      "specimen_id",
      "block",
      0,
      1,
      "PC1",
      "PC2",
    );
    const specimenTraces = traces.slice(0, 11) as any[];
    const blockTraces = traces.slice(11) as any[];
    expect(specimenTraces.flatMap((trace) => trace.x)).toHaveLength(33);
    expect(new Set(specimenTraces.map((trace) => trace.marker.color)).size).toBe(11);
    expect(blockTraces.map((trace) => trace.marker.symbol)).toEqual([
      "circle",
      "diamond",
      "square",
    ]);
    expect(specimenTraces[0].hovertemplate).toContain("block");
    expect(state.columnLabels.block.slice(0, 12)).toEqual([...Array(11).fill("1"), "2"]);
    expect(state.colorOptions.map((option) => option.value)).toContain("acquisition_order");
    expect(state.colorOptions.map((option) => option.value)).toContain("authenticity_status");
    expect(state.symbolOptions.map((option) => option.value)).toContain("block");
  });

  it("refuses reordered and duplicate sample identity while allowing other metadata schemas", () => {
    const { yAxis } = fixture();
    yAxis.sample_table.sample_id = [...yAxis.sample_table.sample_id].reverse();
    expect(metadataGroupingState(yAxis, 33)).toMatchObject({ kind: "invalid" });
    const missing = fixture().yAxis;
    delete (missing.sample_table as any).block;
    const withoutBlock = metadataGroupingState(missing, 33);
    expect(withoutBlock.kind).toBe("valid");
    if (withoutBlock.kind === "valid") {
      expect(withoutBlock.symbolOptions.map((option) => option.value)).not.toContain("block");
    }
    const duplicate = fixture().yAxis;
    duplicate.sample_table.sample_id[1] = duplicate.sample_table.sample_id[0];
    duplicate.labels[1] = duplicate.labels[0];
    expect(metadataGroupingState(duplicate, 33)).toMatchObject({ kind: "invalid" });
  });

  it("uses exact axis labels when an aligned native metadata table omits redundant sample_id", () => {
    expect(metadataGroupingState({ labels: ["a", "b"] }, 2)).toEqual({ kind: "absent" });
    const state = metadataGroupingState(
      { labels: ["a", "b"], sample_table: { acquired_at: ["first", "second"] } },
      2,
    );
    expect(state).toMatchObject({ kind: "valid", sampleIds: ["a", "b"] });
    expect(
      metadataGroupingState({ labels: ["a", "b"], sample_table: { sample_id: ["b", "a"] } }, 2),
    ).toMatchObject({ kind: "invalid" });
  });

  it("keeps aligned tables without a low-cardinality field valid but unstyled", () => {
    const ids = Array.from({ length: 25 }, (_, index) => `sample-${index + 1}`);
    const state = metadataGroupingState(
      {
        labels: ids,
        sample_table: { sample_id: ids, continuous: ids.map((_, index) => index / 7) },
      },
      ids.length,
    );
    expect(state).toMatchObject({ kind: "valid", colorOptions: [] });
  });

  it("refuses malformed columns instead of silently skipping them", () => {
    const { yAxis } = fixture();
    yAxis.sample_table.authenticity_status.pop();
    expect(metadataGroupingState(yAxis, 33)).toMatchObject({ kind: "invalid" });
    const structured = fixture().yAxis;
    (structured.sample_table.authenticity_status as unknown[])[0] = { status: "reported" };
    expect(metadataGroupingState(structured, 33)).toMatchObject({ kind: "invalid" });
  });

  it("keeps equal-looking scalar types as distinct metadata identities", () => {
    const labels = ["a", "b", "c", "d"];
    const state = metadataGroupingState(
      { labels, sample_table: { sample_id: labels, batch: [1, "1", 1, "1"] } },
      4,
    );
    expect(state.kind).toBe("valid");
    if (state.kind !== "valid") throw new Error("expected valid grouping");
    expect(new Set(state.columns.batch).size).toBe(2);
    expect(state.columnLabels.batch).toEqual([
      "1 (number)",
      "1 (string)",
      "1 (number)",
      "1 (string)",
    ]);
  });

  it("uses the same metadata authority for sample-resolved line plots", () => {
    const { yAxis, scores } = fixture();
    const state = metadataGroupingState(yAxis, 33);
    if (state.kind !== "valid") throw new Error("expected valid grouping");
    const traces = buildMetadataLineTraces([1, 2, 3], scores, state, "specimen_id", "block");
    const sampleTraces = traces.slice(0, 33) as any[];
    expect(new Set(sampleTraces.map((trace) => trace.line.color)).size).toBe(11);
    expect(new Set(sampleTraces.map((trace) => trace.line.dash)).size).toBe(3);
    expect(sampleTraces.every((trace) => trace.showlegend === false)).toBe(true);
  });

  it("uses DSO axis class sets when no sample table exists", () => {
    const labels = ["A-1", "A-2", "B-1", "B-2"];
    const state = metadataGroupingState(
      {
        labels,
        class_sets: [
          {
            name: "Species",
            values: [1, 1, 2, 2],
            levels: [
              { code: 1, label: "Lavender" },
              { code: 2, label: "Lemon" },
            ],
            source_set_index: 0,
          },
          {
            name: "Batch",
            values: ["A", "B", "A", "B"],
            source_set_index: 1,
          },
        ],
      },
      labels.length,
    );
    expect(state.kind).toBe("valid");
    if (state.kind !== "valid") throw new Error("expected valid DSO class grouping");
    expect(state.colorOptions.map((option) => option.value)).toEqual(["Species", "Batch"]);
    expect(state.columnLabels.Species).toEqual(["Lavender", "Lavender", "Lemon", "Lemon"]);
    const traces = buildMetadataScoreTraces(
      labels.map((_, index) => [index, index * 2]),
      state,
      "Species",
      "Batch",
      0,
      1,
      "LV1",
      "LV2",
    );
    expect(traces.slice(0, 2).map((trace: any) => trace.name)).toEqual(["Lavender", "Lemon"]);
  });

  it("refuses malformed, ambiguous, and non-lossless DSO class sets", () => {
    const labels = ["a", "b"];
    const base = {
      labels,
      class_sets: [{ name: "Batch", values: [1, 2], source_set_index: 0 }],
    };
    expect(metadataGroupingState(base, 2)).toMatchObject({ kind: "valid" });
    expect(
      metadataGroupingState(
        { ...base, class_sets: [{ name: "Batch", values: [1], source_set_index: 0 }] },
        2,
      ),
    ).toMatchObject({ kind: "invalid" });
    expect(
      metadataGroupingState(
        {
          ...base,
          sample_table: { sample_id: labels, Batch: [1, 2] },
        },
        2,
      ),
    ).toMatchObject({ kind: "invalid" });
    expect(
      metadataGroupingState(
        { ...base, class_sets: [{ name: "Batch", values: [1, Number.NaN], source_set_index: 0 }] },
        2,
      ),
    ).toMatchObject({ kind: "invalid" });
  });
});


it("keeps micro-values in metadata-styled score and selected-spectra hover",()=>{
  const {yAxis,scores}=fixture(); const state=metadataGroupingState(yAxis,scores.length);
  if(state.kind!=="valid") throw new Error("fixture invalid");
  const tiny=scores.map(row=>row.map(v=>v*1e-6));
  for(const traces of [buildMetadataScoreTraces(tiny,state,"specimen_id","block",0,1,"PC1","PC2"),
                      buildMetadataLineTraces([1000.01,1000.02,1000.03],tiny,state,"specimen_id","block")]) {
    expect(traces[0].hovertemplate).toContain(".15g}");
    expect(traces[0].hovertemplate).not.toContain(".4f}");
  }
});
