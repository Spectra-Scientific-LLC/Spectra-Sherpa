'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { Backend } = require('../backend.cjs');
const fixture = path.join(__dirname, 'fixtures/backend.cjs');
test('real pipe handshake and authorized health; shutdown closes owned process', async () => {
  const backend = new Backend(process.execPath, [fixture]);
  try {
    const endpoint = await backend.start();
    assert.match(endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
    assert.equal((await fetch(`${endpoint}/api/health`)).status, 403);
    assert.equal(backend.version, '0.6.0');
    await backend.stop();
    assert.equal(backend.child.exitCode, 0);
    assert.equal(backend.secret, '');
    assert.equal(backend.endpoint, null);
  } finally { await backend.stop(); }
});
for (const mode of ['oversize', 'invalid', 'failure']) {
  test(`refuse ${mode} protocol and reap owned child`, async () => {
    const backend = new Backend(process.execPath, [fixture, mode]);
    await assert.rejects(backend.start());
    assert.equal(backend.child.exitCode, 0);
    assert.equal(backend.endpoint, null);
  });
}
test('missing executable fails clearly without a hanging cleanup', async () => {
  const backend = new Backend(path.join(__dirname, 'absent-executable'));
  await assert.rejects(backend.start(), /could not be started/);
});

test('owned process exit completes shutdown even while a descendant retains stdout', async () => {
  const backend = new Backend(process.execPath, [fixture, 'inherited-stdout']);
  try {
    await backend.start();
    const stopped = backend.stop();
    let deadline;
    try {
      await Promise.race([stopped, new Promise((_, reject) => {
        deadline = setTimeout(() => reject(new Error('Shutdown waited for descendant stdio')), 1000);
      })]);
    } finally { clearTimeout(deadline); }
    assert.equal(backend.child.exitCode, 0);
    assert.equal(backend.secret, '');
    assert(backend.child.stdout.destroyed);
  } finally { await backend.stop(); }
});
test('uncooperative owned backend is reaped within a bounded shutdown', async () => {
  const stages = [];
  const backend = new Backend(process.execPath, [fixture, 'stubborn'], {
    shutdownTimes: { graceful: 50, force: 100, deadline: 2000 }, trace: stage => stages.push(stage),
  });
  try {
    await backend.start();
    await backend.stop();
    assert(stages.includes('termination-requested'));
    if (process.platform !== 'win32') assert(stages.includes('forced-termination-requested'));
    assert(stages.includes('process-exited'));
    assert(backend.child.exitCode !== null || backend.child.signalCode !== null);
    assert.equal(backend.secret, '');
    assert.equal(backend.endpoint, null);
  } finally { await backend.stop(); }
});

test('a signaling error never counts as owned process exit', async () => {
  const backend = new Backend(process.execPath, [fixture, 'stubborn'], {
    shutdownTimes: { graceful: 50, force: 200, deadline: 2000 },
  });
  try {
    await backend.start();
    const kill = backend.child.kill.bind(backend.child);
    let reportFailure;
    const failedSignal = new Promise(resolve => { reportFailure = resolve; });
    backend.child.kill = signal => {
      if (signal === 'SIGTERM') {
        backend.child.emit('error', new Error('Simulated signaling refusal'));
        reportFailure();
        return false;
      }
      return kill(signal);
    };
    let resolved = false;
    const stopped = backend.stop().then(() => { resolved = true; });
    await failedSignal;
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(resolved, false);
    assert.equal(backend.child.exitCode, null);
    assert.equal(backend.child.signalCode, null);
    await stopped;
    assert(backend.child.exitCode !== null || backend.child.signalCode !== null);
  } finally { await backend.stop(); }
});
