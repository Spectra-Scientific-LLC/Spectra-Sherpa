import { test, expect } from "@playwright/test";
import { assertIdentity, assertMatrix, assertReportedNumber, parseCsv } from "./assertions";

// Deliberate corruptions exercise the same assertions used on browser outputs.
// An executor's "completed" status cannot make these scientific checks pass.
test("acceptance rejects blank tables, plausible transpositions and wrong exclusion identities @smoke", () => {
  const expected = [
    [1, 2, 3],
    [4, 5, 6],
  ];
  expect(() => assertMatrix([], expected)).toThrow(/population/);
  expect(() =>
    assertMatrix(
      [
        [1, 4],
        [2, 5],
        [3, 6],
      ],
      expected,
    ),
  ).toThrow();
  expect(() =>
    assertMatrix(
      [
        [1, 2, 3],
        [4, 50, 6],
      ],
      expected,
    ),
  ).toThrow(/value mismatch/);
  expect(() => assertIdentity(["S1", "S2"], ["S1", "S3"])).toThrow(/inclusion authority/);
  assertReportedNumber("0.1235", 0.123456);
  expect(() => assertReportedNumber("0", 1e-15)).toThrow(/Report value/);
  expect(() => assertReportedNumber("—", 0.12)).toThrow(/missing or invalid/);
  expect(() => assertReportedNumber("0.9", 0.12)).toThrow(/Report value/);
  expect(parseCsv('Sample,Value\n"sample, one",1\n"sample ""two""",2\n')).toEqual([
    ["Sample", "Value"],
    ["sample, one", "1"],
    ['sample "two"', "2"],
  ]);
});
