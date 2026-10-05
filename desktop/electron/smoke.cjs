'use strict';
// Native CI/developer qualification only. All scientific state is disposable.
const { _electron: electron } = require('playwright');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');
async function smoke() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'spectra-electron-smoke-'));
  const application = await electron.launch({
    executablePath: process.env.SPECTRA_DESKTOP_SMOKE_APP || require('electron'),
    args: process.env.SPECTRA_DESKTOP_SMOKE_APP ? [] : [__dirname], timeout: 60000,
    env: { ...process.env, DATA_DIR: profile, SPECTRA_DESKTOP_DEV_PROFILE: profile },
  });
  let endpoint;
  let page;
  try {
    assert.equal(await application.evaluate(() => process.versions.electron), require('./package.json').devDependencies.electron);
    page = await application.firstWindow();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+/, { timeout: 180000 });
    endpoint = new URL(page.url()).origin;
    await page.getByRole('tab', { name: 'Your Project', exact: true, selected: true }).waitFor();
    assert.equal(await page.evaluate(() => typeof process), 'undefined');
    assert.equal(await page.evaluate(() => typeof require), 'undefined');
    assert.equal(await page.evaluate(async () => (await fetch('/api/health')).status), 200);
    assert.equal((await fetch(`${endpoint}/api/health`)).status, 403);
    // A second local service stands in for a hostile destination. No app
    // request (and therefore no transport credential) may reach it.
    let foreignRequests = 0;
    const foreign = http.createServer((_request, response) => { foreignRequests++; response.end('unexpected'); });
    await new Promise(resolve => foreign.listen(0, '127.0.0.1', resolve));
    try {
      const denied = await page.evaluate(async url => {
        try { await fetch(url); return false; } catch { return true; }
      }, `http://127.0.0.1:${foreign.address().port}/capture`);
      assert(denied);
      assert.equal(foreignRequests, 0);
    } finally { await new Promise(resolve => foreign.close(resolve)); }

    const wsResult = await page.evaluate(() => new Promise((resolve, reject) => {
      const ws = new WebSocket(location.origin.replace('http:', 'ws:') + '/ws');
      const timer = setTimeout(() => { ws.close(); reject(new Error('Desktop WebSocket did not answer')); }, 10000);
      ws.onopen = () => ws.send(JSON.stringify({ action: 'ping' }));
      ws.onmessage = event => {
        if (JSON.parse(event.data).type === 'pong') { clearTimeout(timer); ws.close(); resolve(true); }
      };
      ws.onerror = () => { clearTimeout(timer); reject(new Error('Desktop WebSocket refused')); };
    }));
    assert.equal(wsResult, true);
    assert.deepEqual(errors, []);
    if (process.env.SPECTRA_DESKTOP_SMOKE_SCREENSHOT) {
      await page.screenshot({ path: process.env.SPECTRA_DESKTOP_SMOKE_SCREENSHOT });
    }
    console.log(JSON.stringify({ status: 'passed', runtime: process.platform + '-' + process.arch,
      electron: require('./package.json').devDependencies.electron, title: await page.title(),
      checks: ['real-frontend', 'sandbox', 'authorized-http', 'unauthorized-http', 'authorized-websocket'] }));
  } catch (error) {
    // A native startup refusal is displayed in the window; retain its bounded,
    // protocol-redacted explanation rather than reporting only a URL timeout.
    if (page && !page.isClosed()) {
      console.error('Native startup screen:', (await page.locator('body').innerText()).slice(0,4096));
    }
    throw error;
  } finally { await application.close(); }
  assert(!fs.existsSync(path.join(profile, '.spectrasherpa-desktop.lock')), 'Backend still owns the profile after quit');
  if (endpoint) await assert.rejects(fetch(`${endpoint}/api/health`, { signal: AbortSignal.timeout(3000) }));
  fs.rmSync(profile, { recursive: true });
}
smoke().catch(error => { console.error(error.message); process.exitCode = 1; });
