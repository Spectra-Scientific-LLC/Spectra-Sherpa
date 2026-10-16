/** Local-only real Chromium/Plotly interaction and 5k-observation latency check.
 * The HTTP numerical journey is test_pca_sample_review.py; this fixture isolates
 * browser rendering with synthetic receipts and an in-memory API adapter.
 * Run: node scripts/qualify-pca-review.mjs (no CI or external service).
 */
import { writeFile, rm, realpath } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";
import assert from "node:assert/strict";
import { createServer } from "vite";
import { chromium } from "@playwright/test";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const html = resolve(root, ".pca-review-fixture.html");
const entry = resolve(root, ".pca-review-fixture.js");
let server, browser;
try {
  await writeFile(
    html,
    '<html><body><div id="app"></div><script type="module" src="/.pca-review-fixture.js"></script></body></html>',
  );
  await writeFile(
    entry,
    `
import { createApp, h, nextTick } from 'vue';
import { createPinia } from 'pinia';
import PrimeVue from 'primevue/config';
import 'primevue/resources/themes/lara-light-blue/theme.css';
import 'primevue/resources/primevue.min.css';
import Workbench from '/src/components/PcaReviewWorkbench.vue';
import api from '/src/api/client.ts';
import { useWorkflowStore } from '/src/stores/workflow.ts';
const rows = Array.from({ length: 5000 }, (_, i) => ({ id: 's' + i.toString().padStart(4, '0'),
 role: 'calibration', group: 'Batch ' + (i % 3), scores: [i % 100, Math.floor(i / 100)], t2: i % 100, q: Math.floor(i / 100) }));
const receipt = { run_id: 10, latest_run_id: 10, revision: 0, graph_digest: 'a'.repeat(64), source_digest: 'b'.repeat(64),
 stale: false, rows, n_components: 2, n_calibration: 5000, calibration_t2_limit: 80, application_t2_limit: 82,
 q_limit: 40, q_limit_method: 'synthetic browser fixture', state: { marked: [], excluded: [] }, history: [] };
window.reviewCalls = [];
api.defaults.adapter = async config => {
 if (config.method === 'post') { const action = JSON.parse(config.data); window.reviewCalls.push(action);
 receipt.revision++; receipt.state.marked = action.sample_ids;
 receipt.history.unshift({ revision: receipt.revision, action: action.action, reason: action.reason, sample_ids: action.sample_ids, run_id: 10 }); }
 return { data: structuredClone(receipt), status: 200, statusText: 'OK', headers: {}, config };
};
const pinia = createPinia();
const app = createApp({ render: () => h(Workbench, { modelValue: true, nodeId: 'pca' }) });
app.use(pinia).use(PrimeVue);
const store = useWorkflowStore(); store.workflowId = 12;
app.mount('#app');
window.vueTick = nextTick;
`,
  );
  server = await createServer({
    root,
    server: {
      host: "127.0.0.1",
      port: 5194,
      strictPort: true,
      fs: { allow: [root, await realpath(resolve(root, "node_modules"))] },
    },
    logLevel: "error",
  });
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://127.0.0.1:5194/.pca-review-fixture.html");
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll(".plotly-canvas")].length === 2 &&
      [...document.querySelectorAll(".plotly-canvas")].every((e) => e._fullLayout && e.calcdata),
  );
  // Actual pointer lasso in the scores chart, then exact linked IDs in the second chart/table.
  const point = page.locator(".plotly-canvas").first().locator(".scatterlayer .point").nth(200);
  await point.scrollIntoViewIfNeeded();
  const box = await point.boundingBox();
  const left = box.x - 5,
    top = box.y - 5,
    right = box.x + box.width + 5,
    bottom = box.y + box.height + 5;
  await page.mouse.move(left, top);
  await page.mouse.down();
  for (const [x, y] of [
    [right, top],
    [right, bottom],
    [left, bottom],
    [left, top],
  ])
    await page.mouse.move(x, y, { steps: 3 });
  await page.mouse.up();
  await page
    .waitForFunction(() =>
      document.querySelectorAll(".plotly-canvas")[1].data.some((t) => t.selectedpoints?.length),
    )
    .catch(async (e) => {
      await page.screenshot({ path: "/private/tmp/pca-review-browser.png", fullPage: true });
      console.log(await page.locator("body").innerText(), errors);
      throw e;
    });
  const lasso = await page.evaluate(() =>
    [...document.querySelectorAll(".plotly-canvas")].map((el) =>
      el.data.flatMap((t) => (t.selectedpoints || []).map((i) => t.customdata[i])).sort(),
    ),
  );
  assert(lasso[0].length > 0);
  assert.deepEqual(lasso[0], lasso[1]);
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await page
    .waitForFunction(() =>
      [...document.querySelectorAll(".plotly-canvas")].every((el) =>
        el.data.every((t) => t.selectedpoints == null),
      ),
    )
    .catch(async (e) => {
      console.log(
        await page.evaluate(() => ({
          status: [...document.querySelectorAll("[role=status]")].map((e) => e.textContent),
          plots: [...document.querySelectorAll(".plotly-canvas")].map((e) =>
            e.data.map((t) => t.selectedpoints),
          ),
        })),
        errors,
      );
      throw e;
    });
  await page.getByRole("checkbox", { name: "Select sample s0002", exact: true }).check();
  await page
    .waitForFunction(() =>
      [...document.querySelectorAll(".plotly-canvas")].every((el) =>
        el.data
          .flatMap((t) => (t.selectedpoints || []).map((i) => t.customdata[i]))
          .includes("s0002"),
      ),
    )
    .catch(async (e) => {
      console.log(
        await page.evaluate(() => ({
          status: [...document.querySelectorAll("[role=status]")].map((e) => e.textContent),
          plots: [...document.querySelectorAll(".plotly-canvas")].map((e) =>
            e.data.map((t) => ({ ids: t.customdata.slice(0, 4), points: t.selectedpoints })),
          ),
        })),
        errors,
      );
      throw e;
    });
  await page
    .getByPlaceholder("For example: high Q; inspect acquisition record")
    .fill("Synthetic browser review");
  await page.getByRole("button", { name: "Mark as outlier", exact: true }).click();
  await page.waitForFunction(
    () =>
      window.reviewCalls.length === 1 &&
      [...document.querySelectorAll(".plotly-canvas")].every((el) =>
        el.data.some((t) => t.marker.symbol === "diamond-open" && t.customdata.includes("s0002")),
      ),
  );
  // Measure native selected event -> BOTH completed Plotly restyles plus Vue table paint.
  const samples = await page.evaluate(async () => {
    const plots = [...document.querySelectorAll(".plotly-canvas")];
    const durations = [];
    for (let i = 0; i < 25; i++) {
      const id = "s" + (i + 10).toString().padStart(4, "0");
      const completed = plots.map(
        (el) => new Promise((resolve) => el.once("plotly_afterplot", resolve)),
      );
      const start = performance.now();
      plots[0].emit("plotly_selected", { points: [{ customdata: id }] });
      await Promise.all(completed);
      await window.vueTick();
      await new Promise(requestAnimationFrame);
      durations.push(performance.now() - start);
    }
    return durations.slice(5).sort((a, b) => a - b);
  });
  const p95 = samples[Math.ceil(samples.length * 0.95) - 1];
  const report = {
    browser: await browser.version(),
    hardware: os.cpus()[0].model,
    platform: os.platform(),
    samples: 5000,
    charts: 2,
    lassoSelected: lasso[0].length,
    selectedEventToBothHighlightsP95Ms: p95,
    maxMs: samples.at(-1),
    errors,
    note: "Synthetic UI receipts; scientific HTTP loop qualified separately.",
  };
  console.log(JSON.stringify(report, null, 2));
  assert.deepEqual(errors, []);
  assert(p95 < 200, "Selection p95 must be below 200ms");
} finally {
  await browser?.close();
  await server?.close();
  await Promise.all([rm(html, { force: true }), rm(entry, { force: true })]);
}
