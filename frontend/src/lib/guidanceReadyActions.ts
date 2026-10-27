// UI availability hints only. Server-owned project progress still decides
// whether Guidance applies; these never grant permission or execute an action.
const STARTER_ACTIONS = ["import_data", "open_analysis_starters"] as const;

export function guidanceReadyActions(root: ParentNode = document): string[] {
  return STARTER_ACTIONS.filter(action =>
    Array.from(root.querySelectorAll<HTMLElement>(`[data-guidance-ready="${action}"]`)).some(element =>
      !element.matches(':disabled, [aria-disabled="true"], [aria-busy="true"]')
      && !element.closest('[hidden], [inert], [aria-hidden="true"]')
      && element.getClientRects().length > 0
      && getComputedStyle(element).visibility !== "hidden",
    ),
  );
}
