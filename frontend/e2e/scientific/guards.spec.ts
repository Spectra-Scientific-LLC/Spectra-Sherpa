import { test, expect } from "@playwright/test";
import { assertDefaultDisplayMatrix, assertIdentity, assertLabelledMatrixCsv, assertMatrix, assertReportedNumber, assertSameScreenshot, parseCsv, settledPlotScreenshot, settledTableScreenshot } from "./assertions";

test("table capture preserves exact content across text raster modes @smoke", async ({ page }) => {
  await page.setContent('<div role="dialog"><div class="p-datatable-wrapper" style="width:300px;height:80px;background:#0f172a;color:white;font:12px monospace;-webkit-font-smoothing:subpixel-antialiased"><table><tbody><tr><td>moisture-nir-01</td><td>0.369612</td></tr></tbody></table></div></div>');
  const capture = (name: string) => settledTableScreenshot(page, test.info().outputPath(`table-${name}.png`));
  const before = await capture("before");
  await page.locator(".p-datatable-wrapper").evaluate(el => {
    (el as HTMLElement).style.setProperty("-webkit-font-smoothing", "antialiased");
  });
  await assertSameScreenshot(page, before, await capture("reopened"));
  for (const change of ["text", "color", "position"]) {
    await page.locator("td").first().evaluate((el, change) => {
      el.textContent = change === "text" ? "moisture-nir-02" : "moisture-nir-01";
      (el as HTMLElement).style.color = change === "color" ? "red" : "white";
      (el as HTMLElement).style.transform = change === "position" ? "translateX(1px)" : "none";
    }, change);
    await expect(assertSameScreenshot(page, before, await capture(change))).rejects.toThrow(/Scientific surface pixels/);
  }
});

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
test("labelled CSV acceptance checks metadata columns without hiding scientific corruption @smoke", () => {
  const labels = ['Sample, "one"', "Sample | two"];
  const columns = ["PC1 (73.0%)", "PC2 (22.9%)", "PC3 (3.7%)"];
  const values = [[0.123456789012, 2, 3], [4, 5, 6]];
  const csv = [
    ["Index", "Label", ...columns],
    ["1", labels[0], ...values[0].map(String)],
    ["2", labels[1], ...values[1].map(String)],
  ];
  assertLabelledMatrixCsv(csv, values, labels, columns);
  // The former one-column slice reproduces the CI failure on valid labelled data.
  expect(() => assertMatrix(csv.slice(1).map(row => row.slice(1).map(Number)), values)).toThrow(/orientation/);
  const corruptions: Array<(copy: string[][]) => void> = [
    copy => { copy[0][1] = "Include"; },
    copy => { copy.forEach(row => row.splice(1, 1)); },
    copy => { [copy[0][2], copy[0][3]] = [copy[0][3], copy[0][2]]; },
    copy => { copy[1][1] = labels[1]; },
    copy => { copy[1][0] = "2"; },
    copy => { [copy[1], copy[2]] = [copy[2], copy[1]]; },
    copy => { copy[1].push("7"); },
    copy => { copy[1].pop(); },
    copy => { copy[1][2] = "0.123457"; },
    copy => { copy[1][2] = ""; },
    copy => { copy[1][2] = "NaN"; },
    copy => { copy[1][3] = "50"; },
    copy => { copy.pop(); },
  ];
  for (const corrupt of corruptions) {
    const copy = structuredClone(csv);
    corrupt(copy);
    expect(() => assertLabelledMatrixCsv(copy, values, labels, columns)).toThrow();
  }
});

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
