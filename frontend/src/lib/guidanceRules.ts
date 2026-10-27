// Keep these labels aligned with the starter rule IDs in
// the guidance rules starter module.
// Each label is the user-facing chip rendered in the notification
// drawer.  Pure function — no internal identifiers should ever leak
// to the UI; any rule_id missing from this map falls through to
// the generic "Guidance" string in the function below.
const GUIDANCE_RULE_LABELS: Record<string, string> = {
  empty_project_import: "Project setup",
  imported_no_preprocess: "Analysis setup",
  workflow_saved_never_run: "Workflow run",
  correction_caveat_ignored: "Data caveat",
  idle_on_results: "Results review",
  data_idle_no_dataset_synthesis: "FTIR synthesis",
  // PR5 — deploy + report rules.
  deploy_runs_no_automation: "Automation",
  report_idle_with_runs: "Reporting",
  // Goal-aware rules follow the project's Starter plan.
  goal_add_data: "Your goal",
  goal_load_data: "Your goal",
  goal_choose_starter: "Your goal",
  goal_open_workflow: "Your goal",
  goal_configure: "Your goal",
  goal_recover_run: "Your goal",
  goal_run_workflow: "Your goal",
  goal_review_results: "Your goal",
};

export function guidanceRuleLabel(ruleId?: string | null): string {
  if (!ruleId) return "Guidance";
  if (ruleId.startsWith("llm_")) return "Guidance insight";
  return GUIDANCE_RULE_LABELS[ruleId] ?? "Guidance";
}
