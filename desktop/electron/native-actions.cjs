'use strict';
const path = require('node:path');
const fs = require('node:fs/promises');
const { backendURL } = require('./security.cjs');
function admitNativeSender(event, window, endpoint) {
  return !!window && !window.isDestroyed() && event.sender === window.webContents &&
    event.senderFrame === window.webContents.mainFrame && backendURL(event.senderFrame?.url, endpoint) &&
    event.senderFrame.url.startsWith('http:');
}
function installFolderPicker(ipcMain, dialog, getWindow, getEndpoint) {
  let pending = false;
  ipcMain.handle('spectra:choose-watch-folder', async (event, ...args) => {
    const window = getWindow();
    if (args.length || !admitNativeSender(event, window, getEndpoint())) throw new Error('Native action is unavailable');
    if (pending) return null;
    pending = true;
    try {
      const result = await dialog.showOpenDialog(window, { title: 'Choose a folder for inference', properties: ['openDirectory'] });
      return result.canceled ? null : result.filePaths[0] || null;
    } finally { pending = false; }
  });
}
function configureDownloads(session, getWindow) {
  session.on('will-download', (event, item, contents) => {
    const window = getWindow();
    if (!window || contents !== window.webContents) { event.preventDefault(); return; }
    item.setSaveDialogOptions({ title: 'Export from Spectra Sherpa', defaultPath: path.basename(item.getFilename()) });
    item.once('done', (_event, state) => {
      if (state === 'interrupted' && !window.isDestroyed()) {
        const { dialog } = require('electron');
        void dialog.showMessageBox(window, { type: 'error', message: 'Export did not finish.', detail: 'Check the destination and try exporting again.' });
      }
    });
  });
}
async function saveDiagnostics(dialog, window, versions) {
  const selected = await dialog.showSaveDialog(window, { title: 'Save desktop diagnostics',
    defaultPath: 'spectra-desktop-diagnostics.json', filters: [{ name: 'JSON', extensions: ['json'] }] });
  if (selected.canceled || !selected.filePath) return;
  // Explicit allowlist: no logs, spectra, paths, tokens, environment, or chat text.
  const report = { format: 'spectra-desktop-diagnostics/1', application: versions.application,
    backend: versions.backend, electron: versions.electron, chromium: versions.chromium,
    platform: process.platform, architecture: process.arch, timestamp: new Date().toISOString() };
  await fs.writeFile(selected.filePath, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
}
module.exports = { admitNativeSender, installFolderPicker, configureDownloads, saveDiagnostics };
