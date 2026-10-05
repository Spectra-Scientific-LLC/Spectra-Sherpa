'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { installFolderPicker, saveDiagnostics } = require('../native-actions.cjs');
test('folder picker is main-frame/endpoint bound and accepts no renderer arguments', async () => {
  const endpoint = 'http://127.0.0.1:12345';
  const frame = { url: endpoint + '/deploy' };
  const contents = { mainFrame: frame };
  const window = { webContents: contents, isDestroyed: () => false };
  let handler, opens = 0;
  installFolderPicker({ handle: (name, callback) => { assert.equal(name, 'spectra:choose-watch-folder'); handler = callback; } },
    { showOpenDialog: async () => { opens++; return { canceled: false, filePaths: ['/selected/by/user'] }; } },
    () => window, () => endpoint);
  const event = { sender: contents, senderFrame: frame };
  assert.equal(await handler(event), '/selected/by/user');
  await assert.rejects(handler(event, '/arbitrary/path'));
  await assert.rejects(handler({ ...event, senderFrame: { url: endpoint } }));
  await assert.rejects(handler({ ...event, sender: {} }));
  frame.url = 'https://external.example';
  await assert.rejects(handler(event));
  assert.equal(opens, 1);
});
test('diagnostics are an explicit allowlist without token, environment, logs or spectra', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'sherpa-diagnostics-'));
  try {
    const output = path.join(dir, 'diagnostics.json');
    await saveDiagnostics({ showSaveDialog: async () => ({ canceled: false, filePath: output }) }, {},
      { application: '0.6.0', backend: '0.6.0', electron: '44.4.5', chromium: 'test',
        token: 'private', logs: ['spectrum'], environment: process.env });
    const result = JSON.parse(await fs.readFile(output, 'utf8'));
    assert.equal(result.application, '0.6.0');
    assert.equal(result.token, undefined);
    assert.equal(result.logs, undefined);
    assert.equal(result.environment, undefined);
    assert.deepEqual(Object.keys(result).sort(), ['application', 'architecture', 'backend', 'chromium', 'electron', 'format', 'platform', 'timestamp']);
  } finally { await fs.rm(dir, { recursive: true }); }
});
