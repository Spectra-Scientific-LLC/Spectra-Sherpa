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

let inTab: Promise<unknown> = Promise.resolve();

async function serialize<T>(action: () => T): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request(SESSION_STORAGE_KEY, action);
  }
  // Web Locks exist only in secure contexts, so plain-HTTP access to a local
  // workbench on another address has none. Serialize within this tab and keep
  // every compare-and-set check; never emulate a cross-tab lock in
  // localStorage, which would be unsafe.
  const run = inTab.then(action);
  inTab = run.catch(() => undefined);
  return run;
}

/** randomUUID is also secure-context only; getRandomValues is not. */
function newLoginId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

function persist(session: BrowserSession): BrowserSession {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  // Legacy credentials cease to be authoritative once an envelope exists.
  localStorage.removeItem("token");
  return session;
}

export function startBrowserSession(token: string | null): Promise<BrowserSession> {
  return serialize(() => persist({ token, loginId: newLoginId(), generation: 0,
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
    ? persist({ token: null, loginId: newLoginId(), generation: 0, transition: "logout" }) : null);
}
