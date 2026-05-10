/**
 * Shared DOM utilities for resolving guidance action targets.
 *
 * Both ``GuidanceGlowOverlay`` (PR2) and ``runGuidanceAction``'s click
 * dispatch (PR6) need to find the same ``[data-action="<id>"]``
 * element after a route change, so the lookup + wait logic lives in
 * one place rather than duplicated.
 *
 * Action ids only — no raw selectors.  This matches the privacy
 * posture of the activity tracker and keeps the surface auditable.
 */

export function findActionTarget(actionId?: string | null): HTMLElement | null {
  if (!actionId) return null;
  // Iterate over ``[data-action]`` elements and compare the
  // attribute value in JS rather than building a CSS attribute
  // selector.  The selector path is cheaper at scale but breaks
  // (SyntaxError) on action ids containing characters CSS treats
  // as special — and actions ids come over the wire, so we don't
  // own the quoting discipline of every future entry.  At ~10
  // tagged buttons per page the iteration cost is negligible.
  const candidates = document.querySelectorAll<HTMLElement>("[data-action]");
  for (const candidate of candidates) {
    if (candidate.getAttribute("data-action") === actionId) {
      return candidate;
    }
  }
  return null;
}

/**
 * Poll for an action target with a hard timeout.  Resolves with the
 * element when it lands in the DOM, or ``null`` on timeout.
 *
 * Used by both (a) glow positioning when the destination view is
 * still mounting after a route change, and (b) ``clickTarget``
 * dispatch which has the same race window.  Polling at 50ms keeps
 * the perceived latency under ~one frame of jank when the target
 * is already there, while still bounding the wait when the view
 * never mounts (network failure, route guard rejection, etc.).
 */
export async function waitForActionTarget(
  actionId: string,
  timeoutMs = 2000,
  pollMs = 50,
): Promise<HTMLElement | null> {
  const start = performance.now();
  while (performance.now() - start < timeoutMs) {
    const target = findActionTarget(actionId);
    if (target) return target;
    await new Promise<void>((resolve) => setTimeout(resolve, pollMs));
  }
  return findActionTarget(actionId);
}
