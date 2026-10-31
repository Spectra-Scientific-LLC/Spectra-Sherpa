import { describe, it, expect } from "vitest";
import { reviewRowLabel, selectedSampleIds, selectionIndices } from "@/utils/sampleReview";

describe("exact sample selection", () => {
  it("keeps optional duplicate GUI labels separate from full identities and old fallback", () => {
    expect(reviewRowLabel({ id: "full:a", display_label: "full:b" })).toBe("full:b");
    expect(reviewRowLabel({ id: "full:b", display_label: "full:b" })).toBe("full:b");
    expect(reviewRowLabel({ id: "historical" })).toBe("historical");
    expect(reviewRowLabel({ id: "full:a", display_label: "   " })).toBe("full:a");
    expect(selectedSampleIds({ points: [{ text: "full:b" }] }, new Set(["full:b"]))).toEqual([]);
  });
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
