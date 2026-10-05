'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { backendURL, installSessionBoundary } = require('../security.cjs');
const { endpointFromFrame } = require('../backend.cjs');
const endpoint = 'http://127.0.0.1:47321';
test('authority excludes other ports, origins, credentials and protocols', () => {
  for (const url of [endpoint, `${endpoint}/api/health`, endpoint.replace('http:', 'ws:') + '/ws']) assert(backendURL(url, endpoint));
  for (const url of ['file:///etc/passwd', 'https://127.0.0.1:47321', 'http://localhost:47321', 'http://127.0.0.1:47322', 'http://token@127.0.0.1:47321', 'https://unrelated.example']) assert(!backendURL(url, endpoint));
  assert(!backendURL(endpoint, null));
});
test('readiness requires the exact private endpoint contract', () => {
  const frame = { protocol: 1, type: 'ready', endpoint, version: '0.6.0' };
  assert.equal(endpointFromFrame(frame), endpoint);
  for (const wrong of ['http://127.0.0.1:0', 'http://127.0.0.1', `${endpoint}/route`, `${endpoint}?token=secret`, 'https://elsewhere.example']) {
    assert.throws(() => endpointFromFrame({ ...frame, endpoint: wrong }));
  }
});
test('only owned web contents receives transport credentials and restart revokes authority', () => {
  let request, headers, permission;
  const session = {
    setPermissionRequestHandler: callback => permission = callback,
    setPermissionCheckHandler: callback => assert.equal(callback(), false),
    webRequest: { onBeforeRequest: callback => request = callback, onBeforeSendHeaders: callback => headers = callback },
  };
  const backend = { endpoint, secret: 'test-secret' };
  installSessionBoundary(session, backend, () => 7);
  for (const id of [7, 8]) {
    headers({ webContentsId: id, url: `${endpoint}/ws`, requestHeaders: { 'x-spectra-desktop-token': 'forged' } }, result => {
      assert.equal(result.requestHeaders['x-spectra-desktop-token'], undefined);
      assert.equal(result.requestHeaders['X-Spectra-Desktop-Token'], id === 7 ? backend.secret : undefined);
    });
    request({ webContentsId: id, url: endpoint }, result => assert.equal(result.cancel, id !== 7));
  }
  request({ webContentsId: 7, url: 'https://unrelated.example' }, result => assert.equal(result.cancel, true));
  permission(null, 'media', result => assert.equal(result, false));
  backend.endpoint = null;
  headers({ webContentsId: 7, url: endpoint, requestHeaders: {} }, result => assert.deepEqual(result.requestHeaders, {}));
});
test('redirects and foreign windows cannot carry a forged transport header', () => {
  let headers;
  const session = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {},
    webRequest: { onBeforeRequest() {}, onBeforeSendHeaders: callback => headers = callback } };
  installSessionBoundary(session, { endpoint, secret: 'session-secret' }, () => 7);
  for (const url of ['https://unrelated.example', 'http://127.0.0.1:9999', 'file:///secret']) {
    headers({ webContentsId: 7, url, requestHeaders: { 'X-SPECTRA-DESKTOP-TOKEN': 'session-secret' } },
      result => assert.deepEqual(result.requestHeaders, {}));
  }
});
test('navigation, redirects, webviews and popups refuse external privileges', () => {
  const { protectWindow } = require('../security.cjs');
  const listeners = {};
  let popup;
  protectWindow({ webContents: { on: (event, callback) => listeners[event] = callback,
    setWindowOpenHandler: callback => popup = callback } }, { endpoint });
  for (const event of ['will-navigate', 'will-redirect']) {
    for (const url of ['file:///private.txt', 'data:text/html,attack', 'https://external.example']) {
      let refused = false;
      listeners[event]({ preventDefault: () => refused = true }, url);
      assert(refused);
    }
    listeners[event]({ preventDefault: () => assert.fail('Canonical navigation refused') }, `${endpoint}/workflow`);
  }
  let refused = false;
  listeners['will-attach-webview']({ preventDefault: () => refused = true });
  assert(refused);
  assert.equal(popup({ url: `${endpoint}/workflow` }).action, 'deny');
});
