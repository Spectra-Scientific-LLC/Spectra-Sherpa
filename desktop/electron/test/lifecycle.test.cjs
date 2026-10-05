'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Lifecycle, closeQuestion, stopOwnedBackend } = require('../lifecycle.cjs');
function fixture(activity, response) {
  const calls = [];
  const actions = { activity: async () => activity,
    ask: async question => { calls.push(question); return { response }; },
    background: () => calls.push('background'), close: () => calls.push('close'),
    prepareClose: async () => { calls.push('prepare'); return true; },
    stop: async () => calls.push('stop'), restart: async () => calls.push('restart'),
    erase: async () => calls.push('erase'), failed: async error => calls.push(error),
    quit: () => calls.push('quit') };
  const controller = new Lifecycle(actions);
  return { controller, actions, calls };
}
test('cancelled renderer navigation preserves backend and permits a later accepted quit', async () => {
  const { controller, actions, calls } = fixture({}, 0);
  actions.prepareClose = async () => { calls.push('prepare'); controller.cancelUnload(); return false; };
  await controller.request('quit');
  assert.deepEqual(calls, ['prepare']);
  assert.equal(controller.intent, null);
  assert.equal(controller.allowClose, false);
  actions.prepareClose = async () => { calls.push('prepare'); return true; };
  await controller.request('quit');
  assert.deepEqual(calls, ['prepare', 'prepare', 'stop', 'close', 'quit']);
});
test('the native window stays alive until owned backend exit is confirmed', async () => {
  const { controller, actions, calls } = fixture({}, 0);
  let release;
  actions.stop = () => new Promise(resolve => { calls.push('stop'); release = resolve; });
  const pending = controller.request('quit');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['prepare', 'stop']);
  assert.equal(controller.allowClose, false);
  await controller.request('close');
  await controller.request('reset');
  assert.deepEqual(calls, ['prepare', 'stop'], 'Concurrent close/reset must not duplicate shutdown');
  release();
  await pending;
  assert.deepEqual(calls, ['prepare', 'stop', 'close', 'quit']);
});
test('reset waits for a backend assigned after pre-spawn startup was already closing', async () => {
  const { controller, actions, calls } = fixture({}, 0);
  let backend;
  let credentialsReady;
  let processExited;
  const startup = new Promise(resolve => { credentialsReady = resolve; });
  actions.stop = () => stopOwnedBackend(() => backend, () => startup);
  const pending = controller.request('reset');
  await new Promise(resolve => setImmediate(resolve));
  assert(controller.preparedToClose, 'Startup must suppress workbench navigation after accepted close');
  assert.deepEqual(calls, ['prepare']);
  backend = { stop: () => new Promise(resolve => { calls.push('stop-late-backend'); processExited = resolve; }) };
  credentialsReady();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['prepare', 'stop-late-backend']);
  assert.equal(controller.allowClose, false);
  processExited();
  await pending;
  assert.deepEqual(calls, ['prepare', 'stop-late-backend', 'erase', 'close', 'restart']);
  assert.equal(controller.preparedToClose, false);
});
test('active watch close offers background without stopping or closing renderer', async () => {
  const { controller, calls } = fixture({ watches: 2 }, 1);
  await controller.request('close');
  assert(calls[0].message.includes('2 folder watch'));
  assert.deepEqual(calls.slice(1), ['background']);
  assert.equal(controller.allowClose, false);
});
test('cancel leaves analysis and window untouched', async () => {
  const { controller, calls } = fixture({ jobs: true }, 0);
  await controller.request('quit');
  assert.equal(calls.length, 1);
  assert.equal(controller.allowClose, false);
});
test('restart confirms interruption and stops old backend before closing or restarting', async () => {
  const { controller, calls } = fixture({ jobs: true, watches: 1 }, 1);
  await controller.request('restart');
  assert.deepEqual(calls.slice(1), ['prepare', 'stop', 'close', 'restart']);
  assert.equal(controller.allowClose, false);
});
test('unknown activity is disclosed and defaults to cancel', () => {
  const question = closeQuestion('quit', { unknown: true });
  assert.match(question.message, /could not confirm/);
  assert.equal(question.defaultId, 0);
  assert.equal(question.cancelId, 0);
});
test('delete-all-data erases only after backend exit then closes and starts fresh', async () => {
  const { controller, calls } = fixture({}, 0);
  await controller.request('reset');
  assert.deepEqual(calls, ['prepare', 'stop', 'erase', 'close', 'restart']);
});
for (const action of ['quit', 'restart', 'reset']) {
  test(`${action} failure leaves the window open and never erases or restarts`, async () => {
    const { controller, actions, calls } = fixture({}, 0);
    const error = new Error('Owned process did not exit');
    actions.stop = async () => { calls.push('stop'); throw error; };
    await controller.request(action);
    assert.deepEqual(calls, ['prepare', 'stop', error]);
    assert.equal(controller.allowClose, false);
    assert.equal(controller.busy, false);
  });
}
test('failed navigation is reported before any backend action', async () => {
  const { controller, actions, calls } = fixture({}, 0);
  const error = new Error('Navigation failed');
  actions.prepareClose = async () => { throw error; };
  await controller.request('quit');
  assert.deepEqual(calls, [error]);
});
test('delete-all-data with active work names the destructive choice', () => {
  const question = closeQuestion('reset', { jobs: true, watches: 0, unknown: false });
  assert.deepEqual(question.buttons, ['Cancel', 'Stop work and delete data']);
  assert.equal(question.defaultId, 0);
  assert.equal(question.cancelId, 0);
});
