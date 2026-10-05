/** Read the signed JWT expiry only for user-facing scheduling.
 *
 * Authentication remains server-authoritative; this unverified claim is never
 * used to grant access.  It lets the Workbench warn a scientist before the
 * server-enforced session end interrupts an inspection or edit.
 */
export const jwtExpiryMilliseconds = (token: string | null | undefined): number | null => {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const decoded = JSON.parse(window.atob(padded)) as { exp?: unknown };
    return typeof decoded.exp === "number" && Number.isFinite(decoded.exp)
      ? decoded.exp * 1000
      : null;
  } catch {
    return null;
  }
};

export const sessionExpiryMinutesRemaining = (
  token: string | null | undefined,
  nowMilliseconds = Date.now(),
): number | null => {
  const expiry = jwtExpiryMilliseconds(token);
  return expiry === null ? null : Math.max(0, Math.ceil((expiry - nowMilliseconds) / 60_000));
};
