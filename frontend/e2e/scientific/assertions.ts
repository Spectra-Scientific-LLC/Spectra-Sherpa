import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { expect, type Locator, type Page } from "@playwright/test";

export function assertMatrix(actual: number[][], expected: number[][], tolerance = 1e-10): void {
  assert.ok(expected.length > 0, "An acceptance oracle must not be empty");
  assert.equal(actual.length, expected.length, "Scientific row population");
  actual.forEach((row, r) => {
    assert.equal(row.length, expected[r].length, `Column/component orientation at row ${r}`);
    row.forEach((value, c) => {
      assert.ok(Number.isFinite(value), `Nonfinite/missing displayed value at ${r},${c}`);
      assert.ok(
        Math.abs(value - expected[r][c]) <= tolerance * Math.max(1, Math.abs(expected[r][c])),
        `Scientific value mismatch at ${r},${c}: ${value} != ${expected[r][c]}`,
      );
    });
  });
}

/** Exact six-significant-digit default display, independent of production formatting.
 * Full-precision values are asserted separately in CSVs and plot arrays.
 */
export function assertDefaultDisplayMatrix(actual: string[][], expected: number[][]): void {
  assert.ok(expected.length > 0, "An acceptance oracle must not be empty");
  assert.deepEqual(actual, expected.map(row => row.map(value => {
    assert.ok(Number.isFinite(value), "Display oracle must be finite");
    return value.toPrecision(6);
  })), "Default scientific display must preserve correctly rounded values and shape");
}

export function assertIdentity(actual: string[], expected: string[]): void {
  assert.deepEqual(
    actual,
    expected,
    "Sample membership and order must agree with inclusion authority",
  );
}

/** Four-significant-digit report rounding, never an absolute zero-sized error allowance. */
export function assertReportedNumber(text: string, expected: number): void {
  const actual = Number(text.trim());
  assert.ok(Number.isFinite(actual), `Report number missing or invalid: ${text}`);
  assert.ok(
    Math.abs(actual - expected) <= Math.max(Math.abs(expected) * 5e-4, Number.MIN_VALUE),
    `Report value ${actual} does not match retained value ${expected}`,
  );
}

export async function assertRegressionReport(
  page: Page,
  expected: { training: number; heldOut: number; rmse: number },
): Promise<void> {
  const body = page.frameLocator('iframe[title="Report preview"]').locator("body");
  for (const [label, count] of [
    ["Development population (partition_1)", expected.training],
    ["Test population (partition_1)", expected.heldOut],
  ] as const) {
    const row = body.getByRole("row").filter({ hasText: label });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole("cell").last()).toHaveText(`${count} rows`);
  }
  const row = body.getByRole("row").filter({ hasText: "Held-out test (recorded role) · eval_1 / comparison" });
  await expect(row).toHaveCount(1);
  const headers = await row.locator("xpath=ancestor::table").getByRole("columnheader").allTextContents();
  const cells = await row.getByRole("cell").allTextContents();
  expect(headers).toContain("n");
  expect(Number(cells[headers.indexOf("n")])).toBe(expected.heldOut);
  const errorIndex = headers.findIndex((header) => header === "RMSEP" || header === "Error by population");
  expect(errorIndex).toBeGreaterThanOrEqual(0);
  expect(cells[errorIndex]).toMatch(/^RMSEP/);
  assertReportedNumber(cells[errorIndex].split(":").at(-1)!, expected.rmse);
  await expect(body).not.toContainText("Evaluation (independence unverified)");
}

export async function plotData(dialog: Locator) {
  const canvas = dialog.locator(".plotly-canvas").first();
  await expect(canvas.locator(".main-svg").first()).toBeVisible();
  return canvas.evaluate((el) => {
    const graph = el as HTMLElement & {
      data: Array<{
        name: string;
        x: number[];
        y: number[];
        mode: string;
        visible?: boolean | string;
      }>;
      layout: { xaxis: { title: { text: string } }; yaxis: { title: { text: string } } };
    };
    return {
      traces: graph.data.map((trace) => ({
        name: trace.name,
        x: Array.from(trace.x ?? []),
        y: Array.from(trace.y ?? []),
        mode: trace.mode,
        visible: trace.visible,
      })),
      xTitle: graph.layout.xaxis.title.text,
      yTitle: graph.layout.yaxis.title.text,
    };
  });
}

