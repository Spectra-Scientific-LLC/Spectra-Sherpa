'use strict';
const { app, BrowserWindow, Menu, session, dialog, Tray, nativeImage, ipcMain, safeStorage, shell } = require('electron');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { Backend } = require('./backend.cjs');
const { installSessionBoundary, protectWindow } = require('./security.cjs');
const { Lifecycle, readActivity, stopOwnedBackend } = require('./lifecycle.cjs');
const { installFolderPicker, configureDownloads, saveDiagnostics } = require('./native-actions.cjs');
const { loadCredentialKey } = require('./credential.cjs');
const { claimProfile, eraseProfile } = require('./profile-erase.cjs');

app.enableSandbox();
app.setName('Spectra Sherpa');
const website = 'https://spectrascientific.ai/';
const logo = path.join(__dirname, 'assets/logo.png');
let window;
let backend;
let quitting = false;
let starting = false;
let backendVersion = 'Starting';
let lifecycle;
let startTask;
let tray;
let keptAfterErase = [];
const statusPage = (title, description) => {
  const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Spectra Sherpa</title><style>body{font:18px system-ui;background:#f4f7fb;color:#223044;padding:64px;max-width:780px}h1{font-size:30px}p{line-height:1.6;white-space:pre-wrap}</style></head><body><h1>${escape(title)}</h1><p>${escape(description)}</p></body></html>`);
};
// The one local profile this app owns. The shell names it explicitly so the
// credential key, "Delete all local data" and the backend agree on it.
function profileDirectory() {
  if (!app.isPackaged && process.env.SPECTRA_DESKTOP_DEV_PROFILE) return path.resolve(process.env.SPECTRA_DESKTOP_DEV_PROFILE);
  if (process.env.DATA_DIR) return path.resolve(process.env.DATA_DIR);
  return path.join(os.homedir(), '.spectra_sherpa');
}
function launchCommand() {
  const executable = process.platform === 'win32' ? 'SpectraSherpa.exe' : 'SpectraSherpa';
  const profile = ['--data-dir', profileDirectory()];
  if (app.isPackaged) return [path.join(process.resourcesPath, 'backend', executable), profile];
  // Development only: never allow environment-selected executables in a package.
  if (process.env.SPECTRA_DESKTOP_DEV_PYTHON) {
    return [process.env.SPECTRA_DESKTOP_DEV_PYTHON, ['-m', 'spectra_sherpa.desktop_launcher', ...profile]];
  }
  return [path.join(__dirname, '..', 'dist', 'SpectraSherpa', executable), profile];
}
async function startWorkbench() {
  if (starting || quitting) return;
  starting = true;
  try {
    if (backend) await backend.stop();
    await window.loadURL(statusPage('Starting Spectra Sherpa', 'Preparing your local scientific workbench. Database upgrades may take a moment.'));
    const [command, args] = launchCommand();
    await claimProfile(fs, profileDirectory());
    const credential = await loadCredentialKey({ safeStorage, fs, dataDir: profileDirectory() });
    backend = new Backend(command, args, { credentialKey: credential.key,
      trace: stage => console.info(`Spectra Sherpa backend: ${stage}`) });
    const current = backend;
    installSessionBoundary(window.webContents.session, current, () => window?.webContents.id);
    backend.on('unexpected-exit', () => {
      if (backend !== current || quitting || window.isDestroyed()) return;
      backendVersion = 'Stopped';
      if (!starting) void dialog.showMessageBox(window, { type: 'error', message: 'The scientific backend stopped.',
        detail: 'Your saved data remains in your local profile. The current window stays open so you can inspect unsaved edits. Choose Application → Restart workbench to recover.' });
    });
    const endpoint = await backend.start();
    if (keptAfterErase.length && !lifecycle.preparedToClose && !window.isDestroyed()) {
      const kept = keptAfterErase;
      keptAfterErase = [];
      void dialog.showMessageBox(window, { type: 'info', message: 'Spectra Sherpa data was deleted.',
        detail: `These items in ${profileDirectory()} were kept because Spectra Sherpa could not confirm it created them, or they are links:\n${kept.slice(0, 20).join('\n')}${kept.length > 20 ? '\n…' : ''}` });
    }
    if (credential.status === 'unavailable' && !lifecycle.preparedToClose && !window.isDestroyed()) {
      void dialog.showMessageBox(window, { type: 'warning', message: 'Saved API keys are unavailable on this computer.',
        detail: 'The operating system credential protection could not be used, so Spectra Sherpa will not store or use API keys. Your analysis and data are unaffected.' });
    }
    if (credential.status === 'replaced' && !lifecycle.preparedToClose && !window.isDestroyed()) {
      void dialog.showMessageBox(window, { type: 'warning', message: 'Saved API keys need to be entered again.',
        detail: 'The protected key for this profile could not be read on this computer or account. Re-enter your AI provider and HITRAN keys in Settings.' });
    }
    backendVersion = backend.version;
    if (!quitting && !lifecycle.preparedToClose) {
      await window.loadURL(endpoint);
      // Non-sensitive lifecycle receipt for packaged qualification/support.
      console.info('Spectra Sherpa native window ready');
    }
  } catch (error) {
    if (!quitting && !lifecycle.preparedToClose && !window.isDestroyed()) {
      await window.loadURL(statusPage('Spectra Sherpa could not start', `${error.message}\n\nChoose Application → Restart workbench to retry after resolving the problem. Your original data has not been replaced.`));
    }
  } finally { starting = false; }
}
async function confirmErase() {
  const { response } = await dialog.showMessageBox(window, { type: 'warning',
    message: 'Delete all Spectra Sherpa data on this computer?',
    detail: `This permanently deletes the projects, datasets, models, results, logs, backups and saved API keys that Spectra Sherpa stored in:\n${profileDirectory()}\n\nOther files in that folder are kept. Export anything you want to keep first. This cannot be undone.`,
    buttons: ['Cancel', 'Delete all data'], defaultId: 0, cancelId: 0, noLink: true });
  if (response === 1) void lifecycle.request('reset');
}
function focus() {
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
  if (tray) { tray.destroy(); tray = null; }
}
function background() {
  if (!tray) {
    const icon = nativeImage.createFromPath(path.join(__dirname, 'assets/logo.png')).resize({ width: 22, height: 22 });
    tray = new Tray(icon);
    tray.setToolTip('Spectra Sherpa — scientific work continues');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Open workbench', click: focus },
      { label: 'Quit Spectra Sherpa…', click: () => void lifecycle.request('quit') },
    ]));
    tray.on('click', focus);
  }
  window.hide();
}
async function createWindow() {
  const isolated = session.fromPartition(`spectra-desktop-${randomUUID()}`);
  await isolated.setProxy({ mode: 'direct' });
  window = new BrowserWindow({
    width: 1440, height: 960, minWidth: 960, minHeight: 640,
    title: 'Spectra Sherpa', backgroundColor: '#f4f7fb',
    icon: logo,
    webPreferences: { session: isolated, sandbox: true, contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false, nodeIntegrationInWorker: false, webviewTag: false,
      webSecurity: true, allowRunningInsecureContent: false, devTools: !app.isPackaged },
  });
  protectWindow(window, { get endpoint() { return backend?.endpoint; } });
  configureDownloads(isolated, () => window);
  window.on('close', event => {
    if (!lifecycle.allowClose) { event.preventDefault(); void lifecycle.request('close'); }
  });
  window.webContents.on('will-prevent-unload', event => {
    const response = dialog.showMessageBoxSync(window, { type: 'warning',
      message: 'There are unsaved workflow edits.', detail: 'Return to the workbench to save them before leaving.',
      buttons: ['Return to workbench', 'Discard unsaved edits'], defaultId: 0, cancelId: 0, noLink: true });
    if (response === 1) event.preventDefault();
    else lifecycle.cancelUnload();
  });
  startTask = startWorkbench();
  await startTask;
}
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', focus);
  app.on('activate', focus);
  app.on('before-quit', event => {
    if (quitting || !lifecycle) return;
    console.info('Spectra Sherpa lifecycle: before-quit-prevented');
    event.preventDefault();
    void lifecycle.request('quit');
  });
  // Lifecycle owns final quit, including the interval between restart windows.
  app.on('window-all-closed', () => console.info('Spectra Sherpa lifecycle: all-windows-closed'));
  app.on('will-quit', () => console.info('Spectra Sherpa lifecycle: will-quit'));
  app.whenReady().then(async () => {
    lifecycle = new Lifecycle({
      trace: stage => console.info(`Spectra Sherpa lifecycle: ${stage}`),
      activity: () => readActivity(backend),
      ask: question => dialog.showMessageBox(window, question),
      background, close: () => window.close(),
      prepareClose: async () => {
        try {
          await window.loadURL(statusPage('Closing Spectra Sherpa', 'Stopping your local scientific backend.'));
          return true;
        } catch (error) {
          // A cancelled beforeunload clears the intent in will-prevent-unload.
          if (lifecycle.intent === null) return false;
          throw error;
        }
      },
      stop: () => stopOwnedBackend(() => backend, () => startTask),
      failed: async () => {
        if (!window.isDestroyed()) await window.loadURL(statusPage('Spectra Sherpa could not finish closing',
          'The owned backend did not confirm a clean shutdown. Your local data has not been deleted. Keep this window open and save desktop diagnostics before retrying.'));
      },
      restart: createWindow,
      erase: async () => { keptAfterErase = await eraseProfile(fs, profileDirectory()); },
      quit: () => { quitting = true; if (tray) tray.destroy(); app.quit(); },
    });
    installFolderPicker(ipcMain, dialog, () => window, () => backend?.endpoint);
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'Application', submenu: [
        { label: 'About Spectra Sherpa', click: async () => {
          const copyright = 'Copyright © 2026 Spectra Scientific LLC. All rights reserved.';
          const license = 'Spectra Sherpa is licensed under AGPL-3.0-only. Open-source license grants and third-party notices remain applicable.';
          if (process.platform === 'win32') {
            const result = await dialog.showMessageBox(window, { type: 'info',
              title: 'About Spectra Sherpa', message: `Spectra Sherpa ${app.getVersion()}`,
              detail: `${copyright}\n\n${license}\n\n${website}\n\nBackend ${backendVersion}; Electron ${process.versions.electron}; Chromium ${process.versions.chrome}; Node ${process.versions.node}`,
              icon: nativeImage.createFromPath(logo),
              buttons: ['Close', 'Visit spectrascientific.ai'], defaultId: 0, cancelId: 0, noLink: true });
            if (result.response === 1) {
              try { await shell.openExternal(website); }
              catch { await dialog.showMessageBox(window, { message: 'The website could not be opened.', detail: website }); }
            }
            return;
          }
          app.setAboutPanelOptions({ applicationName: 'Spectra Sherpa', applicationVersion: app.getVersion(),
            copyright, credits: license, website, iconPath: logo,
            version: `Backend ${backendVersion}; Electron ${process.versions.electron}; Chromium ${process.versions.chrome}; Node ${process.versions.node}` });
          app.showAboutPanel();
        } },
        { label: 'Restart workbench…', click: () => void lifecycle.request('restart') },
        { label: 'Delete all local data…', click: () => void confirmErase() },
        { label: 'Save desktop diagnostics…', click: () => {
          void saveDiagnostics(dialog, window, { application: app.getVersion(), backend: backendVersion,
            electron: process.versions.electron, chromium: process.versions.chrome }).catch(() => {
            void dialog.showMessageBox(window, { type: 'error', message: 'Diagnostics could not be saved.', detail: 'Check the destination and try again.' });
          });
        } },
        { type: 'separator' }, { role: 'quit' },
      ] },
      { role: 'editMenu' },
      { label: 'View', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
    ]));
    await createWindow();
  }).catch(() => { quitting = true; void Promise.resolve(backend?.stop()).finally(() => app.quit()); });
}
