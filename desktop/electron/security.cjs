'use strict';
const { TOKEN_HEADER } = require('./backend.cjs');
function backendURL(raw, endpoint) {
  if (!endpoint) return false;
  try {
    const url = new URL(raw);
    return !url.username && !url.password && ['http:', 'ws:'].includes(url.protocol) &&
      url.host === new URL(endpoint).host;
  } catch { return false; }
}
function installSessionBoundary(session, backend, windowId) {
  session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.setPermissionCheckHandler(() => false);
  session.webRequest.onBeforeRequest((details, callback) => {
    const own = details.webContentsId === windowId();
    const bundled = details.url.startsWith('data:') && details.resourceType === 'mainFrame';
    const blob = backend.endpoint && details.url.startsWith(`blob:${backend.endpoint}/`);
    callback({ cancel: !(own && (bundled || blob || backendURL(details.url, backend.endpoint))) });
  });
  session.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders };
    for (const key of Object.keys(headers)) {
      if (key.toLowerCase() === TOKEN_HEADER.toLowerCase()) delete headers[key];
    }
    if (details.webContentsId === windowId() && backendURL(details.url, backend.endpoint)) {
      headers[TOKEN_HEADER] = backend.secret;
    }
    callback({ requestHeaders: headers });
  });
}
function protectWindow(window, backend) {
  const restrict = (event, url) => {
    if (!backendURL(url, backend.endpoint) || !url.startsWith('http:')) event.preventDefault();
  };
  window.webContents.on('will-navigate', restrict);
  window.webContents.on('will-redirect', restrict);
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
}
module.exports = { backendURL, installSessionBoundary, protectWindow };