/** CSV export has quoted cells and may contain embedded commas/newlines. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [],
    cell = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (!quoted && (c === "," || c === "\n")) {
      row.push(cell.replace(/\r$/, ""));
      cell = "";
      if (c === "\n") {
        rows.push(row);
        row = [];
      }
    } else cell += c;
  }
  if (cell || row.length) rows.push([...row, cell.replace(/\r$/, "")]);
  assert.equal(quoted, false, "CSV must not end inside a quoted cell");
  return rows;
}

export async function downloadTable(page: Page, dialog: Locator): Promise<string[][]> {
  const downloaded = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Export all rows CSV", exact: true }).click();
  const file = await downloaded;
  const path = await file.path();
  assert.ok(path, "Browser must produce a readable CSV download");
  return parseCsv(await readFile(path, "utf8"));
}

export async function closeDialog(page: Page): Promise<void> {
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** Read geometry only after the surface and its containing dialog finish entering. */
export async function settledSurfaceLayout(surface: Locator): Promise<void> {
  await surface.evaluate(async el => {
    await document.fonts.ready;
    // A visible SVG can still be scaled by an ancestor's dialog transition.
    // Include ancestors for embedded Detailed View, not just the chart subtree.
    const animations = new Set(el.getAnimations({ subtree: true }));
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      parent.getAnimations().forEach(animation => animations.add(animation));
    }
    await Promise.all([...animations].filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity,
    ).map(animation => animation.finished.catch(() => undefined)));
    await new Promise<void>(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    });
  });
}

/** Capture only after the plot has settled into the dialog's rendered layout. */
export async function settledPlotScreenshot(page: Page, path: string): Promise<Buffer> {
  const canvas = page.getByRole("dialog").locator(".plotly-canvas");
  // Dialog layout and Plotly's debounced ResizeObserver finish separately.
  // Wait for the rendered SVG to fill its actual container, never force a resize.
  await expect
    .poll(() =>
      canvas.evaluate((el) => {
        const svg = el.querySelector<SVGSVGElement>(".main-svg");
        return svg ? Math.max(
          Math.abs(svg.height.baseVal.value - el.clientHeight),
          Math.abs(svg.width.baseVal.value - el.clientWidth),
        ) : Infinity;
      }),
    )
    .toBeLessThanOrEqual(1);
  await settledSurfaceLayout(canvas);
  await page.mouse.move(0, 0);
  // Dialogs can leave the same SVG in different compositor tiles after reopen.
  // Retained Ubuntu artifacts show edge-coverage differences of 2–7 channel
  // levels confined to an upper strip, consistent with compositor tiling,
  // despite identical trace coordinates.
  // Give the real rendered canvas one stable layer, not a cloned/exported plot.
  // This changes neither content nor layout; retain the exact pixel assertion.
  const captureStyle = await page.addStyleTag({
    content: ".plotly-canvas { will-change: transform !important; } " +
      ".plotly-canvas, .plotly-canvas * { -webkit-font-smoothing: antialiased !important; }",
  });
  try {
    await canvas.evaluate(() => new Promise<void>(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));
    return await canvas.screenshot({ animations: "disabled", path });
  } finally {
    await captureStyle.evaluate(el => { el.parentNode?.removeChild(el); });
  }
}

/** Compare decoded pixels, not browser PNG compression/metadata bytes. */
export async function assertSameScreenshot(
  page: Page,
  before: Buffer,
  after: Buffer,
): Promise<void> {
  const difference = await page.evaluate(
    async ({ before, after }) => {
      async function decode(encoded: string) {
        const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const context = canvas.getContext("2d")!;
        context.drawImage(bitmap, 0, 0);
        bitmap.close();
        return {
          width: canvas.width,
          height: canvas.height,
          rgba: context.getImageData(0, 0, canvas.width, canvas.height).data,
        };
      }
      const left = await decode(before),
        right = await decode(after);
      if (left.width !== right.width || left.height !== right.height)
        return { dimensions: false, pixels: -1 };
      let pixels = 0;
      for (let i = 0; i < left.rgba.length; i += 4) {
        // Identical SVG strokes can round by one 8-bit channel level across
        // paints. No shifted/missing pixel or larger color change is admitted.
        if (
          [0, 1, 2, 3].some(
            (channel) => Math.abs(left.rgba[i + channel] - right.rgba[i + channel]) > 1,
          )
        )
          pixels++;
      }
      return { dimensions: true, pixels };
    },
    { before: before.toString("base64"), after: after.toString("base64") },
  );
  expect(difference, "Scientific surface pixels must survive reopening").toEqual({
    dimensions: true,
    pixels: 0,
  });
}
