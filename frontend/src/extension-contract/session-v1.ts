/** Browser credential ownership, shared by the host and hosted auth module.
 * This is not authentication: the server still validates every credential.
 * One atomic envelope distinguishes a new login from rotation of its token.
 */
export const SESSION_STORAGE_KEY = "spectra_sherpa_session_v1";
export interface BrowserSession {
  token: string | null;
  loginId: string;
  generation: number;
  transition: "login" | "renew" | "logout";
}

export function readBrowserSession(): BrowserSession {
  const raw = localStorage.getItem(SESSION_STORAGE_KEY);
  if (raw) {
    try {
      const value = JSON.parse(raw) as BrowserSession;
      if ((typeof value.token === "string" || value.token === null) &&
          typeof value.loginId === "string" && value.loginId.length > 0 &&
          Number.isSafeInteger(value.generation) && value.generation >= 0 &&
          ["login", "renew", "logout"].includes(value.transition)) return value;
    } catch { /* Corrupted new-format state must not revive legacy credentials. */ }
    return { token: null, loginId: "invalid", generation: 0, transition: "logout" };
  }
  return { token: localStorage.getItem("token"), loginId: "legacy", generation: 0, transition: "login" };
}

export function sameBrowserSession(a: BrowserSession, b = readBrowserSession()): boolean {
  return a.token === b.token && a.loginId === b.loginId && a.generation === b.generation;
}

export function readBrowserToken(): string | null { return readBrowserSession().token; }

async function serialize<T>(action: () => T): Promise<T> {
  // All supported browsers provide Web Locks. Never emulate cross-tab CAS with
  // an unsafe read/write lock in localStorage.
  if (!navigator.locks) throw new Error("Browser session updates require Web Locks.");
  return navigator.locks.request(SESSION_STORAGE_KEY, action);
}

function persist(session: BrowserSession): BrowserSession {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  // Legacy credentials cease to be authoritative once an envelope exists.
  localStorage.removeItem("token");
  return session;
}

export function startBrowserSession(token: string | null): Promise<BrowserSession> {
  return serialize(() => persist({ token, loginId: crypto.randomUUID(), generation: 0,
    transition: token ? "login" : "logout" })).then(session => {
      window.dispatchEvent(new Event("sherpa-session-changed"));
      return session;
    });
}

export function renewBrowserSession(expected: BrowserSession, token: string,
  stillCurrent: () => boolean): Promise<BrowserSession | null> {
  return serialize(() => {
    if (!stillCurrent() || !sameBrowserSession(expected)) return null;
    return persist({ token, loginId: expected.loginId, generation: expected.generation + 1, transition: "renew" });
  });
}

/** Expire only the rejected session, never a later login or renewal. */
export function endBrowserSession(expected = readBrowserSession()): Promise<BrowserSession | null> {
  return serialize(() => sameBrowserSession(expected)
    ? persist({ token: null, loginId: crypto.randomUUID(), generation: 0, transition: "logout" }) : null);
}
