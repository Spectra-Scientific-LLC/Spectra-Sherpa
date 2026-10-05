'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// No paths, event object, raw IPC, arbitrary channel or filesystem API is exposed.
contextBridge.exposeInMainWorld('spectraDesktop', Object.freeze({
  chooseWatchFolder: () => ipcRenderer.invoke('spectra:choose-watch-folder'),
}));
