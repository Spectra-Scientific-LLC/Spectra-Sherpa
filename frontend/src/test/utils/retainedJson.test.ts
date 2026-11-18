import { describe, expect, it } from "vitest";
import { retainedJsonForDisplay } from "@/utils/retainedJson";

describe("inert retained JSON display", () => {
  it("preserves numeric lexemes and quoted strings without rounding", () => {
    const source = String.raw`{"id":9007199254740993,"signal":1.234567890123456789,"tiny":-1.00e-200,"units":"cm-1","escaped":"a\"2","flag":true,"absent":null}`;
    expect(retainedJsonForDisplay(source)).toEqual({
      id: "9007199254740993", signal: "1.234567890123456789", tiny: "-1.00e-200",
      units: "cm-1", escaped: 'a"2', flag: true, absent: null,
    });
  });
  it("keeps scalar and table shapes without resolving executable objects", () => {
    expect(retainedJsonForDisplay('[{"node_type":"pro.missing","value":-0}]')).toEqual([
      { node_type: "pro.missing", value: "-0" },
    ]);
    expect(() => retainedJsonForDisplay('{"value":NaN}')).toThrow();
  });
});
