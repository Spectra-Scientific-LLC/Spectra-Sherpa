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
  expectedScope?: { tabKey: string; subscopeKey?: string };
  /**
   * Optional ``data-action`` value of a button to click after
   * navigation + scope-wait complete.  Used to actually open a
   * modal/dialog the user would otherwise have to find themselves
   * (e.g. "New Project", "New Watch", "Import Data").  Polled for
   * up to 2s; no-op on timeout.
   *
   * Do NOT set ``clickTarget`` for actions whose target executes
   * destructive or side-effectful work (``run_workflow``,
   * ``save_workflow``).  Glow-only is the right pattern for those.
   */
  clickTarget?: string;
}

export const GUIDANCE_ACTIONS: Record<string, GuidanceActionMeta> = {
  import_data: {
    actionId: "import_data",
    actionVersion: 1,
    route: "/data",
    label: "Import data",
    // Open the file-upload dialog after navigating.
    clickTarget: "import_data",
  },
  add_preprocessing: {
    actionId: "add_preprocessing",
    actionVersion: 1,
    route: "/workflow",
    label: "Add preprocessing",
  },
  // run_workflow and save_workflow deliberately have NO clickTarget
  // — auto-clicking them would execute / persist work.  Glow-only.
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
    // Experiments has dynamic subscopes (overview / batch_run /
    // compare keyed by active tab). Wait for the tab to settle, but
    // accept whichever experiments subscope the user lands on.
    expectedScope: { tabKey: "experiments" },
  },
  new_project: {
    actionId: "new_project",
    actionVersion: 1,
    route: "/project",
    label: "New project",
    // Opens the create-project dialog.
    clickTarget: "new_project",
  },
  open_workflow: { actionId: "open_workflow", actionVersion: 1, route: "/workflow", label: "Open workflow" },
  create_folder_watch: {
    actionId: "create_folder_watch",
    actionVersion: 1,
    route: "/deploy",
    label: "Create folder watch",
    // Opens the New-Watch dialog.  With this in place, the
    // deploy_runs_no_automation rule's toast CTA actually does the
    // work the user expects, instead of routing them to a page
    // they're already on.
    clickTarget: "create_folder_watch",
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
