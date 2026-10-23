import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia';
import api from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import { startBrowserSession, renewBrowserSession, readBrowserSession } from '@/extension-contract/session-v1';
let pinia: Pinia;
beforeEach(async () => {
  localStorage.clear(); await startBrowserSession('A');
  pinia = createPinia(); setActivePinia(pinia);
  useAuthStore().user = { id: 7, username: 'A' };
});
afterEach(() => { disposePinia(pinia); vi.unstubAllGlobals(); });

it('does not send an old private payload under a replacement login', async () => {
  const adapter = vi.fn();
  await startBrowserSession('B');
  await expect(api.post('/projects', { name: 'A private draft' }, { adapter })).rejects.toThrow('session changed');
  expect(adapter).not.toHaveBeenCalled();
});

it.each([429, 503])('refuses dispatch without clearing identity on validation %s', async status => {
  const auth = useAuthStore(), revision = auth.sessionRevision;
  await renewBrowserSession(readBrowserSession(), 'renewed', () => true);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })));
  const adapter = vi.fn();
  await expect(api.post('/projects', { name: 'draft' }, { adapter })).rejects.toThrow('could not be verified');
  expect(adapter).not.toHaveBeenCalled();
  expect(auth.sessionRevision).toBe(revision);
  expect(auth.user?.id).toBe(7);
});

it('dispatches with a validated renewal without invalidating its actor', async () => {
  const auth = useAuthStore(), revision = auth.sessionRevision;
  await renewBrowserSession(readBrowserSession(), 'renewed', () => true);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 7 }))));
  const adapter = vi.fn(async config => ({ data: {}, status: 200, statusText: 'OK', headers: {}, config }));
  await api.post('/projects', { name: 'draft' }, { adapter });
  expect(adapter.mock.calls[0]![0].headers.Authorization).toBe('Bearer renewed');
  expect(auth.sessionRevision).toBe(revision);
});
