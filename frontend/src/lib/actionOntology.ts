export interface GuidanceActionMeta {
  actionId: string;
  actionVersion: number;
  route?: string;
  label: string;
  prompt?: string;
}

export const GUIDANCE_ACTIONS: Record<string, GuidanceActionMeta> = {
  import_data: { actionId: "import_data", actionVersion: 1, route: "/data", label: "Import data" },
  add_preprocessing: {
    actionId: "add_preprocessing",
    actionVersion: 1,
    route: "/workflow",
    label: "Add preprocessing",
  },
  run_workflow: { actionId: "run_workflow", actionVersion: 1, route: "/workflow", label: "Run workflow" },
  save_workflow: { actionId: "save_workflow", actionVersion: 1, route: "/workflow", label: "Save workflow" },
  view_results: { actionId: "view_results", actionVersion: 1, route: "/experiments", label: "View results" },
  open_data_explore: {
    actionId: "open_data_explore",
    actionVersion: 1,
    route: "/data",
    label: "Review data",
  },
  open_memory_map: {
    actionId: "open_memory_map",
    actionVersion: 1,
    route: "/project/memory-map",
    label: "Open memory map",
  },
  explain_latest_results: {
    actionId: "explain_latest_results",
    actionVersion: 1,
    route: "/experiments",
    label: "Explain results",
    prompt: "Explain the results of my latest run.",
  },
  new_project: { actionId: "new_project", actionVersion: 1, route: "/project", label: "New project" },
  open_workflow: { actionId: "open_workflow", actionVersion: 1, route: "/workflow", label: "Open workflow" },
};

export function resolveGuidanceAction(actionId?: string | null): GuidanceActionMeta | null {
  if (!actionId) return null;
  return GUIDANCE_ACTIONS[actionId] ?? null;
}
