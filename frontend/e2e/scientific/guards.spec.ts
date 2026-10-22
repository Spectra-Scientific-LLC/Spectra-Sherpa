import { test, expect } from "@playwright/test";
import { assertDefaultDisplayMatrix, assertIdentity, assertMatrix, assertReportedNumber, assertSameScreenshot, parseCsv, settledPlotScreenshot } from "./assertions";

test("visual parity still rejects changed text, color and geometry @smoke", async ({ page }) => {
  await page.setContent('<div role="dialog"><div class="plotly-canvas" style="width:240px;height:80px"><svg class="main-svg" width="240" height="80" style="background:white"><text x="10" y="35" fill="black">PC 1 · Wavelength (nm)</text><path d="M10 65L80 45L150 60" stroke="blue" fill="none"/></svg></div></div>');
  const capture = (name: string) => settledPlotScreenshot(page, test.info().outputPath(`${name}.png`));
  const before = await capture("before");
  await assertSameScreenshot(page, before, await capture("unchanged"));
  for (const change of ["text", "color", "position"]) {
    await page.locator("text").evaluate((el, change) => {
      el.textContent = change === "text" ? "PC 2 · Wavelength (nm)" : "PC 1 · Wavelength (nm)";
      el.setAttribute("fill", change === "color" ? "red" : "black");
      el.setAttribute("x", change === "position" ? "11" : "10");
    }, change);
    await expect(assertSameScreenshot(page, before, await capture(change))).rejects.toThrow();
  }
});

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
  assertDefaultDisplayMatrix([["0.369612"]], [[0.3696116996106742]]);
  expect(() => assertDefaultDisplayMatrix([["0.369613"]], [[0.3696116996106742]])).toThrow();
  expect(() => assertDefaultDisplayMatrix([], [[0.3696116996106742]])).toThrow();
  // Rounding is a display contract, never a relaxed scientific-data tolerance.
  expect(() => assertMatrix([[0.369612]], [[0.3696116996106742]])).toThrow(/value mismatch/);
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
