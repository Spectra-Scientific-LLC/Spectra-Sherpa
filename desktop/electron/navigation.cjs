// Builds native menus from the current trusted workbench's navigation snapshot.
'use strict';

const { admitNativeSender } = require('./native-actions.cjs');

const publishChannel = 'spectra:navigation:publish';
const commandChannel = 'spectra:navigation:command';
const boundedText = (value, limit = 128) =>
  typeof value === 'string' && value.length > 0 && value.length <= limit && !/[\x00-\x1f\x7f]/.test(value);

function readNavigation(value) {
  if (!value || !Number.isSafeInteger(value.generation) || value.generation < 1
      || typeof value.menu !== 'boolean' || !boundedText(value.title, 320)
      || !Array.isArray(value.pages) || value.pages.length > 32) return null;
  const ids = new Set();
  function readNode(node, children, nextChildren) {
    if (!node || !boundedText(node.id) || !boundedText(node.label, 96) || ids.has(node.id)) return null;
    ids.add(node.id);
    if (!children) return { id: node.id, label: node.label };
    if (!Array.isArray(node[children]) || node[children].length > 32) return null;
    const nodes = node[children].map(entry => readNode(entry, nextChildren));
    return nodes.includes(null) ? null : { id: node.id, label: node.label, [children]: nodes };
  }
  const pages = value.pages.map(page => readNode(page, 'sections', 'views'));
  if (pages.includes(null) || (value.pageId != null && !pages.some(page => page.id === value.pageId))) return null;
  let primary = null;
  if (value.primary != null) {
    const action = value.primary;
    if (!boundedText(action.id) || !boundedText(action.label, 96) || !boundedText(action.locationKey)
        || !Number.isSafeInteger(action.revision) || typeof action.disabled !== 'boolean'
        || (action.accelerator != null && action.accelerator !== 'CmdOrCtrl+Enter')) return null;
    primary = { id: action.id, label: action.label, locationKey: action.locationKey, revision: action.revision,
      disabled: action.disabled, accelerator: action.accelerator };
  }
  return { pages, primary, pageId: value.pageId, generation: value.generation, title: value.title, menu: value.menu };
}

function navigationMenu(snapshot, send) {
  if (!snapshot.menu) return [];
  const click = id => () => send({ kind: 'navigate', id, generation: snapshot.generation });
  return snapshot.pages.map(page => {
    const submenu = [];
    const primary = page.id === snapshot.pageId ? snapshot.primary : null;
    if (primary) {
      submenu.push({ label: primary.label, enabled: !primary.disabled, accelerator: primary.accelerator,
        click: () => send({ kind: 'primary', id: primary.id, revision: primary.revision,
          locationKey: primary.locationKey, generation: snapshot.generation }) });
      submenu.push({ type: 'separator' });
    }
    if (!page.sections.length) submenu.push({ label: `Open ${page.label}`, click: click(page.id) });
    for (const section of page.sections) {
      submenu.push(section.views.length
        ? { label: section.label, submenu: [
          { label: `Open ${section.label}`, click: click(section.id) },
          { type: 'separator' },
          ...section.views.map(view => ({ label: view.label, click: click(view.id) })),
        ] }
        : { label: section.label, click: click(section.id) });
    }
    return { label: page.label, submenu };
  });
}

function installNavigation(ipcMain, Menu, baseMenu, getWindow, getEndpoint) {
  let owner;
  let latest;
  function reset() {
    owner = latest = undefined;
    Menu.setApplicationMenu(Menu.buildFromTemplate(baseMenu));
    const window = getWindow();
    if (window && !window.isDestroyed()) window.setTitle('Spectra Sherpa');
  }
  ipcMain.on(publishChannel, (event, value) => {
    const window = getWindow();
    if (!admitNativeSender(event, window, getEndpoint())) return;
    const snapshot = readNavigation(value);
    if (!snapshot || (owner === event.senderFrame && latest && snapshot.generation <= latest.generation)) return;
    owner = event.senderFrame;
    latest = snapshot;
    const send = (command) => {
      if (window !== getWindow() || window.isDestroyed() || latest !== snapshot) return;
      const contents = window.webContents;
      if (!admitNativeSender({ sender: contents, senderFrame: contents.mainFrame }, window, getEndpoint())
          || contents.mainFrame !== owner) return;
      contents.send(commandChannel, command);
      window.focus();
      contents.focus();
    };
    window.setTitle(snapshot.menu ? snapshot.title : 'Spectra Sherpa');
    Menu.setApplicationMenu(Menu.buildFromTemplate([...baseMenu, ...navigationMenu(snapshot, send)]));
  });
  reset();
  return reset;
}

module.exports = { readNavigation, navigationMenu, installNavigation, publishChannel, commandChannel };
