import { describe, expect, it } from "vitest";
import { sampleSelectionMap } from "@/utils/sampleSelectionMap";

describe("retained Filter selection map", () => {
  const indices = Array.from({ length: 150 }, (_, index) => index).filter(index => ![134, 141].includes(index));
  const value = { provenance: [{ op_id: "data.filter_samples", parameters: {
    n_input: 150, n_selected: 148, selected_indices: indices, no_filter: false,
  } }] };
  it("keeps input rows 135/142 separate from renumbered result rows", () => {
    const map = sampleSelectionMap(value, 148)!;
    expect(map.inputRows).toBe(150);
    expect(map.resultRows.has(134)).toBe(false);
    expect(map.resultRows.has(141)).toBe(false);
    expect(map.resultRows.get(135)).toBe(135);
    expect(map.resultRows.get(142)).toBe(141);
    expect(map.resultRows.get(149)).toBe(148);
  });
  it.each([[0, 0], [1, 0], [-1, 0], [0, 150], [0, 1.5]])("refuses incomplete or malformed selection receipts %s", (...selected_indices) => {
    expect(sampleSelectionMap({ provenance: [{ op_id: "data.filter_samples", parameters: {
      n_input: 150, n_selected: 2, selected_indices,
    } }] }, 2)).toBeNull();
  });
  it("does not reuse an upstream Filter receipt for a different result", () => {
    expect(sampleSelectionMap({ provenance: [...value.provenance, { op_id: "data.split" }] }, 148)).toBeNull();
    expect(sampleSelectionMap(value, 147)).toBeNull();
    expect(sampleSelectionMap({ provenance: { count: 1 } }, 148)).toBeNull();
  });
});
