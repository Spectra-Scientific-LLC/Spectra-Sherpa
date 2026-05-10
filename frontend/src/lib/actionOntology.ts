export interface GuidanceActionMeta {
  actionId: string;
  actionVersion: number;
  route?: string;
  label: string;
  prompt?: string;
  /**
   * Optional scope the route is expected to settle on before any
   * follow-on action (e.g. ``requestAdvisorPrompt``) fires.
   *
   * Without this, prompt-backed actions clicked from the notification
   * drawer can race the destination view's ``onMounted`` advisor
   * scope switch — the prompt lands in the previous tab's topic
   * because ``router.push`` resolves before the new view's async
   * scope assignment completes.  ``runGuidanceAction`` waits up to
   * 2s for ``advisorStore.activeNode`` to match before dispatching.
   */
  expectedScope?: { tabKey: string; subscopeKey: string };
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
    // No ``expectedScope`` here — Experiments has dynamic subscopes
    // (overview / batch_run / compare keyed by active tab).  Live
    // toasts on /experiments don't race because the user is already
    // on the page; notification-drawer clicks from other tabs may
    // race, but landing the prompt in the wrong experiments subscope
    // is less harmful than landing it in a totally different tab —
    // accept the small risk until we have a "wait for any scope in
    // this tab" primitive.
  },
  new_project: { actionId: "new_project", actionVersion: 1, route: "/project", label: "New project" },
  open_workflow: { actionId: "open_workflow", actionVersion: 1, route: "/workflow", label: "Open workflow" },
  create_folder_watch: {
    actionId: "create_folder_watch",
    actionVersion: 1,
    route: "/deploy",
    label: "Create folder watch",
  },
  draft_report_via_advisor: {
    actionId: "draft_report_via_advisor",
    actionVersion: 1,
    route: "/report",
    label: "Draft with Advisor",
    prompt: "Help me draft a short report based on my latest execution run — methods, results, and what to compare next.",
    // ReportContent's onMounted asynchronously runs ``advisorStore.switchScope({ tabKey: "report", subscopeKey: "draft" })``.
    // Without this hint, a notification-drawer click from another tab
    // would race that switch and the prompt would land in the prior
    // scope's topic.
    expectedScope: { tabKey: "report", subscopeKey: "draft" },
  },
};

export function resolveGuidanceAction(actionId?: string | null): GuidanceActionMeta | null {
  if (!actionId) return null;
  return GUIDANCE_ACTIONS[actionId] ?? null;
}
