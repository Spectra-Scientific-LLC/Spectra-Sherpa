'use strict';
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { EventEmitter } = require('node:events');
const http = require('node:http');

const MAX_FRAME = 4096;
const TOKEN_HEADER = 'X-Spectra-Desktop-Token';
function endpointFromFrame(frame) {
  if (frame.protocol !== 1 || frame.type !== 'ready' || typeof frame.version !== 'string') {
    throw new Error('Unsupported backend readiness response');
  }
  const url = new URL(frame.endpoint);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || Number(url.port) < 1 ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Backend did not report a private loopback endpoint');
  }
  return url.origin;
}
function health(endpoint, secret) {
  return new Promise((resolve, reject) => {
    // Node http connects directly; never consults a system/browser proxy.
    const request = http.get(`${endpoint}/api/health`, {
      headers: { [TOKEN_HEADER]: secret }, timeout: 5000, agent: false,
    }, response => {
      response.resume();
      response.statusCode === 200 ? resolve() : reject(new Error('Backend health authorization failed'));
    });
    request.on('timeout', () => request.destroy(new Error('Backend health check timed out')));
    request.on('error', reject);
  });
}
class Backend extends EventEmitter {
  constructor(command, args = [], options = {}) {
    super();
    this.command = command;
    this.args = args;
    this.options = options;
    this.secret = randomBytes(32).toString('base64url');
    this.endpoint = null;
    this.child = null;
    this.stopping = false;
    // Internal injection supports real-process tests; packaged callers use these bounds.
    this.shutdownTimes = options.shutdownTimes || { graceful: 20000, force: 22000, deadline: 24000 };
    const { graceful, force, deadline } = this.shutdownTimes;
    if (![graceful, force, deadline].every(value => Number.isSafeInteger(value) && value > 0) ||
        graceful >= force || force >= deadline) throw new Error('Invalid owned-backend shutdown bounds');
  }
  async start() {
    if (this.child) throw new Error('Backend is already started');
    const child = spawn(this.command, [...this.args, '--desktop-ipc'], {
      windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'ignore'],
      env: this.options.env || process.env,
    });
    this.child = child;
    // 'close' also waits for inherited stdio in descendants. Ownership ends at
    // this child's exit; a pipe writer must not strand the native shell afterwards.
    this.exited = new Promise(resolve => {
      child.once('exit', () => { this.options.trace?.('process-exited'); resolve(); });
      child.on('error', () => {
        this.options.trace?.('process-error');
        // Node also reports signaling errors here. Only a failed spawn proves
        // there is no owned process; a later error is never an exit receipt.
        if (!child.pid) resolve();
      });
    });
    child.once('close', () => this.options.trace?.('stdio-closed'));
    // EPIPE is possible when startup fails before the launch frame is consumed.
    child.stdin.on('error', () => {});
    child.once('exit', (code, signal) => {
      this.endpoint = null;
      if (!this.stopping) this.emit('unexpected-exit', { code, signal });
    });
    try {
      const ready = await new Promise((resolve, reject) => {
        let buffer = Buffer.alloc(0);
        let settled = false;
        const settle = (error, frame) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          error ? reject(error) : resolve(frame);
        };
        const timer = setTimeout(() => settle(new Error('Backend initialization timed out')), 180000);
        child.once('error', () => settle(new Error('The bundled scientific backend could not be started')));
        child.once('exit', () => settle(new Error('Backend exited before readiness')));
        child.stdout.on('data', chunk => {
          buffer = Buffer.concat([buffer, chunk]);
          let end;
          while ((end = buffer.indexOf(10)) !== -1) {
            if (end + 1 > MAX_FRAME) {
              settle(new Error('Oversized backend protocol frame'));
              void this.stop();
              return;
            }
            const line = buffer.subarray(0, end);
            buffer = buffer.subarray(end + 1);
            try {
              const frame = JSON.parse(line.toString('utf8'));
              if (frame.protocol !== 1) throw new Error('Unsupported backend protocol');
              if (frame.type === 'error') {
                const message = String(frame.message || 'Backend initialization failed').replaceAll(this.secret, '[redacted]');
                settle(new Error(message));
              } else if (frame.type === 'ready') {
                endpointFromFrame(frame);
                settle(null, frame);
              } else if (frame.type === 'stopped') {
                this.options.trace?.('protocol-stopped');
              } else if (frame.type !== 'starting') {
                throw new Error('Unexpected backend protocol frame');
              }
            } catch {
              settle(new Error('Invalid backend protocol response'));
            }
          }
          if (buffer.length > MAX_FRAME) {
            settle(new Error('Oversized backend protocol frame'));
            void this.stop();
          }
        });
        // Keep the ownership pipe open for this launch.
        const launch = { protocol: 1, type: 'launch', secret: this.secret };
        if (this.options.credentialKey) launch.credential_key = this.options.credentialKey;
        child.stdin.write(JSON.stringify(launch) + '\n');
      });
      this.endpoint = endpointFromFrame(ready);
      this.version = ready.version;
      await health(this.endpoint, this.secret);
      return this.endpoint;
    } catch (error) {
      await this.stop();
      throw error;
    }
  }
  stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    this.endpoint = null;
    this.stopPromise = (async () => {
      const child = this.child;
      if (!child) return;
      this.options.trace?.('stop-entered');
      child.stdin.end(() => this.options.trace?.('ownership-pipe-ended'));
      this.options.trace?.('ownership-pipe-end-requested');
      // Signal only our still-running child handle. Never discover or signal PIDs.
      const signal = (name, stage) => {
        if (child.exitCode !== null || child.signalCode !== null || !child.pid) return;
        this.options.trace?.(stage);
        try { child.kill(name); }
        catch { this.options.trace?.('termination-error'); } // Keep escalation/deadline armed.
      };
      const soft = setTimeout(() => signal('SIGTERM', 'termination-requested'), this.shutdownTimes.graceful);
      const hard = setTimeout(() => signal('SIGKILL', 'forced-termination-requested'), this.shutdownTimes.force);
      this.options.trace?.('shutdown-escalation-armed');
      let deadline;
      try {
        await Promise.race([this.exited, new Promise((_, reject) => {
          deadline = setTimeout(() => reject(new Error('Owned backend did not exit within its shutdown deadline')),
            this.shutdownTimes.deadline);
        })]);
        // The process has exited (or failed to spawn). Release our ends even if a
        // descendant retained a writer; this does not signal that descendant.
        child.stdin.destroy();
        child.stdout.destroy();
        this.secret = '';
      } finally {
        clearTimeout(soft);
        clearTimeout(hard);
        clearTimeout(deadline);
      }
    })();
    return this.stopPromise;
  }
}
module.exports = { Backend, endpointFromFrame, TOKEN_HEADER, MAX_FRAME };
