'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// No paths, event object, raw IPC, arbitrary channel or filesystem API is exposed.
contextBridge.exposeInMainWorld('spectraDesktop', Object.freeze({
  chooseWatchFolder: () => ipcRenderer.invoke('spectra:choose-watch-folder'),
  publishNavigation: snapshot => ipcRenderer.send('spectra:navigation:publish', snapshot),
  onNavigationCommand: callback => {
    const listener = (_event, command) => callback(command);
    ipcRenderer.on('spectra:navigation:command', listener);
    return () => ipcRenderer.removeListener('spectra:navigation:command', listener);
  },
}));
