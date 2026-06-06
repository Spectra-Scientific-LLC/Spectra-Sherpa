import { describe, expect, it } from "vitest";
import { scaleLibraryTraceToSamplePeaks } from "@/utils/libraryTraceScaling";

describe("scaleLibraryTraceToSamplePeaks", () => {
  it("uses the median ratio across matched sample and library peaks instead of a single interfered peak", () => {
    const x = [1000, 1001, 1002, 1003, 1004, 1005, 1006];
    const library = [0, 10, 0, 5, 0, 4, 0];
    const sample = [0, 20, 0, 10, 0, 40, 0];

    const scaled = scaleLibraryTraceToSamplePeaks(x, library, x, sample);

    expect(scaled[1]).toBeCloseTo(20);
    expect(scaled[3]).toBeCloseTo(10);
    expect(scaled[5]).toBeCloseTo(8);
  });

  it("ignores tiny library peaks under unrelated sample features", () => {
    const x = [1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008];
    const library = [0, 10, 0, 5, 0, 0.2, 0, 0.15, 0];
    const sample = [0, 20, 0, 10, 0, 10, 0, 12, 0];

    const scaled = scaleLibraryTraceToSamplePeaks(x, library, x, sample);

    expect(scaled[1]).toBeCloseTo(20);
    expect(scaled[3]).toBeCloseTo(10);
    expect(scaled[5]).toBeCloseTo(0.4);
    expect(scaled[7]).toBeCloseTo(0.3);
  });

  it("falls back to the single available peak ratio when only one peak is usable", () => {
    const x = [1000, 1001, 1002];
    const library = [0, 3, 0];
    const sample = [0, 12, 0];

    expect(scaleLibraryTraceToSamplePeaks(x, library, x, sample)).toEqual([0, 12, 0]);
  });

  it("keeps non-finite values as plot gaps", () => {
    const x = [1000, 1001, 1002];
    const library = [0, Number.NaN, 4];
    const sample = [0, 0, 8];

    expect(scaleLibraryTraceToSamplePeaks(x, library, x, sample)).toEqual([0, null, 8]);
  });
});
