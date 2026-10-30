import { isAvailableActionTarget } from "@/lib/actionTargets";

// UI availability hints only. Server-owned project progress still decides
// whether Guidance applies; these never grant permission or execute an action.
const STARTER_ACTIONS = ["import_data", "open_analysis_starters", "review_optimization_candidate", "review_optimization_plateau"] as const;

export function guidanceReadyActions(root: ParentNode = document): string[] {
  return STARTER_ACTIONS.filter(action =>
    Array.from(root.querySelectorAll<HTMLElement>(`[data-guidance-ready="${action}"]`)).some(isAvailableActionTarget),
  );
}

// Context is an opaque UI binding, not scientific or execution authority.
export function guidanceReadyContexts(root: ParentNode = document): Record<string, string> {
  return Object.fromEntries(guidanceReadyActions(root).flatMap(action => {
    const target = Array.from(root.querySelectorAll<HTMLElement>(`[data-guidance-ready="${action}"]`)).find(isAvailableActionTarget);
    const context = target?.dataset.guidanceContext;
    return context && context.length <= 1024 ? [[action, context]] : [];
  }));
}
