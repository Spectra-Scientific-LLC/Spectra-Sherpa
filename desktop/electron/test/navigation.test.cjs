'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readNavigation, navigationMenu, installNavigation, publishChannel, commandChannel } = require('../navigation.cjs');

const snapshot = {
  generation: 3,
  title: 'Corn · Workflow › Builder',
  menu: true,
  pageId: 'workflow',
  pages: [{ id: 'workflow', label: 'Workflow', sections: [
    { id: 'builder', label: 'Builder', views: [{ id: 'sheet', label: 'Active Sheet' }] },
  ] }],
  primary: { id: 'run', label: 'Run', accelerator: 'CmdOrCtrl+Enter', disabled: false, revision: 9, locationKey: '6' },
};

test('the native menu leads with the current primary and sends opaque commands', () => {
  const sent = [];
  const [workflow] = navigationMenu(readNavigation(snapshot), command => sent.push(command));
  assert.equal(workflow.label, 'Workflow');
  const [run, separator, builder] = workflow.submenu;
  assert.equal(run.label, 'Run');
  assert.equal(run.accelerator, 'CmdOrCtrl+Enter');
  assert.equal(separator.type, 'separator');
  run.click();
  builder.submenu.at(-1).click();
  assert.deepEqual(sent, [
    { kind: 'primary', id: 'run', revision: 9, locationKey: '6', generation: 3 },
    { kind: 'navigate', id: 'sheet', generation: 3 },
  ]);
  assert.deepEqual(navigationMenu({ ...snapshot, menu: false }, () => {}), []);
});

test('snapshots refuse duplicate IDs, invalid keys, and foreign primary accelerators', () => {
  assert.equal(readNavigation({ ...snapshot, pages: [...snapshot.pages, ...snapshot.pages] }), null);
  assert.equal(readNavigation({ ...snapshot, title: 'Control\ncharacter' }), null);
  assert.equal(readNavigation({ ...snapshot, primary: { ...snapshot.primary, accelerator: 'CmdOrCtrl+Q' } }), null);
});

test('trusted focused commands stop after a new snapshot or a renderer reset', () => {
  const endpoint = 'http://127.0.0.1:12345';
  const frame = { url: endpoint + '/workflow' };
  const sent = [];
  let rendererFocus = 0;
  let windowFocus = 0;
  let title;
  let handler;
  let menu;
  const contents = { mainFrame: frame, send: (...args) => sent.push(args), focus: () => { rendererFocus++; } };
  const window = { webContents: contents, isDestroyed: () => false, setTitle: value => { title = value; },
    focus: () => { windowFocus++; } };
  const reset = installNavigation(
    { on: (name, listener) => { assert.equal(name, publishChannel); handler = listener; } },
    { buildFromTemplate: value => value, setApplicationMenu: value => { menu = value; } },
    [{ label: 'File' }], () => window, () => endpoint,
  );
  const event = { sender: contents, senderFrame: frame };
  handler({ ...event, senderFrame: { url: frame.url } }, snapshot);
  assert.equal(menu.length, 1);
  handler(event, snapshot);
  assert.equal(title, snapshot.title);
  const old = menu[1].submenu[0].click;
  old();
  assert.equal(sent[0][0], commandChannel);
  assert.equal(rendererFocus, 1);
  assert.equal(windowFocus, 1);
  handler(event, { ...snapshot, generation: 2 });
  assert.equal(menu[1].submenu[0].click, old);
  handler(event, { ...snapshot, generation: 4, menu: false });
  assert.equal(menu.length, 1);
  old();
  handler(event, { ...snapshot, generation: 5 });
  const current = menu[1].submenu[0].click;
  reset();
  current();
  assert.equal(sent.length, 1);
  assert.equal(title, 'Spectra Sherpa');
});
