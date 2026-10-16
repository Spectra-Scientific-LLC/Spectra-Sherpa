import { describe, it, expect } from "vitest";
import { selectedSampleIds, selectionIndices } from "@/utils/sampleReview";

describe("exact sample selection", () => {
  it("never recovers identity from plot positions or display text", () => {
    const allowed = new Set(["id-a", "id-b"]);
    expect(
      selectedSampleIds(
        {
          points: [
            { customdata: "id-b" },
            { customdata: "id-b" },
            { customdata: "foreign" },
            { pointIndex: 0, text: "id-a" },
            { customdata: ["id-a"] },
          ],
        },
        allowed,
      ),
    ).toEqual(["id-b"]);
    expect(selectedSampleIds(null, allowed)).toEqual([]);
  });
  it("keeps identities after trace regrouping and sorting for 5,000 observations", () => {
    const ids = Array.from({ length: 5000 }, (_, i) => `sample-${i}`);
    const selected = new Set(ids.filter((_, i) => i % 7 === 0));
    const traces = [ids.filter((_, i) => i % 2).reverse(), ids.filter((_, i) => !(i % 2))];
    const indices = selectionIndices(
      traces.map((customdata) => ({ customdata })),
      selected,
    );
    expect(
      new Set(indices.flatMap((values, trace) => values.map((i) => traces[trace][i]))),
    ).toEqual(selected);
  });
});
