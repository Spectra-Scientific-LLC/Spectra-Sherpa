'use strict';
const http = require('node:http');
const { TOKEN_HEADER } = require('./backend.cjs');
function readJSON(backend, route) {
  return new Promise((resolve, reject) => {
    if (!backend?.endpoint) return resolve([]);
    const request = http.get(backend.endpoint + route, { agent: false, timeout: 5000,
      headers: { [TOKEN_HEADER]: backend.secret } }, response => {
      let body = '';
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 1024 * 1024) request.destroy(new Error('Activity response exceeds limit'));
      });
      response.on('error', reject);
      response.on('end', () => {
        if (response.statusCode !== 200) return reject(new Error('Activity status unavailable'));
        try {
          const value = JSON.parse(body);
          if (!Array.isArray(value)) throw new Error('Invalid activity response');
          resolve(value);
        } catch (error) { reject(error); }
      });
    });
    request.on('timeout', () => request.destroy(new Error('Activity check timed out')));
    request.on('error', reject);
  });
}
async function readActivity(backend) {
  try {
    const [running, pending, watches] = await Promise.all([
      readJSON(backend, '/api/v1/jobs?status=running&limit=1'),
      readJSON(backend, '/api/v1/jobs?status=pending&limit=1'),
      readJSON(backend, '/api/v1/deploy/watches'),
    ]);
    return { jobs: running.length + pending.length > 0,
      watches: watches.filter(item => item.is_enabled === true).length, unknown: false };
  } catch { return { jobs: false, watches: 0, unknown: true }; }
}
function closeQuestion(action, activity) {
  if (!activity.jobs && !activity.watches && !activity.unknown) return null;
  const background = action === 'close';
  return {
    type: 'warning', title: 'Scientific work is still active',
    message: activity.unknown ? 'Sherpa could not confirm whether scientific work is active.' :
      [activity.jobs && 'An analysis is running or waiting.', activity.watches && `${activity.watches} folder watch(es) are enabled.`].filter(Boolean).join('\n'),
    detail: 'Stopping the workbench interrupts active work. Folder watching pauses until you reopen the app. Return to the workbench to save or stop work first.',
    buttons: background ? ['Cancel', 'Keep running in background', 'Stop work and quit'] :
      ['Cancel', { restart: 'Stop work and restart', reset: 'Stop work and delete data' }[action] || 'Stop work and quit'],
    defaultId: 0, cancelId: 0, noLink: true,
  };
}
async function stopOwnedBackend(getBackend, getStartup) {
  await getBackend()?.stop();
  await getStartup();
  // Startup can still be awaiting credentials before it assigns its backend.
  // Re-read ownership after that task settles; never erase a live profile.
  await getBackend()?.stop();
}
class Lifecycle {
  constructor(actions) {
    this.actions = actions; this.busy = false; this.intent = null;
    this.allowClose = false; this.preparedToClose = false;
  }
  async request(action) {
    if (this.busy || this.allowClose) return;
    this.busy = true;
    try {
      this.actions.trace?.('checking-activity');
      const activity = await this.actions.activity();
      this.actions.trace?.(activity.unknown ? 'activity-unknown' : activity.jobs || activity.watches ? 'activity-active' : 'activity-idle');
      const question = closeQuestion(action, activity);
      if (question) {
        const { response } = await this.actions.ask(question);
        if (response === 0) return;
        if (action === 'close' && response === 1) { this.actions.background(); return; }
      }
      this.intent = ['restart', 'reset'].includes(action) ? action : 'quit';
      // Navigation exercises the renderer's real beforeunload decision while
      // retaining a native window to keep Electron's event loop running.
      this.actions.trace?.('preparing-close');
      if (!await this.actions.prepareClose()) { this.intent = null; return; }
      this.preparedToClose = true;
      const intent = this.intent;
      this.actions.trace?.('stopping-backend');
      await this.actions.stop();
      this.actions.trace?.('backend-stopped');
      // Erase only after confirmed owned-process exit and profile release.
      if (intent === 'reset') await this.actions.erase();
      this.allowClose = true;
      this.actions.trace?.('closing-window');
      this.actions.close();
      if (intent === 'restart' || intent === 'reset') {
        this.allowClose = false;
        this.preparedToClose = false;
        await this.actions.restart();
      } else this.actions.quit();
    } catch (error) {
      this.allowClose = false;
      this.actions.trace?.('shutdown-failed');
      await this.actions.failed(error);
    } finally { this.intent = null; this.busy = false; }
  }
  cancelUnload() { this.actions.trace?.('unload-cancelled'); this.allowClose = false; this.intent = null; }
}
module.exports = { Lifecycle, readActivity, closeQuestion, stopOwnedBackend };
