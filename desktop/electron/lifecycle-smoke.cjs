'use strict';
const { _electron: electron } = require('playwright');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
async function smoke() {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'spectra-lifecycle-'));
  const application = await electron.launch({ executablePath: process.env.SPECTRA_DESKTOP_SMOKE_APP || require('electron'),
    args: process.env.SPECTRA_DESKTOP_SMOKE_APP ? [] : [__dirname], timeout: 60000,
    env: { ...process.env, DATA_DIR: profile, SPECTRA_DESKTOP_DEV_PROFILE: profile } });
  try {
    let page = await application.firstWindow();
    await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+/, { timeout: 180000 });
    await page.getByRole('tab', { name: 'Your Project', exact: true, selected: true }).waitFor();
    const oldEndpoint = new URL(page.url()).origin;
    // Exercise the real context-isolated bridge; substitute only the OS chooser.
    await application.evaluate(({ dialog }, selected) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [selected] });
      global.lifecyclePrompts = [];
      global.lifecyclePromptResponse = 0;
      dialog.showMessageBoxSync = (_window, options) => {
        global.lifecyclePrompts.push(options.message); return global.lifecyclePromptResponse;
      };
    }, profile);
    assert.equal(await page.evaluate(() => window.spectraDesktop.chooseWatchFolder()), profile);
    assert.deepEqual(await page.evaluate(() => Object.keys(window.spectraDesktop)), ['chooseWatchFolder']);
    const exported = path.join(profile, 'native-export.csv');
    await application.evaluate(({ BrowserWindow }, destination) => {
      BrowserWindow.getAllWindows()[0].webContents.session.once('will-download', (_event, item) => {
        global.downloadDialogTitle = item.getSaveDialogOptions().title;
        item.setSavePath(destination); // Substitute only the OS save chooser.
      });
    }, exported);
    await page.evaluate(() => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob(['sample,prediction\nA,1.25\n'], { type: 'text/csv' }));
      link.download = 'prediction.csv'; link.click();
    });
    let contents;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { contents = await fs.readFile(exported, 'utf8'); break; } catch { await new Promise(resolve => setTimeout(resolve, 100)); }
    }
    assert.equal(contents, 'sample,prediction\nA,1.25\n');
    assert.equal(await application.evaluate(() => global.downloadDialogTitle), 'Export from Spectra Sherpa');

    // Electron's will-prevent-unload handler owns this native prompt.
    // Suppress Playwright's default competing CDP auto-dismiss.
    page.on('dialog', () => {});
    await page.locator('body').click({ position: { x: 700, y: 400 } });
    await page.evaluate(() => {
      window.testUnsaved = true;
      window.addEventListener('beforeunload', event => {
        if (window.testUnsaved) { event.preventDefault(); event.returnValue = ''; }
      });
    });
    await application.evaluate(({ Menu }) => Menu.getApplicationMenu().items[0].submenu.items
      .find(item => item.label === 'Restart workbench…').click());
    for (let attempt = 0; attempt < 100; attempt++) {
      if (await application.evaluate(() => global.lifecyclePrompts.length)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal(await application.evaluate(() => global.lifecyclePrompts.length), 1);
    assert.equal(await page.evaluate(async () => (await fetch('/api/health')).status), 200,
      'Cancelling unsaved-edit close must preserve the running backend');
    // Keep the same unsaved handler: now accept the actual discard prompt.
    await application.evaluate(() => { global.lifecyclePromptResponse = 1; });
    const nextWindow = application.waitForEvent('window');
    await application.evaluate(({ Menu }) => Menu.getApplicationMenu().items[0].submenu.items
      .find(item => item.label === 'Restart workbench…').click());
    page = await nextWindow;
    await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+/, { timeout: 180000 });
    await page.getByRole('tab', { name: 'Your Project', exact: true, selected: true }).waitFor();
    assert.equal(await application.evaluate(() => global.lifecyclePrompts.length), 2,
      'Accepted restart must pass through the renderer unsaved-edit decision');
    await assert.rejects(fetch(`${oldEndpoint}/api/health`, { signal: AbortSignal.timeout(3000) }));
    console.log(JSON.stringify({ status: 'passed', checks: ['native-folder-bridge', 'native-export', 'cancel-unsaved-preserves-backend', 'accepted-discard-before-restart', 'restart-reaps-old-backend'] }));
  } finally { await application.close(); }
  await assert.rejects(fs.access(path.join(profile, '.spectrasherpa-desktop.lock')));
  await fs.rm(profile, { recursive: true });
}
smoke().catch(error => { console.error(error); process.exitCode = 1; });
