import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { endBrowserSession, readBrowserSession, renewBrowserSession, startBrowserSession } from '@/extension-contract/session-v1';

// Plain-HTTP access to a local workbench on a LAN address is not a secure
// context: the browser then offers neither Web Locks nor crypto.randomUUID.
const locks = Object.getOwnPropertyDescriptor(navigator, 'locks');
const randomUUID = Object.getOwnPropertyDescriptor(crypto, 'randomUUID');
beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: undefined });
});
afterEach(() => {
  if (locks) Object.defineProperty(navigator, 'locks', locks);
  if (randomUUID) Object.defineProperty(crypto, 'randomUUID', randomUUID);
  else delete (crypto as { randomUUID?: unknown }).randomUUID;
  expect(typeof crypto.randomUUID).toBe('function');
});

describe('browser session outside a secure context', () => {
  it('still logs in, renews and logs out with the same compare-and-set rules', async () => {
    const login = await startBrowserSession('first');
    expect(login.loginId).toMatch(/^[0-9a-f]{32}$/);
    expect(readBrowserSession().token).toBe('first');

    const renewed = await renewBrowserSession(login, 'second', () => true);
    expect(renewed?.generation).toBe(1);
    // A stale expectation never overwrites the renewal.
    expect(await renewBrowserSession(login, 'stale', () => true)).toBeNull();
    expect(await endBrowserSession(login)).toBeNull();
    expect(readBrowserSession().token).toBe('second');

    const ended = await endBrowserSession();
    expect(ended?.token).toBeNull();
    expect(ended?.loginId).not.toBe(login.loginId);
  });

  it('runs updates in order within the tab', async () => {
    const order: string[] = [];
    const login = await startBrowserSession('first');
    await Promise.all([
      renewBrowserSession(login, 'a', () => { order.push('a'); return true; }),
      renewBrowserSession(login, 'b', () => { order.push('b'); return true; }),
    ]);
    expect(order).toEqual(['a', 'b']);
    expect(readBrowserSession().token).toBe('a');
  });
});
