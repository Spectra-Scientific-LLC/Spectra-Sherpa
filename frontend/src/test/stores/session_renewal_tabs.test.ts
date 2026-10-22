import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia';
import { useAuthStore } from '@/stores/auth';
import { useProjectStore } from '@/stores/project';
import { useWorkflowStore } from '@/stores/workflow';
import { startBrowserSession, readBrowserSession, readBrowserToken, endBrowserSession, renewBrowserSession } from '@/extension-contract/session-v1';

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const instances: Pinia[] = [];
const originalFetch = globalThis.fetch;
beforeEach(() => { localStorage.clear(); });
afterEach(() => { instances.splice(0).forEach(disposePinia); globalThis.fetch = originalFetch; });
function tab() {
  const pinia = createPinia(); instances.push(pinia); setActivePinia(pinia);
  const auth = useAuthStore(); auth.user = { id: 7, username: 'first' };
  const project = useProjectStore(); project.currentProjectId = 129;
  const workflow = useWorkflowStore(); workflow.workflowId = 385;
  workflow.nodes = [{ id: 'snv', type: 'preprocess.normalize' }] as never;
  return { auth, project, workflow };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe('cross-tab renewable credential authority', () => {
  it('preserves the receiving workspace only after exact credential validation', async () => {
    await startBrowserSession('original');
    const first = tab(), second = tab();
    const revision = second.auth.sessionRevision;
    const held = deferred<Response>();
    globalThis.fetch = vi.fn(() => held.promise);
    expect(await first.auth.acceptRenewal(first.auth.captureSession(), 'renewed')).toBe(true);
    let ready = false;
    const pending = second.auth.ensureStoredSession().then(() => { ready = true; });
    expect(ready).toBe(false);
    expect(second.project.currentProjectId).toBe(129);
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/auth/me', expect.objectContaining({
      headers: { Authorization: 'Bearer renewed' },
    }));
    held.resolve(new Response(JSON.stringify({ id: 7, is_active: true })));
    await pending;
    expect(second.auth.token).toBe('renewed');
    expect(second.auth.sessionRevision).toBe(revision);
    expect(second.workflow.workflowId).toBe(385);
    expect(second.workflow.nodes).toHaveLength(1);
  });

  it.each(['different-user', 'rejected', 'logout', 'same-token-login'])(
    'does not preserve or restore the old workspace after %s', async kind => {
      await startBrowserSession('original');
      const first = tab(), second = tab();
      const held = deferred<Response>(); globalThis.fetch = vi.fn(() => held.promise);
      await first.auth.acceptRenewal(first.auth.captureSession(), 'renewed');
      const pending = second.auth.ensureStoredSession();
      if (kind === 'logout') await endBrowserSession();
      if (kind === 'same-token-login') await startBrowserSession('renewed');
      held.resolve(kind === 'rejected' ? new Response('', { status: 401 }) :
        new Response(JSON.stringify({ id: kind === 'different-user' ? 8 : 7 })));
      await pending.catch(() => undefined);
      expect(second.auth.user).toBeNull();
      expect(second.project.currentProjectId).toBeNull();
      expect(second.workflow.nodes).toEqual([]);
    },
  );

  it('gates requests on network failure without discarding the canvas and allows retry', async () => {
    await startBrowserSession('original');
    const first = tab(), second = tab();
    await first.auth.acceptRenewal(first.auth.captureSession(), 'renewed');
    globalThis.fetch = vi.fn().mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 7 })));
    await expect(second.auth.ensureStoredSession()).rejects.toThrow('could not be verified');
    expect(second.workflow.workflowId).toBe(385);
    await second.auth.ensureStoredSession();
    expect(second.auth.token).toBe('renewed');
    expect(second.workflow.workflowId).toBe(385);
  });

  it('serializes competing renewals and never overwrites a new login or logout', async () => {
    await startBrowserSession('original');
    const old = readBrowserSession();
    const results = await Promise.all([
      renewBrowserSession(old, 'first', () => true),
      renewBrowserSession(old, 'second', () => true),
    ]);
    expect(results.filter(Boolean)).toHaveLength(1);
    expect(readBrowserToken()).toBe('first');
    await startBrowserSession('replacement');
    expect(await renewBrowserSession(old, 'late', () => true)).toBeNull();
    expect(await endBrowserSession(old)).toBeNull();
    expect(readBrowserToken()).toBe('replacement');
    const current = readBrowserSession();
    await endBrowserSession(current);
    expect(await renewBrowserSession(current, 'resurrect', () => true)).toBeNull();
    expect(readBrowserToken()).toBeNull();
  });

  it.each([429, 500, 503])('retains the receiving workspace when validation returns %s', async status => {
    await startBrowserSession('original');
    const first = tab(), second = tab();
    const revision = second.auth.sessionRevision;
    await first.auth.acceptRenewal(first.auth.captureSession(), 'renewed');
    globalThis.fetch = vi.fn().mockResolvedValueOnce(new Response('', { status }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 7 })));
    await expect(second.auth.ensureStoredSession()).rejects.toThrow('could not be verified');
    expect(second.auth.sessionRevision).toBe(revision);
    expect(second.workflow.workflowId).toBe(385);
    await second.auth.ensureStoredSession();
    expect(second.auth.token).toBe('renewed');
  });
});
